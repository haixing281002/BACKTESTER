"""Supplying data at Gate A.

Gate A is the last cheap moment. It is where a researcher learns that a paper's
translation needs NIFTY 500 constituent prices the fund does not hold -- and the
useful thing to do at that moment is hand over the data, not abandon the paper.

This module is that path: drop files into data/raw/, declare what they are in
data/raw/MANIFEST.yaml, re-run. Stage 03 then resolves against the enlarged
registry and the pipeline continues.

WHY A MANIFEST, RATHER THAN SNIFFING THE FILES

Because ros/data/firm_registry.py says, correctly, that an over-generous
registry converts a fail-fast into three wasted days and a result nobody can
defend. A file's existence tells you nothing about whether its history was
knowable as-was on past dates. Auto-registering whatever appears in a folder
as clean, point-in-time data would defeat Step 03 entirely -- the gate would
pass because someone copied a spreadsheet.

So the declaration is manual and the awkward fields are mandatory. Whoever adds
a series states its pit_status, its licence and its caveats, and those travel
with every result computed from it. Typing "backfilled" is a two-second
admission that saves a quarter of misplaced confidence.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml

from ros.data.registry import DataCapability, DataRegistry

RAW_DIR = "data/raw"
MANIFEST = os.path.join(RAW_DIR, "MANIFEST.yaml")

# Accepted spellings for the manifest. ros/data/registry.py owns the canonical
# set and normalises these; `point_in_time` and `true_pit` are the same thing.
PIT_STATUSES = ("point_in_time", "true_pit", "backfilled", "restated", "unknown")

REQUIRED_FIELDS = ("name", "kind", "frequency", "file", "pit_status", "licence")


class ManifestError(ValueError):
    """A manifest entry that cannot be trusted. Never downgraded to a warning."""


def manifest_stanza(instrument: str, kind: str = "price",
                    frequency: str = "daily") -> str:
    """The YAML a researcher pastes to declare one supplied series.

    Printed at Gate A next to whatever is missing, so the fix is a copy rather
    than a documentation hunt.
    """
    return f"""  - name: {instrument}
    kind: {kind}                      # {' / '.join(sorted(_KINDS))}
    frequency: {frequency}
    file: <your_file.xlsx|csv>        # relative to {RAW_DIR}/
    sheet: 0                          # xlsx only; omit for csv
    date_column: Date
    pit_status: backfilled            # {' / '.join(PIT_STATUSES)}  <- be honest
    licence: "<who owns this and what may we do with it>"
    coverage_note: "<what is IN the file: adjusted? dividends? volume?>"
    caveats:
      - "<what would mislead someone reading a result built on this>"
"""


_KINDS = {
    "price", "total_return_index", "volume", "fundamental", "membership",
    "corporate_action", "risk_free_rate", "macro", "factor_return",
    "publication_date",
}


def _validate_entry(e: Dict[str, Any], i: int) -> List[str]:
    errs = []
    for f in REQUIRED_FIELDS:
        if not e.get(f):
            errs.append(f"entry[{i}]: '{f}' is required")
    kind = e.get("kind")
    if kind and kind not in _KINDS:
        errs.append(f"entry[{i}]: kind '{kind}' not in {sorted(_KINDS)}")
    pit = e.get("pit_status")
    if pit and pit not in PIT_STATUSES:
        errs.append(f"entry[{i}]: pit_status '{pit}' not in {list(PIT_STATUSES)}")
    if e.get("file"):
        path = os.path.join(RAW_DIR, e["file"])
        if not os.path.exists(path):
            errs.append(f"entry[{i}]: file not found: {path}")
    return errs


def read_manifest(path: str = MANIFEST) -> List[Dict[str, Any]]:
    """Parse and validate the supplied-data manifest. Missing file -> []."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        blob = yaml.safe_load(fh) or {}
    entries = blob.get("series") or []
    if not isinstance(entries, list):
        raise ManifestError(f"{path}: 'series' must be a list")
    errs: List[str] = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            errs.append(f"entry[{i}] is {type(e).__name__}, not a mapping")
            continue
        errs += _validate_entry(e, i)
    if errs:
        raise ManifestError(f"{path} is not usable:\n  - " + "\n  - ".join(errs))
    return entries


