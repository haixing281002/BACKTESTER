# Quant AI Researcher by Harshil Pahuja
"""STEP 1: barrid -> ISIN, dated, using the point-in-time ticker. Writes data/universe/barrid_isin_bridge.csv and
reports/bridge_unmatched.csv, reports/bridge_conflicts.csv, reports/bridge_summary.txt.

A row covers one run of one ticker on one barrid. Candidates, each recorded so a human can audit the match:
    nse_spell       the NSE-rebuilt spell for that symbol overlapping the run's dates (git 6e09344)
    ace_master      Ace security master, symbol = ticker_asof
    holdings        NIFTY 500 holdings workbook, symbol = ticker_asof
    latest_ticker   Ace security master, symbol = the barrid's latest ticker (the master holds today's symbols)
    isin_stem       the spell's ISIN is not in the master but one with the same issuer and security class is (first 9
                    characters; a face-value change or scheme issues a new serial)
    barrid_sibling  another run of the same barrid matched, and nothing else did
    nse_spell_not_in_ace  the NSE spell gives the ISIN, but the Ace file has no such security: mapped, and NOT priceable
The ISIN written is the one the Ace panels are keyed by (the master's) wherever one exists, since that is what the universe
must join to. `ace_overlaps_run` says whether Ace actually prices the run's dates: an ISIN alone does not make a name tradable.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import al_common as C

from ros.data import ace, nifty500

OVERLAP_DAYS = 45       # Alpha Lab lags NSE by up to a month, so a spell may sit just outside the run's dates
ORDER = ["nse_spell", "isin_stem", "ace_master", "holdings", "latest_ticker"]
DATED = {"nse_spell", "isin_stem", "ace_master", "holdings"}       # latest_ticker is undated, so it cannot contradict these


def runs(daily: pd.DataFrame) -> pd.DataFrame:
    """One row per consecutive run of a ticker on a barrid (a gap in membership does not break a run)."""
    d = daily.sort_values(["barrid", "date"])
    brk = (d["ticker_asof"] != d.groupby("barrid")["ticker_asof"].shift()).cumsum()
    r = d.groupby(["barrid", brk], sort=False).agg(ticker=("ticker_asof", "first"), valid_from=("date", "min"),
                                                  valid_to=("date", "max"), days=("date", "size"))
    return r.reset_index(level=1, drop=True).reset_index()


def check_names_ever(r: pd.DataFrame, names: pd.DataFrame) -> list[str]:
    """The workbook's undated history must equal the order of the runs built from the CSV."""
    built = r.sort_values(["barrid", "valid_from"]).groupby("barrid")["ticker"].apply(list)
    bad = []
    for _, n in names.iterrows():
        hist = [t.strip() for t in str(n["history"]).split(">")]
        if built.get(n["barrid"]) != hist:
            bad.append(f"{n['barrid']}: workbook {hist} vs csv {built.get(n['barrid'])}")
    return bad


def fact_lines(daily: pd.DataFrame, reb: pd.DataFrame, r: pd.DataFrame, names: pd.DataFrame) -> list[str]:
    """The brief's stated facts about the workbook, tested rather than assumed."""
    by_day = daily.groupby("date")["barrid"].apply(frozenset)
    by_reb = reb.groupby("date")["barrid"].apply(frozenset)
    mismatch = [d for d in by_reb.index if by_day.get(d) != by_reb[d]]
    changed = [d for prev, d in zip(by_day.index, by_day.index[1:]) if by_day[prev] != by_day[d]]
    outside = [d for d in changed if d not in by_reb.index]
    n = by_day.map(len)
    bad = check_names_ever(r, names)
    return [f"Rebalance columns: {len(by_reb)}, {by_reb.index.min().date()} to {by_reb.index.max().date()}",
            f"Rebalance columns whose member set differs from the CSV on that date: {len(mismatch)}",
            (f"Dates the daily member set changes: {len(changed)}; of those NOT a rebalance column: {len(outside)}"
            f" {[str(d.date()) for d in outside[:10]]}"),
            f"2017 names min/max: {n['2017'].min()}/{n['2017'].max()}; 2018: {n['2018'].min()}/{n['2018'].max()}",
            f"Barrids: {r['barrid'].nunique()}; with a ticker change: {(r.groupby('barrid').size() > 1).sum()}",
            f"Names-ever history disagreeing with the CSV's run order: {len(bad)}"] + [f"  {b}" for b in bad[:20]]


