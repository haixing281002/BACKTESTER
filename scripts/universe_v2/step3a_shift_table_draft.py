# Quant AI Researcher by Harshil Pahuja
"""STEP 3, first half: the shift table, for a human to read BEFORE anything is applied. Writes no universe.

For every Alpha Lab membership change in 2017-2018, find the NSE effective date of the same change (git 6e09344 spells):
    review   NSE date falls on an end-March or end-September review (the last trading days of those months, or the first
             days after them)
    interim  NSE date falls elsewhere; the spell's own source names the NSE document
    no_match no NSE change for this name within WINDOW_DAYS; the Alpha Lab date would be kept and flagged
Then measure what the rule would buy: Alpha Lab as is, Alpha Lab shifted, and the current universe (v1), each against NSE
at every trading day of the gap. The two official NSE month-end lists on the Desktop are read as an independent check on
the spells, by symbol, and on nothing else.

Writes data/universe/reports/shift_table_draft.csv, shift_table_summary.csv, shift_residual.csv, gap_accuracy.csv.
"""
from __future__ import annotations

import itertools
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import al_common as C
from step2_reconcile import Nse, al_daily_isin

from ros.data import nifty500

GAP = (pd.Timestamp("2017-01-01"), pd.Timestamp("2018-12-31"))
WINDOW_DAYS = 45


def is_review(d: pd.Timestamp) -> bool:
    return (d.month in (3, 9) and d.day >= 25) or (d.month in (4, 10) and d.day <= 5)


def events(mem: pd.DataFrame) -> pd.DataFrame:
    """Alpha Lab entries and exits by ISIN stem: the first date a name appears or disappears."""
    days = sorted(mem["date"].unique())
    by = mem.groupby("date")["st"].apply(set)
    rows = []
    for prev, d in itertools.pairwise(days):
        for st in by[d] - by[prev]:
            rows.append((pd.Timestamp(d), "entry", st))
        for st in by[prev] - by[d]:
            rows.append((pd.Timestamp(d), "exit", st))
    return pd.DataFrame(rows, columns=["al_date", "type", "st"])


