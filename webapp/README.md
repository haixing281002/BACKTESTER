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
- **Not built here**: triggering Step 05-08 (the actual backtest) from
  the dashboard. That still means running `run_pipeline.py` or one of
  `scripts/*_backtest.py` from a terminal, same as always. Once you do,
  its outputs land in `outputs/` and the dashboard's static file mount
  (`/outputs/...`) can serve them -- wiring that into the UI (real
  tearsheets, real equity curves) is the natural next step.

## Files

- `server.py` -- FastAPI backend, three real endpoints (`/api/cards`,
  `/api/library`, `/api/analyze`) plus static file serving.
- `static/index.html` -- the dashboard itself. Self-contained, no build
  step, no external JS framework.
- `requirements.txt` -- the extra web-serving deps (`fastapi`, `uvicorn`,
  `python-multipart`) on top of what's already in the repo's own
  `requirements.txt`.
