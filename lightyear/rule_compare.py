# Quant AI Researcher
"""Run two versions of the spec audit over every past run and record both results (Wave 2, item 7).

Any change to the audit rules (lightyear/spec_audit.py, lightyear/numbers_audit.py) must be compared this way before it
is committed, and the comparison logged in docs/spec_audit_rules_log.md; tests/test_spec_audit_rules_logged.py fails
when the audit code changes without a log entry. This exists because a start-window rule was loosened (7e0e4f6) three
minutes after it failed the run it audited, and the old rule was never re-run on past runs.

    python -m lightyear.rule_compare OLD_REF [NEW_REF] [--runs DIR ...] [--out CSV]

OLD_REF / NEW_REF are git refs; NEW_REF defaults to the working tree. Each run folder's small files are copied to a
temporary folder first, so neither version writes into a real run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import importlib
import os
import shutil
import subprocess
import sys
import tempfile

import pandas as pd

from .paths import REPO, RUNS

AUDIT_FILES = ("lightyear/spec_audit.py", "lightyear/numbers_audit.py")
_SMALL = (".csv", ".json", ".yaml", ".yml", ".md")


def _source(ref: str | None, path: str) -> str | None:
    if ref is None:
        p = os.path.join(REPO, path)
        return open(p, encoding="utf-8").read() if os.path.isfile(p) else None
    r = subprocess.run(["git", "-C", REPO, "show", f"{ref}:{path}"], capture_output=True, text=True, encoding="utf-8",
                       check=False)
    return r.stdout if r.returncode == 0 else None


def load_version(ref: str | None, tmp: str):
    """The spec audit as it was at `ref` (None = working tree), as an importable module."""
    name = "audit_" + (ref or "worktree").replace("~", "_").replace("^", "_").replace("/", "_")
    pkg = os.path.join(tmp, name)
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as fh:
        fh.write("")
    with open(os.path.join(pkg, "paths.py"), "w", encoding="utf-8") as fh:
        fh.write(f"REPO = {REPO!r}\n")
    for f in AUDIT_FILES:
        src = _source(ref, f)
        if src is not None:
            with open(os.path.join(pkg, os.path.basename(f)), "w", encoding="utf-8") as fh:
                fh.write(src)
    sys.path.insert(0, tmp)
    return importlib.import_module(f"{name}.spec_audit")


def run_folders(extra: list[str] | None = None) -> list[str]:
    dirs = sorted(glob.glob(os.path.join(RUNS, "2*"))) + sorted(glob.glob(os.path.join(REPO, "outputs", "lightyear_archive_*", "2*")))
    return [d for d in dirs + list(extra or []) if os.path.isfile(os.path.join(d, "daily_returns.csv"))]


def _card(run_dir: str) -> str | None:
    p = os.path.join(run_dir, "card_approved.yaml")
    return p if os.path.isfile(p) else None


def _copy_small(run_dir: str, dest: str) -> str:
    for root, _dirs, files in os.walk(run_dir):
        rel = os.path.relpath(root, run_dir)
        for f in files:
            if f.lower().endswith(_SMALL) and f != "spec_audit.json":
                os.makedirs(os.path.join(dest, rel), exist_ok=True)
                shutil.copy2(os.path.join(root, f), os.path.join(dest, rel, f))
    return dest


def compare(old_ref: str, new_ref: str | None = None, runs: list[str] | None = None) -> pd.DataFrame:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        old_mod, new_mod = load_version(old_ref, tmp), load_version(new_ref, tmp)
        for rd in runs if runs is not None else run_folders():
            card = _card(rd)
            if card is None:
                continue
            res = {}
            for tag, mod in (("old", old_mod), ("new", new_mod)):
                work = _copy_small(rd, os.path.join(tmp, "runs", tag, os.path.basename(rd)))
                try:
                    out = mod.run(work, card)
                    res[tag] = {c["rule"]: c["passed"] for c in out["checks"]}
                except Exception as e:  # noqa: BLE001 -- an old rule set that cannot run on a run is a result, recorded
                    res[tag] = {"(audit could not run)": f"{type(e).__name__}: {e}"}
            for rule in sorted(set(res["old"]) | set(res["new"])):
                o, n = res["old"].get(rule, "absent"), res["new"].get(rule, "absent")
                rows.append({"run": os.path.basename(rd), "rule": rule, "old": o, "new": n, "changed": o != n})
    return pd.DataFrame(rows, columns=["run", "rule", "old", "new", "changed"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old_ref")
    ap.add_argument("new_ref", nargs="?", default=None)
    ap.add_argument("--runs", nargs="*", default=None, help="run folders (default: every run under outputs/)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    df = compare(a.old_ref, a.new_ref, a.runs)
    out = a.out or os.path.join(REPO, "outputs", "spec_audit_rule_changes",
                                f"{dt.date.today():%Y-%m-%d}_{a.old_ref}_vs_{a.new_ref or 'worktree'}.csv".replace("~", "-"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Quant AI Researcher\n")
        df.to_csv(fh, index=False)
    ch = df[df["changed"]]
    print(f"{df['run'].nunique()} runs, {len(df)} rule results, {len(ch)} changed between the two versions -> {out}")
    if len(ch):
        print(ch.to_string(index=False, max_colwidth=90))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