def load_series(entry: Dict[str, Any]) -> pd.DataFrame:
    """Read one declared file into a dated frame."""
    path = os.path.join(RAW_DIR, entry["file"])
    date_col = entry.get("date_column", "Date")
    if path.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(path, sheet_name=entry.get("sheet", 0))
    else:
        df = pd.read_csv(path)
    if date_col not in df.columns:
        raise ManifestError(
            f"{path}: no column named '{date_col}'. Columns present: "
            f"{list(df.columns)[:12]}")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df[df[date_col].notna()].set_index(date_col).sort_index()
    return df


def extend_registry(registry: DataRegistry,
                    path: str = MANIFEST) -> Tuple[DataRegistry, List[str]]:
    """Add every declared series to `registry`. Returns (registry, added names).

    A supplied series that collides with one the fund already holds is an error,
    not an override: silently shadowing the firm's own data with a file someone
    dropped in a folder is exactly how an unauditable result gets made.
    """
    added: List[str] = []
    for e in read_manifest(path):
        name = e["name"]
        if registry.get(name) is not None:
            raise ManifestError(
                f"supplied series '{name}' collides with one the fund already "
                f"holds. Rename it, or remove it from {path} -- a dropped file "
                f"must never silently shadow the firm's own data.")
        caveats = list(e.get("caveats") or [])
        if e["pit_status"] != "point_in_time":
            caveats.append(
                f"Declared pit_status={e['pit_status']}: this history was not "
                f"necessarily knowable as-was on past dates. Any live claim "
                f"resting on it needs a point-in-time re-run.")
        caveats.append(f"SUPPLIED AT INTAKE from {e['file']}, not a firm data "
                       f"feed. Provenance is the manifest entry, nothing more.")
        registry.add(DataCapability(
            name=name, kind=e["kind"], frequency=e["frequency"],
            start=str(e.get("start") or ""), end=str(e.get("end") or ""),
            pit_status=e["pit_status"], licence=e["licence"],
            coverage_note=e.get("coverage_note", ""),
            caveats=caveats))
        added.append(name)
    return registry, added


def read_master_declaration(path: str = MANIFEST) -> Optional[Dict[str, Any]]:
    """The manifest's `master:` block, validated, or None.

    A master universe is one file carrying many securities, so it does not fit
    the per-series `series:` list. It still needs the same honesty fields: the
    provenance of the spine travels with every number computed from it, and
    `pit_status` is what decides whether a live claim may rest on the work.
    """
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        blob = yaml.safe_load(fh) or {}
    m = blob.get("master")
    if not m:
        return None
    if not isinstance(m, dict):
        raise ManifestError(f"{path}: 'master' must be a mapping")
    errs = [f"master: '{f}' is required" for f in ("file", "pit_status", "licence")
            if not m.get(f)]
    if m.get("pit_status") and m["pit_status"] not in PIT_STATUSES:
        errs.append(f"master: pit_status '{m['pit_status']}' not in {list(PIT_STATUSES)}")
    full = os.path.join(RAW_DIR, m["file"]) if m.get("file") else ""
    if full and not os.path.exists(full):
        errs.append(f"master: file not found: {full}")
    if errs:
        raise ManifestError(f"{path} is not usable:\n  - " + "\n  - ".join(errs))
    out = dict(m)
    out["path"] = full
    return out


def load_declared_master(path: str = MANIFEST, **kw):
    """Parse the manifest-declared master universe, or None if none is declared."""
    decl = read_master_declaration(path)
    if decl is None:
        return None, None
    from ros.data.master import load_master
    mu = load_master(decl["path"], **kw)
    return mu, decl


def describe_shortfall(missing: List[str]) -> str:
    """The Gate A block: exactly what to supply, and how."""
    if not missing:
        return ""
    out = [
        "  TO SUPPLY THIS DATA AND CONTINUE",
        "",
        f"  1. Put the file(s) in {RAW_DIR}/",
        f"  2. Declare each series in {MANIFEST}, under a top-level `series:` list.",
        "     The awkward fields are mandatory on purpose -- they travel with",
        "     every result computed from the series.",
        "",
    ]
    for m in missing:
        kind = ("membership" if "membership" in m
                else "fundamental" if any(k in m for k in
                                          ("marketcap", "market_cap", "float",
                                           "earnings", "book"))
                else "price")
        out.append(manifest_stanza(m, kind=kind))
    out += [
        "  3. Re-run. Step 03 resolves against the enlarged registry.",
        "",
        "  If the data does not exist or cannot be licensed, that is a finding",
        "  worth recording: it says what the fund would have to buy to answer",
        "  this question, which is a procurement decision rather than a",
        "  research one.",
    ]
    return "\n".join(out)
