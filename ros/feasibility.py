"""Step 03 -- DATA FEASIBILITY. Fail fast, or obtain sign-off.

This is the cheapest gate in the pipeline and the one that saves the most money.
Most papers die here, and they should: a paper whose data we cannot get is not a
research question, it is a procurement question.

Resolution per requirement:
  AVAILABLE   -- we hold the series, with acceptable PIT status
  PROXY       -- we hold something that stands in, and the substitution is recorded
  DEGRADED    -- we hold it, but its PIT status undermines the claim (backfill)
  UNAVAILABLE -- we do not hold it and have no proxy

Verdicts:
  GO              -- every mandatory requirement AVAILABLE
  GO_WITH_PROXY   -- mandatory requirements met, some via proxy/degraded; needs sign-off
  FAIL_FAST       -- a mandatory requirement is UNAVAILABLE; stop before writing code
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from ros.cards.schema import StrategyCard
from ros.data.registry import DataRegistry

AVAILABLE, PROXY, DEGRADED, UNAVAILABLE = "AVAILABLE", "PROXY", "DEGRADED", "UNAVAILABLE"
GO, GO_WITH_PROXY, FAIL_FAST = "GO", "GO_WITH_PROXY", "FAIL_FAST"


@dataclass
class Resolution:
    requirement: str
    kind: str
    mandatory: bool
    status: str
    resolved_to: Optional[str] = None
    reason: str = ""
    caveats: List[str] = field(default_factory=list)


@dataclass
class FeasibilityReport:
    card_id: str
    mode: str
    verdict: str
    resolutions: List[Resolution]
    blocking: List[str] = field(default_factory=list)
    signoff_required: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def can_proceed(self) -> bool:
        return self.verdict in (GO, GO_WITH_PROXY)

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for r in self.resolutions:
            out[r.status] = out.get(r.status, 0) + 1
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card_id": self.card_id, "mode": self.mode, "verdict": self.verdict,
            "counts": self.counts(),
            "resolutions": [asdict(r) for r in self.resolutions],
            "blocking": self.blocking, "signoff_required": self.signoff_required,
            "notes": self.notes,
        }

    def render(self) -> str:
        lines = [
            "STEP 03 -- DATA FEASIBILITY",
            f"  card    : {self.card_id}  (mode={self.mode})",
            f"  verdict : {self.verdict}",
            f"  counts  : {self.counts()}",
            "",
            f"  {'requirement':<34}{'req':<5}{'status':<13}{'resolved to'}",
            f"  {'-'*34}{'-'*5}{'-'*13}{'-'*34}",
        ]
        for r in self.resolutions:
            lines.append(
                f"  {r.requirement:<34}{'M' if r.mandatory else 'o':<5}"
                f"{r.status:<13}{r.resolved_to or '--'}")
            if r.reason:
                lines.append(f"      why: {r.reason}")
            for c in r.caveats:
                lines.append(f"      ! {c}")
        if self.blocking:
            lines += ["", "  BLOCKING:"] + [f"    X {b}" for b in self.blocking]
        if self.signoff_required:
            lines += ["", "  SIGN-OFF REQUIRED (Gate A):"] + [f"    ? {s}" for s in self.signoff_required]
        if self.notes:
            lines += ["", "  NOTES:"] + [f"    - {n}" for n in self.notes]
        return "\n".join(lines)


def assess(card: StrategyCard, registry: DataRegistry,
           allow_backfilled: bool = True) -> FeasibilityReport:
    """Resolve every data requirement on the card against the registry."""
    resolutions: List[Resolution] = []
    blocking: List[str] = []
    signoff: List[str] = []
    notes: List[str] = []

    for req in card.data_requirements:
        cap = registry.get(req.name)
        if cap is not None:
            caveats = list(cap.caveats)
            if cap.pit_status in ("backfilled", "unknown"):
                status = DEGRADED
                reason = (f"held, but pit_status={cap.pit_status}: history was not "
                          f"knowable as-was on past dates")
                if not allow_backfilled and req.mandatory:
                    blocking.append(f"{req.name}: backfilled data not permitted for this run")
                if req.mandatory:
                    signoff.append(
                        f"{req.name}: accept {cap.pit_status} history? Results carry "
                        f"selection bias from the index/field construction.")
            else:
                status, reason = AVAILABLE, ""
            resolutions.append(Resolution(
                requirement=req.name, kind=req.kind, mandatory=req.mandatory,
                status=status, resolved_to=cap.name, reason=reason, caveats=caveats))
            continue

        # no direct hold -- look for a declared proxy
        proxies = registry.proxies_for(req.name)
        if proxies:
            p = proxies[0]
            resolutions.append(Resolution(
                requirement=req.name, kind=req.kind, mandatory=req.mandatory,
                status=PROXY, resolved_to=p.name,
                reason=f"substituting {p.name}",
                caveats=list(p.caveats)))
            if req.mandatory:
                signoff.append(
                    f"{req.name}: approve proxy '{p.name}'. A proxy changes the "
                    f"economic claim, not just the data.")
            continue

        resolutions.append(Resolution(
            requirement=req.name, kind=req.kind, mandatory=req.mandatory,
            status=UNAVAILABLE, reason="not in registry and no declared proxy"))
        if req.mandatory:
            blocking.append(f"{req.name} ({req.kind}) is mandatory and unavailable")

    # unresolved interpretation is also a feasibility blocker
    for a in card.unresolved_ambiguities:
        blocking.append(f"unresolved ambiguity '{a.field}': {a.issue}")

    if blocking:
        verdict = FAIL_FAST
    elif any(r.status in (PROXY, DEGRADED) for r in resolutions):
        verdict = GO_WITH_PROXY
    else:
        verdict = GO

    if card.intent.mode == "adaptation":
        notes.append(
            "Adaptation card: a PASS here means the ADAPTED strategy is testable on our "
            "data. It says nothing about whether the original paper replicates.")
        for b in card.intent.broken_assumptions:
            notes.append(f"broken assumption carried from source paper: {b}")

    n_mand = sum(1 for r in resolutions if r.mandatory)
    n_ok = sum(1 for r in resolutions if r.mandatory and r.status == AVAILABLE)
    notes.append(f"{n_ok}/{n_mand} mandatory requirements are clean-AVAILABLE.")

    return FeasibilityReport(
        card_id=card.paper.id, mode=card.intent.mode, verdict=verdict,
        resolutions=resolutions, blocking=blocking, signoff_required=signoff, notes=notes)
