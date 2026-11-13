# Quant AI Researcher
"""Build docs/lightyear-results-gate-b-metrics-v3.pdf: "Financial metrics: what is on the dashboard and in the workbook".

Every metric the Lightyear dashboard shows and the workbook holds, in the order it appears on the page, and each section
says where to find it: the dashboard card and the workbook sheet. No run results and no examples.

Every formula carries the function or cell it was checked against (the last item of each row, and CHECKS for the boxed
formulas). `--checks` prints that list instead of building.

    python scripts/build_metrics_pdf.py            # writes the .html and prints the .pdf path
    python scripts/build_metrics_pdf.py --checks   # every formula beside what it was checked against
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros import config
from ros.metrics import se
from ros.validation.gate_evidence import INVESTABLE_FACTORS
from ros.versions import GATE_VERSION

OUT = os.path.join(REPO, "docs", "lightyear-results-gate-b-metrics-v3")
SIG = "Quant AI Researcher"
RUNNING = "Lightyear: financial metrics"
TH = config.gate_thresholds()
RFA = config.hurdle_annual()
RF = f"{RFA:.0%}"
CHECKS: list[tuple[str, str, str]] = []      # (where in the PDF, formula in words, checked against)


def pc(x, d=0):
    return f"{x * 100:.{d}f}%"


def table(sec, head, rows, widths):
    """rows: (metric, formula, how to read it, checked against). The last item goes to CHECKS, not to the page."""
    cols = "".join(f'<col style="width:{w}%">' for w in widths)
    body = ""
    for r in rows:
        *cells, src = r
        if src:
            CHECKS.append((sec, f"{strip(cells[0])}: {strip(cells[1])}", src))
        body += "<tr>" + "".join(f"<td>{c}</td>" if i else f"<td><b>{c}</b></td>" for i, c in enumerate(cells)) + "</tr>"
    return f"<table><colgroup>{cols}</colgroup><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + f"</tr></thead><tbody>{body}</tbody></table>"


def strip(t):
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t)).replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&").strip()


SE_READ = {
    "Total Return": "What 1 became over the whole window.", "CAGR": "Twelve months count as a year, whatever the calendar days.",
    "Avg Month Ret": "A typical month.", "Positive Months": "", "Negative Months": "A flat month counts as negative.",
    "Max Month Ret": "", "Min Month Ret": "", "Best Month Contri": "How much of the whole gain one month is worth.", "Worst Month Contri": "",
    "Annualized Volatility": "Lower is smoother. Population stdev, on months.",
    "Positive Monthly Vol": "Bumpiness of the winning months. Not annualised.", "Negative Monthly Vol": "Bumpiness of the losing months. Not annualised.",
    "Max Drawdown": "A negative number. <b>The peak starts at the first month's own value, so a loss in the first month is not counted.</b>",
    "Average Annual Max Drawdown": "A typical year's worst fall. The same first-month rule applies inside each year, and part-years are included.",
    "Sharpe Ratio": "Return above the risk-free rate per unit of risk.", "Treynor Ratio": "Return above the risk-free rate per unit of market risk.",
    "Sortino Ratio": "<b>Differs from the textbook:</b> the divisor is the spread of the losing months, not a downside deviation below a target.",
    "Calmar Ratio": "Return per unit of worst fall.",
    "Sterling Ratio": "<b>Differs from the textbook:</b> the usual 10-point adjustment is replaced by the drawdown limit, which is 0.",
    "Omega Ratio": "Above 1 means gains over the threshold outweigh shortfalls.", "Gain to Pain ratio": "Winning months against losing months.",
    "Tail Ratio": "Above 1 means big wins are larger than big losses.", "Beta": "1.0 moves in line with the index.", "Alpha": "Points a year ahead of the index.",
    "Jensens Alpha (Adj Beta)": "<b>Differs from its label:</b> no risk-free rate and no adjusted beta are used.",
    "Positive Monthly Alpha": "Months ahead of the index.", "Negative Monthly Alpha": "Months behind it.", "Tracking Error": "How far it strays from the index.",
    "Information Ratio": "The CAGR gap, not the mean monthly gap, over tracking error.", "Hit Rate": "Share of months ahead; ties are left out.",
    "Max Monthly Alpha": "", "Min Monthly Alpha": "", "Ret +Ve": "What it earned in the index's up months.", "Ret -Ve": "What it lost in the index's down months.",
    "Upside Capture": "Above 1 rises more than the index.", "Downside Capture": "Below 1 falls less than the index.", "Capture Ratio": "Above 1 gains more than it gives back.",
    "Ex. Ret +Ve": "The index's strongest months.", "Ex. Ret -Ve": "The index's worst months.", "Ex. Upside Capture": "", "Ex. Downside Capture": "",
    "Extreme Capture Ratio": "Whether it holds up when the market moves hardest.", "Skewness": "Negative means big falls are more common than big rises.",
    "Kurtosis": "A bell curve scores 0. Positive means fat tails.", "95% VaR": "A negative return, not a positive loss.", "99% VaR": "A negative return.",
    "95% CVaR": "The average month once you are in that tail.", "99% CVaR": "",
}
SE_FORMULA = {
    "Total Return": "∏(1 + m) − 1", "CAGR": "(1 + Total Return)<sup>12 ÷ months</sup> − 1", "Avg Month Ret": "mean(m)",
    "Positive Months": "count of months with m &gt; 0", "Negative Months": "count of months with m ≤ 0", "Max Month Ret": "max(m)", "Min Month Ret": "min(m)",
    "Best Month Contri": "Max Month Ret ÷ Total Return", "Worst Month Contri": "Min Month Ret ÷ Total Return",
    "Annualized Volatility": "pop stdev(m) × √12", "Positive Monthly Vol": "pop stdev of the months with m ≥ 0", "Negative Monthly Vol": "pop stdev of the months with m ≤ 0",
    "Max Drawdown": "min over months of (W ÷ highest W so far − 1), where W = running ∏(1 + m)", "Average Annual Max Drawdown": "mean of the Max Calendar Year Drawdown rows",
    "Sharpe Ratio": "(CAGR − Rf) ÷ Annualized Volatility", "Treynor Ratio": "(CAGR − Rf) ÷ Beta", "Sortino Ratio": "(CAGR − Rf) ÷ (Negative Monthly Vol × √12)",
    "Calmar Ratio": "CAGR ÷ |Max Drawdown|", "Sterling Ratio": "CAGR ÷ (|Average Annual Max Drawdown| − drawdown limit)",
    "Omega Ratio": "Σ(m − T) over months with m &gt; T ÷ |Σ(m − T) over months with m &lt; T|, T the monthly threshold",
    "Gain to Pain ratio": "Σ of months with m ≥ 0 ÷ |Σ of months with m &lt; 0|", "Tail Ratio": "|95th percentile of m| ÷ |5th percentile of m|",
    "Beta": "slope of m on the benchmark's monthly returns", "Alpha": "CAGR − CAGR<sub>benchmark</sub>", "Jensens Alpha (Adj Beta)": "CAGR − CAGR<sub>benchmark</sub> × Beta",
    "Positive Monthly Alpha": "count of months with m &gt; b", "Negative Monthly Alpha": "count of months with m &lt; b", "Tracking Error": "pop stdev(m − b) × √12",
    "Information Ratio": "Alpha ÷ Tracking Error", "Hit Rate": "Positive Monthly Alpha ÷ (Positive + Negative Monthly Alpha)",
    "Max Monthly Alpha": "max(m − b)", "Min Monthly Alpha": "min(m − b)", "Ret +Ve": "mean(m) in months with b ≥ 0", "Ret -Ve": "mean(m) in months with b &lt; 0",
    "Upside Capture": "Ret +Ve ÷ the benchmark's Ret +Ve", "Downside Capture": "Ret −Ve ÷ the benchmark's Ret −Ve", "Capture Ratio": "Upside Capture ÷ Downside Capture",
    "Ex. Ret +Ve": "mean(m) in months with b ≥ 5%", "Ex. Ret -Ve": "mean(m) in months with b &lt; −5%", "Ex. Upside Capture": "Ex. Ret +Ve ÷ the benchmark's",
    "Ex. Downside Capture": "Ex. Ret −Ve ÷ the benchmark's", "Extreme Capture Ratio": "Ex. Upside Capture ÷ Ex. Downside Capture",
    "Skewness": "sample skew of m", "Kurtosis": "sample excess kurtosis of m", "95% VaR": "5th percentile of m", "99% VaR": "1st percentile of m",
    "95% CVaR": "mean of the months with m ≤ 95% VaR", "99% CVaR": "mean of the months with m ≤ 99% VaR",
}
assert set(SE_FORMULA) == set(SE_READ) == {lab for _s, lab, *_ in se.SPEC}, "every SE metric, and nothing else"


def where(dash, excel):
    """The one line under each heading that says where the section is."""
    return f'<p class="where"><b>Dashboard:</b> {dash}<br><b>Excel:</b> {excel}</p>'


def content():
    sp, fa, pp, bt, di = TH["sub_period"], TH["factor_alpha"], TH["post_publication"], TH["bootstrap"], TH["data_integrity"]
    om, dl = se.DEFAULT_INPUTS["omega_threshold"], se.DEFAULT_INPUTS["drawdown_limit"]
    W3 = [24, 41, 35]
    H3 = ["Metric", "Formula", "How to read it"]
    h = []
    A = h.append
    core, ch, scr = "ros/metrics/core.py", "lightyear/charts.py", "the run's backtest script (its fixed validation rows)"
    res, pf, ge = "ros/validation/research.py", "ros/validation/portfolio.py", "ros/validation/gate_evidence.py"
    val = 'diagnostics workbook, sheet "Validation", pasted values (blue), in the same order.'

    # ------------------------------------------------------------ page 1
    A('<h1 class="title">Financial metrics</h1><p class="sub">Every metric on the Lightyear dashboard and in the Excel workbook: where it is, the formula, and how to read it.</p>')
    A('<div class="note"><p><b>How this is arranged.</b> The sections follow the dashboard from top to bottom, one section per card, with the card\'s own name. Under each '
      'heading two lines say where to find it: the dashboard card, and the workbook sheet. <b>Part 1</b> is the main display, on monthly returns. <b>Part 2</b> is the daily '
      'calculations and the run diagnostics, both collapsed on the page. <b>Part 3</b> is the Gate B tab.</p><p>In the workbook, a <b>formula</b> means Excel calculates the figure itself; a <b>pasted value</b> means Python calculated it and the '
      'workbook only shows it. There are no run results or examples here.</p></div>')
    A('<p class="ft"><b>Notation used in every formula</b></p>' + table("Notation", ["Symbol", "Meaning"], [
        ("r, b", "One day's return on the strategy and on the benchmark, the NIFTY 500 price index.", ""),
        ("m", "One calendar month's return, compounded from the daily returns. Used throughout Part 1.", ""),
        (f"Rf ({RF})", "The risk-free rate in every Sharpe and Sortino. One config setting. A yardstick, not income.", ""),
        ("c", "The card's cash rate: what idle cash earns in the backtest. Beta and the factor regression subtract it. Not the risk-free rate.", ""),
        ("V<sub>t</sub>", "Portfolio value on day t.", ""),
        ("mean, stdev", "Average and sample standard deviation (divides by n − 1). <b>Pop stdev</b> divides by n; Part 1 uses it.", ""),
        ("√252, √12", "Annualise daily and monthly volatility. 252 is the assumed trading days a year.", ""),
        ("years", "Calendar days ÷ 365.25. In Part 1, months ÷ 12.", "")], [16, 84]))
    A("<h2 class='c'>Contents</h2>%%TOC%%")

    # ------------------------------------------------------------ Part 1
    qi_, mw = "ros/metrics/qi.py", "lightyear/main_workbook.py"
    rowof, r_, prev = {}, 5, None
    for s_, lab, *_ in se.SPEC:
        if prev is not None and s_ != prev:
            r_ += 1
        rowof[lab] = r_
        prev = s_
        r_ += 1

    def se_rows(labels, rename=None):
        return [((rename or {}).get(lab, lab), SE_FORMULA[lab], SE_READ[lab], f"ros/metrics/se.py compute() [{lab}]; workbook 'SE Return Analytics'!K{rowof[lab]}") for lab in labels]

    A('<h1 class="brk" id="p1">Part 1. The main display (monthly)</h1>')
    A(f'<div class="warn"><p><b>Everything in Part 1 is on monthly returns.</b> Calendar-month returns m, the population standard deviation, CAGR by month count, and three '
      f'inputs: risk-free rate {RF}, Omega threshold {pc(om)} a month, drawdown limit {pc(dl)}. <b>Complete calendar months only:</b> a month counts when the run has a return '
      "for every trading session in it; the first month also counts when the only session without a return is its first, the run's starting point. Days outside complete "
      'months are left out and listed in the notes at the foot of the page. Python and Excel calculate each figure separately, and the sheet "Python vs Excel" marks each OK or FAIL at 1e-9. '
      "The benchmark is the NIFTY 500 price index until a total-return series is on file.</p></div>")
    A('<h2 id="1.1">1.1 Strategy vs benchmark: the five tiles</h2>' + where('Results tab, card "Strategy vs benchmark (monthly)".', 'main workbook, sheet "Returns overview", rows 6 to 10, links to "SE Return Analytics".'))
    A("<p>The tiles are CAGR and Total Return (formulas in 1.5) and Annualized Volatility, Sharpe Ratio and Max Drawdown (formulas in 1.9), for the strategy with the benchmark "
      "under each. The notes at the foot of the page give the first and last complete month and the daily returns left out.</p>")
    CHECKS.append(("1.1", "Complete months: first and last complete calendar months, and the daily returns outside them", "ros/metrics/se.py complete_months(), block()"))
    A('<h2 id="1.2">1.2 Financial-year returns</h2>' + where('Results tab, card "Financial-year returns".', 'main workbook, sheet "Returns overview", second table.'))
    A(table("1.2", H3, [
        ("Financial Year Performance", "∏(1 + m) from April to March − 1", "* marks the first year, ** a last part-year. A part year is not annualised.", "ros/metrics/se.py periods(), compute() tables; workbook 'SE Return Analytics' rows under the analytics"),
        ("Alpha, each year", "Strategy's year − benchmark's year", "Points ahead of the index in that year.", f"{qi_} block() financial_year; workbook 'Returns overview' column D"),
        ("Annualised alpha", "CAGR − CAGR<sub>benchmark</sub>", "The Alpha row of 1.11, shown under the table.", f"{qi_} block() annualised_alpha; ros/metrics/se.py compute() [Alpha]")], W3))
    A('<h2 id="1.3">1.3 Strategy against index NAV</h2>' + where('Results tab, card "Strategy against index NAV (100 at start)".', 'main workbook, chart on "Returns overview"; values on "Monthly series", columns E and F, formulas.'))
    A(table("1.3", ["Chart", "Calculation", "How to read it"], [("NAV, 100 at start", "100 × running ∏(1 + m), month-end values", "Above the benchmark's line means ahead of it at that month-end.", f"{qi_} block() nav")], W3))
    A('<h2 id="1.4">1.4 Trailing returns</h2>' + where('Results tab, card "Trailing returns".', 'main workbook, sheet "Returns overview", third table, formulas over "Monthly series".'))
    A(table("1.4", H3, [
        ("1M, 3M, 6M, 1Y", "∏(1 + m) over the last 1, 3, 6 or 12 months − 1", "Not annualised.", f"{qi_} trailing(), period_return()"),
        ("3Y, 5Y, 10Y, since inception", "(∏(1 + m) over the last k months)<sup>12 ÷ k</sup> − 1", "Annualised. A period longer than the run shows n/a.", f"{qi_} trailing(), period_return()"),
        ("Alpha", "Strategy's figure − benchmark's", "", f"{qi_} trailing()")], W3))
    A('<h2 id="1.5">1.5 Key return metrics</h2>' + where('Results tab, card "Key return metrics".', 'main workbook, sheet "Returns overview", fourth table, links to "SE Return Analytics" column K.'))
    A(table("1.5", H3, se_rows(["Total Return", "CAGR", "Avg Month Ret", "Positive Months", "Negative Months", "Positive Monthly Alpha", "Hit Rate", "Max Month Ret", "Min Month Ret", "Best Month Contri", "Worst Month Contri"],
                               {"Positive Monthly Alpha": "Positive Alpha Months", "Max Month Ret": "Best Month Ret", "Min Month Ret": "Worst Month Ret",
                                "Best Month Contri": "Best Month Contribution", "Worst Month Contri": "Worst Month Contribution"}), W3))
    A('<h2 id="1.6">1.6 Market phases</h2>' + where('Results tab, card "Market phases": the shaded chart, then the table.', 'main workbook, sheet "Market phases", formulas over "Monthly series".'))
    A(table("1.6", H3, [
        ("Phase", "Whole calendar months from the phase table in config/market_phases.yaml; the first phase is clipped to the run", "A phase with no end month is still running.", f"{qi_} phases(); ros/config.py market_phases()"),
        ("Absolute return", "∏(1 + m) over the phase's months − 1", "The strategy's figure. The chart is the strategy's NAV, and labels each phase with its name, its dates and this figure.", f"{qi_} phases()"),
        ("Annualised return", "(1 + absolute return)<sup>12 ÷ months</sup> − 1", "<b>Annualised whatever the length</b>, so a two-month phase is scaled up sixfold in the exponent.", f"{qi_} phases()"),
        ("Length (months)", "Count of the run's months in the phase", "", f"{qi_} phases()")], W3))
    A('<h2 id="1.7">1.7 Rolling returns</h2>' + where('Results tab, card "Rolling returns": two charts, then the numbers.', 'main workbook, sheet "Rolling returns"; the series are on "Monthly series", columns M to X, formulas.'))
    A(table("1.7", H3, [
        ("Rolling 1-year return", "∏(1 + m) over the 12 months ending at each month − 1", "", f"{qi_} rolling()"),
        ("Rolling 3-year return", "(∏(1 + m) over the 36 months ending at each month)<sup>1 ÷ 3</sup> − 1", "Annualised.", f"{qi_} rolling()"),
        ("Rolling alpha", "Strategy's rolling return − benchmark's", "", f"{qi_} rolling()"),
        ("Rolling Sharpe", "(rolling return − Rf) ÷ (pop stdev of the window's months × √12)", "", f"{qi_} rolling()"),
        ("Excess Sharpe", "Strategy's rolling Sharpe − benchmark's", "<b>An assumed definition</b>, labelled as such on the page.", f"{qi_} rolling()"),
        ("Share of observations with positive alpha", "Count of windows with alpha &gt; 0 ÷ count of windows", "", f"{qi_} rolling()"),
        ("Average, minimum, maximum rolling return", "mean, min and max of the rolling returns, strategy and benchmark", "", f"{qi_} rolling()")], W3))
    A('<h2 id="1.8">1.8 Returns attribution to factor indices</h2>' + where('Results tab, card "Returns attribution to factor indices": three tables, then the rolling chart.',
      'main workbook, sheet "Factor attribution", LINEST formulas; the indices\' monthly returns are on "Monthly series", columns I to L (pasted), rolling coefficients in Y to AB.'))
    A('<div class="warn"><p><b>No alpha term.</b> The regression has no intercept, so it only splits the return across the indices. Gate B\'s factor test (3.2) is a separate '
      "regression: daily returns, seven factors, with an intercept.</p></div>")
    A(table("1.8", H3, [
        ("Coefficients", "Least squares of m on the three indices' monthly returns, through the origin", "The indices: NIFTY500 Quality 50, NIFTY500 Momentum 50 and NIFTY Smallcap 250, price indices. Value 50 is left out: its coefficient is not different from zero beside the other three.", f"{qi_} factor_attribution(), _ols0(), FACTOR_INDICES; lightyear/charts.py factor_monthly()"),
        ("R Square; Multiple R", "Σ fitted² ÷ Σ m²; its square root", "The uncentred R Square a no-intercept regression reports.", f"{qi_} factor_attribution()"),
        ("Adjusted R Square", "1 − (1 − R Square) × n ÷ (n − k)", "n is the number of months, k the number of indices (3).", f"{qi_} factor_attribution()"),
        ("Standard Error", "√(Σ residual² ÷ (n − k))", "", f"{qi_} factor_attribution()"),
        ("ANOVA: SS, MS, F, Significance F", "Regression SS = Σ fitted², residual SS = Σ residual², MS = SS ÷ df, F = MS<sub>regression</sub> ÷ MS<sub>residual</sub>, with k and n − k degrees of freedom", "", f"{qi_} factor_attribution()"),
        ("Standard error, t stat, P-value, 95% range", "se from the residual variance; t = coefficient ÷ se; two-sided p from Student's t with n − k degrees of freedom; coefficient ± t<sub>0.975</sub> × se", "", f"{qi_} factor_attribution()"),
        ("One-year rolling attribution", "The same coefficients on each 12-month window", "Twelve months in each window, so they move a great deal.", f"{qi_} factor_attribution() rolling, FACTOR_WINDOW")], W3))
    A('<h2 id="1.9">1.9 Drawdown and advanced risk ratios</h2>' + where('Results tab, card "Drawdown and advanced risk ratios": the chart, then the table.',
      'main workbook, sheet "Drawdown and risk", links to "SE Return Analytics"; the drawdown series is on "Monthly series", columns G and H.'))
    A(table("1.9", H3, [("Monthly drawdown <i>(chart)</i>", "W ÷ highest W so far − 1 at each month-end, W = running ∏(1 + m)", "0% is a new month-end high.", f"{qi_} drawdown_series()")]
            + se_rows(["Annualized Volatility", "Negative Monthly Vol"])
            + [("Downside Deviation", "Negative Monthly Vol × √12", "The annualised figure. The reference deck prints this one under the name Negative Monthly Vol.", f"{qi_} block() risk, RISK")]
            + [("Largest Monthly Loss", "Worst Month Ret of 1.5", "", "ros/metrics/qi.py RISK")]
            + se_rows(["Max Drawdown", "Average Annual Max Drawdown", "Sharpe Ratio", "Treynor Ratio", "Sortino Ratio", "Calmar Ratio", "Sterling Ratio", "Omega Ratio", "Gain to Pain ratio", "Tail Ratio"])
            + se_rows(["Positive Monthly Vol"], {"Positive Monthly Vol": "Positive Monthly Vol <i>(workbook only)</i>"}), W3))
    A('<h2 id="1.10">1.10 Tail risk</h2>' + where('Results tab, card "Tail risk": the table, then three charts of monthly returns with the VaR and CVaR lines.',
      'main workbook, sheet "Tail risk": strategy and benchmark link to "SE Return Analytics"; the alpha column is formulas over "Monthly series" column D.'))
    A("<p>Three columns: the strategy, the benchmark, and the monthly alpha m − b. Each row is the same formula on that column's months.</p>")
    A(table("1.10", H3, [("Distribution chart", "Count of months in each 2-point band of monthly return, strategy and benchmark", "The left end is the tail; lines mark the strategy's VaR and CVaR.", f"{qi_} histogram()"),
                         ("Mean", "mean of the months", "", f"{qi_} tail()"), ("Volatility (monthly)", "pop stdev of the months", "Not annualised.", f"{qi_} tail()")]
            + se_rows(["Skewness", "Kurtosis", "95% VaR", "99% VaR", "95% CVaR", "99% CVaR"]), W3))
    A('<h2 id="1.11">1.11 Performance versus index and capture</h2>' + where('Results tab, card "Performance versus index and capture": three tables, then the quarterly table.',
      'main workbook, sheet "Index and capture", links to "SE Return Analytics"; quarterly returns are in its columns F and G.'))
    for sec_name in ("Performance Vs Index", "Capture Ratio", "Extreme Capture Ratio"):
        A(f'<h3>{sec_name}</h3>' + table("1.11", H3, se_rows([lab for s_, lab, *_ in se.SPEC if s_ == sec_name]), W3))
    A('<h3>Average quarterly performance</h3>' + table("1.11", H3, [
        ("Quarterly return", "∏(1 + m) over the calendar quarter − 1", "Complete quarters only; a part quarter is left out and named.", "ros/metrics/se.py periods(), compute() tables; workbook 'SE Return Analytics' columns F, G"),
        ("Average return in rising / falling quarters", "mean of the quarterly returns in quarters with the benchmark's return ≥ 0 / &lt; 0", "", f"{qi_} quarterly_capture()"),
        ("Upside / downside capture", "Strategy's average ÷ benchmark's average, in rising / falling quarters", "Above 1 up and below 1 down is the good shape.", f"{qi_} quarterly_capture()"),
        ("Capture ratio", "Upside capture ÷ downside capture", "", f"{qi_} quarterly_capture()")], W3))
    A('<h2 id="1.12">1.12 Calendar-year tables</h2>' + where('Results tab, card "Calendar-year performance and max calendar-year drawdown".', 'main workbook, sheet "Calendar years", links to "SE Return Analytics".'))
    A(table("1.12", H3, [
        ("Calendar Year Performance", "∏(1 + m) from January to December − 1", "* marks the first year, ** a last part-year.", "ros/metrics/se.py periods(), compute() tables"),
        ("Max Calendar Year Drawdown", "The Max Drawdown formula on that year's months alone", "<b>A loss in the year's first month is not counted</b>, because the peak starts at that month's own value.",
         "ros/metrics/se.py _dd(), compute() tables; workbook LET / SCAN / LAMBDA cells")], W3))
    A('<h2 id="1.13">1.13 Market-cap and sector allocation</h2>' + where('Results tab, card "Market-cap and sector allocation and returns, by financial year".',
      'main workbook, sheet "Allocation": yearly tables are formulas over the per-rebalance figures to their right, which are pasted.'))
    A(table("1.13", H3, [
        ("Bucket", "Large = Nifty 100, mid = Midcap 150, small = Smallcap 250, from the latest quarterly NIFTY 500 list on or before the rebalance. Sector = Ace's present-day sector, grouped by config/sector_groups.yaml",
         "Sectors are not dated: each company is under its present sector for every year.", "lightyear/allocation.py build(); config/sector_groups.yaml"),
        ("Allocation", "Average, over the year's rebalances, of the bucket's weight", "Cash is 1 − the sum of the buckets.", "lightyear/allocation.py build()"),
        ("Market-cap return", "Holdings' returns from one execution date to the next, weighted by their weights, compounded over the year", "A bucket holding one small position takes that stock's return.", "lightyear/allocation.py build()"),
        ("Sector return", "Plain average of the sector's holdings' returns per holding period, compounded over the year", "", "lightyear/allocation.py build()")], W3))

    # ------------------------------------------------------------ Part 2
    A('<h1 class="brk" id="p2">Part 2. Daily calculations and run diagnostics</h1>')
    A("<p>Both sections are collapsed on the Results tab, under the main display. The first six daily figures follow the Barra site's formulas (daily returns added, not compounded; sample standard deviation; 250 days a year; no risk-free rate), "
      "so a book here and the same book on the site differ only by their data. The rows after them are Lightyear's own, on 252 days. All differ from the monthly figures of the same name in Part 1. Gate B reads the run diagnostics and its own daily tests.</p>")
    A('<h2 id="2.1">2.1 Daily calculations</h2>' + where('Results tab, section "Daily calculations": one row per metric, with its daily formula, the daily value and the monthly figure beside it.',
      'main workbook, sheet "Daily calculations", formulas over the "Returns" sheet, checked on "Python vs Excel". The "Summary" sheet of the diagnostics workbook repeats the first rows.'))
    A(table("2.1", H3, [
        ("Annualised return", "mean(r) × 250", "The average day's return, scaled to a year by adding. Not a compounded rate.", f"{core} site_annual_return(); config/fund.yaml site_days_per_year; workbook 'Daily calculations'"),
        ("Volatility", "stdev(r) × √250", "How much returns swing in a year. Lower is a smoother ride.", f"{core} site_vol(); workbook 'Daily calculations'"),
        ("Sharpe (no risk-free rate)", "Annualised return ÷ Volatility", "Return per unit of risk, with nothing taken off for the risk-free rate.", f"{core} site_sharpe(); workbook 'Daily calculations'"),
        ("Sortino (no risk-free rate)", "Annualised return ÷ (stdev of the days with r &lt; 0 × √250)", "Like the Sharpe, but only the days with a loss count as risk.", f"{core} site_sortino(); workbook 'Daily calculations'"),
        ("Maximum drawdown", "max over t of (highest S so far − S<sub>t</sub>), S = running sum of r", "The biggest fall of the summed returns from a high to a later low, in points of return, as a positive number.", f"{core} site_max_drawdown(); workbook 'Daily calculations'"),
        ("Days with a gain", "count(r &gt; 0) ÷ count(r)", "The share of days the book made money.", f"{core} hit_rate(); workbook 'Daily calculations'"),
        ("Final value", "100 × ∏(1 + r)", "What 100 grew into after every daily return.", f"{core} value_from_returns(); workbook 'Daily calculations'"),
        ("Drawdown duration", "Longest run of trading days below a previous high", "How long the longest wait to recover took.", f"{core} drawdown_duration(); workbook 'Daily calculations'"),
        ("95% CVaR (daily loss)", "−mean of the daily returns at or below their 5th percentile", "The average bad day, as a positive number.", f"{core} cvar(), cvar_95(); workbook 'Daily calculations'"),
        ("Skew", "Sample skew of daily returns", "Negative means big falls are more common than big rises.", f"{core} skew(); workbook 'Daily calculations'"),
        ("CAGR without the 10 best days", "Remove the 10 best days, then compound; years run from the first return date", "Whether a handful of days made the result.",
         f"{core} cagr_without_best_days(); workbook 'Daily calculations'"),
        ("Beta", "Cov(r − c, b − c) ÷ Var(b − c)", "1.0 moves in line with the index. Below 1 is less sensitive.", f"{core} beta(); workbook 'Daily calculations'"),
        ("Tracking error", "stdev(r − b) × √252", "How far it strays from the index.", f"{core} tracking_error(); workbook 'Daily calculations'"),
        ("Information ratio", "mean(r − b) × 252 ÷ tracking error", "Return over the index per unit of straying. Higher is better.", f"{core} information_ratio(); workbook 'Daily calculations'"),
        ("Rolling one-year periods behind", "Share of 252-day windows with compounded return below the index's", "How often an investor would have been trailing.",
         f"{core} rolling_periods_behind(); workbook 'Daily calculations'"),
        ("Two-way turnover a year <i>(Run facts card)</i>", "Σ |weight after − weight before| over every trade, ÷ years", "1.0 means trading the whole portfolio's value once a year.",
         f"{core} two_way_turnover_from_trades(), annual_turnover()"),
        ("After publication <i>(Run facts card)</i>", "CAGR, benchmark CAGR, their gap (edge), arithmetic Sharpe and maximum drawdown, on the days from the paper's publication date",
         "Whether the result held once the idea was public. A date given only as a year is read as 31 December.", f"{core} post_publication(), publication_cutoff()"),
        ("Capacity per Rs 1 crore <i>(Run facts card; dashboard only)</i>", f"For each trade: (its share of capital × Rs 1 crore) ÷ the stock's 20-day average traded value. The 95th percentile P is shown, and the capital at which it reaches the limit: {pc(TH['capacity']['p95_adv_participation_max'])} ÷ P",
         "Information only. No fund size is assumed, and the limit is a placeholder.", f"{core} capacity_unit(), adv_20(); config/gate_thresholds.yaml capacity"),
        ("Sharpe by calendar year, arithmetic <i>(Run facts card; dashboard only)</i>", "mean(r − Rf per day) ÷ stdev(r − Rf per day) × √252, on that year's days",
         "The yearly form of the Sharpe. It is labelled arithmetic wherever it appears.", f"{core} sharpe(), calendar_year_sharpe()")], W3))

    A('<h3>Beta in different markets (card "Run facts (daily)"; dashboard only)</h3>' + table("2.1", H3, [
        ("Up-market / down-market beta", "Beta using only days the index rose / fell", "Ideally high in rises and low in falls. The two do not average to the overall beta.",
         f"{core} beta_on(); {ch} build(), beta_split"),
        ("Index filter open / shut", "Beta using only days the card's index filter was open / shut. The filter's state on a day is read at the previous session's close",
         "Shown when the card has an index filter. A low beta when shut is the filter holding cash.", f"{ch} _filter_betas()")], W3))

    A('<h2 id="2.2">2.2 The daily charts</h2>' + where('Results tab, section "Run diagnostics", one card per chart (daily).',
      'diagnostics workbook, sheet "Returns": value in columns D and E, drawdown in F and G, formulas. Sheets "Calendar-year returns" and "Monthly returns".'))
    A(table("2.2", ["Chart", "Calculation", "How to read it"], [
        ("Growth of 100", "100 × running product of (1 + r)", "Above the benchmark's line means ahead of it on that day.", f"{ch} value_path()"),
        ("Drawdown", "V<sub>t</sub> ÷ highest V so far − 1", "0% is a new high. Deeper dips are bigger losses.", f"{ch} build()"),
        ("Rolling 3-month volatility", "stdev of the last 63 daily returns × √252", "How bumpy the last three months were. Dashboard only.", f"{core} rolling_vol(), window 63"),
        ("Calendar-year return", "Product of (1 + r) within the year − 1", "First and last years may be part-years.", f"{ch} build(), calendar"),
        ("Strategy monthly returns", "Product of (1 + r) within the month − 1", "Green months gained, red months lost.", f"{ch} build(), monthly")], W3))

    A('<h2 id="2.3">2.3 Appendix: the simpler alternatives</h2>' + where('Results tab, section "Run diagnostics", card "Appendix: the simpler alternatives it had to beat".',
      'diagnostics workbook, sheet "Comparators": daily returns from column H, the metrics table is formulas. Sheet "Performance" holds the same figures as pasted values.'))
    A("<p>For each alternative (for example the equal-weight basket) the card shows CAGR, volatility, Sharpe and worst fall. They are the formulas in 2.1 on that "
      "alternative's daily returns over the same days.</p>")

    A('<p>Sections 2.4 to 2.8 are the five cards of rows written by each run\'s own script. <b>Rows tied to a strategy\'s rules appear only for that strategy</b>, so another '
      "run can show a different list.</p>")
    A('<h2 id="2.4">2.4 Returns &amp; risk</h2>' + where('Results tab, section "Run diagnostics", card "Returns &amp; risk".', val) + table("2.4", H3, [
        ("CAGR, volatility, Sharpe, max drawdown: strategy, index, alternatives", "The formulas in 2.1", "The same headline figures, listed for each series.", f"{core} tearsheet()"),
        ("Edge over the index", "CAGR<sub>strategy</sub> − CAGR<sub>benchmark</sub>", "Points a year ahead of the index.", f"{core} edge()"),
        ("Drawdown in the latest index correction", "Each series' fall over the index's latest fall deeper than 10%", "How it behaved in the most recent real test.", scr),
        ("Beta; information ratio", "As in 2.1", "", ""),
        ("Calendar-year return, a named year", "Product of (1 + r) within that year − 1", "A year the run's notes single out.", scr),
        ("Deflated Sharpe, at V = 1 and at V from the variants", "P(skill) = Φ[(SR − SR<sub>0</sub>) × √(n − 1) ÷ √(1 − S·SR + (K − 1) ÷ 4 × SR²)], with the luck bar "
         "SR<sub>0</sub> = √V × [(1 − γ) Φ<sup>−1</sup>(1 − 1 ÷ N) + γ Φ<sup>−1</sup>(1 − 1 ÷ (N e))]. SR is the arithmetic Sharpe per day, n the days, S and K skew and kurtosis, "
         "N the versions tried, V the variance of their Sharpes",
         "The chance the Sharpe is skill, after allowing for N versions tried. Very sensitive to V, so two answers are shown. It is outside Gate B.",
         f"{res} deflated_sharpe(), expected_max_sharpe(); ros/validation/trials.py count()")], W3))
    A('<h2 id="2.5">2.5 Costs &amp; execution</h2>' + where('Results tab, section "Run diagnostics", card "Costs &amp; execution".',
      val + ' The sweep itself is on the sheet "Appendix cost sweep".') + table("2.5", H3, [
        ("Two-way turnover a year", "As in 2.1", "", ""),
        ("Breakeven round-trip cost", "The cost at which CAGR equals the benchmark's, read between two points of the cost sweep", "How much trading cost the edge can absorb. Blank if beyond the sweep.", scr),
        ("Edge at a high cost", "CAGR re-simulated at that round-trip cost − CAGR<sub>benchmark</sub>", "What survives expensive trading.", scr + "; config/costs.yaml sweep"),
        ("Fills over the run", "Count of trades: buys, sells and resizes", "How busy the book is.", scr),
        ("Names held per rebalance, mean", "mean(stocks held per rebalance)", "Too few means the result rests on few companies.", scr),
        ("Largest single weight", "max(single weight at any rebalance)", "Concentration risk.", scr),
        ("Different stocks held", "Count of distinct names", "Higher means more breadth.", scr),
        ("Top-2 stocks' share of gains", "Gains of the two best names ÷ gains of all winners", "High means a couple of stocks made the result.", scr),
        ("Mean / maximum cash share", "mean / max(cash ÷ NAV)", "How invested the book really was.", scr),
        ("Median holding period", "Median calendar days, entry to exit", "How long a position typically lasts.", scr),
        ("Small-cap share", "mean(NAV share in Smallcap 250 names)", "How much of the result is a small-cap bet.", scr)], W3))
    A('<h2 id="2.6">2.6 Statistical robustness</h2>' + where('Results tab, section "Run diagnostics", card "Statistical robustness".',
      val + ' Sheets "Sensitivities", "Cash-rate sweep", "Sub-period stability" and "Sub-period CAGR" hold the tables behind them.'))
    A("<p>Every Sharpe in this card is arithmetic: mean(r − Rf per day) ÷ stdev(r − Rf per day) × √252.</p>" + table("2.6", H3, [
        ("Sharpe (arithmetic)", "mean(r − Rf per day) ÷ stdev(r − Rf per day) × √252", "The form the statistical tests use.", f"{core} sharpe()"),
        ("Bootstrap Sharpe 95% low / high", "2.5th and 97.5th percentile of the Sharpe across 2,000 re-shuffled histories (stationary bootstrap, blocks of days)",
         "A range that includes low values means the Sharpe is uncertain.", f"{res} stationary_bootstrap()"),
        ("Paired P(no Sharpe edge), each comparator", "Share of re-shuffled histories where strategy Sharpe − comparator Sharpe ≤ 0, both cut at the same days",
         "Small means the edge is hard to explain by chance.", f"{res} stationary_bootstrap()"),
        ("Paired P with a 5-day / 63-day block", "The same P with the average block length fixed", "A check that the answer does not hang on the block length.", f"{ge} paired_bootstrap(), sensitivity"),
        ("Paired Sharpe difference, 95% interval low", "2.5th percentile of the Sharpe difference across the histories", "Below 0 means no edge is within the range.", f"{res} stationary_bootstrap()"),
        ("Factor alpha a year", "Regress r − c on the factor indices' returns − c; α is the intercept. Shown as (1 + α)<sup>252</sup> − 1", "Return left after known factors.", f"{pf} factor_fingerprint()"),
        ("Alpha HAC t-stat; p-value", "α ÷ its HAC (Newey-West) standard error; p is the two-sided probability of that t", "How sure we are alpha is not zero.", f"{pf} factor_fingerprint()"),
        ("Factor alpha over the risk-free rate", "The same regression with returns above Rf instead of c", "Shown beside the main figure.", "lightyear/gate_run.py score(); " + scr),
        ("Loading on a factor", "β<sub>k</sub> in the factor regression", "How much of that factor it behaves like.", f"{pf} factor_fingerprint()"),
        ("Factor R-squared", "Share of variance the factors explain", "High means mostly known factors.", f"{pf} factor_fingerprint()"),
        ("Alpha with a factor left out; on a variant", "The same regression with one factor removed, or on a variant book", "Shows how much one factor or rule was accounting for.", f"{ge} factor_alpha(), leave_one_out"),
        ("Worst sub-period excess CAGR", "The smallest CAGR<sub>strategy</sub> − CAGR<sub>benchmark</sub> across the windows", "Whether the result depends on one stretch.", f"{res} subperiod_table(), oos_summary()"),
        ("Last window: CAGR, Sharpe", "CAGR and arithmetic Sharpe on the last window's days", "How it did most recently.", scr),
        ("CAGR after one rule change", "Re-simulate with one rule changed", "A real effect keeps its sign when a rule moves.", scr),
        ("CAGR / edge from a later start", "Re-simulate from that start date", "Tests the years with the weakest data.", scr),
        ("CAGR with cash at another rate", "Re-simulate with idle cash earning that rate", "How much the cash rate contributes.", scr + "; config/fund.yaml cash_rate_sweep"),
        ("Deflated Sharpe: selection threshold", "The luck bar SR<sub>0</sub> in 2.4, as a yearly Sharpe", "The Sharpe luck alone could reach after N versions.", f"{res} expected_max_sharpe()")], W3))
    A('<h2 id="2.7">2.7 Diagnostics</h2>' + where('Results tab, section "Run diagnostics", card "Diagnostics (specific to this strategy\'s rules)".',
      val + ' Sheets "Rebalance log", "Exits by reason" and "Exits (every sell)" hold the detail.') + table("2.7", H3, [
        ("Rebalances with few names", "Count with fewer than 5 names, overall and while buying was open", "Separates a filter holding cash from a universe running dry.", scr),
        ("Signals with buying shut; share", "Count of signals with the index filter closed; ÷ all signals", "How often the market filter stopped new buys.", scr),
        ("Signals fully in cash; with few eligible names", "Counts of signals", "How often filters left nothing or little to buy.", scr),
        ("Eligible names, mean per signal", "mean(names passing every filter)", "How wide the choice was.", scr),
        ("Names removed by a rule", "mean(top-band names rejected per signal)", "How hard a filter bites.", scr),
        ("Names bought and cash share at the first fill", "Count of positions opened on day one; cash ÷ NAV after it", "How the book starts.", scr),
        ("Resize fills", "Count of trades that only resized a position", "How much trading is upkeep.", scr),
        ("Rebalances with a weight above 25%", "Count", "Concentration risk.", scr),
        ("Exits by rule; their mean return", "Count of sells forced by each rule; mean return since entry", "Whether a rule mostly cuts losers or winners.", scr),
        ("Sells on leaving the index; their mean return", "Count; mean return since entry", "What index exits cost or earned.", scr),
        ("Buys / sells on big-move days", "Count of trades after a close up or down more than 9.5%", "Proxy for trading at a price band, where a real fill may fail.", scr),
        ("Suspensions and delistings sat through", "Count of held names with no price", "How often the missing-price rule was used.", scr)], W3))
    A('<h2 id="2.8">2.8 Other</h2>' + where('Results tab, section "Run diagnostics", card "Other".', val + ' Sheets "Checks" and "Universe coverage" hold the detail.')
      + table("2.8", ["Row", "What it counts"], [
          ("Checks passed", "Look-ahead and accounting checks that passed, out of those run.", ""),
          ("Signals; trading days; last signal and fill; run end date", "How many decisions and days the run covers, and where it stops.", ""),
          ("Universe source; members; members priced; never priced", "Which index list was used, and how many members could actually be traded.", ""),
          ("Price moves that coincide with an adjustment change", "Whether a price rule is tripped by splits and bonuses rather than real shocks.", ""),
          ("Trials for the deflated Sharpe", "N in 2.4: versions from the paper, earlier runs and studies, plus this run's sensitivities.", ""),
          ("Previous run rows", "The same metrics copied from the earlier run, for comparison.", "")], [40, 60]))

    # ------------------------------------------------------------ Part 3
    n_f = len(INVESTABLE_FACTORS)
    A('<h1 class="brk" id="p3">Part 3. The Gate B tab</h1>')
    A(where(f'Gate B tab, card "Gate B: investment decision" (gate version {GATE_VERSION}): the tables "Hard blocks" and "Evidence scorecard".',
            'diagnostics workbook, sheet "Gate B", pasted results. The status is repeated on its "Summary" sheet.'))
    A("<p>Hard blocks decide the status, PASS or FAIL. Scorecard rows are green, amber or red and do not block. A test with nothing to run on shows as not run, which is "
      f"not a pass. Every Sharpe here is arithmetic, over the risk-free rate of {RF}.</p>")
    W4 = [23, 40, 22, 15]
    H4 = ["Test", "What is calculated", "Pass mark", "Kind"]
    A('<h2 id="3.1">3.1 Hard blocks</h2>' + table("3.1", H4, [
        ("Data integrity", "Every check the run wrote passed; no card rule broken; coverage = Σ(priced members × sessions) ÷ Σ(all members × sessions)",
         f"All pass; coverage ≥ {pc(di['min_priced_coverage'])}", "Hard block", "lightyear/gate_run.py _coverage(), _checks(); ros/governance/gate_v2.py integrity_row()"),
        ("Edge over the benchmark", "CAGR<sub>strategy</sub> − CAGR<sub>benchmark</sub>, at the cost on the card", "&gt; 0", "Hard block", f"lightyear/gate_run.py score() net_edge; {core} cagr_from_returns()"),
        ("Paired bootstrap", "P = share of 2,000 re-shuffled histories where Sharpe<sub>strategy</sub> − Sharpe<sub>benchmark</sub> ≤ 0. Block length chosen from the data; seed 7",
         f"P ≤ {bt['p_max']}", "Hard block", f"{ge} paired_bootstrap(); {core} stationary_bootstrap_indices(), sharpe_draws(), politis_white_block(), auto_mean_block()")], W4))
    A('<h2 id="3.2">3.2 Evidence scorecard</h2>' + table("3.2", H4, [
        ("Sub-period stability", "Sharpe<sub>strategy</sub> − Sharpe<sub>benchmark</sub> in each of 4 equal windows; the value shown is the worst gap",
         f"Green: ≥ {pc(sp['min_windows_ahead_share'])} of windows ahead and none below {sp['window_floor']}. Amber: worst ≥ {sp['window_floor_amber']}", "Scorecard",
         f"{ge} sub_period(), windows(); {core} split_windows(); ros/governance/gate_v2.py evaluate()"),
        ("Factor alpha, one-sided", f"Regress r − c on {n_f} factor indices' returns − c. t = α ÷ its HAC standard error, with lags = ⌈4 (n ÷ 100)<sup>2/9</sup>⌉",
         f"Green: α &gt; 0 and t ≥ {fa['t_green_min']}. Amber: t ≥ {fa['t_amber_min']}", "Scorecard", f"{pf} factor_fingerprint(); {ge} factor_alpha(), INVESTABLE_FACTORS"),
        ("Performance after publication", "CAGR<sub>strategy</sub> − CAGR<sub>benchmark</sub> from the paper's publication date; needs 252 trading days",
         f"Green: &gt; {pc(pp['edge_green_min'])}. Amber: &gt; {pc(pp['edge_amber_min'])}", "Scorecard", f"{core} post_publication(), publication_cutoff(); ros/governance/gate_v2.py evaluate()")], W4))
    A("<p>Under each test the tab says in plain words what it asks. The decision stays PENDING until a named person records it.</p>")

    A('<h3>The two workbooks</h3><p>Both are downloaded from the Results tab, and every section above names its sheet. <b>Main workbook:</b> Returns overview, Market phases, '
      "Rolling returns, Factor attribution, Drawdown and risk, Tail risk, Index and capture, Calendar years, Allocation, Daily calculations, Python vs Excel, SE Return Analytics, "
      "Monthly series, Returns. <b>Diagnostics workbook:</b> Summary, Returns, Monthly returns, Gate B, Comparators, Validation, Holdings, Rebalances, Trades, and one sheet for each "
      "table the run wrote.</p>")
    A('<p class="src">Sources: ros/metrics/se.py, ros/metrics/qi.py, ros/metrics/core.py, lightyear/charts.py, lightyear/main_workbook.py, lightyear/allocation.py, lightyear/workbook.py, '
      "lightyear/se_sheet.py, lightyear/gate_run.py, ros/governance/gate_v2.py, ros/validation/gate_evidence.py, research.py, portfolio.py, trials.py, config/fund.yaml, "
      "config/market_phases.yaml, config/sector_groups.yaml, config/gate_thresholds.yaml.</p>")
    return "\n".join(h)


TOC = [("p1", "Part 1. The main display (monthly)", 0), ("1.1", "1.1 Strategy vs benchmark: the five tiles", 1), ("1.2", "1.2 Financial-year returns", 1),
       ("1.3", "1.3 Strategy against index NAV", 1), ("1.4", "1.4 Trailing returns", 1), ("1.5", "1.5 Key return metrics", 1), ("1.6", "1.6 Market phases", 1),
       ("1.7", "1.7 Rolling returns", 1), ("1.8", "1.8 Returns attribution to factor indices", 1), ("1.9", "1.9 Drawdown and advanced risk ratios", 1), ("1.10", "1.10 Tail risk", 1),
       ("1.11", "1.11 Performance versus index and capture", 1), ("1.12", "1.12 Calendar-year tables", 1), ("1.13", "1.13 Market-cap and sector allocation", 1),
       ("p2", "Part 2. Daily calculations and run diagnostics", 0), ("2.1", "2.1 Daily calculations", 1), ("2.2", "2.2 The daily charts", 1), ("2.3", "2.3 Appendix: the simpler alternatives", 1),
       ("2.4", "2.4 Returns & risk", 1), ("2.5", "2.5 Costs & execution", 1), ("2.6", "2.6 Statistical robustness", 1), ("2.7", "2.7 Diagnostics", 1), ("2.8", "2.8 Other", 1),
       ("p3", "Part 3. The Gate B tab", 0), ("3.1", "3.1 Hard blocks", 1), ("3.2", "3.2 Evidence scorecard", 1)]

CSS = """
@page { size: A4; margin: 17mm 17mm 19mm 17mm;
  @top-left { content: "%(run)s"; font: 8pt Arial; color: #6b7785; padding-bottom: 3mm; }
  @bottom-left { content: "%(sig)s"; font: 8pt Arial; color: #6b7785; border-top: 0.5pt solid #d9dee5; padding-top: 2mm; }
  @bottom-right { content: "Page " counter(page); font: 8pt Arial; color: #6b7785; border-top: 0.5pt solid #d9dee5; padding-top: 2mm; }
  @bottom-center { content: ""; border-top: 0.5pt solid #d9dee5; } }
@page :first { @top-left { content: ""; } }
body { font: 9.5pt/1.36 Arial, Helvetica, sans-serif; color: #1c2430; }
h1 { color: #1f4e79; font-size: 20pt; margin: 0 0 8pt; } h1.title { font-size: 27pt; margin: 0 0 4pt; } h1.brk { break-before: page; }
h2 { color: #1f4e79; font-size: 13pt; margin: 10pt 0 4pt; break-after: avoid; } h2.c { font-size: 15pt; margin: 7pt 0 2pt; }
h3 { color: #1f4e79; font-size: 11.5pt; margin: 9pt 0 3pt; break-after: avoid; }
p { margin: 4pt 0; } p.sub { color: #5f6b7a; font-size: 12pt; margin: 0 0 9pt; } p.ft { margin: 8pt 0 2pt; break-after: avoid; } p.src { color: #6b7785; font-size: 8.3pt; margin-top: 10pt; }
p.where { font-size: 8.9pt; background: #f6f8fa; border-left: 3pt solid #9aa5b1; padding: 4pt 9pt; margin: 3pt 0 6pt; break-after: avoid; }
p.cap { font-size: 8.4pt; margin: 6pt 0 2pt; break-after: avoid; } p.tiny { font-size: 7.6pt; color: #6b7785; margin: 2pt 0 4pt; }
table { border-collapse: collapse; width: 100%%; margin: 4pt 0 8pt; table-layout: fixed; }
th { text-align: left; color: #1f4e79; background: #eef3f8; border-bottom: 1.2pt solid #1f4e79; padding: 4pt 6pt; font-size: 8.8pt; }
td { border-bottom: 0.5pt solid #d9dee5; padding: 2.6pt 6pt; vertical-align: top; font-size: 8.6pt; overflow-wrap: anywhere; } tr { break-inside: avoid; }
.f { background: #f6f8fa; border: 0.6pt solid #dfe4ea; padding: 7pt 12pt; margin: 2pt 0 6pt; break-inside: avoid; } .f math { font-size: 13pt; }
.note { background: #eef3f8; border-left: 3pt solid #1f4e79; padding: 5pt 11pt; margin: 6pt 0; break-inside: avoid; font-size: 9.9pt; }
.warn { background: #fff4d6; border-left: 3pt solid #d9a514; padding: 6pt 11pt; margin: 8pt 0; break-inside: avoid; font-size: 10.2pt; }
ul { margin: 4pt 0 4pt 14pt; padding: 0; } li { margin: 2pt 0; }
.toc { margin: 0; columns: 2; column-gap: 22pt; } .toc div { display: flex; align-items: baseline; font-size: 8.8pt; line-height: 1.14; margin: 0; }
.toc .p0 { color: #1f4e79; font-weight: bold; font-size: 9.6pt; margin-top: 3pt; } .toc .p1 { padding-left: 12pt; }
.toc .dots { flex: 1; border-bottom: 1.2pt dotted #9aa5b1; margin: 0 5pt 2.5pt; } .toc .p0 .dots { border-bottom-color: #1f4e79; }
""" % {"run": RUNNING, "sig": SIG}


def html_doc(pages=None):
    CHECKS.clear()
    body = content()
    toc = '<div class="toc">' + "".join(f'<div class="p{lvl}"><span>{t}</span><span class="dots"></span><span>{(pages or {}).get(k, "")}</span></div>' for k, t, lvl in TOC) + "</div>"
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Financial metrics</title><style>{CSS}</style></head><body>"
            + body.replace("%%TOC%%", toc) + "</body></html>")


def print_pdf():
    browsers = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
    exe = next((b for b in browsers if os.path.exists(b)), None)
    if not exe:
        raise SystemExit(f"wrote {OUT}.html; no Edge or Chrome found to print the PDF")
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={OUT}.pdf", "file:///" + (OUT + ".html").replace("\\", "/")],
                   check=True, capture_output=True, timeout=180)


def main():
    if "--checks" in sys.argv:
        html_doc()
        for where, what, src in CHECKS:
            print(f"{where}\t{what}\t{src}")
        return
    import pymupdf
    pages = None
    for _ in range(5):                       # repeat until the contents list's page numbers stop changing
        doc = html_doc(pages)
        assert "Harshil" not in doc and "Pahuja" not in doc and "Systematic Equity" not in doc, "no personal name and no fund name"
        with open(OUT + ".html", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(doc)
        print_pdf()
        pdf = pymupdf.open(OUT + ".pdf")
        found = {}
        for k, t, _lvl in TOC:
            for i in range(len(pdf) - 1, 0, -1):     # the LAST page that carries the heading: an earlier one is the contents list
                if t in " ".join(pdf[i].get_text().split()):
                    found[k] = i + 1
                    break
        n = len(pdf)
        pdf.close()
        if found == pages:
            break
        pages = found
    print(f"{OUT}.pdf  ({n} pages, {len(CHECKS)} formulas with a source)")


if __name__ == "__main__":
    main()
