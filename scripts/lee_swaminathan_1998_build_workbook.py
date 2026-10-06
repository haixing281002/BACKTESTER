"""Results workbook for the Lee & Swaminathan run, built to the xlsx skill's rules.

  - Arial throughout; blue text = hardcoded inputs, black = formulas, yellow fill = key assumption.
  - The Summary metrics are FORMULAS over the Returns sheet, not pasted numbers, so the workbook
    recalculates if the returns change. The Returns sheet's two return columns are the only
    hardcoded series (daily returns written by scripts/lee_swaminathan_1998_india_backtest.py).
  - Everything the backtest code computed that cannot be a formula here (bootstrap intervals,
    deflated Sharpe, the factor fingerprint, Gate B criteria) is shown as a hardcoded value with
    its source named next to it.
  - Headline = the strategy against NIFTY 500, nothing else. Comparators sit on their own sheet.

usage: python scripts/lee_swaminathan_1998_build_workbook.py
Then recalculate with the skill's recalc.py (needs LibreOffice) and check total_errors is 0.
"""
import json
import os
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "outputs")
SLUG = "lee_swaminathan_1998"
STRAT_COL, BENCH_COL = "MAIN R10V1-R1V3 (long-short)", "NIFTY 500"
STRAT_LABEL = "R10V1 - R1V3 (long-short)"

ARIAL = "Arial"
F_BASE = Font(name=ARIAL, size=10)
F_BOLD = Font(name=ARIAL, size=10, bold=True)
F_TITLE = Font(name=ARIAL, size=14, bold=True)
F_INPUT = Font(name=ARIAL, size=10, color="0000FF")
F_NOTE = Font(name=ARIAL, size=9, italic=True, color="555555")
F_HEAD = Font(name=ARIAL, size=10, bold=True, color="FFFFFF")
FILL_HEAD = PatternFill("solid", fgColor="1F4E79")
FILL_KEY = PatternFill("solid", fgColor="FFFF00")
THIN = Side(style="thin", color="BBBBBB")
PCT, PCT2, NUM2, DATE = "0.0%;(0.0%);-", "0.00%;(0.00%);-", "0.00;(0.00);-", "yyyy-mm-dd"


def style_range(ws, rng, font=F_BASE, fmt=None, align=None):
    for row in ws[rng]:
        for c in row:
            c.font = font
            if fmt:
                c.number_format = fmt
            if align:
                c.alignment = align


