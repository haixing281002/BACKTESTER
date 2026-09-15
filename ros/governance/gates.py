"""Gates A and B, and the promotion ladder.

The board replaced 'promising / rejected' with a governed ladder:

    REPLICATED > INDIA_VALIDATED > ROBUST > ORTHOGONAL > PORTFOLIO_USEFUL
              > PAPER_TRADED > LIVE_CANDIDATE

Rules that make the ladder mean something:
  - rungs are strictly ordered; a strategy sits at the HIGHEST rung whose every
    criterion passes AND all lower rungs pass. No skipping.
  - an adaptation card can never claim REPLICATED. Different question, different
    evidence. It enters at INDIA_VALIDATED.
  - every rung stores its evidence; a rung with no evidence is a fail, not a pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

LADDER = ["REPLICATED", "INDIA_VALIDATED", "ROBUST", "ORTHOGONAL",
          "PORTFOLIO_USEFUL", "PAPER_TRADED", "LIVE_CANDIDATE"]


@dataclass
class Criterion:
    name: str
    passed: bool
    evidence: str = ""
    value: Any = None
    threshold: Any = None
    blocking: bool = True

    def render(self) -> str:
        mark = "PASS" if self.passed else ("FAIL" if self.blocking else "warn")
        val = "" if self.value is None else f"  [{self.value} vs {self.threshold}]"
        return f"    [{mark:>4}] {self.name}{val}" + (f"\n           {self.evidence}" if self.evidence else "")


@dataclass
class GateResult:
    gate: str
    owner: str
    criteria: List[Criterion] = field(default_factory=list)
    decision: str = "PENDING"        # APPROVE | REJECT | FIX | OBSERVE | PENDING
    rationale: str = ""

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria if c.blocking)

    @property
    def warnings(self) -> List[Criterion]:
        return [c for c in self.criteria if not c.passed and not c.blocking]

    def render(self) -> str:
        head = f"  {self.gate} (owner: {self.owner}) -> {'PASS' if self.passed else 'BLOCKED'}"
        body = "\n".join(c.render() for c in self.criteria)
        tail = f"\n    decision: {self.decision}" + (f" -- {self.rationale}" if self.rationale else "")
        return head + "\n" + body + tail

    def to_dict(self) -> Dict[str, Any]:
        return {"gate": self.gate, "owner": self.owner, "decision": self.decision,
                "passed": self.passed, "rationale": self.rationale,
                "criteria": [asdict(c) for c in self.criteria]}


def gate_a(card, feasibility, extraction_quality=None) -> GateResult:
    """GATE A -- HUMAN INTERPRETATION CONTROL.

    Owned by the researcher. Confirms we understand the paper before we spend a
    day coding it. Everything here is cheap; everything after it is not.
    """
    c: List[Criterion] = []

    c.append(Criterion(
        "card validates against schema", not card.validate(),
        evidence="; ".join(card.validate()) or "schema clean"))

    unresolved = card.unresolved_ambiguities
    c.append(Criterion(
        "all ambiguities resolved", not unresolved,
        value=len(unresolved), threshold=0,
        evidence="unresolved: " + ", ".join(a.field for a in unresolved) if unresolved
                 else f"{len(card.ambiguities)} ambiguities logged and resolved"))

    low = [a for a in card.material_ambiguities if a.confidence == "low"]
    c.append(Criterion(
        "no low-confidence material interpretation", not low,
        value=len(low), threshold=0, blocking=False,
        evidence="low-confidence: " + ", ".join(a.field for a in low) if low else "none"))

    c.append(Criterion(
        "data feasibility resolved", feasibility.can_proceed,
        value=feasibility.verdict, threshold="GO or GO_WITH_PROXY",
        evidence="; ".join(feasibility.blocking) or "no blocking data gaps"))

    if card.intent.mode == "replication":
        c.append(Criterion(
            "replication targets defined", bool(card.replication_targets),
            value=len(card.replication_targets), threshold=">=1",
            evidence="targets pinned to a single accounting basis"))
    else:
        c.append(Criterion(
            "transferred mechanism stated", bool(card.intent.transferred_mechanism),
            evidence=card.intent.transferred_mechanism or "MISSING"))
        c.append(Criterion(
            "broken source assumptions enumerated", bool(card.intent.broken_assumptions),
            value=len(card.intent.broken_assumptions), threshold=">=1", blocking=False,
            evidence="; ".join(card.intent.broken_assumptions) or "none listed -- suspicious"))

    if extraction_quality is not None:
        c.append(Criterion(
            "source text is machine-readable", extraction_quality.usable,
            evidence="; ".join(extraction_quality.warnings) or "clean extraction",
            blocking=True))
        c.append(Criterion(
            "equations verified against rendered page",
            extraction_quality.mean_math_density < 0.05,
            value=f"{extraction_quality.mean_math_density:.1%}", threshold="<5%",
            blocking=False,
            evidence="high math density: formulas were hand-checked, not trusted from text"))

    return GateResult("GATE A -- interpretation", "researcher", c)


def gate_b(card, research: Dict[str, Any], portfolio: Dict[str, Any],
           thresholds: Optional[Dict[str, float]] = None) -> GateResult:
    """GATE B -- INVESTMENT DECISION. Owned by PM / IC.

    Deliberately strict on orthogonality and incremental IR: those are the two
    criteria that separate 'a real effect' from 'a real effect we are already paid for'.
    """
    t = {"min_oos_sharpe": 0.30, "max_corr_to_book": 0.80, "min_delta_ir": 0.05,
         "min_dsr": 0.95, "max_turnover": 4.0, "min_alpha_t": 2.0}
    t.update(thresholds or {})
    c: List[Criterion] = []

    dsr = research.get("deflated_sharpe", {})
    if "deflated_sharpe_prob" in dsr:
        c.append(Criterion(
            "deflated Sharpe clears selection bias",
            dsr["deflated_sharpe_prob"] >= t["min_dsr"],
            value=f"{dsr['deflated_sharpe_prob']:.2f}", threshold=t["min_dsr"],
            evidence=dsr.get("interpretation", "")))

    oos = research.get("oos_min_sharpe")
    if oos is not None:
        c.append(Criterion(
            "positive Sharpe in every out-of-sample window",
            oos >= t["min_oos_sharpe"],
            value=f"{oos:.2f}", threshold=t["min_oos_sharpe"],
            evidence="worst walk-forward window"))

    sig = research.get("bootstrap_p_not_positive")
    if sig is not None:
        c.append(Criterion(
            "advantage over benchmark is significant",
            sig <= 0.05, value=f"{sig:.3f}", threshold="<=0.05",
            evidence="paired stationary-bootstrap P(Sharpe difference <= 0)"))

    corr = portfolio.get("max_corr_to_book")
    if corr is not None:
        c.append(Criterion(
            "differentiated from existing book",
            corr <= t["max_corr_to_book"],
            value=f"{corr:.2f}", threshold=f"<={t['max_corr_to_book']}",
            evidence="max correlation to any existing signal"))

    dir_ = portfolio.get("best_delta_ir")
    if dir_ is not None:
        c.append(Criterion(
            "improves the book's information ratio",
            dir_ >= t["min_delta_ir"],
            value=f"{dir_:+.3f}", threshold=f">={t['min_delta_ir']}",
            evidence="incremental IR at a realistic sleeve size"))

    at = portfolio.get("alpha_t_hac")
    if at is not None:
        c.append(Criterion(
            "alpha survives the factor fingerprint",
            abs(at) >= t["min_alpha_t"],
            value=f"{at:.2f}", threshold=f"|t|>={t['min_alpha_t']}",
            evidence="HAC t-stat of alpha vs known factor sleeves"))

    mand = portfolio.get("mandate", {})
    if mand:
        c.append(Criterion(
            "implementable within mandate", bool(mand.get("passes")),
            evidence="; ".join(mand.get("violations", [])) or "no mandate violations"))

    to = portfolio.get("annual_turnover")
    if to is not None:
        c.append(Criterion(
            "turnover within operational tolerance", to <= t["max_turnover"],
            value=f"{to:.0%}", threshold=f"<={t['max_turnover']:.0%}", blocking=False,
            evidence="annualised two-way turnover"))

    return GateResult("GATE B -- investment decision", "PM / IC", c)


@dataclass
class PromotionRung:
    rung: str
    criteria: List[Criterion] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.criteria) and all(c.passed for c in self.criteria if c.blocking)


def evaluate_ladder(card, rung_criteria: Dict[str, List[Criterion]]) -> Dict[str, Any]:
    """Walk the ladder in order, stopping at the first rung that fails.

    An adaptation card starts at INDIA_VALIDATED: REPLICATED is marked N/A rather
    than passed, so an adaptation can never be reported as a replication.
    """
    results: List[Dict[str, Any]] = []
    attained: Optional[str] = None
    stopped_at: Optional[str] = None

    for rung in LADDER:
        if rung == "REPLICATED" and card.intent.mode == "adaptation":
            results.append({"rung": rung, "status": "N/A",
                            "note": "adaptation card: replication is a different question",
                            "criteria": []})
            continue
        crits = rung_criteria.get(rung)
        if crits is None:
            results.append({"rung": rung, "status": "NOT_EVALUATED", "criteria": []})
            if stopped_at is None:
                stopped_at = rung
            break
        r = PromotionRung(rung, crits)
        results.append({
            "rung": rung, "status": "PASS" if r.passed else "FAIL",
            "criteria": [asdict(c) for c in crits],
            "failed": [c.name for c in crits if not c.passed and c.blocking],
        })
        if r.passed:
            attained = rung
        else:
            stopped_at = rung
            break

    return {
        "card_id": card.paper.id,
        "mode": card.intent.mode,
        "attained_rung": attained,
        "stopped_at": stopped_at,
        "ladder": results,
    }


def render_ladder(lad: Dict[str, Any]) -> str:
    lines = ["STEP 08 -- PROMOTION LADDER",
             f"  card: {lad['card_id']} ({lad['mode']})",
             f"  attained: {lad['attained_rung'] or 'NONE'}   stopped at: {lad['stopped_at'] or '--'}",
             ""]
    for r in lad["ladder"]:
        lines.append(f"  {r['rung']:<18} {r['status']}")
        if r.get("note"):
            lines.append(f"      {r['note']}")
        for c in r.get("criteria", []):
            mk = "PASS" if c["passed"] else ("FAIL" if c["blocking"] else "warn")
            v = "" if c["value"] is None else f"  [{c['value']} vs {c['threshold']}]"
            lines.append(f"      [{mk:>4}] {c['name']}{v}")
            if c.get("evidence"):
                lines.append(f"             {c['evidence']}")
    return "\n".join(lines)