def main() -> int:
    al = al_daily_isin()
    al["st"] = al["ISIN"].str[:9]
    nse = Nse()
    ev = events(al)
    # An Alpha Lab change just after the gap can carry an NSE date inside it (the lag), so look a window past the end.
    ev = ev[(ev["al_date"] >= GAP[0]) & (ev["al_date"] <= GAP[1] + pd.Timedelta(days=WINDOW_DAYS))]
    names = al.sort_values("date").drop_duplicates("st", keep="last").set_index("st")
    rows = []
    for e in ev.itertuples():
        g = nse.by.get(e.st)
        col, src = ("start_date", "start_source") if e.type == "entry" else ("end_date", "end_reason")
        nse_date, doc = None, ""
        if g is not None:
            c = g[g[col].notna()]
            c = c[(c[col] - e.al_date).abs() <= pd.Timedelta(days=WINDOW_DAYS)]
            if len(c):
                best = c.iloc[(c[col] - e.al_date).abs().argsort().iloc[0]]
                nse_date, doc = best[col], best[src]
        kind = "no_match" if nse_date is None else "review" if is_review(nse_date) else "interim"
        rows.append({"al_date": e.al_date.date(), "type": e.type, "ISIN": names.loc[e.st, "ISIN"], "ticker": names.loc[e.st, "ticker_asof"],
                     "nse_effective": nse_date.date() if nse_date is not None else "",
                     "shift_days": (e.al_date - nse_date).days if nse_date is not None else "", "kind": kind,
                     "apply_date": (nse_date if nse_date is not None else e.al_date).date(),
                     "flag": "" if nse_date is not None else "kept_alpha_lab_date", "nse_document": doc})
    t = pd.DataFrame(rows).sort_values(["al_date", "type", "ticker"])
    t = t[pd.to_datetime(t["apply_date"]) <= GAP[1]]
    C.write_csv(t, os.path.join(C.REPORTS, "shift_table_draft.csv"))
    summ = t.groupby(["al_date", "nse_effective", "kind"], dropna=False).agg(
        entries=("type", lambda s: (s == "entry").sum()), exits=("type", lambda s: (s == "exit").sum()),
        shift_days=("shift_days", "first"), example=("ticker", lambda s: ", ".join(list(s)[:4]))).reset_index()
    C.write_csv(summ, os.path.join(C.REPORTS, "shift_table_summary.csv"))

    # What the rule would buy: count of names off NSE on every trading day of the gap
    days = pd.DatetimeIndex(sorted(al.loc[(al["date"] >= GAP[0]) & (al["date"] <= GAP[1]), "date"].unique()))
    start = set(al.loc[al["date"] == days[0], "st"])
    moves = t.assign(st=t["ISIN"].str[:9], apply_date=pd.to_datetime(t["apply_date"]))
    al_by = al.groupby("date")["st"].apply(set)
    v1 = nifty500.load_membership().assign(st=lambda x: x["isin"].str[:9])
    acc, resid = [], []
    cur = set(start)
    applied = moves.sort_values("apply_date")
    i = 0
    rec = applied.to_dict("records")
    for d in days:
        while i < len(rec) and rec[i]["apply_date"] <= d:
            (cur.add if rec[i]["type"] == "entry" else cur.discard)(rec[i]["st"])
            i += 1
        n = nse.on(d)
        v = set(v1.loc[(v1["start_date"] <= d) & (v1["end_date"].isna() | (v1["end_date"] > d)), "st"])
        acc.append({"date": d.date(), "year": d.year, "nse": len(n), "al_raw_n": len(al_by[d]), "al_raw_off": len(al_by[d] ^ n),
                    "al_shifted_n": len(cur), "al_shifted_off": len(cur ^ n), "v1_n": len(v), "v1_off": len(v ^ n)})
        for st in cur - n:
            resid.append({"date": d.date(), "side": "only_al_shifted", "st": st})
        for st in n - cur:
            resid.append({"date": d.date(), "side": "only_nse", "st": st})
    a = pd.DataFrame(acc)
    C.write_csv(a, os.path.join(C.REPORTS, "gap_accuracy.csv"))
    r = pd.DataFrame(resid)
    if len(r):
        sp = nse.s.drop_duplicates("st", keep="last").set_index("st")
        r = r.groupby(["side", "st"]).agg(days=("date", "size"), first=("date", "min"), last=("date", "max")).reset_index()
        r["symbol"] = r["st"].map(sp["symbol"]).fillna(r["st"].map(names["ticker_asof"]))
        r["company"] = r["st"].map(sp["company_name"])
        C.write_csv(r, os.path.join(C.REPORTS, "shift_residual.csv"))

    # Independent check of the spells against the two official NSE lists (by symbol)
    desk = os.path.join(C.HOME, "Desktop")
    pd.set_option("display.width", 200, "display.max_rows", 200, "display.max_colwidth", 60)
    for f, d in (("nifty500_constituents_NSE_2017-09-29.csv", "2017-09-29"), ("nifty500_constituents_NSE_2018-09-28.csv", "2018-09-28")):
        p = os.path.join(desk, f)
        if os.path.exists(p):
            sym = set(pd.read_csv(p, keep_default_na=False)["symbol"])
            dd = pd.Timestamp(d)
            s = nse.s[(nse.s["start_date"] <= dd) & (nse.s["end_date"].isna() | (nse.s["end_date"] > dd))]
            print(f"Official list {d}: {len(sym)} symbols; NSE spells {s['symbol'].nunique()}; only official {sorted(sym - set(s['symbol']))}; "
                  f"only spells {sorted(set(s['symbol']) - sym)}")

    print("\nEvents by kind:", t["kind"].value_counts().to_dict(), " total", len(t))
    print(summ.to_string(index=False))
    print("\nNames off NSE, trading days of the gap:")
    print(a.groupby("year")[["al_raw_off", "al_shifted_off", "v1_off"]].agg(["mean", "median", "max"]).round(1).to_string())
    print("days exact (0 off): AL raw", (a["al_raw_off"] == 0).sum(), " AL shifted", (a["al_shifted_off"] == 0).sum(), " v1", (a["v1_off"] == 0).sum(), " of", len(a))
    print("\nResidual after shifting:")
    print(r.sort_values("days", ascending=False).head(25).to_string(index=False) if len(r) else "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
