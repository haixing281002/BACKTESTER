# Quant AI Researcher
"""Open a run on a live Lightyear in a real browser and test the metrics and Gate v2 against the page, manifest and workbook.

Nothing is changed unless --rebuild is passed, which rebuilds the run's charts and workbook from its own files first.

    python scripts/gate_v2/check_dashboard.py <run_id> --base http://127.0.0.1:8101 --rebuild
"""
import argparse
import json
import os
import sys
import time
import urllib.request

import openpyxl
from playwright.sync_api import sync_playwright


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--base", default="http://127.0.0.1:8101")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--out", default=os.path.join("outputs", "tmp"))
    a = ap.parse_args()
    base, rid = a.base, a.run
    os.makedirs(a.out, exist_ok=True)
    for _ in range(90):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=2)
            break
        except OSError:
            time.sleep(1)
    if a.rebuild:
        req = urllib.request.Request(f"{base}/api/runs/{rid}/rebuild", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=60).read()
    t0 = time.time()
    time.sleep(3)
    while time.time() - t0 < 500:
        try:
            st = json.load(urllib.request.urlopen(f"{base}/api/runs/{rid}", timeout=30))
        except OSError:     # the page can be mid-rebuild
            time.sleep(5)
            continue
        if st["status"] in ("gate_b", "failed", "decided"):
            break
        time.sleep(5)
    ch = json.load(urllib.request.urlopen(f"{base}/api/runs/{rid}/charts", timeout=60))
    res, errors = [], []

    def chk(name, ok, detail=""):
        res.append({"check": name, "ok": bool(ok), "detail": str(detail)[:220]})
        print("PASS" if ok else "FAIL", "|", name, "|", str(detail)[:150])

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base + "/")
        pg.wait_for_timeout(2500)
        pg.evaluate(f"openRun('{rid}')")
        pg.wait_for_timeout(2500)
        pg.evaluate("setTab('results', true)")
        pg.wait_for_timeout(7000)
        txt = pg.locator('[data-p="results"]').inner_text()
        tiles = pg.eval_on_selector_all("#kpis .kpi .l", "e => e.map(x => x.textContent.trim())")
        vals = pg.eval_on_selector_all("#kpis .kpi .v", "e => e.map(x => x.textContent.trim())")
        core = pg.eval_on_selector_all("#coretab tr", "rows => rows.map(r => [...r.cells].map(c => c.textContent.trim()))")
        h2 = pg.eval_on_selector_all('[data-p="results"] h2', "e => e.map(x => x.textContent.trim())")
        drawn = pg.eval_on_selector_all('[data-p="results"] .chart', "e => e.filter(x => x.querySelector('svg')).map(x => x.id)")
        diag = pg.eval_on_selector_all('[data-p="results"] .card', "cs => cs.filter(c => (c.querySelector('h2') || {}).textContent && c.querySelector('h2').textContent.startsWith('Diagnostics')).map(c => [...c.querySelectorAll('tr')].slice(1).map(r => r.cells[0].innerText))")
        more = pg.locator("#coremore").inner_text()
        pg.locator('[data-p="results"]').screenshot(path=os.path.join(a.out, "results_tab.png"))
        pg.evaluate("setTab('gateb', true)")
        pg.wait_for_timeout(1500)
        gb = pg.locator('[data-p="gateb"]').inner_text()
        tabs = pg.eval_on_selector_all('[data-p="gateb"] table', "t => t.slice(0,2).map(x => [...x.rows].slice(1).map(r => [...r.cells].slice(0,3).map(c => c.innerText.split('\\n')[0])))")
        pg.locator('[data-p="gateb"]').screenshot(path=os.path.join(a.out, "gate_b_tab.png"))
        b.close()

    rd = os.path.join("outputs", "lightyear", rid)
    m = ch["metrics"]["strategy"]
    g = st["results"]["gate_v2"]
    val = st["results"]["validation"]
    labels = {v["label"] for v in val}
    rows = {r[0]: r for r in core}
    bp = ch["card_bp"]
    wb = openpyxl.load_workbook(os.path.join(rd, st["workbook"]), data_only=True)
    wf = openpyxl.load_workbook(os.path.join(rd, st["workbook"]))
    s = wb["Summary"]

    chk("No script errors on the page", not errors, errors[:2])
    chk("The card's cost is the only cost on the page", f"the card's {bp:g}bp" in core[0][1 if not ch["gross"] else 2], core[0])
    chk("The gate is scored at the card's cost", f"{bp:g}bp" in g["basis"], g["basis"])
    chk("No other cost named in the core table or gate", "30bp" not in " ".join(core[0]) + g["basis"] or bp == 30, core[0])
    chk("No row at another cost outside an appendix", not [x for x in labels if "bp" in x and "appendix" not in x.lower() and "reakeven" not in x], [x for x in labels if "bp" in x])
    chk("No row or table names a house cost", not [x for x in labels if "house" in x.lower()], [x for x in labels if "house" in x.lower()])
    prose = (txt + gb).lower().count("house floor") + (txt + gb).lower().count("house cost")
    print("NOTE prose mentions of a house cost, in Claude's text for this run:", prose)
    chk("Tile reads 'Sharpe'", "Sharpe" in tiles, tiles)
    chk("Tile Sharpe equals ros.metrics.core", vals[tiles.index("Sharpe")] == f"{m['sharpe']:.2f}", vals[tiles.index("Sharpe")])
    chk("Cash rate on the page is the card's", "from the card" in more, more[-60:])
    chk("Core performance table: 16 metrics", "Core performance" in h2 and len(core) == 17, f"{len(core) - 1} rows")
    for k in ("Sortino", "Calmar", "95% CVaR (daily loss)", "Up capture (monthly)", "Down capture (monthly)", "Tracking error", "Drawdown duration (trading days)", "CAGR without the 10 best days", "Rolling one-year periods behind"):
        chk(f"Shown with a value: {k}", k in rows and rows[k][1] not in ("", "–"), rows.get(k, ["", "missing"])[1])
    chk("Benchmark labelled as flattering relative figures", "flatters" in txt)
    chk("Post-publication shown separately", "After publication" in more)
    chk("Capacity says why it is not run", "Capacity not computed" in more and "aum_inr_cr" in more)
    chk("Diagnostics section separate", any(x.startswith("Diagnostics") for x in h2))
    want = ["Sells forced", "Mean return of membership", "15%-gap exits", "eligible names", "Names bought at the first fill", "index gate was open", "Fortnightly resize"]
    flat = diag[0] if diag else []
    chk("Rule-specific rows are all in Diagnostics", all(any(w in x for x in flat) for w in want), f"{len(flat)} rows")
    chk("All charts drew", len(drawn) >= 6, drawn)
    chk("Gate tab shows gate_version v2", "gate_version v2" in gb)
    chk("Hard blocks table", "Hard blocks" in gb and len(tabs[0]) == 5, [r[:2] for r in tabs[0]])
    chk("Scorecard table, no deflated Sharpe row", "Evidence scorecard" in gb and not [r for r in tabs[1] if "Deflated" in r[0]], [r[:2] for r in tabs[1]])
    chk("No INCOMPLETE anywhere", "INCOMPLETE" not in gb)
    chk("Missing inputs listed as not run", "Not run, so not passed" in gb, g["tests_not_run"])
    chk("The missing luck test is stated on the page", "selection luck" in gb)
    chk("Decision PENDING", "PENDING" in gb)
    chk("v1 kept for comparison", "Gate v1 checklist, for comparison" in gb)
    chk("Evidence supports labelled as Claude's", "Claude's written read" in gb)
    with open(os.path.join(rd, "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    chk("Manifest records versions", man.get("gate_version") and man.get("metrics_version") == "v2", (man.get("gate_version"), man.get("metrics_version")))
    chk("Workbook records versions", "gate_version v2" in str(s["A3"].value) and "metrics_version v2" in str(s["A3"].value), str(s["A3"].value)[-80:])
    chk("Workbook cash rate is the card's", s["B4"].value == ch["cash_rate"] and "the card" in str(s["A4"].value), s["A4"].value)
    chk("Workbook Sharpe is the one formula", wf["Summary"]["B14"].value == "=(AVERAGE(Ret_Strat)-Cash_Daily)*252/B13", wf["Summary"]["B14"].value)
    for label, cell, key in (("CAGR", "B12", "cagr"), ("Volatility", "B13", "vol"), ("Sharpe", "B14", "sharpe"), ("Max drawdown", "B15", "max_dd"), ("Sortino", "B16", "sortino"), ("Calmar", "B17", "calmar")):
        v = s[cell].value
        chk(f"Excel agrees with the dashboard: {label}", isinstance(v, (int, float)) and abs(v - m[key]) < 1e-6, f"Excel {v} / page {m[key]}")
    chk("Workbook has Core metrics and Gate v2 sheets", {"Core metrics", "Gate v2"} <= set(wb.sheetnames))
    chk("Excel Validation has a Diagnostics section", any(str(r[0]).startswith("Diagnostics") for r in wb["Validation"].iter_rows(values_only=True) if r[0]))
    chk("Workbook recalculated with no errors", (st.get("recalc") or {}).get("total_errors") == 0, st.get("recalc"))
    n_ok = sum(r["ok"] for r in res)
    print(n_ok, "of", len(res))
    with open(os.path.join(a.out, "dash_check.json"), "w", encoding="utf-8") as fh:
        json.dump({"checks": res, "core": core, "more": more, "gate": g, "h2": h2}, fh, indent=1, default=str)
    return 0 if n_ok == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
