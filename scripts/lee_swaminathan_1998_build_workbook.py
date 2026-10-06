"""Results workbook for the Lee & Swaminathan run, built to the xlsx skill's rules.

  - Colour coded (see universal_backtester/xlsx_style.py): blue = hardcoded, black = formula,
    green = cross-sheet formula, yellow = key assumption, green/red fills for pass/fail and sign.
  - Summary metrics are FORMULAS over the Returns sheet, written with defined names
    (Hurdle, Ret_Strat, Val_Strat, DD_Strat ...) so they read as =(CAGR-Hurdle)/Vol.
  - Everything the backtest code computed that cannot be a formula here (bootstrap intervals,
    deflated Sharpe, factor fingerprint, Gate B criteria) is a hardcoded blue value with its source beside it.
  - Headline = the strategy against NIFTY 500, nothing else. Comparators sit on their own sheet.

usage: python scripts/lee_swaminathan_1998_build_workbook.py
Then recalculate with the skill's recalc.py (needs LibreOffice) and check total_errors is 0. Without
LibreOffice the file still calculates when opened in Excel; cached values are simply absent until then.
"""
import json
import os
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from universal_backtester.xlsx_style import (BOX, DATE, F_BASE, F_BOLD, F_INPUT, F_LINK, F_NOTE, F_SUB,  # noqa: E402
                                             F_TITLE, FILL_KEY, INT, NUM1, NUM2, PCT, PCT2, band,
                                             drawdown_scale, header, legend, name, pass_fail, put,
                                             sign_colour, widths)

OUT = os.path.join(REPO, "outputs")
SLUG = "lee_swaminathan_1998"
STRAT_COL, BENCH_COL = "MAIN R10V1-R1V3 (long-short)", "NIFTY 500"
STRAT_LABEL = "R10V1 - R1V3 (long-short)"
C_STRAT, C_BENCH = "1F4E79", "D98324"


