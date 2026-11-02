# Quant AI Researcher by Harshil Pahuja
"""STEP 3, second half: build the hybrid NIFTY 500 universe v2 from the rules the operator approved on 2026-11-02.

    2017-01-01 .. 2018-12-31 (the gap)   membership from Alpha Lab, each change moved to its NSE effective date as
                                         listed in reports/shift_table_approved.csv (253 changes, all matched);
                                         plus Dalmia Bharat as a flagged fill (NSE lists it, Alpha Lab does not).
    every other date                     the holdings workbook stays primary with its own quarterly semantics (a name
                                         is a member from the snapshot that lists it to the first that does not);
                                         rows the workbook could not map to an ISIN are mapped through the NSE spell
                                         for their symbol (flag holdings_symbol_mapped); Alpha Lab adds a name only
                                         when NSE confirms it was a member on that snapshot date (flag alpha_lab_fill).
                                         Alpha Lab never removes a name.
    truncated workbook pulls             2017-09-30, 2018-06-30, 2018-09-30 all sit inside the gap, so the gap rule
                                         replaces them; step 4 checks those dates against the NSE list.
    point in time                        nothing is filled from a later list: the gap applies each change on its
                                         effective date, and a workbook snapshot applies from its own date.

Keys: the ISIN the Ace panels use (the bridge's ISIN) wherever Ace knows the security; otherwise the NSE ISIN, which
is then a member that cannot be priced (counted, never dropped).

Writes data/processed/universe/
    nifty500_members_v2.parquet          one row per (trading day, member): date, isin, symbol, barrid, source, flags
    nifty500_members_v2_spells.csv       the loader's format: isin, symbol, company_name, start_date, end_date, source
    nse_review_2013-09-27_members.csv    the Sep-2013 NSE review list (the new start rule's first-signal universe)
    reports/shift_table_approved.csv     the approved shift table, as applied
    reports/v1_vs_v2_diff.csv            every (snapshot date, name) where v2 and v1 disagree, with the source
    reports/start_rule_interim_changes.csv  NSE changes effective after the Sep-2013 review and before 2013-12-31
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import al_common as C
from step2_reconcile import al_daily_isin

from ros.data import ace, nifty500

GAP = (pd.Timestamp("2017-01-01"), pd.Timestamp("2018-12-31"))
REVIEW_2013 = pd.Timestamp("2013-09-27")        # NSE semi-annual review effective date, from nifty500_changes.csv
FIRST_SIGNAL = pd.Timestamp("2013-12-31")
APPROVAL = "approved by Harshil Pahuja on 2026-11-02 as presented (253 changes: 191 review, 62 interim)"


def key_map(bridge: pd.DataFrame) -> dict[str, str]:
    """NSE spell ISIN -> the ISIN the Ace panels are keyed by: the bridge's match where there is one, else the single
    master ISIN with the same issuer stem (a face-value change issues a new serial; the master keeps one ISIN)."""
    b = bridge[(bridge["spell_isin"] != "") & (bridge["ISIN"] != "")]
    out = dict(zip(b["spell_isin"], b["ISIN"]))
    sm = ace.security_master()
    master = sm[sm["isin"].notna()].drop_duplicates("isin")
    stems = master.assign(st=master["isin"].str[:9]).groupby("st")["isin"].apply(list)
    for isin in C.read_nse_spells()["isin"].unique():
        if isin not in out and isin not in set(master["isin"]):
            hits = stems.get(isin[:9], [])
            if len(hits) == 1:
                out[isin] = hits[0]
    return out


def main() -> int:
    bridge = pd.read_csv(os.path.join(C.OUT, "barrid_isin_bridge.csv"), skiprows=1, keep_default_na=False,
                         parse_dates=["valid_from", "valid_to"])
    kmap = key_map(bridge)
    spells = C.read_nse_spells()
    spells = spells[spells["entry_type"] != "demerger_placeholder"].copy()
    spells["key"] = spells["isin"].map(lambda i: kmap.get(i, i))
    sm = ace.security_master()
    master = sm[sm["isin"].notna()].drop_duplicates("isin").set_index("isin")
    cal = pd.DatetimeIndex(ace.trading_calendar())
    close = ace.wide("close")

    def nse_on(d: pd.Timestamp) -> pd.DataFrame:
        x = spells[(spells["start_date"] <= d) & (spells["end_date"].isna() | (spells["end_date"] > d))]
        return x.drop_duplicates("key")

    # ---------------------------------------------------------------- workbook (v1) with symbol mapping and fills
    snaps = nifty500.load_snapshots(include_incomplete=True)
    complete = sorted(snaps.groupby("snapshot_date").size().pipe(lambda n: n[n >= nifty500.MIN_COMPLETE]).index)
    spell_by_symbol = spells.sort_values("start_date").drop_duplicates("symbol", keep="last").set_index("symbol")
    al = al_daily_isin()
    al_by_date = {d: g for d, g in al.groupby("date")}
    al_dates = pd.DatetimeIndex(sorted(al_by_date))
    rows_by_snapshot: dict[pd.Timestamp, pd.DataFrame] = {}
    diff = []
    for d in complete:
        d = pd.Timestamp(d)
        x = snaps[snaps["snapshot_date"] == d]
        out = {}
        for r in x.itertuples():
            if r.mapped:
                out[r.isin] = {"symbol": r.symbol, "source": "holdings_v1", "flags": ""}
            elif isinstance(r.symbol, str) and r.symbol in spell_by_symbol.index:
                k = kmap.get(spell_by_symbol.loc[r.symbol, "isin"], spell_by_symbol.loc[r.symbol, "isin"])
                if k not in out:
                    out[k] = {"symbol": r.symbol, "source": "holdings_symbol_mapped", "flags": "isin_from_nse_spell"}
                    diff.append({"date": d.date(), "isin": k, "symbol": r.symbol, "only_in": "v2", "source": "holdings_symbol_mapped"})
            else:
                diff.append({"date": d.date(), "isin": "", "symbol": r.bbg_id, "only_in": "v1_unmapped", "source": "holdings_unmapped_dropped"})
        if not (GAP[0] <= d <= GAP[1]) and d >= al_dates[0]:
            nse = nse_on(d)
            ad = al_dates[al_dates <= d].max()
            a = al_by_date[ad]
            for isin, tick, barrid in zip(a["ISIN"], a["ticker_asof"], a["barrid"]):
                if isin not in out and isin in set(nse["key"]):
                    out[isin] = {"symbol": tick, "source": "alpha_lab_fill", "flags": f"nse_confirmed;al_date={ad.date()};barrid={barrid}"}
                    diff.append({"date": d.date(), "isin": isin, "symbol": tick, "only_in": "v2", "source": "alpha_lab_fill"})
        rows_by_snapshot[d] = pd.DataFrame.from_dict(out, orient="index").rename_axis("isin").reset_index()

    # ---------------------------------------------------------------- the gap: Alpha Lab shifted to NSE dates
    shift = pd.read_csv(os.path.join(C.REPORTS, "shift_table_draft.csv"), skiprows=1, keep_default_na=False,
                        parse_dates=["al_date", "nse_effective", "apply_date"])
    C.write_csv(shift.assign(approval=APPROVAL), os.path.join(C.REPORTS, "shift_table_approved.csv"))
    gap_days = cal[(cal >= GAP[0]) & (cal <= GAP[1])]
    first = al_by_date[al_dates[al_dates <= gap_days[0]].max()]
    cur = {i: {"symbol": t, "source": "alpha_lab_gap", "flags": f"barrid={b}"} for i, t, b in zip(first["ISIN"], first["ticker_asof"], first["barrid"])}
    al_names = al.drop_duplicates("ISIN", keep="last").set_index("ISIN")
    ev = shift[shift["al_date"] > gap_days[0]].sort_values(["apply_date", "type"])
    ev_by_day = {d: g for d, g in ev.groupby("apply_date")}
    dalmia = spells[(spells["symbol"] == "DALMIABHA") & (spells["start_date"] <= GAP[0])]
    assert len(dalmia) == 1, "expected one Dalmia Bharat spell covering 2017-01-02"
    dal_key, dal_end = dalmia["key"].iloc[0], dalmia["end_date"].iloc[0]
    gap_rows = []
    for d in gap_days:
        for e in ev_by_day.get(d, pd.DataFrame()).itertuples():
            if e.type == "entry":
                cur[e.ISIN] = {"symbol": e.ticker, "source": "alpha_lab_gap",
                               "flags": f"shifted_from={e.al_date.date()};{e.kind}" + (";" + e.flag if e.flag else "")
                               + f";barrid={al_names.loc[e.ISIN, 'barrid'] if e.ISIN in al_names.index else ''}"}
            else:
                cur.pop(e.ISIN, None)
        day = {k: dict(v) for k, v in cur.items()}
        if d < dal_end:
            day[dal_key] = {"symbol": "DALMIABHA", "source": "nse_fill", "flags": "dalmia_bharat;nse_lists_it_alpha_lab_does_not"}
        for k, v in day.items():
            gap_rows.append({"date": d, "isin": k, **v})
    gap_df = pd.DataFrame(gap_rows)

    # ---------------------------------------------------------------- daily table: workbook semantics outside the gap
    daily = []
    snap_dates = sorted(rows_by_snapshot)
    for i, d in enumerate(snap_dates):
        nxt = snap_dates[i + 1] if i + 1 < len(snap_dates) else cal[-1] + pd.Timedelta(days=1)
        days = cal[(cal >= d) & (cal < nxt)]
        days = days[(days < GAP[0]) | (days > GAP[1])]
        if len(days) == 0:
            continue
        r = rows_by_snapshot[d].assign(snapshot=d.date())
        daily.append(r.merge(pd.DataFrame({"date": days}), how="cross"))
    v2 = pd.concat(daily + [gap_df], ignore_index=True)
    v2["flags"] = v2["flags"].fillna("")
    v2 = v2.sort_values(["date", "isin"]).reset_index(drop=True)
    assert not v2.duplicated(["date", "isin"]).any()
    # barrid and dated ticker from the bridge where the name is in Alpha Lab
    b = bridge[bridge["ISIN"] != ""]
    v2 = v2.merge(b[["ISIN", "barrid", "ticker", "valid_from", "valid_to"]].rename(columns={"ISIN": "isin"}), on="isin", how="left")
    ok = (v2["date"] >= v2["valid_from"]) & (v2["date"] <= v2["valid_to"])
    v2.loc[~ok, ["barrid", "ticker"]] = None
    v2 = v2.sort_values(["date", "isin", "barrid"]).drop_duplicates(["date", "isin"], keep="first")
    v2 = v2.rename(columns={"ticker": "ticker_asof"}).drop(columns=["valid_from", "valid_to"])
    v2["company_name"] = v2["isin"].map(master["company_name"])
    miss = v2["company_name"].isna()
    v2.loc[miss, "company_name"] = v2.loc[miss, "isin"].map(spells.drop_duplicates("key").set_index("key")["company_name"])
    v2["ace_has_close"] = False
    cols = set(close.columns)
    for isin, g in v2.groupby("isin"):
        if isin in cols:
            v2.loc[g.index, "ace_has_close"] = close[isin].reindex(g["date"]).notna().to_numpy()
    v2 = v2[["date", "isin", "symbol", "ticker_asof", "barrid", "company_name", "source", "flags", "ace_has_close"]]
    os.makedirs(C.OUT, exist_ok=True)
    v2.to_parquet(os.path.join(C.OUT, "nifty500_members_v2.parquet"), index=False)

    # ---------------------------------------------------------------- spells for the loader
    pos = {d: i for i, d in enumerate(cal)}
    sp = []
    for isin, g in v2.groupby("isin"):
        g = g.sort_values("date")
        idx = g["date"].map(pos).to_numpy()
        brk = (idx[1:] != idx[:-1] + 1).nonzero()[0] + 1
        starts = [0, *brk]
        ends = [*brk, len(g)]
        for s, e in zip(starts, ends):
            last = g.iloc[e - 1]
            end = pd.NaT if pos[last["date"]] + 1 >= len(cal) else cal[pos[last["date"]] + 1]
            sp.append({"isin": isin, "symbol": last["symbol"], "company_name": last["company_name"],
                       "start_date": g.iloc[s]["date"].date(), "end_date": end.date() if pd.notna(end) else "",
                       "source": ";".join(sorted(set(g.iloc[s:e]["source"]))), "flags": ";".join(sorted({f for f in g.iloc[s:e]["flags"] if f}))[:200]})
    sp = pd.DataFrame(sp).sort_values(["start_date", "isin"])
    C.write_csv(sp, os.path.join(C.OUT, "nifty500_members_v2_spells.csv"))

    # ---------------------------------------------------------------- v1 vs v2 on every snapshot date and in the gap
    v1 = nifty500.load_membership()
    v1_symbol = dict(zip(v1["isin"], v1["symbol"]))
    for d in [*complete, *pd.DatetimeIndex(gap_days).to_series().groupby(gap_days.to_period("M")).max()]:
        d = pd.Timestamp(d)
        if d < al_dates[0]:
            continue
        a = set(v1.loc[(v1["start_date"] <= d) & (v1["end_date"].isna() | (v1["end_date"] > d)), "isin"])
        dd = cal[cal >= d][0] if d not in pos else d
        bset = v2[v2["date"] == dd]
        bs = dict(zip(bset["isin"], bset["source"]))
        b_symbol = dict(zip(bset["isin"], bset["symbol"]))
        if GAP[0] <= d <= GAP[1]:
            for k in set(bs) - a:
                diff.append({"date": d.date(), "isin": k, "symbol": b_symbol[k], "only_in": "v2", "source": bs[k]})
            for k in a - set(bs):
                diff.append({"date": d.date(), "isin": k, "symbol": v1_symbol.get(k, ""), "only_in": "v1", "source": "removed_in_gap"})
    diff_df = pd.DataFrame(diff).drop_duplicates().sort_values(["date", "only_in", "isin"])
    C.write_csv(diff_df, os.path.join(C.REPORTS, "v1_vs_v2_diff.csv"))

    # ---------------------------------------------------------------- the Sep-2013 review list and the interim changes
    rev = nse_on(REVIEW_2013)[["key", "isin", "symbol", "company_name"]].rename(columns={"key": "isin_key", "isin": "nse_isin"})
    rev["in_ace_master"] = rev["isin_key"].isin(master.index)
    rev = rev.sort_values("symbol")
    C.write_csv(rev, os.path.join(C.OUT, "nse_review_2013-09-27_members.csv"))
    raw = subprocess.run(["git", "show", f"{C.NSE_SPELLS_COMMIT}:data/raw/nifty500/nifty500_changes.csv"], cwd=C.REPO,
                         capture_output=True, check=True).stdout
    ch = pd.read_csv(io.BytesIO(raw), parse_dates=["effective_date"])
    interim = ch[(ch["effective_date"] > REVIEW_2013) & (ch["effective_date"] <= FIRST_SIGNAL) & ch["action"].isin(["IN", "OUT"])]
    C.write_csv(interim, os.path.join(C.REPORTS, "start_rule_interim_changes.csv"))

    n = v2.groupby("date").size()
    print(f"v2 rows {len(v2):,}; dates {v2['date'].min().date()} to {v2['date'].max().date()}; spells {len(sp):,}")
    print("members per day by year (min/max):")
    print(n.groupby(n.index.year).agg(["min", "max", "mean"]).round(1).to_string())
    print("sources:", v2["source"].value_counts().to_dict())
    print("diff rows:", diff_df["only_in"].value_counts().to_dict(), " by source:", diff_df["source"].value_counts().to_dict())
    print(f"Sep-2013 review list: {len(rev)} names, {int(rev['in_ace_master'].sum())} in the Ace master; interim changes to 2013-12-31: {len(interim)}")
    print(interim[["effective_date", "action", "symbol", "company_name"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
