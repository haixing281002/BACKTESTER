"""Step 08 -- STRATEGY LIBRARY. The research graph that makes knowledge compound.

Negative results are first-class. A paper that failed feasibility, or replicated
and then died on orthogonality, is a permanent asset: it stops the firm paying
for the same disappointment twice. The library is therefore append-only and
indexes failures as carefully as successes.

Storage is a JSON directory rather than a database on purpose: it diffs, it
reviews in a pull request, and it survives the tool that wrote it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if (np.isnan(v) or np.isinf(v)) else v
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, float):
        return None if (np.isnan(o) or np.isinf(o)) else o
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "to_dict"):
        return o.to_dict()
    return str(o)


@dataclass
class LibraryEntry:
    entry_id: str
    card_id: str
    mode: str
    created_utc: str
    card_fingerprint: str
    snapshot_id: Optional[str] = None
    content_hash: Optional[str] = None
    engine_code_hash: Optional[str] = None
    git_commit: Optional[str] = None
    outcome: str = "UNKNOWN"          # e.g. FAIL_FAST, REJECTED, PROMOTED
    attained_rung: Optional[str] = None
    stopped_at: Optional[str] = None
    headline_metrics: Dict[str, Any] = field(default_factory=dict)
    factor_fingerprint: Dict[str, float] = field(default_factory=dict)
    gates: List[Dict[str, Any]] = field(default_factory=list)
    lessons: List[str] = field(default_factory=list)
    reuse_notes: List[str] = field(default_factory=list)
    reviewer: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StrategyLibrary:
    def __init__(self, root: str = "outputs/library"):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, entry_id: str) -> str:
        return os.path.join(self.root, f"{entry_id}.json")

    def write(self, entry: LibraryEntry) -> str:
        p = self._path(entry.entry_id)
        with open(p, "w") as fh:
            json.dump(entry.to_dict(), fh, indent=2, default=_jsonable)
        return p

    def all(self) -> List[Dict[str, Any]]:
        out = []
        for f in sorted(os.listdir(self.root)):
            if f.endswith(".json"):
                with open(os.path.join(self.root, f)) as fh:
                    out.append(json.load(fh))
        return out

    def find_duplicate_experiment(self, fingerprint: str,
                                  exclude: Optional[str] = None) -> List[Dict[str, Any]]:
        """Has this exact experiment been run before?

        Guards the trial count that feeds the deflated Sharpe ratio. Re-running
        an experiment and reporting it as new is how a firm accidentally
        p-hacks itself across months.
        """
        return [e for e in self.all()
                if e.get("card_fingerprint") == fingerprint and e.get("entry_id") != exclude]

    def similar_by_fingerprint(self, fingerprint: Dict[str, float],
                               threshold: float = 0.90,
                               exclude: Optional[str] = None) -> List[Dict[str, Any]]:
        """Cosine similarity over factor loadings: find the same bet under a new name.

        `exclude` drops one entry_id from the search. The caller writes its own
        entry before searching, so without this the run always reports itself as
        a perfect match and buries the genuine neighbours underneath it.
        """
        if not fingerprint:
            return []
        keys = sorted(fingerprint)
        v = np.array([fingerprint[k] for k in keys], dtype=float)
        nv = np.linalg.norm(v)
        hits = []
        for e in self.all():
            if exclude is not None and e.get("entry_id") == exclude:
                continue
            fp = e.get("factor_fingerprint") or {}
            common = [k for k in keys if k in fp]
            if len(common) < max(2, len(keys) // 2):
                continue
            a = np.array([fingerprint[k] for k in common], dtype=float)
            b = np.array([fp[k] for k in common], dtype=float)
            na, nb = np.linalg.norm(a), np.linalg.norm(b)
            if na == 0 or nb == 0:
                continue
            cos = float(a @ b / (na * nb))
            if cos >= threshold:
                hits.append({"entry_id": e["entry_id"], "card_id": e.get("card_id"),
                             "cosine": round(cos, 4), "outcome": e.get("outcome")})
        return sorted(hits, key=lambda h: -h["cosine"])

    def trials_for_family(self, card_id_prefix: str,
                          exclude_fingerprint: Optional[str] = None) -> int:
        """DISTINCT prior configurations in a family -- the honest n for the DSR.

        Counts distinct card fingerprints, not entries. Re-running an identical
        configuration is not a new trial: no selection happens, so it must not
        inflate the deflation threshold. Running a DIFFERENT configuration is a
        trial, and it counts even if it was run in another session last month --
        which is the leak that lets a firm quietly p-hack itself over time.
        """
        fps = {e.get("card_fingerprint") for e in self.all()
               if str(e.get("card_id", "")).startswith(card_id_prefix)}
        fps.discard(None)
        fps.discard(exclude_fingerprint)
        return len(fps)

    def summary(self) -> List[Dict[str, Any]]:
        return [{"entry_id": e["entry_id"], "card": e.get("card_id"),
                 "mode": e.get("mode"), "outcome": e.get("outcome"),
                 "rung": e.get("attained_rung"), "stopped_at": e.get("stopped_at"),
                 "created": e.get("created_utc")} for e in self.all()]


def make_entry_id(card_id: str, fingerprint: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{card_id}__{fingerprint}__{stamp}"
