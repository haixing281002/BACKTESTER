# Quant AI Researcher by Harshil Pahuja
"""Build docs/gate_b/gate-b-v2-change-log.pdf. Run figures are read from the run files and the dashboard check, never typed.

    python scripts/gate_v2/build_change_log.py <run_id> "<pytest summary>"
"""
import json
import os
import subprocess
import sys

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle

NEW, TESTS = sys.argv[1], sys.argv[2]
RN = f"outputs/lightyear/{NEW}"
OUT = "docs/gate_b/gate-b-v2-change-log.pdf"
SIGN = "Quant AI Researcher by Harshil Pahuja"
with open(RN + "/state.json", encoding="utf8") as fh:
    state = json.load(fh)
with open(RN + "/charts.json", encoding="utf8") as fh:
    ch = json.load(fh)
with open("outputs/tmp/dash_check.json", encoding="utf8") as fh:
    dash = json.load(fh)
res = state["results"]
g = res["gate_v2"]
commits = [ln.split("|", 1) for ln in subprocess.run(["git", "log", "--reverse", "--format=%h|%s", "gate-v1..HEAD"], capture_output=True, text=True).stdout.splitlines()]
stat = subprocess.run(["git", "diff", "--shortstat", "gate-v1..HEAD"], capture_output=True, text=True).stdout.strip()
vv = pd.read_csv("docs/gate_b/v1_vs_v2.csv")
t = pd.read_csv("docs/gate_b/calibration/power_table_approved.csv")
sweep = pd.read_csv(RN + "/out/cost_sweep.csv")

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
     "H2": ParagraphStyle("H2", fontName="AB", fontSize=12.4, leading=16, textColor=NAVY, spaceBefore=11, spaceAfter=5, keepWithNext=1),
     "title": ParagraphStyle("title", fontName="AB", fontSize=22, leading=27, textColor=NAVY, spaceAfter=4),
     "sub": ParagraphStyle("sub", fontName="A", fontSize=11, leading=15, textColor=MUTED, spaceAfter=9)}
W = A4[0] - 100


def P(x, s="body"):
    return Paragraph(x, S[s])


def TBL(data, widths, boldfirst=True):
    out = [[Paragraph(str(c), S["th" if i == 0 else ("cellb" if boldfirst and j == 0 else "cell")]) for j, c in enumerate(r)] for i, r in enumerate(data)]
    tb = Table(out, colWidths=[w * W for w in widths], repeatRows=1)
    tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY)]))
    tb.spaceAfter = 7
    return tb


def BOX(flow, bg=SOFT):
    tb = Table([[flow]], colWidths=[W])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 2.6, NAVY if bg == SOFT else colors.HexColor("#d9a400")), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return KeepTogether([tb, Spacer(1, 8)])


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


def pc(x):
    return "n/a" if x is None or x != x else f"{x:.2%}"


def nm(x, d=3):
    return "n/a" if x is None or x != x else f"{x:.{d}f}"


def rate(test, case):
    return float(t[(t.gate == "v2") & (t.test == test) & (t.case == case)].pass_rate.iloc[0])


why = {"Freeze": "So every later result can be compared with what v1 really said.", "One metrics": "The same metric name gave different numbers depending on where you looked.",
       "Gate v2:": "Built so it could be simulated, before any threshold was chosen.", "Calibrate": "So thresholds come from simulation, not from any one strategy.",
       "Fixes": "The dashboard check found these.", "Change log": "You asked for a record of the changes.", "Approve": "Your rulings, committed before any named strategy was scored on them.",
       "Wire": "So every run is scored on v2, on the page and in Excel.", "Page,": "Superseded by the card-only rule below.", "Reference": "The document updated to v2.",
       "A run's cost": "<b>Your ruling: the cost set at Gate A is the cost charged.</b>", "A value with": "My new breakeven row broke the page at 0bp.", "Drop": "A leftover 30bp row from an earlier run."}
crows = [["Commit", "What", "Why"]] + [[h, s, next((v for k, v in why.items() if s.startswith(k)), "")] for h, s in commits]

