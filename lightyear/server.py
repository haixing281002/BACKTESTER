"""Lightyear HTTP server. Listens on 127.0.0.1 only: nobody else on the network can reach it."""
import json
import os
import shutil
from contextlib import asynccontextmanager
from typing import Optional

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, gates, jobs, prompts, workbook
from .paths import PAPERS, REPO, STATIC, find_claude, run_dir, slugify

def _code_fingerprint():
    """Modification times of Lightyear's Python files. If they change while the server runs, the page says
    'restart Lightyear': a running server keeps the old code (that is how a run once used stale prompts)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return {f: os.path.getmtime(os.path.join(here, f)) for f in sorted(os.listdir(here)) if f.endswith(".py")}


_BOOT_CODE = _code_fingerprint()


@asynccontextmanager
async def _lifespan(_app):
    os.makedirs(jobs.RUNS, exist_ok=True)
    jobs.recover_interrupted()
    yield


app = FastAPI(title="Lightyear", version=__version__, lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
DECISIONS = ("APPROVE", "OBSERVE", "FIX", "REJECT")


def _repo_file(rel):
    p = os.path.abspath(os.path.join(REPO, rel))
    if not p.startswith(os.path.abspath(REPO) + os.sep) or not os.path.isfile(p):
        raise HTTPException(404, f"not found: {rel}")
    return p


def _state(rid):
    try:
        return jobs.load(rid)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"no run {rid}")


def _busy_guard():
    a = jobs.active_run()
    if a:
        raise HTTPException(409, f"Run {a} is still working. Lightyear runs one paper at a time.")


@app.get("/", response_class=HTMLResponse)
def index():
    return open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()


@app.get("/api/health")
def health():
    try:
        claude = find_claude()
    except FileNotFoundError as e:
        claude = None
    lo = os.path.exists(os.path.expanduser(r"~\LibreOffice\program\soffice.exe")) or bool(os.environ.get("SOFFICE"))
    changed = [f for f, t in _code_fingerprint().items() if _BOOT_CODE.get(f) != t]
    return {"ok": True, "version": __version__, "repo": REPO, "claude": claude, "libreoffice": lo,
            "active_run": jobs.active_run(), "restart_needed": bool(changed), "changed_files": changed,
            "stages": {"A": prompts.STAGES_A, "B": prompts.STAGES_B}}


@app.get("/api/papers")
def papers():
    return sorted(f for f in os.listdir(PAPERS) if f.lower().endswith(".pdf"))


@app.get("/api/runs")
def runs():
    return jobs.list_runs()


@app.post("/api/runs")
async def new_run(operator: str = Form(...), model: str = Form(""), auto_continue: bool = Form(False),
                  existing: str = Form(""), pdf: Optional[UploadFile] = File(None)):
    _busy_guard()
    if not operator.strip():
        raise HTTPException(400, "Operator name is required.")
    if pdf is not None and pdf.filename:
        if not pdf.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Upload a PDF.")
        slug = slugify(pdf.filename)
        dest = os.path.join(PAPERS, f"{slug}.pdf")
        with open(dest, "wb") as f:
            shutil.copyfileobj(pdf.file, f)
    elif existing:
        if existing not in papers():
            raise HTTPException(400, f"Unknown paper {existing}")
        slug = slugify(existing)
        dest = os.path.join(PAPERS, existing)
    else:
        raise HTTPException(400, "Upload a PDF or pick one already in docs/papers. There is no default paper.")
    rid = jobs.create(os.path.relpath(dest, REPO).replace("\\", "/"), slug, operator.strip(),
                      model.strip(), auto_continue)
    jobs.start(jobs.phase_a, rid)
    return {"id": rid}


@app.get("/api/runs/{rid}")
def run_state(rid: str):
    st = _state(rid)
    pa = st.get("phase_a") or {}
    if pa.get("card_path"):
        try:
            st["card_yaml"] = open(_repo_file(pa["card_path"]), encoding="utf-8").read()
        except HTTPException:
            st["card_yaml"] = None
    if pa.get("gate_a_path"):
        try:
            st["gate_a_md"] = open(_repo_file(pa["gate_a_path"]), encoding="utf-8").read()
        except HTTPException:
            st["gate_a_md"] = None
    res = st.get("results") or {}
    if res.get("gate_b_brief_path"):
        try:
            st["gate_b_md"] = open(_repo_file(res["gate_b_brief_path"]), encoding="utf-8").read()
        except HTTPException:
            st["gate_b_md"] = None
    if res.get("gate_b"):
        res["gate_rows"] = gates.rows(res["gate_b"].get("criteria", []))
    rv = os.path.join(run_dir(rid), "review.json")
    if os.path.exists(rv):
        try:
            st["review"] = json.load(open(rv, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            st["review"] = None
    st["eta"] = jobs.eta(st)
    fp = os.path.join(run_dir(rid), "paper_facts.json")
    if os.path.exists(fp):
        try:
            st["paper_facts"] = json.load(open(fp, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            st["paper_facts"] = None       # half-written; next poll picks it up
    st["run_dir_abs"] = run_dir(rid)
    listed = {os.path.normpath(os.path.join(REPO, f)) for f in (pa.get("files") or []) + (res.get("files") or [])}
    here = {os.path.join(run_dir(rid), f) for f in os.listdir(run_dir(rid))
            if os.path.isfile(os.path.join(run_dir(rid), f)) and not f.endswith(".tmp")}
    st["files_abs"] = sorted(listed | here)
    st["run_log_abs"] = os.path.join(run_dir(rid), "run.log")
    return st


@app.get("/api/runs/{rid}/log")
def run_log(rid: str, after: int = 0):
    _state(rid)
    items, total = jobs.read_log(rid, after)
    return {"items": items, "next": total}


@app.get("/api/runs/{rid}/charts")
def run_charts(rid: str):
    p = os.path.join(run_dir(rid), "charts.json")
    if not os.path.exists(p):
        raise HTTPException(404, "charts not built yet")
    return json.load(open(p, encoding="utf-8"))


@app.get("/api/runs/{rid}/positions")
def run_positions(rid: str):
    """Holdings per rebalance and the trades between them, for the page's Positions tab."""
    import pandas as pd
    _state(rid)
    rd = run_dir(rid)
    out = {"holdings": [], "trades": []}
    hp, tp = os.path.join(rd, "holdings.csv"), os.path.join(rd, "trades.csv")
    if os.path.exists(hp):
        h = pd.read_csv(hp)
        if "leg" not in h.columns:
            h["leg"] = h["weight"].apply(lambda w: "long" if w > 0 else "short")
        out["holdings"] = h[["date", "symbol", "leg", "weight"]].to_dict("records")
        t = pd.read_csv(tp) if os.path.exists(tp) else workbook.derive_trades(h)
        t["date"] = pd.to_datetime(t["date"]).dt.strftime("%Y-%m-%d")
        out["trades"] = t[["date", "symbol", "action", "weight_before", "weight_after"]].to_dict("records")
        out["trades_derived"] = not os.path.exists(tp)
    return out


