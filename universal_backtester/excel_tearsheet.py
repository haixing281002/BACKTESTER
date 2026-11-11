# Quant AI Researcher
"""The return-analytics workbook: every tearsheet metric as a live Excel formula over a sheet of DAILY returns.

Hard rule (2026-11-11): Python's ros/metrics/core.py is the single definition of every metric, and each formula here
reproduces it exactly. tests/test_excel_equals_python.py recalculates this workbook and fails the suite if any cell differs
from core by more than 1e-6. No metric may be defined in Excel only.

Conventions, the same as core: daily returns; sample standard deviation (STDEV); annualise with 252; the risk-free rate
from config/fund.yaml (shown as the risk-free rate); a loss, drawdown, VaR or CVaR is a positive number; years = calendar days / 365.25. Metrics that
are monthly by definition (month counts, gain to pain, capture ratios) use calendar-month compounding of the daily returns,
which is core.monthly_returns().

The earlier monthly "SE Return Analytics" layout (population standard deviation, a separate 5% risk-free cell, a 1% Omega
threshold, 83rd/7th percentile capture) was removed on the operator's instruction: one set of formulas only.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula

from ros import config
from ros.metrics import core
from universal_backtester.xlsx_style import (DATE, F_BASE, F_BOLD, F_INPUT, F_NOTE, F_TITLE, FILL_KEY, apply_house_style,
                                             header, name, put, widths)

PCT, NUM, INT = "0.00%", "0.0000", "0"
SIGNATURE = "Quant AI Researcher"

# label, formula for column x (S or B; None = strategy-only), number format, the definition in words
# {x} is S or B; {r} is this sheet's row of another metric, written as {r[Label]}.
_BOTH = [
    ("Total Return", "ARRAY:=PRODUCT(1+Ret_{x})-1", PCT, "product of (1 + r) - 1"),
    ("Years", "=(MAX(Dates)-Start_Date)/365.25", NUM, "calendar days from the base date / 365.25"),
    ("CAGR", "=(1+{c}{r[Total Return]})^(1/{c}{r[Years]})-1", PCT, "(1 + total return)^(1 / years) - 1"),
    ("Annualized Volatility", "=STDEV(Ret_{x})*SQRT(252)", PCT, "sample stdev of daily returns x sqrt(252)"),
    ("Positive Volatility", "ARRAY:=STDEV(IF(Ret_{x}>0,Ret_{x}))*SQRT(252)", PCT, "sample stdev of the days with a gain x sqrt(252)"),
    ("Negative Volatility", "ARRAY:=STDEV(IF(Ret_{x}<0,Ret_{x}))*SQRT(252)", PCT, "sample stdev of the days with a loss x sqrt(252)"),
    ("Max Drawdown", "=MAX(DD_{x})", PCT, "worst fall from a previous high on daily values, positive"),
    ("Average Annual Max Drawdown", "=AVERAGE(YearDD_{x})", PCT, "mean of each calendar year's worst fall; the year's peak starts at the prior year-end value"),
    ("Sharpe Ratio", "=({c}{r[CAGR]}-Risk_Free_Rate)/{c}{r[Annualized Volatility]}", NUM, "(CAGR - risk-free rate) / annualised volatility"),
    ("Sortino Ratio", "=({c}{r[CAGR]}-Risk_Free_Rate)/(SQRT(SUMPRODUCT((Ex_{x}<0)*Ex_{x}^2)/COUNT(Ret_{x}))*SQRT(252))", NUM,
     "(CAGR - risk-free rate) / downside deviation; downside deviation = sqrt(mean(min(r - rf, 0)^2)) x sqrt(252), rf the daily risk-free rate"),
    ("Calmar Ratio", "={c}{r[CAGR]}/{c}{r[Max Drawdown]}", NUM, "CAGR / max drawdown"),
    ("Sterling Ratio", "={c}{r[CAGR]}/{c}{r[Average Annual Max Drawdown]}", NUM, "CAGR / average annual max drawdown"),
    ("Omega Ratio", "=SUMPRODUCT((Ex_{x}>0)*Ex_{x})/-SUMPRODUCT((Ex_{x}<0)*Ex_{x})", NUM, "daily gains above the daily risk-free rate / daily shortfalls below it"),
    ("Gain to Pain Ratio", '=SUMIF(Mon_{x},">0")/-SUMIF(Mon_{x},"<0")', NUM, "sum of winning months / |sum of losing months|"),
    ("Tail Ratio", "=ABS(PERCENTILE(Ret_{x},0.95))/ABS(PERCENTILE(Ret_{x},0.05))", NUM, "|95th percentile| / |5th percentile| of daily returns"),
    ("Avg Month Ret", "=AVERAGE(Mon_{x})", PCT, "mean calendar-month return"),
    ("Max Month Ret", "=MAX(Mon_{x})", PCT, "best calendar month"),
    ("Min Month Ret", "=MIN(Mon_{x})", PCT, "worst calendar month"),
    ("Positive Months", '=COUNTIF(Mon_{x},">0")', INT, "months with a gain"),
    ("Negative Months", '=COUNTIF(Mon_{x},"<0")', INT, "months with a loss"),
    ("Skewness", "=SKEW(Ret_{x})", NUM, "sample skew of daily returns"),
    ("Excess Kurtosis", "=KURT(Ret_{x})", NUM, "sample excess kurtosis of daily returns; a bell curve is 0"),
    ("95% VaR", "=-PERCENTILE(Ret_{x},0.05)", PCT, "daily loss exceeded on 5% of days, positive"),
    ("99% VaR", "=-PERCENTILE(Ret_{x},0.01)", PCT, "daily loss exceeded on 1% of days, positive"),
    ("95% CVaR", "ARRAY:=-AVERAGE(IF(Ret_{x}<=PERCENTILE(Ret_{x},0.05),Ret_{x}))", PCT, "mean daily loss at or beyond the 95% VaR, positive"),
    ("99% CVaR", "ARRAY:=-AVERAGE(IF(Ret_{x}<=PERCENTILE(Ret_{x},0.01),Ret_{x}))", PCT, "mean daily loss at or beyond the 99% VaR, positive"),
]
_RELATIVE = [
    ("Beta", "=SLOPE(Ret_S,Ret_B)", NUM, "Cov(r, b) / Var(b) on daily returns"),
    ("Adjusted Beta", "=2/3*B{r[Beta]}+1/3", NUM, "2/3 x beta + 1/3"),
    ("Treynor Ratio", "=(B{r[CAGR]}-Risk_Free_Rate)/B{r[Beta]}", NUM, "(CAGR - risk-free rate) / beta"),
    ("Alpha", "=B{r[CAGR]}-C{r[CAGR]}", PCT, "CAGR - benchmark CAGR"),
    ("Jensens Alpha (Adj Beta)", "=(B{r[CAGR]}-Risk_Free_Rate)-B{r[Adjusted Beta]}*(C{r[CAGR]}-Risk_Free_Rate)", PCT, "(CAGR - risk-free rate) - adjusted beta x (benchmark CAGR - risk-free rate)"),
    ("Tracking Error", "=STDEV(Diff)*SQRT(252)", PCT, "sample stdev of (r - b) x sqrt(252)"),
    ("Information Ratio", "=AVERAGE(Diff)*252/B{r[Tracking Error]}", NUM, "mean(r - b) x 252 / tracking error"),
    ("Upside Capture", '=AVERAGEIF(Mon_B,">0",Mon_S)/AVERAGEIF(Mon_B,">0",Mon_B)', NUM, "mean monthly return / benchmark's, in months the benchmark rose"),
    ("Downside Capture", '=AVERAGEIF(Mon_B,"<0",Mon_S)/AVERAGEIF(Mon_B,"<0",Mon_B)', NUM, "the same, in months the benchmark fell"),
    ("Capture Ratio", "=B{r[Upside Capture]}/B{r[Downside Capture]}", NUM, "upside capture / downside capture"),
]
METRIC_LABELS = [m[0] for m in _BOTH] + [m[0] for m in _RELATIVE]


def _cell(ws, ref, text, fmt):
    if text.startswith("ARRAY:"):
        ws[ref] = ArrayFormula(ref, text[6:])
        ws[ref].font, ws[ref].number_format = F_BASE, fmt
    else:
        put(ws, ref, text, F_BASE, fmt, border=True)


def write_return_analytics_workbook(path: str, strategy_returns: pd.Series, benchmark_returns: pd.Series, start,
                                    strategy_name: str = "Strategy", benchmark_name: str = "Benchmark",
                                    hurdle_annual: float | None = None) -> dict[str, Any]:
    """Write the workbook from two DAILY return series on one date index. `start` is the base date: the session before
    the first return, where value is 100. Returns where each metric and table sits, for the Excel-equals-Python test."""
    df = pd.concat([strategy_returns.rename("s"), benchmark_returns.rename("b")], axis=1).dropna()
    if len(df) < 60:
        raise ValueError(f"need at least 60 daily returns on common dates, got {len(df)}")
    if not pd.Timestamp(start) < df.index[0]:
        raise ValueError("start must be before the first return date: it is the value-100 base date")
    hurdle_annual = config.hurdle_annual() if hurdle_annual is None else float(hurdle_annual)
    n, first, last = len(df), 3, len(df) + 2
    wb = Workbook()
    ws = wb.active
    ws.title = "Analytics"
    wd, wm, wy = wb.create_sheet("Daily"), wb.create_sheet("Monthly"), wb.create_sheet("Years")

    # ---- Daily: the only hardcoded numbers in the workbook are the two return columns and the dates
    header(wd, 1, ["Date", f"{strategy_name} return", f"{benchmark_name} return", "Value S", "Value B", "Peak S", "Peak B", "Drawdown S",
                   "Drawdown B", "Year peak S", "Year peak B", "Year drawdown S", "Year drawdown B", "Year", "Year-month", "Financial year",
                   "Return - risk-free S", "Return - risk-free B", "S - B"])
    put(wd, "A2", pd.Timestamp(start).to_pydatetime(), F_INPUT, DATE)
    for col in "DEFG":
        put(wd, f"{col}2", 100.0 if col in "DE" else f"={'D' if col == 'F' else 'E'}2", F_INPUT if col in "DE" else F_BASE, "0.0000")
    for k, (d, row) in enumerate(df.iterrows()):
        i = first + k
        put(wd, f"A{i}", d.to_pydatetime(), F_INPUT, DATE)
        put(wd, f"B{i}", float(row["s"]), F_INPUT, "0.000000")
        put(wd, f"C{i}", float(row["b"]), F_INPUT, "0.000000")
        for v, r, pk, dd, yp, yd in (("D", "B", "F", "H", "J", "L"), ("E", "C", "G", "I", "K", "M")):
            wd[f"{v}{i}"] = f"={v}{i - 1}*(1+{r}{i})"
            wd[f"{pk}{i}"] = f"=MAX({pk}{i - 1},{v}{i})"
            wd[f"{dd}{i}"] = f"=1-{v}{i}/{pk}{i}"
            # the year's peak starts at the prior year-end value (the base, in the first year)
            wd[f"{yp}{i}"] = f"=MAX({v}{i - 1},{v}{i})" if i == first else f"=IF(N{i}<>N{i - 1},MAX({v}{i - 1},{v}{i}),MAX({yp}{i - 1},{v}{i}))"
            wd[f"{yd}{i}"] = f"=1-{v}{i}/{yp}{i}"
        wd[f"N{i}"] = f"=YEAR(A{i})"
        wd[f"O{i}"] = f"=YEAR(A{i})*100+MONTH(A{i})"
        wd[f"P{i}"] = f"=YEAR(A{i})+IF(MONTH(A{i})>=4,1,0)"
        wd[f"Q{i}"] = f"=B{i}-Risk_Free_Daily"
        wd[f"R{i}"] = f"=C{i}-Risk_Free_Daily"
        wd[f"S{i}"] = f"=B{i}-C{i}"
    for nm, col in (("Dates", "A"), ("Ret_S", "B"), ("Ret_B", "C"), ("DD_S", "H"), ("DD_B", "I"), ("YDD_S", "L"), ("YDD_B", "M"),
                    ("Yr", "N"), ("YM", "O"), ("FY", "P"), ("Ex_S", "Q"), ("Ex_B", "R"), ("Diff", "S")):
        name(wb, nm, f"Daily!${col}${first}:${col}${last}")
    widths(wd, [12] + [14] * 18)

    # ---- Monthly and Years: the keys are labels read off the dates; every return is a formula over Daily
    yms = sorted({d.year * 100 + d.month for d in df.index})
    header(wm, 1, ["Year-month", f"{strategy_name} month return", f"{benchmark_name} month return"])
    for k, ym in enumerate(yms, start=2):
        put(wm, f"A{k}", ym, F_BASE, "0")
        for col, x in (("B", "S"), ("C", "B")):
            _cell(wm, f"{col}{k}", f"ARRAY:=PRODUCT(IF(YM=$A{k},1+Ret_{x},1))-1", PCT)
    name(wb, "Mon_S", f"Monthly!$B$2:$B${len(yms) + 1}")
    name(wb, "Mon_B", f"Monthly!$C$2:$C${len(yms) + 1}")
    widths(wm, [14, 24, 24])
    years = sorted(set(df.index.year))
    fys = sorted({d.year + (1 if d.month >= 4 else 0) for d in df.index})
    header(wy, 1, ["Calendar year", "Return S", "Return B", "Max drawdown S", "Max drawdown B", "", "Financial year (ends March)", "Return S", "Return B",
                   "", "Sharpe (arithmetic) S", "Sharpe (arithmetic) B", "Sortino (arithmetic) S", "Sortino (arithmetic) B"])
    for k, y in enumerate(years, start=2):
        put(wy, f"A{k}", y, F_BASE, "0")
        for col, x in (("B", "S"), ("C", "B")):
            _cell(wy, f"{col}{k}", f"ARRAY:=PRODUCT(IF(Yr=$A{k},1+Ret_{x},1))-1", PCT)
        for col, x in (("D", "S"), ("E", "B")):
            _cell(wy, f"{col}{k}", f"ARRAY:=MAX(IF(Yr=$A{k},YDD_{x}))", PCT)
        # per-calendar-year ratios are the ARITHMETIC form, over the daily risk-free rate
        for col, x in (("K", "S"), ("L", "B")):
            _cell(wy, f"{col}{k}", f"ARRAY:=(AVERAGE(IF(Yr=$A{k},Ret_{x}))-Risk_Free_Daily)/STDEV(IF(Yr=$A{k},Ret_{x}))*SQRT(252)", NUM)
        for col, x in (("M", "S"), ("N", "B")):
            _cell(wy, f"{col}{k}", f"ARRAY:=(AVERAGE(IF(Yr=$A{k},Ret_{x}))-Risk_Free_Daily)*252/"
                                   f"(SQRT(SUMPRODUCT((Yr=$A{k})*(Ex_{x}<0)*Ex_{x}^2)/COUNTIF(Yr,$A{k}))*SQRT(252))", NUM)
    for k, y in enumerate(fys, start=2):
        put(wy, f"G{k}", y, F_BASE, "0")
        for col, x in (("H", "S"), ("I", "B")):
            _cell(wy, f"{col}{k}", f"ARRAY:=PRODUCT(IF(FY=$G{k},1+Ret_{x},1))-1", PCT)
    name(wb, "YearDD_S", f"Years!$D$2:$D${len(years) + 1}")
    name(wb, "YearDD_B", f"Years!$E$2:$E${len(years) + 1}")
    widths(wy, [14, 12, 12, 16, 16, 4, 26, 12, 12, 4, 20, 20, 20, 20])

    # ---- Analytics
    put(ws, "A1", "Return analytics", F_TITLE)
    put(ws, "A2", f"Every metric is a formula over the Daily sheet and reproduces ros/metrics/core.py. {SIGNATURE}", F_NOTE)
    put(ws, "A3", "Risk-free rate for Sharpe and Sortino, a year (config/fund.yaml)", F_BOLD)
    put(ws, "B3", hurdle_annual, F_INPUT, PCT, FILL_KEY, border=True, comment="Key assumption: the risk-free rate in Sharpe and Sortino, one setting in config/fund.yaml.")
    put(ws, "C3", "=(1+Risk_Free_Rate)^(1/252)-1", F_BASE, "0.000000%", border=True)
    put(ws, "D3", "the risk-free rate for one day", F_NOTE)
    put(ws, "A4", "Base date (value 100)", F_BOLD)
    put(ws, "B4", "=Daily!A2", F_BASE, DATE, border=True)
    name(wb, "Risk_Free_Rate", "Analytics!$B$3")
    name(wb, "Risk_Free_Daily", "Analytics!$C$3")
    name(wb, "Start_Date", "Analytics!$B$4")
    header(ws, 6, ["Metric", strategy_name, benchmark_name, "Definition (the same as ros/metrics/core.py)"])
    rows = {lab: 7 + k for k, lab in enumerate(METRIC_LABELS)}
    for lab, f, fmt, note in _BOTH:
        for c, x in (("B", "S"), ("C", "B")):
            _cell(ws, f"{c}{rows[lab]}", f.format(x=x, c=c, r=rows), fmt)
        put(ws, f"A{rows[lab]}", lab, F_BASE, border=True)
        put(ws, f"D{rows[lab]}", note, F_NOTE)
    for lab, f, fmt, note in _RELATIVE:
        _cell(ws, f"B{rows[lab]}", f.format(r=rows), fmt)
        put(ws, f"A{rows[lab]}", lab, F_BASE, border=True)
        put(ws, f"D{rows[lab]}", note, F_NOTE)
    widths(ws, [38, 16, 16, 96])
    apply_house_style(wb)
    wb.save(path)
    return {"sheet": "Analytics", "rows": rows, "strategy_col": "B", "benchmark_col": "C", "n_days": n,
            "months": {"sheet": "Monthly", "keys": yms, "first_row": 2}, "years": {"sheet": "Years", "calendar": years, "financial": fys, "first_row": 2}}


def python_values(strategy_returns: pd.Series, benchmark_returns: pd.Series, start, hurdle_annual: float | None = None) -> dict[str, Any]:
    """The same numbers from ros/metrics/core.py: what every cell of the workbook must equal."""
    df = pd.concat([strategy_returns.rename("s"), benchmark_returns.rename("b")], axis=1).dropna()
    h = config.hurdle_annual() if hurdle_annual is None else float(hurdle_annual)
    s, b = df["s"], df["b"]
    return {"strategy": core.tearsheet(s, start, h, b), "benchmark": core.tearsheet(b, start, h),
            "monthly": {"strategy": core.monthly_returns(s), "benchmark": core.monthly_returns(b)},
            "calendar_year": {"strategy": core.calendar_year_returns(s), "benchmark": core.calendar_year_returns(b)},
            "financial_year": {"strategy": core.financial_year_returns(s), "benchmark": core.financial_year_returns(b)},
            "year_max_drawdown": {"strategy": core.calendar_year_max_drawdown(s), "benchmark": core.calendar_year_max_drawdown(b)},
            "year_sharpe": {"strategy": core.calendar_year_sharpe(s, core.daily_cash(h)), "benchmark": core.calendar_year_sharpe(b, core.daily_cash(h))},
            "year_sortino": {"strategy": core.calendar_year_sortino(s, core.daily_cash(h)), "benchmark": core.calendar_year_sortino(b, core.daily_cash(h))}}
