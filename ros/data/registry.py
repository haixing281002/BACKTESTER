"""Step 03 support -- the firm's data capability catalogue.

The feasibility gate compares what a paper NEEDS against what we HAVE. That
comparison is only as honest as this registry, so every entry declares its
point-in-time status and whether it is a proxy. `pit_status` is the field that
decides whether a result is believable:

  true_pit   : as-was; we can reconstruct what was knowable on any past date
  backfilled : history reconstructed after the fact (index backfill, restated
               fundamentals). Usable for mechanism work, NEVER for a live claim.
  unknown    : provenance not established -- treated as backfilled
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

PIT_STATUS = {"true_pit", "backfilled", "unknown"}


@dataclass
class DataCapability:
    name: str
    kind: str
    frequency: str = "daily"
    start: Optional[str] = None
    end: Optional[str] = None
    pit_status: str = "unknown"
    licence: str = "internal"
    coverage_note: str = ""
    is_proxy_for: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        if self.pit_status not in PIT_STATUS:
            return [f"{self.name}: pit_status '{self.pit_status}' not in {sorted(PIT_STATUS)}"]
        return []


class DataRegistry:
    """Catalogue of series the firm can actually get, with provenance."""

    def __init__(self, capabilities: Optional[List[DataCapability]] = None):
        self._caps: Dict[str, DataCapability] = {}
        for c in capabilities or []:
            self.add(c)

    def add(self, cap: DataCapability) -> "DataRegistry":
        errs = cap.validate()
        if errs:
            raise ValueError("; ".join(errs))
        self._caps[cap.name] = cap
        return self

    def get(self, name: str) -> Optional[DataCapability]:
        return self._caps.get(name)

    def has(self, name: str) -> bool:
        return name in self._caps

    def proxies_for(self, name: str) -> List[DataCapability]:
        return [c for c in self._caps.values() if name in c.is_proxy_for]

    def by_kind(self, kind: str) -> List[DataCapability]:
        return [c for c in self._caps.values() if c.kind == kind]

    def names(self) -> List[str]:
        return sorted(self._caps)

    def to_dict(self) -> Dict[str, Any]:
        return {n: asdict(c) for n, c in self._caps.items()}

    def __len__(self) -> int:
        return len(self._caps)
