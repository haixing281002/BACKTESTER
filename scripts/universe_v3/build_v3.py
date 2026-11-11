# Quant AI Researcher
"""Universe v3: NIFTY 500 membership on NSE's own effective dates for every review and interim change, 2013-2026.

Input (build time only, never read by a run): the NSE-rebuilt membership file built 2026-10-21 from NSE's documents and
checked against 128 NSE snapshots (125 exact; the 3 differences are a symbol a day early or late), its path set by
LIGHTYEAR_NSE_MEMBERSHIP or config/local.yaml key nse_nifty500_membership. Output:

    data/processed/universe/nifty500_members_v3_spells.csv        the spells a run reads (membership_source
                                                                  nifty500_members_v3), keyed by the ISIN Ace uses
    data/processed/universe/reports/v3_daily_recon.csv            every session: members in v3, in v2, only in each
    data/processed/universe/reports/v3_vs_v2_2016Q2.csv           the names that differ 2016-04-01 to 2016-06-29
    data/processed/universe/reports/v3_unmapped.csv               NSE members whose ISIN Ace does not know

Rules: regular entries only (demerger placeholders and temporary spin-off listings are not tradable members); an NSE
ISIN maps to the ISIN Ace uses by its end-of-spell ISIN, then its start-of-spell ISIN (face-value splits), then its NSE
symbol in Ace's master, then a later ISIN the NSE file gives the same company, then the one Ace ISIN with the same issuer
and security type (first nine characters: a face-value split changes only the serial), then the ISIN universe v2
gives that symbol; a member that maps to none of these stays in the
universe under NSE's ISIN (in the index, never priced, never tradable: dropping it would be survivorship bias), and is
listed in v3_unmapped.csv. Spells that touch for one ISIN (a symbol rename) are merged. A member on day d: start_date <= d < end_date.

    python scripts/universe_v3/build_v3.py
"""
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from ros.data import ace, nifty500, sources

SIGNATURE = "Quant AI Researcher"


def write_csv(df: pd.DataFrame, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"# {SIGNATURE}\n")
        df.to_csv(fh, index=False)
    return path


def map_isins(nse: pd.DataFrame, sm: pd.DataFrame, v2: pd.DataFrame | None = None) -> tuple[pd.Series, pd.Series]:
    """(the ISIN to key each row by, how it was mapped)."""
    known = set(sm["isin"].dropna())
    # ISIN changes inside the NSE file (a face-value split): a later row's isin_at_start names the earlier ISIN
    alias = {}
    for r in nse.itertuples():
        if isinstance(r.isin_at_start, str) and r.isin_at_start != r.isin:
            alias[r.isin_at_start] = r.isin
    by_issuer = {}                                   # first 9 characters: country, issuer code, security type
    for i in known:
        by_issuer.setdefault(i[:9], set()).add(i)

    def resolve(i):
        seen = set()
        while isinstance(i, str) and i not in known and i in alias and i not in seen:
            seen.add(i)
            i = alias[i]
        return i if i in known else None

    by_symbol = sm.dropna(subset=["isin", "nse_symbol"]).drop_duplicates("nse_symbol").set_index("nse_symbol")["isin"]
    by_v2 = (v2.drop_duplicates("symbol", keep="last").set_index("symbol")["isin"] if v2 is not None else pd.Series(dtype=str))
    out, how = [], []
    for r in nse.itertuples():
        if r.isin in known:
            out.append(r.isin); how.append("isin")
        elif isinstance(r.isin_at_start, str) and r.isin_at_start in known:
            out.append(r.isin_at_start); how.append("isin_at_start")
        elif resolve(r.isin):
            out.append(resolve(r.isin)); how.append("later ISIN in the NSE file")
        elif isinstance(r.isin, str) and len(by_issuer.get(r.isin[:9], ())) == 1:
            out.append(next(iter(by_issuer[r.isin[:9]]))); how.append("same issuer and security type (face-value change)")
        elif r.symbol in by_symbol.index:
            out.append(by_symbol[r.symbol]); how.append("symbol in Ace master")
        elif r.symbol in by_v2.index:
            out.append(by_v2[r.symbol]); how.append("symbol in universe v2")
        else:
            out.append(r.isin); how.append("unmapped: NSE ISIN kept")
    return pd.Series(out, index=nse.index), pd.Series(how, index=nse.index)


