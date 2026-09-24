"""Writes a live-formula Excel workbook matching the "SE Return Analytics"
tab layout (section headers, row labels, glossary column) -- built from
inspecting the real .xlsb, since pyxlsb only exposes computed VALUES, never
formula text. Every ratio below is a genuine Excel formula referencing the
raw monthly-return columns, computed by Excel when the file opens -- not a
value baked in by Python. That means these formulas are written from this
repo's own, independently-tested metric definitions (universal_backtester/
tearsheet.py), not transcribed from the source workbook, because the source
workbook's actual formulas are not retrievable from the .xlsb format at all
(pyxlsb's Cell has no .f / formula-text attribute, only .v / value).
Cross-check a few cells by hand against tearsheet.py's Python output before
trusting this for anything that matters.

Calibrated to the source workbook's own parameters, found in its own
"Parameters" panel: risk-free rate 5%, Omega threshold 1% (monthly),
drawdown limit 0%.
"""
from __future__ import annotations

import pandas as pd

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.formula import ArrayFormula
except ImportError as e:
    raise ImportError("excel_tearsheet.py needs openpyxl: pip install openpyxl") from e

DEFAULT_RISK_FREE_RATE = 0.05
DEFAULT_OMEGA_THRESHOLD = 0.01
DEFAULT_DRAWDOWN_LIMIT = 0.0

_GLOSSARY = [
    ("Annualized Volatility", "Measures how much an investment’s returns fluctuate on an annualized basis calculated using standard deviation."),
    ("Positive Volatility", "Measures fluctuations in returns when the investment's returns are positive"),
    ("Negative Volatility", "Measures fluctuations in returns when the investment's returns are negative"),
    ("Sharpe Ratio", "Shows how much returns an investment delivers per unit of risk - higher is better."),
    ("Treynor Ratio", "Measures return per unit of market risk."),
    ("Sortino Ratio", "Evaluates an investment's returns relative to only downside risk - higher means better returns with fewer losses."),
    ("Calmar Ratio", "Measures the risk-adjusted return of a portfolio by comparing its return to the worst peak-to-trough decline (drawdown)"),
    ("Sterling Ratio", "Measures return over average drawdown"),
    ("Omega Ratio", "Measures the likelihood and magnitude of gains vs. losses, based on a chosen threshold."),
    ("Gain to Pain Ratio", "Evaluates reward per unit of risk, focusing purely on the magnitude of profits vs. losses"),
    ("Tail Ratio", "Ratio of 95th to 5th percentile returns. Measures skewness and extremes in the return distribution."),
    ("Alpha (Adj Beta)", "Jensen's Alpha, indicates whether an investment performed better after adjusting for market risk."),
    ("Tracking Error", "Measures how closely a portfolio follows its benchmark. (Standard deviation of the Alpha)"),
    ("Ret +Ve Nifty 500 TRI", "Average Monthly Returns when Benchmark (Nifty 500 TRI) Returns is positive"),
    ("Ret -Ve Nifty 500 TRI", "Average Monthly Returns when Benchmark (Nifty 500 TRI) Returns is negative"),
    ("Upside Capture", "Measures how much times an investment returns rises during market upswings - higher the better"),
    ("Downside Capture", "Measures how much times an investment returns declines during market downturns - lower the better"),
    ("Capture Ratio", "Ratio of upside to downside capture - a ratio above 1 means the investment gains more in up markets than it loses in down markets."),
    ("Extreme Capture Ratio", "Assesses portfolio performance specifically during periods of extreme market moves — typically the top and bottom percentile of benchmark returns."),
    ("Skewness", "Indicates asymmetry in returns. Positive skew = rare large gains; negative = rare large losses."),
    ("Kurtosis", "Measures “tailedness” of returns. High kurtosis = frequent extreme outcomes."),
    ("95% VaR (Value at Risk)", "Expected loss in the worst 5% of scenarios. Indicates threshold beyond which losses rarely occur."),
    ("99% VaR", "Stricter version of VaR capturing the worst 1% outcomes. Used in high-risk contexts."),
    ("95% CVaR (Conditional VaR)", "Average loss in the worst 5% of cases beyond VaR. Captures tail risk magnitude."),
    ("99%  CVaR", "Average loss in the worst 1% of cases beyond VaR. Reflects extreme downside exposure."),
]

