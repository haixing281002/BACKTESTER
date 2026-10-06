"""Fallback for the Screener industry label (cards/ssrn_962461.yaml data_requests[1].without_it).

Screener's peer table lists the largest companies in a company's own Screener industry, so two
companies in the same industry carry (nearly) the same peer table. For a stock whose label could not
be fetched, find the LABELLED stock whose cached peer table (scr/<SYMBOL>/peers.pkl) overlaps most
with its own (Jaccard on company names, at least 0.5) and borrow that label. Cached data only; no
request is made.

Run alone it validates itself: leave-one-out on the labelled stocks, how often the borrowed label
equals the fetched one. `--write` adds the borrowed labels to the snapshot, marked
label_source=peer_table so they can always be told apart from fetched ones.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(REPO, "data", "raw", "master", "screener_industry_snapshot.csv")
LABELS = ["screener_broad_sector", "screener_sector", "screener_broad_industry", "screener_industry"]
MIN_JACCARD = 0.5


def peer_key(sym: str):
    p = os.path.join(REPO, "scr", sym, "peers.pkl")
    if not os.path.exists(p):
        return None
    t = pd.read_pickle(p)
    if "Company" not in t.columns:
        return None
    c = t["Company"].dropna().astype(str)
    return frozenset(c[~c.str.startswith("Median")])


def best_match(k, keys: dict, exclude=None):
    best = (0.0, None)
    for s, kk in keys.items():
        if s == exclude or not kk:
            continue
        j = len(k & kk) / len(k | kk)
        if j > best[0]:
            best = (j, s)
    return best


def main():
    from scripts.ssrn_962461_fetch_industry import top500_symbols
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    syms = top500_symbols()
    snap = pd.read_csv(SNAP)
    snap["label_source"] = snap.get("label_source", pd.Series(index=snap.index, dtype=object)).fillna("fetched")
    lab = snap[snap["screener_industry"].notna() & (snap["label_source"] == "fetched")]
    keys = {s: peer_key(s) for s in lab["symbol"]}
    keys = {s: k for s, k in keys.items() if k}
    ind = dict(zip(lab["symbol"], lab["screener_industry"]))
    n = ok = 0
    for s, k in keys.items():
        j, m = best_match(k, keys, exclude=s)
        if j >= MIN_JACCARD:
            n += 1
            ok += ind[m] == ind[s]
    print(f"leave-one-out on {len(keys)} fetched labels with a peer table: {n} matched at Jaccard >= {MIN_JACCARD}, "
          f"{ok} of them borrow the right industry ({ok / max(n, 1):.1%})")

    todo = syms[~syms["security_id"].isin(snap.loc[snap["screener_industry"].notna(), "security_id"])]
    rows, no_tab, no_match = [], 0, 0
    full = lab.set_index("symbol")
    for sid, sym in todo.itertuples(index=False):
        k = peer_key(sym)
        if not k:
            no_tab += 1
            continue
        j, m = best_match(k, keys)
        if j < MIN_JACCARD:
            no_match += 1
            continue
        rows.append({"security_id": sid, "symbol": sym, **{c: full.at[m, c] for c in LABELS},
                     "fetch_date": full.at[m, "fetch_date"], "label_source": f"peer_table:{m}:{j:.2f}"})
    print(f"{len(todo)} names without a fetched label: {len(rows)} borrowed, {no_tab} have no cached peer table, "
          f"{no_match} match no labelled table")
    if a.write and rows:
        snap = snap[~snap["security_id"].isin([r["security_id"] for r in rows])]
        pd.concat([snap, pd.DataFrame(rows)], ignore_index=True).to_csv(SNAP, index=False)
        print(f"wrote {SNAP}")


if __name__ == "__main__":
    main()
