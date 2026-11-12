# Quant AI Researcher
"""The main results workbook (Wave 6): the monthly display of the Results tab, sheet for sheet, with live formulas.

Sheets, in order
  Returns overview      headline (monthly), financial-year returns with alpha, NAV chart, trailing returns, key return metrics
  Market phases         the operator's NIFTY 500 phases: chart and table
  Rolling returns       rolling 1-year and 3-year return, alpha and excess Sharpe: numbers and charts
  Factor attribution    regression on four factor indices with no intercept, and its rolling 12-month coefficients
  Drawdown and risk     monthly drawdown chart and the risk ratios
  Tail risk             strategy, benchmark and monthly alpha, with three charts
  Index and capture     performance versus the index, capture, and average quarterly performance
  Calendar years        calendar-year performance and maximum calendar-year drawdown
  Allocation            market-cap and sector allocation and returns by period         [when the run has the data]
  Daily calculations    every daily metric, its formula, and the monthly figure beside it
  Python vs Excel       every Python value beside the cell Excel calculates, OK or FAIL at 1e-9
  SE Return Analytics   the monthly returns and the reference-layout formulas the display sheets read
  Monthly series        month-by-month series behind the charts (formulas), and the factor indices' monthly returns
  Returns               the run's daily returns

Every number on a display sheet is a formula: a link to the SE sheet, or a formula over Monthly series. The Python
side of each is ros/metrics/se.py and ros/metrics/qi.py (monthly) and ros/metrics/core.py (daily).
"""
from __future__ import annotations

from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.data_source import NumFmt
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.formula import ArrayFormula

from ros.metrics import qi as qi_mod
from ros.metrics import se
from universal_backtester.xlsx_style import (
    BOX,
    DATE,
    F_BASE,
    F_BOLD,
    F_INPUT,
    F_LINK,
    F_NOTE,
    F_TITLE,
    FILL_KEY,
    INT,
    NUM2,
    PCT2,
    header,
    name,
    put,
    widths,
)

from . import se_sheet, workbook

SEQ = "'SE Return Analytics'!"
MS, MSQ = "Monthly series", "'Monthly series'!"
C_STRAT, C_BENCH, C_3, C_4 = "1F4E79", "D98324", "6A994E", "8E5EA2"
FMT = {"pct": PCT2, "num": NUM2, "int": INT}
SIGN = "Quant AI Researcher"
TAIL_ROWS = ["Mean", "Volatility (monthly)", "Skewness", "Kurtosis", "95% VaR", "99% VaR", "95% CVaR", "99% CVaR"]
TAIL_FMT = [PCT2, PCT2, NUM2, NUM2, PCT2, PCT2, PCT2, PCT2]


def _f(ws, ref, text, fmt=None, font=None):
    """A formula cell. "ARRAY:" enters it as an array formula. Green when it reads another sheet, black otherwise."""
    if text.startswith("ARRAY:"):
        ws[ref] = ArrayFormula(ref, text[6:])
    else:
        ws[ref] = text
    ws[ref].font = font or (F_LINK if "!" in text else F_BASE)
    ws[ref].border = BOX
    if fmt:
        ws[ref].number_format = fmt


def _lab(ws, ref, text, font=F_BASE):
    put(ws, ref, text, font, border=True)


def _frame(ch, title, y_fmt, y_title, r0, r1, width, height):
    """Title above the plot, legend below it, month labels along the bottom edge."""
    ch.height, ch.width = height, width
    if title:
        ch.title = title
        ch.title.overlay = False
    ch.y_axis.number_format = y_fmt       # no axis title: Excel draws it over the tick labels; the chart title says what is plotted
    ch.x_axis.numFmt = NumFmt(formatCode="mmm yy", sourceLinked=False)
    ch.x_axis.tickLblSkip, ch.x_axis.tickLblPos = max(1, (r1 - r0) // 10), "low"
    ch.x_axis.delete = ch.y_axis.delete = False
    ch.legend.position, ch.legend.overlay = "b", False


def _line(title, ws, cols, r0, r1, colours, y_fmt, y_title, head=4, width=22, height=9):
    ch = LineChart()
    _frame(ch, title, y_fmt, y_title, r0, r1, width, height)
    for c in cols:
        ch.add_data(Reference(ws, min_col=c, min_row=head, max_row=r1), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=r0, max_row=r1))
    for s, colour in zip(ch.series, colours):
        s.graphicalProperties.line.solidFill = colour
        s.graphicalProperties.line.width = 17000
        s.smooth = False
    return ch


def _bars(title, ws, cols, r0, r1, colours, y_fmt, y_title, head=4, stacked=False, width=22, height=9):
    ch = BarChart()
    ch.type = "col"
    _frame(ch, title, y_fmt, y_title, r0, r1, width, height)
    if stacked:
        ch.grouping, ch.overlap = "stacked", 100
    for c in cols:
        ch.add_data(Reference(ws, min_col=c, min_row=head, max_row=r1), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=r0, max_row=r1))
    for s, colour in zip(ch.series, colours):
        s.graphicalProperties.solidFill = colour
        s.invertIfNegative = False
        s.graphicalProperties.line.solidFill = colour
    return ch


