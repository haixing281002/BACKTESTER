#!/usr/bin/env python3
"""Cross-check Accord Fintech prices against NSE bhavcopy prices.

WHY THIS EXISTS

The fund now has two independently-sourced, independently-adjusted price
histories for Indian equities: the vendor panel (Accord Fintech, via
universal_backtester/accord_data.py) and this repo's own ingestion of NSE's
public bhavcopy archive (ros/data/nse_bhavcopy_ingest.py). Neither one's
adjustment logic has been checked against a second opinion -- Accord's
corporate-action handling is a vendor black box, and the bhavcopy ingestion's
own CA-neutralisation is a documented heuristic that "can both miss a
genuine small action and misclassify a genuine large one-day move."

Running the same security through both and diffing is the same idea as
validate/cross_check.py (engine vs. clean-room implementation): agreement is
reassurance, disagreement is a lead, and either way it is cheaper to find
here than inside a Gate B memo.

WHAT THIS DOES NOT DO

It does not merge the two sources into one series, and it does not produce
anything `ros/data/master.py` or MANIFEST.yaml would accept as a master
file. A disagreement is reported for a human to look at, never silently
resolved by picking one source. And the join key here is NSE SYMBOL, via
`accord_data.build_accord_ticker_bridge()` -- a heuristic bridge, not a
permanent ID. This repo's own rule (key on ISIN/Accord Code, never on
symbol, because symbols get reused and renamed) still holds for anything
that gets BUILT; this script only uses the symbol to find candidate pairs
to compare, and flags (never silently drops) any Accord code whose symbol
changed during the file's history (`symbol_ever_changed`).

USAGE

    python scripts/reconcile_accord_vs_nse.py \\
        --accord-price data/raw/stocks/price_data_till_03aug2026.xlsx \\
        --accord-universe data/raw/stocks/Monthly_uni_new.xlsx \\
        --nse-cache cache \\
        --out outputs/reconcile_accord_vs_nse.csv

Needs both an Accord price/universe pair AND an NSE bhavcopy cache (from
download_history.py, run on your own machine -- this sandbox has no network
path to nseindia.com). Writes one row per matched symbol to --out (under
outputs/, gitignored by this repo's own convention) and prints the ones
flagged REVIEW.
"""
from __future__ import annotations

import argparse
import os
from typing import Dict, Optional

import numpy as np
import pandas as pd

from universal_backtester.accord_data import (
    build_accord_ticker_bridge, load_accord_monthly_universe, load_accord_price_panel,
)
from ros.data.nse_bhavcopy_ingest import build_adjusted_prices, combine_cache, dedupe_rows, link_isins


def bhavcopy_symbol_map(raw: pd.DataFrame, links) -> pd.Series:
    """ENT -> most recent SYMBOL seen for it, mirroring the same "latest
    label wins" convention `build_accord_ticker_bridge` uses on the Accord
    side, so the two maps are comparable on the same terms."""
    tagged = raw.assign(ENT=raw["ISIN"].map(links.isin_to_entity))
    return tagged.sort_values("DATE").groupby("ENT")["SYMBOL"].last()


