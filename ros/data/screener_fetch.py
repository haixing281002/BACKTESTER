#!/usr/bin/env python3
"""Fetch fundamentals for NSE symbols from Screener.in (public pages, no login).

usage:
    python -m ros.data.screener_fetch AIAENG                  # one symbol
    python -m ros.data.screener_fetch WIPRO TCS INFY          # several (polite delay between calls)
    python -m ros.data.screener_fetch --out scr --delay 2.5 AIAENG

For each symbol writes  <out>/<SYMBOL>/
    secs.pkl                dict: section id -> list of DataFrames (pandas.read_html output)
    csv/<section>_<n>.csv   the same tables as CSV (portable to R / Excel / other languages)
    peers.pkl               peers table (from Screener's ajax endpoint)
    meta.json               name, view used (consolidated/standalone), headline ratios, growth text
Needs: requests, pandas, lxml, html5lib   (pip install requests pandas lxml html5lib beautifulsoup4)

SCREENER DATA IS NOT POINT-IN-TIME. It is restated, latest-value data with no announcement dates, and the
headline ratios (market cap, price) are as of the day of the fetch. Anything built from it carries that caveat.
"""
import argparse, io, json, os, pickle, re, sys, time
import requests, pandas as pd

BASE = "https://www.screener.in"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SECTIONS = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios", "shareholding", "peers"]
HEADLINE = ("Market Cap", "Current Price", "High / Low", "Stock P/E", "Book Value", "Dividend Yield", "ROCE", "ROE", "Face Value")


def get(url, session, extra=None, tries=3):
    """GET with small retry/backoff. Returns the Response (any status for 403/404) or None."""
    for k in range(tries):
        try:
            r = session.get(url, headers={**HEADERS, **(extra or {})}, timeout=30)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404):
                return r                      # not retryable
            if r.status_code == 429:
                time.sleep(10 * (k + 1))      # rate limited: back off
        except requests.RequestException:
            pass
        time.sleep(2 * (k + 1))
    return None


def to_float(s):
    """'Rs 1,234.5 Cr.' -> 1234.5 ; '12.3 %' -> 12.3 ; '1,200 / 800' -> 1200 (first number) ; junk -> None."""
    if not s:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", s.split("/")[0])
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


def fetch_symbol(sym, out, session):
    sym = sym.upper()
    html, used = None, None
    for kind in ("consolidated/", ""):                       # consolidated first, standalone fallback
        r = get(f"{BASE}/company/{sym}/{kind}", session)
        if r is not None and r.status_code == 200 and 'id="profit-loss"' in r.text and "Market Cap" in r.text:
            html, used = r.text, (kind.strip("/") or "standalone")
            break
    if html is None:
        print(f"[{sym}] page not found / no financials")
        return False

    d = os.path.join(out, sym)
    os.makedirs(os.path.join(d, "csv"), exist_ok=True)

    # 1) every financial section is a plain HTML <table> inside <section id="...">
    secs = {}
    for sid in SECTIONS:
        m = re.search(r'<section id="%s".*?</section>' % sid, html, re.S)
        if not m:
            continue
        try:
            tabs = pd.read_html(io.StringIO(m.group(0)))
        except ValueError:
            continue
        secs[sid] = tabs
        for n, t in enumerate(tabs):
            t.to_csv(os.path.join(d, "csv", f"{sid}_{n}.csv"), index=False)
    pickle.dump(secs, open(os.path.join(d, "secs.pkl"), "wb"))

    # 2) headline ratios (top card): <li class="flex flex-space-between"> Name ... value
    top = {}
    for m in re.finditer(r'<li class="flex flex-space-between"[^>]*>(.*?)</li>', html, re.S):
        t = " ".join(re.sub(r"<[^>]+>", "", m.group(1)).split())
        for k in HEADLINE:
            if t.startswith(k):
                top[k] = t[len(k):].strip()
    name = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    meta = dict(symbol=sym, view=used,
                name=" ".join(re.sub(r"<[^>]+>", "", name.group(1)).split()) if name else sym,
                mcap_cr=to_float(top.get("Market Cap")), price=to_float(top.get("Current Price")),
                pe=to_float(top.get("Stock P/E")), roce_pct=to_float(top.get("ROCE")), roe_pct=to_float(top.get("ROE")),
                div_yield_pct=to_float(top.get("Dividend Yield")), headline_raw=top)

    # 3) peers are loaded by an ajax call keyed on Screener's internal "warehouse id"
    wid = re.search(r'data-warehouse-id="(\d+)"', html)
    if wid:
        meta["warehouse_id"] = wid.group(1)
        pr = get(f"{BASE}/api/company/{wid.group(1)}/peers/", session, {"X-Requested-With": "XMLHttpRequest"})
        if pr is not None and pr.status_code == 200:
            try:
                pd.read_html(io.StringIO(pr.text))[0].to_pickle(os.path.join(d, "peers.pkl"))
            except ValueError:
                pass

    # 4) 'Compounded Sales Growth' etc. = the small tables that follow the main P&L table
    meta["growth_text"] = [t.columns[0] + ": " + ", ".join(f"{a} {b}" for a, b in zip(t.iloc[:, 0], t.iloc[:, 1]))
                           for t in secs.get("profit-loss", [])[1:]]
    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf8"), indent=2, ensure_ascii=False)
    print(f"[{sym}] ok ({used}) sections={list(secs)} -> {d}")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--out", default="scr")
    ap.add_argument("--delay", type=float, default=1.5)
    a = ap.parse_args()
    s = requests.Session()
    ok = 0
    for i, sym in enumerate(a.symbols):
        ok += bool(fetch_symbol(sym, a.out, s))
        if i < len(a.symbols) - 1:
            time.sleep(a.delay)
    print(f"done: {ok}/{len(a.symbols)} symbols")