def build(run_dir: str, results: dict[str, Any], df, title: str, out_path: str, ch: dict[str, Any], provenance: dict | None = None,
          alloc: dict[str, Any] | None = None) -> dict[str, Any]:
    """`ch` is lightyear.charts.build() for the run (it carries the SE block, the quant-insights block and the daily
    metrics). Writes the workbook and returns {"sheets": [...], "n_checked": count}."""
    blk, q = ch["se"], ch["qi"]
    s_name = results.get("strategy_name") or "Strategy"
    b_name = results.get("benchmark_name") or "NIFTY 500"
    b_lab = blk["benchmark_label"]
    df = df.sort_values("date").reset_index(drop=True)
    wb = Workbook()
    wr, first, last = workbook.returns_sheet(wb, wb.active, df, s_name, b_name, run_dir, results)
    where = se_sheet.write_se_sheet(wb, blk, s_name, first, last)
    items: list[tuple[str, str, Any, str]] = se_sheet.check_items(blk, where)
    R = where["rows"]
    rf = SEQ + where["inputs"]["RF"]
    n = len(blk["months"])
    K = lambda lab: f"={SEQ}K{R[lab]}"
    B = lambda lab: f"={SEQ}L{R[lab]}"
    cm = blk["complete_months"]
    foot = (f"Complete calendar months only: {n} months, {cm['first_month']} to {cm['last_month']}. "
            + (" ".join(f"Left out: {x['days']} daily returns of {x['month']} ({x['from']} to {x['to']}); {x['why']}." for x in cm["left_out"]) or "No daily return is left out.")
            + (" " + " ".join(cm["notes"]) if cm["notes"] else "")
            + f" Benchmark: {b_lab}" + ("; the NIFTY 500 total-return index is not on file, so every figure against the benchmark flatters the strategy by about the index's dividend yield." if blk["benchmark_basis"] != "total_return" else "."))

    # ------------------------------------------------------------------------------------------------ Monthly series
    wm = wb.create_sheet(MS)
    m0, m1 = 6, 5 + n                       # month rows; row 5 is the start row (value 100)
    fa = q.get("factor_attribution")
    fac = list(fa["factors"]) if fa else []
    heads = ["Month", s_name, b_lab, "Monthly alpha", f"{s_name} value (100 = start)", f"{b_name} value (100 = start)", f"{s_name} drawdown", f"{b_name} drawdown"] + (fac or ["", "", "", ""])
    for k_ in (12, 36):
        heads += [f"{k_}m return, strategy", f"{k_}m return, benchmark", f"{k_}m alpha", f"{k_}m Sharpe, strategy", f"{k_}m Sharpe, benchmark", f"{k_}m excess Sharpe"]
    heads += [f"12m coefficient: {x}" for x in (fac or ["", "", "", ""])]
    for who in ("Strategy", "Benchmark", "Alpha"):
        heads += [f"{who} {x}" for x in ("95% VaR", "99% VaR", "95% CVaR", "99% CVaR")]
    heads += ["Phase band A", "Phase band B"]
    put(wm, "A1", "Monthly series behind the charts", F_TITLE)
    put(wm, "A2", "Formulas over the SE Return Analytics sheet, month by month. Blue = the factor indices' monthly returns, compounded from the NSE index workbook's daily "
        f"closes on the run's own days (price indices, no dividends). {SIGN}", F_NOTE)
    header(wm, 4, heads, height=58)
    _f(wm, "A5", f"=EOMONTH(A{m0},-1)", DATE)      # the start row: the month-end before the first month
    for c in ("E", "F"):
        put(wm, f"{c}5", 100, F_INPUT, "0.00")
    C = {"r12": 13, "r36": 19, "coef": 25, "var": 29, "band": 41}      # first column of each block (1-based)
    for k in range(n):
        r, sr = m0 + k, where["first"] + k
        _f(wm, f"A{r}", f"={SEQ}B{sr}", DATE)
        _f(wm, f"B{r}", f"={SEQ}C{sr}", PCT2)
        _f(wm, f"C{r}", f"={SEQ}D{sr}", PCT2)
        _f(wm, f"D{r}", f"=B{r}-C{r}", PCT2)
        _f(wm, f"E{r}", f"=E{r - 1}*(1+B{r})", "0.00")
        _f(wm, f"F{r}", f"=F{r - 1}*(1+C{r})", "0.00")
        _f(wm, f"G{r}", f"=E{r}/MAX(E${m0}:E{r})-1", PCT2)
        _f(wm, f"H{r}", f"=F{r}/MAX(F${m0}:F{r})-1", PCT2)
        for j, nm in enumerate(fac):
            put(wm, f"{L(9 + j)}{r}", q["factor_returns"][nm][k], F_INPUT, PCT2, border=True)
        for win, c0 in ((12, C["r12"]), (36, C["r36"])):
            if k + 1 < win:
                continue
            a = r - win + 1
            ann = "" if win <= 12 else f"^(12/{win})"
            for j, src in enumerate(("B", "C")):
                _f(wm, f"{L(c0 + j)}{r}", f"ARRAY:=PRODUCT(1+{src}{a}:{src}{r}){ann}-1", PCT2)
                _f(wm, f"{L(c0 + 3 + j)}{r}", f"=({L(c0 + j)}{r}-{rf})/(STDEVP({src}{a}:{src}{r})*SQRT(12))", NUM2)
            _f(wm, f"{L(c0 + 2)}{r}", f"={L(c0)}{r}-{L(c0 + 1)}{r}", PCT2)
            _f(wm, f"{L(c0 + 5)}{r}", f"={L(c0 + 3)}{r}-{L(c0 + 4)}{r}", NUM2)
        if fac and k + 1 >= fa["window"]:
            a = r - fa["window"] + 1
            for j in range(4):
                _f(wm, f"{L(C['coef'] + j)}{r}", f"ARRAY:=INDEX(LINEST(B{a}:B{r},I{a}:L{r},FALSE,FALSE),1,{4 - j})", NUM2)
    widths(wm, [12] + [16] * (len(heads) - 1))
    wm.freeze_panes = "B5"
    rs, rb, ra = f"{MSQ}$B${m0}:$B${m1}", f"{MSQ}$C${m0}:$C${m1}", f"{MSQ}$D${m0}:$D${m1}"

    def table(ws, top, heads_, col=1):
        header(ws, top, heads_, col=col, height=34)
        return top + 1

    def sheet(title_, sub):
        ws = wb.create_sheet(title_)
        put(ws, "A1", title_, F_TITLE)
        put(ws, "A2", sub + " " + SIGN, F_NOTE)
        return ws

    # ------------------------------------------------------------------------------------------------ Returns overview
    wo = sheet("Returns overview", f"{title}. Monthly figures, calculated as the reference analytics sheet does: calendar-month returns, population standard deviation, "
                                   "CAGR by month count, risk-free rate from config/fund.yaml. Every number is a formula.")
    put(wo, "A3", foot, F_NOTE)
    r = table(wo, 5, ["Headline (monthly)", s_name, b_lab, "Alpha"])
    for lab, fmt in (("CAGR", PCT2), ("Annualized Volatility", PCT2), ("Sharpe Ratio", NUM2), ("Max Drawdown", PCT2), ("Total Return", PCT2)):
        _lab(wo, f"A{r}", lab)
        _f(wo, f"B{r}", K(lab), fmt)
        _f(wo, f"C{r}", B(lab), fmt)
        _f(wo, f"D{r}", f"=B{r}-C{r}", fmt)
        r += 1
    r = table(wo, r + 1, ["Financial-year returns (April to March)", s_name, b_lab, "Alpha"])
    for t, i in zip(q["financial_year"], where["tables"]["financial_year"]):
        _lab(wo, f"A{r}", t["label"] + (" (part year)" if t["part"] else ""))
        _f(wo, f"B{r}", f"={SEQ}K{i}", PCT2)
        _f(wo, f"C{r}", f"={SEQ}L{i}", PCT2)
        _f(wo, f"D{r}", f"=B{r}-C{r}", PCT2)
        items.append(("Financial-year alpha", t["label"], t["alpha"], f"'Returns overview'!D{r}"))
        r += 1
    _lab(wo, f"A{r}", "Annualised alpha (CAGR minus benchmark CAGR)", F_BOLD)
    _f(wo, f"D{r}", K("Alpha"), PCT2)
    items.append(("Financial-year alpha", "Annualised alpha", q["annualised_alpha"], f"'Returns overview'!D{r}"))
    put(wo, f"A{r + 1}", "A part year is not annualised. * returns from the first month; ** returns till the last complete month.", F_NOTE)
    r = table(wo, r + 3, ["Trailing returns", s_name, b_lab, "Alpha", "Months", "Basis"])
    for t in q["trailing"]:
        k = t["months"]
        _lab(wo, f"A{r}", t["label"])
        put(wo, f"E{r}", k, F_BASE, INT, border=True)
        _lab(wo, f"F{r}", "annualised" if t["annualised"] else "not annualised")
        if t["strategy"] is None:
            for c in "BCD":
                _lab(wo, f"{c}{r}", "n/a")
        else:
            ann = f"^(12/{k})" if t["annualised"] else ""
            for c, src, key in (("B", "B", "strategy"), ("C", "C", "benchmark")):
                _f(wo, f"{c}{r}", f"ARRAY:=PRODUCT(1+{MSQ}{src}{m1 - k + 1}:{src}{m1}){ann}-1", PCT2)
                items.append(("Trailing returns", f"{t['label']}, {key}", t[key], f"'Returns overview'!{c}{r}"))
            _f(wo, f"D{r}", f"=B{r}-C{r}", PCT2)
            items.append(("Trailing returns", f"{t['label']}, alpha", t["alpha"], f"'Returns overview'!D{r}"))
        r += 1
    put(wo, f"A{r}", "Periods over one year are annualised: (1 + return)^(12 / months) - 1. Periods longer than the run show n/a.", F_NOTE)
    r = table(wo, r + 2, ["Key return metrics", s_name, b_lab, "Alpha"])
    for row in q["key_return"]:
        src = next(s_ for lab_, s_, _d in qi_mod.KEY_RETURN if lab_ == row["label"])
        fmt = FMT[row["format"]]
        _lab(wo, f"A{r}", row["label"])
        _f(wo, f"B{r}", K(src), fmt)
        if row["benchmark"] is not None:
            _f(wo, f"C{r}", B(src), fmt)
        if row["alpha"] is not None:
            _f(wo, f"D{r}", f"=B{r}-C{r}", fmt)
        r += 1
    put(wo, f"A{r}", "Best and Worst Month Contribution = the month's return / Total Return, as the reference has it. Hit Rate = months ahead of the benchmark / months ahead or behind.", F_NOTE)
    wo.add_chart(_line(f"Strategy against index NAV (100 at start): {s_name} vs {b_name}", wm, [5, 6], 5, m1, [C_STRAT, C_BENCH], "0", "Value (100 = start)"), "H5")
    widths(wo, [46, 22, 26, 14, 10, 16])

    # ------------------------------------------------------------------------------------------------ Market phases
    wp = sheet("Market phases", "NIFTY 500 phases named by the operator (config/market_phases.yaml). Annualised = (1 + absolute return)^(12 / months) - 1, whatever the "
                                "length, as the reference deck's table does; a phase shorter than a year is therefore scaled up. Months after the last named phase are Unclassified.")
    r = r0 = table(wp, 4, ["Phase", "Months covered", "Strategy annualised", f"{b_lab} annualised", "Alpha", "Length (months)", "Wyckoff phase", "Market term",
                           "Strategy absolute", f"{b_lab} absolute", "Chart label"])
    top = f"MAX({MSQ}$F$5:$F${m1})"
    for j, p in enumerate(q["phases"]):
        a, b_ = m0 + p["first"], m0 + p["last"]
        _lab(wp, f"A{r}", p["label"] + (" (clipped to the run)" if p["clipped"] else ""))
        _lab(wp, f"B{r}", f"{p['first_month']} to {p['last_month']}")
        _f(wp, f"F{r}", f"=ROWS({MSQ}B{a}:B{b_})", INT)
        _f(wp, f"I{r}", f"ARRAY:=PRODUCT(1+{MSQ}B{a}:B{b_})-1", PCT2)
        _f(wp, f"J{r}", f"ARRAY:=PRODUCT(1+{MSQ}C{a}:C{b_})-1", PCT2)
        _f(wp, f"C{r}", f"=(1+I{r})^(12/F{r})-1", PCT2, F_BASE)
        _f(wp, f"D{r}", f"=(1+J{r})^(12/F{r})-1", PCT2, F_BASE)
        _f(wp, f"E{r}", f"=C{r}-D{r}", PCT2)
        _lab(wp, f"G{r}", p["wyckoff_phase"])
        _lab(wp, f"H{r}", p["market_term"])
        _f(wp, f"K{r}", f'=G{r}&": "&TEXT(J{r},"0%")', None, F_BASE)
        for key, c in (("strategy_ann", "C"), ("benchmark_ann", "D"), ("alpha", "E"), ("months", "F"), ("strategy_abs", "I"), ("benchmark_abs", "J")):
            items.append(("Market phases", f"{p['label']}, {key}", p[key], f"'Market phases'!{c}{r}"))
        for rr in range(a, b_ + 1):       # the shading band behind the index line: alternate phases, alternate columns
            _f(wm, f"{L(C['band'] + j % 2)}{rr}", f"={top}", "0.00")
        r += 1
    put(wp, f"A{r}", "The chart shades each phase in turn; its name and the index's absolute return in it are in the Chart label column.", F_NOTE)
    band = BarChart()
    band.type, band.gapWidth = "col", 0
    _frame(band, f"Market phases: {b_name} (100 at start), each phase shaded", "0", "Value (100 = start)", 5, m1, 30, 10)
    for c, colour in ((C["band"], "DCE6F1"), (C["band"] + 1, "F2F2F2")):
        band.add_data(Reference(wm, min_col=c, min_row=4, max_row=m1), titles_from_data=True)
        band.series[-1].graphicalProperties.solidFill = colour
        band.series[-1].graphicalProperties.line.solidFill = colour
    band.set_categories(Reference(wm, min_col=1, min_row=5, max_row=m1))
    band.overlap = 100
    idx_line = _line("", wm, [6], 5, m1, [C_BENCH], "0", "")
    band += idx_line
    wp.add_chart(band, f"A{r + 2}")
    widths(wp, [34, 22, 16, 18, 12, 12, 20, 26, 16, 18, 30])

    # ------------------------------------------------------------------------------------------------ Rolling returns
    wl = sheet("Rolling returns", "Rolling windows on monthly returns. A 3-year return is annualised; a 1-year return is the 12-month return. Rolling Sharpe = (window return - "
                                  "risk-free rate) / (population stdev of the window's months x sqrt(12)). Excess Sharpe = strategy rolling Sharpe - benchmark rolling Sharpe: "
                                  "this definition is the operator's assumption, not taken from the reference.")
    r = table(wl, 4, ["Number", "Rolling 1-year", "Rolling 3-year"])
    stats_rows = [("Observations", "observations", INT, "=COUNT({a})"), ("Share of observations with positive alpha", "positive_alpha_share", PCT2, '=COUNTIF({a},">0")/COUNT({a})'),
                  ("Strategy: average rolling return", "strategy_avg", PCT2, "=AVERAGE({s})"), ("Strategy: minimum", "strategy_min", PCT2, "=MIN({s})"), ("Strategy: maximum", "strategy_max", PCT2, "=MAX({s})"),
                  (f"{b_name}: average rolling return", "benchmark_avg", PCT2, "=AVERAGE({b})"), (f"{b_name}: minimum", "benchmark_min", PCT2, "=MIN({b})"), (f"{b_name}: maximum", "benchmark_max", PCT2, "=MAX({b})")]
    for lab, key, fmt, fx in stats_rows:
        _lab(wl, f"A{r}", lab)
        for col, win, c0 in (("B", 12, C["r12"]), ("C", 36, C["r36"])):
            ro = q["rolling"][str(win)]
            if ro is None:
                _lab(wl, f"{col}{r}", "n/a")
                continue
            a0 = m0 + win - 1
            rng = {k_: f"{MSQ}{L(c0 + j)}{a0}:{L(c0 + j)}{m1}" for j, k_ in enumerate(("s", "b", "a"))}
            _f(wl, f"{col}{r}", fx.format(**rng), fmt)
            items.append((f"Rolling {win} months", lab, ro[key], f"'Rolling returns'!{col}{r}"))
        r += 1
    for win, c0, anchor in ((12, C["r12"], "E4"), (36, C["r36"], "E24")):
        ro = q["rolling"][str(win)]
        if ro is None:
            continue
        for j, key in enumerate(("strategy", "benchmark", "alpha", "strategy_sharpe", "benchmark_sharpe", "excess_sharpe")):
            for e, v in zip(ro["end"], ro[key]):
                items.append((f"Rolling {win} months: series", f"{blk['months'][e][:7]}, {key}", v, f"{MSQ}{L(c0 + j)}{m0 + e}"))
        c1 = _line(f"Rolling {win // 12}-year: alpha and excess Sharpe", wm, [c0 + 2], 5, m1, [C_STRAT], "0%", "Alpha" + (" (annualised)" if win > 12 else ""))
        c2 = _line("", wm, [c0 + 5], 5, m1, [C_BENCH], "0.0", "Excess Sharpe")
        c2.y_axis.axId, c2.y_axis.crosses, c2.y_axis.majorGridlines = 200, "max", None
        c1 += c2
        wl.add_chart(c1, anchor)
    widths(wl, [44, 18, 18])

    # ------------------------------------------------------------------------------------------------ Factor attribution
    wf = sheet("Factor attribution", "Strategy monthly returns regressed on the monthly returns of four factor indices, with NO intercept, as the reference deck does. "
                                     "This regression has no alpha term. Gate B's factor test is a separate regression: daily returns, seven factors, with an intercept.")
    if not fa:
        put(wf, "A4", "Not calculated: " + (q.get("factors_missing") or "the factor indices' returns are not on file") + ".", F_BOLD)
    else:
        y, X = rs, f"{MSQ}$I${m0}:$L${m1}"
        lin = f"LINEST({y},{X},FALSE,TRUE)"
        r = table(wf, 4, ["Regression statistics", "Value"])
        st_rows = [("R Square", f"ARRAY:=INDEX({lin},3,1)", NUM2), ("Multiple R", "=SQRT(B5)", NUM2), ("Observations", f"=COUNT({y})", INT),
                   ("Residual degrees of freedom", f"ARRAY:=INDEX({lin},4,2)", INT), ("Adjusted R Square", "=1-(1-B5)*B7/B8", NUM2), ("Standard Error", f"ARRAY:=INDEX({lin},3,2)", "0.0000")]
        for lab, fx, fmt in st_rows:
            _lab(wf, f"A{r}", lab)
            _f(wf, f"B{r}", fx, fmt)
            if lab in fa["statistics"]:
                items.append(("Factor attribution: statistics", lab, fa["statistics"][lab], f"'Factor attribution'!B{r}"))
            r += 1
        put(wf, f"A{r}", "R Square is the uncentred one (total = sum of squared returns), which is what a regression without an intercept reports. "
                         "Adjusted R Square = 1 - (1 - R Square) x observations / residual degrees of freedom.", F_NOTE)
        r = a0 = table(wf, r + 2, ["ANOVA", "df", "SS", "MS", "F", "Significance F"])
        an = fa["anova"]
        _lab(wf, f"A{r}", "Regression")
        _f(wf, f"B{r}", f"=COLUMNS({X})", INT)
        _f(wf, f"C{r}", f"ARRAY:=INDEX({lin},5,1)", "0.0000")
        _f(wf, f"D{r}", f"=C{r}/B{r}", "0.0000")
        _f(wf, f"E{r}", f"ARRAY:=INDEX({lin},4,1)", NUM2)
        _f(wf, f"F{r}", f"=FDIST(E{r},B{r},B{r + 1})", "0.00E+00")
        _lab(wf, f"A{r + 1}", "Residual")
        _f(wf, f"B{r + 1}", "=B8", INT)
        _f(wf, f"C{r + 1}", f"ARRAY:=INDEX({lin},5,2)", "0.0000")
        _f(wf, f"D{r + 1}", f"=C{r + 1}/B{r + 1}", "0.000000")
        _lab(wf, f"A{r + 2}", "Total")
        _f(wf, f"B{r + 2}", "=B7", INT)
        _f(wf, f"C{r + 2}", f"=C{r}+C{r + 1}", "0.0000")
        for lab, v, ref in (("Regression SS", an["regression"]["ss"], f"C{r}"), ("Regression MS", an["regression"]["ms"], f"D{r}"), ("F", an["regression"]["f"], f"E{r}"),
                            ("Significance F", an["regression"]["significance_f"], f"F{r}"), ("Residual SS", an["residual"]["ss"], f"C{r + 1}"),
                            ("Residual MS", an["residual"]["ms"], f"D{r + 1}"), ("Total SS", an["total"]["ss"], f"C{r + 2}"), ("Total df", an["total"]["df"], f"B{r + 2}")):
            items.append(("Factor attribution: ANOVA", lab, v, f"'Factor attribution'!{ref}"))
        r = table(wf, r + 4, ["Index", "Coefficient", "Standard error", "t stat", "P-value", "Lower 95%", "Upper 95%"])
        for j, c in enumerate(fa["coefficients"]):
            _lab(wf, f"A{r}", c["factor"])
            _f(wf, f"B{r}", f"ARRAY:=INDEX({lin},1,{4 - j})", NUM2)
            _f(wf, f"C{r}", f"ARRAY:=INDEX({lin},2,{4 - j})", NUM2)
            _f(wf, f"D{r}", f"=B{r}/C{r}", NUM2)
            _f(wf, f"E{r}", f"=TDIST(ABS(D{r}),$B$8,2)", "0.0000")
            _f(wf, f"F{r}", f"=B{r}-TINV(0.05,$B$8)*C{r}", NUM2)
            _f(wf, f"G{r}", f"=B{r}+TINV(0.05,$B$8)*C{r}", NUM2)
            for key, col in (("coefficient", "B"), ("standard_error", "C"), ("t_stat", "D"), ("p_value", "E"), ("lower_95", "F"), ("upper_95", "G")):
                items.append(("Factor attribution: coefficients", f"{c['factor']}, {key}", c[key], f"'Factor attribution'!{col}{r}"))
            for e, v in zip(fa["rolling"]["end"], fa["rolling"]["coefficients"][c["factor"]]):
                items.append(("Factor attribution: rolling 12 months", f"{blk['months'][e][:7]}, {c['factor']}", v, f"{MSQ}{L(C['coef'] + j)}{m0 + e}"))
            r += 1
        put(wf, f"A{r}", "The factor indices are NSE price indices, backfilled before their launch dates. The rolling chart shows the same regression's coefficients on each "
                         "12-month window (12 months, four coefficients: they move a great deal).", F_NOTE)
        wf.add_chart(_bars("Rolling 12-month attribution: coefficient on each factor index", wm, [C["coef"] + j for j in range(4)], 5, m1,
                           [C_STRAT, C_BENCH, C_3, C_4], "0.0", "Coefficient", stacked=True, width=28, height=10), f"A{r + 2}")
        widths(wf, [34, 14, 16, 12, 12, 16, 12])

    # ------------------------------------------------------------------------------------------------ Drawdown and risk
    wd = sheet("Drawdown and risk", "Drawdown on month-end values (the peak starts at the first month-end, as in the reference). Every ratio is the reference sheet's formula. "
                                    "Downside Deviation = Negative Monthly Vol x sqrt(12). Largest Monthly Loss = the worst month's return.")
    r = table(wd, 4, ["Risk and ratios (monthly)", s_name, b_lab])
    for row, (lab, src, f_) in zip(q["risk"], qi_mod.RISK):
        _lab(wd, f"A{r}", lab)
        for col, who, cell_ in (("B", "strategy", "K"), ("C", "benchmark", "L")):
            if src is None:
                _f(wd, f"{col}{r}", f"={SEQ}{cell_}{R['Negative Monthly Vol']}*SQRT(12)", FMT[f_])
                items.append(("Drawdown and risk", f"{lab}, {who}", row[who], f"'Drawdown and risk'!{col}{r}"))
            else:
                _f(wd, f"{col}{r}", f"={SEQ}{cell_}{R[src]}", FMT[f_])
        r += 1
    for who, col in (("strategy", "G"), ("benchmark", "H")):
        for k, v in enumerate(q["drawdown"][who]):
            items.append(("Drawdown: series", f"{blk['months'][k][:7]}, {who}", v, f"{MSQ}{col}{m0 + k}"))
    wd.add_chart(_line(f"Monthly drawdown: {s_name} vs {b_name}", wm, [7, 8], 5, m1, [C_STRAT, C_BENCH], "0%", "Below previous month-end high"), "E4")
    widths(wd, [36, 22, 26])

    # ------------------------------------------------------------------------------------------------ Tail risk
    wt = sheet("Tail risk", "Monthly returns of the strategy, the benchmark and the monthly alpha (strategy minus benchmark). VaR = the 5th and 1st percentile of the months; "
                            "CVaR = the average of the months at or below that VaR. Volatility here is the population standard deviation of the months, not annualised.")
    r = t0 = table(wt, 4, ["Tail risk (monthly)", s_name, b_lab, "Monthly alpha"])
    se_of = {"Mean": "Avg Month Ret", "Skewness": "Skewness", "Kurtosis": "Kurtosis", "95% VaR": "95% VaR", "99% VaR": "99% VaR", "95% CVaR": "95% CVaR", "99% CVaR": "99% CVaR"}
    alpha_fx = {"Mean": f"=AVERAGE({ra})", "Volatility (monthly)": f"=STDEVPA({ra})", "Skewness": f"=SKEW({ra})", "Kurtosis": f"=KURT({ra})",
                "95% VaR": f"=_xlfn.PERCENTILE.INC({ra},0.05)", "99% VaR": f"=_xlfn.PERCENTILE.INC({ra},0.01)",
                "95% CVaR": f'=AVERAGEIFS({ra},{ra},"<="&D{t0 + 4})', "99% CVaR": f'=AVERAGEIFS({ra},{ra},"<="&D{t0 + 5})'}
    for lab, fmt in zip(TAIL_ROWS, TAIL_FMT):
        _lab(wt, f"A{r}", lab)
        for col, who, cell_, rng in (("B", "strategy", "K", rs), ("C", "benchmark", "L", rb)):
            _f(wt, f"{col}{r}", f"=STDEVPA({rng})" if lab not in se_of else f"={SEQ}{cell_}{R[se_of[lab]]}", fmt)
            items.append(("Tail risk", f"{lab}, {who}", q["tail"][who][lab], f"'Tail risk'!{col}{r}"))
        _f(wt, f"D{r}", alpha_fx[lab], fmt)
        items.append(("Tail risk", f"{lab}, alpha", q["tail"]["alpha"][lab], f"'Tail risk'!D{r}"))
        r += 1
    for g, (col, src, nm) in enumerate((("B", 2, s_name), ("C", 3, b_name), ("D", 4, "monthly alpha"))):
        c0 = C["var"] + 4 * g
        for j in range(4):
            for rr in range(m0, m1 + 1):
                _f(wm, f"{L(c0 + j)}{rr}", f"='Tail risk'!${col}${t0 + 4 + j}", PCT2)
        bar = _bars(f"Monthly returns, {nm}: tail risk", wm, [src], 5, m1, [C_STRAT if g != 1 else C_BENCH], "0%", "Monthly return", width=24, height=9)
        ln = _line("", wm, [c0 + j for j in range(4)], 5, m1, ["C00000", "7F0000", "ED7D31", "7030A0"], "0%", "")
        bar += ln
        wt.add_chart(bar, f"F{4 + 19 * g}")
    widths(wt, [30, 22, 26, 16])

    # ------------------------------------------------------------------------------------------------ Index and capture
    wc = sheet("Index and capture", "Performance versus the index and capture: every row of those groups of the reference sheet, on monthly returns. Then the average quarterly "
                                    "return in rising and falling quarters (complete calendar quarters; rising = the benchmark's quarterly return is zero or more).")
    r = 4
    shown = {row["label"]: row["shown"] for row in blk["rows"]}
    for sec in ("Performance Vs Index", "Capture Ratio", "Extreme Capture Ratio"):
        r = table(wc, r, [sec + " (monthly)", s_name, b_lab])
        for sec_, lab, cols, fmt, _xl in se.SPEC:
            if sec_ != sec:
                continue
            _lab(wc, f"A{r}", shown[lab])
            _f(wc, f"B{r}", K(lab), FMT[fmt])
            if cols == "SB":
                _f(wc, f"C{r}", B(lab), FMT[fmt])
            r += 1
        r += 1
    qc, qt = q["quarterly_capture"], blk["tables"]["quarterly"]
    full = [i for t, i in zip(qt, where["quarterly_rows"]) if not t["part"]]
    r = table(wc, r, ["Average quarterly performance", s_name, b_lab])
    if full:
        qs_, qb_ = f"{SEQ}$F${full[0]}:$F${full[-1]}", f"{SEQ}$G${full[0]}:$G${full[-1]}"
        rows_q = [("Complete quarters", "quarters", INT, None, f"=COUNT({qb_})"), ("Rising quarters", "rising_quarters", INT, None, f'=COUNTIF({qb_},">=0")'),
                  ("Falling quarters", "falling_quarters", INT, None, f'=COUNTIF({qb_},"<0")'),
                  ("Average return in rising quarters", ("strategy_rising", "benchmark_rising"), PCT2, f'=AVERAGEIFS({qs_},{qb_},">=0")', f'=AVERAGEIFS({qb_},{qb_},">=0")'),
                  ("Average return in falling quarters", ("strategy_falling", "benchmark_falling"), PCT2, f'=AVERAGEIFS({qs_},{qb_},"<0")', f'=AVERAGEIFS({qb_},{qb_},"<0")'),
                  ("Upside capture", "upside_capture", NUM2, "=B{u}/C{u}", None), ("Downside capture", "downside_capture", NUM2, "=B{d}/C{d}", None),
                  ("Capture ratio", "capture_ratio", NUM2, "=B{uc}/B{dc}", None)]
        u, d = r + 3, r + 4
        for lab, key, fmt, fs, fb in rows_q:
            _lab(wc, f"A{r}", lab)
            pos = {"u": u, "d": d, "uc": u + 2, "dc": u + 3}
            if fs:
                _f(wc, f"B{r}", fs.format(**pos), fmt, F_BASE if "{" in fs else None)
                items.append(("Quarterly capture", lab + (", strategy" if isinstance(key, tuple) else ""), qc[key[0] if isinstance(key, tuple) else key], f"'Index and capture'!B{r}"))
            if fb:
                _f(wc, f"C{r}", fb, fmt)
                items.append(("Quarterly capture", lab + (", benchmark" if isinstance(key, tuple) else ""), qc[key[1] if isinstance(key, tuple) else key], f"'Index and capture'!C{r}"))
            r += 1
        if qc["part_quarters_left_out"]:
            put(wc, f"A{r}", "Part quarters left out: " + ", ".join(qc["part_quarters_left_out"]) + ".", F_NOTE)
    widths(wc, [44, 22, 26])

    # ------------------------------------------------------------------------------------------------ Calendar years
    wy = sheet("Calendar years", "Calendar-year performance and the maximum drawdown inside each calendar year, on month-end values. A fall in a year's first month is not "
                                 "counted, as in the reference. * returns from the first month; ** returns till the last complete month.")
    r = table(wy, 4, ["Calendar year", f"{s_name}: return", f"{b_lab}: return", "Alpha", f"{s_name}: max drawdown in the year", f"{b_lab}: max drawdown in the year"])
    for t, i, j in zip(blk["tables"]["calendar_year"], where["tables"]["calendar_year"], where["tables"]["calendar_year_drawdown"]):
        _lab(wy, f"A{r}", t["label"] + (" (part year)" if t["part"] else ""))
        _f(wy, f"B{r}", f"={SEQ}K{i}", PCT2)
        _f(wy, f"C{r}", f"={SEQ}L{i}", PCT2)
        _f(wy, f"D{r}", f"=B{r}-C{r}", PCT2)
        _f(wy, f"E{r}", f"={SEQ}K{j}", PCT2)
        _f(wy, f"F{r}", f"={SEQ}L{j}", PCT2)
        r += 1
    widths(wy, [22, 24, 26, 12, 30, 32])

    has_alloc = bool(alloc) and alloc.get("status") == "built"
    if has_alloc:
        from . import allocation
        items += allocation.write_sheet(wb, alloc)

    # ------------------------------------------------------------------------------------------------ Daily calculations
    items += _daily_sheet(wb, ch, s_name, b_name, first, last, R)
    se_sheet.write_check_sheet(wb, items)
    order = ["Returns overview", "Market phases", "Rolling returns", "Factor attribution", "Drawdown and risk", "Tail risk", "Index and capture", "Calendar years"] \
        + (["Allocation"] if has_alloc else []) + ["Daily calculations", se_sheet.CHECK, se_sheet.SHEET, MS, "Returns"]
    wb._sheets = [wb[nm] for nm in order]
    pv = provenance or {}
    put(wb["Returns overview"], "A4", f"Run {pv.get('run_id', '?')} · card sha256 {(pv.get('card_sha256_approved') or pv.get('card_sha256_run') or '?')[:12]} · "
        f"Lightyear code {pv.get('code_hash_disk', '?')} · {SIGN}", F_NOTE)
    wb.save(out_path)
    return {"sheets": order, "n_checked": len(items)}


