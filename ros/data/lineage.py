# Quant AI Researcher
"""Run lineage: one manifest.json per run folder, so a reported number can be traced to exact bytes.

A run script calls write_run_manifest() after it has written its hand-off files. The manifest records
the sha256 of every input it was given (a file, or every file under a directory), the hash of the engine
source plus the script itself, the git commit, the interpreter and library versions, the parameters the
script chose, and the sha256 of the hand-off files it wrote. verify_run_manifest() recomputes the input
hashes later and names what changed, so "same script, same inputs" is checkable rather than assumed.

Timestamps are tz-aware Asia/Kolkata (house rule). Nothing here reads market data.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from collections.abc import Iterable
from datetime import datetime
from importlib import metadata
from typing import Any
from zoneinfo import ZoneInfo

from ros.data.snapshot import _ENGINE_FILES, code_hash, git_commit, git_dirty, is_text_path, lf_chunks

IST = ZoneInfo("Asia/Kolkata")
SCHEMA = "lightyear-run-manifest/1"
_PACKAGES = ("pandas", "numpy", "scipy", "statsmodels", "openpyxl", "pyyaml", "pydantic")
_CHUNK = 1 << 20


def sha256_both(path: str) -> tuple[str, str]:
    """(sha256 with CRLF folded to LF for text files, sha256 of the raw bytes), in one pass."""
    norm, raw = hashlib.sha256(), hashlib.sha256()
    text = is_text_path(path)
    with open(path, "rb") as fh:
        carry = b""
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            raw.update(chunk)
            if text:
                chunk = carry + chunk
                carry = b"\r" if chunk.endswith(b"\r") else b""
                if carry:
                    chunk = chunk[:-1]
                chunk = chunk.replace(b"\r\n", b"\n")
            norm.update(chunk)
        if carry:
            norm.update(carry)
    return norm.hexdigest(), raw.hexdigest()


def sha256_file(path: str) -> str:
    """sha256 of a file; text files are hashed with line endings folded to LF (a CRLF checkout hashes the same)."""
    return sha256_both(path)[0]


def sha256_tree(path: str) -> dict[str, Any]:
    """One digest over every file under a directory: sorted (relative name, file sha256) pairs."""
    h = hashlib.sha256()
    names, total = [], 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            p = os.path.join(root, f)
            names.append((os.path.relpath(p, path).replace("\\", "/"), p))
    for rel, p in sorted(names):
        h.update(rel.encode())
        h.update(sha256_file(p).encode())
        total += os.path.getsize(p)
    sorted_names = [r for r, _ in sorted(names)]
    return {"kind": "directory", "sha256": h.hexdigest(), "files": len(names), "bytes": total,
            "first": sorted_names[0] if sorted_names else None, "last": sorted_names[-1] if sorted_names else None}


def hash_input(path: str) -> dict[str, Any]:
    if os.path.isdir(path):
        return sha256_tree(path)
    if os.path.isfile(path):
        norm, raw = sha256_both(path)
        return {"kind": "file", "sha256": norm, "sha256_raw": raw, "bytes": os.path.getsize(path)}
    return {"kind": "missing"}


def _rel(path: str, repo: str) -> str:
    p = os.path.abspath(path)
    r = os.path.abspath(repo)
    if p.startswith(r + os.sep):
        return os.path.relpath(p, r).replace("\\", "/")
    return p.replace("\\", "/")


def _versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in _PACKAGES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def write_run_manifest(run_dir: str, script: str, inputs: dict[str, str], params: dict[str, Any] | None = None,
                       outputs: Iterable[str] = (), repo: str | None = None) -> str:
    """Write <run_dir>/manifest.json and return its path.

    inputs   name -> file or directory the script read (hashed now).
    params   the constants the script chose (sample end, costs, trial count ...), JSON-serialisable.
    outputs  file names inside run_dir to hash (the hand-off files); missing ones are recorded as missing.
    """
    repo = repo or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script_abs = os.path.abspath(script)
    manifest = {
        "schema": SCHEMA,
        "written_at": datetime.now(IST).isoformat(timespec="seconds"),
        "run_dir": _rel(run_dir, repo),
        "script": {"path": _rel(script_abs, repo), "sha256": sha256_file(script_abs)},
        "git_commit": git_commit(repo),
        "git_dirty": bool(dirty := (git_dirty(repo) or [])),
        "dirty_files": dirty[:200],
        "code_hash": code_hash(list(_ENGINE_FILES) + [_rel(script_abs, repo)], root=repo),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": _versions(),
        "inputs": {name: {"path": _rel(p, repo), **hash_input(p)} for name, p in inputs.items()},
        "params": params or {},
        "outputs": {},
    }
    for name in outputs:
        p = os.path.join(run_dir, name)
        manifest["outputs"][name] = sha256_file(p) if os.path.isfile(p) else None
    out = os.path.join(run_dir, "manifest.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, default=str)
    return out


def verify_run_manifest(path: str, repo: str | None = None) -> dict[str, Any]:
    """Recompute every input hash. Returns {'ok', 'changed': [names], 'missing': [names]}."""
    repo = repo or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)
    changed, missing = [], []
    for name, rec in m.get("inputs", {}).items():
        p = rec["path"] if os.path.isabs(rec["path"]) else os.path.join(repo, rec["path"])
        now = hash_input(p)
        if now.get("kind") == "missing":
            missing.append(name)
        elif rec.get("sha256") not in (now.get("sha256"), now.get("sha256_raw")):   # older manifests hashed raw bytes
            changed.append(name)
    script = m.get("script") or {}
    script_changed = code_changed = None
    if script.get("path"):
        sp = script["path"] if os.path.isabs(script["path"]) else os.path.join(repo, script["path"])
        if os.path.isfile(sp):
            script_changed = script.get("sha256") not in sha256_both(sp)
            code_changed = m.get("code_hash") != code_hash(list(_ENGINE_FILES) + [_rel(sp, repo)], root=repo)
        else:
            missing.append("script")
    return {"ok": not changed and not missing and not script_changed and not code_changed,
            "changed": changed, "missing": missing, "script_changed": script_changed, "code_changed": code_changed}