hr = {r["key"]: r for r in g["hard_blocks"] + g["scorecard"]}
v1c = {c["name"]: c for c in res["gate_b"]["criteria"]}
sm = g["summary"]
cl = [["Test", "Gate v1", f"Gate v2, at the card's {ch['card_bp']:g}bp"],
      ["<b>Status</b>", "<b>FAIL</b>, 1 of 5 blocking", f"<b>{g['status']}</b>"],
      ["Edge over the benchmark", "Not tested", f"{pc(sm['net_edge'])}: {hr['net_edge']['status']}"],
      ["Paired bootstrap P", f"{v1c['advantage over benchmark is significant']['value']}: fail at 0.05", f"{nm(sm['bootstrap_p'])}: {hr['bootstrap']['status']} at 0.10"],
      ["Worst window", f"{v1c['positive Sharpe in every out-of-sample window']['value']} absolute Sharpe: fail at 0.30", f"Sharpe gap {nm(sm['sub_period_worst'], 2)}, {sm['sub_period_positive']} of {sm['sub_period_n']} windows ahead: {hr['sub_period']['status']}"],
      ["Factor alpha t", f"{v1c['alpha survives the factor fingerprint']['value']} on 2 factors: fail at 2.0", f"{nm(sm['alpha_t'], 2)} on 7 factors: <b>{hr['factor_alpha']['status']}</b>, does not block"],
      ["Deflated Sharpe", f"{v1c['deflated Sharpe clears selection bias']['value']}: fail", "Out of the gate"],
      ["After publication: edge", "Not tested", f"{pc(sm['post_publication_edge'])}: {hr['post_publication']['status']}"],
      ["Data integrity", "Not tested", hr["data_integrity"]["status"]],
      ["Mandate, capacity, book", "Mandate passed on the card's flag; no book", "Not run: no values supplied"]]
core = {r[0]: r for r in dash["core"]}
core_rows = [["On the page now", "Strategy, at the card's cost", "NIFTY 500"]] + [[k, core[k][1], core[k][2]] for k in ("CAGR", "Sharpe", "Sortino", "Calmar", "Maximum drawdown", "Drawdown duration (trading days)", "Information ratio")]
sw = [["Appendix sweep: round-trip cost"] + [f"{r.round_trip_cost_bp:g}bp" for r in sweep.itertuples()], ["CAGR"] + [pc(r.cagr) for r in sweep.itertuples()], ["Edge over the index"] + [pc(r.minus_nifty500_cagr) for r in sweep.itertuples()]]

short = {"oceanofpdf_com_stocks_on_the_move_andreas_clenow": "Clenow", "padhy_2024_130_30_long_short": "Padhy 130/30", "lee_swaminathan_1998_price_momentum_trading_volume": "Lee-Swaminathan", "1_s2_0_s0970389623000538_main": "1_s2_0 (s0970389623000538)", "method_nifty_equity_indices": "Momentum 50 rebuild"}
rr = [["Run", "Strategy", "v1", "v2", "Edge", "P", "Why it changed"]]
for _, r in vv.iterrows():
    if r["v1"] != r["v2"]:
        txt = f"Clears every hard block that could be run. Alpha (t {r['alpha_t']:.2f}) no longer blocks, and the deflated Sharpe is out"
    else:
        txt = "Still fails: bootstrap P above 0.10" if r["bootstrap_p"] > 0.10 else "Still fails"
    rr.append([r["run"], short.get(r["strategy"], r["strategy"]), r["v1"], f"<b>{r['v2']}</b>", pc(r["edge"]), nm(r["bootstrap_p"]), txt])
n_pass = int((vv["v2"] == "PASS").sum())
checks = dash["checks"]
n_ok, n_all = sum(c["ok"] for c in checks), len(checks)
assert n_ok == n_all

