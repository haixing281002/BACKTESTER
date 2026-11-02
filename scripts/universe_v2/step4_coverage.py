# Quant AI Researcher by Harshil Pahuja
"""STEP 4: what the v2 universe covers, with "100%" defined and never rounded up.

For every NSE review date (end-March / end-September effective dates, plus the Sep-2013 review that starts the new
rule) and for every year: members, ISIN-mapped, Ace-priced on the day, unpriced names by name. v1 beside v2, so the
2017-2018 gap and the early unmapped names can be read off directly. Also:
    * the gap dates 2017-09-29, 2018-06-29, 2018-09-28 (the workbook's truncated pulls) against the NSE list
    * the Sep-2013 review list's warm-up: closes in the 100 and 200 sessions before 2013-12-31 for every member
    * a price-history splice check for every bridge row that mapped through an ISIN stem (a new ISIN serial for the
      same issuer): coverage inside the membership spell, gaps and jumps inside it, and what sits after it

Writes data/processed/universe/reports/ coverage_by_review_date.csv, coverage_by_year.csv, unpriced_members.csv,
truncated_dates_vs_nse.csv, start_rule_warmup.csv, splice_check.csv, coverage_summary.md.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import al_common as C
from step3b_build_v2 import FIRST_SIGNAL, REVIEW_2013, key_map

from ros.data import ace, nifty500

FFILL_LIMIT = 5          # the Clenow script carries a stale close at most this many sessions


def review_dates(cal: pd.DatetimeIndex, first: pd.Timestamp, last: pd.Timestamp) -> list[pd.Timestamp]:
    """The first trading day on or after each NSE semi-annual review (31 March / 30 September effective dates)."""
    out = []
    for y in range(first.year, last.year + 1):
        for m, d in ((3, 31), (9, 30)):
            t = pd.Timestamp(y, m, d)
            if first <= t <= last:
                out.append(cal[cal >= t][0])
    return out


def main() -> int:
    v2 = pd.read_parquet(os.path.join(C.OUT, "nifty500_members_v2.parquet"))
    v1 = nifty500.load_membership()
    cal = pd.DatetimeIndex(ace.trading_calendar())
    close = ace.wide("close")
    filled = close.ffill(limit=FFILL_LIMIT)
    cols = set(close.columns)
    sm = ace.security_master()
    master = sm[sm["isin"].notna()].drop_duplicates("isin").set_index("isin")
    bridge = pd.read_csv(os.path.join(C.OUT, "barrid_isin_bridge.csv"), skiprows=1, keep_default_na=False,
                         parse_dates=["valid_from", "valid_to"])
    spells = C.read_nse_spells()
    spells = spells[spells["entry_type"] != "demerger_placeholder"].copy()
    kmap = key_map(bridge)
    spells["key"] = spells["isin"].map(lambda i: kmap.get(i, i))

    def v1_on(d):
        return set(v1.loc[(v1["start_date"] <= d) & (v1["end_date"].isna() | (v1["end_date"] > d)), "isin"])

    def nse_on(d):
        x = spells[(spells["start_date"] <= d) & (spells["end_date"].isna() | (spells["end_date"] > d))]
        return set(x["key"])

    by_day = {d: g for d, g in v2.groupby("date")}
    px_day = filled

    def priced(isins, d):
        row = px_day.loc[d] if d in px_day.index else None
        return {i for i in isins if i in cols and row is not None and pd.notna(row[i])}

    # ---------------------------------------------------------------- per review date
    rows, unpriced = [], []
    dates = [cal[cal >= REVIEW_2013][0], *review_dates(cal, pd.Timestamp("2013-12-31"), v2["date"].max())]
    for d in dates:
        g = by_day[d]
        mem = set(g["isin"])
        mapped = {i for i in mem if i in master.index}
        pr = priced(mem, d)
        v1m = v1_on(d)
        nse = nse_on(d)
        src = g["source"].value_counts().to_dict()
        rows.append({"review_date": d.date(), "members_v2": len(mem), "isin_in_ace_master": len(mapped),
                     "isin_nse_only": len(mem - mapped), "ace_priced": len(pr), "unpriced": len(mem - pr),
                     "members_v1": len(v1m), "v1_priced": len(priced(v1m, d)), "nse_members": len(nse),
                     "v2_vs_nse_off": len(mem ^ nse), "v1_vs_nse_off": len(v1m ^ nse),
                     "sources": "; ".join(f"{k}={v}" for k, v in sorted(src.items())),
                     "unpriced_names": ", ".join(sorted(g.loc[~g["isin"].isin(pr), "symbol"].astype(str)))})
        for r in g[~g["isin"].isin(pr)].itertuples():
            unpriced.append({"review_date": d.date(), "isin": r.isin, "symbol": r.symbol, "company_name": r.company_name,
                             "source": r.source, "in_ace_master": r.isin in master.index,
                             "ace_first": master.loc[r.isin, "first_date"] if r.isin in master.index else "",
                             "ace_last": master.loc[r.isin, "last_date"] if r.isin in master.index else ""})
    by_review = pd.DataFrame(rows)
    C.write_csv(by_review, os.path.join(C.REPORTS, "coverage_by_review_date.csv"))
    un = pd.DataFrame(unpriced)
    C.write_csv(un, os.path.join(C.REPORTS, "unpriced_members.csv"))

    # ---------------------------------------------------------------- per year, every trading day
    v2 = v2[v2["date"] >= pd.Timestamp("2013-06-03")]
    daily = v2.groupby("date").agg(members=("isin", "size"), priced=("ace_has_close", "sum"))
    # a name is "priced" for the engine when a close exists within the carry limit; ace_has_close is the strict same-day flag
    daily["priced_ffill"] = [len(priced(set(by_day[d]["isin"]), d)) for d in daily.index]
    yr = daily.groupby(daily.index.year).agg(days=("members", "size"), members_min=("members", "min"), members_max=("members", "max"),
                                             priced_min=("priced_ffill", "min"), priced_max=("priced_ffill", "max"),
                                             priced_mean=("priced_ffill", "mean")).round(1)
    yr["unpriced_mean"] = (yr["members_max"] - yr["priced_mean"]).round(1)
    v1_daily = []
    for d in daily.index:
        m = v1_on(d)
        v1_daily.append((d, len(m), len(priced(m, d))))
    v1d = pd.DataFrame(v1_daily, columns=["date", "v1_members", "v1_priced"]).set_index("date")
    yr["v1_members_min"] = v1d["v1_members"].groupby(v1d.index.year).min()
    yr["v1_priced_mean"] = v1d["v1_priced"].groupby(v1d.index.year).mean().round(1)
    unp_names = {}
    for y, g in v2.groupby(v2["date"].dt.year):
        bad = g[~g["ace_has_close"]].groupby("isin")["symbol"].first()
        # count a name as unpriced in a year only when it has no close at all that year
        has = g.groupby("isin")["ace_has_close"].any()
        unp_names[y] = ", ".join(sorted(str(bad[i]) for i in has[~has].index))
    yr["unpriced_all_year"] = pd.Series(unp_names)
    yr = yr.reset_index().rename(columns={"date": "year"})
    C.write_csv(yr, os.path.join(C.REPORTS, "coverage_by_year.csv"))

    # ---------------------------------------------------------------- member counts that are not 500/501, with a reason
    n = v2[v2["date"] >= pd.Timestamp("2014-01-01")].groupby("date").size()
    odd = n[~n.isin([500, 501])]
    exc = []
    if len(odd):
        runs = (odd.index.to_series().diff().dt.days > 10).cumsum()
        for _, g in odd.groupby(runs):
            for k, gg in g.groupby(g.values):
                reason = ("holdings workbook snapshot 2026-05-31 lists 504 names; NSE's own list on 2026-05-02 had 504 "
                          "(demerger placeholders), see nifty500_validation.csv at git 6e09344" if k > 501 else "unexplained")
                exc.append({"from": gg.index.min().date(), "to": gg.index.max().date(), "count": int(k), "days": len(gg), "reason": reason})
    C.write_csv(pd.DataFrame(exc, columns=["from", "to", "count", "days", "reason"]), os.path.join(C.OUT, "member_count_exceptions.csv"))

    # ---------------------------------------------------------------- the workbook's truncated pulls, in the gap
    tr = []
    for d in (pd.Timestamp("2017-09-29"), pd.Timestamp("2018-06-29"), pd.Timestamp("2018-09-28")):
        mem, nse = set(by_day[d]["isin"]), nse_on(d)
        tr.append({"date": d.date(), "v2_members": len(mem), "nse_members": len(nse), "only_v2": ", ".join(sorted(mem - nse)),
                   "only_nse": ", ".join(sorted(nse - mem)), "v1_members": len(v1_on(d))})
    tr = pd.DataFrame(tr)
    C.write_csv(tr, os.path.join(C.REPORTS, "truncated_dates_vs_nse.csv"))

    # ---------------------------------------------------------------- start rule: warm-up before the first signal
    rev = pd.read_csv(os.path.join(C.OUT, "nse_review_2013-09-27_members.csv"), skiprows=1, keep_default_na=False)
    before = cal[cal <= FIRST_SIGNAL]
    w100, w200 = before[-100:], before[-200:]
    wr = []
    for r in rev.itertuples():
        i = r.isin_key
        c100 = int(close[i].reindex(w100).notna().sum()) if i in cols else 0
        c200 = int(close[i].reindex(w200).notna().sum()) if i in cols else 0
        f100 = int(filled[i].reindex(w100).notna().sum()) if i in cols else 0
        wr.append({"symbol": r.symbol, "isin": i, "company_name": r.company_name, "closes_last_100": c100,
                   "closes_last_100_carried": f100, "closes_last_200": c200, "priced_on_signal": bool(i in cols and pd.notna(filled.loc[FIRST_SIGNAL, i])),
                   "warmup_ok": f100 >= 100})
    wr = pd.DataFrame(wr).sort_values(["warmup_ok", "closes_last_100", "symbol"])
    C.write_csv(wr, os.path.join(C.REPORTS, "start_rule_warmup.csv"))

    # ---------------------------------------------------------------- splice check for stem matches
    sc = []
    for b in bridge[bridge["match_method"].str.contains("isin_stem") | (bridge["ticker"] == "DHFL")].itertuples():
        i = b.ISIN
        if i not in cols:
            sc.append({"ticker": b.ticker, "isin": i, "company_name": b.company_name, "verdict": "no Ace series"})
            continue
        s = close[i]
        inside = s.loc[b.valid_from:b.valid_to]
        n_in, have = len(inside), int(inside.notna().sum())
        d_in = inside.dropna()
        gaps = d_in.index.to_series().diff().dt.days
        jumps = d_in.pct_change().abs()
        after = s.loc[b.valid_to + pd.Timedelta(days=1):].dropna()
        later_jump = ""
        if len(after) and len(d_in):
            g = (after.index[0] - d_in.index[-1]).days
            if g > 60:
                later_jump = f"relisting {g} days later at {after.iloc[0]:.1f} vs {d_in.iloc[-1]:.1f} last in spell"
        ok = have >= 0.9 * n_in and (gaps.max() if len(gaps) else 0) <= 20 and (jumps.max() if len(jumps) else 0) <= 0.4
        sc.append({"ticker": b.ticker, "isin": i, "company_name": b.company_name, "spell_from": b.valid_from.date(), "spell_to": b.valid_to.date(),
                   "sessions_in_spell": n_in, "closes_in_spell": have, "max_gap_days_in_spell": int(gaps.max()) if len(gaps) else 0,
                   "max_abs_move_in_spell": round(float(jumps.max()), 3) if len(jumps) else 0.0, "after_spell": later_jump,
                   "verdict": "clean inside the spell" if ok else "CHECK"})
    sc = pd.DataFrame(sc)
    C.write_csv(sc, os.path.join(C.REPORTS, "splice_check.csv"))

    # ---------------------------------------------------------------- summary
    first_rev = by_review.iloc[0]
    lines = ["# NIFTY 500 universe v2: coverage report", "", C.SIGNATURE, "",
             (f"Built {pd.Timestamp.now(tz='Asia/Kolkata').isoformat(timespec='minutes')} from the holdings workbook, the Alpha Lab "
             f"pull of 2026-10-30 and the NSE-rebuilt spells (git {C.NSE_SPELLS_COMMIT})."), "",
             "## Definition of 100%", "",
             ("A date is 100% covered when every NSE member on that date is in the universe (members = NSE count), every member "
             "has an ISIN, and every member has an Ace close within the engine's 5-session carry. The last condition is NOT met "
             "on any date before 2022: the names below are in the universe and cannot be traded. Nothing is rounded up."), "",
             "## By review date", "",
             C.md_table(by_review[["review_date", "members_v2", "isin_in_ace_master", "isin_nse_only", "ace_priced", "unpriced", "members_v1",
                                   "v1_priced", "nse_members", "v2_vs_nse_off", "v1_vs_nse_off"]]), "",
             "## By year (every trading day)", "",
             C.md_table(yr[["year", "days", "members_min", "members_max", "priced_min", "priced_max", "priced_mean", "unpriced_mean",
                            "v1_members_min", "v1_priced_mean"]]), "",
             "## The workbook's truncated pulls", "", C.md_table(tr[["date", "v2_members", "nse_members", "only_v2", "only_nse", "v1_members"]]), "",
             "## Unpriced members (in the universe, cannot be traded)", "",
             C.md_table(un.groupby(["symbol", "isin", "company_name"]).agg(first=("review_date", "min"), last=("review_date", "max"),
                                                                            dates=("review_date", "size")).reset_index()), "",
             "## Start rule warm-up (Sep-2013 review list before the 2013-12-31 signal)", "",
             (f"{int(wr['warmup_ok'].sum())} of {len(wr)} members have 100 carried closes in the 100 sessions before the signal; "
             f"{int(wr['priced_on_signal'].sum())} are priced on the signal day. Members short of warm-up:"), "",
             C.md_table(wr[~wr["warmup_ok"]][["symbol", "isin", "company_name", "closes_last_100", "closes_last_200", "priced_on_signal"]]), "",
             "## Price-history splice check (ISIN-stem matches and DHFL)", "", C.md_table(sc), "",
             "## Note for Rohit", "",
             ("The folder 'Rohit Rakhecha - Adjusted Prices' is empty on this machine. The names listed as unpriced above are in the "
             "universe but have no price in the Ace file for the dates they were index members, so a backtest can neither buy nor hold "
             "them; most are companies that later failed. Price history for them is the only fix for the remaining survivorship bias.")]
    with open(os.path.join(C.REPORTS, "coverage_summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines[:60]))
    print("...")
    print(f"first review date {first_rev['review_date']}: {first_rev['members_v2']} members, {first_rev['ace_priced']} priced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
