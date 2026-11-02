# Quant AI Researcher by Harshil Pahuja
"""STEP 2: Alpha Lab vs the holdings workbook on every holdings snapshot date, with a reason for each difference; and both
against the NSE-rebuilt spells (git 6e09344), used only as a referee. Nothing here changes membership.

Writes data/universe/reports/:
    recon_by_date.csv     one row per snapshot date: counts and reason counts
    recon_by_year.csv     the same summed per year
    recon_detail.csv      one row per differing name per date, with its reason
    recon_unexplained.csv dates with more than ASK_OVER unexplained names (these go to a human)
    al_vs_nse_monthly.csv Alpha Lab vs NSE at each month end, to measure the source itself
    hold_vs_nse.csv       holdings vs NSE at each snapshot date
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import al_common as C

from ros.data import nifty500

ASK_OVER = 5                # the brief: ask about any unexplained difference over 5 names on a date
LAG_DAYS = 45               # Alpha Lab's known lag is up to a month; a little slack for the batch date
STALE_DAYS = 100            # a quarterly snapshot can trail or lead NSE's effective date by up to a quarter


def stem(isin: str) -> str:
    """Issuer + security class. Compares securities across a face-value ISIN change."""
    return isin[:9]


def al_daily_isin() -> pd.DataFrame:
    """date, barrid, ticker_asof, ISIN for every Alpha Lab row, through the dated bridge."""
    b = pd.read_csv(os.path.join(C.OUT, "barrid_isin_bridge.csv"), skiprows=1, parse_dates=["valid_from", "valid_to"],
                    keep_default_na=False)
    d = C.read_daily().merge(b[["barrid", "ticker", "valid_from", "valid_to", "ISIN", "ace_overlaps_run"]],
                             left_on=["barrid", "ticker_asof"], right_on=["barrid", "ticker"])
    d = d[(d["date"] >= d["valid_from"]) & (d["date"] <= d["valid_to"])]
    return d[["date", "barrid", "ticker_asof", "ISIN", "ace_overlaps_run"]]


class Nse:
    """Who NSE says was a member, and when each spell started and ended, by ISIN stem."""

    def __init__(self):
        s = C.read_nse_spells()
        # One company, two ISINs: where the bridge keyed a run to a different issuer's ISIN than the NSE spell (a merger
        # into a new listing, e.g. TECHNO), compare on the bridge's key so a key difference is not reported as membership.
        b = pd.read_csv(os.path.join(C.OUT, "barrid_isin_bridge.csv"), skiprows=1, keep_default_na=False)
        b = b[(b["spell_isin"] != "") & (b["ISIN"] != "") & (b["spell_isin"].str[:9] != b["ISIN"].str[:9])]
        self.alias = dict(zip(b["spell_isin"].str[:9], b["ISIN"].str[:9]))
        st = s["isin"].str[:9].map(lambda x: self.alias.get(x, x))
        self.s = s[s["entry_type"] != "demerger_placeholder"].assign(st=st)
        self.by = {k: g for k, g in self.s.groupby("st")}

    def on(self, d: pd.Timestamp) -> set:
        x = self.s
        return set(x.loc[(x["start_date"] <= d) & (x["end_date"].isna() | (x["end_date"] > d)), "st"])

    def is_member(self, st: str, d: pd.Timestamp) -> bool:
        g = self.by.get(st)
        return g is not None and bool(((g["start_date"] <= d) & (g["end_date"].isna() | (g["end_date"] > d))).any())

    def days_since_exit(self, st: str, d: pd.Timestamp) -> int | None:
        g = self.by.get(st)
        if g is None:
            return None
        e = g["end_date"].dropna()
        e = e[e <= d]
        return int((d - e.max()).days) if len(e) else None

    def days_to_entry(self, st: str, d: pd.Timestamp) -> int | None:
        g = self.by.get(st)
        if g is None:
            return None
        e = g["start_date"][g["start_date"] > d]
        return int((e.min() - d).days) if len(e) else None


def holdings_on(snaps: pd.DataFrame, d: pd.Timestamp, spell_by_symbol: dict) -> tuple[dict, list]:
    """ISIN -> symbol for a snapshot; a row with no ISIN is mapped through the NSE spell for its symbol when it has one.
    Returns (members, ids with neither an ISIN nor a usable symbol)."""
    x = snaps[snaps["snapshot_date"] == d]
    out, lost = {}, []
    for r in x.itertuples():
        if r.mapped:
            out[r.isin] = r.symbol
        elif isinstance(r.symbol, str) and r.symbol in spell_by_symbol:
            out[spell_by_symbol[r.symbol]] = r.symbol
        else:
            lost.append(r.bbg_id)
    return out, lost


def main() -> int:
    al = al_daily_isin()
    al_dates = pd.DatetimeIndex(sorted(al["date"].unique()))
    nse = Nse()
    snaps = nifty500.load_snapshots(include_incomplete=True)
    sizes = snaps.groupby("snapshot_date").size()
    spell_by_symbol = nse.s.drop_duplicates("symbol", keep="last").set_index("symbol")["isin"].to_dict()
    al_sets = {d: g for d, g in al.groupby("date")}
    first_al = {}
    for st, g in al.assign(st=al["ISIN"].str[:9].map(lambda x: nse.alias.get(x, x))).groupby("st"):
        first_al[st] = pd.DatetimeIndex(sorted(g["date"].unique()))

    def al_adds_within(st: str, d: pd.Timestamp, days: int) -> bool:
        a = first_al.get(st)
        return a is not None and bool(((a > d) & (a <= d + pd.Timedelta(days=days))).any())

    summary, detail = [], []
    for d in sorted(snaps["snapshot_date"].unique()):
        d = pd.Timestamp(d)
        if d < al_dates[0]:
            continue
        ad = al_dates[al_dates <= d].max()
        a = al_sets[ad]
        a_map = dict(zip(a["ISIN"], a["ticker_asof"]))
        h_map, lost = holdings_on(snaps, d, spell_by_symbol)
        truncated = sizes[d] < nifty500.MIN_COMPLETE
        # compare on the stem so a face-value ISIN change is not reported as two different names
        a_st = {nse.alias.get(stem(i), stem(i)): i for i in a_map}
        h_st = {nse.alias.get(stem(i), stem(i)): i for i in h_map}
        only_a, only_h = set(a_st) - set(h_st), set(h_st) - set(a_st)
        nse_now = nse.on(d)
        reasons: dict[str, int] = {}

        def note(side: str, st: str, isin: str, tick: str, why: str) -> None:
            reasons[why] = reasons.get(why, 0) + 1
            detail.append({"date": d.date(), "side": side, "ISIN": isin, "ticker": tick, "reason": why})

        for st in sorted(only_a):
            if truncated:
                why = "existing: truncated snapshot"
            elif nse.is_member(st, d):
                why = "existing: mapping (an unmapped Bloomberg id here)" if lost else "existing: missing a name NSE lists"
            else:
                ex, en = nse.days_since_exit(st, d), nse.days_to_entry(st, d)
                if ex is not None and ex <= LAG_DAYS:
                    why = "timing: Alpha Lab lag, NSE already removed it"
                elif en is not None and en <= LAG_DAYS:
                    why = "timing: Alpha Lab ahead of NSE"
                elif st not in nse.by:
                    why = "unexplained: Alpha Lab name unknown to NSE spells"
                else:
                    why = "unexplained: Alpha Lab lists it, NSE and existing do not"
            note("only_alpha_lab", st, a_st[st], a_map[a_st[st]], why)
        for st in sorted(only_h):
            if nse.is_member(st, d):
                why = "timing: Alpha Lab lag, entry not yet applied" if al_adds_within(st, d, LAG_DAYS) \
                    else "alpha_lab: missing a name NSE lists"
            else:
                ex, en = nse.days_since_exit(st, d), nse.days_to_entry(st, d)
                if ex is not None and ex <= STALE_DAYS:
                    why = "timing: existing trails NSE, already removed"
                elif en is not None and en <= STALE_DAYS:
                    why = "timing: existing ahead of NSE, entry follows"
                elif st not in nse.by:
                    why = "unexplained: existing name unknown to NSE spells"
                else:
                    why = "unexplained: existing lists it, NSE and Alpha Lab do not"
            note("only_existing", st, h_st[st], h_map[h_st[st]], why)
        unexpl = sum(v for k, v in reasons.items() if k.startswith("unexplained"))
        summary.append({"date": d.date(), "year": d.year, "al_date_used": ad.date(), "existing_rows": int(sizes[d]),
                        "existing_truncated": bool(truncated), "existing_mapped": len(h_map), "existing_lost_ids": len(lost),
                        "alpha_lab": len(a_map), "overlap": len(set(a_st) & set(h_st)), "only_alpha_lab": len(only_a),
                        "only_existing": len(only_h), "nse_members": len(nse_now),
                        "existing_vs_nse_off": len(set(h_st) ^ nse_now), "alpha_lab_vs_nse_off": len(set(a_st) ^ nse_now),
                        "unexplained": unexpl, "reasons": "; ".join(f"{k} = {v}" for k, v in sorted(reasons.items()))})
    s = pd.DataFrame(summary)
    det = pd.DataFrame(detail)
    C.write_csv(s, os.path.join(C.REPORTS, "recon_by_date.csv"))
    C.write_csv(det, os.path.join(C.REPORTS, "recon_detail.csv"))
    y = s.groupby("year").agg(dates=("date", "size"), truncated=("existing_truncated", "sum"), overlap_min=("overlap", "min"),
                              overlap_max=("overlap", "max"), only_al_mean=("only_alpha_lab", "mean"), only_al_max=("only_alpha_lab", "max"),
                              only_existing_mean=("only_existing", "mean"), only_existing_max=("only_existing", "max"),
                              existing_vs_nse_mean=("existing_vs_nse_off", "mean"), existing_vs_nse_max=("existing_vs_nse_off", "max"),
                              al_vs_nse_mean=("alpha_lab_vs_nse_off", "mean"), al_vs_nse_max=("alpha_lab_vs_nse_off", "max"),
                              unexplained_total=("unexplained", "sum")).round(1).reset_index()
    C.write_csv(y, os.path.join(C.REPORTS, "recon_by_year.csv"))
    ask = det[det["reason"].str.startswith("unexplained")].groupby("date").size()
    ask = ask[ask > ASK_OVER]
    C.write_csv(det[det["date"].isin(ask.index) & det["reason"].str.startswith("unexplained")],
                os.path.join(C.REPORTS, "recon_unexplained.csv"))

    # Alpha Lab vs NSE at each month end: the source itself, including every month of the gap
    rows = []
    for me in al_dates.to_series().groupby(al_dates.to_period("M")).max():
        a = {nse.alias.get(stem(i), stem(i)): t for i, t in zip(al_sets[me]["ISIN"], al_sets[me]["ticker_asof"])}
        n = nse.on(me)
        rows.append({"date": me.date(), "year": me.year, "alpha_lab": len(a), "nse": len(n), "overlap": len(set(a) & n),
                     "only_alpha_lab": len(set(a) - n), "only_nse": len(n - set(a)), "off": len(set(a) ^ n)})
    m = pd.DataFrame(rows)
    C.write_csv(m, os.path.join(C.REPORTS, "al_vs_nse_monthly.csv"))

    pd.set_option("display.width", 200, "display.max_rows", 300, "display.max_colwidth", 120)
    print(y.to_string(index=False))
    print()
    print(s[["date", "existing_rows", "existing_truncated", "alpha_lab", "overlap", "only_alpha_lab", "only_existing",
             "existing_vs_nse_off", "alpha_lab_vs_nse_off", "unexplained"]].to_string(index=False))
    print("\nReason totals:\n", det["reason"].value_counts().to_string())
    print("\nDates with more than", ASK_OVER, "unexplained:", ask.to_dict())
    print("\nAlpha Lab vs NSE at month ends, by year:")
    print(m.groupby("year")[["only_alpha_lab", "only_nse", "off"]].agg(["mean", "max"]).round(1).to_string())
    print("\nGap months:")
    print(m[(m["year"] >= 2017) & (m["year"] <= 2018)][["date", "alpha_lab", "nse", "only_alpha_lab", "only_nse", "off"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
