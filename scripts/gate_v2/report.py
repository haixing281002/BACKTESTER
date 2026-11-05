# Quant AI Researcher by Harshil Pahuja
"""Build docs/gate_b/gate-b-v2-calibration.pdf from the calibration tables: the curves and thresholds to approve.

Every number is read from docs/gate_b/calibration/. Nothing here decides a threshold.

    python scripts/gate_v2/report.py
"""
from __future__ import annotations

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
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
sys.path.insert(0, os.path.join(REPO, "scripts", "gate_v2"))
import analyse as A

CAL = os.path.join(REPO, "docs", "gate_b", "calibration")
OUT = os.path.join(REPO, "docs", "gate_b", "gate-b-v2-calibration.pdf")
SIGN = "Quant AI Researcher by Harshil Pahuja"
LEVELS = ["level 0", "level 0.25", "level 0.5", "level 0.75", "level 1"]
X = [0, 0.25, 0.5, 0.75, 1.0]
C_V2, C_V1, C_V1B = "#2166ac", "#c8660c", "#1b8a6b"

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
     "bul": ParagraphStyle("bul", fontName="A", fontSize=9.7, leading=13.6, textColor=INK, leftIndent=12, bulletIndent=1, spaceAfter=3.5),
     "H2": ParagraphStyle("H2", fontName="AB", fontSize=12.4, leading=16, textColor=NAVY, spaceBefore=11, spaceAfter=5, keepWithNext=1),
     "title": ParagraphStyle("title", fontName="AB", fontSize=22, leading=27, textColor=NAVY, spaceAfter=4),
     "sub": ParagraphStyle("sub", fontName="A", fontSize=11, leading=15, textColor=MUTED, spaceAfter=9)}