def _daily_sheet(wb, ch, s_name, b_name, first, last, R) -> list[tuple[str, str, Any, str]]:
    """Every daily metric as a live formula over the Returns sheet (each reproduces ros/metrics/core.py), its formula in
    words, and the monthly figure of the same name beside it. Returns the items the Python vs Excel sheet checks."""
    ws = wb.create_sheet("Daily calculations")
    m, b = ch["metrics"]["strategy"], ch["metrics"]["benchmark"]
    rf = ch["sharpe_hurdle"]
    put(ws, "A1", "Daily calculations", F_TITLE)
    put(ws, "A2", "The daily block: daily returns, sample standard deviation, 252 days a year, years = calendar days / 365.25, losses as positive numbers. The monthly columns "
        f"are the main display's figures; the two differ by construction and neither is wrong. Gate B uses its own daily tests, not this sheet. {SIGN}", F_NOTE)
    put(ws, "A3", "Risk-free rate (config/fund.yaml)", F_BOLD)
    put(ws, "B3", rf, F_INPUT, PCT2, FILL_KEY, border=True, comment="Key assumption: the one risk-free rate, config/fund.yaml. A yardstick, not income.")
    put(ws, "C3", "=(1+Risk_Free_Rate)^(1/252)-1", F_BASE, "0.000000%", border=True)
    put(ws, "D3", "the same rate for one day", F_NOTE)
    name(wb, "Risk_Free_Rate", "'Daily calculations'!$B$3")
    name(wb, "Risk_Free_Daily", "'Daily calculations'!$C$3")
    header(ws, 5, ["Metric (daily)", "Daily formula", f"{s_name}: daily", f"{b_name}: daily", "Monthly figure of the same kind", f"{s_name}: monthly", f"{b_name}: monthly"], height=34)
    n = last - first + 1
    sortino = "=({c}8-Risk_Free_Rate)/(SQRT(SUMPRODUCT(({r}-Risk_Free_Daily<0)*({r}-Risk_Free_Daily)^2)/COUNT({r}))*SQRT(252))"
    dur = "ARRAY:=MAX(_xlfn.SCAN(0,{dd},_xlfn.LAMBDA(_xlpm.a,_xlpm.x,IF(_xlpm.x<-0.000000000001,_xlpm.a+1,0))))"
    cvar = "ARRAY:=-AVERAGE(IF({r}<=_xlfn.PERCENTILE.INC({r},0.05),{r}))"
    best = "ARRAY:=(PRODUCT(1+{r})/PRODUCT(1+LARGE({r},{{1;2;3;4;5;6;7;8;9;10}})))^(365.25/(MAX(Dates)-INDEX(Dates,2)))-1"
    roll = (f"=SUMPRODUCT(--((Returns!$D${first + 251}:$D${last}/Returns!$D$2:$D${last - 252})<(Returns!$E${first + 251}:$E${last}/Returns!$E$2:$E${last - 252})))/{n - 251}"
            if n > 252 else None)
    S, B = {"r": "Ret_Strat", "dd": "DD_Strat", "v": "Val_Strat", "c": "C"}, {"r": "Ret_Bench", "dd": "DD_Bench", "v": "Val_Bench", "c": "D"}
    # label, key, format, formula (strategy and benchmark share it; {..} filled per column; None = strategy only), words, monthly SE label
    rows = [("Years", "years", NUM2, "=(MAX(Dates)-Start_Date)/365.25", "(last date - start date) / 365.25", None),
            ("Final value (100 = start)", "final", "0.00", "=INDEX({v},ROWS({v}))", "100 x product of (1 + daily return)", "Total Return"),
            ("CAGR", "cagr", PCT2, "=({c}7/100)^(1/{c}6)-1", "(final / 100)^(1 / years) - 1", "CAGR"),
            ("Volatility", "vol", PCT2, "=STDEV({r})*SQRT(252)", "sample stdev of daily returns x sqrt(252)", "Annualized Volatility"),
            ("Sharpe", "sharpe", NUM2, "=({c}8-Risk_Free_Rate)/{c}9", "(CAGR - risk-free rate) / volatility", "Sharpe Ratio"),
            ("Sortino", "sortino", NUM2, sortino, "(CAGR - risk-free rate) / downside deviation of daily returns below the daily risk-free rate", "Sortino Ratio"),
            ("Maximum drawdown", "max_dd", PCT2, "=-MIN({dd})", "largest fall of the daily value from its previous high, as a positive number", "Max Drawdown"),
            ("Calmar", "calmar", NUM2, "={c}8/{c}12", "CAGR / maximum drawdown", "Calmar Ratio"),
            ("Drawdown duration (trading days)", "dd_duration_days", INT, dur, "longest run of days below a previous high", None),
            ("95% CVaR (daily loss)", "cvar_95", PCT2, cvar, "minus the average of the daily returns at or below their 5th percentile", "95% CVaR"),
            ("Skew", "skew", NUM2, "=SKEW({r})", "sample skew of daily returns", "Skewness"),
            ("CAGR without the 10 best days", "best_days_removed_cagr", PCT2, best, "the 10 best days removed, then compounded; years from the first return date", None),
            ("Beta", "beta", NUM2, None, "slope of daily returns on the benchmark's (both over the card's cash rate)", "Beta"),
            ("Tracking error", "tracking_error", PCT2, None, "sample stdev of (daily return - benchmark's) x sqrt(252)", "Tracking Error"),
            ("Information ratio", "information_ratio", NUM2, None, "mean of (daily return - benchmark's) x 252 / tracking error", "Information Ratio"),
            ("Rolling one-year periods behind", "rolling_behind", PCT2, None, "share of 252-day windows with a compounded return below the benchmark's", None)]
    only_s = {"beta": "=SLOPE(Ret_Strat,Ret_Bench)", "tracking_error": "ARRAY:=STDEV(Ret_Strat-Ret_Bench)*SQRT(252)",
              "information_ratio": "ARRAY:=AVERAGE(Ret_Strat-Ret_Bench)*252/(STDEV(Ret_Strat-Ret_Bench)*SQRT(252))", "rolling_behind": roll}
    items = []
    for i, (label, key, fmt, fx, words, mon) in enumerate(rows, start=6):
        _lab(ws, f"A{i}", label)
        put(ws, f"B{i}", words, F_NOTE, border=True)
        for col, who, d, src in (("C", "strategy", S, m), ("D", "benchmark", B, b)):
            text = fx.format(**d) if fx else (only_s[key] if col == "C" else None)
            if text is None or src.get(key) is None:
                put(ws, f"{col}{i}", None, F_BASE, border=True)
                continue
            _f(ws, f"{col}{i}", text, fmt)
            items.append(("Daily calculations", f"{label}, {who}", src.get(key), f"'Daily calculations'!{col}{i}"))
        _lab(ws, f"E{i}", (mon + " (monthly)") if mon else "none")
        if mon:
            _f(ws, f"F{i}", f"={SEQ}K{R[mon]}", PCT2 if fmt in (PCT2, "0.00") else fmt)
            if mon not in ("Tracking Error", "Information Ratio"):
                _f(ws, f"G{i}", f"={SEQ}L{R[mon]}", PCT2 if fmt in (PCT2, "0.00") else fmt)
    r = 7 + len(rows)
    put(ws, f"A{r}", "The monthly Max Drawdown and 95% CVaR are negative numbers and the daily ones positive: each block keeps its own sign convention. "
        "The monthly Total Return sits beside the daily final value: final / 100 - 1 over all days against the product of the complete months.", F_NOTE)
    gross = ch.get("gross")
    if gross:
        put(ws, f"A{r + 2}", f"Before the card's {ch.get('card_bp')}bp round-trip cost (Python values; the gross returns are not in the workbook)", F_BOLD)
        for j, (label, key, fmt, *_rest) in enumerate(rows, start=r + 3):
            _lab(ws, f"A{j}", label)
            put(ws, f"C{j}", gross.get(key), F_INPUT, fmt, border=True)
    widths(ws, [34, 70, 20, 20, 34, 20, 20])
    ws.freeze_panes = "C6"
    return items