def _num_or_text(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def _line_chart(title, ws_data, col_s, col_b, last, anchor, ws_target, y_fmt, y_title):
    ch = LineChart()
    ch.title, ch.height, ch.width = title, 8.5, 17
    ch.y_axis.title, ch.y_axis.number_format = y_title, y_fmt
    ch.x_axis.number_format, ch.x_axis.tickLblSkip = "mmm yy", 126
    ch.x_axis.delete = ch.y_axis.delete = False
    for col, colour in ((col_s, C_STRAT), (col_b, C_BENCH)):
        ch.add_data(Reference(ws_data, min_col=col, min_row=1, max_row=last), titles_from_data=True)
    ch.set_categories(Reference(ws_data, min_col=1, min_row=2, max_row=last))
    for s, colour in zip(ch.series, (C_STRAT, C_BENCH)):
        s.graphicalProperties.line.solidFill = colour
        s.graphicalProperties.line.width = 19000
        s.smooth = False
    ch.legend.position = "b"
    ws_target.add_chart(ch, anchor)


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
                   f"{STRAT_LABEL} drawdown", "NIFTY 500 drawdown"], height=44)
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
    drawdown_scale(wr, f"F2:G{last}")
    put(wr, f"A{n + 3}", "Source: outputs/lee_swaminathan_1998_daily_returns.csv, written by "
        "scripts/lee_swaminathan_1998_india_backtest.py. Blue = hardcoded daily returns (net of 30bp costs and 100bp borrow "
        "inside the strategy; NIFTY 500 is price-return, last 10 trading days carried forward because the index data ends "
        "2026-09-18). Black = formulas. Drawdown is shaded red at its deepest.", F_NOTE)

    for label, col in (("Dates", "A"), ("Ret_Strat", "B"), ("Ret_Bench", "C"), ("Val_Strat", "D"),
                       ("Val_Bench", "E"), ("DD_Strat", "F"), ("DD_Bench", "G")):
        name(wb, label, f"Returns!${col}$2:${col}${last}")

    # ------------------------------------------------------------------ Summary
    ws = wb.create_sheet("Summary", 0)
    put(ws, "A1", "Lee & Swaminathan (1998) price momentum and trading volume, India quick test", F_TITLE)
    put(ws, "A2", "Card run as drafted. Strategy against NIFTY 500 only. Decision: PENDING (Gate B is a human decision).", F_NOTE)
    put(ws, "A4", "Hurdle rate for Sharpe", F_BOLD)
    put(ws, "B4", 0.06, F_INPUT, PCT, FILL_KEY, border=True,
        comment="Key assumption: flat 6% proxy for the Indian short rate (the repo's convention; no real series is held).")
    put(ws, "C4", "Flat 6% proxy, the repo's convention. Change it and the Sharpe row updates.", F_NOTE)
    name(wb, "Hurdle", "Summary!$B$4")
    header(ws, 6, ["Metric", STRAT_LABEL, "NIFTY 500", "Strategy minus NIFTY 500"])
    mrows = [  # label, strategy formula, benchmark formula, format, show excess
        ("Start date", "=MIN(Dates)", "=MIN(Dates)", DATE, False),
        ("End date", "=MAX(Dates)", "=MAX(Dates)", DATE, False),
        ("Years", "=(B8-B7)/365.25", "=(C8-C7)/365.25", NUM2, False),
        ("Trading days", "=COUNT(Ret_Strat)", "=COUNT(Ret_Bench)", INT, False),
        ("Final value (100 = start)", "=INDEX(Val_Strat,ROWS(Val_Strat))", "=INDEX(Val_Bench,ROWS(Val_Bench))", NUM1, True),
        ("CAGR", "=(B11/INDEX(Val_Strat,1))^(1/B9)-1", "=(C11/INDEX(Val_Bench,1))^(1/C9)-1", PCT, True),
        ("Annualised volatility", "=STDEV(Ret_Strat)*SQRT(252)", "=STDEV(Ret_Bench)*SQRT(252)", PCT, False),
        ("Sharpe vs hurdle", "=(B12-Hurdle)/B13", "=(C12-Hurdle)/C13", NUM2, True),
        ("Maximum drawdown", "=-MIN(DD_Strat)", "=-MIN(DD_Bench)", PCT, False),
    ]
    for i, (label, fs, fb, fmt, ex) in enumerate(mrows, start=7):
        put(ws, f"A{i}", label, F_BASE, border=True)
        put(ws, f"B{i}", fs, F_LINK if "Dates" in fs or "Ret_" in fs or "Val_" in fs or "DD_" in fs else F_BASE, fmt, border=True)
        put(ws, f"C{i}", fb, F_LINK if "Dates" in fb or "Ret_" in fb or "Val_" in fb or "DD_" in fb else F_BASE, fmt, border=True)
        if ex:
            put(ws, f"D{i}", f"=B{i}-C{i}", F_BASE, fmt, border=True)
        else:
            put(ws, f"D{i}", None, F_BASE, border=True)
    for r in (11, 12, 14):
        sign_colour(ws, f"D{r}")
    put(ws, "A16", "CAGR uses calendar years (days / 365.25); volatility is the standard deviation of daily returns "
        "times the square root of 252, matching universal_backtester/metrics.py. Rows 7 to 15 are formulas over the Returns sheet.",
        F_NOTE)

    header(ws, 18, ["Gate B criterion (computed by ros/governance/gates.py)", "Result", "Value", "Threshold"])
    gb = res["gate_b"]["criteria"]
    for i, c in enumerate(gb, start=19):
        put(ws, f"A{i}", c["name"], F_BASE, border=True)
        put(ws, f"B{i}", "PASS" if c["passed"] else ("FAIL" if c["blocking"] else "not computed"),
            F_BOLD, border=True, align=Alignment(horizontal="center"))
        put(ws, f"C{i}", _num_or_text(c.get("value")), F_INPUT, NUM2, border=True)
        put(ws, f"D{i}", _num_or_text(c.get("threshold")), F_INPUT, NUM2, border=True)
    g_last = 18 + len(gb)
    pass_fail(ws, f"B19:B{g_last}")
    r = g_last + 1
    put(ws, f"A{r}", "Decision", F_BOLD, border=True)
    put(ws, f"B{r}", res["gate_b"]["decision"], F_BOLD, border=True, align=Alignment(horizontal="center"))
    put(ws, f"A{r+1}", "Source: outputs/lee_swaminathan_1998_results.json (gate_b); blue values are hardcoded from that run. "
        "The mandate criterion was not run on this script path, so it has no row. Decision stays PENDING until a named human records one.",
        F_NOTE)
    legend(ws, r + 3)
    widths(ws, [52, 26, 18, 26])
    _line_chart("Growth of 100", wr, 4, 5, last, "F6", ws, "0", "Value (100 = start)")
    _line_chart("Drawdown from peak", wr, 6, 7, last, "F24", ws, "0%", "Drawdown")

    # ------------------------------------------------------------------ Validation
    wv = wb.create_sheet("Validation")
    put(wv, "A1", "Validation, as computed by the backtest code", F_TITLE)
    put(wv, "A2", "Hardcoded from outputs/lee_swaminathan_1998_results.json and the run log. Block-bootstrap block length is "
        "126 days (K = 6 months), 1,000 resamples, seed 0.", F_NOTE)
    header(wv, 4, ["Test", "Point", "90% low", "90% high", "Interval vs zero"])
    bm, pv, pe = res["bootstrap_main"], res["paired_vs_plain"], res["paired_vs_equal_weight"]
    ph = res["paired_hv_vs_plain"]
    vrows = [
        ("Strategy Sharpe (zero hurdle)", bm),
        ("Paired: strategy minus plain momentum", pv),
        ("Paired: strategy minus equal-weight universe", pe),
        ("Paired: high-volume momentum minus plain momentum", ph),
    ]
    for i, (lab, d) in enumerate(vrows, start=5):
        put(wv, f"A{i}", lab, border=True)
        for col, k in zip("BCD", ("point", "ci_low", "ci_high")):
            put(wv, f"{col}{i}", float(d[k]), F_INPUT, NUM2, border=True)
        put(wv, f"E{i}", f'=IF(C{i}>0,"excludes zero, positive",IF(D{i}<0,"excludes zero, negative","spans zero"))',
            F_BASE, border=True)
    sign_colour(wv, "B5:B8")
    put(wv, "A10", "Deflated Sharpe probability (48 trials, trial Sharpe std 0.3)", border=True)
    put(wv, "B10", float(res["deflated_sharpe"]), F_INPUT, NUM2, border=True)
    fp = res.get("factor_fingerprint", {})
    put(wv, "A11", "Factor fingerprint alpha, annualised (vs VALUE 50, MOMENTUM 50)", border=True)
    put(wv, "B11", float(fp.get("alpha_ann", float("nan"))), F_INPUT, PCT2, border=True)
    put(wv, "A12", "Factor fingerprint alpha HAC t-statistic", border=True)
    put(wv, "B12", float(fp.get("alpha_t_hac", float("nan"))), F_INPUT, NUM2, border=True)
    put(wv, "A13", "Factor fingerprint R-squared", border=True)
    put(wv, "B13", float(fp.get("r_squared", float("nan"))), F_INPUT, NUM2, border=True)
    put(wv, "C12", '=IF(ABS(B12)>=2,"significant at about 5%","not significant")', F_BASE)
    put(wv, "A15", "Allocator diagnostics (the card's 15-name rule applied literally)", F_SUB)
    md = res["main_diagnostics"]
    diag = [("Tranches formed", md["tranches_formed"]), ("Months skipped for warmup", md["months_skipped_warmup"]),
            ("Months skipped, a needed cell under 15 names", md["months_skipped_thin"]),
            ("Mean names in long cell when formed", md["mean_long_names_formed"]),
            ("Mean names in short cell when formed", md["mean_short_names_formed"])]
    for i, (lab, v) in enumerate(diag, start=16):
        put(wv, f"A{i}", lab, border=True)
        put(wv, f"B{i}", float(v), F_INPUT, NUM1 if isinstance(v, float) else INT, border=True)
    put(wv, "A21", "Share of months skipped as thin", border=True)
    put(wv, "B21", "=B18/(B16+B17+B18)", F_BASE, PCT, border=True)
    put(wv, "A22", "A skipped month carries the book forward unchanged, so old tranches do not expire while months are skipped. "
        "Share skipped = thin months over (formed + warmup + thin).", F_NOTE)
    widths(wv, [62, 14, 14, 14, 28])

    # ------------------------------------------------------------------ Sensitivity
    wsn = wb.create_sheet("Sensitivity")
    put(wsn, "A1", "Sensitivity of the strategy", F_TITLE)
    put(wsn, "A2", "Hardcoded from the CSVs the backtest script wrote (outputs/lee_swaminathan_1998_*.csv).", F_NOTE)
    jk = pd.read_csv(os.path.join(OUT, f"{SLUG}_sensitivity_jk.csv"))
    put(wsn, "A3", "Holding and ranking period", F_SUB)
    header(wsn, 4, ["J = K (months)", "CAGR", "Volatility", "Sharpe (zero hurdle)", "Max drawdown"])
    for i, rr in enumerate(jk.itertuples(index=False), start=5):
        put(wsn, f"A{i}", int(rr[0]), F_INPUT, "0", border=True)
        for col, v, fm in zip("BCDE", rr[1:5], (PCT, PCT, NUM2, PCT)):
            put(wsn, f"{col}{i}", float(v), F_INPUT, fm, border=True)
    sign_colour(wsn, f"B5:B{4+len(jk)}")
    sign_colour(wsn, f"D5:D{4+len(jk)}")
    s0 = 5 + len(jk) + 3
    put(wsn, f"A{s0-1}", "Cost and borrow sweep", F_SUB)
    sw = pd.read_csv(os.path.join(OUT, f"{SLUG}_cost_borrow_sweep.csv"))
    header(wsn, s0, ["Spread (bp)", "Borrow (bp a year)", "CAGR", "Volatility", "Sharpe vs 6%", "Max drawdown"])
    for i, rr in enumerate(sw.itertuples(index=False), start=s0 + 1):
        put(wsn, f"A{i}", float(rr[0]), F_INPUT, "0", border=True)
        put(wsn, f"B{i}", float(rr[1]), F_INPUT, "0", border=True)
        for col, v, fm in zip("CDEF", rr[2:6], (PCT, PCT, NUM2, PCT)):
            put(wsn, f"{col}{i}", float(v), F_INPUT, fm, border=True)
    sign_colour(wsn, f"C{s0+1}:C{s0+len(sw)}")
    sign_colour(wsn, f"E{s0+1}:E{s0+len(sw)}")
    o0 = s0 + len(sw) + 4
    put(wsn, f"A{o0-1}", "Out-of-sample stability (anchored walk-forward)", F_SUB)
    oos = pd.read_csv(os.path.join(OUT, f"{SLUG}_oos_stability.csv"))
    header(wsn, o0, ["Window", "Observations", "CAGR", "Volatility", "Sharpe", "Max drawdown"])
    for i, rr in enumerate(oos.itertuples(index=False), start=o0 + 1):
        put(wsn, f"A{i}", str(rr[0]), F_INPUT, border=True)
        put(wsn, f"B{i}", int(rr[1]), F_INPUT, INT, border=True)
        for col, v, fm in zip("CDEF", rr[2:6], (PCT, PCT, NUM2, PCT)):
            put(wsn, f"{col}{i}", float(v), F_INPUT, fm, border=True)
    sign_colour(wsn, f"C{o0+1}:C{o0+len(oos)}")
    sign_colour(wsn, f"E{o0+1}:E{o0+len(oos)}")
    widths(wsn, [30, 18, 12, 12, 20, 16])

    # ------------------------------------------------------------------ Comparators
    wc = wb.create_sheet("Comparators")
    put(wc, "A1", "Comparators used only for the card's must-beat tests", F_TITLE)
    put(wc, "A2", "Not part of the headline. Hardcoded from outputs/lee_swaminathan_1998_comparators_appendix.csv. "
        "High-volume momentum was a comparator looked at after the main result failed; it needs its own card and trial count.", F_NOTE)
    app = pd.read_csv(os.path.join(OUT, f"{SLUG}_comparators_appendix.csv"))
    header(wc, 4, ["Book", "CAGR", "Volatility", "Sharpe vs 6%", "Max drawdown", "Sharpe minus strategy"])
    for i, rr in enumerate(app.itertuples(index=False), start=5):
        put(wc, f"A{i}", str(rr[0]), border=True)
        for col, v, fm in zip("BCDE", rr[1:5], (PCT, PCT, NUM2, PCT)):
            put(wc, f"{col}{i}", float(v), F_INPUT, fm, border=True)
        put(wc, f"F{i}", f"=D{i}-Summary!$B$14", F_LINK, NUM2, border=True)
    sign_colour(wc, f"F5:F{4+len(app)}")
    widths(wc, [40, 12, 12, 14, 16, 22])

    # ------------------------------------------------------------------ Notes
    wn = wb.create_sheet("Notes")
    put(wn, "A1", "Assumptions and caveats", F_TITLE)
    notes = [
        "Data: NSE bhavcopy and Screener.in only (plus the NIFTY 500 index close for the benchmark). Five years, June 2022 to October 2026.",
        "Turnover uses today's Screener share counts carried back; Screener is not point-in-time and has no page for delisted names (8.8% of universe stock-days have no turnover).",
        "Corporate-action neutralisation flattens any one-day move outside 0.72 to 1.40 and misses small bonuses.",
        "Costs: 30bp round trip. Borrow: 100bp a year on short notional, an unsourced placeholder.",
        "Hurdle for Sharpe: flat 6% (Summary!B4, yellow), the repo's convention, because no Indian short-rate series is held.",
        "NIFTY 500 is price-return (about 1.3 to 1.5 points a year below total return) and its data ends 2026-09-18.",
        "The card's 15-name rule skipped 35 of 55 months; the book is mostly old tranches carried forward. This is a test of the card as drafted, not of the paper's idea.",
        "Gate B is a human decision. Nothing in this workbook assigns one.",
    ]
    for i, t in enumerate(notes, start=3):
        put(wn, f"A{i}", t, align=Alignment(wrap_text=True, vertical="top"))
    wn.column_dimensions["A"].width = 130

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
    wb["Summary"].sheet_properties.tabColor = "1F4E79"
    wb["Returns"].sheet_properties.tabColor = "0000FF"

    out = os.path.join(OUT, f"{SLUG}_results.xlsx")
    wb.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
