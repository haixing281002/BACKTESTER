"""Lineage for interpretation work done by a human or by Claude Code in the editor.

The API path (`ros/agents/`) records model id, prompt hash and token counts for
every call. An editor session cannot produce a prompt hash -- but the thing that
actually matters downstream is not the prompt, it is:

    which artifact was produced, from which inputs, by whom, when.

That this module records, and it hashes the artifact so the record cannot drift
from the file it describes. The result is the same guarantee the API path gives:
a card in the library can be traced back to the document and the operator that
produced it, whether the interpretation was done by a model through an API, by a
model in the editor, or by a person with a text editor and an afternoon.

Both paths emit the SAME artifacts, validated against the SAME schemas in
ros/agents/schemas.py. The producer is recorded; it is not special-cased.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Artifacts (analyses, critiques, briefs) live here; the lineage RECORDS about
# them live in a subdirectory, so listing records never picks up the artifacts
# they describe.
INTERP_DIR = "outputs/interpretation"
LINEAGE_DIR = os.path.join(INTERP_DIR, "_lineage")

PRODUCERS = {"claude-code", "api", "human"}

# Pipeline stages that produce an interpretation artifact. Keyed to the chart:
# the LLM-owned and LLM-advising stages, plus the two human gates.
STAGES = {
    "00_triage": "TriageVerdict",
    "01_ingest": "PaperAnalysis",
    "02_card": None,                 # a Strategy Card, validated by load_card()
    "02_critique": "AmbiguityReport",
    "03_data_mapping": "FeasibilityMapping",
    "05_template": "TemplateMatch",
    "06_results_critique": "ResultsCritique",
    "08_librarian": "LibrarianAnswer",
    "gate_a": None,
    "gate_b": None,
}


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> Optional[str]:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:                                            # noqa: BLE001
        return None


@dataclass
class InterpretationRecord:
    """One piece of interpretation work, with enough provenance to re-trace it."""
    stage: str
    produced_by: str                 # claude-code | api | human
    operator: str                    # the NAMED person accountable for it
    output_path: str
    output_sha256: str = ""
    model: str = ""                  # e.g. claude-opus-5, or "" for a person
    session_ref: str = ""            # Claude Code session URL, or a ticket id
    created_utc: str = ""
    inputs: List[Dict[str, str]] = field(default_factory=list)
    schema: Optional[str] = None
    schema_valid: Optional[bool] = None
    notes: str = ""
    git_commit: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def record(stage: str, output_path: str, operator: str,
           produced_by: str = "claude-code", model: str = "",
           session_ref: str = "", inputs: Optional[List[str]] = None,
           notes: str = "", outdir: str = LINEAGE_DIR) -> str:
    """Write a provenance record for an interpretation artifact.

    `operator` is mandatory and is a person's name, not a tool's. Interpretation
    is accountable work: if a card turns out to be wrong, somebody has to be
    answerable for having produced or approved it, and "the model did it" is not
    an answer a fund can give.
    """
    if stage not in STAGES:
        raise SystemExit(f"unknown stage '{stage}'. Known: {sorted(STAGES)}")
    if produced_by not in PRODUCERS:
        raise SystemExit(f"produced_by must be one of {sorted(PRODUCERS)}")
    if not operator.strip():
        raise SystemExit("operator is required -- a named person owns every artifact")
    if not os.path.exists(output_path):
        raise SystemExit(f"artifact not found: {output_path}")

    rec = InterpretationRecord(
        stage=stage, produced_by=produced_by, operator=operator.strip(),
        output_path=output_path, output_sha256=file_sha256(output_path),
        model=model, session_ref=session_ref,
        created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        inputs=[{"path": p, "sha256": file_sha256(p)}
                for p in (inputs or []) if os.path.exists(p)],
        schema=STAGES[stage], notes=notes, git_commit=_git_commit(),
    )
    if rec.schema:
        ok, msg = validate(output_path, rec.schema)
        rec.schema_valid = ok
        if not ok:
            rec.notes = (rec.notes + " | SCHEMA INVALID: " + msg).strip(" |")

    os.makedirs(outdir, exist_ok=True)
    stamp = rec.created_utc.replace(":", "").replace("-", "")
    path = os.path.join(outdir, f"{stage}__{stamp}.json")
    with open(path, "w") as fh:
        json.dump(rec.to_dict(), fh, indent=2)
    return path


def validate(path: str, schema_name: str) -> tuple[bool, str]:
    """Check an artifact against the same Pydantic schema the API agents use.

    This is what makes the two producers interchangeable: an analysis written by
    Claude Code in the editor has to satisfy exactly the contract an API call
    would have had to satisfy. Neither gets a privileged path.
    """
    from ros.agents import schemas as S
    cls = getattr(S, schema_name, None)
    if cls is None:
        return False, f"unknown schema '{schema_name}'"
    try:
        with open(path) as fh:
            blob = json.load(fh)
    except Exception as e:                                       # noqa: BLE001
        return False, f"not readable JSON: {e}"
    try:
        cls.model_validate(blob)
        return True, "ok"
    except Exception as e:                                       # noqa: BLE001
        return False, str(e).replace("\n", " ")[:400]


def history(outdir: str = LINEAGE_DIR) -> List[Dict[str, Any]]:
    """Every lineage record, oldest first. Non-records are skipped rather than
    assumed: a stray file in the directory must not break the audit trail."""
    if not os.path.isdir(outdir):
        return []
    out = []
    for f in sorted(os.listdir(outdir)):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(outdir, f)) as fh:
                blob = json.load(fh)
        except Exception:                                        # noqa: BLE001
            continue
        if isinstance(blob, dict) and {"stage", "produced_by", "operator"} <= blob.keys():
            out.append(blob)
    return sorted(out, key=lambda r: r.get("created_utc", ""))


def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Interpretation lineage")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="check an artifact against a schema")
    v.add_argument("path")
    v.add_argument("--schema", required=True)

    r = sub.add_parser("record", help="write a provenance record")
    r.add_argument("--stage", required=True)
    r.add_argument("--output", required=True)
    r.add_argument("--operator", required=True)
    r.add_argument("--produced-by", default="claude-code")
    r.add_argument("--model", default="")
    r.add_argument("--session-ref", default="")
    r.add_argument("--input", action="append", default=[])
    r.add_argument("--notes", default="")

    sub.add_parser("history", help="list every interpretation record")
    args = ap.parse_args(argv)

    if args.cmd == "validate":
        ok, msg = validate(args.path, args.schema)
        print(f"{'VALID' if ok else 'INVALID'}  {args.path}  [{args.schema}]")
        if not ok:
            print(f"  {msg}")
        return 0 if ok else 1

    if args.cmd == "record":
        p = record(stage=args.stage, output_path=args.output, operator=args.operator,
                   produced_by=args.produced_by, model=args.model,
                   session_ref=args.session_ref, inputs=args.input, notes=args.notes)
        rec = json.load(open(p))
        print(f"recorded -> {p}")
        print(f"  stage      : {rec['stage']}")
        print(f"  produced by: {rec['produced_by']}  operator: {rec['operator']}")
        print(f"  artifact   : {rec['output_path']}  sha256 {rec['output_sha256'][:16]}")
        if rec["schema"]:
            print(f"  schema     : {rec['schema']}  valid={rec['schema_valid']}")
        return 0

    rows = history()
    if not rows:
        print("no interpretation records yet")
        return 0
    print(f"{'stage':<20}{'by':<13}{'operator':<20}{'valid':<7}artifact")
    print("-" * 96)
    for r_ in rows:
        print(f"{r_['stage']:<20}{r_['produced_by']:<13}{r_['operator'][:18]:<20}"
              f"{str(r_.get('schema_valid', '-')):<7}{r_['output_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
