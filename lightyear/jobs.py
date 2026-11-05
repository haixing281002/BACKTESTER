# Quant AI Researcher by Harshil Pahuja
"""Run state machine and the headless Claude Code driver.

States:  phase_a -> gate_a -> phase_b -> building -> gate_b -> decided
         (any of them can end in stopped / failed / cancelled / interrupted)

Everything about a run is on disk under outputs/lightyear/<run_id>/: state.json, log.jsonl, the hand-off
files, charts.json and the workbook, so a server restart loses nothing but the live process.
One run at a time: the backtests are heavy and share one machine.

Gate A -> Gate B hand-off (fixed 2026-10-30 after the audit): every revision an operator asks for at Gate A is kept
in state.json["revisions"] and, with the approval box, is handed to the Phase B and review sessions and shown on the
page and in the workbook. Approval pins the card's sha256; build_outputs() refuses a run whose manifest.json disagrees
with the approved card. A session that ends in error, or a revision that writes nothing, fails the run loudly.
"""
import csv
import datetime as dt
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid

import pandas as pd

from ros import config
from ros.cards.schema import load_card
from ros.metrics import core

from . import changelog, charts, contract, gate_run, gates, prompts, spec_audit, wording, workbook
from .paths import LEDGER, REPO, RUNS, code_hash, find_claude, git_bash, git_commit, rel, run_dir

_log = logging.getLogger("lightyear")
STALL_MINUTES = float(os.environ.get("LIGHTYEAR_STALL_MINUTES", "60"))   # no output from Claude Code for this long = stuck

ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "TodoWrite", "Skill",
                 "Bash(python:*)", "Bash(python3:*)", "Bash(py:*)", "Bash(ls:*)", "Bash(mkdir:*)",
                 "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)", "Bash(echo:*)", "Bash(tee:*)",
                 "Bash(grep:*)", "Bash(sort:*)", "Bash(find:*)", "Bash(cd:*)"]
DISALLOWED_TOOLS = ["Bash(git:*)", "Bash(rm:*)", "Bash(curl:*)", "Bash(pip:*)", "WebFetch", "WebSearch"]
STAGE_RE = re.compile(r"LIGHTYEAR-STAGE:\s*([0-9A-Za-z]+)")
# looser signals, used only to move the tracker forward by at most two stages:
BANNER_RE = re.compile(r"\bSTAGE\s+0?([0-7])\b")                        # script banners: "STAGE 05 -- BUILD"
LEAD_RE = re.compile(r"^\W{0,4}(?:Stage|Step)\s+0?([0-7])\b", re.MULTILINE)    # a message that opens "Stage 5 ..."
RUNNING = ("phase_a", "phase_b", "building", "revising")
DATA_MODE = ("- DATA MODE: the three files above are the whole data universe. No web request of any kind. Before\n"
             "  stage 03 run  python -m ros.data.sources  and quote its three lines in the data map so the operator\n"
             "  sees which files (and how old) the run used.")
IDS_A = [s for s, _ in prompts.STAGES_A]
IDS_B = [s for s, _ in prompts.STAGES_B]
ORDER = IDS_A + IDS_B
# minutes per stage before Lightyear has timed any real runs; replaced by medians of past runs as they finish
DEFAULT_MIN = {"00": 3, "01": 3, "02": 5, "03m": 2, "GA": 3, "03": 4, "04": 6, "05": 15, "06": 8, "07": 5, "GB": 4}

_lock = threading.RLock()
_procs = {}            # run_id -> Popen


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _sha(path):
    """sha256 of a file, or None when it does not exist (repo-relative paths resolve against REPO)."""
    p = path if os.path.isabs(path) else os.path.join(REPO, path)
    if not os.path.isfile(p):
        return None
    return contract.sha256_file(p)


def operator_notes(st):
    """Every instruction a human typed at Gate A, in order: each card revision, then the approval box. This is what
    Phase B and the analyst review receive; before 2026-10-30 only the approval box was handed on."""
    parts = [f"[card revision {i + 1}, asked {r.get('at', '?')}] {r.get('notes', '')}"
             for i, r in enumerate(st.get("revisions") or [])]
    ap = st.get("approval") or {}
    if ap.get("notes"):
        parts.append(f"[approval box, {ap.get('at', '?')}] {ap['notes']}")
    return "\n".join(parts) if parts else "(none)"


