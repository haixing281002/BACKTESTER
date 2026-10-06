import sys
import pandas as pd

sys.path.insert(0, ".")
from universal_backtester.accord_data import load_accord_daily_price_mcap

df, _ = load_accord_daily_price_mcap("data/raw/stocks/prices_marketcap_data_till_03082026.csv")
cases = [("HDFC Bank", "2019-09-19"), ("Infosys", "2018-06-14"), ("Tata Consultancy", "2018-06-01")]
for name, d in cases:
    sub = df[df["company_name"].str.contains(name, case=False, na=False)]
    codes = sub["accord_code"].unique()
    print("==", name, codes[:5], sub["company_name"].unique()[:3])
    if len(codes) == 0:
        continue
    c = codes[0]
    s = df[df["accord_code"] == c].sort_values("date")
    t = pd.Timestamp(d)
    w = s[(s["date"] >= t - pd.Timedelta(days=6)) & (s["date"] <= t + pd.Timedelta(days=6))]
    w = w.assign(implied_sh=w["mcap"] / w["close"])
    print(w[["date", "close", "mcap", "implied_sh", "volume", "traded_value"]].to_string(index=False))
