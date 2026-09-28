"""Builds the standalone Accord Code <-> NSE ticker bridge file.

Run this locally, where Monthly_uni_new.xlsx actually is:

    python scripts/build_accord_ticker_bridge.py

Output: outputs/accord_code_ticker_bridge.csv -- one row per Accord Code,
just the bridge key and nothing else (accord_code, nse_symbol,
company_name, as_of, n_months_seen, n_months_symbol_known,
symbol_ever_changed, prior_symbols). Self-contained: no other file is
needed to read it, so it's the one to send someone who just needs the
mapping, not the whole pipeline.

WHY A SEPARATE FILE AT ALL: universal_backtester/accord_data.py's own
module docstring is explicit that Accord Code, never NSE_symbol or
Company Name, is this dataset's stable join key -- symbols get reused,
names change. This file does not change that discipline anywhere in the
pipeline; it exists ONLY as a read-only reference export for a human (or
a system outside this repo) who needs "what does Accord Code 132540
actually trade as", not as something anything in ros/ or
universal_backtester/ ever joins against.

WHY THE SYMBOL IS SOMETIMES BLANK: only 127 of Monthly_uni_new.xlsx's 163
monthly sheets carry an NSE_symbol column at all (the other ~36 have a
shorter schema). A blank nse_symbol here means the file itself never
recorded one for that code, not that this script failed to look -- see
n_months_symbol_known (0 means genuinely never seen).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from universal_backtester.accord_data import (
    load_accord_monthly_universe, build_accord_ticker_bridge, write_accord_ticker_bridge_csv,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "Monthly_uni_new.xlsx")
OUTPUT_DIR = os.path.join(REPO_ROOT, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def main():
    print(f"Loading Accord monthly universe: {UNIVERSE_PATH}")
    uni, uni_prov = load_accord_monthly_universe(UNIVERSE_PATH)
    print(f"  {uni_prov['n_sheets']} monthly sheets, {len(uni):,} rows, "
          f"{uni['accord_code'].nunique():,} distinct Accord Codes")
    if uni_prov["n_empty_sheets"]:
        print(f"  {uni_prov['n_empty_sheets']} empty sheets skipped "
              f"(no universe data for those months)")

    print("\nBuilding the Accord Code <-> NSE ticker bridge...")
    bridge, prov = build_accord_ticker_bridge(uni)
    print(f"  {prov['n_codes_total']:,} distinct Accord Codes")
    print(f"  {prov['n_codes_with_known_symbol']:,} have a known NSE symbol "
          f"({prov['n_codes_with_known_symbol'] / prov['n_codes_total']:.1%})")
    print(f"  {prov['n_codes_symbol_unknown']:,} have NO symbol recorded anywhere in the file "
          f"(never fabricated -- left blank)")
    print(f"  {prov['n_codes_symbol_ever_changed']:,} codes carried more than one distinct symbol "
          f"over time (see prior_symbols column) -- exactly the reuse risk this dataset warns about")

    out_path = os.path.join(OUTPUT_DIR, "accord_code_ticker_bridge.csv")
    write_accord_ticker_bridge_csv(out_path, bridge)
    print(f"\nBridge file written to: {out_path}")
    print(f"  ({len(bridge):,} rows -- self-contained, safe to send to someone on its own)")

    print("\nSample rows:")
    print(bridge.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
