"""Stage 03 data request for cards/ssrn_962461.yaml: Screener.in industry label per stock.

The card's four basket sleeves are defined by industry, and the bhavcopy master carries no
industry column. Screener's public company page shows a four-level classification
(Broad Sector > Sector > Broad Industry > Industry) as links with those titles. This script
reads only that, for every stock that is ever in the card's top-500-by-traded-value
universe, and writes data/raw/master/screener_industry_snapshot.csv.

Rules (the operator's): public pages only, never log in, one session, one request at a
time, >= 1.5 s apart. Resumable: symbols already in the output file are not fetched again.

The label is TODAY's classification, not point in time; a company that changed business
inside the window is classified by what it is now, and delisted names have no page.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(REPO, "data", "raw", "master", "bhavcopy_screener_master.csv")
OUT = os.path.join(REPO, "data", "raw", "master", "screener_industry_snapshot.csv")
BASE = "https://www.screener.in"
HEADERS = {"User-Agent": "Mozilla/5.0"}
LEVELS = ("Broad Sector", "Sector", "Broad Industry", "Industry")


def top500_symbols(master_path: str = MASTER) -> pd.DataFrame:
    """Every (security_id, symbol) ever in the card's universe -- see
    scripts/ssrn_962461_india_backtest.py:top500_membership for the rule itself."""
    from scripts.ssrn_962461_india_backtest import load_panel, top500_membership
    px, adv, flag, names = load_panel(master_path)
    mem = top500_membership(adv, flag)
    ever = mem.columns[mem.any()]
    return pd.DataFrame({"security_id": ever, "symbol": [names[e] for e in ever]})


def parse_labels(page: str) -> dict:
    out = {}
    for m in re.finditer(r'<a href="/market/[^"]*"[^>]*title="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        title, text = m.group(1), html.unescape(" ".join(re.sub(r"<[^>]+>", "", m.group(2)).split()))
        if title in LEVELS and title not in out:
            out[title] = text
    return out


def fetch(sym: str, session: requests.Session) -> dict | None:
    for kind in ("consolidated/", ""):
        for k in range(3):
            try:
                r = session.get(f"{BASE}/company/{sym}/{kind}", headers=HEADERS, timeout=30)
            except requests.RequestException:
                time.sleep(3 * (k + 1))
                continue
            if r.status_code == 429:
                time.sleep(15 * (k + 1))
                continue
            break
        else:
            continue
        if r.status_code == 200:
            lab = parse_labels(r.text)
            if lab:
                return lab
        time.sleep(1.6)  # second request for the same symbol is still spaced
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delay", type=float, default=1.6)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    assert a.delay >= 1.5, "operator rule: at least 1.5 s between Screener requests"

    syms = top500_symbols()
    done = pd.read_csv(OUT) if os.path.exists(OUT) else pd.DataFrame(
        columns=["security_id", "symbol", "screener_broad_sector", "screener_sector",
                 "screener_broad_industry", "screener_industry", "fetch_date"])
    todo = syms[~syms["security_id"].isin(done["security_id"])]
    if a.limit:
        todo = todo.head(a.limit)
    print(f"{len(syms)} names ever in the top-500 universe; {len(done)} already labelled; fetching {len(todo)} "
          f"at {a.delay}s apart (about {len(todo) * a.delay / 60:.0f} min)", flush=True)
    s = requests.Session()
    today = dt.date.today().isoformat()
    rows = []
    for i, (sid, sym) in enumerate(todo.itertuples(index=False)):
        lab = fetch(sym, s)
        rows.append({"security_id": sid, "symbol": sym,
                     "screener_broad_sector": (lab or {}).get("Broad Sector"),
                     "screener_sector": (lab or {}).get("Sector"),
                     "screener_broad_industry": (lab or {}).get("Broad Industry"),
                     "screener_industry": (lab or {}).get("Industry"), "fetch_date": today})
        print(f"[{i + 1}/{len(todo)}] {sym}: {lab.get('Industry') if lab else 'NOT FOUND'}", flush=True)
        if len(rows) % 25 == 0 or i == len(todo) - 1:
            done = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
            done.to_csv(OUT, index=False)
            rows = []
        if i < len(todo) - 1:
            time.sleep(a.delay)
    print(f"wrote {OUT}: {len(done)} rows, {done['screener_industry'].isna().sum()} without a label")


if __name__ == "__main__":
    main()
