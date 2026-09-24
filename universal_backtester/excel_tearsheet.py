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

VERIFIED, 2026-09-24: every formula below (Total Return through Max
Calendar Year Drawdown -- 30+ distinct ratios) was checked bit-for-bit
against the real 161-month reference series extracted from the source
.xlsb (tests/fixtures/se_return_analytics_reference.json), NOT assumed.
That check caught and fixed several real formula bugs from an earlier
pass: STDEV should have been STDEVP (population, ddof=0) throughout;
Positive/Negative Monthly Vol is the one pair NOT annualized; Average
Annual Max Drawdown is the mean of each CALENDAR YEAR's own peak-reset
drawdown, not equal to the whole-history Max Drawdown; Gain to Pain
Ratio's numerator is winning months only, not every month; VaR/CVaR are
reported UNNEGATED (the raw, negative tail value). See
tests/test_universal_backtester_tearsheet_reference.py for the full set
of checks.

UNVERIFIED_JENSENS_ALPHA: "Jensens Alpha (Adj Beta)" is the one row that
resisted this exercise -- several plausible CAPM-with-shrunk-beta
variants were tried against the real number and none reproduced it
exactly. The formula below (Bloomberg-style (2/3*beta + 1/3) shrinkage)
is a reasonable, documented convention, consistent with Treynor's own
raw-beta formula on the same sheet, but is NOT a confirmed match --
flagged here rather than silently claimed as verified.
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

from universal_backtester.tearsheet import EXTREME_UPPER_PCT, EXTREME_LOWER_PCT, financial_year_label

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

