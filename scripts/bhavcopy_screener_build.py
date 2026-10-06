#!/usr/bin/env python3
"""Build the 5-year bhavcopy + Screener panel, step by step.

Two sources only: NSE bhavcopy and Screener.in. Nothing else is read.

    1. python -m ros.data.nse_bhavcopy_download --years 5          # raw daily files -> cache/
    2. python scripts/bhavcopy_screener_build.py symbols           # who needs a Screener page
    3. python scripts/bhavcopy_screener_build.py fetch-screener    # pages -> scr/ (slow, polite, resumable)
    4. python scripts/bhavcopy_screener_build.py build             # panel CSV + coverage report

Screener pages are fetched one at a time with a delay (default 2.5 s) in one session, are public,
need no login, and are cached in scr/ so nothing is fetched twice. Data from both sources stays on
this machine (cache/ and scr/ are gitignored); Screener's data is not redistributed.
"""
import argparse
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ros.data.bhavcopy_screener_panel import (  # noqa: E402
    assert_sources, build_turnover_panel, coverage_report, manifest_stanza, screener_shares,
    shares_snapshot_frame, to_master_frame, universe_symbols,
)
from ros.data.nse_bhavcopy_ingest import combine_cache  # noqa: E402
from ros.data.screener_fetch import fetch_symbol  # noqa: E402


def cmd_symbols(a):
    assert_sources(["nse_bhavcopy"])
    df = combine_cache(a.cache)
    syms = universe_symbols(df, top_n=a.top_n)
    open(a.out, "w", encoding="utf-8").write("\n".join(syms) + "\n")
    print(f"{len(syms)} symbols were in the point-in-time top-{a.top_n} at some date -> {a.out}")


def cmd_fetch(a):
    assert_sources(["screener"])
    syms = [s.strip() for s in open(a.symbols_file, encoding="utf-8").read().split() if s.strip()]
    todo = [s for s in syms if not os.path.exists(os.path.join(a.out, s.upper(), "meta.json"))]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(syms)} symbols listed, {len(syms) - len(todo)} already fetched, fetching {len(todo)} "
          f"at {a.delay}s apart (about {len(todo) * a.delay / 60:.0f} min)")
    s = requests.Session()
    ok = bad = 0
    missing = []
    for i, sym in enumerate(todo):
        if fetch_symbol(sym, a.out, s):
            ok += 1
        else:
            bad += 1
            missing.append(sym)
        if i < len(todo) - 1:
            time.sleep(a.delay)
    if missing:
        open(os.path.join(a.out, "_not_found.txt"), "a", encoding="utf-8").write("\n".join(missing) + "\n")
    print(f"done: {ok} fetched, {bad} not found (delisted or no financials); not-found list in {a.out}/_not_found.txt")


def cmd_build(a):
    assert_sources(["nse_bhavcopy", "screener"])
    df = combine_cache(a.cache)
    syms = universe_symbols(df, top_n=a.top_n)
    shares = screener_shares(a.scr, syms)
    panel = build_turnover_panel(df, shares, top_n=a.top_n, window=a.window)
    os.makedirs(a.out_dir, exist_ok=True)
    panel_path = os.path.join(a.out_dir, "bhavcopy_screener_panel.csv")
    master_path = os.path.join(a.out_dir, "bhavcopy_screener_master.csv")
    shares_path = os.path.join(a.out_dir, "screener_shares_snapshot.csv")
    panel.to_csv(panel_path, index=False)
    to_master_frame(panel).to_csv(master_path, index=False)
    import datetime as _dt
    shares_snapshot_frame(shares, _dt.date.today().isoformat()).to_csv(shares_path, index=False)
    print(f"wrote {len(panel)} rows, {panel['security_id'].nunique()} entities, "
          f"{panel['date'].min().date()} to {panel['date'].max().date()}")
    print(f"  panel  -> {panel_path}")
    print(f"  master -> {master_path}")
    print(f"  shares -> {shares_path}")
    print("coverage (the gap is the survivorship bias):")
    for k, v in coverage_report(panel).items():
        print(f"  {k}: {v}")
    flagged = shares[(shares["shares_ratio"] - 1).abs() > 0.15]
    print(f"  shares estimates that disagree by >15% (equity capital / face value vs market cap / price): "
          f"{len(flagged)} of {len(shares)}")
    print()
    print("Declare it in data/raw/MANIFEST.yaml (local only, see docs/BHAVCOPY_SCREENER.md):")
    print(manifest_stanza(master_path, shares_path, a.top_n))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("symbols")
    p.add_argument("--cache", default="cache")
    p.add_argument("--top-n", type=int, default=500)
    p.add_argument("--out", default="scr_symbols.txt")
    p.set_defaults(fn=cmd_symbols)
    p = sub.add_parser("fetch-screener")
    p.add_argument("--symbols-file", default="scr_symbols.txt")
    p.add_argument("--out", default="scr")
    p.add_argument("--delay", type=float, default=2.5)
    p.add_argument("--limit", type=int, default=0, help="fetch at most this many (0 = all)")
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("build")
    p.add_argument("--cache", default="cache")
    p.add_argument("--scr", default="scr")
    p.add_argument("--top-n", type=int, default=1000)
    p.add_argument("--window", type=int, default=21)
    p.add_argument("--out-dir", default="data/raw/master")
    p.set_defaults(fn=cmd_build)
    a = ap.parse_args()
    a.fn(a)
