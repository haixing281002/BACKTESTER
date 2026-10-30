#!/usr/bin/env python3
"""Patched re-fetch for symbols whose cached screener data came back empty.

Differs from screener_fetch.py only in: tries BOTH consolidated and standalone
pages regardless of which one "looks" valid, and keeps whichever actually has
non-empty profit-loss rows (not just header labels). Everything else (section
regex, headline parse, peers) is identical to screener_fetch.py so downstream
code can read the output the same way.
"""
import argparse
import io
import json
import os
import pickle
import re
import time

import pandas as pd
import requests

BASE = "https://www.screener.in"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SECTIONS = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios", "shareholding", "peers"]
HEADLINE = ("Market Cap", "Current Price", "High / Low", "Stock P/E", "Book Value", "Dividend Yield", "ROCE", "ROE", "Face Value")


def get(url, session, extra=None, tries=3):
    for k in range(tries):
        try:
            r = session.get(url, headers={**HEADERS, **(extra or {})}, timeout=30)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404):
                return r
            if r.status_code == 429:
                time.sleep(10 * (k + 1))
        except requests.RequestException:
            pass
        time.sleep(2 * (k + 1))
    return None


def to_float(s):
    if not s:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", s.split("/")[0])
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


def parse_html(html, used):
    secs = {}
    for sid in SECTIONS:
        m = re.search(r'<section id="%s".*?</section>' % sid, html, re.DOTALL)
        if not m:
            continue
        try:
            tabs = pd.read_html(io.StringIO(m.group(0)))
        except ValueError:
            continue
        secs[sid] = tabs

    # does profit-loss actually have numeric data (more than just the label column)?
    has_data = False
    pl = secs.get("profit-loss")
    if pl and len(pl) > 0 and pl[0].shape[1] > 1:
        has_data = True

    top = {}
    for m in re.finditer(r'<li class="flex flex-space-between"[^>]*>(.*?)</li>', html, re.DOTALL):
        t = " ".join(re.sub(r"<[^>]+>", "", m.group(1)).split())
        for k in HEADLINE:
            if t.startswith(k):
                top[k] = t[len(k):].strip()
    name = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    meta = dict(symbol=None, view=used,
                name=" ".join(re.sub(r"<[^>]+>", "", name.group(1)).split()) if name else None,
                mcap_cr=to_float(top.get("Market Cap")), price=to_float(top.get("Current Price")),
                pe=to_float(top.get("Stock P/E")), roce_pct=to_float(top.get("ROCE")), roe_pct=to_float(top.get("ROE")),
                div_yield_pct=to_float(top.get("Dividend Yield")), headline_raw=top)
    wid = re.search(r'data-warehouse-id="(\d+)"', html)
    if wid:
        meta["warehouse_id"] = wid.group(1)
    meta["growth_text"] = [t.columns[0] + ": " + ", ".join(f"{a} {b}" for a, b in zip(t.iloc[:, 0], t.iloc[:, 1]))
                            for t in secs.get("profit-loss", [])[1:]]
    return secs, meta, has_data


def fetch_symbol(sym, out, session):
    sym = sym.upper()
    best = None   # (secs, meta, html) from whichever view has real data
    any_html = None
    for kind in ("consolidated/", ""):
        r = get(f"{BASE}/company/{sym}/{kind}", session)
        if r is None or r.status_code != 200:
            continue
        if 'id="profit-loss"' not in r.text:
            continue
        used = kind.strip("/") or "standalone"
        secs, meta, has_data = parse_html(r.text, used)
        any_html = any_html or r.text
        if has_data:
            best = (secs, meta, used)
            break   # consolidated preferred if it has data; else loop tries standalone
    if best is None:
        print(f"[{sym}] still empty after consolidated+standalone retry")
        return False

    secs, meta, used = best
    meta["symbol"] = sym
    if not meta.get("name"):
        meta["name"] = sym
    d = os.path.join(out, sym)
    os.makedirs(os.path.join(d, "csv"), exist_ok=True)
    for sid, tabs in secs.items():
        for n, t in enumerate(tabs):
            t.to_csv(os.path.join(d, "csv", f"{sid}_{n}.csv"), index=False)
    pickle.dump(secs, open(os.path.join(d, "secs.pkl"), "wb"))

    if wid_present(meta):
        pr = get(f"{BASE}/api/company/{meta['warehouse_id']}/peers/", session, {"X-Requested-With": "XMLHttpRequest"})
        if pr is not None and pr.status_code == 200:
            try:
                pd.read_html(io.StringIO(pr.text))[0].to_pickle(os.path.join(d, "peers.pkl"))
            except ValueError:
                pass

    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[{sym}] ok ({used}) sections={list(secs.keys())} -> {d}")
    return True


def wid_present(meta):
    return "warehouse_id" in meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--out", default="scr")
    ap.add_argument("--delay", type=float, default=2.0)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    session = requests.Session()
    ok = 0
    for i, sym in enumerate(args.symbols):
        if fetch_symbol(sym, args.out, session):
            ok += 1
        if i < len(args.symbols) - 1:
            time.sleep(args.delay)
    print(f"done: {ok}/{len(args.symbols)} symbols")


if __name__ == "__main__":
    main()
