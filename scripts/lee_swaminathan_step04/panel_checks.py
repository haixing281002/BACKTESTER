"""Step 04 checks for the Lee & Swaminathan card, on the bhavcopy + Screener panel.

Two sources only. Reads cache/ (bhavcopy) and data/raw/master/bhavcopy_screener_panel.csv.
Writes one JSON with: universe size, delisted names, turnover coverage, the corporate-action
heuristic's footprint, and a COUNT-ONLY look at the sort's extreme cells (no outcome returns).

usage: python scripts/lee_swaminathan_step04/panel_checks.py out.json
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ros.data.nse_bhavcopy_ingest import (build_adjusted_prices, combine_cache, dedupe_rows,  # noqa: E402
                                          link_isins)

PANEL = "data/raw/master/bhavcopy_screener_panel.csv"
J_DAYS = 126
MIN_CELL = 15
out = {}

# ---------------------------------------------------------------- A. universe and delisting
p = pd.read_csv(PANEL, parse_dates=["date"])
u = p[p["in_universe"] == 1]
per_day = u.groupby("date").size()
out["A_universe_names_per_day_min_max"] = [int(per_day.min()), int(per_day.max())]
out["A_entities_total"] = int(p["security_id"].nunique())
out["A_entities_ever_in_universe"] = int(u["security_id"].nunique())
last = p.groupby("security_id")["date"].max()
end = p["date"].max()
gone = last[last < end - pd.Timedelta(days=10)]
ever = set(u["security_id"].unique())
out["A_entities_stopped_trading_before_end"] = int(len(gone))
out["A_stopped_trading_and_ever_in_universe"] = int(sum(1 for e in gone.index if e in ever))
out["A_stopped_by_year"] = {str(y): int(n) for y, n in gone.dt.year.value_counts().sort_index().items()}

# ---------------------------------------------------------------- B. turnover coverage
have = u["turnover_window"].notna()
out["B_universe_stock_days"] = int(len(u))
out["B_share_with_turnover"] = round(float(have.mean()), 4)
by_q = u.assign(q=u["date"].dt.to_period("Q"), h=have).groupby("q")["h"].mean().round(3)
out["B_share_with_turnover_by_quarter_min_max"] = [float(by_q.min()), float(by_q.max())]
miss = u[~have].groupby("security_id").size()
out["B_entities_with_no_turnover_in_universe"] = int(u.groupby("security_id")["turnover_window"].apply(lambda s: s.notna().sum() == 0).sum())

# ---------------------------------------------------------------- C. corporate-action heuristic footprint
df = dedupe_rows(combine_cache("cache"))
links = link_isins(df)
adj = build_adjusted_prices(df, links)
ev = adj.ca_events.copy()
out["C_neutralised_days_total"] = int(len(ev))
if len(ev):
    out["C_neutralised_down_lt_0.72"] = int((ev["raw_gross_return"] < 0.72).sum())
    out["C_neutralised_up_gt_1.40"] = int((ev["raw_gross_return"] > 1.40).sum())
    sym = df.assign(ENT=df["ISIN"].map(links.isin_to_entity)).sort_values("DATE").groupby("ENT")["SYMBOL"].last()
    ev["SYMBOL"] = ev["ENT"].map(sym)
    in_u = u.set_index(["date", "security_id"]).index
    ev["in_universe_that_day"] = [(d, e) in in_u for d, e in zip(pd.to_datetime(ev["DATE"]), ev["ENT"])]
    out["C_neutralised_days_on_universe_stock_days"] = int(ev["in_universe_that_day"].sum())
    big = ev.loc[ev["in_universe_that_day"]].copy()
    big["absmove"] = (np.log(big["raw_gross_return"])).abs()
    top = big.sort_values("absmove", ascending=False).head(12)
    out["C_largest_neutralised_universe_days"] = [
        {"symbol": r["SYMBOL"], "date": str(pd.to_datetime(r["DATE"]).date()),
         "raw_gross_return": round(float(r["raw_gross_return"]), 3)} for _, r in top.iterrows()]

# ---------------------------------------------------------------- D. count-only look at the cells
adjp = p.pivot(index="date", columns="security_id", values="adj_close_now_basis")
tv = p.pivot(index="date", columns="security_id", values="traded_value_cr")
mc = p.pivot(index="date", columns="security_id", values="mcap_cr_est")
inu = p.pivot(index="date", columns="security_id", values="in_universe").fillna(0).astype(bool)
daily_turn = tv / mc
turn_j = daily_turn.rolling(J_DAYS, min_periods=int(J_DAYS * 0.8)).mean()
ret_j = adjp / adjp.shift(J_DAYS) - 1.0

dates = adjp.index
month_end = pd.Series(dates, index=dates).groupby(dates.to_period("M")).last()
rows = []
for d in month_end:
    i = dates.get_loc(d)
    if i < J_DAYS + 5 + 1:
        continue
    prev = dates[i - 1]                       # ranks use data to the previous day
    el = inu.loc[prev] & ret_j.loc[prev].notna() & turn_j.loc[prev].notna()
    n = int(el.sum())
    if n < 100:
        continue
    r = ret_j.loc[prev][el]
    t = turn_j.loc[prev][el]
    r_pct = r.rank(pct=True)
    t_pct = t.rank(pct=True)
    R10 = r_pct > 0.9
    R1 = r_pct <= 0.1
    V1 = t_pct <= 1 / 3
    V3 = t_pct > 2 / 3
    # the same count restricted to the top 500 by that day's traded value (the NIFTY 500-style cut)
    rank_tv = tv.loc[prev][el].rank(ascending=False)
    top500 = rank_tv <= 500
    rows.append({"date": str(d.date()), "eligible": n,
                 "R10V1": int((R10 & V1).sum()), "R1V3": int((R1 & V3).sum()),
                 "R10V3": int((R10 & V3).sum()), "R1V1": int((R1 & V1).sum()),
                 "R10V1_top500": int((R10 & V1 & top500).sum()), "R1V3_top500": int((R1 & V3 & top500).sum())})
cells = pd.DataFrame(rows)
out["D_formation_months"] = int(len(cells))
if len(cells):
    for c in ("eligible", "R10V1", "R1V3", "R10V1_top500", "R1V3_top500"):
        out[f"D_{c}_min_median_max"] = [int(cells[c].min()), float(cells[c].median()), int(cells[c].max())]
    both = np.minimum(cells["R10V1"], cells["R1V3"])
    out["D_months_either_extreme_cell_below_15"] = int((both < MIN_CELL).sum())
    both5 = np.minimum(cells["R10V1_top500"], cells["R1V3_top500"])
    out["D_months_either_extreme_cell_below_15_top500_cut"] = int((both5 < MIN_CELL).sum())
    out["D_first_and_last_formation"] = [cells["date"].iloc[0], cells["date"].iloc[-1]]
    out["D_note"] = "counts only; ranks use data to the day before formation and no outcome returns are read"

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