def build_spells(nse: pd.DataFrame, sm: pd.DataFrame, v2: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    nse = nse[nse["entry_type"] == "regular"].copy()
    nse["start_date"] = pd.to_datetime(nse["start_date"])
    nse["end_date"] = pd.to_datetime(nse["end_date"])
    nse["ace_isin"], nse["mapped_by"] = map_isins(nse, sm, v2)
    unmapped = nse[nse["mapped_by"].str.startswith("unmapped")][["symbol", "isin", "isin_at_start", "company_name",
                                                                 "start_date", "end_date"]]
    spells = []
    for isin, g in nse.dropna(subset=["ace_isin"]).sort_values("start_date").groupby("ace_isin"):
        cur = None
        for r in g.itertuples():
            if cur is not None and pd.notna(cur["end_date"]) and r.start_date <= cur["end_date"]:
                cur["end_date"] = r.end_date if pd.isna(r.end_date) else max(cur["end_date"], r.end_date)
                cur["symbol"], cur["flags"] = r.symbol, "renamed" if cur["symbol"] != r.symbol else cur["flags"]
            else:
                if cur is not None:
                    spells.append(cur)
                cur = {"isin": isin, "symbol": r.symbol, "company_name": r.company_name, "start_date": r.start_date,
                       "end_date": r.end_date, "source": "nse_effective_dates", "flags": ""}
        spells.append(cur)
    sp = pd.DataFrame(spells).sort_values(["start_date", "isin"]).reset_index(drop=True)
    return sp, unmapped


def members_on(sp: pd.DataFrame, d: pd.Timestamp) -> set:
    return set(sp[(sp["start_date"] <= d) & (sp["end_date"].isna() | (sp["end_date"] > d))]["isin"])


def daily_recon(v3: pd.DataFrame, v2: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for d in cal:
        a, b = members_on(v3, d), members_on(v2, d)
        rows.append({"date": d.date(), "v3_members": len(a), "v2_members": len(b), "only_in_v3": len(a - b),
                     "only_in_v2": len(b - a)})
    return pd.DataFrame(rows)


def main() -> int:
    src = sources.require(sources.NSE_NIFTY500_MEMBERSHIP, "NSE-rebuilt NIFTY 500 membership file (universe v3 build)")
    nse = pd.read_csv(src, dtype=str, keep_default_na=False).replace("", None)
    sm = ace.security_master()
    v2 = nifty500.load_membership(source="nifty500_members_v2")
    v3, unmapped = build_spells(nse, sm, v2)
    out = os.path.join(sources.PROCESSED_DIR, "universe")
    write_csv(v3.assign(start_date=v3["start_date"].dt.date, end_date=v3["end_date"].dt.date), os.path.join(out, "nifty500_members_v3_spells.csv"))
    write_csv(unmapped, os.path.join(out, "reports", "v3_unmapped.csv"))
    cal = pd.DatetimeIndex(ace.trading_calendar())
    cal = cal[(cal >= v3["start_date"].min()) & (cal <= pd.Timestamp("2026-10-21"))]
    rec = daily_recon(v3, v2, cal)
    write_csv(rec, os.path.join(out, "reports", "v3_daily_recon.csv"))
    q = cal[(cal >= "2016-04-01") & (cal <= "2016-06-29")]
    names = sm.dropna(subset=["isin"]).drop_duplicates("isin").set_index("isin")["nse_symbol"]
    diff = []
    for d in q:
        a, b = members_on(v3, d), members_on(v2, d)
        diff += [{"date": d.date(), "isin": i, "symbol": names.get(i), "in": "v3 only"} for i in sorted(a - b)]
        diff += [{"date": d.date(), "isin": i, "symbol": names.get(i), "in": "v2 only"} for i in sorted(b - a)]
    write_csv(pd.DataFrame(diff), os.path.join(out, "reports", "v3_vs_v2_2016Q2.csv"))
    print(f"v3: {len(v3)} spells, {v3['isin'].nunique()} ISINs, {len(unmapped)} NSE rows kept under NSE's ISIN (unmapped); "
          f"members per session {rec['v3_members'].min()}-{rec['v3_members'].max()} over {len(rec)} sessions")
    q2 = rec[(pd.to_datetime(rec["date"]) >= "2016-04-01") & (pd.to_datetime(rec["date"]) <= "2016-06-29")]
    print(f"2016-04-01 to 06-29 against v2: only in v3 {q2['only_in_v3'].min()}-{q2['only_in_v3'].max()} a day, "
          f"only in v2 {q2['only_in_v2'].min()}-{q2['only_in_v2'].max()} a day")
    other = rec[~rec.index.isin(q2.index)]
    print(f"every other session: only in v3 at most {other['only_in_v3'].max()}, only in v2 at most {other['only_in_v2'].max()}; "
          f"sessions with any difference: {int(((other['only_in_v3'] + other['only_in_v2']) > 0).sum())} of {len(other)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
