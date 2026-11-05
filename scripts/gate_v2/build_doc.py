# Quant AI Researcher by Harshil Pahuja
"""Build docs/gate_b/financial-metrics-and-gate-b-v2.pdf: one formula per metric, the gate, its calibration, and what changed.

A reference: no strategy's results. Thresholds come from config/gate_thresholds.yaml and rates from the calibration tables.

    python scripts/gate_v2/build_doc.py
"""
from __future__ import annotations

import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yaml
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    Image,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAL = os.path.join(REPO, "docs", "gate_b", "calibration")
OUT = os.path.join(REPO, "docs", "gate_b", "financial-metrics-and-gate-b-v2.pdf")
SIGN = "Quant AI Researcher by Harshil Pahuja"
sys.path.insert(0, REPO)
from ros.versions import GATE_VERSION, METRICS_VERSION

F = "C:/Windows/Fonts/"
for nm, fl in (("A", "arial.ttf"), ("AB", "arialbd.ttf"), ("AI", "ariali.ttf")):
    pdfmetrics.registerFont(TTFont(nm, F + fl))
pdfmetrics.registerFontFamily("A", normal="A", bold="AB", italic="AI", boldItalic="AB")
NAVY, INK, MUTED = colors.HexColor("#1f4e79"), colors.HexColor("#1b2430"), colors.HexColor("#5d6b7c")
LINE, SOFT, WARN = colors.HexColor("#dfe4ea"), colors.HexColor("#eef3f8"), colors.HexColor("#fff3d6")
S = {"body": ParagraphStyle("body", fontName="A", fontSize=9.7, leading=14, textColor=INK, spaceAfter=6),
     "small": ParagraphStyle("small", fontName="A", fontSize=8, leading=11, textColor=MUTED, spaceAfter=4),
     "cell": ParagraphStyle("cell", fontName="A", fontSize=8.3, leading=11.2, textColor=INK),
     "cellb": ParagraphStyle("cellb", fontName="AB", fontSize=8.3, leading=11.2, textColor=INK),
     "th": ParagraphStyle("th", fontName="AB", fontSize=8.2, leading=10.5, textColor=NAVY),
     "H1": ParagraphStyle("H1", fontName="AB", fontSize=16, leading=20, textColor=NAVY, spaceBefore=6, spaceAfter=6, keepWithNext=1),
     "H2": ParagraphStyle("H2", fontName="AB", fontSize=12, leading=15, textColor=NAVY, spaceBefore=9, spaceAfter=4, keepWithNext=1),
     "title": ParagraphStyle("title", fontName="AB", fontSize=22, leading=27, textColor=NAVY, spaceAfter=4),
     "sub": ParagraphStyle("sub", fontName="A", fontSize=11, leading=15, textColor=MUTED, spaceAfter=9)}
W = A4[0] - 100


def P(t, s="body"):
    return Paragraph(t, S[s])


def TBL(data, widths, boldfirst=True):
    out = [[Paragraph(str(c), S["th" if i == 0 else ("cellb" if boldfirst and j == 0 else "cell")]) for j, c in enumerate(r)] for i, r in enumerate(data)]
    t = Table(out, colWidths=[w * W for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY)]))
    t.spaceAfter = 7
    return t


