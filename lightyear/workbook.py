"""The results workbook for any Lightyear run, built to the xlsx skill's rules from the run's hand-off files.

Sheets
  Summary        metrics as formulas over named ranges; Gate B with live PASS/FAIL formulas against editable
                 (yellow) thresholds; colour key; two Excel charts
  Returns        start row (100 at the close before the first return), daily returns (blue), value and
                 drawdown formulas (black)
  Comparators    daily returns of the simpler alternatives (long leg alone, equal-weight list, the index...),
                 each with value/drawdown formulas and a formula metrics table          [if comparators.csv]
  Rebalances     one row per rebalance date: names long/short, gross long/short, net, as formulas over Holdings
  Holdings       every position at every rebalance (target weights)                     [if holdings.csv]
  Trades         every change between rebalances: BUY / SELL / SHORT / COVER / ADD / TRIM, with the weight change
                 as a formula                                                           [if trades or holdings]
  Positives & negatives   measured from the returns, from the run's tests, and Claude's analyst read
  Validation, one sheet per table CSV the run listed, Notes
Colour code from universal_backtester/xlsx_style.py. Recalculate afterwards with scripts/xlsx_recalc_libreoffice.py.
"""
import os
import re

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, PatternFill

from universal_backtester.xlsx_style import (DATE, F_BASE, F_BOLD, F_INPUT, F_LINK, F_NOTE, F_SUB, F_TITLE,
                                             FILL_FAIL, FILL_KEY, FILL_PASS, INT, NUM1, NUM2, PCT, PCT2, drawdown_scale,
                                             header, legend, name, pass_fail, put, sign_colour, widths)

from . import gates
from .charts import start_date
from .paths import REPO

C_STRAT, C_BENCH = "1F4E79", "D98324"
FMT = {"pct": PCT2, "num": NUM2, "int": INT, "text": None}
PCT_NAME = re.compile(r"cagr|vol|drawdown|\bdd\b|return|\bret\b|alpha|turnover|weight|%|pct", re.I)
FILL_ADV = PatternFill("solid", bgColor="FFEB9C", fgColor="FFEB9C")
RET_FMT = "0.000%;(0.000%);-"