def main() -> int:
    daily = C.read_daily()
    reb = C.read_rebalance_membership()
    names = C.read_names_ever()
    r = runs(daily)
    lines = [C.SIGNATURE, "", f"Alpha Lab workbook: {C.AL_XLSX}", f"Row-level CSV (dated tickers): {C.AL_CSV}", ""]
    lines += fact_lines(daily, reb, r, names) + [""]

    sm = ace.security_master()
    master = sm[sm["isin"].notna()]
    by_sym = master[master["nse_symbol"].notna()].groupby("nse_symbol")
    known_isins = set(master["isin"])
    stems = master.assign(st=master["isin"].str[:9]).groupby("st")["isin"].apply(list)
    info = master.drop_duplicates("isin").set_index("isin")
    spells = C.read_nse_spells()
    hold = nifty500.load_snapshots(include_incomplete=True)
    hold = hold[hold["mapped"] & hold["symbol"].notna()].groupby("symbol")["isin"].agg(lambda s: sorted(set(s)))
    latest = names.set_index("barrid")["latest_ticker"]

    def to_key(isin: str, start: str, ticker: str) -> tuple[str | None, str, str]:
        """The Ace-keyed ISIN for an NSE spell's ISIN (face-value splits change an ISIN; the master keeps one)."""
        if isin in known_isins:
            return isin, "", "nse_spell"
        if start in known_isins:
            return start, f"spell isin {isin} not in master; used isin_at_start", "nse_spell"
        if ticker in by_sym.groups:
            return (by_sym.get_group(ticker)["isin"].iloc[0], f"spell isin {isin} not in master; used master isin for {ticker}",
                    "nse_spell")
        hits = stems.get(isin[:9], [])
        if len(hits) == 1:
            return hits[0], f"spell isin {isin} not in master; same issuer stem {hits[0]}", "isin_stem"
        return None, f"spell isin {isin} not in master; no such security in the Ace file", ""

    rows = []
    for x in r.itertuples():
        cands: dict[str, str] = {}
        notes: list[str] = []
        lo, hi = x.valid_from - pd.Timedelta(days=OVERLAP_DAYS), x.valid_to + pd.Timedelta(days=OVERLAP_DAYS)
        sp = spells[(spells["symbol"] == x.ticker) & (spells["start_date"] <= hi)
                    & (spells["end_date"].isna() | (spells["end_date"] >= lo))
                    & (spells["entry_type"] != "demerger_placeholder")]
        raw_isin = ""
        if len(sp):
            s = sp.iloc[(sp["start_date"] - x.valid_from).abs().argsort().iloc[0]]
            raw_isin = s["isin"]
            k, n, how = to_key(s["isin"], s["isin_at_start"], x.ticker)
            if n:
                notes.append(n)
            if k:
                cands[how] = k
        if x.ticker in by_sym.groups:
            g = by_sym.get_group(x.ticker)
            cands["ace_master"] = g["isin"].iloc[0]
            if len(g) > 1:
                notes.append(f"{len(g)} master rows for {x.ticker}")
        if x.ticker in hold.index:
            cands["holdings"] = hold[x.ticker][0]
            if len(hold[x.ticker]) > 1:
                notes.append(f"holdings has {len(hold[x.ticker])} ISINs for {x.ticker}: {hold[x.ticker]}")
        lt = latest.get(x.barrid)
        if lt != x.ticker and lt in by_sym.groups:
            cands["latest_ticker"] = by_sym.get_group(lt)["isin"].iloc[0]
        rows.append({"barrid": x.barrid, "ticker": x.ticker, "valid_from": x.valid_from, "valid_to": x.valid_to,
                     "cands": cands, "notes": notes, "raw_isin": raw_isin})

    # A dated NSE spell outranks an undated symbol lookup; disagreement is recorded, never hidden.
    by_barrid: dict[str, set] = {}
    for row in rows:
        c = row["cands"]
        chosen = next((m for m in ORDER if m in c), None)
        row["ISIN"] = c[chosen] if chosen else None
        row["match_method"] = "+".join(m for m in ORDER if m in c and c[m] == row["ISIN"]) if chosen else ""
        row["conflict"] = "; ".join(f"{m}={c[m]}" for m in ORDER if m in c and m in DATED and c[m] != row["ISIN"])
        if chosen and c.get("latest_ticker", row["ISIN"]) != row["ISIN"]:
            row["notes"].append(f"barrid's latest ticker now maps to {c['latest_ticker']} (later corporate event; undated, not used)")
        if row["ISIN"]:
            by_barrid.setdefault(row["barrid"], set()).add(row["ISIN"])
    for row in rows:
        sib = by_barrid.get(row["barrid"], set())
        if not row["ISIN"] and len(sib) == 1:
            row["ISIN"], row["match_method"] = next(iter(sib)), "barrid_sibling"

    spell_by_stem = spells.assign(st=spells["isin"].str[:9])
    out = []
    for row in rows:
        i = row["ISIN"]
        lo, hi = row["valid_from"] - pd.Timedelta(days=OVERLAP_DAYS), row["valid_to"] + pd.Timedelta(days=OVERLAP_DAYS)
        in_nse = bool(i) and bool(((spell_by_stem["st"] == i[:9]) & (spell_by_stem["start_date"] <= hi)
                                   & (spell_by_stem["end_date"].isna() | (spell_by_stem["end_date"] >= lo))).any())
        if not i and row["raw_isin"]:            # known to NSE, absent from Ace: mapped, and not priceable
            i, row["match_method"], in_nse = row["raw_isin"], "nse_spell_not_in_ace", True
        methods = row["match_method"].split("+") if row["match_method"] else []
        known = i in info.index if i else False
        first = pd.Timestamp(info.loc[i, "first_date"]) if known else pd.NaT
        last = pd.Timestamp(info.loc[i, "last_date"]) if known else pd.NaT
        priced = known and bool(info.loc[i, "in_ace"]) and first <= row["valid_to"] and last >= row["valid_from"]
        if not i:
            conf = "none"
        elif row["conflict"] or (known and not priced) or "barrid_sibling" in methods or (methods == ["latest_ticker"] and not in_nse):
            conf = "low"
        elif "nse_spell" in methods and len(methods) >= 2:
            conf = "high"
        else:
            conf = "medium"
        name = info.loc[i, "company_name"] if known else ""
        if i and not known:
            sn = spells.loc[spells["isin"] == i, "company_name"]
            name = sn.iloc[0] if len(sn) else ""
        out.append({"barrid": row["barrid"], "ticker": row["ticker"], "valid_from": row["valid_from"].date(),
                    "valid_to": row["valid_to"].date(), "ISIN": i or "", "match_method": row["match_method"],
                    "confidence": conf, "accord_code": int(info.loc[i, "accord_code"]) if known else "",
                    "company_name": name, "ace_first": first.date() if known else "", "ace_last": last.date() if known else "",
                    "ace_overlaps_run": priced, "isin_seen_in_nse_spells": in_nse, "conflict": row["conflict"],
                    "spell_isin": row["raw_isin"], "note": "; ".join(row["notes"])})
    b = pd.DataFrame(out).sort_values(["barrid", "valid_from"])
    C.write_csv(b, os.path.join(C.OUT, "barrid_isin_bridge.csv"))
    un = b[b["ISIN"] == ""]
    C.write_csv(un[["barrid", "ticker", "valid_from", "valid_to", "spell_isin", "note"]],
                os.path.join(C.REPORTS, "bridge_unmatched.csv"))
    review = b[(b["conflict"] != "") | (b["confidence"] == "low")]
    C.write_csv(review, os.path.join(C.REPORTS, "bridge_conflicts.csv"))
    unpriced = b[~b["ace_overlaps_run"] & (b["ISIN"] != "")]
    C.write_csv(unpriced[["barrid", "ticker", "valid_from", "valid_to", "ISIN", "company_name", "match_method", "ace_first", "ace_last"]],
                os.path.join(C.REPORTS, "bridge_mapped_but_unpriced.csv"))
    dup = b[b["ISIN"] != ""].groupby("ISIN")["barrid"].nunique()
    lines += [f"Bridge rows: {len(b)}; barrids {b['barrid'].nunique()}",
              f"By confidence: {b['confidence'].value_counts().to_dict()}",
              f"By method: {b['match_method'].value_counts().to_dict()}",
              (f"Unmatched rows: {len(un)}; barrids with no ISIN at all: "
              f"{b.groupby('barrid')['ISIN'].apply(lambda s: (s == '').all()).sum()}"),
              f"Rows with a dated source conflict: {(b['conflict'] != '').sum()}; low confidence: {(b['confidence'] == 'low').sum()}",
              (f"Mapped to an ISIN but no Ace price in the run's dates: {len(unpriced)} rows, {unpriced['barrid'].nunique()} barrids "
              f"(see reports/bridge_mapped_but_unpriced.csv)"),
              f"ISINs reached by more than one barrid: {(dup > 1).sum()}"]
    with open(os.path.join(C.REPORTS, "bridge_summary.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
