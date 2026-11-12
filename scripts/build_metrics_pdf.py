# Quant AI Researcher
"""Build docs/lightyear-results-gate-b-metrics-v3.pdf: "Financial metrics and Gate B tests", version 3.

Same document as the earlier metrics PDF, with today's formulas: the same title, intro box, notation table, contents,
three parts, formula boxes, three-column tables and one short block per Gate B test. No run results and no examples; the
only numbers are method settings and pass marks, read here from the code and config.

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
from ros.validation import research
from ros.validation.gate_evidence import INVESTABLE_FACTORS
from ros.versions import GATE_VERSION

OUT = os.path.join(REPO, "docs", "lightyear-results-gate-b-metrics-v3")
SIG = "Quant AI Researcher"
RUNNING = "Lightyear: financial metrics and Gate B tests"
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


def luck_bar_svg():
    """The luck bar SR0 against N at V = 1, from the code's own function."""
    w, h, l, b, t = 760, 150, 28, 30, 8
    xs = list(range(2, 201))
    ys = [research.expected_max_sharpe(n, 1.0) for n in xs]
    px = lambda n: l + (n / 200.0) * (w - l - 6)
    py = lambda y: t + (1 - y / 3.0) * (h - b - t)
    path = "M " + " L ".join(f"{px(n):.1f} {py(y):.1f}" for n, y in zip(xs, ys))
    grid = "".join(f'<line x1="{l}" y1="{py(v):.1f}" x2="{w - 6}" y2="{py(v):.1f}" stroke="#e3e7ec" stroke-width="1"/>'
                   f'<text x="{l - 6}" y="{py(v) + 3.5:.1f}" text-anchor="end" font-size="10" fill="#667">{v}</text>' for v in (0, 1, 2, 3))
    ticks = "".join(f'<text x="{px(n):.1f}" y="{h - b + 14}" text-anchor="middle" font-size="10" fill="#667">{n}</text>' for n in range(0, 201, 25))
    return (f'<p class="cap"><b>The luck bar SR<sub>0</sub> rises with N (shown with the default V = 1)</b></p>'
            f'<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg">{grid}{ticks}'
            f'<path d="{path}" fill="none" stroke="#2166ac" stroke-width="2.2"/>'
            f'<text x="{(w + l) / 2:.0f}" y="{h - 2}" text-anchor="middle" font-size="10" fill="#667">N, the number of strategy versions tried</text></svg>')


def bootstrap_svg():
    cols = {"A": "#2166ac", "B": "#c8660c", "C": "#7f8c99", "D": "#5a9bd4", "E": "#dfa26b"}

    def bar(segs, gaps):
        x, out = 0.0, ""
        for name, wd in segs:
            if name is None:
                out += f'<rect x="{x}" y="0" width="{wd}" height="26" fill="#edf0f3"/>'
            else:
                out += (f'<rect x="{x}" y="0" width="{wd - gaps}" height="26" fill="{cols[name]}"/>'
                        f'<text x="{x + (wd - gaps) / 2}" y="17" text-anchor="middle" font-size="11" fill="#fff" font-weight="bold">{name}</text>')
            x += wd
        return f'<svg viewBox="0 0 760 26" width="100%" xmlns="http://www.w3.org/2000/svg">{out}</svg>'

    top = [(None, 107), ("A", 90), (None, 32), ("B", 67), (None, 85), ("C", 121), (None, 32), ("D", 52), (None, 55), ("E", 88), (None, 31)]
    low = [("D", 53), ("A", 91), ("E", 93), ("C", 122), ("B", 68), ("D", 53), ("C", 122), ("A", 92), ("E", 66)]
    return ('<p class="cap"><b>The actual history, in order</b></p>' + bar(top, 0)
            + '<p class="cap"><b>One bootstrap draw: blocks of real days, in random order, with random lengths, to the same total length</b></p>' + bar(low, 1.5)
            + '<p class="tiny">The strategy and the benchmark are cut at the same days on each draw. That is what "paired" means.</p>')


