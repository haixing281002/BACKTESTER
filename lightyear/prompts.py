"""Prompts for the two headless Claude Code phases, and the file contract each must satisfy.

Each phase prints `LIGHTYEAR-STAGE: <id>` lines as it starts a stage (the page turns those into the
stage tracker) and ends by writing a JSON hand-off file that the server validates. The model never
writes the workbook or the charts; the server builds those from the hand-off files.
"""

STAGES_A = [("00", "Triage"), ("01", "Ingest"), ("02", "Card + critique"), ("03m", "Data map"), ("GA", "Gate A")]
STAGES_B = [("03", "Data feasibility"), ("04", "Point-in-time data"), ("05", "Build + execute"),
            ("06", "Research validation"), ("07", "Portfolio validation"), ("GB", "Gate B brief")]

_COMMON = """You are running inside LIGHTYEAR, a local web front end for this repository's paper-to-backtest pipeline.
Nobody is watching this terminal: you cannot ask questions and nobody will answer. Where CLAUDE.md or a
.claude/commands file says to ask or wait, take the sensible documented default, record it, and carry on.

Hard rules (from CLAUDE.md, restated):
- Read CLAUDE.md first and follow it. The operator is {operator}.
- Data: NSE bhavcopy and Screener.in only (cached locally in cache/, scr/, data/raw/master/, declared in
  data/raw/MANIFEST.yaml), five years, plus the NIFTY 500 index workbook as the benchmark and a flat 6% hurdle.
  Do not fetch from any other source. Screener rules: public pages only, never log in, >=1.5 s between
  requests, one session, nothing in parallel. Prefer the cache; fetch only what is missing.
- Never run git commit, git push or any git command that changes the repository.
- Never record a Gate B decision. A named human does that on the Lightyear page.
- Presentation: strategy against NIFTY 500 only, at most one extra sleeve; comparators in an appendix.
- Each time you START a stage, print a line on its own exactly like:  LIGHTYEAR-STAGE: <id>
- If something is genuinely impossible (e.g. the paper fails triage, or the data does not exist in the two
  sources), say so plainly in the hand-off file instead of inventing a substitute.
"""

PHASE_A = _COMMON + """
YOUR JOB NOW: stages 00 through Gate A assembly for the paper  {pdf}  (slug: {slug}).
Stage ids for this phase: 00, 01, 02, 03m, GA.

Follow, in order: .claude/commands/triage.md (00), ingest.md (01), draft-card.md then critique-card.md (02;
fold material critique points back into the card yourself and re-validate), map-data.md (03m), gate-a.md (GA).
Record lineage with `python -m ros.interpretation validate/record` as those files say, operator "{operator}".
Write exactly one card: cards/{slug}.yaml. Save the Gate A document (the deterministic gate_a_document() output
plus card.plain_summary(), and anything a model adds, clearly marked) to
outputs/interpretation/{slug}__gate_a_queue.md.
STOP after Gate A. Do NOT start stage 03, do NOT run a backtest.

Finally write the hand-off file  {run_dir}/phase_a.json  with exactly these keys:
{{
  "status": "ok" | "stopped",            // "stopped" if triage rejects the paper or the card is BLOCKED and unfixable
  "reason": "<one sentence; why stopped, or empty>",
  "paper_title": "<title as printed on page 1>",
  "slug": "{slug}",
  "card_path": "cards/{slug}.yaml",       // repo-relative, or null if stopped before a card exists
  "gate_a_path": "outputs/interpretation/{slug}__gate_a_queue.md",
  "plain_summary": "<card.plain_summary() text>",
  "universe": "<the Indian universe chosen>",
  "data_verdict": "<what data the card needs and whether bhavcopy + Screener cover it>",
  "open_questions": ["<things a human at Gate A should look at>"],
  "files": ["<repo-relative path of every file this phase wrote>"]
}}
"""

PHASE_B = _COMMON + """
YOUR JOB NOW: stages 03 through Gate B assembly for the card  {card}  (paper {pdf}, slug {slug}).
Gate A was approved on the Lightyear page by {approver}. Operator notes from Gate A (may be empty):
<<<
{notes}
>>>
Stage ids for this phase: 03, 04, 05, 06, 07, GB.

Do the run the way .claude/commands/paper.md steps 7-9 describe (run.md, critique-results.md, gate-b.md).
If run_pipeline.py cannot run this card's mechanism (an individual-stock card usually needs its own script,
like scripts/lee_swaminathan_1998_india_backtest.py), write scripts/{slug}_india_backtest.py following that
example's conventions: causal signals (shift >= 1), costs and borrow applied, look-ahead tripwires, block-bootstrap
Sharpe interval, deflated Sharpe, walk-forward stability, a cost sensitivity, the factor fingerprint, and
Gate B criteria computed by ros.governance.gates.gate_b(). Use universal_backtester/clean_charts.py for charts.
Keep every number in code; never estimate a statistic in prose.

Then write these hand-off files into {run_dir}/ (the server builds the workbook and interactive charts from them):

1. daily_returns.csv  -- columns: date,strategy,benchmark[,sleeve]. Daily simple returns as fractions, the
   strategy NET of costs, benchmark = NIFTY 500. One row per trading day of the live period. `sleeve` only if
   one extra sleeve is genuinely important.
2. results.json with exactly these keys:
{{
  "strategy_name": "<short name of the strategy book>",
  "benchmark_name": "NIFTY 500",
  "sleeve_name": null | "<name>",
  "headline": "<one sentence: what this is and what the evidence supports>",
  "evidence_supports": "PROMOTE" | "OBSERVE" | "REJECT",
  "decisive_criterion": "<the Gate B criterion that matters most, named>",
  "gate_b": <gate_b(...).to_dict(), unchanged; its decision must be PENDING>,
  "validation": [{{"label": "...", "value": <number or string>, "format": "pct|num|int|text", "source": "<file or function>"}}],
  "tables": [{{"title": "<sheet title, <= 28 chars>", "csv": "<repo-relative csv path>", "note": "<source/caveat>"}}],
  "assumptions": [{{"label": "...", "value": <number>, "format": "pct|num|int", "note": "<source>"}}],
  "notes": ["<caveat a reader must see>"],
  "gate_b_brief_path": "outputs/interpretation/{slug}__gate_b_brief.md",
  "files": ["<repo-relative path of every file this phase wrote or read>"]
}}
"tables" should include the sensitivity / walk-forward / comparator CSVs your run wrote.
STOP after the Gate B brief. decision stays PENDING.
"""

REVISE_A = _COMMON + """
YOUR JOB NOW: revise the card {card} for paper {pdf} (slug {slug}) using the operator's Gate A notes below, then
re-validate it and re-assemble Gate A exactly as .claude/commands/gate-a.md says (stage id GA).
Operator notes:
<<<
{notes}
>>>
Overwrite outputs/interpretation/{slug}__gate_a_queue.md and rewrite {run_dir}/phase_a.json with the same keys
as before (status, reason, paper_title, slug, card_path, gate_a_path, plain_summary, universe, data_verdict,
open_questions, files). Do not start stage 03.
"""