E = [P("Gate B v2 and metrics: change log", "title"), P("What changed, why, what the re-run showed, and what the dashboard now shows.", "sub"),
     BOX([P("<b>Where this stands.</b> All six phases are done on the branch gate-b-v2-and-metrics-consolidation. It is not pushed, as you asked, and not merged, so this shows on port 8101 only.", "body"),
          P(f"<b>Cost and cash now come only from the card.</b> The backtest always ran at your 0bp. The 30bp was added afterwards, to Gate v2 and a \"net\" column, by a rule in the brief that I applied over your Gate A ruling. That is removed, along with every other cost or cash number in the code.", "body"),
          P(f"<b>Clenow's latest run ({NEW}) now reads {g['status']} on Gate v2, at your {ch['card_bp']:g}bp.</b> Bootstrap P {nm(sm['bootstrap_p'])} clears the eased 0.10, but would miss the original 0.05. Factor alpha is {hr['factor_alpha']['status']} at t {nm(sm['alpha_t'], 2)}. At 0bp nothing here tests what trading {ch['annual_turnover']:.1f} times capital a year would cost: the sweep below does that.", "body")], WARN),
     P("Your rulings", "H2"),
     TBL([["You said", "What I did"],
          ["Use 0bp as set at Gate A. Remove all hard-coding of cost and cash", "Card only: the gate, metrics, page and Excel use costs.spread_bps and universe.cash_asset. Details below"],
          ["Approve, but make them easier", f"Bootstrap P eased from 0.05 to 0.10, and sub-period to 2 of 4 windows, none below -1.0. Pass at a true excess Sharpe of 0.5 rose from 42.6% to {rate('PASS and green, no book', 'level 0.5'):.1%}. Alpha stays at t 2.0: any lower breaks the 5% false-pass target"],
          ["Benchmark Sharpe", "Where the deflated Sharpe bar starts. Dormant while the test is out"],
          ["Remove the deflated Sharpe for now", "Out of the gate, off in config. <b>So v2 no longer tests for selection luck</b>. The results table still reports it as a figure"],
          ["INCOMPLETE is not the right way", "Status is PASS or FAIL. A test with nothing to run on shows as not run and is listed beside the status"],
          ["Good to proceed without those values", "AUM, mandate limits, the book and product costs stay blank. Their tests show as not run"],
          ["Archive, but keep the tearsheet for Excel", "<b>Nothing archived:</b> the Excel calculation needs both tearsheet files, and the momentum rotation script produces that workbook"],
          ["Hold the push", "Not pushed"]], [0.34, 0.66]),
     P("Cost and cash: what was removed", "H2"),
     TBL([["Where", "Before", "Now"],
          ["Gate v2 and the \"net\" column", "Charged a 30bp house cost over your 0bp", "The run's returns as they are, at the card's cost. Gross shows beside net only if that cost is not zero"],
          ["config/costs.yaml", "house_round_trip_bp: 30", "Only the appendix sweep grid. It never reaches a headline or a gate"],
          ["config/fund.yaml", "A 6% fallback I added yesterday", "Removed. Only the appendix cash sweep. A card naming no rate gets Sharpe over zero, and the page says so"],
          ["Clenow script", "A dedicated 30bp comparator and two rows at 30bp and 100bp. Grids written in code", "Removed. Grids read from config. A breakeven row replaces them"],
          ["Rule text: CLAUDE.md, Gate A requirements, card drafting, universes, the model's prompts", "\"30bp is non-negotiable\"", "The card states a cost and a human confirms it at Gate A"],
          ["Code defaults", "Cost 5bp and 10bp in the engines and schema. Cash 6% in the pipeline, runner, cross-check and deciles, and 5% in the Excel tearsheet", "No defaults. A missing value is an error, or comes from the card"],
          ["Completeness and Gate A checks", "A cost under 20bp counted as a fault", "The check is that the card states one. Zero is a stated cost, and cost is always flagged for a human"],
          ["Momentum rotation script", "30bp, and 5% on the Excel sheet", "It has no card, so you pass both when you run it"],
          ["Simulations", "6% and 30bp written in", "In config/calibration.yaml, read by the simulations only. No strategy run reads them"]], [0.26, 0.37, 0.37]),
     P("A test now fails if a number like these is written back into live code.", "small"),
     P("Commits", "H2"), TBL(crows, [0.09, 0.53, 0.38], boldfirst=False),
     P(f"{stat}, compared with the tag gate-v1. Tests: {TESTS} on the final code (570 passed before this work). ruff: no new errors against the original code.", "small"),
     P("Metric definitions: before and after", "H2"),
     TBL([["Metric", "Before", "Now"],
          ["Sharpe", "Four formulas: (CAGR - 6%) / vol on the tile, (CAGR - compounded cash) / vol in tables, (mean x 252 - 6%) / vol in Excel, mean excess / stdev in the deflated Sharpe", "One: mean(r - c) / stdev(r - c) x sqrt(252)"],
          ["Max drawdown", "Positive in some places, negative in others", "Daily values, positive"],
          ["Drawdown duration", "Calendar days", "Trading days"],
          ["Tracking error", "Sample in one path, population in another", "Sample stdev of daily gaps"],
          ["Up / down capture", "Daily means in one path, monthly in another", "<b>Monthly means</b>. My choice: your brief named no frequency"],
          ["95% CVaR", "Rolling 21-day in one path, daily and negative in another", "<b>Daily, positive loss</b>. My choice of frequency"],
          ["Turnover", "Mean x 252 in one path, sum / years in another", "Sum / years"],
          ["Bootstrap", "Geometric Sharpe", "The one Sharpe, same settings, plus a paired drawdown gap as evidence only"]], [0.18, 0.5, 0.32]),
     P("Added", "H2"),
     TBL([["What", "Where"],
          ["Core performance table: the same 16 metrics on every run, including Sortino and Calmar", "Results tab; Core metrics sheet in Excel"],
          ["Gate v2: hard blocks, scorecard, PASS or FAIL. v1 folded below for comparison", "Gate B tab; Gate v2 sheet in Excel"],
          ["Capacity. Code done, shows as not run until you supply AUM", "Results tab, Gate B tab"],
          ["Post-publication metrics", "Results tab, Excel, scorecard"],
          ["Diagnostics section for rows tied to one strategy's rules", "Results tab, Excel Validation sheet"],
          ["gate_version and metrics_version", "manifest.json, workbook header, Gate B tab"],
          ["Card fields: n_configs_selected_from, n_sensitivities, rules_fixed_in_print, fits_parameters", "ros/cards/schema.py"]], [0.68, 0.32]),
     P("Cut and kept", "H2"),
     TBL([["Item", "Status"],
          ["Mean drawdown, vol consistency, hit rate, monthly CVaR, the geometric and duplicate Sharpes", "<b>Cut</b> from the pipeline report and metrics modules"],
          ["Sterling, Treynor, Omega, Gain to Pain, tail ratio, adjusted beta, Jensen's alpha, extreme capture and the rest of your cut list", "<b>Off Lightyear, still in the tearsheet</b>, because you need the Excel calculation. Its numbers can differ from the dashboard's"],
          ["Geometric Sharpe", "<b>Kept in one place</b>, so a paper's printed Sharpe compares on its own definition"],
          ["validate/independent.py", "<b>Kept separate on purpose:</b> the clean-room cross-check imports nothing from ros"],
          ["universal_backtester/validation.py", "<b>Not consolidated.</b> Its own bootstrap and deflated Sharpe remain, but no Lightyear path or gate uses them"]], [0.55, 0.45]),
     P("Gate v2 and the calibration", "H2"),
     TBL([["Share passing", "True Sharpe 0", "0.5", "0.75", "1.0", "Factor only", "Best of 20", "Best of 100"]] +
         [[lab] + [f"{rate(tst, c):.1%}" for c in ("level 0", "level 0.5", "level 0.75", "level 1", "pure factor", "best of 20", "best of 100")] for lab, tst in (("Status PASS (hard blocks)", "STATUS PASS, hard blocks"), ("PASS and all green", "PASS and green, no book"))], [0.28, 0.12, 0.09, 0.09, 0.09, 0.11, 0.11, 0.11]),
     BOX([P(f"<b>What the rulings cost.</b> PASS and all green meets the targets for no-skill and factor-only strategies. <b>Status PASS alone does not:</b> {rate('STATUS PASS, hard blocks', 'pure factor'):.0%} of factor-only strategies and {rate('STATUS PASS, hard blocks', 'level 0'):.1%} of no-skill ones read PASS, because the scorecard does not block. With the deflated Sharpe out, {rate('PASS and green, no book', 'best of 100'):.0%} of the best of 100 random strategies get PASS and all green. And a card at 0bp is charged nothing, so PASS there says nothing about trading costs.", "body")], WARN),
     P("Thresholds came from simulations and were committed (fb6bdc7) before Clenow was scored on them. To be open about it: I had already seen Clenow's zero-cost P of 0.054 when I eased the bar past it. Formulas and curves: financial-metrics-and-gate-b-v2.pdf. gate-b-v2-calibration.pdf is the earlier proposal.", "small"),
     KeepTogether([P("Clenow's latest run: v1 against v2", "H2"), TBL(cl, [0.24, 0.36, 0.4]), TBL(sw, [0.34] + [0.66 / (len(sw[0]) - 1)] * (len(sw[0]) - 1))]),
     TBL(core_rows, [0.5, 0.28, 0.22]),
     P(f"Daily returns, trades and holdings are byte-identical to the earlier runs of this card. Turnover {ch['annual_turnover']:.2f} times capital a year. Breakeven is beyond the sweep.", "small"),
     P("Every past run: v1 against v2", "H2"),
     P(f"All {len(vv)} runs failed v1. Under v2, each at its own card's cost, {n_pass} pass and {len(vv) - n_pass} fail. Most of the passes are runs of the same Clenow card. Full detail: docs/gate_b/v1_vs_v2.csv."),
     TBL(rr, [0.24, 0.15, 0.07, 0.08, 0.09, 0.07, 0.3], boldfirst=False),
     P("Dashboard check", "H2"),
     P(f"I opened the re-run in a real browser on the final code: <b>{n_ok} of {n_all}</b> checks pass, with no script errors. Excel, after recalculation, matches the page on CAGR, volatility, Sharpe, drawdown, Sortino and Calmar. Run it again with scripts/gate_v2/check_dashboard.py."),
     P("Problems found and fixed", "H2"),
     TBL([["Problem", "Cause", "Fix"],
          ["The gate charged 30bp on a 0bp card", "A rule in the brief, which I applied over your Gate A ruling instead of raising the conflict", "Card only"],
          ["The Results page returned a server error at 0bp", "<b>My bug.</b> Breakeven is infinite when the edge never reaches zero, and the page cannot carry that", "Shows blank, and no value can do this again"],
          ["Turnover read 10.33 and 10.26", "<b>My bug.</b> The first day's purchases were dropped", "Counted on the first day"],
          ["Older runs said \"Sharpe\" but showed the old 6% number", "My relabel", "Labelled as the old formula, with a note to press Rebuild"],
          ["7 rule-specific rows sat in Costs &amp; execution", "Written during the run", "Lightyear moves them to Diagnostics"],
          ["A factor equal to the strategy gave alpha t 17.6", "A series regressed on itself", "An identical factor is left out, and the row says so"]], [0.34, 0.36, 0.3]),
     P("Still open", "H2"),
     TBL([["Item", "Why it matters"],
          ["Claude's written text on this run still says \"the 30bp house floor\", in its strengths, weaknesses and notes", "Written before the instruction changed. Future runs are told not to. Nothing enforces prose, as with \"Evidence supports\""],
          ["Mandate, capacity and book tests show not run", "A PASS has not been tested on these. Filling in config/fund.yaml and config/mandate.yaml switches them on"],
          ["The Gate B brief and \"Evidence supports\" are written from the v1 checklist", "They can disagree with the v2 status above them. Labelled on the page"],
          ["Each run can still add its own rows", "\"Rolling one-year behind\" can show two values. Runs are told not to, but nothing enforces it"],
          ["Older runs show v2 only after Rebuild", "The table above scores them all, but their pages need Rebuild"],
          ["config/calibration.yaml still holds 6% and 30bp", "For the simulations only. No strategy run reads it"],
          ["Your usual Lightyear on port 8100", "It is on the old branch, and was not running when I last checked"]], [0.5, 0.5], boldfirst=False)]
doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=50, rightMargin=50, topMargin=44, bottomMargin=48, title="Gate B v2 and metrics: change log", author=SIGN, subject="What changed, why, and what the re-run and dashboard check showed")
doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(50, 48, W, A4[1] - 92, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=footer)])
doc.build(E)
print("OK", OUT, os.path.getsize(OUT))