def header(ws, row, values, col=1):
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=col + i, value=v)
        c.font, c.fill = F_HEAD, FILL_HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def widths(ws, spec):
    for i, w in enumerate(spec, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def put(ws, ref, value, font=F_BASE, fmt=None, fill=None, comment=None):
    c = ws[ref]
    c.value = value
    c.font = font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if comment:
        c.comment = Comment(comment, "analysis")
    return c


def main():
    res = json.load(open(os.path.join(OUT, f"{SLUG}_results.json"), encoding="utf-8"))
    rets = pd.read_csv(os.path.join(OUT, f"{SLUG}_daily_returns.csv"), index_col=0, parse_dates=True)
    rets = rets[[STRAT_COL, BENCH_COL]].dropna()
    n = len(rets)
    last = n + 1                                   # last data row on the Returns sheet

    wb = Workbook()

    # ------------------------------------------------------------------ Returns
    wr = wb.active
    wr.title = "Returns"
    header(wr, 1, ["Date", f"{STRAT_LABEL} daily return", "NIFTY 500 daily return",
                   f"{STRAT_LABEL} value (100 = start)", "NIFTY 500 value (100 = start)",
                   f"{STRAT_LABEL} drawdown", "NIFTY 500 drawdown"])
    for i, (d, r) in enumerate(rets.iterrows(), start=2):
        wr.cell(row=i, column=1, value=d.to_pydatetime()).number_format = DATE
        c1 = wr.cell(row=i, column=2, value=float(r[STRAT_COL]))
        c2 = wr.cell(row=i, column=3, value=float(r[BENCH_COL]))
        for c in (c1, c2):
            c.font, c.number_format = F_INPUT, "0.000%;(0.000%);-"
        if i == 2:
            wr.cell(row=i, column=4, value=100)
            wr.cell(row=i, column=5, value=100)
        else:
            wr.cell(row=i, column=4, value=f"=D{i-1}*(1+B{i})")
            wr.cell(row=i, column=5, value=f"=E{i-1}*(1+C{i})")
        wr.cell(row=i, column=6, value=f"=D{i}/MAX(D$2:D{i})-1")
        wr.cell(row=i, column=7, value=f"=E{i}/MAX(E$2:E{i})-1")
        for col in (1, 4, 5, 6, 7):
            wr.cell(row=i, column=col).font = F_BASE
        wr.cell(row=i, column=4).number_format = wr.cell(row=i, column=5).number_format = "0.00"
        wr.cell(row=i, column=6).number_format = wr.cell(row=i, column=7).number_format = PCT
    wr.freeze_panes = "B2"
    widths(wr, [12, 22, 22, 24, 24, 22, 22])
    wr.row_dimensions[1].height = 32
    note_r = n + 3
    put(wr, f"A{note_r}", "Source: outputs/lee_swaminathan_1998_daily_returns.csv, written by "
        "scripts/lee_swaminathan_1998_india_backtest.py. Blue = hardcoded daily returns (net of 30bp costs and 100bp borrow "
        "inside the strategy; NIFTY 500 is price-return, with its last 10 trading days carried forward because the index "
        "data ends 2026-09-18). Black = formulas.", F_NOTE)

    # ------------------------------------------------------------------ Summary
    ws = wb.create_sheet("Summary", 0)
    put(ws, "A1", "Lee & Swaminathan (1998) price momentum and trading volume, India quick test", F_TITLE)
    put(ws, "A2", "Card run as drafted. Strategy against NIFTY 500 only. Decision: PENDING (Gate B is a human decision).", F_NOTE)
    put(ws, "A4", "Hurdle rate for Sharpe", F_BOLD)
    put(ws, "B4", 0.06, F_INPUT, PCT, FILL_KEY,
        comment="Key assumption: flat 6% proxy for the Indian short rate (the repo's convention; no real series is held).")
    put(ws, "C4", "Assumption: flat 6% proxy, the repo's convention. Change it here and Sharpe updates.", F_NOTE)
    header(ws, 6, ["Metric", STRAT_LABEL, "NIFTY 500"])
    rng = lambda col: f"Returns!{col}$2:{col}${last}"
    rows = [
        ("Start date", f"=MIN(Returns!$A$2:$A${last})", f"=MIN(Returns!$A$2:$A${last})", DATE),
        ("End date", f"=MAX(Returns!$A$2:$A${last})", f"=MAX(Returns!$A$2:$A${last})", DATE),
        ("Trading days", f"=COUNT({rng('B')})", f"=COUNT({rng('C')})", "#,##0"),
        ("CAGR", f"=(Returns!D{last}/Returns!D2)^(365.25/(MAX(Returns!$A$2:$A${last})-MIN(Returns!$A$2:$A${last})))-1",
                 f"=(Returns!E{last}/Returns!E2)^(365.25/(MAX(Returns!$A$2:$A${last})-MIN(Returns!$A$2:$A${last})))-1", PCT),
        ("Annualised volatility", f"=STDEV({rng('B')})*SQRT(252)", f"=STDEV({rng('C')})*SQRT(252)", PCT),
        ("Sharpe vs hurdle", "=(B10-$B$4)/B11", "=(C10-$B$4)/C11", NUM2),
        ("Maximum drawdown", f"=-MIN({rng('F')})", f"=-MIN({rng('G')})", PCT),
        ("Final value (100 = start)", f"=Returns!D{last}", f"=Returns!E{last}", "0.0"),
    ]
    for i, (label, fs, fb, fmt) in enumerate(rows, start=7):
        put(ws, f"A{i}", label, F_BASE)
        put(ws, f"B{i}", fs, F_BASE, fmt)
        put(ws, f"C{i}", fb, F_BASE, fmt)
    put(ws, "A16", "CAGR uses calendar years (days / 365.25), volatility is the standard deviation of daily returns "
        "times the square root of 252, matching universal_backtester/metrics.py. All cells above are formulas over the Returns sheet.",
        F_NOTE)
    header(ws, 18, ["Gate B criterion (computed by ros/governance/gates.py)", "Result", "Value", "Threshold"])
    gb = res["gate_b"]["criteria"]
    for i, c in enumerate(gb, start=19):
        put(ws, f"A{i}", c["name"], F_BASE)
        put(ws, f"B{i}", "PASS" if c["passed"] else ("FAIL" if c["blocking"] else "not computed"), F_BOLD)
        put(ws, f"C{i}", str(c.get("value")), F_INPUT)
        put(ws, f"D{i}", str(c.get("threshold")), F_INPUT)
    r = 19 + len(gb)
    put(ws, f"A{r}", "Decision", F_BOLD)
    put(ws, f"B{r}", res["gate_b"]["decision"], F_BOLD)
    put(ws, f"A{r+1}", "Source: outputs/lee_swaminathan_1998_results.json (gate_b). Values in blue are hardcoded from that run. "
        "The mandate criterion was not run on this script path, so it has no row.", F_NOTE)
    widths(ws, [52, 26, 22, 16])
    ws.row_dimensions[6].height = 28

    # ------------------------------------------------------------------ Validation
    wv = wb.create_sheet("Validation")
    put(wv, "A1", "Validation, as computed by the backtest code", F_TITLE)
    put(wv, "A2", "Hardcoded from outputs/lee_swaminathan_1998_results.json and the run log. Block-bootstrap block length is "
        "126 days (K = 6 months), 1,000 resamples, seed 0.", F_NOTE)
    header(wv, 4, ["Test", "Point", "90% low", "90% high", "Share of resamples positive"])
    bm, pv, pe = res["bootstrap_main"], res["paired_vs_plain"], res["paired_vs_equal_weight"]
    ph = res["paired_hv_vs_plain"]
    vrows = [
        ("Strategy Sharpe (zero hurdle)", bm["point"], bm["ci_low"], bm["ci_high"], None),
        ("Paired: strategy minus plain momentum", pv["point"], pv["ci_low"], pv["ci_high"], None),
        ("Paired: strategy minus equal-weight universe", pe["point"], pe["ci_low"], pe["ci_high"], None),
        ("Paired: high-volume momentum minus plain momentum", ph["point"], ph["ci_low"], ph["ci_high"], None),
    ]
    for i, (lab, p, lo, hi, _) in enumerate(vrows, start=5):
        put(wv, f"A{i}", lab)
        for col, v in zip("BCD", (p, lo, hi)):
            put(wv, f"{col}{i}", float(v), F_INPUT, NUM2)
    put(wv, "A10", "Deflated Sharpe probability (48 trials, trial Sharpe std 0.3)")
    put(wv, "B10", float(res["deflated_sharpe"]), F_INPUT, NUM2)
    fp = res.get("factor_fingerprint", {})
    put(wv, "A11", "Factor fingerprint alpha, annualised (vs VALUE 50, MOMENTUM 50)")
    put(wv, "B11", float(fp.get("alpha_ann", float("nan"))), F_INPUT, PCT2)
    put(wv, "A12", "Factor fingerprint alpha HAC t-statistic")
    put(wv, "B12", float(fp.get("alpha_t_hac", float("nan"))), F_INPUT, NUM2)
    put(wv, "A13", "Factor fingerprint R-squared")
    put(wv, "B13", float(fp.get("r_squared", float("nan"))), F_INPUT, NUM2)
    put(wv, "A15", "Allocator diagnostics (the card's 15-name rule applied literally)", F_BOLD)
    md = res["main_diagnostics"]
    diag = [("Tranches formed", md["tranches_formed"]), ("Months skipped for warmup", md["months_skipped_warmup"]),
            ("Months skipped, a needed cell under 15 names", md["months_skipped_thin"]),
            ("Mean names in long cell when formed", md["mean_long_names_formed"]),
            ("Mean names in short cell when formed", md["mean_short_names_formed"])]
    for i, (lab, v) in enumerate(diag, start=16):
        put(wv, f"A{i}", lab)
        put(wv, f"B{i}", float(v), F_INPUT, "0.0" if isinstance(v, float) else "0")
    put(wv, "A22", "A skipped month carries the book forward unchanged, so old tranches do not expire while months are skipped.", F_NOTE)
    widths(wv, [62, 14, 14, 14, 26])

    # ------------------------------------------------------------------ Sensitivity
    wsn = wb.create_sheet("Sensitivity")
    put(wsn, "A1", "Sensitivity of the strategy", F_TITLE)
    put(wsn, "A2", "Hardcoded from the CSVs the backtest script wrote (outputs/lee_swaminathan_1998_*.csv).", F_NOTE)
    jk = pd.read_csv(os.path.join(OUT, f"{SLUG}_sensitivity_jk.csv"))
    header(wsn, 4, ["J = K (months)", "CAGR", "Volatility", "Sharpe (zero hurdle)", "Max drawdown"])
    for i, rr in enumerate(jk.itertuples(index=False), start=5):
        put(wsn, f"A{i}", int(rr[0]), F_INPUT, "0")
        for col, v, fm in zip("BCDE", rr[1:5], (PCT, PCT, NUM2, PCT)):
            put(wsn, f"{col}{i}", float(v), F_INPUT, fm)
    s0 = 5 + len(jk) + 2
    put(wsn, f"A{s0-1}", "Cost and borrow sweep", F_BOLD)
    sw = pd.read_csv(os.path.join(OUT, f"{SLUG}_cost_borrow_sweep.csv"))
    header(wsn, s0, ["Spread (bp)", "Borrow (bp a year)", "CAGR", "Volatility", "Sharpe vs 6%", "Max drawdown"])
    for i, rr in enumerate(sw.itertuples(index=False), start=s0 + 1):
        put(wsn, f"A{i}", float(rr[0]), F_INPUT, "0")
        put(wsn, f"B{i}", float(rr[1]), F_INPUT, "0")
        for col, v, fm in zip("CDEF", rr[2:6], (PCT, PCT, NUM2, PCT)):
            put(wsn, f"{col}{i}", float(v), F_INPUT, fm)
    o0 = s0 + len(sw) + 3
    put(wsn, f"A{o0-1}", "Out-of-sample stability (anchored walk-forward)", F_BOLD)
    oos = pd.read_csv(os.path.join(OUT, f"{SLUG}_oos_stability.csv"))
    header(wsn, o0, ["Window", "Observations", "CAGR", "Volatility", "Sharpe", "Max drawdown"])
    for i, rr in enumerate(oos.itertuples(index=False), start=o0 + 1):
        put(wsn, f"A{i}", str(rr[0]), F_INPUT)
        put(wsn, f"B{i}", int(rr[1]), F_INPUT, "#,##0")
        for col, v, fm in zip("CDEF", rr[2:6], (PCT, PCT, NUM2, PCT)):
            put(wsn, f"{col}{i}", float(v), F_INPUT, fm)
    widths(wsn, [30, 18, 12, 12, 20, 16])

    # ------------------------------------------------------------------ Comparators
    wc = wb.create_sheet("Comparators")
    put(wc, "A1", "Comparators used only for the card's must-beat tests", F_TITLE)
    put(wc, "A2", "Not part of the headline. Hardcoded from outputs/lee_swaminathan_1998_comparators_appendix.csv. "
        "High-volume momentum was a comparator looked at after the main result failed; it needs its own card and trial count.", F_NOTE)
    app = pd.read_csv(os.path.join(OUT, f"{SLUG}_comparators_appendix.csv"))
    header(wc, 4, ["Book", "CAGR", "Volatility", "Sharpe vs 6%", "Max drawdown"])
    for i, rr in enumerate(app.itertuples(index=False), start=5):
        put(wc, f"A{i}", str(rr[0]))
        for col, v, fm in zip("BCDE", rr[1:5], (PCT, PCT, NUM2, PCT)):
            put(wc, f"{col}{i}", float(v), F_INPUT, fm)
    widths(wc, [40, 12, 12, 14, 16])

    # ------------------------------------------------------------------ Notes
    wn = wb.create_sheet("Notes")
    put(wn, "A1", "Assumptions and caveats", F_TITLE)
    notes = [
        "Data: NSE bhavcopy and Screener.in only (plus the NIFTY 500 index close for the benchmark). Five years, June 2022 to October 2026.",
        "Turnover uses today's Screener share counts carried back; Screener is not point-in-time and has no page for delisted names (8.8% of universe stock-days have no turnover).",
        "Corporate-action neutralisation flattens any one-day move outside 0.72 to 1.40 and misses small bonuses.",
        "Costs: 30bp round trip. Borrow: 100bp a year on short notional, an unsourced placeholder.",
        "Hurdle for Sharpe: flat 6%, the repo's convention, because no Indian short-rate series is held.",
        "NIFTY 500 is price-return (about 1.3 to 1.5 points a year below total return) and its data ends 2026-09-18.",
        "The card's 15-name rule skipped 35 of 55 months; the book is mostly old tranches carried forward. This is a test of the card as drafted, not of the paper's idea.",
        "Gate B is a human decision. Nothing in this workbook assigns one.",
    ]
    for i, t in enumerate(notes, start=3):
        put(wn, f"A{i}", t)
        wn[f"A{i}"].alignment = Alignment(wrap_text=True, vertical="top")
    wn.column_dimensions["A"].width = 130

    out = os.path.join(OUT, f"{SLUG}_results.xlsx")
    wb.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
