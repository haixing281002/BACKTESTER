# Quant AI Researcher
"""Build docs/lightyear-results-gate-b-metrics-v3.pdf: "Financial metrics".

Only the metrics Lightyear shows for every run and the workbook calculates: the headline tiles, the charts, the Core
performance table and the figures under it, and SE Return Analytics (monthly). No Gate B tests, no rows written by one
run's script, no run results and no examples.

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


# ---------------------------------------------------------------- MathML, for the boxed formulas
def M(inner):
    return f'<div class="f"><math display="inline">{inner}</math></div>'


def mi(x):
    return f"<mi>{x}</mi>"


def mt(x):
    return f"<mtext>{x}</mtext>"


def mo(x):
    return f"<mo>{x}</mo>"


def mn(x):
    return f"<mn>{x}</mn>"


def frac(a, b):
    return f"<mfrac><mrow>{a}</mrow><mrow>{b}</mrow></mfrac>"


def sub(a, b):
    return f"<msub><mrow>{a}</mrow><mrow>{b}</mrow></msub>"


def sup(a, b):
    return f"<msup><mrow>{a}</mrow><mrow>{b}</mrow></msup>"


def box(sec, title, mathml, words, src):
    CHECKS.append((sec, words, src))
    return f'<p class="ft"><b>{title}</b></p>' + M(mathml)


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


def content():
    om, dl = se.DEFAULT_INPUTS["omega_threshold"], se.DEFAULT_INPUTS["drawdown_limit"]
    W3 = [22, 41, 37]
    h = []
    A = h.append
    core, ch = "ros/metrics/core.py", "lightyear/charts.py"

    # ------------------------------------------------------------ page 1
    A('<h1 class="title">Financial metrics</h1><p class="sub">Every metric on the Lightyear dashboard and in the workbook: the formula, and how to read it.</p>')
    A('<div class="note"><p><b>Part 1</b> is the daily block: the tiles, charts and Core performance table Lightyear builds for every run. <b>Part 2</b> is SE Return '
      'Analytics, the monthly block. Both are on the Results tab, and the workbook calculates both with live formulas.</p>'
      '<p>There are no run results or examples here. The only numbers are method settings, checked against the code.</p></div>')
    A('<p class="ft"><b>Notation used in every formula</b></p>' + table("Notation", ["Symbol", "Meaning"], [
        ("r, b", "One day's return on the strategy and on the benchmark, the NIFTY 500 price index.", ""),
        ("m", "One calendar month's return, compounded from the daily returns. Used in Part 2.", ""),
        (f"Rf ({RF})", "The risk-free rate in every Sharpe and Sortino. One config setting. A yardstick, not income.", ""),
        ("c", "The card's cash rate: what idle cash earns in the backtest. Beta subtracts it. Not the risk-free rate.", ""),
        ("V<sub>t</sub>", "Portfolio value on day t.", ""),
        ("mean, stdev", "Average and sample standard deviation (divides by n − 1). <b>Pop stdev</b> divides by n; Part 2 uses it.", ""),
        ("√252, √12", "Annualise daily and monthly volatility. 252 is the assumed trading days a year.", ""),
        ("years", "Calendar days ÷ 365.25. In Part 2, months ÷ 12.", "")], [16, 84]))
    A("<h2 class='c'>Contents</h2>%%TOC%%")

    # ------------------------------------------------------------ Part 1
    A('<h1 class="brk" id="p1">Part 1. On the Lightyear dashboard (daily)</h1>')
    A('<h2 id="1.1">1.1 The five headline numbers</h2><p>These tiles appear on every run\'s Results tab, for the strategy and the benchmark over the same days. The comparators '
      'table repeats CAGR, volatility, Sharpe and worst fall for each alternative.</p>')
    A(box("1.1", "CAGR: the steady yearly growth rate from start to finish",
          mt("CAGR") + mo("=") + sup("<mo>(</mo>" + frac(sub(mi("V"), mt("end")), sub(mi("V"), mt("start"))) + "<mo>)</mo>", frac(mn(1), mt("years"))) + mo("−") + mn(1),
          "CAGR = (V_end / V_start)^(1/years) − 1, V_start = 100 on the session before the first return", f"{core} cagr(), cagr_from_returns(); workbook Summary!B12"))
    A(box("1.1", "Volatility: how much returns swing in a year. Lower is a smoother ride",
          mt("Vol") + mo("=") + mt("stdev") + mo("(") + sub(mi("r"), mt("daily")) + mo(")") + mo("×") + "<msqrt><mn>252</mn></msqrt>",
          "Vol = stdev(daily r) × √252", f"{core} ann_vol(); workbook Summary!B13"))
    A(box("1.1", f"Sharpe (risk-free rate {RF}): return above the risk-free rate, per unit of risk. Higher is better",
          mt("Sharpe") + mo("=") + frac(mt("CAGR") + mo("−") + mt(RF), mt("Vol")),
          f"Sharpe = (CAGR − {RF}) / Vol", f"{core} sharpe_geometric(); config/fund.yaml sharpe_hurdle; workbook Summary!B14"))
    A(f"<p>The {RF} is the risk-free rate, a yardstick. It is not income the strategy earns: idle cash earns the card's cash rate. This headline Sharpe is the geometric form. "
      "Figures for a single calendar year use the arithmetic form shown in 1.4.</p>")
    A(box("1.1", "Worst fall from peak (maximum drawdown): the biggest loss from a high to a later low",
          mt("Max drawdown") + mo("=") + "<munder><mi>max</mi><mi>t</mi></munder>" + mo("(") + mn(1) + mo("−")
          + frac(sub(mi("V"), mi("t")), "<munder><mi>max</mi><mrow><mi>s</mi><mo>≤</mo><mi>t</mi></mrow></munder>" + sub(mi("V"), mi("s"))) + mo(")"),
          "Max drawdown = max over t of (1 − V_t / highest V so far)", f"{core} max_drawdown(); workbook Summary!B15"))
    A(box("1.1", "100 became: what 100 grew into, after every daily return",
          mt("Final") + mo("=") + mn(100) + mo("×") + "<munder><mo>∏</mo><mi>t</mi></munder>" + mo("(") + mn(1) + mo("+") + sub(mi("r"), mi("t")) + mo(")"),
          "Final = 100 × ∏(1 + r_t)", f"{core} value_from_returns(); workbook Summary!B11"))
    A('<h2 id="1.2">1.2 The charts</h2>' + table("1.2", ["Chart", "Calculation", "How to read it"], [
        ("Growth of 100", "100 × running product of (1 + r)", "Above the benchmark's line means ahead of it on that day.", f"{ch} value_path()"),
        ("Drawdown", "V<sub>t</sub> ÷ highest V so far − 1", "0% is a new high. Deeper dips are bigger losses.", f"{ch} build()"),
        ("Rolling volatility", "stdev of the last 63 daily returns × √252", "How bumpy the last three months were.", f"{core} rolling_vol(), window 63"),
        ("Calendar-year return", "Product of (1 + r) within the year − 1", "First and last years may be part-years.", f"{ch} build(), calendar"),
        ("Monthly heat map", "Product of (1 + r) within the month − 1", "Green months gained, red months lost.", f"{ch} build(), monthly")], W3))
    A('<h2 id="1.3">1.3 Core performance table</h2><p>For the strategy and the benchmark over the same days. CAGR, volatility, Sharpe and maximum drawdown are the '
      "formulas in 1.1. The workbook's Core metrics sheet calculates each row with a formula over the Returns sheet.</p>")
    A(table("1.3", ["Metric", "Formula", "How to read it"], [
        (f"Sortino (risk-free rate {RF})", f"(CAGR − {RF}) ÷ DD, where DD = √mean(min(r − Rf per day, 0)²) × √252", "Like the Sharpe, but only falls below the risk-free rate count as risk.",
         f"{core} sortino_geometric(); workbook Summary!B16"),
        ("Calmar", "CAGR ÷ maximum drawdown", "Return per unit of worst fall.", f"{core} calmar(); workbook Summary!B17"),
        ("Drawdown duration", "Longest run of trading days below a previous high", "How long the longest wait to recover took.", f"{core} drawdown_duration(); workbook 'Core metrics'"),
        ("95% CVaR (daily loss)", "−mean of the daily returns at or below their 5th percentile", "The average bad day, as a positive number.", f"{core} cvar(), cvar_95(); workbook 'Core metrics'"),
        ("Skew", "Sample skew of daily returns", "Negative means big falls are more common than big rises.", f"{core} skew(); workbook 'Core metrics'"),
        ("CAGR without the 10 best days", "Remove the 10 best days, then compound; years run from the first return date", "Whether a handful of days made the result.",
         f"{core} cagr_without_best_days(); workbook 'Core metrics'"),
        ("Beta", "Cov(r − c, b − c) ÷ Var(b − c)", "1.0 moves in line with the index. Below 1 is less sensitive.", f"{core} beta(); workbook 'Core metrics'"),
        ("Tracking error", "stdev(r − b) × √252", "How far it strays from the index.", f"{core} tracking_error(); workbook 'Core metrics'"),
        ("Information ratio", "mean(r − b) × 252 ÷ tracking error", "Return over the index per unit of straying. Higher is better.", f"{core} information_ratio(); workbook 'Core metrics'"),
        ("Up / down capture (monthly)", "mean monthly return ÷ the benchmark's, in months the benchmark rose / fell", "Above 1 up and below 1 down is the good shape.",
         f"{core} up_capture(), down_capture(); workbook 'Core metrics'"),
        ("Rolling one-year periods behind", "Share of 252-day windows with compounded return below the index's", "How often an investor would have been trailing.",
         f"{core} rolling_periods_behind(); workbook 'Core metrics'")], W3))
    A('<h2 id="1.4">1.4 Figures under the table</h2>' + table("1.4", ["Metric", "Formula", "How to read it"], [
        ("Two-way turnover a year", "Σ |weight after − weight before| over every trade, ÷ years", "1.0 means trading the whole portfolio's value once a year.",
         f"{core} two_way_turnover_from_trades(), annual_turnover()"),
        ("After publication", "CAGR, benchmark CAGR, their gap (edge), arithmetic Sharpe and maximum drawdown, on the days from the paper's publication date",
         "Whether the result held once the idea was public. A date given only as a year is read as 31 December.", f"{core} post_publication(), publication_cutoff()"),
        ("Sharpe by calendar year (arithmetic)", "mean(r − Rf per day) ÷ stdev(r − Rf per day) × √252, on that year's days", "The yearly form of the Sharpe. It is labelled arithmetic wherever it appears.",
         f"{core} sharpe(), calendar_year_sharpe()"),
        ("Capacity per Rs 1 crore", f"For each trade: (its share of capital × Rs 1 crore) ÷ the stock's 20-day average traded value. The 95th percentile P is shown, and the capital at which it reaches the limit: {pc(TH['capacity']['p95_adv_participation_max'])} ÷ P",
         "Information only. No fund size is assumed, and the limit is a placeholder.", f"{core} capacity_unit(), adv_20(); config/gate_thresholds.yaml capacity")], W3))
    A('<h2 id="1.5">1.5 Beta in different markets</h2>' + table("1.5", ["Metric", "Formula", "How to read it"], [
        ("Up-market / down-market beta", "Beta using only days the index rose / fell", "Ideally high in rises and low in falls. The two do not average to the overall beta.",
         f"{core} beta_on(); {ch} build(), beta_split"),
        ("Beta with the index filter open / shut", "Beta using only days the card's index filter was open / shut. The filter's state on a day is read at the previous session's close",
         "Shown when the card has an index filter. A low beta when shut is the filter holding cash.", f"{ch} _filter_betas()")], W3))

    # ------------------------------------------------------------ Part 2
    A('<h1 class="brk" id="p2">Part 2. SE Return Analytics (monthly)</h1>')
    A(f'<div class="warn"><p><b>A separate block, on monthly returns.</b> It is on the Results tab and in the workbook sheet "SE Return Analytics". Every figure uses calendar-month '
      f'returns m compounded from the daily returns, the population standard deviation, and three inputs: risk-free rate {RF}, Omega threshold {pc(om)} a month, drawdown limit {pc(dl)}. '
      'Do not compare a figure here with a daily figure of the same name in Part 1. The benchmark is the price index.</p>'
      '<p><b>Python and Excel calculate each metric separately.</b> Python calculates it in ros/metrics/se.py; Excel calculates it from a live formula in the workbook. The '
      'workbook\'s "Python vs Excel" sheet sets the two side by side and marks each OK or FAIL at 1e-9.</p></div>')
    names = {"Performance": "2.1", "Risk Parameters": "2.2", "Performance Vs Index": "2.3", "Capture Ratio": "2.4", "Extreme Capture Ratio": "2.5", "Tail Risk": "2.6"}
    rowof = {}
    r_ = 5
    prev = None
    for s_, lab, *_ in se.SPEC:
        if prev is not None and s_ != prev:
            r_ += 1
        rowof[lab] = r_
        prev = s_
        r_ += 1
    for sec_name, num in names.items():
        rows = [(lab, SE_FORMULA[lab], SE_READ[lab], f"ros/metrics/se.py compute() [{lab}]; workbook 'SE Return Analytics'!K{rowof[lab]}")
                for s_, lab, *_ in se.SPEC if s_ == sec_name]
        A(f'<h2 id="{num}">{num} {sec_name}</h2>' + table(num, ["Metric", "Formula", "How to read it"], rows, [24, 40, 36]))
    A('<h2 id="2.7">2.7 Period tables</h2>' + table("2.7", ["Metric", "Formula", "How to read it"], [
        ("Quarterly return", "∏(1 + m) over the calendar quarter − 1", "A quarter with fewer than three months is a part-period.", "ros/metrics/se.py periods(), compute() tables; workbook 'SE Return Analytics' columns F, G"),
        ("Financial Year Performance", "∏(1 + m) from April to March − 1", "* marks the first year, ** a last part-year.", "ros/metrics/se.py periods(), compute() tables; workbook rows under the analytics"),
        ("Calendar Year Performance", "∏(1 + m) from January to December − 1", "Same marks.", "ros/metrics/se.py periods(), compute() tables"),
        ("Max Calendar Year Drawdown", "The Max Drawdown formula on that year's months alone", "<b>A loss in the year's first month is not counted</b>, because the peak starts at that month's own value.",
         "ros/metrics/se.py _dd(), compute() tables; workbook LET / SCAN / LAMBDA cells")], [24, 40, 36]))

    A('<p class="src">Sources: ros/metrics/core.py, ros/metrics/se.py, lightyear/charts.py, lightyear/workbook.py, lightyear/se_sheet.py, config/fund.yaml, '
      "config/gate_thresholds.yaml.</p>")
    return "\n".join(h)


TOC = [("p1", "Part 1. On the Lightyear dashboard (daily)", 0), ("1.1", "1.1 The five headline numbers", 1), ("1.2", "1.2 The charts", 1),
       ("1.3", "1.3 Core performance table", 1), ("1.4", "1.4 Figures under the table", 1), ("1.5", "1.5 Beta in different markets", 1),
       ("p2", "Part 2. SE Return Analytics (monthly)", 0), ("2.1", "2.1 Performance", 1), ("2.2", "2.2 Risk Parameters", 1), ("2.3", "2.3 Performance Vs Index", 1),
       ("2.4", "2.4 Capture Ratio", 1), ("2.5", "2.5 Extreme Capture Ratio", 1), ("2.6", "2.6 Tail Risk", 1), ("2.7", "2.7 Period tables", 1)]

CSS = """
@page { size: A4; margin: 17mm 17mm 19mm 17mm;
  @top-left { content: "%(run)s"; font: 8pt Arial; color: #6b7785; padding-bottom: 3mm; }
  @bottom-left { content: "%(sig)s"; font: 8pt Arial; color: #6b7785; border-top: 0.5pt solid #d9dee5; padding-top: 2mm; }
  @bottom-right { content: "Page " counter(page); font: 8pt Arial; color: #6b7785; border-top: 0.5pt solid #d9dee5; padding-top: 2mm; }
  @bottom-center { content: ""; border-top: 0.5pt solid #d9dee5; } }
@page :first { @top-left { content: ""; } }
body { font: 9.7pt/1.45 Arial, Helvetica, sans-serif; color: #1c2430; }
h1 { color: #1f4e79; font-size: 20pt; margin: 0 0 8pt; } h1.title { font-size: 27pt; margin: 0 0 4pt; } h1.brk { break-before: page; }
h2 { color: #1f4e79; font-size: 13.5pt; margin: 13pt 0 5pt; break-after: avoid; } h2.c { font-size: 15pt; margin: 7pt 0 2pt; }
h3 { color: #1f4e79; font-size: 12.5pt; margin: 14pt 0 4pt; break-after: avoid; }
p { margin: 4pt 0; } p.sub { color: #5f6b7a; font-size: 12pt; margin: 0 0 9pt; } p.ft { margin: 8pt 0 2pt; break-after: avoid; } p.src { color: #6b7785; font-size: 8.3pt; margin-top: 10pt; }
p.cap { font-size: 8.4pt; margin: 6pt 0 2pt; break-after: avoid; } p.tiny { font-size: 7.6pt; color: #6b7785; margin: 2pt 0 4pt; }
table { border-collapse: collapse; width: 100%%; margin: 4pt 0 8pt; table-layout: fixed; }
th { text-align: left; color: #1f4e79; background: #eef3f8; border-bottom: 1.2pt solid #1f4e79; padding: 4pt 6pt; font-size: 8.8pt; }
td { border-bottom: 0.5pt solid #d9dee5; padding: 4pt 6pt; vertical-align: top; font-size: 8.8pt; overflow-wrap: anywhere; } tr { break-inside: avoid; }
.f { background: #f6f8fa; border: 0.6pt solid #dfe4ea; padding: 7pt 12pt; margin: 2pt 0 6pt; break-inside: avoid; } .f math { font-size: 13pt; }
.note { background: #eef3f8; border-left: 3pt solid #1f4e79; padding: 5pt 11pt; margin: 6pt 0; break-inside: avoid; font-size: 9.9pt; }
.warn { background: #fff4d6; border-left: 3pt solid #d9a514; padding: 6pt 11pt; margin: 8pt 0; break-inside: avoid; font-size: 10.2pt; }
ul { margin: 4pt 0 4pt 14pt; padding: 0; } li { margin: 2pt 0; }
.toc { margin: 0; } .toc div { display: flex; align-items: baseline; font-size: 8.8pt; line-height: 1.14; margin: 0; }
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