_HEADER_FILL = PatternFill(start_color="2F6F62", end_color="2F6F62", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_SECTION_FONT = Font(bold=True)

# Helper columns (kept off to the right, past the glossary) for the running
# NAV / running-peak series that Max Drawdown needs -- Excel has no single
# built-in function for "max drawdown of a return series."
_NAV_G_COL, _NAV_H_COL = 18, 19    # R, S
_PEAK_G_COL, _PEAK_H_COL = 20, 21  # T, U


def write_se_return_analytics_workbook(
    path: str,
    monthly_dates: pd.DatetimeIndex,
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    strategy_name: str = "Strategy",
    benchmark_name: str = "Nifty 500 TRI",
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    omega_threshold: float = DEFAULT_OMEGA_THRESHOLD,
    drawdown_limit: float = DEFAULT_DRAWDOWN_LIMIT,
) -> None:
    """Write a live-formula .xlsx replicating the SE Return Analytics layout.

    `strategy_returns` / `benchmark_returns` must be MONTHLY simple returns
    (not cumulative, not annualized), aligned to `monthly_dates`. Every cell
    in the Parameters/Analytics panel is a real Excel formula referencing
    the raw data columns -- open the file and click a cell to see it.
    """
    n = len(monthly_dates)
    if not (len(strategy_returns) == len(benchmark_returns) == n):
        raise ValueError("monthly_dates, strategy_returns, benchmark_returns must be the same length")
    if n < 2:
        raise ValueError(f"need at least 2 months of data, got {n}")

    wb = Workbook()
    ws = wb.active
    ws.title = "SE Return Analytics"

    first_row = 4
    last_row = first_row + n - 1
    C = f"C{first_row}:C{last_row}"
    D = f"D{first_row}:D{last_row}"

    # ---- raw monthly data (columns B, C, D) -------------------------------
    ws["B3"], ws["C3"], ws["D3"] = "Months", strategy_name, benchmark_name
    for col in ("B3", "C3", "D3"):
        ws[col].font = _HEADER_FONT
        ws[col].fill = _HEADER_FILL
    for i, (dt, sr, br) in enumerate(zip(monthly_dates, strategy_returns, benchmark_returns)):
        row = first_row + i
        ws.cell(row=row, column=2, value=pd.Timestamp(dt).to_pydatetime()).number_format = "mmm-yy"
        ws.cell(row=row, column=3, value=float(sr)).number_format = "0.00%"
        ws.cell(row=row, column=4, value=float(br)).number_format = "0.00%"

    # ---- running NAV / running peak helper columns (for Max Drawdown) -----
    ws.cell(row=3, column=_NAV_G_COL, value="NAV helper (strategy)")
    ws.cell(row=3, column=_NAV_H_COL, value="NAV helper (benchmark)")
    ws.cell(row=3, column=_PEAK_G_COL, value="Running peak (strategy)")
    ws.cell(row=3, column=_PEAK_H_COL, value="Running peak (benchmark)")
    for i in range(n):
        row = first_row + i
        nav_g = f"{get_column_letter(_NAV_G_COL)}{row}"
        nav_h = f"{get_column_letter(_NAV_H_COL)}{row}"
        prev_g = "1" if i == 0 else f"{get_column_letter(_NAV_G_COL)}{row - 1}"
        prev_h = "1" if i == 0 else f"{get_column_letter(_NAV_H_COL)}{row - 1}"
        ws.cell(row=row, column=_NAV_G_COL, value=f"={prev_g}*(1+C{row})")
        ws.cell(row=row, column=_NAV_H_COL, value=f"={prev_h}*(1+D{row})")
        prev_peak_g = nav_g if i == 0 else f"{get_column_letter(_PEAK_G_COL)}{row - 1}"
        prev_peak_h = nav_h if i == 0 else f"{get_column_letter(_PEAK_H_COL)}{row - 1}"
        ws.cell(row=row, column=_PEAK_G_COL, value=(f"={nav_g}" if i == 0 else f"=MAX({nav_g},{prev_peak_g})"))
        ws.cell(row=row, column=_PEAK_H_COL, value=(f"={nav_h}" if i == 0 else f"=MAX({nav_h},{prev_peak_h})"))
    NAV_G = f"{get_column_letter(_NAV_G_COL)}{first_row}:{get_column_letter(_NAV_G_COL)}{last_row}"
    NAV_H = f"{get_column_letter(_NAV_H_COL)}{first_row}:{get_column_letter(_NAV_H_COL)}{last_row}"
    PEAK_G = f"{get_column_letter(_PEAK_G_COL)}{first_row}:{get_column_letter(_PEAK_G_COL)}{last_row}"
    PEAK_H = f"{get_column_letter(_PEAK_H_COL)}{first_row}:{get_column_letter(_PEAK_H_COL)}{last_row}"

    # ---- parameters (named cells every formula below references) ---------
    ws["N1"], ws["O1"] = "Risk Free Rate", risk_free_rate
    ws["N2"], ws["O2"] = "Omega Threshold (monthly)", omega_threshold
    ws["N3"], ws["O3"] = "Drawdown Limit", drawdown_limit
    RFR, OMEGA_T = "$O$1", "$O$2"

    # ---- Parameters / Analytics panel (columns F, G, H) --------------------
    ws["F3"], ws["G3"], ws["H3"] = "Parameters", strategy_name, benchmark_name
    for col in ("F3", "G3", "H3"):
        ws[col].font = _HEADER_FONT
        ws[col].fill = _HEADER_FILL

    row_of = {}   # label -> row number, so later formulas can reference earlier ones by name

    def section(r, label):
        ws.cell(row=r, column=6, value=label).font = _SECTION_FONT

    def metric(r, label, g_formula, h_formula, pct=True):
        row_of[label] = r
        ws.cell(row=r, column=6, value=label)
        gc, hc = ws.cell(row=r, column=7), ws.cell(row=r, column=8)
        gc.value, hc.value = g_formula, h_formula
        gc.number_format = hc.number_format = "0.00%" if pct else "0.00"

    def g(label):
        return f"G{row_of[label]}"

    def h(label):
        return f"H{row_of[label]}"

    r = 5
    section(r, "Performance"); r += 1
    metric(r, "Total Return", f"=PRODUCT(1+{C})-1", f"=PRODUCT(1+{D})-1"); r += 1
    metric(r, "CAGR", f"=(1+{g('Total Return')})^(12/COUNT({C}))-1", f"=(1+{h('Total Return')})^(12/COUNT({D}))-1"); r += 1
    metric(r, "Avg Month Ret", f"=AVERAGE({C})", f"=AVERAGE({D})"); r += 1
    metric(r, "Positive Months", f"=COUNTIF({C},\">0\")", f"=COUNTIF({D},\">0\")", pct=False); r += 1
    metric(r, "Negative Months", f"=COUNTIF({C},\"<0\")", f"=COUNTIF({D},\"<0\")", pct=False); r += 1
    metric(r, "Max Month Ret", f"=MAX({C})", f"=MAX({D})"); r += 1
    metric(r, "Min Month Ret", f"=MIN({C})", f"=MIN({D})"); r += 1
    r += 1

    section(r, "Risk Parameters"); r += 1
    metric(r, "Annualized Volatility", f"=STDEV({C})*SQRT(12)", f"=STDEV({D})*SQRT(12)"); r += 1
    metric(r, "Positive Monthly Vol",
          ArrayFormula(f"G{r}", f"=STDEV(IF({C}>0,{C}))*SQRT(12)"),
          ArrayFormula(f"H{r}", f"=STDEV(IF({D}>0,{D}))*SQRT(12)")); r += 1
    metric(r, "Negative Monthly Vol",
          ArrayFormula(f"G{r}", f"=STDEV(IF({C}<0,{C}))*SQRT(12)"),
          ArrayFormula(f"H{r}", f"=STDEV(IF({D}<0,{D}))*SQRT(12)")); r += 1
    metric(r, "Max Drawdown",
          ArrayFormula(f"G{r}", f"=MIN({NAV_G}/{PEAK_G})-1"),
          ArrayFormula(f"H{r}", f"=MIN({NAV_H}/{PEAK_H})-1")); r += 1
    metric(r, "Average Annual Max Drawdown", f"={g('Max Drawdown')}", f"={h('Max Drawdown')}"); r += 1
    metric(r, "Sharpe Ratio",
          f"=({g('CAGR')}-{RFR})/{g('Annualized Volatility')}",
          f"=({h('CAGR')}-{RFR})/{h('Annualized Volatility')}"); r += 1
    metric(r, "Treynor Ratio", "PENDING_BETA", "PENDING_BETA", pct=False); r += 1
    treynor_row = r - 1
    metric(r, "Sortino Ratio",
          ArrayFormula(f"G{r}", f"=({g('CAGR')}-{RFR})/(STDEV(IF({C}<0,{C}))*SQRT(12))"),
          ArrayFormula(f"H{r}", f"=({h('CAGR')}-{RFR})/(STDEV(IF({D}<0,{D}))*SQRT(12))")); r += 1
    metric(r, "Calmar Ratio", f"={g('CAGR')}/ABS({g('Max Drawdown')})", f"={h('CAGR')}/ABS({h('Max Drawdown')})"); r += 1
    metric(r, "Sterling Ratio",
          f"={g('CAGR')}/ABS({g('Average Annual Max Drawdown')})",
          f"={h('CAGR')}/ABS({h('Average Annual Max Drawdown')})"); r += 1
    metric(r, "Omega Ratio",
          f"=SUMIF({C},\">\"&{OMEGA_T},{C})/-SUMIF({C},\"<\"&{OMEGA_T},{C})",
          f"=SUMIF({D},\">\"&{OMEGA_T},{D})/-SUMIF({D},\"<\"&{OMEGA_T},{D})", pct=False); r += 1
    metric(r, "Gain to Pain ratio",
          f"=SUM({C})/-SUMIF({C},\"<0\")", f"=SUM({D})/-SUMIF({D},\"<0\")", pct=False); r += 1
    metric(r, "Tail Ratio",
          f"=ABS(PERCENTILE({C},0.95))/ABS(PERCENTILE({C},0.05))",
          f"=ABS(PERCENTILE({D},0.95))/ABS(PERCENTILE({D},0.05))", pct=False); r += 1
    r += 1

    section(r, "Performance Vs Index"); r += 1
    metric(r, "Beta", ArrayFormula(f"G{r}", f"=SLOPE({C},{D})"), "=1", pct=False); r += 1
    metric(r, "Alpha", f"={g('CAGR')}-{h('CAGR')}", "=0"); r += 1
    metric(r, "Jensens Alpha (Adj Beta)",
          f"=({g('CAGR')}-{RFR})-((2/3*{g('Beta')}+1/3)*({h('CAGR')}-{RFR}))", "=0"); r += 1
    metric(r, "Tracking Error", ArrayFormula(f"G{r}", f"=STDEV({C}-{D})*SQRT(12)"), "=0"); r += 1
    # Now that Beta exists, fill in the Treynor row left pending above.
    ws.cell(row=treynor_row, column=7).value = f"=({g('CAGR')}-{RFR})/{g('Beta')}"
    ws.cell(row=treynor_row, column=8).value = f"=({h('CAGR')}-{RFR})/1"
    r += 1

    section(r, "Capture Ratio"); r += 1
    metric(r, "Ret +Ve Nifty 500 TRI", f"=AVERAGEIF({D},\">0\",{C})", f"=AVERAGEIF({D},\">0\",{D})"); r += 1
    metric(r, "Ret -Ve Nifty 500 TRI", f"=AVERAGEIF({D},\"<0\",{C})", f"=AVERAGEIF({D},\"<0\",{D})"); r += 1
    metric(r, "Upside Capture", f"={g('Ret +Ve Nifty 500 TRI')}/{h('Ret +Ve Nifty 500 TRI')}", "=1", pct=False); r += 1
    metric(r, "Downside Capture", f"={g('Ret -Ve Nifty 500 TRI')}/{h('Ret -Ve Nifty 500 TRI')}", "=1", pct=False); r += 1
    metric(r, "Capture Ratio", f"={g('Upside Capture')}/{g('Downside Capture')}", "=1", pct=False); r += 1
    r += 1

    section(r, "Tail Risk"); r += 1
    metric(r, "Skewness", f"=SKEW({C})", f"=SKEW({D})", pct=False); r += 1
    metric(r, "Kurtosis", f"=KURT({C})", f"=KURT({D})", pct=False); r += 1
    metric(r, "95% VaR", f"=-PERCENTILE({C},0.05)", f"=-PERCENTILE({D},0.05)"); r += 1
    metric(r, "99% VaR", f"=-PERCENTILE({C},0.01)", f"=-PERCENTILE({D},0.01)"); r += 1
    metric(r, "95% CVaR",
          ArrayFormula(f"G{r}", f"=-AVERAGE(IF({C}<=PERCENTILE({C},0.05),{C}))"),
          ArrayFormula(f"H{r}", f"=-AVERAGE(IF({D}<=PERCENTILE({D},0.05),{D}))")); r += 1
    metric(r, "99%  CVaR",
          ArrayFormula(f"G{r}", f"=-AVERAGE(IF({C}<=PERCENTILE({C},0.01),{C}))"),
          ArrayFormula(f"H{r}", f"=-AVERAGE(IF({D}<=PERCENTILE({D},0.01),{D}))")); r += 1

    assert "PENDING_BETA" not in str(ws.cell(row=treynor_row, column=7).value), \
        "Treynor row was never backfilled -- a real bug, not a placeholder left on purpose"

    # ---- glossary (columns K, L) ------------------------------------------
    ws["K3"], ws["L3"] = "Analytics", "Glossary"
    ws["K3"].font = _HEADER_FONT
    ws["K3"].fill = _HEADER_FILL
    ws["L3"].font = _HEADER_FONT
    ws["L3"].fill = _HEADER_FILL
    for i, (label, text) in enumerate(_GLOSSARY):
        row = first_row + i
        ws.cell(row=row, column=11, value=label)
        ws.cell(row=row, column=12, value=text).alignment = Alignment(wrap_text=True)

    for col, width in (("A", 3), ("B", 10), ("C", 14), ("D", 14), ("F", 26),
                       ("G", 14), ("H", 14), ("K", 26), ("L", 60)):
        ws.column_dimensions[col].width = width

    wb.save(path)
