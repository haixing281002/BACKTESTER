# Quant AI Researcher
"""The Barra site step: send a finished run's book to the Barra site and show its figures beside Lightyear's.

Lightyear holds no site address, login or upload code. Those live in a separate local folder, the tester, named by the
environment variable LIGHTYEAR_BARRA_TESTER or the key barra_tester in the gitignored config/local.yaml. This module only
starts the tester's one command for a run, passes its progress lines to the run log, and copies the result,
barra_site.json, into the run folder. Without a tester the step is not offered.

The step is a report. Gate B does not read it, and nothing here changes a result file.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from ros.data import sources

from .paths import REPO

FILE = "barra_site.json"
COMMAND = os.path.join("scripts", "run_for_lightyear.py")


def tester_dir() -> str:
    return sources._path("LIGHTYEAR_BARRA_TESTER", "barra_tester")


def configured() -> bool:
    d = tester_dir()
    return bool(d) and os.path.isfile(os.path.join(d, COMMAND))


def load(run_dir: str) -> dict[str, Any] | None:
    p = os.path.join(run_dir, FILE)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def run(run_dir: str, log: Callable[[str], None]) -> dict[str, Any]:
    """Run the tester for this run folder. Returns the result as copied into the run folder. Raises RuntimeError with
    the tester's own last words when it fails."""
    if not configured():
        raise RuntimeError("The Barra site step is not set up on this machine (config/local.yaml key barra_tester).")
    try:
        rel = os.path.relpath(run_dir, REPO).replace(os.sep, "/")
    except ValueError:              # another drive: the tester takes an absolute path as it is
        rel = run_dir
    proc = subprocess.Popen([sys.executable, os.path.join(tester_dir(), COMMAND), REPO, rel], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    result, last = None, ""
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        last = line
        if line.startswith("STEP "):
            log("Barra site, " + line[5:])
        elif line.startswith("RESULT "):
            result = line[7:]
    if proc.wait() != 0 or not result or not os.path.isfile(result):
        raise RuntimeError(f"The Barra site step stopped: {last or 'no output'}")
    shutil.copyfile(result, os.path.join(run_dir, FILE))
    return load(run_dir) or {}
