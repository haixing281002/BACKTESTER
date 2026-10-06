import sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from universal_backtester.accord_data import load_accord_daily_price_mcap

D = "data/raw/stocks/prices_marketcap_data_till_03082026.csv"
df, _ = load_accord_daily_price_mcap(D)
df = df.dropna(subset=["close", "mcap"]).sort_values(["accord_code", "date"]).reset_index(drop=True)
df["implied_sh"] = df["mcap"] / df["close"]
df["turn_shares"] = df["volume"] / df["implied_sh"]
df["turn_value"] = df["traded_value"] / df["mcap"]
g = df.groupby("accord_code")
df["dlog_sh"] = np.log(df["implied_sh"] / g["implied_sh"].shift(1))
df["dlog_close"] = np.log(df["close"] / g["close"].shift(1))
ev = df[(df["dlog_sh"].abs() > np.log(1.5)) & (df["dlog_close"].abs() < np.log(1.15))]
res = []
for idx, r in ev.iterrows():
    sub = df[df["accord_code"] == r["accord_code"]]
    i = sub.index.get_loc(idx)
    b = sub.iloc[max(0, i - 20):i]
    a = sub.iloc[i:i + 20]
    if len(b) < 15 or len(a) < 15:
        continue
    mb, ma = b["turn_shares"].median(), a["turn_shares"].median()
    vb, va = b["turn_value"].median(), a["turn_value"].median()
    volb, vola = b["volume"].median(), a["volume"].median()
    if min(mb, ma, vb, va, volb, vola) <= 0:
        continue
    res.append({"f": float(np.exp(r["dlog_sh"])), "shares_turn_ratio": ma / mb, "value_turn_ratio": va / vb, "volume_ratio": vola / volb})
x = pd.DataFrame(res)
out = {"n_events": int(len(x)),
       "share_events_up": int((x["f"] > 1).sum()), "share_events_down": int((x["f"] < 1).sum())}
for name, sub in (("up_f_gt1", x[x["f"] > 1]), ("down_f_lt1", x[x["f"] < 1])):
    out[name] = {
        "n": int(len(sub)),
        "median_f": float(sub["f"].median()),
        "median_volume_ratio_after_over_before": float(sub["volume_ratio"].median()),
        "median_shares_turnover_ratio": float(sub["shares_turn_ratio"].median()),
        "median_value_turnover_ratio": float(sub["value_turn_ratio"].median()),
    }
# fraction of events where the shares-based turnover jumps by >40% vs value-based
out["frac_events_shares_turnover_changes_gt40pct"] = float(((x["shares_turn_ratio"] - 1).abs() > 0.4).mean())
out["frac_events_value_turnover_changes_gt40pct"] = float(((x["value_turn_ratio"] - 1).abs() > 0.4).mean())
# overall rank agreement between share-based and value-based monthly-ish turnover (last day of each month)
df["ym"] = df["date"].dt.to_period("M")
last = df.groupby(["accord_code", "ym"]).tail(1)
m = last.groupby("ym").apply(lambda t: t[["turn_shares", "turn_value"]].rank(pct=True).corr().iloc[0, 1])
out["rank_corr_shares_vs_value_turnover_daily_snapshot_median"] = float(m.median())
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1)
print(json.dumps(out, indent=1))