def reconcile(accord_price: pd.DataFrame, accord_bridge: pd.DataFrame,
             nse_panel: pd.DataFrame, nse_symbol: pd.Series,
             min_common_days: int = 40, corr_threshold: float = 0.97,
             max_dev_threshold_pct: float = 10.0) -> pd.DataFrame:
    """One row per symbol seen on both sides: correlation of daily returns
    over their common trading days, and the worst cumulative-level drift
    once both series are re-based to 1.0 at their first common date.

    Comparing REBASED levels rather than raw prices on purpose: the two
    sources need not share a base/split-adjustment convention, only the
    same subsequent RETURNS, which is what both corporate-action-adjustment
    pipelines are actually trying to get right.
    """
    # Filter the TWO columns together on one mask, never dropna() on each
    # separately -- the bridge has 571 codes with no known symbol, and
    # dropping NaNs column-by-column before zipping silently pairs each
    # symbol with the wrong code once the two columns' lengths diverge.
    known = accord_bridge.dropna(subset=["nse_symbol", "accord_code"])
    sym_to_code: Dict[str, int] = dict(zip(known["nse_symbol"], known["accord_code"].astype(int)))
    changed = set(accord_bridge.loc[accord_bridge["symbol_ever_changed"], "accord_code"].astype(int))
    sym_to_ent: Dict[str, str] = {s: e for e, s in nse_symbol.items()}

    common_symbols = sorted(set(sym_to_code) & set(sym_to_ent))
    rows = []
    for sym in common_symbols:
        code, ent = sym_to_code[sym], sym_to_ent[sym]
        if code not in accord_price.columns or ent not in nse_panel.columns:
            continue
        a, b = accord_price[code].dropna(), nse_panel[ent].dropna()
        common_idx = a.index.intersection(b.index)
        note = "accord_symbol_changed_during_history" if code in changed else ""
        if len(common_idx) < min_common_days:
            rows.append(dict(symbol=sym, accord_code=code, nse_entity=ent,
                             n_common_days=len(common_idx), return_corr=np.nan,
                             max_abs_rebased_dev_pct=np.nan,
                             status="too_few_common_days", note=note))
            continue
        a_c, b_c = a.loc[common_idx].sort_index(), b.loc[common_idx].sort_index()
        a_ret, b_ret = a_c.pct_change().dropna(), b_c.pct_change().dropna()
        ridx = a_ret.index.intersection(b_ret.index)
        corr = float(a_ret.loc[ridx].corr(b_ret.loc[ridx])) if len(ridx) > 2 else float("nan")
        a_idx, b_idx = a_c / a_c.iloc[0], b_c / b_c.iloc[0]
        max_dev = float((a_idx - b_idx).abs().max() * 100)
        ok = pd.notna(corr) and corr >= corr_threshold and max_dev <= max_dev_threshold_pct
        rows.append(dict(symbol=sym, accord_code=code, nse_entity=ent,
                         n_common_days=len(common_idx), return_corr=corr,
                         max_abs_rebased_dev_pct=max_dev,
                         status="ok" if ok else "REVIEW", note=note))

    cols = ["symbol", "accord_code", "nse_entity", "n_common_days", "return_corr",
            "max_abs_rebased_dev_pct", "status", "note"]
    out = pd.DataFrame(rows, columns=cols)
    if out.empty:
        return out
    order = {"REVIEW": 0, "too_few_common_days": 1, "ok": 2}
    return out.assign(_o=out["status"].map(order)).sort_values(["_o", "symbol"]).drop(columns="_o")


def run(accord_price_path: str, accord_universe_path: str, nse_cache: str,
       out_path: str, min_common_days: int = 40, corr_threshold: float = 0.97,
       max_dev_threshold_pct: float = 10.0) -> pd.DataFrame:
    accord_price, _ = load_accord_price_panel(accord_price_path)
    universe_df, _ = load_accord_monthly_universe(accord_universe_path)
    accord_bridge, _ = build_accord_ticker_bridge(universe_df)

    raw = dedupe_rows(combine_cache(nse_cache))
    links = link_isins(raw)
    adjusted = build_adjusted_prices(raw, links)
    nse_symbol = bhavcopy_symbol_map(raw, links)

    report = reconcile(accord_price, accord_bridge, adjusted.panel, nse_symbol,
                       min_common_days=min_common_days, corr_threshold=corr_threshold,
                       max_dev_threshold_pct=max_dev_threshold_pct)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    report.to_csv(out_path, index=False)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accord-price", default="data/raw/stocks/price_data_till_03aug2026.xlsx")
    ap.add_argument("--accord-universe", default="data/raw/stocks/Monthly_uni_new.xlsx")
    ap.add_argument("--nse-cache", default="cache")
    ap.add_argument("--out", default="outputs/reconcile_accord_vs_nse.csv")
    ap.add_argument("--min-common-days", type=int, default=40)
    ap.add_argument("--corr-threshold", type=float, default=0.97)
    ap.add_argument("--max-dev-threshold-pct", type=float, default=10.0)
    args = ap.parse_args()

    report = run(args.accord_price, args.accord_universe, args.nse_cache, args.out,
                args.min_common_days, args.corr_threshold, args.max_dev_threshold_pct)

    n = len(report)
    n_ok = int((report["status"] == "ok").sum()) if n else 0
    n_review = int((report["status"] == "REVIEW").sum()) if n else 0
    n_skip = int((report["status"] == "too_few_common_days").sum()) if n else 0

    print(f"Accord <-> NSE bhavcopy reconciliation")
    print(f"  symbols matched on both sides : {n}")
    print(f"  ok                             : {n_ok}")
    print(f"  REVIEW                         : {n_review}")
    print(f"  too few common trading days    : {n_skip}")
    print(f"  report written to              : {args.out}")
    if n_review:
        print()
        print("Flagged for review:")
        print(report[report["status"] == "REVIEW"].to_string(index=False))


if __name__ == "__main__":
    main()
