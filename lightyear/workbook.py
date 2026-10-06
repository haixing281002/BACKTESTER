"""The results workbook for any Lightyear run, built to the xlsx skill's rules from the run's hand-off files.

Sheets: Summary (formulas over named ranges, Gate B, colour key, two charts), Returns (blue data, black
formulas), Validation, one sheet per table CSV the run listed, Notes. Colour code from
universal_backtester/xlsx_style.py. Recalculate afterwards with scripts/xlsx_recalc_libreoffice.py.
"""
import os
import re

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment

from universal_backtester.xlsx_style import (DATE, F_BASE, F_BOLD, F_INPUT, F_LINK, F_NOTE, F_SUB, F_TITLE,
                                             FILL_KEY, INT, NUM1, NUM2, PCT, PCT2, drawdown_scale, header,
                                             legend, name, pass_fail, put, sign_colour, widths)

from .paths import REPO

C_STRAT, C_BENCH = "1F4E79", "D98324"
FMT = {"pct": PCT2, "num": NUM2, "int": INT, "text": None}
PCT_NAME = re.compile(r"cagr|vol|drawdown|\bdd\b|return|\bret\b|alpha|turnover|weight|%|pct", re.I)


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


def build(run_dir, results, df, title, out_path, hurdle=0.06):
    s_name = results.get("strategy_name") or "Strategy"
    b_name = results.get("benchmark_name") or "NIFTY 500"
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)
    last = n + 1
    wb = Workbook()

    # ---------------------------------------------------------------- Returns
    wr = wb.active
    wr.title = "Returns"
    header(wr, 1, ["Date", f"{s_name} daily return", f"{b_name} daily return", f"{s_name} value (100 = start)",
                   f"{b_name} value (100 = start)", f"{s_name} drawdown", f"{b_name} drawdown"], height=44)
    for i, row in enumerate(df.itertuples(index=False), start=2):
        wr.cell(row=i, column=1, value=row.date.to_pydatetime()).number_format = DATE
        for col, v in ((2, row.strategy), (3, row.benchmark)):
            c = wr.cell(row=i, column=col, value=0.0 if pd.isna(v) else float(v))
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
    put(wr, f"A{n + 3}", f"Source: {os.path.relpath(os.path.join(run_dir, 'daily_returns.csv'), REPO)} (written by the run). "
        "Blue = hardcoded daily returns, strategy net of costs. Black = formulas. Drawdown shaded red at its deepest.", F_NOTE)
    for label, col in (("Dates", "A"), ("Ret_Strat", "B"), ("Ret_Bench", "C"), ("Val_Strat", "D"),
                       ("Val_Bench", "E"), ("DD_Strat", "F"), ("DD_Bench", "G")):
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
    header(ws, 6, ["Metric", s_name, b_name, f"Strategy minus {b_name}"])
    mrows = [
        ("Start date", "=MIN(Dates)", "=MIN(Dates)", DATE, False, True),
        ("End date", "=MAX(Dates)", "=MAX(Dates)", DATE, False, True),
        ("Years", "=(B8-B7)/365.25", "=(C8-C7)/365.25", NUM2, False, False),
        ("Trading days", "=COUNT(Ret_Strat)", "=COUNT(Ret_Bench)", INT, False, True),
        ("Final value (100 = start)", "=INDEX(Val_Strat,ROWS(Val_Strat))", "=INDEX(Val_Bench,ROWS(Val_Bench))", NUM1, True, True),
        ("CAGR", "=(B11/INDEX(Val_Strat,1))^(1/B9)-1", "=(C11/INDEX(Val_Bench,1))^(1/C9)-1", PCT, True, True),
        ("Annualised volatility", "=STDEV(Ret_Strat)*SQRT(252)", "=STDEV(Ret_Bench)*SQRT(252)", PCT, False, True),
        ("Sharpe vs hurdle", "=(B12-Hurdle)/B13", "=(C12-Hurdle)/C13", NUM2, True, False),
        ("Maximum drawdown", "=-MIN(DD_Strat)", "=-MIN(DD_Bench)", PCT, False, True),
    ]
    for i, (label, fs, fb, fmt, ex, link) in enumerate(mrows, start=7):
        put(ws, f"A{i}", label, F_BASE, border=True)
        put(ws, f"B{i}", fs, F_LINK if link else F_BASE, fmt, border=True)
        put(ws, f"C{i}", fb, F_LINK if link else F_BASE, fmt, border=True)
        put(ws, f"D{i}", f"=B{i}-C{i}" if ex else None, F_BASE, fmt, border=True)
    for r in (11, 12, 14):
        sign_colour(ws, f"D{r}")
    put(ws, "A16", "CAGR on calendar years (days / 365.25); volatility = stdev of daily returns x sqrt(252). "
        "Rows 7 to 15 are formulas over the Returns sheet (green = pulls from another sheet).", F_NOTE)

    header(ws, 18, ["Gate B criterion (ros/governance/gates.py)", "Result", "Value", "Threshold"])
    crit = results["gate_b"].get("criteria", [])
    for i, c in enumerate(crit, start=19):
        res = "PASS" if c.get("passed") else ("FAIL" if c.get("blocking", True) else "not computed")
        put(ws, f"A{i}", c.get("name", ""), F_BASE, border=True)
        put(ws, f"B{i}", res, F_BOLD, border=True, align=Alignment(horizontal="center"))
        put(ws, f"C{i}", _num_or_text(c.get("value")), F_INPUT, NUM2, border=True)
        put(ws, f"D{i}", _num_or_text(c.get("threshold")), F_INPUT, NUM2, border=True)
    g_last = 18 + len(crit)
    if crit:
        pass_fail(ws, f"B19:B{g_last}")
    r = g_last + 1
    put(ws, f"A{r}", "Evidence supports", F_BOLD, border=True)
    put(ws, f"B{r}", results.get("evidence_supports", ""), F_BOLD, border=True, align=Alignment(horizontal="center"))
    put(ws, f"A{r+1}", "Decision", F_BOLD, border=True)
    put(ws, f"B{r+1}", "PENDING", F_BOLD, border=True, align=Alignment(horizontal="center"))
    put(ws, f"A{r+2}", "Source: results.json gate_b, computed by gate_b() in the run. Decision stays PENDING until a "
        "named human records one on the Lightyear page.", F_NOTE)
    legend(ws, r + 4)
    widths(ws, [52, 26, 18, 26])
    _line_chart("Growth of 100", wr, 4, 5, last, "F6", ws, "0", "Value (100 = start)")
    _line_chart("Drawdown from peak", wr, 6, 7, last, "F24", ws, "0%", "Drawdown")

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
    used = {"summary", "returns", "validation", "notes"}
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
        for i, rr in enumerate(tab.itertuples(index=False), start=5):
            for j, v in enumerate(rr, start=1):
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