def _num_or_text(v):
    if isinstance(v, bool):
        return str(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return "" if v is None else str(v)


def _sheet_title(title, used):
    t = re.sub(r"[\[\]\:\*\?\/\\]", " ", str(title)).strip()[:28] or "Table"
    base, k = t, 2
    while t.lower() in used:
        t = f"{base[:25]} {k}"
        k += 1
    used.add(t.lower())
    return t


def _line_chart(title, ws_data, col_s, col_b, last, anchor, ws_target, y_fmt, y_title):
    ch = LineChart()
    ch.title, ch.height, ch.width = title, 8.5, 17
    ch.y_axis.title, ch.y_axis.number_format = y_title, y_fmt
    ch.x_axis.number_format = "mmm yy"
    ch.x_axis.tickLblSkip = max(1, (last - 1) // 8)
    ch.x_axis.delete = ch.y_axis.delete = False
    for col in (col_s, col_b):
        ch.add_data(Reference(ws_data, min_col=col, min_row=1, max_row=last), titles_from_data=True)
    ch.set_categories(Reference(ws_data, min_col=1, min_row=2, max_row=last))
    for s, colour in zip(ch.series, (C_STRAT, C_BENCH)):
        s.graphicalProperties.line.solidFill = colour
        s.graphicalProperties.line.width = 19000
        s.smooth = False
    ch.legend.position = "b"
    ws_target.add_chart(ch, anchor)


def derive_trades(h):
    """Trades implied by target weights at consecutive rebalances (the book drifts with prices in between)."""
    h = h.copy()
    h["date"] = pd.to_datetime(h["date"])
    piv = h.pivot_table(index="date", columns="symbol", values="weight", aggfunc="sum").fillna(0.0).sort_index()
    rows, prev = [], pd.Series(0.0, index=piv.columns)
    for dte, cur in piv.iterrows():
        for sym in piv.columns:
            b, a = float(prev[sym]), float(cur[sym])
            if abs(a - b) < 1e-9:
                continue
            if b == 0:
                act = "BUY" if a > 0 else "SHORT"
            elif a == 0:
                act = "SELL" if b > 0 else "COVER"
            elif (a > 0) != (b > 0):
                act = "FLIP"
            else:
                act = "ADD" if abs(a) > abs(b) else "TRIM"
            rows.append({"date": dte, "symbol": sym, "action": act, "weight_before": b, "weight_after": a})
        prev = cur
    return pd.DataFrame(rows, columns=["date", "symbol", "action", "weight_before", "weight_after"])


def build(run_dir, results, df, title, out_path, hurdle=0.06, holdings=None, trades=None, comparators=None,
          observations=None, review=None):
    s_name = results.get("strategy_name") or "Strategy"
    b_name = results.get("benchmark_name") or "NIFTY 500"
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)
    first, last = 3, n + 2           # row 2 is the start row; data rows 3..n+2
    wb = Workbook()

    # ---------------------------------------------------------------- Returns
    wr = wb.active
    wr.title = "Returns"
    header(wr, 1, ["Date", f"{s_name} daily return", f"{b_name} daily return", f"{s_name} value (100 = start)",
                   f"{b_name} value (100 = start)", f"{s_name} drawdown", f"{b_name} drawdown"], height=44)
    wr.cell(row=2, column=1, value=start_date(df["date"]).to_pydatetime()).number_format = DATE
    wr.cell(row=2, column=1).font = F_INPUT
    for col in (4, 5):
        c = wr.cell(row=2, column=col, value=100)
        c.font, c.number_format = F_INPUT, "0.00"
    for col in (6, 7):
        c = wr.cell(row=2, column=col, value=0)
        c.font, c.number_format = F_BASE, PCT
    put(wr, "B2", "start: value 100 at the close before the first return", F_NOTE)
    for i, row in enumerate(df.itertuples(index=False), start=first):
        wr.cell(row=i, column=1, value=row.date.to_pydatetime()).number_format = DATE
        for col, v in ((2, row.strategy), (3, row.benchmark)):
            c = wr.cell(row=i, column=col, value=0.0 if pd.isna(v) else float(v))
            c.font, c.number_format = F_INPUT, RET_FMT
        wr.cell(row=i, column=4, value=f"=D{i-1}*(1+B{i})")
        wr.cell(row=i, column=5, value=f"=E{i-1}*(1+C{i})")
        wr.cell(row=i, column=6, value=f"=D{i}/MAX(D$2:D{i})-1")
        wr.cell(row=i, column=7, value=f"=E{i}/MAX(E$2:E{i})-1")
        for col in (1, 4, 5, 6, 7):
            wr.cell(row=i, column=col).font = F_BASE
        wr.cell(row=i, column=4).number_format = wr.cell(row=i, column=5).number_format = "0.00"
        wr.cell(row=i, column=6).number_format = wr.cell(row=i, column=7).number_format = PCT
    wr.freeze_panes = "B3"
    widths(wr, [12, 22, 22, 24, 24, 22, 22])
    drawdown_scale(wr, f"F3:G{last}")
    put(wr, f"A{last + 2}", f"Source: {os.path.relpath(os.path.join(run_dir, 'daily_returns.csv'), REPO)} (written by the run). "
        "Blue = hardcoded daily returns, strategy net of costs. Black = formulas. Row 2 is the starting point: 100 at the "
        "close one business day before the first return, so every return counts.", F_NOTE)
    name(wb, "Dates", f"Returns!$A$2:$A${last}")
    name(wb, "Start_Date", "Returns!$A$2")
    for label, col in (("Ret_Strat", "B"), ("Ret_Bench", "C")):
        name(wb, label, f"Returns!${col}${first}:${col}${last}")
    for label, col in (("Val_Strat", "D"), ("Val_Bench", "E"), ("DD_Strat", "F"), ("DD_Bench", "G")):
        name(wb, label, f"Returns!${col}$2:${col}${last}")

    # ---------------------------------------------------------------- Summary
    ws = wb.create_sheet("Summary", 0)
    put(ws, "A1", title, F_TITLE)
    put(ws, "A2", results.get("headline", ""), F_NOTE)
    put(ws, "A4", "Hurdle rate for Sharpe", F_BOLD)
    put(ws, "B4", hurdle, F_INPUT, PCT, FILL_KEY, border=True,
        comment="Key assumption: flat 6% proxy for the Indian short rate (the repo's convention).")
    put(ws, "C4", "Flat 6% proxy, the repo's convention. Change it and the Sharpe row updates.", F_NOTE)
    name(wb, "Hurdle", "Summary!$B$4")
    header(ws, 6, ["Metric", f"Strategy: {s_name}", f"Benchmark: {b_name}", f"Strategy minus {b_name}"])
    mrows = [
        ("Start (value = 100)", "=Start_Date", "=Start_Date", DATE, False, True),
        ("End date", "=MAX(Dates)", "=MAX(Dates)", DATE, False, True),
        ("Years", "=(B8-B7)/365.25", "=(C8-C7)/365.25", NUM2, False, False),
        ("Trading days", "=COUNT(Ret_Strat)", "=COUNT(Ret_Bench)", INT, False, True),
        ("Final value (100 = start)", "=INDEX(Val_Strat,ROWS(Val_Strat))", "=INDEX(Val_Bench,ROWS(Val_Bench))", NUM1, True, True),
        ("CAGR", "=(B11/100)^(1/B9)-1", "=(C11/100)^(1/C9)-1", PCT, True, False),
        ("Annualised volatility", "=STDEV(Ret_Strat)*SQRT(252)", "=STDEV(Ret_Bench)*SQRT(252)", PCT, True, True),
        ("Sharpe vs hurdle", "=(B12-Hurdle)/B13", "=(C12-Hurdle)/C13", NUM2, True, False),
        ("Maximum drawdown", "=-MIN(DD_Strat)", "=-MIN(DD_Bench)", PCT, True, True),
    ]
    for i, (label, fs, fb, fmt, ex, link) in enumerate(mrows, start=7):
        put(ws, f"A{i}", label, F_BASE, border=True)
        put(ws, f"B{i}", fs, F_LINK if link else F_BASE, fmt, border=True)
        put(ws, f"C{i}", fb, F_LINK if link else F_BASE, fmt, border=True)
        put(ws, f"D{i}", f"=B{i}-C{i}" if ex else None, F_BASE, fmt, border=True)
    for r in (11, 12, 14):
        sign_colour(ws, f"D{r}")
    for r in (13, 15):   # more volatility / deeper drawdown than the benchmark is bad
        ws.conditional_formatting.add(f"D{r}", CellIsRule(operator="greaterThan", formula=["0"], fill=FILL_FAIL))
        ws.conditional_formatting.add(f"D{r}", CellIsRule(operator="lessThan", formula=["0"], fill=FILL_PASS))
    put(ws, "A16", "CAGR on calendar years from the start row (days / 365.25); volatility = stdev of daily returns x "
        "sqrt(252). Rows 7 to 15 are formulas over the Returns sheet (green = pulls from another sheet).", F_NOTE)

    header(ws, 18, ["Gate B criterion (ros/governance/gates.py)", "Result", "Value", "Rule", "Threshold (editable)",
                    "Counts toward decision"])
    grows = gates.rows(results["gate_b"].get("criteria", []))
    for i, g in enumerate(grows, start=19):
        put(ws, f"A{i}", g["name"], F_BASE, border=True)
        if g["value"] is not None and g["threshold"] is not None and g["op"]:
            fmt = PCT if "%" in str(g["threshold_raw"]) or "%" in str(g["value_raw"]) else NUM2
            put(ws, f"C{i}", g["value"], F_INPUT, fmt, border=True, comment=g.get("evidence") or None)
            put(ws, f"D{i}", ("|value| " if g["abs"] else "value ") + g["op"], F_INPUT, border=True)
            put(ws, f"E{i}", g["threshold"], F_INPUT, fmt, FILL_KEY, border=True)
            lhs = f"ABS(C{i})" if g["abs"] else f"C{i}"
            put(ws, f"B{i}", f'=IF({lhs}{g["op"]}E{i},"PASS",IF(F{i}="advisory","FAIL (advisory)","FAIL"))',
                F_BOLD, border=True, align=Alignment(horizontal="center"))
        else:
            put(ws, f"C{i}", str(g["value_raw"]), F_INPUT, border=True, comment=g.get("evidence") or None)
            put(ws, f"D{i}", "", F_INPUT, border=True)
            put(ws, f"E{i}", str(g["threshold_raw"]), F_INPUT, border=True)
            put(ws, f"B{i}", g["result"], F_BOLD, border=True, align=Alignment(horizontal="center"),
                comment="Not computed: there was nothing to compare against in this run.")
        put(ws, f"F{i}", "blocking" if g["blocking"] else "advisory", F_INPUT, border=True)
    g_last = 18 + len(grows)
    if grows:
        pass_fail(ws, f"B19:B{g_last}")
        ws.conditional_formatting.add(f"B19:B{g_last}", CellIsRule(operator="equal", formula=['"FAIL (advisory)"'], fill=FILL_ADV))
    r = g_last + 1
    put(ws, f"A{r}", "Blocking criteria passed", F_BOLD, border=True)
    put(ws, f"B{r}", f'=COUNTIFS(B19:B{g_last},"PASS",F19:F{g_last},"blocking")&" of "&COUNTIF(F19:F{g_last},"blocking")',
        F_BOLD, border=True, align=Alignment(horizontal="center"))
    put(ws, f"A{r+1}", "Evidence supports", F_BOLD, border=True)
    put(ws, f"B{r+1}", results.get("evidence_supports", ""), F_BOLD, border=True, align=Alignment(horizontal="center"))
    put(ws, f"A{r+2}", "Decision", F_BOLD, border=True)
    put(ws, f"B{r+2}", "PENDING", F_BOLD, border=True, align=Alignment(horizontal="center"))
    put(ws, f"A{r+3}", "Values are what gate_b() measured in the run (blue). Thresholds are the fund's policy, editable in "
        "yellow: change one and the Result recalculates. 'Advisory' criteria are reported but do not block. "
        "Decision stays PENDING until a named human records one on the Lightyear page.", F_NOTE)
    legend(ws, r + 5)
    widths(ws, [52, 26, 18, 14, 20, 22])
    _line_chart(f"Growth of 100: {s_name} vs {b_name}", wr, 4, 5, last, "H6", ws, "0", "Value (100 = start)")
    _line_chart("Drawdown from peak", wr, 6, 7, last, "H24", ws, "0%", "Drawdown")

    used = {"summary", "returns", "validation", "notes"}

    # ---------------------------------------------------------------- Comparators (daily)
    if comparators is not None and len(comparators.columns) > 1:
        cmp = comparators.set_index("date").reindex(df["date"].values)
        names_c = list(cmp.columns)
        wc = wb.create_sheet("Comparators")
        used.add("comparators")
        put(wc, "A1", "Simpler alternatives, run over the same days", F_TITLE)
        put(wc, "A2", "What the strategy has to beat to be worth its complexity. Daily returns (blue) from comparators.csv; "
            "values, drawdowns and the metrics table are formulas. Appendix only: the headline stays strategy vs NIFTY 500.", F_NOTE)
        header(wc, 4, ["Comparator", "CAGR", "Annualised volatility", "Sharpe vs hurdle", "Maximum drawdown",
                       "CAGR minus strategy"])
        top = 5 + len(names_c) + 2           # data header row
        d0, d1 = top + 2, top + 1 + n        # start row top+1, data rows top+2 .. top+1+n
        hdr = ["Date"]
        for c in names_c:
            hdr += [f"{c} daily return", f"{c} value", f"{c} drawdown"]
        header(wc, top, hdr, height=44)
        wc.cell(row=top + 1, column=1, value=start_date(df["date"]).to_pydatetime()).number_format = DATE
        for j in range(len(names_c)):
            cv = wc.cell(row=top + 1, column=3 + 3 * j, value=100)
            cv.font = F_INPUT
            wc.cell(row=top + 1, column=4 + 3 * j, value=0).number_format = PCT
        for i, dte in enumerate(df["date"], start=d0):
            wc.cell(row=i, column=1, value=dte.to_pydatetime()).number_format = DATE
            for j, c in enumerate(names_c):
                rc, vc, dc = 2 + 3 * j, 3 + 3 * j, 4 + 3 * j
                L = lambda k: wc.cell(row=1, column=k).column_letter
                v = cmp[c].iloc[i - d0]
                cell = wc.cell(row=i, column=rc, value=0.0 if pd.isna(v) else float(v))
                cell.font, cell.number_format = F_INPUT, RET_FMT
                wc.cell(row=i, column=vc, value=f"={L(vc)}{i-1}*(1+{L(rc)}{i})").number_format = "0.00"
                wc.cell(row=i, column=dc, value=f"={L(vc)}{i}/MAX({L(vc)}${top+1}:{L(vc)}{i})-1").number_format = PCT
        for j, c in enumerate(names_c):
            row = 5 + j
            L = lambda k: wc.cell(row=1, column=k).column_letter
            rc, vc, dc = L(2 + 3 * j), L(3 + 3 * j), L(4 + 3 * j)
            put(wc, f"A{row}", c, F_BASE, border=True)
            put(wc, f"B{row}", f"=({vc}{d1}/100)^(1/Summary!$B$9)-1", F_LINK, PCT, border=True)
            put(wc, f"C{row}", f"=STDEV({rc}{d0}:{rc}{d1})*SQRT(252)", F_BASE, PCT, border=True)
            put(wc, f"D{row}", f"=(B{row}-Hurdle)/C{row}", F_LINK, NUM2, border=True)
            put(wc, f"E{row}", f"=-MIN({dc}{d0-1}:{dc}{d1})", F_BASE, PCT, border=True)
            put(wc, f"F{row}", f"=B{row}-Summary!$B$12", F_LINK, PCT, border=True)
        sign_colour(wc, f"F5:F{4 + len(names_c)}")
        wc.freeze_panes = wc.cell(row=top + 1, column=2)
        widths(wc, [34] + [18] * (3 * len(names_c)))

    # ---------------------------------------------------------------- Holdings, Rebalances, Trades
    if holdings is not None and len(holdings):
        h = holdings.copy()
        h["date"] = pd.to_datetime(h["date"])
        if "leg" not in h.columns:
            h["leg"] = h["weight"].apply(lambda w: "long" if w > 0 else "short")
        h = h.sort_values(["date", "leg", "weight"], ascending=[True, True, False]).reset_index(drop=True)
        wh = wb.create_sheet("Holdings")
        used.add("holdings")
        extra = [c for c in h.columns if c not in ("date", "symbol", "leg", "weight")]
        put(wh, "A1", "Every position at every rebalance", F_TITLE)
        put(wh, "A2", "Target weights as a fraction of capital (shorts negative), from holdings.csv written by the run. "
            "Between rebalances the book drifts with prices.", F_NOTE)
        header(wh, 4, ["Rebalance date", "Symbol", "Leg", "Target weight"] + extra)
        h0 = 5
        for i, row in enumerate(h.itertuples(index=False), start=h0):
            put(wh, f"A{i}", row.date.to_pydatetime(), F_INPUT, DATE)
            put(wh, f"B{i}", str(row.symbol), F_INPUT)
            put(wh, f"C{i}", str(row.leg), F_INPUT)
            put(wh, f"D{i}", float(row.weight), F_INPUT, PCT)
            for k, col in enumerate(extra):
                v = _num_or_text(getattr(row, col))
                c = wh.cell(row=i, column=5 + k, value=v)
                c.font = F_INPUT
                if isinstance(v, float):
                    c.number_format = NUM2
        h1 = h0 + len(h) - 1
        sign_colour(wh, f"D{h0}:D{h1}")
        wh.freeze_panes = "A5"
        wh.auto_filter.ref = f"A4:{wh.cell(row=4, column=4 + len(extra)).column_letter}{h1}"
        widths(wh, [14, 16, 9, 14] + [16] * len(extra))
        name(wb, "H_Date", f"Holdings!$A${h0}:$A${h1}")
        name(wb, "H_Leg", f"Holdings!$C${h0}:$C${h1}")
        name(wb, "H_Weight", f"Holdings!$D${h0}:$D${h1}")

        wb2 = wb.create_sheet("Rebalances")
        used.add("rebalances")
        put(wb2, "A1", "What the strategy held at each rebalance", F_TITLE)
        put(wb2, "A2", "Counts and gross exposures are formulas over the Holdings sheet.", F_NOTE)
        header(wb2, 4, ["Rebalance date", "Names long", "Names short", "Gross long", "Gross short", "Net exposure",
                        "Gross exposure", "Largest single weight"])
        for i, dte in enumerate(sorted(h["date"].unique()), start=5):
            put(wb2, f"A{i}", pd.Timestamp(dte).to_pydatetime(), F_INPUT, DATE, border=True)
            put(wb2, f"B{i}", f'=COUNTIFS(H_Date,A{i},H_Leg,"long")', F_LINK, INT, border=True)
            put(wb2, f"C{i}", f'=COUNTIFS(H_Date,A{i},H_Leg,"short")', F_LINK, INT, border=True)
            put(wb2, f"D{i}", f'=SUMIFS(H_Weight,H_Date,A{i},H_Leg,"long")', F_LINK, PCT, border=True)
            put(wb2, f"E{i}", f'=-SUMIFS(H_Weight,H_Date,A{i},H_Leg,"short")', F_LINK, PCT, border=True)
            put(wb2, f"F{i}", f"=D{i}-E{i}", F_BASE, PCT, border=True)
            put(wb2, f"G{i}", f"=D{i}+E{i}", F_BASE, PCT, border=True)
            put(wb2, f"H{i}", f"=SUMPRODUCT(MAX((H_Date=A{i})*ABS(H_Weight)))", F_LINK, PCT, border=True)
        r_last = 4 + h["date"].nunique()
        wb2.conditional_formatting.add(f"B5:B{r_last}", CellIsRule(operator="lessThan", formula=["5"], fill=FILL_ADV))
        wb2.conditional_formatting.add(f"H5:H{r_last}", CellIsRule(operator="greaterThan", formula=["0.25"], fill=FILL_FAIL))
        put(wb2, f"A{r_last + 2}", "Amber: fewer than 5 names long. Red: one position above 25% of capital (concentration risk).", F_NOTE)
        widths(wb2, [16, 12, 12, 12, 12, 13, 14, 20])
        if trades is None:
            trades = derive_trades(h)
            t_note = "Derived by Lightyear from the change in target weights between rebalances (the run wrote no trades.csv)."
        else:
            t_note = "From trades.csv written by the run."
    else:
        t_note = "From trades.csv written by the run."

    if trades is not None and len(trades):
        t = trades.copy()
        t["date"] = pd.to_datetime(t["date"])
        wt = wb.create_sheet("Trades")
        used.add("trades")
        put(wt, "A1", "Every trade", F_TITLE)
        put(wt, "A2", t_note + " Weights are fractions of capital; shorts negative. Change = after minus before (formula).", F_NOTE)
        cols = ["date", "symbol", "action", "weight_before", "weight_after"]
        extra = [c for c in t.columns if c not in cols]
        header(wt, 4, ["Date", "Symbol", "Action", "Weight before", "Weight after", "Change"] + extra)
        for i, row in enumerate(t.itertuples(index=False), start=5):
            put(wt, f"A{i}", row.date.to_pydatetime(), F_INPUT, DATE)
            put(wt, f"B{i}", str(row.symbol), F_INPUT)
            put(wt, f"C{i}", str(row.action), F_INPUT)
            put(wt, f"D{i}", float(row.weight_before), F_INPUT, PCT)
            put(wt, f"E{i}", float(row.weight_after), F_INPUT, PCT)
            put(wt, f"F{i}", f"=E{i}-D{i}", F_BASE, PCT)
            for k, col in enumerate(extra):
                v = _num_or_text(getattr(row, col))
                c = wt.cell(row=i, column=7 + k, value=v)
                c.font = F_INPUT
        t1 = 4 + len(t)
        sign_colour(wt, f"F5:F{t1}")
        wt.freeze_panes = "A5"
        wt.auto_filter.ref = f"A4:{wt.cell(row=4, column=6 + len(extra)).column_letter}{t1}"
        put(wt, f"H2", "Total trades", F_BOLD)
        put(wt, f"I2", f"=COUNTA(B5:B{t1})", F_BASE, INT)
        widths(wt, [14, 16, 10, 14, 14, 12] + [14] * len(extra))

    # ---------------------------------------------------------------- Positives & negatives
    wp = wb.create_sheet("Positives & negatives")
    used.add("positives & negatives")
    put(wp, "A1", "What works and what doesn't", F_TITLE)
    put(wp, "A2", "Measured = calculated by Lightyear from the daily returns. From the tests = the run's own validation. "
        "Analyst read = Claude's review of all the results (an opinion, not a decision).", F_NOTE)
    header(wp, 4, ["", "Point", "Source"])
    rr = 5
    obs = observations or {}
    groups = [("+", obs.get("positives", []), "measured"), ("+", results.get("strengths", []) or [], "from the tests"),
              ("+", (review or {}).get("strengths", []), "analyst read"),
              ("-", obs.get("negatives", []), "measured"), ("-", results.get("weaknesses", []) or [], "from the tests"),
              ("-", (review or {}).get("weaknesses", []), "analyst read"),
              ("!", (review or {}).get("red_flags", []), "analyst read: check this")]
    for sign, items, src in groups:
        for text in items:
            fill = FILL_PASS if sign == "+" else (FILL_FAIL if sign == "-" else FILL_ADV)
            put(wp, f"A{rr}", {"+": "Positive", "-": "Negative", "!": "Red flag"}[sign], F_BOLD, fill=fill, border=True)
            put(wp, f"B{rr}", str(text), F_BASE, border=True, align=Alignment(wrap_text=True, vertical="top"))
            put(wp, f"C{rr}", src, F_NOTE, border=True)
            rr += 1
    if review and review.get("verdict"):
        put(wp, f"A{rr + 1}", "Analyst read", F_SUB)
        put(wp, f"B{rr + 1}", review["verdict"], F_BASE, align=Alignment(wrap_text=True, vertical="top"))
    widths(wp, [12, 110, 22])

    # ---------------------------------------------------------------- Validation + assumptions
    wv = wb.create_sheet("Validation")
    put(wv, "A1", "Validation, as computed by the run's code", F_TITLE)
    put(wv, "A2", "Blue = hardcoded from results.json; the source column names the file or function.", F_NOTE)
    header(wv, 4, ["Measure", "Value", "Source"])
    row = 5
    for v in results.get("validation", []) or []:
        val = _num_or_text(v.get("value"))
        fmt = FMT.get(v.get("format", "num"), NUM2) if isinstance(val, float) else None
        put(wv, f"A{row}", v.get("label", ""), border=True)
        put(wv, f"B{row}", val, F_INPUT, fmt, border=True)
        put(wv, f"C{row}", v.get("source", ""), F_NOTE, border=True)
        row += 1
    if results.get("assumptions"):
        row += 1
        put(wv, f"A{row}", "Assumptions used by the run", F_SUB)
        row += 1
        header(wv, row, ["Assumption", "Value", "Source / note"])
        row += 1
        for a in results["assumptions"]:
            val = _num_or_text(a.get("value"))
            put(wv, f"A{row}", a.get("label", ""), border=True)
            put(wv, f"B{row}", val, F_INPUT, FMT.get(a.get("format", "num"), NUM2) if isinstance(val, float) else None,
                FILL_KEY, border=True)
            put(wv, f"C{row}", a.get("note", ""), F_NOTE, border=True)
            row += 1
    widths(wv, [60, 16, 70])

    # ---------------------------------------------------------------- one sheet per table
    for t in results.get("tables", []) or []:
        p = t["csv"] if os.path.isabs(t["csv"]) else os.path.join(REPO, t["csv"])
        tab = pd.read_csv(p)
        st = wb.create_sheet(_sheet_title(t.get("title", "Table"), used))
        put(st, "A1", t.get("title", ""), F_TITLE)
        put(st, "A2", f"Hardcoded from {t['csv']}. {t.get('note', '')}", F_NOTE)
        header(st, 4, [str(c) for c in tab.columns])
        fmts = []
        for col in tab.columns:
            s = pd.to_numeric(tab[col], errors="coerce").dropna()
            if PCT_NAME.search(str(col)) and len(s) and (s.abs() <= 5).all():
                fmts.append(PCT)
            elif len(s) and (s == s.round()).all():
                fmts.append(INT)
            else:
                fmts.append(NUM2)
        for i, rr_ in enumerate(tab.itertuples(index=False), start=5):
            for j, v in enumerate(rr_, start=1):
                val = _num_or_text(v)
                c = put(st, f"{st.cell(row=i, column=j).column_letter}{i}", val,
                        F_INPUT if isinstance(val, float) else F_BASE, border=True)
                if isinstance(val, float):
                    c.number_format = fmts[j - 1]
        widths(st, [max(14, min(40, len(str(c)) + 4)) for c in tab.columns])

    # ---------------------------------------------------------------- Notes
    wn = wb.create_sheet("Notes")
    put(wn, "A1", "Assumptions and caveats", F_TITLE)
    notes = list(results.get("notes", []) or []) + [
        "Data: NSE bhavcopy and Screener.in only, plus the NIFTY 500 index for the benchmark. Screener values are "
        "today's restated figures carried back, not point-in-time.",
        "Gate B is a human decision. Nothing in this workbook assigns one."]
    for i, t in enumerate(notes, start=3):
        put(wn, f"A{i}", t, align=Alignment(wrap_text=True, vertical="top"))
    wn.column_dimensions["A"].width = 130

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
    wb["Summary"].sheet_properties.tabColor = "1F4E79"
    wb.save(out_path)
    return out_path
