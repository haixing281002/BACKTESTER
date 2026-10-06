"""Run state machine and the headless Claude Code driver.

States:  phase_a -> gate_a -> phase_b -> building -> gate_b -> decided
         (any of them can end in stopped / failed / cancelled / interrupted)

Everything about a run is on disk under outputs/lightyear/<run_id>/: state.json, log.jsonl, the hand-off
files, charts.json and the workbook, so a server restart loses nothing but the live process.
One run at a time: Screener's rules allow one session, and the backtests are heavy.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid

from . import charts, contract, gates, prompts, workbook
from .paths import LEDGER, REPO, RUNS, find_claude, rel, run_dir

ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "TodoWrite", "Skill",
                 "Bash(python:*)", "Bash(python3:*)", "Bash(py:*)", "Bash(ls:*)", "Bash(mkdir:*)",
                 "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)", "Bash(echo:*)", "Bash(tee:*)",
                 "Bash(grep:*)", "Bash(sort:*)", "Bash(find:*)", "Bash(cd:*)"]
DISALLOWED_TOOLS = ["Bash(git:*)", "Bash(rm:*)", "Bash(curl:*)", "Bash(pip:*)", "WebFetch", "WebSearch"]
STAGE_RE = re.compile(r"LIGHTYEAR-STAGE:\s*([0-9A-Za-z]+)")
# looser signals, used only to move the tracker forward by at most two stages:
BANNER_RE = re.compile(r"\bSTAGE\s+0?([0-7])\b")                        # script banners: "STAGE 05 -- BUILD"
LEAD_RE = re.compile(r"^\W{0,4}(?:Stage|Step)\s+0?([0-7])\b", re.M)    # a message that opens "Stage 5 ..."
RUNNING = ("phase_a", "phase_b", "building", "revising")
IDS_A = [s for s, _ in prompts.STAGES_A]
IDS_B = [s for s, _ in prompts.STAGES_B]
ORDER = IDS_A + IDS_B
# minutes per stage before Lightyear has timed any real runs; replaced by medians of past runs as they finish
DEFAULT_MIN = {"00": 3, "01": 3, "02": 5, "03m": 2, "GA": 3, "03": 4, "04": 6, "05": 15, "06": 8, "07": 5, "GB": 4}

_lock = threading.RLock()
_procs = {}            # run_id -> Popen


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ state on disk
def state_path(rid):
    return os.path.join(run_dir(rid), "state.json")


def load(rid):
    # Under the same lock as save(): on Windows, os.replace fails while another thread holds the file open.
    for attempt in range(20):
        try:
            with _lock, open(state_path(rid), encoding="utf-8") as f:
                return json.load(f)
        except (PermissionError, json.JSONDecodeError):
            if attempt == 19:
                raise
            time.sleep(0.05)


def save(st):
    with _lock:
        st["updated"] = now()
        p = state_path(st["id"])
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=1, default=str)
        for attempt in range(20):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:          # a reader outside this process (antivirus, an editor) has it open
                if attempt == 19:
                    raise
                time.sleep(0.05)


def update(rid, **kw):
    with _lock:
        st = load(rid)
        st.update(kw)
        save(st)
        return st


def log(rid, kind, msg, **extra):
    t = now()
    with _lock:
        with open(os.path.join(run_dir(rid), "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": t, "kind": kind, "msg": msg, **extra}, default=str) + "\n")
        # the same log, human-readable, refreshed with every event of every run
        text = msg if kind != "tool_out" else msg[-600:]
        with open(os.path.join(run_dir(rid), "run.log"), "a", encoding="utf-8") as f:
            f.write(f"{t[11:]} [{kind:<10}] " + str(text).replace("\n", "\n" + " " * 22) + "\n")


def read_log(rid, after=0):
    p = os.path.join(run_dir(rid), "log.jsonl")
    if not os.path.exists(p):
        return [], 0
    lines = open(p, encoding="utf-8").read().splitlines()
    return [json.loads(x) for x in lines[after:] if x.strip()], len(lines)


def list_runs():
    out = []
    if os.path.isdir(RUNS):
        for rid in os.listdir(RUNS):
            if os.path.exists(os.path.join(RUNS, rid, "state.json")):
                try:
                    st = load(rid)
                    out.append({k: st.get(k) for k in ("id", "slug", "paper_title", "status", "created", "updated",
                                                       "operator", "decision")})
                except Exception:
                    pass
    return sorted(out, key=lambda s: s.get("created") or "", reverse=True)


def active_run():
    for r in list_runs():
        if r["status"] in RUNNING:
            return r["id"]
    return None


def recover_interrupted():
    """On server start: a run left 'running' has no process any more."""
    for r in list_runs():
        if r["status"] in RUNNING:
            update(r["id"], status="interrupted", error="The server stopped while this phase was running. "
                   "Resume the phase from the page.", resume_from=r["status"])
            log(r["id"], "server", "Marked interrupted: the server restarted mid-phase.")


# ------------------------------------------------------------------ creating a run
def create(pdf_rel, slug, operator, model, auto_continue):
    rid = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    os.makedirs(run_dir(rid), exist_ok=True)
    stages = {sid: "pending" for sid, _ in prompts.STAGES_A + prompts.STAGES_B}
    st = {"id": rid, "slug": slug, "pdf": pdf_rel, "operator": operator, "model": model or "",
          "auto_continue": bool(auto_continue), "created": now(), "status": "phase_a", "stages": stages,
          "current_stage": None, "paper_title": None, "phase_a": None, "approval": None, "results": None,
          "decision": None, "error": None, "cost_usd": 0.0, "sessions": []}
    save(st)
    log(rid, "server", f"Run created for {pdf_rel} (operator {operator}).")
    return rid


# ------------------------------------------------------------------ the Claude Code driver
def _summarise_tool(name, inp):
    if name == "Bash":
        return f"$ {str(inp.get('command', ''))[:300]}"
    if name in ("Read", "Write", "Edit"):
        return f"{name} {os.path.relpath(inp.get('file_path', ''), REPO) if inp.get('file_path') else ''}"
    if name in ("Glob", "Grep"):
        return f"{name} {inp.get('pattern', '')}"
    if name == "TodoWrite":
        todos = inp.get("todos", [])
        return "Plan: " + "; ".join(f"[{t.get('status', '')[:1]}] {t.get('content', '')}" for t in todos)[:400]
    return f"{name} {json.dumps(inp)[:200]}"


def _mark_stage(rid, sid, phase_ids, loose=False):
    """Move the tracker forward to `sid`. Never backwards; a loose signal moves at most two stages."""
    with _lock:
        st = load(rid)
        if sid not in phase_ids:
            return
        cur = st.get("current_stage")
        ci = phase_ids.index(cur) if cur in phase_ids else -1
        ni = phase_ids.index(sid)
        if ni <= ci or (loose and ni - ci > 2):
            return
        t = now()
        times = st.setdefault("stage_times", {})
        for s in phase_ids[:ni]:
            if st["stages"].get(s) != "done":
                st["stages"][s] = "done"
                times.setdefault(s, {}).setdefault("start", t)
                times[s]["end"] = t
        st["stages"][sid] = "running"
        times[sid] = {"start": t}
        st["current_stage"] = sid
        save(st)
    log(rid, "stage", f"Stage {sid} started", stage=sid)


def _detect(rid, text, phase_ids, source):
    for m in STAGE_RE.finditer(text or ""):
        _mark_stage(rid, m.group(1), phase_ids)
    rx = BANNER_RE if source == "tool" else LEAD_RE
    for m in rx.finditer(text or ""):
        d = m.group(1)
        sid = "0" + d
        if sid in phase_ids:
            _mark_stage(rid, sid, phase_ids, loose=True)


def _finish_stages(rid, ids):
    with _lock:
        st = load(rid)
        t = now()
        times = st.setdefault("stage_times", {})
        for s in ids:
            if st["stages"].get(s) in ("running", "pending"):
                st["stages"][s] = "done"
                times.setdefault(s, {}).setdefault("start", t)
                times[s]["end"] = t
        save(st)


# ------------------------------------------------------------------ ETA
_est_cache = {"t": 0, "v": None}


def stage_estimates():
    """Median minutes per stage over every finished stage of every past run, falling back to DEFAULT_MIN."""
    if _est_cache["v"] is not None and time.time() - _est_cache["t"] < 60:
        return _est_cache["v"]
    samples = {s: [] for s in ORDER}
    if os.path.isdir(RUNS):
        for rid in os.listdir(RUNS):
            p = os.path.join(RUNS, rid, "state.json")
            if not os.path.exists(p):
                continue
            try:
                times = load(rid).get("stage_times", {})
            except Exception:
                continue
            for s, tt in times.items():
                if s in samples and tt.get("start") and tt.get("end"):
                    m = (dt.datetime.fromisoformat(tt["end"]) - dt.datetime.fromisoformat(tt["start"])).total_seconds() / 60
                    if 0.1 <= m <= 240:
                        samples[s].append(m)
    est = {}
    for s in ORDER:
        xs = sorted(samples[s])
        est[s] = xs[len(xs) // 2] if xs else DEFAULT_MIN[s]
    _est_cache.update(t=time.time(), v=(est, {s: len(samples[s]) for s in ORDER}))
    return _est_cache["v"]


def eta(st):
    """Minutes left until the next gate, and elapsed time in the current stage."""
    status = st.get("status")
    if status == "building":
        return {"phase": "Building charts and workbook", "minutes_left": 1, "phase_total": 1, "until": "Gate B",
                "stage_elapsed": None, "learned_from": 0}
    if status not in ("phase_a", "phase_b", "revising"):
        return None
    ids = IDS_B if status == "phase_b" else IDS_A
    est, n = stage_estimates()
    cur = st.get("current_stage") if st.get("current_stage") in ids else None
    elapsed = 0.0
    if cur and (st.get("stage_times", {}).get(cur) or {}).get("start"):
        elapsed = (dt.datetime.now() - dt.datetime.fromisoformat(st["stage_times"][cur]["start"])).total_seconds() / 60
    ci = ids.index(cur) if cur else -1
    left = sum(est[s] for s in ids[ci + 1:])
    if cur:
        left += max(0.5, est[cur] - elapsed)
    return {"phase": "Stages 00 to Gate A" if ids is IDS_A else "Stages 03 to Gate B", "until": "Gate A" if ids is IDS_A else "Gate B",
            "minutes_left": round(left, 1), "phase_total": round(sum(est[s] for s in ids), 1),
            "stage_elapsed": round(elapsed, 1), "stage_estimate": round(est[cur], 1) if cur else None,
            "learned_from": sum(n[s] for s in ids)}


def _set_activity(rid, txt):
    """The latest plain-English line from Claude, shown on the page as 'what is happening now'."""
    lines = [l.strip(" *#>-") for l in txt.splitlines() if l.strip() and not STAGE_RE.search(l)]
    if not lines:
        return
    msg = " ".join(lines)
    msg = re.sub(r"`([^`]*)`", r"\1", msg)
    update(rid, activity=(msg[:277] + "...") if len(msg) > 280 else msg, activity_at=now())


def run_claude(rid, prompt, label, phase_ids):
    """Run one headless Claude Code session to completion, streaming its events into the run log.
    Returns (ok, result_text)."""
    claude = find_claude()
    st = load(rid)
    exe = [sys.executable, claude] if claude.endswith(".py") else [claude]   # .py = test stand-in
    cmd = [*exe, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
           "--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", *DISALLOWED_TOOLS]
    if st.get("model"):
        cmd += ["--model", st["model"]]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", LIGHTYEAR_RUN=rid)
    log(rid, "server", f"{label}: starting Claude Code headless ({os.path.basename(claude)}).")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
    _procs[rid] = proc
    proc.stdin.write(prompt)
    proc.stdin.close()
    result_text, ok = "", False
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            log(rid, "raw", line[:2000])
            continue
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            update(rid, sessions=load(rid)["sessions"] + [ev.get("session_id")])
            log(rid, "system", f"Session {ev.get('session_id', '')[:8]} on model {ev.get('model', '?')}")
        elif t == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    txt = block["text"]
                    _detect(rid, txt, phase_ids, "text")
                    _set_activity(rid, txt)
                    log(rid, "text", txt)
                elif block.get("type") == "tool_use":
                    inp = block.get("input", {}) or {}
                    if block.get("name") == "Bash":
                        _detect(rid, str(inp.get("command", "")), phase_ids, "cmd")
                    log(rid, "tool", _summarise_tool(block.get("name", "?"), inp))
        elif t == "user":
            for block in ev.get("message", {}).get("content", []) if isinstance(ev.get("message", {}).get("content"), list) else []:
                if block.get("type") == "tool_result":
                    c = block.get("content")
                    text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))
                    _detect(rid, text, phase_ids, "tool")
                    if block.get("is_error"):
                        log(rid, "tool_error", (text or "")[:1500])
                    elif text:
                        log(rid, "tool_out", text[-1500:])
        elif t == "result":
            ok = not ev.get("is_error") and ev.get("subtype") == "success"
            result_text = ev.get("result", "") or ""
            cost = float(ev.get("total_cost_usd") or 0)
            update(rid, cost_usd=round(load(rid).get("cost_usd", 0) + cost, 4))
            log(rid, "result", result_text[-4000:], ok=ok, turns=ev.get("num_turns"),
                minutes=round((ev.get("duration_ms") or 0) / 60000, 1))
    proc.wait()
    _procs.pop(rid, None)
    if proc.returncode not in (0, None) and not ok:
        log(rid, "error", f"Claude Code exited with code {proc.returncode}.")
    return ok, result_text


def cancel(rid):
    proc = _procs.get(rid)
    if proc and proc.poll() is None:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
    st = load(rid)
    update(rid, status="cancelled", error="Cancelled from the page.",
           resume_from=st["status"] if st["status"] in RUNNING else st.get("resume_from"))
    log(rid, "server", "Cancelled from the page.")


# ------------------------------------------------------------------ phases
def _fmt(template, rid, **kw):
    st = load(rid)
    return template.format(operator=st["operator"], pdf=st["pdf"], slug=st["slug"], run_dir=rel(run_dir(rid)), **kw)


def _after_phase_a(rid, ok, label):
    if load(rid)["status"] == "cancelled":
        return
    try:
        pa = contract.check_phase_a(run_dir(rid))
    except contract.ContractError as e:
        update(rid, status="failed", error=f"{label} did not hand back a valid phase_a.json: {e}", resume_from="phase_a")
        log(rid, "error", str(e))
        return
    _finish_stages(rid, [s for s, _ in prompts.STAGES_A])
    if pa["status"] == "stopped":
        update(rid, status="stopped", phase_a=pa, paper_title=pa.get("paper_title"), error=pa.get("reason"))
        log(rid, "server", f"Stopped before Gate A: {pa.get('reason')}")
        return
    st = update(rid, status="gate_a", phase_a=pa, paper_title=pa.get("paper_title"), current_stage="GA")
    log(rid, "gate", "Gate A assembled. Review the card on the page.")
    if st.get("auto_continue"):
        approve(rid, st["operator"], "(auto-continue: Gate A shown, not waited on)")


def phase_a(rid):
    ok, _ = run_claude(rid, _fmt(prompts.PHASE_A, rid), "Stages 00-02 + Gate A", IDS_A)
    _after_phase_a(rid, ok, "Phase A")


def revise_a(rid, notes):
    st = update(rid, status="revising", current_stage="03m", activity="Revising the card with your notes.")
    with _lock:
        s = load(rid)
        s["stages"]["GA"] = "pending"
        save(s)
    ok, _ = run_claude(rid, _fmt(prompts.REVISE_A, rid, card=st["phase_a"]["card_path"], notes=notes),
                       "Card revision + Gate A", IDS_A)
    _after_phase_a(rid, ok, "Revision")


def phase_b(rid):
    st = load(rid)
    if st.get("current_stage") not in IDS_B:
        update(rid, current_stage=None, activity="Starting the backtest stages.")
    ok, _ = run_claude(rid, _fmt(prompts.PHASE_B, rid, card=st["phase_a"]["card_path"],
                                 approver=st["approval"]["by"], notes=st["approval"].get("notes") or ""),
                       "Stages 03-07 + Gate B", IDS_B)
    if load(rid)["status"] == "cancelled":
        return
    build_outputs(rid)


def build_outputs(rid, review=True):
    """Deterministic: validate the hand-off, build charts.json and the workbook, recalc with LibreOffice."""
    update(rid, status="building", activity="Checking the results, drawing the charts and building the Excel workbook.")
    rd = run_dir(rid)
    try:
        res, df = contract.check_results(rd)
    except contract.ContractError as e:
        update(rid, status="failed", error=f"Phase B did not hand back valid results: {e}", resume_from="phase_b")
        log(rid, "error", str(e))
        return
    _finish_stages(rid, [s for s, _ in prompts.STAGES_B])
    extra, warn = contract.load_optional(rd, df["date"])
    for w in warn:
        log(rid, "error", f"Hand-off warning: {w}")
    names = {"strategy": res.get("strategy_name") or "Strategy", "benchmark": res.get("benchmark_name") or "NIFTY 500",
             "sleeve": res.get("sleeve_name") or "Sleeve"}
    ch = charts.build(df, names, comparators=extra.get("comparators"))
    json.dump(ch, open(os.path.join(rd, "charts.json"), "w", encoding="utf-8"), default=float)
    log(rid, "server", "Interactive chart series built from daily_returns.csv"
        + (" and comparators.csv." if "comparators" in extra else "."))
    recalc = _workbook(rid, res, df, extra, ch["observations"], _load_review(rd))
    res["gate_rows"] = gates.rows(res["gate_b"].get("criteria", []))
    update(rid, status="gate_b", current_stage="GB", results=res, recalc=recalc, handoff_warnings=warn,
           has_holdings="holdings" in extra, has_trades=("trades" in extra or "holdings" in extra),
           has_comparators="comparators" in extra)
    log(rid, "gate", "Gate B ready. A named human records the decision on the page.")
    if review and not os.environ.get("LIGHTYEAR_SKIP_REVIEW"):
        try:
            analyst_review(rid)
        except Exception as e:      # the review is extra; Gate B is already on the page
            update(rid, review_status="failed")
            log(rid, "error", f"Analyst review failed: {e}")


def _load_review(rd):
    p = os.path.join(rd, "review.json")
    try:
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    except (json.JSONDecodeError, OSError):
        return None


def _workbook(rid, res, df, extra, observations, review):
    """Build the workbook and recalculate it. Never loses the run over a workbook problem."""
    st = load(rid)
    rd = run_dir(rid)
    xlsx = os.path.join(rd, f"{st['slug']}_results.xlsx")
    title = f"{st.get('paper_title') or st['slug']}: India test"
    try:
        workbook.build(rd, res, df, title, xlsx, holdings=extra.get("holdings"), trades=extra.get("trades"),
                       comparators=extra.get("comparators"), observations=observations, review=review)
        update(rid, workbook=os.path.basename(xlsx))
        if os.environ.get("LIGHTYEAR_SKIP_RECALC"):
            return {"error": "recalc skipped (LIGHTYEAR_SKIP_RECALC set)"}
        log(rid, "server", "Workbook built; recalculating with LibreOffice.")
        p = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "xlsx_recalc_libreoffice.py"), xlsx],
                           capture_output=True, text=True, timeout=600)
        recalc = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {"error": (p.stderr or p.stdout)[-500:]}
        log(rid, "server", f"Recalc: {recalc.get('status', recalc.get('error'))}, "
            f"{recalc.get('total_formulas', '?')} formulas, {recalc.get('total_errors', '?')} errors.")
        return recalc
    except Exception as e:
        log(rid, "error", f"Workbook step failed: {e}")
        return {"error": str(e)}


def analyst_review(rid):
    """Claude reads the finished run and writes review.json: plain-English strengths, weaknesses, red flags.
    Runs after Gate B is shown (it never holds the page up) and never decides anything."""
    update(rid, review_status="running")
    log(rid, "server", "Analyst review: Claude is reading the results.")
    card = ((load(rid).get("phase_a") or {}).get("card_path")) or "(no card)"
    ok, _ = run_claude(rid, _fmt(prompts.REVIEW, rid, card=card), "Analyst review", [])
    rd = run_dir(rid)
    rev = _load_review(rd)
    if not rev:
        update(rid, review_status="failed")
        log(rid, "error", "Analyst review did not write a valid review.json.")
        return
    try:
        res, df = contract.check_results(rd)
        extra, _ = contract.load_optional(rd, df["date"])
        ch = json.load(open(os.path.join(rd, "charts.json"), encoding="utf-8"))
        recalc = _workbook(rid, res, df, extra, ch.get("observations"), rev)
        update(rid, review_status="done", recalc=recalc)
    except Exception as e:
        update(rid, review_status="done")
        log(rid, "error", f"Review saved, but the workbook refresh failed: {e}")
    log(rid, "server", "Analyst review ready.")


# ------------------------------------------------------------------ human actions
def approve(rid, by, notes=""):
    st = update(rid, approval={"by": by, "at": now(), "notes": notes}, status="phase_b")
    log(rid, "gate", f"Gate A approved by {by}.")
    start(phase_b, rid)
    return st


def decide(rid, decision, by, rationale):
    rec = {"run": rid, "decision": decision, "decided_by": by, "rationale": rationale, "at": now()}
    st = load(rid)
    rec.update(slug=st["slug"], card=(st.get("phase_a") or {}).get("card_path"), paper=st["pdf"],
               evidence_supports=(st.get("results") or {}).get("evidence_supports"))
    json.dump(rec, open(os.path.join(run_dir(rid), "decision.json"), "w", encoding="utf-8"), indent=1)
    os.makedirs(RUNS, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    update(rid, status="decided", decision=rec)
    log(rid, "gate", f"Gate B decision recorded: {decision} by {by}.")
    return rec


def start(fn, *args):
    def wrap():
        rid = args[0]
        try:
            fn(*args)
        except Exception as e:
            import traceback
            where = {phase_a: "phase_a", phase_b: "phase_b", build_outputs: "building", revise_a: "revising"}.get(fn)
            update(rid, status="failed", error=f"{type(e).__name__}: {e}", resume_from=where)
            log(rid, "error", traceback.format_exc()[-3000:])
    th = threading.Thread(target=wrap, daemon=True)
    th.start()
    return th