def provenance(st, boot_hash=None):
    """What a reader needs to tell a fresh result from a stale one: run id, when it was created, the card and its sha
    (as approved and as on disk now), the script sha from manifest.json, and the code version (server and disk)."""
    rid = st["id"]
    rd = run_dir(rid)
    card_path = (st.get("phase_a") or {}).get("card_path") or ""
    man = {}
    mp = os.path.join(rd, "manifest.json")
    if os.path.exists(mp):
        try:
            man = json.load(open(mp, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            man = {}
    return {"run_id": rid, "created": st.get("created"), "rerun_of": st.get("rerun_of"),
            "card_path": card_path, "card_sha256_approved": (st.get("approval") or {}).get("card_sha256"),
            "card_sha256_on_disk": _sha(card_path) if card_path else None,
            "card_sha256_run": ((man.get("inputs") or {}).get("card") or {}).get("sha256"),
            "script_sha256": (man.get("script") or {}).get("sha256"), "manifest_written_at": man.get("written_at"),
            "code_hash_server": boot_hash, "code_hash_disk": code_hash(), "git_commit": git_commit(),
            "workbook": st.get("workbook")}


def _load_json_list(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, list) else None
    except (json.JSONDecodeError, OSError):
        return None


def revisions_from_log(rid):
    """Backfill for runs created before revisions were persisted: read them back from log.jsonl's gate events."""
    out = []
    for e in read_log(rid)[0]:
        if e.get("kind") == "gate" and str(e.get("msg", "")).startswith("Revision requested at Gate A: "):
            out.append({"at": e.get("t"), "notes": e["msg"][len("Revision requested at Gate A: "):], "source": "log.jsonl"})
    return out


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
                except Exception as e:                                    # noqa: BLE001
                    _log.warning("run %s: state.json unreadable, left out of the run list (%r)", rid, e)
    return sorted(out, key=lambda s: s.get("created") or "", reverse=True)


def active_run():
    for r in list_runs():
        if r["status"] in RUNNING:
            return r["id"]
    return None


def _pid_alive(pid, names=None):
    """Is this pid running and, when names is given, is its image one of them (claude, node, python)?
    The name check guards against a recycled pid belonging to something else."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                             capture_output=True, text=True).stdout
        rows = [r for r in csv.reader(out.splitlines()) if len(r) > 1 and r[1].strip() == str(pid)]
        if not rows:
            return False
        image = rows[0][0].lower()
    else:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
                image = fh.read().strip().lower()
        except OSError:
            image = ""
    return True if names is None else any(image.startswith(n.lower()) for n in names)


def _kill(pid):
    """Kill a process and, on Windows, its whole tree (the headless session spawns bash and python children)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass


def recover_interrupted():
    """On server start: a run left 'running' has no live driver any more. If the Claude Code child it last
    started (pid in state.json) outlived the old server, kill it, so two sessions never write into one run."""
    for r in list_runs():
        if r["status"] in RUNNING:
            pid = load(r["id"]).get("pid")
            if pid and _pid_alive(pid, names=("claude", "node", "python")):
                _kill(pid)
                log(r["id"], "server", f"Killed orphaned Claude Code process {pid} left by the previous server.")
            update(r["id"], status="interrupted", pid=None, error="The server stopped while this phase was running. "
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
            except Exception as e:                                    # noqa: BLE001
                _log.warning("run %s: state.json unreadable, skipped for the time estimate (%r)", rid, e)
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
    if sys.platform == "win32":
        # PowerShell can be blocked by Group Policy (uv_spawn EUNKNOWN); force Git Bash instead. The path is
        # discovered (env, ~/.claude/settings.json, PATH, install folders), never hard-coded to one machine.
        bash = git_bash()
        if bash:
            env["CLAUDE_CODE_GIT_BASH_PATH"] = bash
        else:
            log(rid, "server", "Git Bash not found. If Claude Code fails to start, set CLAUDE_CODE_GIT_BASH_PATH.")
        env["CLAUDE_CODE_USE_POWERSHELL_TOOL"] = "0"
    # Put this interpreter first on PATH: Git Bash does not see the Windows Python install, and calling python.exe by
    # its full path does not match the "Bash(python:*)" allow rule, so every Python call would need an approval.
    pydir = os.path.dirname(sys.executable)
    env["PATH"] = os.pathsep.join([pydir, os.path.join(pydir, "Scripts"), env.get("PATH", "")])
    log(rid, "server", f"{label}: starting Claude Code headless ({os.path.basename(claude)}).")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
    _procs[rid] = proc
    update(rid, pid=proc.pid)                 # so a restarted server can find and kill an orphaned session
    proc.stdin.write(prompt)
    proc.stdin.close()
    last_line = [time.time()]

    def _watch():
        """Kill a session that has gone quiet for STALL_MINUTES: a hung tool call would otherwise hold the run
        (and the one-run-at-a-time lock) for ever. Every stream line resets the clock."""
        while proc.poll() is None:
            time.sleep(15)
            if proc.poll() is None and time.time() - last_line[0] > STALL_MINUTES * 60:
                log(rid, "error", f"No output from Claude Code for {STALL_MINUTES:.0f} minutes: killing the session.")
                _kill(proc.pid)
                return
    threading.Thread(target=_watch, daemon=True, name=f"watch-{rid}").start()
    result_text, ok = "", False
    for line in proc.stdout:
        last_line[0] = time.time()
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
    update(rid, pid=None)
    if proc.returncode not in (0, None) and not ok:
        log(rid, "error", f"Claude Code exited with code {proc.returncode}.")
    return ok, result_text


def cancel(rid):
    proc = _procs.get(rid)
    if proc and proc.poll() is None:
        _kill(proc.pid)
    st = load(rid)
    update(rid, status="cancelled", error="Cancelled from the page.",
           resume_from=st["status"] if st["status"] in RUNNING else st.get("resume_from"))
    log(rid, "server", "Cancelled from the page.")


# ------------------------------------------------------------------ phases
def _fmt(template, rid, **kw):
    st = load(rid)
    return template.format(operator=st["operator"], pdf=st["pdf"], slug=st["slug"], run_dir=rel(run_dir(rid)),
                           data_mode=DATA_MODE, **kw)


def _after_phase_a(rid, ok, label, since=None, must_change=None):
    """Accept a Phase A / revision hand-off only when the session succeeded, phase_a.json is newer than the session,
    and (for a revision) the card or phase_a.json actually changed. Before 2026-10-30 `ok` was ignored and a crashed
    revision came back as 'Gate A assembled' with the unrevised card."""
    if load(rid)["status"] == "cancelled":
        return
    resume = "revising" if label == "Revision" else "phase_a"
    if not ok:
        update(rid, status="failed", resume_from=resume,
               error=f"{label}: the Claude Code session ended with an error, so nothing it may have written was accepted. "
                     "Check the log, then resume or request the revision again.")
        log(rid, "error", f"{label}: session failed; the files on disk were NOT accepted as this session's output.")
        return
    try:
        pa = contract.check_phase_a(run_dir(rid), since=since)
    except contract.ContractError as e:
        update(rid, status="failed", error=f"{label} did not hand back a valid phase_a.json: {e}", resume_from=resume)
        log(rid, "error", str(e))
        return
    if must_change:
        after = {p: _sha(p) for p in must_change}
        if after == must_change:
            update(rid, status="failed", resume_from="revising",
                   error=f"{label} changed neither the card nor phase_a.json; the notes were not applied.")
            log(rid, "error", f"{label}: no file changed; refusing to show the old Gate A as revised.")
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
    t0 = time.time()
    ok, _ = run_claude(rid, _fmt(prompts.PHASE_A, rid), "Stages 00-02 + Gate A", IDS_A)
    _after_phase_a(rid, ok, "Phase A", since=t0)


def revise_a(rid, notes):
    with _lock:
        s = load(rid)
        s["revisions"] = list(s.get("revisions") or []) + [{"at": now(), "notes": notes}]
        s.update(status="revising", current_stage="03m", activity="Revising the card with your notes.")
        s["stages"]["GA"] = "pending"
        save(s)
    st = s
    card_path = st["phase_a"]["card_path"]
    before = {p: _sha(p) for p in (card_path, os.path.join(run_dir(rid), "phase_a.json"))}
    t0 = time.time()
    ok, _ = run_claude(rid, _fmt(prompts.REVISE_A, rid, card=card_path, notes=notes), "Card revision + Gate A", IDS_A)
    _after_phase_a(rid, ok, "Revision", since=t0, must_change=before)


DIAGNOSTIC_LABEL = re.compile(r"leaving the|membership-forced|gap exits|gap rule|eligible names|first fill|index gate|buying shut|band proxy|resize fills|fewer than 5 names", re.I)


def phase_b(rid):
    st = load(rid)
    if st.get("current_stage") not in IDS_B:
        update(rid, current_stage=None, activity="Starting the backtest stages.")
    ok, _ = run_claude(rid, _fmt(prompts.PHASE_B, rid, card=st["phase_a"]["card_path"],
                                 approver=st["approval"]["by"], notes=operator_notes(st)),
                       "Stages 03-07 + Gate B", IDS_B)
    if load(rid)["status"] == "cancelled":
        return
    if not ok:
        update(rid, status="failed", resume_from="phase_b",
               error="Phase B: the Claude Code session ended with an error; the results on disk were not built "
                     "into charts or a workbook. Check the log, then resume.")
        log(rid, "error", "Phase B session failed; build_outputs was not run on possibly stale files.")
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
    extra, warn = contract.load_optional(rd, df["date"])
    for w in warn:
        log(rid, "error", f"Hand-off warning: {w}")
    st = load(rid)
    # Freshness: every hand-off file must have been written AFTER the card was approved (a rebuild from files left by
    # an earlier session, or a results.json older than the approval, is a stale result and is refused)
    approved_at = (st.get("approval") or {}).get("at")
    if approved_at:
        t_ok = dt.datetime.fromisoformat(approved_at).timestamp() - 120
        old = [f for f in ("results.json", "daily_returns.csv", "manifest.json")
               if os.path.exists(os.path.join(rd, f)) and os.path.getmtime(os.path.join(rd, f)) < t_ok]
        if old:
            update(rid, status="failed", resume_from="phase_b",
                   error=f"Stale hand-off: {', '.join(old)} predate the Gate A approval at {approved_at}; "
                         "the backtest did not run after the card was approved.")
            log(rid, "error", f"stale hand-off files refused: {old}")
            return
    # Fixed output template (2026-10-30): when the script wrote out/validation_rows.json and out/tables.json, those rows and
    # sheets come FIRST and never change between runs; the model's own rows are only ever appended (new labels / new CSVs)
    fixed_v = _load_json_list(os.path.join(rd, "out", "validation_rows.json"))
    if fixed_v:
        labels = {r.get("label") for r in fixed_v}
        model_rows = [r for r in (res.get("validation") or []) if r.get("label") not in labels]
        res["validation"] = fixed_v + model_rows
    # Rows tied to this strategy's rules belong in Diagnostics, whichever step wrote them.
    for v in res.get("validation") or []:
        if DIAGNOSTIC_LABEL.search(str(v.get("label", ""))):
            v["group"] = "diagnostics"
        log(rid, "server", f"Validation sheet: {len(fixed_v)} fixed rows from the run, {len(model_rows)} model rows appended.")
    fixed_t = _load_json_list(os.path.join(rd, "out", "tables.json"))
    if fixed_t:
        csvs = {os.path.normpath(t.get("csv", "")) for t in fixed_t}
        model_tabs = [t for t in (res.get("tables") or []) if os.path.normpath(t.get("csv", "")) not in csvs]
        res["tables"] = fixed_t + model_tabs
        log(rid, "server", f"Table sheets: {len(fixed_t)} fixed from the run, {len(model_tabs)} model tables appended.")
    # Run-authored notes (2026-11-02): a script may write out/notes_fixed.json, a list of sentences computed from its own
    # data (universe coverage, unpriced names, the start rule). They go first in results.notes, so the page and the
    # workbook Notes carry them whatever the model wrote.
    fixed_n = _load_json_list(os.path.join(rd, "out", "notes_fixed.json"))
    if fixed_n:
        have = set(res.get("notes") or [])
        res["notes"] = [n for n in fixed_n if isinstance(n, str)] + [n for n in (res.get("notes") or []) if n not in fixed_n]
        log(rid, "server", f"Notes: {len(fixed_n)} fixed sentences from the run placed first, {len(have)} model notes kept.")
    # Comparison words follow the numbers ('lower volatility (16.8% against 15.9%)' is corrected, and recorded)
    corrections = wording.fix_results(res)
    if corrections:
        log(rid, "server", "Wording corrected to follow the numbers: " + "; ".join(f"'{c['was']}' -> '{c['now']}'" for c in corrections))
    # Gate A -> Gate B wiring check: the run must come from the APPROVED card, parameter by parameter
    try:
        comp_cols = [c for c in extra["comparators"].columns if c != "date"] if "comparators" in extra else []
        card_checks = contract.check_card_consistency(rd, (st.get("phase_a") or {}).get("card_path") or "",
                                                      approval=st.get("approval"), results=res, comparator_columns=comp_cols)
    except contract.ContractError as e:
        update(rid, status="failed", error=f"Phase B's run does not match the approved card: {e}", resume_from="phase_b")
        log(rid, "error", str(e))
        return
    log(rid, "server", f"Run checked against the approved card: {len(card_checks)} items agree "
        f"({', '.join(c['item'] for c in card_checks[:6])}{', ...' if len(card_checks) > 6 else ''}).")
    # Did the backtest DO what the card says? Independent audit of the run's own files (shown on the page, never hidden)
    try:
        audit = spec_audit.run(rd, (st.get("phase_a") or {}).get("card_path") or "", results=res)
        update(rid, spec_audit=audit)
        log(rid, "error" if audit["n_fail"] else "server",
            f"Gate A specification audit of the run's files: {audit['n_pass']} pass, {audit['n_fail']} fail, {audit['n_not_checkable']} not checkable."
            + ("".join(f" FAIL: {c['rule']} ({c['detail']})" for c in audit["checks"] if c["passed"] is False)))
    except Exception as e:      # noqa: BLE001  the audit is a report; a crash in it must not lose the run
        log(rid, "error", f"Specification audit could not run: {type(e).__name__}: {e}")
    # What changed vs the previous run of this card (card fields, script, metrics) -> state, Notes, page
    try:
        cl = changelog.build(st, rd)
        update(rid, change_log=cl)
        log(rid, "server", " ".join(cl["lines"]))
    except Exception as e:      # noqa: BLE001
        log(rid, "error", f"Change log could not be built: {type(e).__name__}: {e}")
    _finish_stages(rid, [s for s, _ in prompts.STAGES_B])
    names = {"strategy": res.get("strategy_name") or "Strategy", "benchmark": res.get("benchmark_name") or "NIFTY 500",
             "sleeve": res.get("sleeve_name") or "Sleeve"}
    extras, warn_core = _core_inputs(st, res, df, extra)
    warn = list(warn) + warn_core
    ch = charts.build(df, names, comparators=extra.get("comparators"), **extras)
    try:
        ch["capacity"] = gate_run.capacity(df, extra.get("trades"))
    except Exception as e:  # noqa: BLE001  a report; the failure is shown, and the run is not lost
        log(rid, "error", f"Capacity not computed: {type(e).__name__}: {e}")
        ch["capacity"] = {"status": "not computed", "why": f"{type(e).__name__}: {e}"}
    ch["benchmark_basis"] = "price" if not res.get("benchmark_is_total_return") else "total_return"
    json.dump(ch, open(os.path.join(rd, "charts.json"), "w", encoding="utf-8"), default=float)
    log(rid, "server", "Interactive chart series built from daily_returns.csv"
        + (" and comparators.csv." if "comparators" in extra else "."))
    res["gate_v2"] = _gate_v2(rid, st, res, df, extra)
    recalc = _workbook(rid, res, df, extra, ch["observations"], _load_review(rd), ch)
    res["gate_rows"] = gates.rows(res["gate_b"].get("criteria", []))
    update(rid, status="gate_b", current_stage="GB", results=res, recalc=recalc, handoff_warnings=warn, error=None,
           card_checks=card_checks,
           has_holdings="holdings" in extra, has_trades=("trades" in extra or "holdings" in extra),
           has_comparators="comparators" in extra)
    log(rid, "gate", "Gate B ready. A named human records the decision on the page.")
    if review and not os.environ.get("LIGHTYEAR_SKIP_REVIEW"):
        try:
            analyst_review(rid)
        except Exception as e:      # the review is extra; Gate B is already on the page
            update(rid, review_status="failed")
            log(rid, "error", f"Analyst review failed: {e}")


def _core_inputs(st, res, df, extra):
    """What ros.metrics.core needs from the card and the hand-off files, and a plain warning for whatever is missing."""
    warn, out = [], {"house_bp": config.house_cost_bp(), "charged_bp": float(res.get("headline_cost_bp") or 0.0)}
    path = (st.get("phase_a") or {}).get("card_path") or ""
    try:
        card = load_card(path if os.path.isabs(path) else os.path.join(REPO, path))
        out["publication_date"] = card.paper.date
        out["cash_rate"], out["cash_source"] = config.cash_rate_for(card)
    except Exception as e:  # noqa: BLE001  an unreadable card must not lose the run; the warning is on the page
        warn.append(f"Card not read for the core metrics ({type(e).__name__}: {e}); Sharpe and Sortino left blank.")
    tr = extra.get("trades")
    if tr is None and "holdings" in extra:
        tr = workbook.derive_trades(extra["holdings"])
    if tr is not None and len(tr):
        out["turnover"] = core.two_way_turnover_from_trades(tr, pd.DatetimeIndex(df["date"]))
    else:
        warn.append("Net-of-cost metrics not computed: the run wrote no trades.csv or holdings.csv to charge the house cost on.")
    return out, warn


def _gate_v2(rid, st, res, df, extra):
    """Score Gate v2 from this run's files. A failure is logged and shown; v1 and the run's results are not lost."""
    tr = extra.get("trades")
    if tr is None and "holdings" in extra:
        tr = workbook.derive_trades(extra["holdings"])
    audit = load(rid).get("spec_audit") or {}
    try:
        g = gate_run.score(run_dir(rid), (st.get("phase_a") or {}).get("card_path") or "", res.get("headline_cost_bp"), df, tr, extra.get("holdings"), audit.get("n_fail"))
        log(rid, "server", f"Gate v2: {g['status']} on {g['basis']}; {len(g['tests_not_run'])} test(s) not run. decision: PENDING.")
        return g
    except Exception as e:  # noqa: BLE001
        log(rid, "error", f"Gate v2 not scored: {type(e).__name__}: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def _load_review(rd):
    p = os.path.join(rd, "review.json")
    try:
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    except (json.JSONDecodeError, OSError):
        return None


def _workbook(rid, res, df, extra, observations, review, ch=None):
    """Build the workbook and recalculate it. Never loses the run over a workbook problem."""
    st = load(rid)
    rd = run_dir(rid)
    xlsx = os.path.join(rd, f"{st['slug']}_results_{rid}.xlsx")       # the run id is in the file name: no two runs share one
    title = f"{st.get('paper_title') or st['slug']}: India test (run {rid})"
    if review:
        for key in ("strengths", "weaknesses", "red_flags"):
            review[key] = [wording.fix_sentence(s)[0] if isinstance(s, str) else s for s in (review.get(key) or [])]
        if isinstance(review.get("verdict"), str):
            review["verdict"] = wording.fix_sentence(review["verdict"])[0]
    kw = dict(holdings=extra.get("holdings"), trades=extra.get("trades"), comparators=extra.get("comparators"),
              observations=observations, review=review, selection=extra.get("selection"),
              selection_rule=(st.get("phase_a") or {}).get("one_line") or None,
              revisions=st.get("revisions"), approval=st.get("approval"), provenance=provenance(st),
              core_metrics=ch,
              change_log=(st.get("change_log") or {}).get("lines"))
    try:
        try:
            workbook.build(rd, res, df, title, xlsx, **kw)
        except PermissionError:
            # Windows locks a workbook that is open in Excel. Writing nothing would leave the page serving the
            # previous run's workbook beside this run's charts, so write a new file and serve that one instead.
            xlsx = os.path.join(rd, f"{st['slug']}_results_{dt.datetime.now():%Y%m%d-%H%M%S}.xlsx")
            log(rid, "error", f"The workbook is open in another program (Excel?) and could not be replaced; "
                f"writing {os.path.basename(xlsx)} instead. Close the old file and use Rebuild to go back to one name.")
            workbook.build(rd, res, df, title, xlsx, **kw)
        update(rid, workbook=os.path.basename(xlsx), workbook_error=None)
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
        # The page hides Download Excel when no workbook was built; say why there, not only in the log.
        msg = f"{type(e).__name__}: {e}"
        log(rid, "error", f"Workbook step failed: {msg}")
        if not load(rid).get("workbook"):
            update(rid, workbook_error=msg)
        return {"error": f"workbook step failed: {msg}"}


def analyst_review(rid):
    """Claude reads the finished run and writes review.json: plain-English strengths, weaknesses, red flags.
    Runs after Gate B is shown (it never holds the page up) and never decides anything."""
    update(rid, review_status="running")
    log(rid, "server", "Analyst review: Claude is reading the results.")
    st = load(rid)
    card = ((st.get("phase_a") or {}).get("card_path")) or "(no card)"
    ok, _ = run_claude(rid, _fmt(prompts.REVIEW, rid, card=card, notes=operator_notes(st)), "Analyst review", [])
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
        recalc = _workbook(rid, res, df, extra, ch.get("observations"), rev, ch)
        update(rid, review_status="done", recalc=recalc)
    except Exception as e:
        update(rid, review_status="done")
        log(rid, "error", f"Review saved, but the workbook refresh failed: {e}")
    log(rid, "server", "Analyst review ready.")


# ------------------------------------------------------------------ human actions
def approve(rid, by, notes=""):
    """Record the approval AND pin the card: its sha256 at this moment is what Phase B must run from."""
    st = load(rid)
    card_path = (st.get("phase_a") or {}).get("card_path") or ""
    approval = {"by": by, "at": now(), "notes": notes, "card_path": card_path, "card_sha256": _sha(card_path)}
    # keep the approved card's CONTENT with the run (not only its sha), so later runs can diff field by field
    src = card_path if os.path.isabs(card_path) else os.path.join(REPO, card_path)
    if os.path.isfile(src):
        with open(src, encoding="utf-8") as fh, open(os.path.join(run_dir(rid), "card_approved.yaml"), "w", encoding="utf-8") as out:
            out.write(fh.read())
    st = update(rid, approval=approval, status="phase_b")
    log(rid, "gate", f"Gate A approved by {by}. Card {card_path} pinned at sha256 {(approval['card_sha256'] or '?')[:12]}; "
        f"{len(st.get('revisions') or [])} revision(s) on record.")
    start(phase_b, rid)
    return st


def rerun_from(src_rid, by, extra_note="", src_dir=None):
    """A NEW run that starts at Phase B from an existing run's approved card: it inherits the paper, the Gate A
    hand-off (phase_a.json, paper_facts.json), every revision on record and the approval notes, re-pins the card at
    its current sha256 and runs stages 03-07 again. Used after a code fix, or after a human edits the card directly
    (pass the edit as `extra_note`, which is recorded as one more revision). `src_dir` points at an archived run
    folder when the source run has been moved out of outputs/. `extra_note` may be a list: one revision each."""
    src_dir = src_dir or run_dir(src_rid)
    with open(os.path.join(src_dir, "state.json"), encoding="utf-8") as fh:
        src = json.load(fh)
    if not src.get("phase_a") or not src.get("approval"):
        raise ValueError("the source run has no approved Gate A to re-run from")
    rid = create(src["pdf"], src["slug"], src["operator"], src.get("model") or "", False)
    for f in ("phase_a.json", "paper_facts.json"):
        p = os.path.join(src_dir, f)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh, open(os.path.join(run_dir(rid), f), "w", encoding="utf-8") as out:
                out.write(fh.read())
    revisions = list(src.get("revisions") or [])
    if not revisions and os.path.exists(os.path.join(src_dir, "log.jsonl")):
        with open(os.path.join(src_dir, "log.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("kind") == "gate" and str(e.get("msg", "")).startswith("Revision requested at Gate A: "):
                    revisions.append({"at": e.get("t"), "notes": e["msg"][len("Revision requested at Gate A: "):], "source": "log.jsonl"})
    for note in ([extra_note] if isinstance(extra_note, str) else list(extra_note or [])):
        if note:
            revisions.append({"at": now(), "notes": note, "by": by, "source": "rerun"})
    with _lock:
        st = load(rid)
        for s, _ in prompts.STAGES_A:
            st["stages"][s] = "done"
        st.update(phase_a=src["phase_a"], paper_title=src.get("paper_title"), revisions=revisions,
                  rerun_of=src_rid, current_stage="GA")
        save(st)
    log(rid, "server", f"Re-run of {src_rid} from its approved card; {len(revisions)} revision(s) carried over.")
    for r in revisions:
        log(rid, "gate", f"Revision on record (from {src_rid}): {r.get('notes', '')}")
    approve(rid, by, (src.get("approval") or {}).get("notes") or "")
    return rid


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