def BOX(flow, bg=SOFT):
    t = Table([[flow]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 2.6, NAVY if bg == SOFT else colors.HexColor("#d9a400")), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return KeepTogether([t, Spacer(1, 8)])


def footer(c, d):
    c.saveState()
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(50, 38, A4[0] - 50, 38)
    c.setFont("A", 7.6)
    c.setFillColor(MUTED)
    c.drawString(50, 27, SIGN)
    c.drawRightString(A4[0] - 50, 27, f"Page {d.page}")
    c.restoreState()


def main() -> int:
    with open(os.path.join(REPO, "config", "gate_thresholds.yaml"), encoding="utf-8") as fh:
        th = yaml.safe_load(fh)
    t = pd.read_csv(os.path.join(CAL, "power_table_approved.csv"))

    def rate(gate, test, case):
        return float(t[(t.gate == gate) & (t.test == test) & (t.case == case)].pass_rate.iloc[0])

    def pc(x):
        return f"{x * 100:.1f}%"

    levels = ["level 0", "level 0.25", "level 0.5", "level 0.75", "level 1"]
    X = [0, 0.25, 0.5, 0.75, 1.0]
    plt.rcParams.update({"font.family": "Arial", "font.size": 8.5, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#9aa5b1", "axes.linewidth": 0.6, "xtick.color": "#5d6b7c",
                         "ytick.color": "#5d6b7c", "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#eef1f4", "axes.titlesize": 9, "axes.titleweight": "bold", "axes.titlelocation": "left"})
    fig, ax = plt.subplots(figsize=(7.2, 2.7))
    for label, gate, test, col, mk, off in (("Gate v2: hard blocks and a green scorecard", "v2", "PASS and green, no book", "#2166ac", "o", (0, 7)), ("Gate v1, N = 1", "v1", "OVERALL, N = 1", "#c8660c", "s", (0, -13)), ("Gate v1, N = 13", "v1", "OVERALL, N = 13", "#1b8a6b", "^", (0, 7))):
        y = [rate(gate, test, c) for c in levels]
        ax.plot(X, y, color=col, lw=2, marker=mk, ms=6, label=label, markeredgecolor="white", markeredgewidth=1.2)
        ax.annotate(f"{y[-1]:.0%}", (1.0, y[-1]), textcoords="offset points", xytext=off, ha="center", fontsize=8)
    ax.axhline(0.7, color="#5d6b7c", lw=0.7, ls="--")
    ax.set(ylim=(-0.03, 1.08), xlim=(-0.04, 1.06), xlabel="True excess Sharpe (information ratio against the benchmark)", ylabel="Share passing")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xticks(X)
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    ax.set_title("How often a strategy passes, by how good it really is. Dashed line: the 70% target")
    fig.tight_layout()
    png = os.path.join(CAL, "power_approved.png")
    fig.savefig(png, dpi=240, facecolor="white")
    plt.close(fig)
    w, h = PILImage.open(png).size

    bp, sp, fa, bk = th["bootstrap"], th["sub_period"], th["factor_alpha"], th["book"]
    order = levels + ["pure factor", "best of 20", "best of 100"]
    table = [["Gate", "True Sharpe 0", "0.25", "0.5", "0.75", "1.0", "Factor only", "Best of 20", "Best of 100"]]
    for lab, g, tst in (("v1, N = 1", "v1", "OVERALL, N = 1"), ("v1, N = 13", "v1", "OVERALL, N = 13"), ("v2 status PASS (hard blocks)", "v2", "STATUS PASS, hard blocks"), ("<b>v2 PASS and all green</b>", "v2", "PASS and green, no book")):
        table.append([lab] + [pc(rate(g, tst, c)) for c in order])

    E = [P("Financial metrics and Gate B tests", "title"),
         P(f"Version 2. metrics_version {METRICS_VERSION}, gate_version {GATE_VERSION}. One formula per metric, the gate, its calibration, and what changed from v1.", "sub"),
         BOX([P("<b>Notation.</b> r, b and c are one day's return on the strategy, the benchmark and cash. mean and stdev are the average and sample standard deviation. The benchmark is the NIFTY 500 price index, with no dividends, which flatters every relative figure. Cash is the card's rate, or the rate in config/fund.yaml if the card names none. All code is in ros/metrics/core.py.", "body")]),
         P("Part 1. The metrics", "H1"), P("Shown on every run, in the Core performance table on the Results tab and the Core metrics sheet in Excel.", "body"),
         TBL([["Metric", "Formula", "How to read it"],
              ["CAGR", "(V<sub>end</sub> / V<sub>start</sub>)<super>1/years</super> - 1, on calendar days / 365.25", "Steady yearly growth rate"],
              ["Volatility", "stdev(r) x sqrt(252)", "Lower is smoother"],
              ["Sharpe", "mean(r - c) / stdev(r - c) x sqrt(252)", "Return above cash per unit of risk. <b>The only Sharpe</b>"],
              ["Sortino", "mean(r - c) x 252 / (sqrt(mean(min(r - c, 0)<super>2</super>)) x sqrt(252))", "As Sharpe, counting only falls as risk"],
              ["Calmar", "CAGR / max drawdown", "Return per unit of worst fall"],
              ["Max drawdown", "max(1 - V<sub>t</sub> / highest V so far), daily, positive", "Worst fall from a high"],
              ["Drawdown duration", "Longest stretch below a previous high, in trading days", "Longest wait to recover"],
              ["95% CVaR", "-mean(r on days at or below its 5th percentile)", "Average loss on the worst days, positive"],
              ["Skew", "Sample skew of r", "Negative: big falls outnumber big rises"],
              ["CAGR without best days", "CAGR after removing the 10 best days, same span", "Did a few days make the result?"],
              ["Beta", "Cov(r - c, b - c) / Var(b - c)", "Sensitivity to the index"],
              ["Tracking error", "stdev(r - b) x sqrt(252)", "How far it strays from the index"],
              ["Information ratio", "mean(r - b) x 252 / tracking error", "Return over the index per unit of straying"],
              ["Up / down capture", "mean monthly r / mean monthly b, in months b rose / fell", "Want high up, low down"],
              ["Rolling periods behind", "Share of rolling 252-day periods with compounded r below b", "How often an investor trailed"]], [0.2, 0.47, 0.33]),
         P("Costs, capacity and timing", "H2"),
         TBL([["Metric", "Formula", "How to read it"],
              ["Net of the house cost", "r - two-way turnover x (house bp - charged bp) / 2 / 10,000", "House cost in config/costs.yaml. A round trip is one buy and one sell, so each unit of two-way turnover pays half. Shown beside gross"],
              ["Two-way turnover", "Sum of |change in weight| per trade, / years", "1.0 means trading capital once a year"],
              ["Capacity", "|change in weight| x AUM / average traded value of the 20 sessions before the trade", "Median, 95th percentile, maximum and names over the limit. Needs AUM"],
              ["Post-publication", "The same metrics from the paper's date onward. A bare year means its end", "Did it survive being published?"],
              ["Period returns", "Compounded r by calendar year, financial year (April to March), month, sub-period", "Where the return came from"]], [0.2, 0.47, 0.33]),
         P("Strategy-specific rows go in a separate Diagnostics section. Each run can add its own further rows to the tables at the bottom of the Results tab, so those still differ by run. Kurtosis is kept only as an input to the deflated Sharpe, which stays in the code.", "small"),
         P("Calculated elsewhere", "H2"),
         P("The Excel tearsheet (universal_backtester/excel_tearsheet.py and tearsheet.py) stays, because the Excel calculation is still needed. It holds Sterling, Treynor, Omega, Gain to Pain, tail ratio, Jensen's alpha, extreme capture and the rest. It is <b>not</b> part of the one-definition rule: it uses monthly returns and its own rates, so its Sharpe will not match the dashboard's. A geometric Sharpe survives in ros/metrics/legacy_v1.py only to compare with a paper's printed figure."),
         CondPageBreak(260), P("Part 2. Gate B v2", "H1"),
         P("<b>Status is PASS or FAIL. The decision stays PENDING until a named person records one.</b> Every hard block that can be run must pass, and net edge and the bootstrap can always be run. A test with nothing to run on, such as no book, AUM or mandate limits, shows as <b>not run</b>: it is not a pass, it is listed beside the status, and it does not hold the gate up. Every number is net of the house cost. \"Evidence supports\" remains Claude's written read."),
         P("Hard blocks", "H2"),
         TBL([["Test", "Measure", "Pass mark", "Status now"],
              ["Mandate", "Actual positions against config/mandate.yaml. A card cannot override it; an override needs a named approval with a timestamp", "No breaches", "Not run: no limits supplied"],
              ["Capacity", "95th percentile of trade size / 20-day traded value at the fund's AUM", f"&le; {th['capacity']['p95_adv_participation_max']:.0%}", "Not run: no AUM supplied"],
              ["Data integrity", "Look-ahead checks, the audit of rules, and share of index members with a price. Unpriced names are listed", f"All pass, coverage &ge; {th['data_integrity']['min_priced_coverage']:.0%}", "Runs when the run's files have them"],
              ["Net edge", "CAGR net of the house cost - benchmark CAGR", "&gt; 0", "Always runs"],
              ["Paired bootstrap", "Share of 2,000 draws (mean block 21, seed 7) with Sharpe<sub>net</sub> - Sharpe<sub>benchmark</sub> &le; 0", f"P &le; {bp['p_max']:.2f}", "Always runs"]], [0.15, 0.5, 0.17, 0.18]),
         P("Evidence scorecard: green, amber or red", "H2"),
         TBL([["Test", "Measure", "Green"],
              ["Sub-period stability", "Sharpe gap to the benchmark in 4 equal windows. Called a walk-forward only if the card says the rules fit parameters, and then it skips the first 5 years", f"At least {sp['min_windows_ahead_share']:.0%} of windows ahead, none below {sp['window_floor']:.2f}"],
              ["Factor alpha", "Regress r - c on market, Midcap 150, Smallcap 250, momentum, value, quality and low-vol, with HAC errors. t = alpha / its standard error. Each factor is also left out in turn", f"Alpha &gt; 0 and t &ge; {fa['t_green_min']:.1f}. One-sided: negative alpha can never go green"],
              ["Book correlation", "Largest correlation to the existing book, when a book file is supplied", f"&le; {bk['corr_green_max']:.2f}"],
              ["Book IR gain", "Best gain in the book's information ratio with a 5%, 10% or 20% sleeve", f"&ge; {bk['ir_gain_green_min']:.2f}"],
              ["Post-publication", "Net edge from the paper's date onward", f"&gt; {th['post_publication']['edge_green_min']:.0%}"]], [0.17, 0.53, 0.3]),
         P("Amber bands are for display and were not simulated. The factor indices are backfilled before their launch dates and price-only. Alpha net of factor product costs needs those costs, which are not supplied yet.", "small"),
         BOX([P("<b>The deflated Sharpe is out of the gate for now, by your ruling.</b> So nothing in Gate v2 tests for selection luck: trying many versions and reporting the best will not be caught. If it returns, its bar starts at the benchmark's Sharpe, also by your ruling, and the code and setting are still there (config/gate_thresholds.yaml, enabled: false). The figures below show the cost.", "body")], WARN),
         CondPageBreak(300), P("Part 3. Calibration", "H1"),
         P("Set by simulation from 8,000 strategies, with no named strategy used: 12.7 years of daily returns, fat tails, volatility clustering, about 17% volatility and 0.8 correlation to the benchmark. The thresholds were eased at your request, as far as the 5% false-pass target allows. They were committed before any named strategy was scored on them."),
         Image(png, width=W, height=W * h / w), Spacer(1, 6), TBL(table, [0.27, 0.1, 0.07, 0.07, 0.07, 0.07, 0.11, 0.12, 0.12]),
         P("\"True Sharpe\" is the true information ratio against the benchmark. Best of N is the best of N strategies with no skill, chosen in-sample. Scored with no book. Simulated returns are treated as already net of cost. Capacity, mandate and data integrity are not modelled.", "small"),
         TBL([["Target", "Result"],
              ["False pass at most 5% at true Sharpe 0", f"<b>Met:</b> {pc(rate('v2', 'PASS and green, no book', 'level 0'))} on PASS and all green. But {pc(rate('v2', 'STATUS PASS, hard blocks', 'level 0'))} reach status PASS, above 5%, because the scorecard does not block"],
              ["False pass at most 5% on pure-factor strategies", f"<b>Met on PASS and all green:</b> {pc(rate('v2', 'PASS and green, no book', 'pure factor'))}. <b>Not on status alone:</b> {pc(rate('v2', 'STATUS PASS, hard blocks', 'pure factor'))} reach PASS with factor alpha red"],
              ["False pass at most 5% on selection bias", f"<b>Not met:</b> {pc(rate('v2', 'PASS and green, no book', 'best of 20'))} of the best of 20 and {pc(rate('v2', 'PASS and green, no book', 'best of 100'))} of the best of 100 pass. This is the cost of removing the deflated Sharpe"],
              ["Pass at least 70% at true Sharpe 1.0", f"<b>Met:</b> {pc(rate('v2', 'PASS and green, no book', 'level 1'))}"]], [0.38, 0.62]),
         BOX([P("<b>So read status and scorecard together.</b> PASS alone means only that the strategy beat the benchmark after costs by more than noise explains. Factor alpha is what separates skill from buying factors, and on the current rules it does not block.", "body")]),
         P("Part 4. What changed from v1", "H1"),
         TBL([["v1", "v2", "Why"],
              ["Deflated Sharpe blocks, at V = 1", "Out of the gate for now", "Your ruling. It failed almost everything: at N = 13, v1 passes 0.1% of strategies with a true excess Sharpe of 1.0"],
              ["Worst window: absolute Sharpe &ge; 0.30", "Sharpe gap to the benchmark, on the scorecard", "A weak market should not fail a strategy that beat it"],
              ["Bootstrap P &le; 0.05, gross", f"P &le; {bp['p_max']:.2f}, net of the house cost", "Your ruling to ease, and costs are real"],
              ["Alpha |t| &ge; 2, blocking, on a narrower factor set", "Alpha &gt; 0 and t &ge; 2, on the scorecard, with size factors", "v1 passed a strongly negative alpha. A missing size factor overstated alpha"],
              ["Book tests advisory when no book", "Not run when no book", "Your ruling: a missing book does not hold the gate up"],
              ["Turnover &le; 400%, advisory", "Reported only. Costs enter through net returns, plus capacity", "Costs are what turnover was standing in for"],
              ["Mandate judged with a flag on the card", "Fund file the card cannot override", "A card should not set its own limits"],
              ["No net-edge test", "Net edge &gt; 0 is a hard block", "The strategy must beat the index after costs"],
              ["A list of 8 criteria", "Hard blocks and a scorecard, PASS or FAIL", "Separates what stops a strategy from what informs you"]], [0.34, 0.33, 0.33], boldfirst=False)]
    doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=50, rightMargin=50, topMargin=44, bottomMargin=48, title="Financial metrics and Gate B tests, version 2", author=SIGN, subject="One formula per metric, the gate, its calibration and what changed")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(50, 48, W, A4[1] - 92, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=footer)])
    doc.build(E)
    print("OK", OUT, os.path.getsize(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
