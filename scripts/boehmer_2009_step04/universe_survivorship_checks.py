import sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from universal_backtester.accord_data import (load_accord_monthly_universe, get_top_n_universe,
                                              load_accord_daily_price_mcap)

U = "data/raw/stocks/Monthly_uni_new.xlsx"
D = "data/raw/stocks/prices_marketcap_data_till_03082026.csv"
P = "data/raw/stocks/price_data_till_03aug2026.xlsx"
out = {}

# ---------- A. universe size per month
uni, up = load_accord_monthly_universe(U)
top, tp = get_top_n_universe(uni, 500)
cnt = top.groupby("month_end").size()
dups = top.groupby(["month_end", "accord_code"]).size()
out["A_months"] = int(cnt.shape[0])
out["A_first_last"] = [str(cnt.index.min().date()), str(cnt.index.max().date())]
out["A_rows_per_month_min_max"] = [int(cnt.min()), int(cnt.max())]
out["A_months_not_500"] = {str(k.date()): int(v) for k, v in cnt[cnt != 500].items()}
out["A_duplicate_code_months"] = int((dups > 1).sum())
out["A_empty_sheets"] = up.get("empty_sheets")
dd = top.drop_duplicates(["month_end", "accord_code"])
cnt2 = dd.groupby("month_end").size()
out["A_after_dedup_not_500"] = {str(k.date()): int(v) for k, v in cnt2[cnt2 != 500].items()}

# ---------- B. survivorship
df, dp = load_accord_daily_price_mcap(D)
df = df.dropna(subset=["close"])
last = df.groupby("accord_code")["date"].max()
first = df.groupby("accord_code")["date"].min()
end = df["date"].max()
out["B_panel_end"] = str(end.date())
out["B_codes_total"] = int(last.shape[0])
gone = last[last < end - pd.Timedelta(days=10)]
out["B_codes_ending_before_panel_end"] = int(gone.shape[0])
out["B_last_date_year_hist"] = {str(y): int(n) for y, n in gone.dt.year.value_counts().sort_index().items()}
byyear = {}
for y in range(2012, 2027):
    ye = pd.Timestamp(f"{y}-12-31") if y < 2026 else end
    m = df[(df["date"] <= ye) & (df["date"] > ye - pd.Timedelta(days=10))]
    byyear[str(y)] = int(m["accord_code"].nunique())
out["B_priced_names_near_year_end"] = byyear
top_codes = set(dd["accord_code"].dropna().astype(int).unique())
gone_in_top = [c for c in gone.index.astype(int) if c in top_codes]
out["B_ever_in_top500_and_stopped_trading"] = len(gone_in_top)
out["B_top500_codes_ever"] = len(top_codes)

# ---------- C. corporate-action basis
df = df.sort_values(["accord_code", "date"])
df["implied_sh"] = df["mcap"] / df["close"]
g = df.groupby("accord_code")
df["dlog_close"] = np.log(df["close"] / g["close"].shift(1))
df["dlog_sh"] = np.log(df["implied_sh"] / g["implied_sh"].shift(1))
df["val_ratio"] = df["traded_value"] * 1e4 / (df["volume"] * df["close"])
vr = df["val_ratio"].replace([np.inf, -np.inf], np.nan).dropna()
vr = vr[(df.loc[vr.index, "volume"] > 0)]
out["C_value_over_volume_x_close_quantiles"] = {str(q): round(float(vr.quantile(q)), 4) for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)}
big = df[df["dlog_close"].abs() > np.log(1.3)]
out["C_days_close_jump_gt_30pct"] = int(big.shape[0])
both = big[big["dlog_sh"].abs() > np.log(1.2)]
out["C_jump_days_where_implied_shares_also_jumps"] = int(both.shape[0])
shj = df[df["dlog_sh"].abs() > np.log(1.2)]
out["C_days_implied_shares_jump_gt_20pct"] = int(shj.shape[0])
sh_only = shj[shj["dlog_close"].abs() <= np.log(1.3)]
out["C_implied_shares_jump_without_big_close_jump"] = int(sh_only.shape[0])
# sample events
ev = big.copy()
ev["opposite"] = np.sign(ev["dlog_close"]) != np.sign(ev["dlog_sh"])
sample = ev[ev["dlog_close"] < -np.log(1.8)].head(8)[["accord_code", "company_name", "date", "dlog_close", "dlog_sh", "val_ratio"]]
out["C_sample_big_down_jumps"] = sample.assign(date=sample["date"].astype(str)).round(3).to_dict("records")
# value ratio before vs after those events
vr_by_year = df.assign(y=df["date"].dt.year).groupby("y")["val_ratio"].median().round(4)
out["C_median_value_ratio_by_year"] = {str(k): float(v) for k, v in vr_by_year.items()}

json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1, default=str)
print("done")
