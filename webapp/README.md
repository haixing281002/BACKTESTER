# Pipeline Desk (local)

A local dashboard that reads this repo's own real files -- no sample data,
no client-side LLM calls, no sandboxed capability API. Runs entirely on
your machine, against your local data.

## Run it

```bash
pip install -r webapp/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...     # only needed for the Analyze tab
python webapp/server.py
```

Open http://127.0.0.1:8000. In VS Code, just run that same command in an
integrated terminal, or use Live Server on `webapp/static/index.html` if
you'd rather serve the page separately (point `fetch()` calls at
`http://127.0.0.1:8000` if you do -- the file as shipped assumes same-origin).

## What's real, what isn't

- **Strategy Cards tab** -- reads `cards/*.yaml` live, through the same
  `load_card()` / `card.facts()` the actual pipeline and Gate A use. A card
  that doesn't validate still shows up, flagged, instead of being dropped.
- **Library tab** -- reads `outputs/library/*.json` live, through
  `ros.governance.library.StrategyLibrary`. Empty until you actually run a
  card through `run_pipeline.py`.
- **Analyze a Paper tab** -- runs the REAL Stage 01-03 agentic pipeline
  (`ros.agents.orchestrator.AgenticPipeline`, the same code
  `run_agentic.py` uses) against an uploaded PDF. Needs a real
  `ANTHROPIC_API_KEY`; the server refuses the request rather than
  silently falling back to the bundled replay fixture if the key isn't
  set -- a canned "devanathan" result for a paper you actually dropped
  would be a worse failure than a clear error.
- **Run Backtests tab** -- triggers the real CLI as a subprocess on this
  machine: `python run_pipeline.py --card <card> --auto-approve` for an
  index-sleeve (ros/engine) card, or one of the three individual-stock
  scripts (`accord_stock_selection_backtest.py`,
  `alquist_2018_india_small_cap_backtest.py`,
  `asness_2015_india_value_longshort_backtest.py`) for a card built on
  the Accord stock-level data. Pick the target that actually matches the
  card's mechanism -- `run_pipeline.py` cannot run an individual-stock
  selection card (see CLAUDE.md's "new-paper-backtest" note on why), so
  pointing it at the wrong one will run, but on the wrong universe. The
  log streams live; `--auto-approve` is the one, deliberate cost of
  triggering a multi-stage checkpointed script from a button instead of a
  terminal -- it skips every per-stage pause, but NEVER supplies a Gate B
  decision (`--decision`/`--decided-by`/`--rationale` are never passed
  here): a real run still stops at `decision: PENDING`, and a named human
  re-runs it from a terminal with those flags to actually rule on it.

## Files

- `server.py` -- FastAPI backend: `/api/cards`, `/api/library`,
  `/api/analyze`, `/api/run-targets` + `/api/runs` (start/list/poll a
  real backtest subprocess), plus static file serving.
- `static/index.html` -- the dashboard itself. Self-contained, no build
  step, no external JS framework.
- `requirements.txt` -- the extra web-serving deps (`fastapi`, `uvicorn`,
  `python-multipart`) on top of what's already in the repo's own
  `requirements.txt`.