def test(sec, title, question, formula_mathml, words, src, method, passmark, fail, watch):
    CHECKS.append((sec, words, src))
    f = M(formula_mathml) if formula_mathml else ""
    return (f'<h3 id="{sec}">{sec} {title}</h3><p><b>The question.</b> {question}</p>{f}'
            f"<p><b>Method.</b> {method} <b>Pass:</b> {passmark} <b>If it fails:</b> {fail}</p><p><b>Watch out:</b> {watch}</p>")


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
    sp, fa, pp, bt, di = TH["sub_period"], TH["factor_alpha"], TH["post_publication"], TH["bootstrap"], TH["data_integrity"]
    om, dl = se.DEFAULT_INPUTS["omega_threshold"], se.DEFAULT_INPUTS["drawdown_limit"]
    W3 = [22, 41, 37]
    h = []
    A = h.append
    core, ch, scr = "ros/metrics/core.py", "lightyear/charts.py", "the run's backtest script (its fixed validation rows)"

    # ------------------------------------------------------------ page 1
    A('<h1 class="title">Financial metrics and Gate B tests</h1><p class="sub">Every metric we calculate and every test a strategy must pass: the formula, and how to read it.</p>')
    A('<div class="note"><p><b>Part 1</b> is what the Lightyear dashboard shows. <b>Part 2</b> is SE Return Analytics, the monthly block, which is now on the dashboard and in '
      f'the workbook. <b>Part 3</b> is Gate B {GATE_VERSION}: four hard blocks and three scorecard rows, with the deflated Sharpe shown outside the gate.</p>'
      '<p>There are no run results or examples here. The only numbers are method settings and pass marks, checked against the code.</p></div>')
    A('<p class="ft"><b>Notation used in every formula</b></p>' + table("Notation", ["Symbol", "Meaning"], [
        ("r, b", "One day's return on the strategy and on the benchmark, the NIFTY 500 price index.", ""),
        ("m", "One calendar month's return, compounded from the daily returns. Used in Part 2.", ""),
        (f"Rf ({RF})", "The risk-free rate in every Sharpe and Sortino. One config setting. A yardstick, not income.", ""),
        ("c", "The card's cash rate: what idle cash earns in the backtest. Beta and the factor regression subtract it. Not the risk-free rate.", ""),
        ("V<sub>t</sub>", "Portfolio value on day t.", ""),
        ("mean, stdev", "Average and sample standard deviation (divides by n − 1). <b>Pop stdev</b> divides by n; Part 2 uses it.", ""),
        ("√252, √12", "Annualise daily and monthly volatility. 252 is the assumed trading days a year.", ""),
        ("years", "Calendar days ÷ 365.25. In Part 2, months ÷ 12.", "")], [16, 84]))
    A("<h2 class='c'>Contents</h2>%%TOC%%")

    # ------------------------------------------------------------ Part 1
    A('<h1 class="brk" id="p1">Part 1. On the Lightyear dashboard</h1>')
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
      "Figures for a single calendar year, and every Gate B test, use the arithmetic form shown in 1.3.</p>")
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
    A('<h2 id="1.3">1.3 Returns and risk table</h2><p>The Core performance table is calculated by Lightyear for every run. The tables below it are written by each run\'s '
      "script, so <b>rows tied to a strategy's rules appear only for that strategy</b>. Each row names its source.</p>")
    A(table("1.3", ["Metric", "Formula", "How to read it"], [
        ("Edge over benchmark", "CAGR<sub>strategy</sub> − CAGR<sub>benchmark</sub>", "Points a year ahead of the index.", f"{core} edge()"),
        (f"Sortino (risk-free rate {RF})", f"(CAGR − {RF}) ÷ DD, where DD = √mean(min(r − Rf per day, 0)²) × √252", "Geometric, like the headline Sharpe. Only falls below the risk-free rate count as risk.",
         f"{core} sortino_geometric(); workbook Summary!B16"),
        ("Sharpe, arithmetic", "mean(r − Rf per day) ÷ stdev(r − Rf per day) × √252", "The form used for each calendar year's Sharpe and in Gate B. It is labelled arithmetic wherever it appears.",
         f"{core} sharpe(), calendar_year_sharpe()"),
        ("Sortino, arithmetic", "mean(r − Rf per day) × 252 ÷ DD", "The yearly form of Sortino.", f"{core} sortino(), calendar_year_sortino()"),
        ("Calmar", "CAGR ÷ maximum drawdown", "Return per unit of worst fall.", f"{core} calmar(); workbook Summary!B17"),
        ("Sub-period CAGR; worst sub-period excess", "CAGR over part of the window; the smallest CAGR<sub>strategy</sub> − CAGR<sub>benchmark</sub> across the windows", "Whether the result depends on one stretch.",
         "ros/validation/research.py subperiod_table(), oos_summary()"),
        ("Drawdown in latest correction", "Each series' fall over the index's latest fall deeper than 10%", "How it behaved in the most recent real test.", scr),
        ("Drawdown duration", "Longest run of trading days below a previous high", "How long the longest wait to recover took.", f"{core} drawdown_duration(); workbook 'Core metrics'"),
        ("95% CVaR (daily loss)", "−mean of the daily returns at or below their 5th percentile", "The average bad day, as a positive number.", f"{core} cvar(), cvar_95()"),
        ("Skew", "Sample skew of daily returns", "Negative means big falls are more common than big rises.", f"{core} skew()"),
        ("CAGR without the 10 best days", "Remove the 10 best days, then compound; years run from the first return date", "Whether a handful of days made the result.", f"{core} cagr_without_best_days()"),
        ("Beta", "Cov(r − c, b − c) ÷ Var(b − c)", "1.0 moves in line with the index. Below 1 is less sensitive.", f"{core} beta()"),
        ("Up-market / down-market beta", "Beta using only days the index rose / fell", "Ideally high in rises and low in falls. The two do not average to the overall beta.", f"{core} beta_on(); {ch} build(), beta_split"),
        ("Beta with the index filter open / shut", "Beta using only days the card's index filter was open / shut. The filter's state on a day is read at the previous session's close",
         "Shown when the card has an index filter. A low beta when shut is the filter holding cash.", f"{ch} _filter_betas()"),
        ("Tracking error", "stdev(r − b) × √252", "How far it strays from the index. Used inside the information ratio.", f"{core} tracking_error()"),
        ("Information ratio", "mean(r − b) × 252 ÷ tracking error", "Return over the index per unit of straying. Higher is better.", f"{core} information_ratio()"),
        ("Up / down capture (monthly)", "mean monthly return ÷ the benchmark's, in months the benchmark rose / fell", "Above 1 up and below 1 down is the good shape.", f"{core} up_capture(), down_capture()"),
        ("Rolling one-year periods behind", "Share of 252-day windows with compounded return below the index's", "How often an investor would have been trailing.", f"{core} rolling_periods_behind()"),
        ("Deflated Sharpe", "See Part 3", "Probability of skill after allowing for versions tried. Outside the gate.", "")], W3))
    A('<h2 id="1.4">1.4 Costs and execution table</h2>' + table("1.4", ["Metric", "Formula", "How to read it"], [
        ("Two-way turnover a year", "Σ |weight after − weight before| over every trade, ÷ years", "1.0 means trading the whole portfolio's value once a year.", f"{core} two_way_turnover_from_trades(), annual_turnover()"),
        ("CAGR at another cost", "Same book, re-simulated at that round-trip cost", "An appendix sweep. The headline is at the cost on the card.", scr + "; config/costs.yaml sweep"),
        ("Edge at a high cost", "CAGR at that cost − CAGR<sub>benchmark</sub>", "What survives expensive trading.", scr),
        ("Capacity per Rs 1 crore", f"For each trade: (its share of capital × Rs 1 crore) ÷ the stock's 20-day average traded value. The 95th percentile P is shown, and the capital at which it reaches the limit: {pc(TH['capacity']['p95_adv_participation_max'])} ÷ P",
         "Information only. No fund size is assumed, and the limit is a placeholder.", f"{core} capacity_unit(), adv_20(); config/gate_thresholds.yaml capacity"),
        ("Fills; resize fills", "Count of trades; count that only resized", "How busy the book is.", scr),
        ("Names held, mean", "mean(stocks held per rebalance)", "Too few means the result rests on few companies.", scr),
        ("Rebalances with few names", "Count with fewer than 5 names, overall and while buying was open", "Separates a filter holding cash from a universe running dry.", scr),
        ("Signals fully in cash; with few eligible", "Counts of signals", "How often filters left nothing or little to buy.", scr),
        ("Names bought at first fill", "Count of positions opened on day one", "How the book starts.", scr),
        ("Largest weight; weights above 25%", "max(single weight); count of rebalances above 25%", "Concentration risk.", scr),
        ("Different stocks held", "Count of distinct names", "Higher means more breadth.", scr),
        ("Top-2 share of gains", "Gains of two best names ÷ gains of all winners", "High means a couple of stocks made the result.", scr),
        ("Mean / max cash share", "mean / max(cash ÷ NAV)", "How invested the book really was.", scr),
        ("Signals with buying shut", "Signals with the market filter closed ÷ all signals", "How often the market filter stopped new buys.", scr),
        ("Median holding period", "Median calendar days, entry to exit", "How long a position typically lasts.", scr),
        ("Names removed by a rule", "mean(top-band names rejected per signal)", "How hard a filter bites.", scr),
        ("Rule exits", "Count of sells forced by each rule, and their mean return since entry", "Whether a rule mostly cuts losers or winners.", scr),
        ("Buys on big up days", "Count of buys after a close up more than 9.5%", "Proxy for buying at a price band, where a real fill may fail.", scr),
        ("Sells on leaving the index", "Count, and mean return since entry", "What index exits cost or earned.", scr),
        ("Small-cap share", "mean(NAV share in Smallcap 250 names)", "How much of the result is a small-cap bet.", scr)], [24, 40, 36]))
    A('<h2 id="1.5">1.5 Statistical robustness table</h2><p>These feed or support the Gate B tests in Part 3, where the methods are explained. Every Sharpe here is arithmetic.</p>'
      + table("1.5", ["Metric", "Formula", "How to read it"], [
          ("Bootstrap Sharpe 95% range", "2.5th and 97.5th percentile of Sharpe across the draws", "A range that includes low values means the Sharpe is uncertain.", "ros/validation/research.py stationary_bootstrap()"),
          ("Paired P, each comparator", "Share of draws where strategy Sharpe − comparator Sharpe ≤ 0", "Small means the edge is hard to explain by chance. Test 4.", "ros/validation/research.py stationary_bootstrap()"),
          ("Paired P at a fixed block", "The same P with the mean block fixed at 5, 21 and 63 days", "A check that the answer does not hang on the block length. Reported, not judged.", "ros/validation/gate_evidence.py paired_bootstrap(), sensitivity"),
          ("Factor alpha a year", "(1 + α)<sup>252</sup> − 1", "Return left after known factors. Test 6.", "ros/validation/portfolio.py factor_fingerprint()"),
          ("Alpha t-stat (HAC)", "α ÷ HAC standard error of α", "How sure we are alpha is not zero. Test 6.", "ros/validation/portfolio.py factor_fingerprint()"),
          ("Factor alpha over the risk-free rate", "The same regression with returns above Rf instead of c", "Shown beside the gate's figure. Reported, not judged.", "lightyear/gate_run.py score(); " + scr),
          ("Factor loadings", "β<sub>k</sub> in the factor regression", "How much of each factor it behaves like.", "ros/validation/portfolio.py factor_fingerprint()"),
          ("Factor R-squared", "Share of variance the factors explain", "High means mostly known factors.", "ros/validation/portfolio.py factor_fingerprint()"),
          ("Alpha with a factor left out; on a variant", "The same regression, one factor removed or on a variant book", "Shows how much one factor or rule was accounting for.", "ros/validation/gate_evidence.py factor_alpha(), leave_one_out"),
          ("CAGR after one rule change", "Re-simulate with one rule changed", "A real effect keeps its sign when a rule moves.", scr),
          ("CAGR with cash at another rate", "Re-simulate with idle cash earning that rate", "An appendix sweep: how much the cash rate contributes.", scr + "; config/fund.yaml cash_rate_sweep")], W3))
    A('<h2 id="1.6">1.6 Run facts table</h2><p>These are counts and dates that show what the test covered. They are not performance metrics.</p>'
      + table("1.6", ["Row", "What it counts"], [
          ("Checks passed", "Look-ahead and accounting checks that passed, out of those run.", ""),
          ("Signals; trading days; first and last dates", "How many decisions and days the run covers, and where it starts and stops.", ""),
          ("Universe source; members; members priced; never priced", "Which index list was used, and how many members could actually be traded. Never-priced members are a remaining survivorship risk.", ""),
          ("Price moves that coincide with an adjustment change", "Whether a price rule is tripped by splits and bonuses rather than real shocks.", ""),
          ("Versions tried", "N for the deflated Sharpe: versions from the paper, earlier runs and studies, plus this run's sensitivities.", "")], [40, 60]))

    # ------------------------------------------------------------ Part 2
    A('<h1 class="brk" id="p2">Part 2. SE Return Analytics (monthly)</h1>')
    A(f'<div class="warn"><p><b>A separate block, on monthly returns.</b> It is on the Results tab and in the workbook sheet "SE Return Analytics". Every figure uses calendar-month '
      f'returns m compounded from the daily returns, the population standard deviation, and three inputs: risk-free rate {RF}, Omega threshold {pc(om)} a month, drawdown limit {pc(dl)}. '
      'Do not compare a figure here with a daily figure of the same name in Part 1. Gate B uses none of them. The benchmark is the price index.</p>'
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

    # ------------------------------------------------------------ Part 3
    n_f = len(INVESTABLE_FACTORS)
    A(f'<h1 class="brk" id="p3">Part 3. The Gate B {GATE_VERSION} tests</h1>')
    A('<h2 id="3.1">3.1 What a strategy must pass</h2><p>Each test rules out one way a backtest can fool you. The pass marks are fixed in config before the run, so nobody can move '
      "the bar after seeing the answer. Every test reads the run's daily returns at the cost on its approved card. <b>Hard blocks</b> decide the status. <b>Scorecard</b> rows "
      "are shown green, amber or red and do not block.</p>")
    cols5 = ['<col style="width:4%"><col style="width:30%"><col style="width:27%"><col style="width:25%"><col style="width:14%">']
    gate_rows = [
        (1, "Implementable within the fund's mandate", "Rule check on actual positions", "No breach", "Hard block"),
        (2, "Data integrity", "Checks, card rules, priced coverage", f"All pass; coverage ≥ {pc(di['min_priced_coverage'])}", "Hard block"),
        (3, "Edge over the benchmark", "CAGR gap", "&gt; 0", "Hard block"),
        (4, "Advantage over benchmark is significant", "Paired stationary bootstrap", f"P ≤ {bt['p_max']}", "Hard block"),
        (5, "Sub-period stability", "Sharpe gap in 4 windows", f"≥ {pc(sp['min_windows_ahead_share'])} of windows ahead; none below {sp['window_floor']}", "Scorecard"),
        (6, "Alpha survives the factor regression", "Regression t-test with HAC errors", f"α &gt; 0 and t ≥ {fa['t_green_min']}", "Scorecard"),
        (7, "Performance after publication", "Edge after the paper's date", f"Edge &gt; {pc(pp['edge_green_min'])}", "Scorecard")]
    A("<table><colgroup>" + cols5[0] + "</colgroup><thead><tr><th>#</th><th>Test</th><th>Method</th><th>Pass mark</th><th>Counts as</th></tr></thead><tbody>"
      + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in gate_rows) + "</tbody></table>")
    CHECKS.append(("3.1", "Status: FAIL if any hard block failed, or if the edge test or the bootstrap did not run and pass; otherwise PASS", "ros/governance/gate_v2.py evaluate()"))
    CHECKS.append(("3.1", "Pass marks in the table", "config/gate_thresholds.yaml (bootstrap.p_max, sub_period, factor_alpha, post_publication, data_integrity)"))
    A('<div class="note"><p><b>Status is PASS or FAIL.</b> It is PASS when no hard block failed and tests 3 and 4 both ran and passed. The scorecard informs the reader and never '
      'blocks. <b>"Not run"</b> means a test had nothing to run on, for example no mandate limits on file. It is not a pass, it is listed beside the status, and it does not hold '
      'the gate up.</p><p><b>Tests 3, 4 and 6 are the statistical tests.</b> Test 5 is a stability test, test 7 asks whether the edge outlived publication, and tests 1 and 2 '
      'are practical checks. The deflated Sharpe (3.9) is outside the gate, so the gate does not test for selection luck.</p></div>')
    A('<p>Lightyear reads each row as PASS, FAIL, green, amber, red or not run. <b>"Evidence supports" on the Gate B tab is written by Claude, not calculated</b>, and the '
      "decision stays PENDING until a named person records it.</p>")
    A(test("3.2", "Test 1: implementable within mandate", "Could the fund actually hold these positions?", "", "Breach if the largest cash share or the largest single weight exceeds its "
           "limit, or any weight is negative under a long-only mandate", "ros/governance/gate_v2.py mandate_row(); lightyear/gate_run.py _positions(); config/mandate.yaml",
           "A rule check on the positions actually held, not the settings: the largest cash share, the largest single weight and the lowest weight, against the fund's limits. A "
           "card cannot change the limits; an override needs a named person and a time, and is shown.", "no breach.", "each breach is listed.",
           "the limits file must hold all three limits. If any is blank the row shows not run, which is not a pass."))
    A(test("3.3", "Test 2: data integrity", "Can the numbers be trusted before any statistic is read?",
           mt("Coverage") + mo("=") + frac("<mo>∑</mo>" + mt("priced members × sessions"), "<mo>∑</mo>" + mt("all members × sessions")),
           "Coverage = Σ(priced members × sessions) / Σ(all members × sessions); pass also needs every check passed and no card rule broken",
           "lightyear/gate_run.py _coverage(), _checks(); ros/governance/gate_v2.py integrity_row()",
           "Three things from the run's own files: every look-ahead and accounting check the run wrote passed; Lightyear's audit of the card's rules found none broken; and enough "
           "index members had a price.", f"all checks pass, no rule broken, coverage ≥ {pc(di['min_priced_coverage'])}.",
           "the result rests on a broken check, a rule the run did not follow, or too many members with no price.",
           "members never priced are a survivorship risk even above the mark. They are named in the evidence."))
    A(test("3.4", "Test 3: edge over the benchmark", "Did it beat the index at all?",
           mt("Edge") + mo("=") + sub(mt("CAGR"), mt("strategy")) + mo("−") + sub(mt("CAGR"), mt("benchmark")),
           "Edge = CAGR_strategy − CAGR_benchmark, both from the same base date", "lightyear/gate_run.py score() net_edge; ros/metrics/core.py cagr_from_returns()",
           "Both CAGRs over the same days, at the cost on the card.", "edge &gt; 0.", "the strategy did not beat the index it is measured against.",
           "on a card set to zero cost this is before any trading cost, so read the turnover and the cost sweep. The benchmark is a price index, which flatters the edge."))
    A('<h3 id="3.5">3.5 Test 4: paired stationary bootstrap</h3><p><b>The question.</b> We cannot re-run history. If we rebuild alternative histories from the real one, how often '
      "does the edge over the benchmark disappear? (Politis and Romano, 1994.)</p>" + bootstrap_svg()
      + "<ul><li><b>Build:</b> pick a random start day and take a block of days, with random lengths, until the history is full length. Blocks keep calm and stormy spells together. "
      "The average block length is chosen from the data (Politis and White, 2004), as the largest of the lengths for the strategy, the benchmark and their difference.</li>"
      "<li><b>Pair:</b> cut the strategy and the benchmark at the same days, which preserves their correlation.</li>"
      f"<li><b>Score:</b> calculate each arithmetic Sharpe, mean(r − Rf) ÷ stdev(r − Rf) × √252 with Rf at {RF}, on that history, and take the gap D.</li>"
      "<li><b>Repeat</b> 2,000 times with fixed seed 7, so the result can be reproduced.</li></ul>"
      + M(mi("D") + mo("=") + sub(mt("Sharpe"), mt("strategy")) + mo("−") + sub(mt("Sharpe"), mt("benchmark")) + "<mspace width='3em'/>" + mi("P") + mo("=")
          + frac(mt("number of draws with ") + mi("D") + mo("≤") + mn(0), mt("number of draws")))
      + f"<p><b>Pass:</b> P ≤ {bt['p_max']}. <b>If it fails:</b> the gap over the index could be noise. <b>Watch out:</b> P is a share of re-shuffled histories, not the chance the "
      "strategy has no edge. Values just either side of the mark are nearly the same evidence. It looks at Sharpe only, so a shallower drawdown does not help. P at fixed blocks "
      "of 5, 21 and 63 days is shown beside it and is not judged.</p>")
    CHECKS.append(("3.5", "D = Sharpe_strategy − Sharpe_benchmark (arithmetic, over Rf); P = draws with D ≤ 0 / draws; 2,000 draws, seed 7, automatic block",
                   "ros/validation/gate_evidence.py paired_bootstrap(); ros/metrics/core.py stationary_bootstrap_indices(), sharpe_draws(), politis_white_block(), auto_mean_block(); lightyear/gate_run.py score()"))
    A(test("3.6", "Test 5: sub-period stability", "Did it work in every stretch, or did one period make all the profit?",
           sub(mt("Gap"), mi("w")) + mo("=") + sub(mt("Sharpe"), mt("strategy, ") + mi("w")) + mo("−") + sub(mt("Sharpe"), mt("benchmark, ") + mi("w")),
           "Gap_w = arithmetic Sharpe of the strategy − of the benchmark in window w; 4 windows; windows under 60 days dropped; 5-year skip only if the card fits parameters",
           "ros/validation/gate_evidence.py sub_period(), windows(); ros/metrics/core.py split_windows(); ros/governance/gate_v2.py evaluate()",
           f"Split the run into 4 equal windows that do not overlap, and take the arithmetic Sharpe gap to the benchmark in each, with Rf at {RF}. Windows under 60 days are dropped. "
           "If the card says the rules fit parameters to data, the first 5 years are skipped and the test is a walk-forward.",
           f"green when at least {pc(sp['min_windows_ahead_share'])} of windows have a gap above 0 and no gap is below {sp['window_floor']}; amber while the worst gap is at least "
           f"{sp['window_floor_amber']}; otherwise red.", "the edge depends on when you measured it.",
           "it is judged against the benchmark, so a weak market does not fail it. If the rules fit no parameters, these are sub-periods, not out-of-sample tests."))
    A(test("3.7", "Test 6: factor regression", "Once you remove what known factors explain, is any return left? If not, you are paying for research to get exposure you can buy off the shelf.",
           mi("r") + mo("−") + mi("c") + mo("=") + mi("α") + mo("+") + "<munder><mo>∑</mo><mi>k</mi></munder>" + sub(mi("β"), mi("k")) + mo("(") + sub(mi("f"), mi("k")) + mo("−") + mi("c") + mo(")")
           + mo("+") + mi("ε") + "<mspace width='2.5em'/>" + mi("t") + mo("=") + frac(mi("α"), sub(mt("SE"), mt("HAC")) + mo("(") + mi("α") + mo(")")) + "<mspace width='2.5em'/>"
           + mt("lags") + mo("=") + mo("⌈") + mn(4) + sup(mo("(") + frac(mi("n"), mn(100)) + mo(")"), "<mn>2</mn><mo>/</mo><mn>9</mn>") + mo("⌉"),
           f"r − c = α + Σ β_k (f_k − c) + ε on {n_f} factors; t = α / SE_HAC(α); lags = ceil(4 (n/100)^(2/9)); one-sided: green needs α > 0 and t ≥ mark",
           "ros/validation/portfolio.py factor_fingerprint(); ros/validation/gate_evidence.py factor_alpha(), INVESTABLE_FACTORS; ros/governance/gate_v2.py evaluate() one_sided",
           f"Regress daily strategy returns on {n_f} factor index returns, all above the card's cash rate: " + ", ".join(INVESTABLE_FACTORS.values()) + ". α is the unexplained return and "
           "β<sub>k</sub> the loading on factor k. The t-stat is α divided by its uncertainty. HAC (Newey and West, 1987) is a safer standard error, since daily returns depend on "
           "each other and volatility clusters. The lag formula sets how many days of dependence it allows.",
           f"green when α &gt; 0 and t ≥ {fa['t_green_min']}; amber from t ≥ {fa['t_amber_min']}; otherwise red. The mark is one-sided: a negative alpha cannot be green.",
           "no reliable return is left after known factors.",
           "a factor left out of the regression can make alpha look larger, and the factor indices are backfilled and price-only. The test subtracts the card's cash rate, not the risk-free rate."))
    A(test("3.8", "Test 7: performance after publication", "Did the edge survive once the idea was public?",
           sub(mt("Edge"), mt("after")) + mo("=") + sub(mt("CAGR"), mt("strategy")) + mo("−") + sub(mt("CAGR"), mt("benchmark")) + mt(" , from the publication date"),
           "Edge_after = CAGR_strategy − CAGR_benchmark from the paper's publication date; a bare year means 31 December; needs 252 days",
           "ros/metrics/core.py post_publication(), publication_cutoff(); ros/governance/gate_v2.py evaluate()",
           "The same edge as test 3, from the paper's publication date onward. A date given only as a year is read as 31 December of that year. It needs at least 252 trading days "
           "after that date; with fewer the row is not run.", f"green when the edge is above {pc(pp['edge_green_min'])}; amber above {pc(pp['edge_amber_min'])}; otherwise red.",
           "the result leaned on the years before anyone could have read the paper.", "a short stretch after publication is weak evidence either way."))
    A('<h3 id="3.9">3.9 Outside the gate: deflated Sharpe</h3><p><b>The question.</b> Try enough versions of a strategy and one will look good by luck. Is this Sharpe higher than the '
      "best you would expect from that many versions with no skill, given how noisy and fat-tailed the returns are? (Bailey and López de Prado, 2014.) It is shown with each run "
      "and does not affect the status.</p><p class='ft'><b>Step 1. How high is the luck bar?</b></p>"
      + M(sub(mt("SR"), mn(0)) + mo("=") + "<msqrt><mi>V</mi></msqrt>" + mo("×") + mo("[") + mo("(") + mn(1) + mo("−") + mi("γ") + mo(")") + sup(mi("Φ"), "<mo>−</mo><mn>1</mn>") + mo("(") + mn(1) + mo("−")
          + frac(mn(1), mi("N")) + mo(")") + mo("+") + mi("γ") + sup(mi("Φ"), "<mo>−</mo><mn>1</mn>") + mo("(") + mn(1) + mo("−") + frac(mn(1), mi("N") + mi("e")) + mo(")") + mo("]"))
      + luck_bar_svg() + "<p class='ft'><b>Step 2. How likely is it that the true Sharpe clears that bar?</b></p>"
      + M(mt("P(skill)") + mo("=") + mi("Φ") + mo("(") + frac(mo("(") + mt("SR") + mo("−") + sub(mt("SR"), mn(0)) + mo(")") + "<msqrt><mi>n</mi><mo>−</mo><mn>1</mn></msqrt>",
                                                             "<msqrt><mn>1</mn><mo>−</mo><mi>S</mi><mo>·</mo><mtext>SR</mtext><mo>+</mo>" + frac(mi("K") + mo("−") + mn(1), mn(4))
                                                             + "<mo>·</mo>" + sup(mt("SR"), mn(2)) + "</msqrt>") + mo(")")))
    CHECKS.append(("3.9", "SR0 = √V × [(1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))]", "ros/validation/research.py expected_max_sharpe(); the chart is drawn from this function"))
    CHECKS.append(("3.9", "P(skill) = Φ((SR − SR0) √(n − 1) / √(1 − S·SR + (K − 1)/4 · SR²)), SR per day", "ros/validation/research.py deflated_sharpe()"))
    A(table("3.9", ["Input", "Meaning"], [
        ("N", "Strategy versions tried: the versions the paper reports, every distinct version run before, earlier studies on the trial ledger, plus this run's sensitivities. "
              "<b>This is a count of versions, not of tests.</b> A re-run that changes no trade is not a new version.", "ros/validation/trials.py count()"),
        ("V", "Variance of the versions' yearly Sharpes. The bar scales with √V, so the result is very sensitive to it. Two answers are shown: V = 1, the default, which sets a high "
              "bar, and V measured on this run's variants, which sets a very low one.", scr),
        ("SR, SR<sub>0</sub>", f"Observed Sharpe (arithmetic, over the risk-free rate of {RF}) and the luck bar, both per day (÷ √252).", ""),
        ("n", "Number of daily returns. More history means more certainty.", ""),
        ("S, K", "Skew and kurtosis, where a bell curve has K = 3. Negative skew and fat tails make a given Sharpe less certain.", ""),
        ("Φ, Φ<sup>−1</sup>; γ, e", "The bell-curve probability function and its inverse; the constants 0.5772 and 2.718.", "")], [14, 86]))
    A("<p><b>Why it is outside the gate.</b> With V = 1 it fails almost everything; with V measured on near-identical variants it passes almost everything. Until V is settled it "
      "is reported for the reader and does not decide the status. <b>Watch out:</b> versions are rarely independent, which overstates the penalty.</p>")
    A('<div class="note"><p><b>Not part of Gate B.</b> The monthly block in Part 2, and the capacity figure in 1.4, are information only. run_pipeline.py also has a promotion '
      "ladder that reuses some of these statistics at different bars. Lightyear does not use the ladder.</p></div>")
    A('<p class="src">Sources: ros/metrics/core.py, ros/metrics/se.py, lightyear/charts.py, lightyear/gate_run.py, lightyear/workbook.py, lightyear/se_sheet.py, '
      "ros/governance/gate_v2.py, ros/validation/gate_evidence.py, research.py, portfolio.py, trials.py, config/fund.yaml, config/gate_thresholds.yaml, config/mandate.yaml. "
      "Bailey and López de Prado (2014), <i>Journal of Portfolio Management</i> 40(5). Politis and Romano (1994), <i>JASA</i> 89(428). Politis and White (2004), "
      "<i>Econometric Reviews</i> 23(1). Newey and West (1987), <i>Econometrica</i> 55(3).</p>")
    return "\n".join(h)