@app.post("/api/runs/{rid}/review")
def rerun_review(rid: str):
    st = _state(rid)
    if st["status"] not in ("gate_b", "decided"):
        raise HTTPException(409, "The analyst review runs on a finished backtest.")
    if st.get("review_status") == "running":
        raise HTTPException(409, "A review is already running.")
    _busy_guard()
    jobs.start(jobs.analyst_review, rid)
    return {"ok": True}


@app.post("/api/runs/{rid}/rebuild")
def rebuild(rid: str):
    """Rebuild charts and the workbook from the hand-off files (after a Lightyear update), without re-running Claude."""
    st = _state(rid)
    if st["status"] not in ("gate_b", "decided", "failed"):
        raise HTTPException(409, "Nothing to rebuild yet.")
    _busy_guard()
    keep = st["status"] if st["status"] == "decided" else None
    def go():
        jobs.build_outputs(rid, review=False)
        if keep:
            jobs.update(rid, status=keep)
    jobs.start(go, rid)
    return {"ok": True}


@app.get("/api/runs/{rid}/workbook")
def run_workbook(rid: str):
    st = _state(rid)
    if not st.get("workbook"):
        raise HTTPException(404, "workbook not built yet")
    p = os.path.join(run_dir(rid), st["workbook"])
    return FileResponse(p, filename=st["workbook"],
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/file", response_class=PlainTextResponse)
def repo_file(path: str):
    p = _repo_file(path)
    if os.path.getsize(p) > 2_000_000:
        raise HTTPException(413, "file too large to preview")
    return open(p, encoding="utf-8", errors="replace").read()


@app.get("/api/image")
def repo_image(path: str):
    p = _repo_file(path)
    if not p.lower().endswith((".png", ".jpg", ".jpeg", ".svg")):
        raise HTTPException(400, "not an image")
    return FileResponse(p)


class Approval(BaseModel):
    by: str
    notes: str = ""


class Revision(BaseModel):
    notes: str


class Decision(BaseModel):
    decision: str
    by: str
    rationale: str


@app.post("/api/runs/{rid}/approve")
def approve(rid: str, a: Approval):
    st = _state(rid)
    if st["status"] != "gate_a":
        raise HTTPException(409, f"Run is at {st['status']}, not Gate A.")
    if not a.by.strip():
        raise HTTPException(400, "A named human approves Gate A.")
    _busy_guard()
    jobs.approve(rid, a.by.strip(), a.notes)
    return {"ok": True}


@app.post("/api/runs/{rid}/revise")
def revise(rid: str, r: Revision):
    st = _state(rid)
    if st["status"] != "gate_a":
        raise HTTPException(409, "Revisions are made at Gate A.")
    if not r.notes.strip():
        raise HTTPException(400, "Say what should change.")
    _busy_guard()
    jobs.log(rid, "gate", f"Revision requested at Gate A: {r.notes}")
    jobs.start(jobs.revise_a, rid, r.notes)
    return {"ok": True}


@app.post("/api/runs/{rid}/decide")
def decide(rid: str, d: Decision):
    st = _state(rid)
    if st["status"] != "gate_b":
        raise HTTPException(409, f"Run is at {st['status']}, not Gate B.")
    if d.decision not in DECISIONS:
        raise HTTPException(400, f"decision must be one of {DECISIONS}")
    if not d.by.strip() or not d.rationale.strip():
        raise HTTPException(400, "A named human and a rationale are required.")
    return jobs.decide(rid, d.decision, d.by.strip(), d.rationale.strip())


@app.post("/api/runs/{rid}/cancel")
def cancel(rid: str):
    _state(rid)
    jobs.cancel(rid)
    return {"ok": True}


@app.post("/api/runs/{rid}/resume")
def resume(rid: str):
    """Re-run the phase that failed or was interrupted. Claude Code picks up from the files already on disk."""
    st = _state(rid)
    if st["status"] not in ("failed", "interrupted", "cancelled"):
        raise HTTPException(409, f"Nothing to resume at {st['status']}.")
    _busy_guard()
    where = st.get("resume_from") or ("phase_b" if st.get("approval") else "phase_a")
    if where == "building":
        jobs.update(rid, status="building", error=None)
        jobs.start(jobs.build_outputs, rid)
    elif where == "revising" and st.get("phase_a"):
        jobs.update(rid, status="gate_a", error=None)
        jobs.log(rid, "server", "Back at Gate A; the revision did not finish, request it again if needed.")
    elif where == "phase_b":
        jobs.update(rid, status="phase_b", error=None)
        jobs.log(rid, "server", "Resuming stages 03-07.")
        jobs.start(jobs.phase_b, rid)
    else:
        jobs.update(rid, status="phase_a", error=None)
        jobs.log(rid, "server", "Resuming stages 00-02.")
        jobs.start(jobs.phase_a, rid)
    return {"ok": True}
