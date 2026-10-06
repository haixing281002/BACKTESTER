# Lightyear

The whole paper-to-Gate-B pipeline on one local web page.

```
python -m lightyear              # opens http://127.0.0.1:8100 (local only)
python -m lightyear --port 8200 --no-browser
```

Needs: `fastapi`, `uvicorn`, `python-multipart` (see `webapp/requirements.txt`), the Claude Code CLI
(found on PATH or inside the VS Code extension; override with `LIGHTYEAR_CLAUDE`), and LibreOffice for the
workbook recalc (`~\LibreOffice\program\soffice.exe`, or set `SOFFICE`). **No API key**: Claude Code runs
headless on your own login.

## What happens

| Step | Who | What you see |
|---|---|---|
| Upload a PDF (or pick one in `docs/papers`) | you | the run appears in the sidebar |
| Stages 00, 01, 02, data map, Gate A assembly | Claude Code, headless | stage tracker + live log |
| **Gate A** | you | plain summary, universe, data verdict, card YAML, Gate A document, local path to the card. *Approve* (with optional notes for the backtest) or *Revise the card* |
| Stages 03 to 07, Gate B brief | Claude Code, headless | stage tracker + live log |
| Charts + workbook | Lightyear (deterministic Python) | interactive charts (growth, drawdown, rolling vol, calendar year, monthly heatmap), KPI tiles, validation table, **Download Excel** |
| **Gate B** | you | criteria PASS/FAIL, evidence supports, the brief; pick APPROVE / OBSERVE / FIX / REJECT, name, rationale |

Ticking *Don't wait at Gate A* when starting shows Gate A and carries straight on (CLAUDE.md's
non-blocking Gate A). Gate B always stops.

## How it is put together

- `server.py`: FastAPI on 127.0.0.1. One run at a time (Screener allows one session; backtests are heavy).
- `jobs.py`: the run state machine and the Claude Code driver
  (`claude -p --output-format stream-json`, tools limited: no git, no rm, no web, no pip).
  Claude prints `LIGHTYEAR-STAGE: <id>` as each stage starts; that drives the tracker.
- `prompts.py`: the two phase prompts and the hand-off **contract**:
  - Phase A writes `outputs/lightyear/<run>/phase_a.json` (card path, Gate A doc, summary, verdicts).
  - Phase B writes `daily_returns.csv` (date, strategy, benchmark[, sleeve]) and `results.json`
    (`gate_b()` dict with decision PENDING, validation, tables, assumptions, notes).
- `contract.py`: checks those files before anything is shown (no percentages-as-fractions mix-ups, no model decision).
- `charts.py`: chart series and KPIs, same definitions as the workbook formulas (a test holds them equal).
- `workbook.py`: the colour-coded workbook (named-range formulas, Gate B fills, colour key, Excel charts),
  then `scripts/xlsx_recalc_libreoffice.py`.
- Everything is on disk under `outputs/lightyear/<run>/` (`state.json`, `log.jsonl`, hand-offs, `charts.json`,
  the workbook, `decision.json`). Decisions are also appended to `outputs/lightyear/decisions.jsonl`.
  A server restart marks a running phase *interrupted*; **Resume** re-runs that phase.

## Usage notes

- A full paper is two long Claude Code sessions. They count against your Claude plan's usage limits; the
  dollar figure shown is Claude Code's computed estimate, not a bill.
- The Gate B decision is recorded by Lightyear in the run folder and the ledger. For a card that
  `run_pipeline.py` itself can run, the same decision can also be written into the pipeline's library with
  `python run_pipeline.py --card <card> --decision ... --decided-by ... --rationale ...`.
- Tests: `python -m pytest tests/test_lightyear.py` (uses `tests/fake_claude.py`, no model or data).
