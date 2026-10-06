"""Shared workbook styling for every Excel file the pipeline writes (xlsx skill rules).

Colour code, stated on each workbook's Legend:
  blue text    hardcoded input (data written by the backtest, or an assumption)
  black text   formula on the same sheet
  green text   formula that pulls from another sheet
  yellow fill  key assumption: change it and the workbook recalculates
  PASS / FAIL  green / red fill by conditional format; "not computed" is grey
Arial throughout. Percentages are stored as fractions.
"""
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName

ARIAL = "Arial"
F_BASE = Font(name=ARIAL, size=10)
F_BOLD = Font(name=ARIAL, size=10, bold=True)
F_TITLE = Font(name=ARIAL, size=14, bold=True, color="1F4E79")
F_SUB = Font(name=ARIAL, size=11, bold=True, color="1F4E79")
F_INPUT = Font(name=ARIAL, size=10, color="0000FF")
F_LINK = Font(name=ARIAL, size=10, color="008000")
F_NOTE = Font(name=ARIAL, size=9, italic=True, color="555555")
F_HEAD = Font(name=ARIAL, size=10, bold=True, color="FFFFFF")

FILL_HEAD = PatternFill("solid", fgColor="1F4E79")
FILL_KEY = PatternFill("solid", fgColor="FFFF00")
FILL_BAND = PatternFill("solid", fgColor="F2F6FA")
FILL_PASS = PatternFill("solid", bgColor="C6EFCE", fgColor="C6EFCE")
FILL_FAIL = PatternFill("solid", bgColor="FFC7CE", fgColor="FFC7CE")
FILL_NA = PatternFill("solid", bgColor="E7E6E6", fgColor="E7E6E6")

THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

PCT, PCT2 = "0.0%;(0.0%);-", "0.00%;(0.00%);-"
NUM2, NUM1, INT = "0.00;(0.00);-", "0.0;(0.0);-", "#,##0"
DATE = "yyyy-mm-dd"


def put(ws, ref, value, font=F_BASE, fmt=None, fill=None, comment=None, border=False, align=None):
    c = ws[ref]
    c.value = value
    c.font = font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if comment:
        c.comment = Comment(comment, "analysis")
    if border:
        c.border = BOX
    if align:
        c.alignment = align
    return c


def header(ws, row, values, col=1, height=30):
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=col + i, value=v)
        c.font, c.fill, c.border = F_HEAD, FILL_HEAD, BOX
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = height


def widths(ws, spec):
    for i, w in enumerate(spec, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def name(wb, label, ref):
    """Workbook-level defined name, so formulas read =(CAGR-Hurdle)/Vol instead of cell addresses."""
    wb.defined_names[label] = DefinedName(label, attr_text=ref)


def band(ws, first_row, last_row, ncols):
    """Light banding on every second data row."""
    for r in range(first_row, last_row + 1):
        if (r - first_row) % 2:
            for c in range(1, ncols + 1):
                cell = ws.cell(row=r, column=c)
                if cell.fill is None or cell.fill.fgColor.rgb in ("00000000", None):
                    cell.fill = FILL_BAND


def pass_fail(ws, rng):
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"PASS"'], fill=FILL_PASS))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"FAIL"'], fill=FILL_FAIL))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"not computed"'], fill=FILL_NA))


def sign_colour(ws, rng):
    """Green fill for positive, red for negative (returns, excess, Sharpe)."""
    ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"], fill=FILL_PASS))
    ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"], fill=FILL_FAIL))


def drawdown_scale(ws, rng):
    ws.conditional_formatting.add(rng, ColorScaleRule(start_type="min", start_color="F8696B",
                                                      end_type="max", end_color="FFFFFF"))


def apply_house_style(wb):
    """Post-pass for workbooks built elsewhere: Arial everywhere, blue for hardcoded numbers,
    green for cross-sheet formulas, black otherwise. Keeps each cell's size, bold, italic and fills."""
    from copy import copy
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                f = copy(c.font)
                colour = f.color.rgb if f.color is not None and isinstance(f.color.rgb, str) else None
                if isinstance(c.value, str) and c.value.startswith("="):
                    new = "FF008000" if "!" in c.value else colour
                elif (isinstance(c.value, (int, float)) and not isinstance(c.value, bool)
                      and (colour or "").upper() not in ("FFFFFFFF", "00FFFFFF")):
                    new = "FF0000FF"
                else:
                    new = colour
                c.font = Font(name=ARIAL, size=f.size or 10, bold=f.bold, italic=f.italic,
                              color=new if new not in (None, "00000000") else None)
        ws.sheet_view.showGridLines = False


def legend(ws, top_row, col="A"):
    """Colour key, placed on the Summary sheet."""
    put(ws, f"{col}{top_row}", "Colour key", F_SUB)
    put(ws, f"{col}{top_row+1}", "Blue text: hardcoded input or data written by the backtest", F_INPUT)
    put(ws, f"{col}{top_row+2}", "Black text: formula on the same sheet", F_BASE)
    put(ws, f"{col}{top_row+3}", "Green text: formula pulling from another sheet", F_LINK)
    put(ws, f"{col}{top_row+4}", "Yellow fill: key assumption, change it and the workbook recalculates", F_BASE, fill=FILL_KEY)
    put(ws, f"{col}{top_row+5}", "Green / red fill: pass or fail, positive or negative", F_BASE, fill=FILL_PASS)