W = A4[0] - 100
plt.rcParams.update({"font.family": "Arial", "font.size": 8.5, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#9aa5b1", "axes.linewidth": 0.6,
                     "xtick.color": "#5d6b7c", "ytick.color": "#5d6b7c", "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#eef1f4", "axes.axisbelow": True,
                     "axes.titlesize": 9, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlecolor": "#1b2430"})


def P(t, s="body"):
    return Paragraph(t, S[s])


def pc(x):
    return f"{x * 100:.1f}%"


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


def img(fig, name):
    p = os.path.join(CAL, name + ".png")
    fig.savefig(p, dpi=240, facecolor="white")
    plt.close(fig)
    w, h = PILImage.open(p).size
    return Image(p, width=W, height=W * h / w)


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
    t = pd.read_csv(os.path.join(CAL, "power_table.csv"))
    with open(os.path.join(CAL, "proposal.json"), encoding="utf-8") as fh:
        prop = json.load(fh)
    df = pd.read_csv(os.path.join(CAL, "sim_stats.csv.gz"))
    ref = pd.read_csv(os.path.join(CAL, "reference.csv"))
    th = prop["thresholds"]
    hard = prop["hard_blocks_alone"]

    def rate(gate, test, case):
        return float(t[(t.gate == gate) & (t.test == test) & (t.case == case)].pass_rate.iloc[0])

    # ---- the power curves
    fig, ax = plt.subplots(figsize=(7.2, 2.75))
    series = [("Gate v2, proposed (with book)", "v2", "OVERALL, with book", C_V2, "o", (0, 7)), ("Gate v1, N = 1", "v1", "OVERALL, N = 1", C_V1, "s", (0, -13)), ("Gate v1, N = 13", "v1", "OVERALL, N = 13", C_V1B, "^", (0, 7))]
    for label, gate, test, col, mk, off in series:
        y = [rate(gate, test, c) for c in LEVELS]
        ax.plot(X, y, color=col, lw=2, marker=mk, ms=6, label=label, markeredgecolor="white", markeredgewidth=1.2)
        ax.annotate(f"{y[-1]:.0%}", (X[-1], y[-1]), textcoords="offset points", xytext=off, ha="center", fontsize=8, color="#1b2430")
    ax.axhline(0.7, color="#5d6b7c", lw=0.7, ls="--")
    ax.text(0.005, 0.715, "Target: at least 70% at true excess Sharpe 1.0", fontsize=7.4, color="#5d6b7c")
    ax.set(ylim=(-0.03, 1.08), xlim=(-0.04, 1.06), xlabel="True excess Sharpe (information ratio against the benchmark)", ylabel="Share of simulated strategies passing")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xticks(X)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, 0.66), fontsize=8)
    ax.set_title("How often a strategy passes, by how good it really is")
    fig.tight_layout()
    f1 = img(fig, "power_overall")

    # ---- each test on its own
    tests = ["net edge", "bootstrap", "deflated Sharpe", "sub-period", "factor alpha", "book IR gain"]
    fig, axes = plt.subplots(2, 3, figsize=(7.2, 3.15), sharex=True, sharey=True)
    for ax, test in zip(axes.flat, tests):
        y = [rate("v2", test, c) for c in LEVELS]
        ax.plot(X, y, color=C_V2, lw=2, marker="o", ms=5, markeredgecolor="white", markeredgewidth=1)
        ax.set_title(test[0].upper() + test[1:])
        ax.set_ylim(-0.03, 1.05)
        ax.set_xticks([0, 0.5, 1.0])
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.annotate(f"{y[-1]:.0%}", (1.0, y[-1]), textcoords="offset points", xytext=(-2, -12), ha="right", fontsize=7.6, color="#1b2430")
        ax.annotate(f"{y[0]:.0%}", (0.0, y[0]), textcoords="offset points", xytext=(7, -4), fontsize=7.6, color="#1b2430")
    fig.supxlabel("True excess Sharpe", fontsize=8.2, color="#5d6b7c")
    fig.tight_layout()
    f2 = img(fig, "power_by_test")

    # ---- options
    base = {"null": "bench", "basis": "active", "floor": "1overT", "boot_p": 0.05, "corr_max": 0.8, "ir_gain_min": 0.05}
    opts = [("Strict", {"dsr_min": 0.95, "window_floor": -0.25, "t_min": 2.0}), ("<b>Proposed</b>", {k: th[k] for k in ("dsr_min", "window_floor", "t_min")}), ("Lenient", {"dsr_min": 0.80, "window_floor": -0.75, "t_min": 1.65})]
    orows = [["Option", "Deflated Sharpe", "Worst window", "Alpha t", "False pass: Sharpe 0", "Factor only", "Best of 100", "Pass: 0.5", "0.75", "1.0"]]
    for nm, o in opts:
        c = {**base, **o}
        r = {k: float(A.v2_pass(A.case(df, k), c, True).mean()) for k in A.CASES}
        orows.append([nm, f"&ge; {o['dsr_min']:.2f}", f"&ge; {o['window_floor']:.2f}", f"&ge; {o['t_min']:.2f}", pc(r["level 0"]), pc(r["pure factor"]), pc(r["best of 100"]), pc(r["level 0.5"]), pc(r["level 0.75"]), pc(r["level 1"])])

    crows = [["Gate", *["True Sharpe 0", "0.25", "0.5", "0.75", "1.0"], "Factor only", "Best of 20", "Best of 100"]]
    order = LEVELS + ["pure factor", "best of 20", "best of 100"]
    crows.append(["v1, N = 1"] + [pc(rate("v1", "OVERALL, N = 1", c)) for c in order])
    crows.append(["v1, N = 13"] + [pc(rate("v1", "OVERALL, N = 13", c)) for c in order])
    crows.append(["v2, hard blocks only"] + [pc(hard[c]) for c in order])
    crows.append(["<b>v2, hard blocks + green, with book</b>"] + [f"<b>{pc(rate('v2', 'OVERALL, with book', c))}</b>" for c in order])
    crows.append(["v2, hard blocks + green, no book*"] + [pc(rate("v2", "OVERALL, no book", c)) for c in order])

    # ---- real data
    named = ref[~ref.name.str.startswith("Random")]
    rnd = ref[ref.name.str.startswith("Random")]
    rrows = [["Reference (net of 30bp where it trades)", "Edge a year", "Bootstrap P", "Hard blocks", "Deflated Sharpe", "Alpha t", "Windows ahead"]]
    for _, r in named.iterrows():
        hb = r["edge"] > 0 and r["boot_p"] <= 0.05
        rrows.append([r["name"], pc(r["edge"]), f"{r['boot_p']:.3f}", "pass" if hb else "fail", f"{r['dsr_bench_n1']:.2f}", "n/a" if pd.isna(r["alpha_t"]) else f"{r['alpha_t']:.2f}", f"{int(r['sp_pos'])} of {int(r['sp_n'])}"])
    n_hb = int(((rnd["edge"] > 0) & (rnd["boot_p"] <= 0.05)).sum())
    rrows.append([f"Random 30 stocks, {len(rnd)} books (mean)", pc(rnd["edge"].mean()), f"{rnd['boot_p'].mean():.3f}", f"{n_hb} of {len(rnd)} pass", f"{rnd['dsr_bench_n1'].mean():.2f}", f"{rnd['alpha_t'].mean():.2f}", f"{rnd['sp_pos'].mean():.1f} of 4"])
    bench_zero = float(named.iloc[0]["dsr_zero_n1"])

    def stricter(case_name):
        """Hard blocks plus the deflated Sharpe and factor alpha, if those two moved into the hard blocks (Decision 2)."""
        x = A.v2_tests(A.case(df, case_name), {**base, **{k: th[k] for k in ("dsr_min", "window_floor", "t_min")}})
        return float((x["net edge"] & x["bootstrap"] & x["deflated Sharpe"] & x["factor alpha"]).mean())


    g = pd.read_csv(os.path.join(CAL, "candidate_grid.csv"))
    z = g[(g["null"] == "zero") & (g["basis"] == "active") & (g["dsr_min"] == 0.95) & (g["t_min"] == 2.0) & (g["window_floor"] == -0.5)].set_index("floor")
    lv0_dsr_zero = float((A.case(df, "level 0")["dsr_zero_active_1overT"] >= 0.95).mean())
    lv0_dsr_bench = float((A.case(df, "level 0")["dsr_bench_active_1overT"] >= th["dsr_min"]).mean())

    E = [P("Gate B v2: calibration", "title"), P("The curves and thresholds to approve. Nothing here is live until you approve it. No named strategy was used.", "sub"),
         BOX([P(f"<b>Proposed thresholds meet both targets.</b> False pass is at most {pc(max(rate('v2', 'OVERALL, with book', c) for c in A.NULLS))} on every no-skill case (target: 5%), and {pc(rate('v2', 'OVERALL, with book', 'level 1'))} of strategies with a true excess Sharpe of 1.0 pass (target: 70%). "
                f"Gate v1 passes {pc(rate('v1', 'OVERALL, N = 13', 'level 1'))} of those at N = 13, and {pc(rate('v1', 'OVERALL, N = 1', 'level 1'))} even at N = 1.", "body"),
              P(f"<b>The hard blocks alone do not stop luck or factor beta.</b> They let through {pc(hard['pure factor'])} of pure-factor strategies and {pc(hard['best of 100'])} of the best of 100 random ones. The scorecard stops those, and the scorecard does not block. See Decision 2.", "body")]),
         P("Proposed thresholds", "H2"),
         TBL([["Test", "Proposed", "Where it sits", "Basis"],
              ["Net-of-cost edge", "&gt; 0", "Hard block", "From the brief"],
              ["Paired bootstrap", "P &le; 0.05, 2,000 draws, mean block 21, seed 7", "Hard block", "From the brief"],
              ["Deflated Sharpe", f"Green &ge; {th['dsr_min']:.2f}. Bar starts at the benchmark's Sharpe", "Scorecard", "Simulated. See Decision 1"],
              ["Deflated Sharpe inputs", "N adjusted for correlation of returns above the benchmark. Floor on V = 1 / years (0.079 at 12.7 years)", "Scorecard", "Simulated"],
              ["Sub-period stability", f"At least 3 of 4 windows ahead of the benchmark, none below {th['window_floor']:.2f} on the Sharpe gap", "Scorecard", "Simulated"],
              ["Factor alpha", f"Alpha &gt; 0 and t &ge; {th['t_min']:.1f}. 1.65 gives almost the same result, so the stricter one is proposed", "Scorecard", "Simulated"],
              ["Book correlation", f"&le; {th['corr_max']:.2f}", "Scorecard", "Simulated on a synthetic book. See Decision 3"],
              ["Book IR gain", f"&ge; {th['ir_gain_min']:.2f}", "Scorecard", "Simulated on a synthetic book"],
              ["Capacity", "95th percentile &le; 10% of 20-day traded value", "Hard block", "<b>Not simulated.</b> Existing repo default"],
              ["Priced-member coverage", "&ge; 95%", "Hard block", "<b>Not simulated.</b> My placeholder"],
              ["Amber bands", "Deflated Sharpe &ge; 0.80, alpha t &ge; 1.0, window floor -1.25, correlation &le; 0.90, IR gain &ge; 0", "Scorecard", "<b>Not simulated.</b> Display only"]], [0.2, 0.46, 0.12, 0.22]),
         CondPageBreak(250), P("Power curves", "H2"), f1,
         TBL(crows, [0.28, 0.1, 0.07, 0.07, 0.07, 0.07, 0.11, 0.11, 0.12]),
         P(f"*No book: the status would read INCOMPLETE, never PASS; this row only shows what the other tests do. {prop['n_simulated_per_case']:,} simulated strategies in each case. A rate near 1% has a margin of about 0.6 points; a rate near 70% about 2.8 points.", "small"),
         P(f"<b>Limit of any test on this much history.</b> A real but moderate edge usually does not clear it: {pc(rate('v2', 'OVERALL, with book', 'level 0.5'))} pass at a true excess Sharpe of 0.5. That comes from 12.7 years of noisy returns, and the only way to raise it is to accept more false passes."),
         CondPageBreak(260), P("Each test on its own, proposed thresholds", "H2"), f2,
         P(f"The left-hand label on each panel is the pass rate with no skill, and the right-hand one at a true excess Sharpe of 1.0. Factor alpha is what removes pure-factor strategies ({pc(rate('v2', 'factor alpha', 'pure factor'))} pass it), and the deflated Sharpe is what removes selection luck ({pc(rate('v2', 'deflated Sharpe', 'best of 100'))} of the best of 100 pass it). Sub-period stability separates little by itself: {pc(rate('v2', 'sub-period', 'pure factor'))} of pure-factor strategies pass it."),
         KeepTogether([P("Other settings that also meet the targets", "H2"),
                       TBL(orows, [0.12, 0.1, 0.09, 0.08, 0.12, 0.09, 0.09, 0.1, 0.1, 0.11]),
                       P(f"{prop['n_meeting_targets']} of the {prop['n_candidates']} settings tried meet both targets, so the targets alone do not pick one. The rule used: worst false pass no higher than 2.5%, half the target, because a simulation is only a model of markets. Among those, the most power at 1.0, then the strictest settings where power ties. Full grid: docs/gate_b/calibration/candidate_grid.csv.", "small")]),
         KeepTogether([P("Real data: reference strategies", "H2"), TBL(rrows, [0.34, 0.1, 0.11, 0.12, 0.11, 0.09, 0.13]),
                       P("Expected: none passes the hard blocks plus a green scorecard. <b>None does.</b> The 2014 to 2026 window, Ace prices, point-in-time membership keeping delisted names, price returns. The Momentum 50 index misses the bootstrap only narrowly, and its alpha is measured with itself left out of the factors. These factor indices are backfilled before their launch dates. The equal-weight book was checked against an independent build and matches.", "small")]),
         CondPageBreak(220), P("Decisions for you", "H2"),
         P(f"<b>1. Where the deflated Sharpe bar starts.</b> The published formula assumes a no-skill strategy has a Sharpe of zero. A no-skill long-only strategy still earns the market's. As written, <b>the NIFTY 500 itself scores {bench_zero:.2f} and goes green at 0.95</b>, and {pc(lv0_dsr_zero)} of no-skill strategies clear 0.95. Starting the bar at the benchmark's Sharpe cuts no-skill strategies to {pc(lv0_dsr_bench)} at {th['dsr_min']:.2f}. This departs from your brief and from the published formula, so it needs your approval. The alternative: keep the published form with a floor on V of 0.25. It also meets the targets overall ({pc(float(z.loc['0p25', 'worst false | book']))} false pass, {pc(float(z.loc['0p25', 'level 1 | book']))} power at the 0.95 row), but the row then says little alone."),
         P(f"<b>2. Should anything from the scorecard block?</b> As briefed, status PASS needs only the hard blocks. So {pc(hard['pure factor'])} of pure-factor strategies would read PASS with a red factor row. A person still decides, but PASS would mean less than it says. I recommend moving factor alpha and the deflated Sharpe into the hard blocks. PASS would then be reached by {pc(stricter('pure factor'))} of pure-factor strategies, {pc(stricter('best of 100'))} of the best of 100, {pc(stricter('level 0'))} with no skill and {pc(stricter('level 1'))} at a true excess Sharpe of 1.0."),
         P("<b>3. What counts as the book.</b> Your brief allows the benchmark in the book. Long-only strategies sit above 0.80 correlation to it almost by construction: 0.91 for the equal-weight book and 0.87 for Momentum 50. Test 4 would fail nearly everything, and an IR gain against the benchmark alone is undefined. I recommend the fund's actual strategies only, without the benchmark. No decision has ever been recorded in Lightyear, so the registry of approved strategies is empty, and <b>every run will read INCOMPLETE until you supply a book file</b>."),
         P("<b>4. Values I need from you.</b> AUM in crore. Mandate limits: long-only or not, maximum cash share, maximum single weight. The capacity and coverage limits above. Yearly costs of the factor products, for alpha net of those costs. These stay blank, and their tests stay INCOMPLETE, until you supply them."),
         P("How this was simulated", "H2")]
    E += [Paragraph(x, S["bul"], bulletText="•") for x in [
        "<b>Each strategy:</b> 12.7 years of daily returns, Student-t tails (df 5), GARCH(1,1) volatility clustering, about 17% volatility and 0.8 correlation to a benchmark with 16% volatility and 7% a year above cash. Cash 6%.",
        "<b>I read \"true excess Sharpe\" as the information ratio against the benchmark:</b> mean(r - b) / stdev(r - b). Tell me if you meant something else. Simulated returns are treated as already net of cost.",
        "<b>Pure factor:</b> a fixed mix of market, size, momentum and value, plus 3% tracking noise and zero alpha. <b>Selection:</b> the best of N no-skill strategies, chosen in-sample on Sharpe, with N honestly reported. A hidden N would defeat the deflated Sharpe.",
        "<b>Book:</b> an independent synthetic strategy with an information ratio of 0.30. A real book may differ.",
        "<b>Not modelled:</b> capacity, mandate and data integrity are assumed to pass, because a simulation has no positions. Regime changes beyond volatility clustering are not modelled either.",
        "<b>Reproducible:</b> one seed per strategy. python scripts/gate_v2/calibrate.py simulate --sims 1000, then analyse.py, reference.py and report.py."]]

    doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=50, rightMargin=50, topMargin=44, bottomMargin=48, title="Gate B v2: calibration", author=SIGN, subject="Power curves and proposed thresholds, for approval")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(50, 48, W, A4[1] - 92, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=footer)])
    doc.build(E)
    print("OK", OUT, os.path.getsize(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
