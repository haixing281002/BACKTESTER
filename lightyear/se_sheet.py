# Quant AI Researcher
"""Two workbook sheets: "SE Return Analytics", laid out like the reference sheet with every analytics cell a live Excel
formula, and "Python vs Excel", which sets each Python value beside the cell Excel calculates.

The formulas are the reference's own (ros/metrics/se.py SPEC), with ranges fitted to the run's months. Monthly returns
are formulas too: each month compounds the run's daily returns on the Returns sheet, so nothing on the sheet is pasted
except the month-end dates, which come from the run. The three yellow cells are the inputs. The drawdown cells use LET,
SCAN and LAMBDA, exactly as the reference does: desktop Excel calculates them; LibreOffice cannot.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from openpyxl.styles import Alignment
from openpyxl.worksheet.formula import ArrayFormula

from ros.metrics import se
from universal_backtester.xlsx_style import (DATE, F_BASE, F_BOLD, F_HEAD, F_INPUT, F_LINK, F_NOTE, F_SUB, F_TITLE, FILL_HEAD, FILL_KEY,
                                             header, put, widths)

SHEET, CHECK = "SE Return Analytics", "Python vs Excel"
FMT = {se.PCT: "0.00%", se.NUM: "0.00", se.INT: "0"}
TOL = 1e-9


def _f(ws, ref, text, fmt, font=F_BASE):
    if text.startswith("ARRAY:"):
        ws[ref] = ArrayFormula(ref, text[6:])
    else:
        ws[ref] = text
    ws[ref].font, ws[ref].number_format = font, fmt


def write_se_sheet(wb, block: dict[str, Any], strategy_name: str, daily_first: int, daily_last: int) -> dict[str, Any]:
    """`block` is ros.metrics.se.block() for the run. `daily_first`/`daily_last` are the first and last data rows of the
    Returns sheet (dates in A, strategy returns in B, benchmark returns in C). Returns where every cell sits."""
    ws = wb.create_sheet(SHEET)
    months = [pd.Timestamp(m) for m in block["months"]]
    n = len(months)
    first, last = 5, 4 + n
    put(ws, "B1", "SE Return Analytics (monthly)", F_TITLE)
    put(ws, "B2", "Monthly Performance since Inception", F_SUB)
    put(ws, "J2", "Analytics", F_SUB)
    put(ws, "O2", "Glossary", F_SUB)
    put(ws, "F3", "Quarterly", F_BOLD)
    header(ws, 4, ["Months", strategy_name, block["benchmark_label"]], col=2)
    ws["F4"], ws["G4"], ws["K4"], ws["L4"] = "=C4", "=D4", "=+C4", "=+D4"
    put(ws, "J4", "Parameters", F_HEAD, fill=FILL_HEAD)
    for c in ("F4", "G4", "K4", "L4"):
        ws[c].font, ws[c].fill = F_HEAD, FILL_HEAD
        ws[c].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    dts = f"Returns!$A${daily_first}:$A${daily_last}"
    for k, m in enumerate(months):
        i = first + k
        put(ws, f"B{i}", m.to_pydatetime(), F_INPUT, DATE)
        for col, src in (("C", "B"), ("D", "C")):
            # the month's return: every daily return dated after the previous month-end and up to this one, compounded
            _f(ws, f"{col}{i}", f"ARRAY:=PRODUCT(IF(({dts}>EOMONTH($B{i},-1))*({dts}<=$B{i}),1+Returns!${src}${daily_first}:${src}${daily_last},1))-1",
               "0.00%", F_LINK)
    for q in block["tables"]["quarterly"]:
        i = first + q["last"]
        for col, src in (("F", "C"), ("G", "D")):
            _f(ws, f"{col}{i}", f"ARRAY:=PRODUCT(1+{src}{first + q['first']}:{src}{i})-1", "0.00%")

    # ---- analytics rows, in the reference's order with a blank row between groups
    rows: dict[str, int] = {}
    r = 5
    prev = None
    for sec, lab, _cols, _fmt, _xl in se.SPEC:
        if prev is not None and sec != prev:
            r += 1
        rows[lab] = r
        prev = sec
        r += 1
    tables = block["tables"]
    fy0 = r + 1
    cy0 = fy0 + len(tables["financial_year"]) + 1
    note0 = cy0 + len(tables["calendar_year"]) + 1
    dd0 = note0 + 3
    in0 = dd0 + len(tables["calendar_year_drawdown"]) + 3
    cells = {"DL": f"$J${in0}", "OM": f"$J${in0 + 1}", "RF": f"$J${in0 + 2}"}
    shown = {row["label"]: row["shown"] for row in block["rows"]}
    seen = None
    for sec, lab, cols, fmt, xl in se.SPEC:
        i = rows[lab]
        if sec != seen:
            put(ws, f"I{i}", sec, F_BOLD)
            seen = sec
        put(ws, f"J{i}", shown[lab], F_BASE)
        for c, x in (("K", f"C{first}:C{last}"), ("L", f"D{first}:D{last}")):
            if c == "L" and cols != "SB":
                continue
            text = xl.format(x=x, c=c, r=rows, C=f"C{first}:C{last}", D=f"$D${first}:$D${last}",
                             cyd=f"{c}{dd0}:{c}{dd0 + len(tables['calendar_year_drawdown']) - 1}", **cells)
            _f(ws, f"{c}{i}", text, FMT[fmt])

    def table(top, title, rows_, product):
        put(ws, f"I{top}", title, F_BOLD)
        out = []
        for k, t in enumerate(rows_):
            i = top + k
            put(ws, f"J{i}", t["label"], F_BASE)
            for c, src in (("K", "C"), ("L", "D")):
                rng = f"{src}{first + t['first']}:{src}{first + t['last']}"
                _f(ws, f"{c}{i}", "ARRAY:" + (product(rng) if product else se.drawdown_formula(rng)), "0.00%")
            out.append(i)
        return out

    where = {"financial_year": table(fy0, "Financial Year Performance", tables["financial_year"], lambda g: f"=PRODUCT(1+{g})-1"),
             "calendar_year": table(cy0, "Calander Year Performance", tables["calendar_year"], lambda g: f"=PRODUCT({g}+1)-1"),
             "calendar_year_drawdown": table(dd0, "Max Calendar Year Drawdown", tables["calendar_year_drawdown"], None)}
    put(ws, f"J{note0}", f"*Returns from {months[0]:%B %Y}", F_NOTE)
    put(ws, f"J{note0 + 1}", f"**Returns till {pd.Timestamp(block['last_return']):%d %B %Y}", F_NOTE)
    for k, (lab, key) in enumerate((("Drawdown limit", "drawdown_limit"), ("Threshold for Omega ratio", "omega_threshold"), ("Risk Free Rate", "risk_free_rate"))):
        put(ws, f"I{in0 + k}", lab, F_BOLD)
        put(ws, f"J{in0 + k}", block["inputs"][key], F_INPUT, "0.00%", FILL_KEY, border=True,
            comment="Input. The risk-free rate is the one setting in config/fund.yaml; the other two are the reference sheet's values.")
    put(ws, f"I{in0 + 4}", "Benchmark: " + block["benchmark_label"] + ". Monthly returns are compounded from the run's daily returns (Returns sheet). "
                           "Every analytics cell is a formula; the yellow cells are the inputs. Quant AI Researcher", F_NOTE)
    for k, (term, text) in enumerate(block["glossary"], start=4):
        put(ws, f"O{k}", term, F_BOLD)
        put(ws, f"P{k}", text, F_NOTE)
    put(ws, f"O{4 + len(block['glossary']) + 1}", "* All are INR returns", F_NOTE)
    ws.freeze_panes = "E5"
    widths(ws, [2, 12, 22, 26, 2, 14, 14, 2, 26, 34, 16, 16, 2, 2, 28, 110])
    return {"sheet": SHEET, "rows": rows, "first": first, "last": last, "tables": where, "inputs": cells,
            "quarterly_rows": [first + q["last"] for q in tables["quarterly"]]}


def check_items(block: dict[str, Any], where: dict[str, Any]) -> list[tuple[str, str, Any, str]]:
    """(group, metric, Python value, Excel cell) for every SE figure: the analytics rows, then the four tables."""
    q = f"'{SHEET}'!"
    items = []
    by = {r["label"]: r for r in block["rows"]}
    for sec, lab, cols, _fmt, _xl in se.SPEC:
        row = by[lab]
        items.append((f"SE: {sec}", f"{row['shown']}, strategy", row["strategy"], f"{q}K{where['rows'][lab]}"))
        if cols == "SB":
            items.append((f"SE: {sec}", f"{row['shown']}, benchmark", row["benchmark"], f"{q}L{where['rows'][lab]}"))
    for key, title in (("financial_year", "Financial year"), ("calendar_year", "Calendar year"), ("calendar_year_drawdown", "Max calendar-year drawdown")):
        for t, i in zip(block["tables"][key], where["tables"][key]):
            items.append((f"SE: {title}", f"{t['label']}, strategy", t["strategy"], f"{q}K{i}"))
            items.append((f"SE: {title}", f"{t['label']}, benchmark", t["benchmark"], f"{q}L{i}"))
    for t, i in zip(block["tables"]["quarterly"], where["quarterly_rows"]):
        items.append(("SE: Quarterly", f"{t['label']}, strategy", t["strategy"], f"{q}F{i}"))
        items.append(("SE: Quarterly", f"{t['label']}, benchmark", t["benchmark"], f"{q}G{i}"))
    for k, (m, s, b) in enumerate(zip(block["months"], block["monthly"]["strategy"], block["monthly"]["benchmark"])):
        items.append(("SE: Monthly returns", f"{m[:7]}, strategy", s, f"{q}C{where['first'] + k}"))
        items.append(("SE: Monthly returns", f"{m[:7]}, benchmark", b, f"{q}D{where['first'] + k}"))
    return items


def write_check_sheet(wb, items: list[tuple[str, str, Any, str]]) -> dict[str, Any]:
    """Metric, Python value, the Excel formula's value, the difference, and OK or FAIL at 1e-9. A figure neither side can
    calculate (no month qualifies) shows n/a on both and counts as OK; one side alone is a FAIL."""
    ws = wb.create_sheet(CHECK)
    put(ws, "A1", "Python vs Excel", F_TITLE)
    put(ws, "A2", "Column C is the value Python calculated (ros/metrics). Column D reads the cell Excel calculates from its own formula. "
                  f"OK means they agree within {TOL:g}. Quant AI Researcher", F_NOTE)
    put(ws, "A3", "Result", F_BOLD)
    first = 6
    last = first + len(items) - 1
    put(ws, "B3", f'=IF(COUNTIF(F{first}:F{last},"FAIL")=0,"ALL "&COUNTA(F{first}:F{last})&" OK",COUNTIF(F{first}:F{last},"FAIL")&" FAIL of "&COUNTA(F{first}:F{last}))',
        F_BOLD)
    header(ws, 5, ["Group", "Metric", "Python value", "Excel formula value", "Difference", "OK or FAIL"])
    for k, (group, metric, py, ref) in enumerate(items, start=first):
        ok = py is not None and py == py
        put(ws, f"A{k}", group, F_BASE)
        put(ws, f"B{k}", metric, F_BASE)
        put(ws, f"C{k}", float(py) if ok else "n/a", F_INPUT, "0.000000000000")
        put(ws, f"D{k}", f'=IFERROR({ref},"n/a")', F_LINK, "0.000000000000")
        put(ws, f"E{k}", f'=IF(AND(ISNUMBER(C{k}),ISNUMBER(D{k})),D{k}-C{k},"")', F_BASE, "0.00E+00")
        put(ws, f"F{k}", f'=IF(AND(ISNUMBER(C{k}),ISNUMBER(D{k})),IF(ABS(D{k}-C{k})<={TOL},"OK","FAIL"),IF(AND(C{k}="n/a",D{k}="n/a"),"OK","FAIL"))', F_BOLD)
    ws.freeze_panes = "A6"
    widths(ws, [30, 52, 20, 20, 14, 12])
    return {"sheet": CHECK, "first": first, "last": last, "result_cell": "B3", "n": len(items)}
