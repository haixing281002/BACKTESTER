import sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from universal_backtester.accord_data import load_accord_daily_price_mcap, load_accord_monthly_universe

df, _ = load_accord_daily_price_mcap("data/raw/stocks/prices_marketcap_data_till_03082026.csv")
df = df.dropna(subset=["close", "mcap"]).sort_values(["accord_code", "date"]).reset_index(drop=True)
df["implied_sh"] = df["mcap"] / df["close"]
g = df.groupby("accord_code")
df["dlog_sh"] = np.log(df["implied_sh"] / g["implied_sh"].shift(1))
df["dlog_close"] = np.log(df["close"] / g["close"].shift(1))
ev = df[(df["dlog_sh"] > np.log(1.5)) & (df["dlog_close"].abs() < np.log(1.15))][["accord_code", "company_name", "date", "dlog_sh"]]

uni, _ = load_accord_monthly_universe("data/raw/stocks/Monthly_uni_new.xlsx")
uni = uni.dropna(subset=["accord_code", "mcap"]).copy()
uni["accord_code"] = uni["accord_code"].astype(int)
uni = uni.drop_duplicates(["month_end", "accord_code"])
dm = df.copy()
dm["ym"] = dm["date"].dt.to_period("M")
dlast = dm.groupby(["accord_code", "ym"]).tail(1).set_index(["accord_code", "ym"])
uni["ym"] = uni["month_end"].dt.to_period("M")
rows = []
for _, r in ev.iterrows():
    c = int(r["accord_code"])
    ym = r["date"].to_period("M")
    u = uni[uni["accord_code"] == c].set_index("ym")["mcap"]
    before, after = ym - 2, ym + 1
    if before in u.index and after in u.index and (c, before) in dlast.index and (c, after) in dlast.index:
        rows.append({"code": c, "name": r["company_name"], "date": str(r["date"].date()), "f": float(np.exp(r["dlog_sh"])),
                     "monthly_file_mcap_ratio_after_over_before": float(u[after] / u[before]),
                     "daily_file_mcap_ratio_after_over_before": float(dlast.loc[(c, after), "mcap"] / dlast.loc[(c, before), "mcap"])})
x = pd.DataFrame(rows)
out = {"n_events_comparable": int(len(x)),
       "median_f": float(x["f"].median()) if len(x) else None,
       "median_monthly_file_ratio": float(x["monthly_file_mcap_ratio_after_over_before"].median()) if len(x) else None,
       "median_daily_file_ratio": float(x["daily_file_mcap_ratio_after_over_before"].median()) if len(x) else None,
       "sample": x.head(8).round(3).to_dict("records")}
print(json.dumps(out, indent=1))
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1)
