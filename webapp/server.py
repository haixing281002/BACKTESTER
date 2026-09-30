"""Local dashboard backend -- runs on YOUR machine, against YOUR local
data files, with no sandbox restrictions.

    pip install -r webapp/requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...          # only needed for /api/analyze
    python webapp/server.py
    # open http://127.0.0.1:8000

What this does and does not do:
  - /api/cards and /api/library read the REAL files this repo's own
    pipeline already writes (cards/*.yaml, outputs/library/*.json) --
    nothing here invents a number or a card.
  - /api/analyze runs the REAL Stage 01-03 agentic pipeline
    (ros.agents.orchestrator.AgenticPipeline, the same code run_agentic.py
    uses) against an uploaded PDF. This needs a real ANTHROPIC_API_KEY --
    it never silently falls back to the replay fixture, because a local
    dashboard returning canned devanathan-fixture output for a paper you
    actually dropped would be a much worse failure than a clear error.
  - Nothing here runs Step 05-08 (the actual backtest). That still means
    running run_pipeline.py or one of scripts/*_backtest.py from a
    terminal, same as always -- this dashboard reads whatever those
    produce, it doesn't replace them. A future version could shell out to
    them from a button; not built here.
"""
from __future__ import annotations

import glob
import os
import sys
import tempfile
import traceback
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ros.cards.schema import CardValidationError, load_card
from ros.governance.library import StrategyLibrary

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_DIR = os.path.join(REPO_ROOT, "cards")
OUTPUTS_DIR = os.path.join(REPO_ROOT, "outputs")
UPLOADS_DIR = os.path.join(OUTPUTS_DIR, "uploads")
AGENTIC_OUT_DIR = os.path.join(OUTPUTS_DIR, "agentic")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Pipeline Desk (local)")


@app.get("/api/health")
def health():
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return {"ok": True, "repo_root": REPO_ROOT, "anthropic_key_present": has_key}


# ---------------------------------------------------------------------
# Real Strategy Cards from cards/*.yaml
# ---------------------------------------------------------------------
@app.get("/api/cards")
def list_cards() -> List[Dict[str, Any]]:
    out = []
    for path in sorted(glob.glob(os.path.join(CARDS_DIR, "*.yaml"))):
        card_id = os.path.splitext(os.path.basename(path))[0]
        try:
            card = load_card(path)
            facts = [
                {"group": f.group, "label": f.label, "value": f.value,
                 "detail": f.detail, "flag": f.flag, "ref": f.ref}
                for f in card.facts()
            ]
            out.append({
                "id": card.paper.id,
                "title": card.paper.title,
                "mode": card.intent.mode,
                "valid": True,
                "path": os.path.relpath(path, REPO_ROOT),
                "facts": facts,
            })
        except (CardValidationError, Exception) as exc:  # noqa: BLE001
            # A card mid-draft is real and worth showing -- just flagged as
            # not-yet-validating, never silently dropped from the list.
            try:
                raw = yaml.safe_load(open(path, encoding="utf-8")) or {}
                title = ((raw.get("paper") or {}).get("title")) or card_id
                mode = ((raw.get("intent") or {}).get("mode")) or "unknown"
            except Exception:  # noqa: BLE001
                title, mode = card_id, "unknown"
            out.append({
                "id": card_id, "title": title, "mode": mode, "valid": False,
                "path": os.path.relpath(path, REPO_ROOT),
                "facts": [{"group": "VERDICT", "label": "Schema validation",
                          "value": "DOES NOT VALIDATE", "detail": str(exc), "flag": "BLOCK", "ref": ""}],
            })
    return out


# ---------------------------------------------------------------------
# Real Strategy Library entries from outputs/library/*.json
# ---------------------------------------------------------------------
@app.get("/api/library")
def list_library() -> List[Dict[str, Any]]:
    lib = StrategyLibrary(os.path.join(OUTPUTS_DIR, "library"))
    entries = lib.all()
    entries.sort(key=lambda e: e.get("created_utc", ""), reverse=True)
    return entries


# ---------------------------------------------------------------------
# Real Stage 01-03 agentic run on an uploaded PDF
# ---------------------------------------------------------------------
@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), mode: str = Form("adaptation"),
                  notes: str = Form("")) -> Dict[str, Any]:
    if mode not in ("replication", "adaptation"):
        raise HTTPException(400, "mode must be 'replication' or 'adaptation'")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if not has_key:
        raise HTTPException(
            400,
            "ANTHROPIC_API_KEY is not set in this environment. This endpoint runs the "
            "real Stage 01-03 agentic pipeline and refuses to silently substitute the "
            "replay fixture for a paper you actually uploaded -- set the key and restart "
            "the server.")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "only PDF uploads are analyzed (this stage reads the rendered document)")

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(AGENTIC_OUT_DIR, exist_ok=True)
    pdf_path = os.path.join(UPLOADS_DIR, file.filename)
    with open(pdf_path, "wb") as fh:
        fh.write(await file.read())

    try:
        from ros.agents.orchestrator import AgenticPipeline
        pipe = AgenticPipeline(mode="live")
        res = pipe.run_interpretation(pdf_path, mode, AGENTIC_OUT_DIR)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"agentic run failed: {exc}\n{traceback.format_exc()}")

    result = res.to_dict()
    result["notes_from_submitter"] = notes
    result["pdf_saved_at"] = os.path.relpath(pdf_path, REPO_ROOT)
    return result


# ---------------------------------------------------------------------
# Static output files (tearsheets, charts, decile workbooks, ...) so the
# dashboard can link to whatever scripts/*_backtest.py or run_pipeline.py
# already produced, without copying them anywhere.
# ---------------------------------------------------------------------
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    print(f"Repo root: {REPO_ROOT}")
    print(f"Cards dir: {CARDS_DIR}  ({len(glob.glob(os.path.join(CARDS_DIR, '*.yaml')))} card(s))")
    lib_dir = os.path.join(OUTPUTS_DIR, "library")
    print(f"Library dir: {lib_dir}  ({len(glob.glob(os.path.join(lib_dir, '*.json')))} entr(y/ies))")
    print("Open http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