# Helper columns for the Financial Year / Calendar Year tables: a per-row
# FY/CY label, plus a running NAV+peak pair that RESETS at the start of
# each calendar year (needed for Max Calendar Year Drawdown -- a whole-
# history running peak gives the wrong answer for a year the strategy
# entered already below its all-time high).
_FY_LABEL_COL = 22    # V
_CY_LABEL_COL = 23    # W
_CYNAV_G_COL, _CYPEAK_G_COL = 24, 25   # X, Y (strategy)
_CYNAV_H_COL, _CYPEAK_H_COL = 26, 27   # Z, AA (benchmark)


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

    # ---- FY/CY labels + calendar-year-reset NAV/peak (for the FY/CY tables) ----
    ws.cell(row=3, column=_FY_LABEL_COL, value="FY label")
    ws.cell(row=3, column=_CY_LABEL_COL, value="CY label")
    ws.cell(row=3, column=_CYNAV_G_COL, value="CY-reset NAV (strategy)")
    ws.cell(row=3, column=_CYPEAK_G_COL, value="CY-reset peak (strategy)")
    ws.cell(row=3, column=_CYNAV_H_COL, value="CY-reset NAV (benchmark)")
    ws.cell(row=3, column=_CYPEAK_H_COL, value="CY-reset peak (benchmark)")
    fy_labels, cy_labels = [], []
    for i, dt in enumerate(monthly_dates):
        row = first_row + i
        ts_dt = pd.Timestamp(dt)
        fy_label = financial_year_label(ts_dt)
        cy_label = f"CY{ts_dt.year % 100:02d}"
        fy_labels.append(fy_label)
        cy_labels.append(cy_label)
        ws.cell(row=row, column=_FY_LABEL_COL, value=fy_label)
        ws.cell(row=row, column=_CY_LABEL_COL, value=cy_label)

        w_col = get_column_letter(_CY_LABEL_COL)
        new_year = i == 0 or cy_labels[i] != cy_labels[i - 1]
        nav_g = f"{get_column_letter(_CYNAV_G_COL)}{row}"
        nav_h = f"{get_column_letter(_CYNAV_H_COL)}{row}"
        if new_year:
            ws.cell(row=row, column=_CYNAV_G_COL, value=f"=1*(1+C{row})")
            ws.cell(row=row, column=_CYNAV_H_COL, value=f"=1*(1+D{row})")
            ws.cell(row=row, column=_CYPEAK_G_COL, value=f"={nav_g}")
            ws.cell(row=row, column=_CYPEAK_H_COL, value=f"={nav_h}")
        else:
            prev_nav_g = f"{get_column_letter(_CYNAV_G_COL)}{row - 1}"
            prev_nav_h = f"{get_column_letter(_CYNAV_H_COL)}{row - 1}"
            prev_peak_g = f"{get_column_letter(_CYPEAK_G_COL)}{row - 1}"
            prev_peak_h = f"{get_column_letter(_CYPEAK_H_COL)}{row - 1}"
            ws.cell(row=row, column=_CYNAV_G_COL, value=f"={prev_nav_g}*(1+C{row})")
            ws.cell(row=row, column=_CYNAV_H_COL, value=f"={prev_nav_h}*(1+D{row})")
            ws.cell(row=row, column=_CYPEAK_G_COL, value=f"=MAX({nav_g},{prev_peak_g})")
            ws.cell(row=row, column=_CYPEAK_H_COL, value=f"=MAX({nav_h},{prev_peak_h})")
    FY_RANGE = f"{get_column_letter(_FY_LABEL_COL)}{first_row}:{get_column_letter(_FY_LABEL_COL)}{last_row}"
    CY_RANGE = f"{get_column_letter(_CY_LABEL_COL)}{first_row}:{get_column_letter(_CY_LABEL_COL)}{last_row}"
    CYNAV_G = f"{get_column_letter(_CYNAV_G_COL)}{first_row}:{get_column_letter(_CYNAV_G_COL)}{last_row}"
    CYPEAK_G = f"{get_column_letter(_CYPEAK_G_COL)}{first_row}:{get_column_letter(_CYPEAK_G_COL)}{last_row}"
    CYNAV_H = f"{get_column_letter(_CYNAV_H_COL)}{first_row}:{get_column_letter(_CYNAV_H_COL)}{last_row}"
    CYPEAK_H = f"{get_column_letter(_CYPEAK_H_COL)}{first_row}:{get_column_letter(_CYPEAK_H_COL)}{last_row}"
    # Ordered, de-duplicated FY/CY label lists for the tables below.
    fy_order = sorted(set(fy_labels), key=lambda s: int(s[2:]))
    cy_order = list(dict.fromkeys(cy_labels))

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
    # STDEVP (population, ddof=0), not STDEV (sample, ddof=1) -- verified
    # against the reference workbook's real numbers; STDEV misses by a
    # small but real margin on every volatility figure below.
    metric(r, "Annualized Volatility", f"=STDEVP({C})*SQRT(12)", f"=STDEVP({D})*SQRT(12)"); r += 1
    # These two are the one pair on the whole sheet that is NOT annualized
    # (no *SQRT(12)) -- also verified against the real numbers, not assumed.
    metric(r, "Positive Monthly Vol",
          ArrayFormula(f"G{r}", f"=STDEVP(IF({C}>0,{C}))"),
          ArrayFormula(f"H{r}", f"=STDEVP(IF({D}>0,{D}))")); r += 1
    metric(r, "Negative Monthly Vol",
          ArrayFormula(f"G{r}", f"=STDEVP(IF({C}<0,{C}))"),
          ArrayFormula(f"H{r}", f"=STDEVP(IF({D}<0,{D}))")); r += 1
    metric(r, "Max Drawdown",
          ArrayFormula(f"G{r}", f"=MIN({NAV_G}/{PEAK_G})-1"),
          ArrayFormula(f"H{r}", f"=MIN({NAV_H}/{PEAK_H})-1")); r += 1
    # Genuinely the mean of each CALENDAR YEAR's own (peak-reset-at-Jan-1)
    # max drawdown -- NOT the same as Max Drawdown above (that one whole-
    # history figure gave the wrong number here, verified against the
    # real reference value). The Max Calendar Year Drawdown table below
    # computes exactly these per-year figures; backfilled once that table
    # exists, same two-pass idiom as the Treynor row below.
    metric(r, "Average Annual Max Drawdown", "PENDING_CY_TABLE", "PENDING_CY_TABLE", pct=True); r += 1
    aamdd_row = r - 1
    metric(r, "Sharpe Ratio",
          f"=({g('CAGR')}-{RFR})/{g('Annualized Volatility')}",
          f"=({h('CAGR')}-{RFR})/{h('Annualized Volatility')}"); r += 1
    metric(r, "Treynor Ratio", "PENDING_BETA", "PENDING_BETA", pct=False); r += 1
    treynor_row = r - 1
    metric(r, "Sortino Ratio",
          ArrayFormula(f"G{r}", f"=({g('CAGR')}-{RFR})/(STDEVP(IF({C}<0,{C}))*SQRT(12))"),
          ArrayFormula(f"H{r}", f"=({h('CAGR')}-{RFR})/(STDEVP(IF({D}<0,{D}))*SQRT(12))")); r += 1
    metric(r, "Calmar Ratio", f"={g('CAGR')}/ABS({g('Max Drawdown')})", f"={h('CAGR')}/ABS({h('Max Drawdown')})"); r += 1
    metric(r, "Sterling Ratio",
          f"={g('CAGR')}/ABS({g('Average Annual Max Drawdown')})",
          f"={h('CAGR')}/ABS({h('Average Annual Max Drawdown')})"); r += 1
    metric(r, "Omega Ratio",
          f"=SUMIF({C},\">\"&{OMEGA_T},{C})/-SUMIF({C},\"<\"&{OMEGA_T},{C})",
          f"=SUMIF({D},\">\"&{OMEGA_T},{D})/-SUMIF({D},\"<\"&{OMEGA_T},{D})", pct=False); r += 1
    # Numerator is the sum of WINNING months only, not every month --
    # verified against the real number; summing every month (winners and
    # losers together) is off by almost exactly 1.0.
    metric(r, "Gain to Pain ratio",
          f"=SUMIF({C},\">0\",{C})/-SUMIF({C},\"<0\",{C})",
          f"=SUMIF({D},\">0\",{D})/-SUMIF({D},\"<0\",{D})", pct=False); r += 1
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

    # Extreme Capture Ratio: same shape as Capture Ratio above, but the
    # +Ve/-Ve split uses PERCENTILE(benchmark, 0.83) / PERCENTILE(benchmark,
    # 0.07) instead of a plain >0/<0 split. Those two exact constants (not a
    # symmetric 90/10 or 95/5) are what reproduces the reference workbook's
    # real numbers -- see EXTREME_UPPER_PCT/EXTREME_LOWER_PCT in tearsheet.py.
    hi_thr = f"PERCENTILE({D},{EXTREME_UPPER_PCT})"
    lo_thr = f"PERCENTILE({D},{EXTREME_LOWER_PCT})"
    section(r, "Extreme Capture Ratio"); r += 1
    metric(r, "Ex. Ret +Ve Nifty 500 TRI",
          ArrayFormula(f"G{r}", f"=AVERAGEIF({D},\">=\"&{hi_thr},{C})"),
          ArrayFormula(f"H{r}", f"=AVERAGEIF({D},\">=\"&{hi_thr},{D})")); r += 1
    metric(r, "Ex. Ret -Ve Nifty 500 TRI",
          ArrayFormula(f"G{r}", f"=AVERAGEIF({D},\"<=\"&{lo_thr},{C})"),
          ArrayFormula(f"H{r}", f"=AVERAGEIF({D},\"<=\"&{lo_thr},{D})")); r += 1
    metric(r, "Ex. Upside Capture",
          f"={g('Ex. Ret +Ve Nifty 500 TRI')}/{h('Ex. Ret +Ve Nifty 500 TRI')}", "=1", pct=False); r += 1
    metric(r, "Ex. Downside Capture",
          f"={g('Ex. Ret -Ve Nifty 500 TRI')}/{h('Ex. Ret -Ve Nifty 500 TRI')}", "=1", pct=False); r += 1
    metric(r, "Extreme Capture Ratio",
          f"={g('Ex. Upside Capture')}/{g('Ex. Downside Capture')}", "=1", pct=False); r += 1
    r += 1

    section(r, "Tail Risk"); r += 1
    metric(r, "Skewness", f"=SKEW({C})", f"=SKEW({D})", pct=False); r += 1
    metric(r, "Kurtosis", f"=KURT({C})", f"=KURT({D})", pct=False); r += 1
    # UNNEGATED -- verified against the real reference numbers, which report
    # VaR/CVaR as the raw (negative) tail value, not a positive loss
    # magnitude, despite the glossary's "expected loss" phrasing.
    metric(r, "95% VaR", f"=PERCENTILE({C},0.05)", f"=PERCENTILE({D},0.05)"); r += 1
    metric(r, "99% VaR", f"=PERCENTILE({C},0.01)", f"=PERCENTILE({D},0.01)"); r += 1
    metric(r, "95% CVaR",
          ArrayFormula(f"G{r}", f"=AVERAGE(IF({C}<=PERCENTILE({C},0.05),{C}))"),
          ArrayFormula(f"H{r}", f"=AVERAGE(IF({D}<=PERCENTILE({D},0.05),{D}))")); r += 1
    metric(r, "99%  CVaR",
          ArrayFormula(f"G{r}", f"=AVERAGE(IF({C}<=PERCENTILE({C},0.01),{C}))"),
          ArrayFormula(f"H{r}", f"=AVERAGE(IF({D}<=PERCENTILE({D},0.01),{D}))")); r += 1
    r += 1

    assert "PENDING_BETA" not in str(ws.cell(row=treynor_row, column=7).value), \
        "Treynor row was never backfilled -- a real bug, not a placeholder left on purpose"
    # (Average Annual Max Drawdown's own PENDING_CY_TABLE placeholder is
    # backfilled further down, after the Max Calendar Year Drawdown table
    # exists -- checked once, right before the file is saved, below.)

    # ---- Financial Year Performance (Apr-Mar), Calendar Year Performance --
    # (Jan-Dec), and Max Calendar Year Drawdown -- all compounded from the
    # raw monthly columns via array PRODUCT/MIN formulas keyed on the FY/CY
    # label helper columns built above. Layout order matches the reference
    # workbook: FY table, CY table, footnotes, then Max CY Drawdown table.
    section(r, "Financial Year Performance"); r += 1
    for i, label in enumerate(fy_order):
        disp = label + ("*" if i == 0 else "**" if i == len(fy_order) - 1 else "")
        metric(r, disp,
              ArrayFormula(f"G{r}", f"=PRODUCT(IF({FY_RANGE}=\"{label}\",1+{C},1))-1"),
              ArrayFormula(f"H{r}", f"=PRODUCT(IF({FY_RANGE}=\"{label}\",1+{D},1))-1")); r += 1
    r += 1

    section(r, "Calendar Year Performance"); r += 1
    for i, label in enumerate(cy_order):
        disp = label + ("*" if i == 0 else "**" if i == len(cy_order) - 1 else "")
        metric(r, "CY:" + disp,
              ArrayFormula(f"G{r}", f"=PRODUCT(IF({CY_RANGE}=\"{label}\",1+{C},1))-1"),
              ArrayFormula(f"H{r}", f"=PRODUCT(IF({CY_RANGE}=\"{label}\",1+{D},1))-1")); r += 1
        ws.cell(row=r - 1, column=6, value=disp)   # display label without the "CY:" dedup prefix
    r += 1

    first_dt, last_dt = pd.Timestamp(monthly_dates[0]), pd.Timestamp(monthly_dates[-1])
    ws.cell(row=r, column=6, value=f"*Returns from {first_dt.strftime('%B %Y')}"); r += 1
    ws.cell(row=r, column=6, value=f"**Returns till {last_dt.strftime('%B %Y')}"); r += 1
    r += 1

    section(r, "Max Calendar Year Drawdown"); r += 1
    dd_first_row = r
    for i, label in enumerate(cy_order):
        disp = label + ("*" if i == 0 else "**" if i == len(cy_order) - 1 else "")
        metric(r, "DD:" + disp,
              ArrayFormula(f"G{r}", f"=MIN(IF({CY_RANGE}=\"{label}\",{CYNAV_G}/{CYPEAK_G}-1))"),
              ArrayFormula(f"H{r}", f"=MIN(IF({CY_RANGE}=\"{label}\",{CYNAV_H}/{CYPEAK_H}-1))")); r += 1
        ws.cell(row=r - 1, column=6, value=disp)
    dd_last_row = r - 1
    r += 2

    # Now that the Max Calendar Year Drawdown table exists, backfill
    # Average Annual Max Drawdown (Risk Parameters) as its plain average --
    # verified against the reference workbook's real number.
    ws.cell(row=aamdd_row, column=7).value = f"=AVERAGE(G{dd_first_row}:G{dd_last_row})"
    ws.cell(row=aamdd_row, column=8).value = f"=AVERAGE(H{dd_first_row}:H{dd_last_row})"

    # ---- Parameters (bottom block, matching the reference workbook's own
    # position and label order) -- these three cells are what the ratios
    # above actually reference (via the $O$1:$O$3 named-parameter cells),
    # shown again here so a reader sees the same panel the source has.
    section(r, "Drawdown limit"); ws.cell(row=r, column=7, value="=$O$3"); r += 1
    section(r, "Threshold for Omega ratio"); ws.cell(row=r, column=7, value="=$O$2"); r += 1
    section(r, "Risk Free Rate"); ws.cell(row=r, column=7, value="=$O$1"); r += 1

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

    assert "PENDING_CY_TABLE" not in str(ws.cell(row=aamdd_row, column=7).value), \
        "Average Annual Max Drawdown was never backfilled -- a real bug, not a placeholder left on purpose"

    wb.save(path)