TOC = [("p1", "Part 1. On the Lightyear dashboard", 0), ("1.1", "1.1 The five headline numbers", 1), ("1.2", "1.2 The charts", 1), ("1.3", "1.3 Returns and risk table", 1),
       ("1.4", "1.4 Costs and execution table", 1), ("1.5", "1.5 Statistical robustness table", 1), ("1.6", "1.6 Run facts table", 1),
       ("p2", "Part 2. SE Return Analytics (monthly)", 0), ("2.1", "2.1 Performance", 1), ("2.2", "2.2 Risk Parameters", 1), ("2.3", "2.3 Performance Vs Index", 1),
       ("2.4", "2.4 Capture Ratio", 1), ("2.5", "2.5 Extreme Capture Ratio", 1), ("2.6", "2.6 Tail Risk", 1), ("2.7", "2.7 Period tables", 1),
       ("p3", f"Part 3. The Gate B {GATE_VERSION} tests", 0), ("3.1", "3.1 What a strategy must pass", 1), ("3.2", "3.2 Test 1: implementable within mandate", 1),
       ("3.3", "3.3 Test 2: data integrity", 1), ("3.4", "3.4 Test 3: edge over the benchmark", 1), ("3.5", "3.5 Test 4: paired stationary bootstrap", 1),
       ("3.6", "3.6 Test 5: sub-period stability", 1), ("3.7", "3.7 Test 6: factor regression", 1), ("3.8", "3.8 Test 7: performance after publication", 1),
       ("3.9", "3.9 Outside the gate: deflated Sharpe", 1)]

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
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Financial metrics and Gate B tests</title><style>{CSS}</style></head><body>"
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
