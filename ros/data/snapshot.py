"""Step 04 -- POINT-IN-TIME DATA. Frozen snapshots with full lineage.

The board's second non-negotiable upgrade: no result without lineage. A snapshot
pins the exact bytes a run consumed, so a number in the strategy library can be
re-derived years later, or shown to be irreproducible.

A snapshot records, and a result cites:
  - source file sha256 (the raw bytes)
  - content hash of the materialised frame (catches a silently changed loader)
  - the code hash of the engine modules
  - every transformation applied, in order
  - declared PIT status and any proxies used
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

_ENGINE_FILES = [
    "ros/engine/backtest.py", "ros/engine/templates.py", "ros/engine/primitives.py",
    "ros/validation/metrics.py", "ros/validation/research.py", "ros/validation/portfolio.py",
    "ros/data/loaders.py", "ros/data/snapshot.py", "ros/feasibility.py",
]


def frame_hash(df: pd.DataFrame) -> str:
    """Content hash of a dataframe: index, columns and values.

    Uses the raw value bytes rather than a printed form, so float formatting
    cannot mask a change.
    """
    h = hashlib.sha256()
    h.update(",".join(map(str, df.columns)).encode())
    h.update(pd.Index(df.index).astype("int64").values.tobytes())
    h.update(df.to_numpy(dtype="float64", na_value=float("nan")).tobytes())
    return h.hexdigest()


def code_hash(files: Optional[List[str]] = None, root: str = ".") -> str:
    """Hash of the engine source. If this changes, prior results are not comparable."""
    h = hashlib.sha256()
    for f in sorted(files or _ENGINE_FILES):
        p = os.path.join(root, f)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                h.update(f.encode())
                h.update(fh.read())
    return h.hexdigest()


def git_commit(root: str = ".") -> Optional[str]:
    try:
        return subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


@dataclass
class Transformation:
    step: str
    detail: str
    rows_before: Optional[int] = None
    rows_after: Optional[int] = None


@dataclass
class Snapshot:
    """An immutable, hashed view of the data a run is allowed to see."""
    snapshot_id: str
    created_utc: str
    frame: pd.DataFrame
    sources: List[Dict[str, Any]] = field(default_factory=list)
    transformations: List[Transformation] = field(default_factory=list)
    pit_status: str = "unknown"
    proxies_used: List[Dict[str, str]] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    content_hash: str = ""
    engine_code_hash: str = ""
    git_commit: Optional[str] = None

    def manifest(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_utc": self.created_utc,
            "content_hash": self.content_hash,
            "engine_code_hash": self.engine_code_hash,
            "git_commit": self.git_commit,
            "shape": list(self.frame.shape),
            "columns": list(map(str, self.frame.columns)),
            "date_min": str(self.frame.index.min().date()),
            "date_max": str(self.frame.index.max().date()),
            "pit_status": self.pit_status,
            "proxies_used": self.proxies_used,
            "caveats": self.caveats,
            "sources": self.sources,
            "transformations": [asdict(t) for t in self.transformations],
        }

    def save(self, outdir: str) -> str:
        os.makedirs(outdir, exist_ok=True)
        self.frame.to_parquet(os.path.join(outdir, f"{self.snapshot_id}.parquet"))
        path = os.path.join(outdir, f"{self.snapshot_id}.manifest.json")
        with open(path, "w") as fh:
            json.dump(self.manifest(), fh, indent=2, default=str)
        return path

    def verify(self) -> bool:
        """Re-hash the frame and confirm it still matches the manifest."""
        return frame_hash(self.frame) == self.content_hash


class SnapshotBuilder:
    """Accumulates a frame plus its lineage, then freezes it."""

    def __init__(self, snapshot_id: str, pit_status: str = "unknown"):
        self.snapshot_id = snapshot_id
        self.pit_status = pit_status
        self._frame: Optional[pd.DataFrame] = None
        self.sources: List[Dict[str, Any]] = []
        self.transformations: List[Transformation] = []
        self.proxies_used: List[Dict[str, str]] = []
        self.caveats: List[str] = []

    def add_source(self, frame: pd.DataFrame, provenance: Dict[str, Any]) -> "SnapshotBuilder":
        self.sources.append(provenance)
        if self._frame is None:
            self._frame = frame.copy()
        else:
            before = len(self._frame)
            self._frame = self._frame.join(frame, how="outer")
            self.transformations.append(Transformation(
                "join_source", provenance.get("path", "?"), before, len(self._frame)))
        return self

    def add_proxy(self, series: pd.Series, proxy_for: str, rationale: str) -> "SnapshotBuilder":
        """Attach a proxy series. Recorded explicitly -- 'no silent proxy use'."""
        if self._frame is None:
            raise RuntimeError("add a primary source before a proxy")
        self._frame[series.name] = series
        self.proxies_used.append({
            "series": str(series.name), "proxy_for": proxy_for, "rationale": rationale})
        self.transformations.append(Transformation("add_proxy", f"{series.name} <- {proxy_for}"))
        return self

    def restrict(self, start: Optional[str] = None, end: Optional[str] = None,
                 columns: Optional[List[str]] = None) -> "SnapshotBuilder":
        before = len(self._frame)
        if columns:
            missing = [c for c in columns if c not in self._frame.columns]
            if missing:
                raise KeyError(f"snapshot missing required columns: {missing}")
            self._frame = self._frame[columns]
        if start or end:
            self._frame = self._frame.loc[start:end]
        self.transformations.append(Transformation(
            "restrict", f"start={start} end={end} cols={columns}", before, len(self._frame)))
        return self

    def require_complete(self, columns: List[str]) -> "SnapshotBuilder":
        """Drop dates where any required column is missing, and say how many.

        Done once, up front, so the backtest never silently changes its investable
        set mid-run.
        """
        before = len(self._frame)
        self._frame = self._frame.dropna(subset=columns)
        after = len(self._frame)
        self.transformations.append(Transformation(
            "require_complete", f"cols={columns}", before, after))
        if before != after:
            self.caveats.append(
                f"Dropped {before - after} dates lacking complete data for {columns}.")
        return self

    def add_caveat(self, text: str) -> "SnapshotBuilder":
        self.caveats.append(text)
        return self

    def freeze(self, root: str = ".") -> Snapshot:
        if self._frame is None or self._frame.empty:
            raise RuntimeError("cannot freeze an empty snapshot")
        frame = self._frame.sort_index()
        return Snapshot(
            snapshot_id=self.snapshot_id,
            created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            frame=frame,
            sources=self.sources,
            transformations=self.transformations,
            pit_status=self.pit_status,
            proxies_used=self.proxies_used,
            caveats=self.caveats,
            content_hash=frame_hash(frame),
            engine_code_hash=code_hash(root=root),
            git_commit=git_commit(root),
        )