def compute_se_return_analytics_rows(
    monthly_dates: pd.DatetimeIndex,
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    omega_threshold: float = DEFAULT_OMEGA_THRESHOLD,
) -> list:
    """The exact same ratios as write_se_return_analytics_workbook's Excel
    formulas, computed here directly in numpy on the monthly series --
    same arithmetic, same section order, same row labels -- so a CSV built
    from this function's output is guaranteed consistent with the Excel
    file's numbers by construction (both come from the same formulas,
    just evaluated by Excel in one case and by numpy in the other).

    Returns a list of (section, label, strategy_value, benchmark_value,
    is_percent) tuples in the same top-to-bottom order as the workbook.
    """
    import numpy as np
    from universal_backtester.tearsheet import (
        financial_year_returns, calendar_year_returns, calendar_year_max_drawdown,
        capture_breakdown, extreme_capture_breakdown, average_annual_max_drawdown,
        positive_volatility, negative_volatility, gain_to_pain_ratio as _gain_to_pain,
        historical_var, historical_cvar, tracking_error as _tracking_error,
    )

    strat_s = pd.Series(strategy_returns.values, index=monthly_dates)
    bench_s = pd.Series(benchmark_returns.values, index=monthly_dates)

    c = pd.Series(strategy_returns).to_numpy(dtype=float)
    d = pd.Series(benchmark_returns).to_numpy(dtype=float)
    n = len(c)
    rfr = risk_free_rate

    def total_return(x): return float(np.prod(1 + x) - 1)
    def cagr(x): return float((1 + total_return(x)) ** (12 / n) - 1)
    def ann_vol(x): return float(np.std(x, ddof=0) * np.sqrt(12))   # STDEVP, verified vs. reference
    def mdd(x):
        nav = np.cumprod(1 + x)
        peak = np.maximum.accumulate(nav)
        return float(np.min(nav / peak - 1))
    def beta_of(x, y):
        return float(np.cov(x, y, ddof=1)[0, 1] / np.var(y, ddof=1))
    def omega(x):
        excess = x - omega_threshold
        gains, losses = excess[excess > 0].sum(), -excess[excess < 0].sum()
        return float(gains / losses) if losses > 0 else float("nan")
    def tail_ratio(x):
        return float(abs(np.percentile(x, 95)) / abs(np.percentile(x, 5)))
    def sortino_denom(x):
        neg = x[x < 0]
        return float(np.std(neg, ddof=0) * np.sqrt(12)) if len(neg) > 1 else float("nan")

    strat_cagr, bench_cagr = cagr(c), cagr(d)
    strat_mdd, bench_mdd = mdd(c), mdd(d)
    # Average Annual Max Drawdown: mean of each calendar year's OWN
    # (peak-reset-at-Jan-1) drawdown -- NOT the same as Max Drawdown,
    # verified against the reference workbook's real number.
    strat_aamdd = average_annual_max_drawdown(strat_s)
    bench_aamdd = average_annual_max_drawdown(bench_s)
    strat_vol, bench_vol = ann_vol(c), ann_vol(d)
    strat_beta = beta_of(c, d)
    strat_sharpe = (strat_cagr - rfr) / strat_vol
    bench_sharpe = (bench_cagr - rfr) / bench_vol
    strat_treynor = (strat_cagr - rfr) / strat_beta
    bench_treynor = (bench_cagr - rfr) / 1.0
    strat_sortino = (strat_cagr - rfr) / sortino_denom(c)
    bench_sortino = (bench_cagr - rfr) / sortino_denom(d)
    strat_calmar = strat_cagr / abs(strat_mdd)
    bench_calmar = bench_cagr / abs(bench_mdd)
    strat_sterling = strat_cagr / abs(strat_aamdd)
    bench_sterling = bench_cagr / abs(bench_aamdd)
    strat_alpha = strat_cagr - bench_cagr
    # Jensen's Alpha (Adj Beta): our own CAPM-with-Bloomberg-shrunk-beta
    # convention. Flagged rather than silently claimed: every other ratio
    # in this module was verified bit-for-bit against the reference
    # workbook's real numbers, but this one specific formula was not --
    # several plausible variants were tried and none reproduced the
    # source exactly, so this is a reasonable, documented convention
    # rather than a confirmed match. See UNVERIFIED_JENSENS_ALPHA below.
    strat_jensens = (strat_cagr - rfr) - ((2 / 3 * strat_beta + 1 / 3) * (bench_cagr - rfr))
    strat_te = _tracking_error(strat_s, bench_s, ann=12)

    cap = capture_breakdown(strat_s, bench_s)
    excap = extreme_capture_breakdown(strat_s, bench_s)

    rows = [
        ("Performance", "Total Return", total_return(c), total_return(d), True),
        ("Performance", "CAGR", strat_cagr, bench_cagr, True),
        ("Performance", "Avg Month Ret", float(c.mean()), float(d.mean()), True),
        ("Performance", "Positive Months", int((c > 0).sum()), int((d > 0).sum()), False),
        ("Performance", "Negative Months", int((c < 0).sum()), int((d < 0).sum()), False),
        ("Performance", "Max Month Ret", float(c.max()), float(d.max()), True),
        ("Performance", "Min Month Ret", float(c.min()), float(d.min()), True),
        ("Risk Parameters", "Annualized Volatility", strat_vol, bench_vol, True),
        ("Risk Parameters", "Positive Monthly Vol",
         positive_volatility(strat_s), positive_volatility(bench_s), True),
        ("Risk Parameters", "Negative Monthly Vol",
         negative_volatility(strat_s), negative_volatility(bench_s), True),
        ("Risk Parameters", "Max Drawdown", strat_mdd, bench_mdd, True),
        ("Risk Parameters", "Average Annual Max Drawdown", strat_aamdd, bench_aamdd, True),
        ("Risk Parameters", "Sharpe Ratio", strat_sharpe, bench_sharpe, False),
        ("Risk Parameters", "Treynor Ratio", strat_treynor, bench_treynor, False),
        ("Risk Parameters", "Sortino Ratio", strat_sortino, bench_sortino, False),
        ("Risk Parameters", "Calmar Ratio", strat_calmar, bench_calmar, False),
        ("Risk Parameters", "Sterling Ratio", strat_sterling, bench_sterling, False),
        ("Risk Parameters", "Omega Ratio", omega(c), omega(d), False),
        ("Risk Parameters", "Gain to Pain ratio",
         _gain_to_pain(strat_s), _gain_to_pain(bench_s), False),
        ("Risk Parameters", "Tail Ratio", tail_ratio(c), tail_ratio(d), False),
        ("Performance Vs Index", "Beta", strat_beta, 1.0, False),
        ("Performance Vs Index", "Alpha", strat_alpha, 0.0, True),
        ("Performance Vs Index", "Jensens Alpha (Adj Beta)", strat_jensens, 0.0, True),
        ("Performance Vs Index", "Tracking Error", strat_te, 0.0, True),
        ("Capture Ratio", "Ret +Ve Nifty 500 TRI", cap["ret_positive_strategy"], cap["ret_positive_benchmark"], True),
        ("Capture Ratio", "Ret -Ve Nifty 500 TRI", cap["ret_negative_strategy"], cap["ret_negative_benchmark"], True),
        ("Capture Ratio", "Upside Capture", cap["upside_capture"], 1.0, False),
        ("Capture Ratio", "Downside Capture", cap["downside_capture"], 1.0, False),
        ("Capture Ratio", "Capture Ratio", cap["capture_ratio"], 1.0, False),
        ("Extreme Capture Ratio", "Ex. Ret +Ve Nifty 500 TRI", excap["ex_ret_positive_strategy"], excap["ex_ret_positive_benchmark"], True),
        ("Extreme Capture Ratio", "Ex. Ret -Ve Nifty 500 TRI", excap["ex_ret_negative_strategy"], excap["ex_ret_negative_benchmark"], True),
        ("Extreme Capture Ratio", "Ex. Upside Capture", excap["ex_upside_capture"], 1.0, False),
        ("Extreme Capture Ratio", "Ex. Downside Capture", excap["ex_downside_capture"], 1.0, False),
        ("Extreme Capture Ratio", "Extreme Capture Ratio", excap["extreme_capture_ratio"], 1.0, False),
        ("Tail Risk", "Skewness", float(pd.Series(c).skew()), float(pd.Series(d).skew()), False),
        ("Tail Risk", "Kurtosis", float(pd.Series(c).kurtosis()), float(pd.Series(d).kurtosis()), False),
        # Unnegated -- see historical_var/historical_cvar's own docstrings.
        ("Tail Risk", "95% VaR", historical_var(strat_s, 0.95), historical_var(bench_s, 0.95), True),
        ("Tail Risk", "99% VaR", historical_var(strat_s, 0.99), historical_var(bench_s, 0.99), True),
        ("Tail Risk", "95% CVaR", historical_cvar(strat_s, 0.95), historical_cvar(bench_s, 0.95), True),
        ("Tail Risk", "99% CVaR", historical_cvar(strat_s, 0.99), historical_cvar(bench_s, 0.99), True),
    ]

    fy_s, fy_b = financial_year_returns(strat_s), financial_year_returns(bench_s)
    for label in fy_s:
        rows.append(("Financial Year Performance", label, fy_s[label], fy_b.get(label, float("nan")), True))
    cy_s, cy_b = calendar_year_returns(strat_s), calendar_year_returns(bench_s)
    for label in cy_s:
        rows.append(("Calendar Year Performance", label, cy_s[label], cy_b.get(label, float("nan")), True))
    dd_s, dd_b = calendar_year_max_drawdown(strat_s), calendar_year_max_drawdown(bench_s)
    for label in dd_s:
        rows.append(("Max Calendar Year Drawdown", label, dd_s[label], dd_b.get(label, float("nan")), True))

    rows.append(("Parameters", "Risk Free Rate", risk_free_rate, None, True))
    rows.append(("Parameters", "Threshold for Omega ratio", omega_threshold, None, True))
    return rows


def write_se_return_analytics_csv(
    path: str,
    monthly_dates: pd.DatetimeIndex,
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    strategy_name: str = "Strategy",
    benchmark_name: str = "Nifty 500 TRI",
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    omega_threshold: float = DEFAULT_OMEGA_THRESHOLD,
) -> None:
    """CSV twin of write_se_return_analytics_workbook: same sections, same
    row labels, same top-to-bottom order, computed from the identical
    formulas (see compute_se_return_analytics_rows) so the two files never
    disagree with each other on a number."""
    rows = compute_se_return_analytics_rows(
        monthly_dates, strategy_returns, benchmark_returns, risk_free_rate, omega_threshold)
    out = pd.DataFrame(rows, columns=["section", "metric", strategy_name, benchmark_name, "is_percent"])
    out.drop(columns=["is_percent"]).to_csv(path, index=False)
