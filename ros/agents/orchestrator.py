"""Agentic orchestration for steps 00-08.

The contract this module enforces, and the reason it is worth reading before
trusting anything below it:

    AI INTERPRETS. DETERMINISTIC SYSTEMS COMPUTE. HUMANS GOVERN.

Concretely, in code:

  * Every agent output is a Pydantic instance, not prose.
  * A drafted Strategy Card is written to disk and then loaded through the SAME
    `load_card()` the human path uses. If it does not validate, the run stops.
    The model gets no privileged entry into the engine.
  * `assess()` -- deterministic -- still owns the feasibility verdict. The data
    mapper's opinion is recorded as advice alongside it, and where the two
    disagree, the disagreement is surfaced rather than resolved.
  * Gate A and Gate B are unchanged deterministic functions over evidence. No
    agent votes.
  * Backtesting, bootstrap and deflated Sharpe never see an LLM.

What the model actually buys us is the expensive-human-time part: reading the
document, noticing what is unstated, and interpreting a diagnostic table.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ros.agents import analysts as A
from ros.agents import schemas as S
from ros.agents.client import Transport, UsageLedger, build_transport
from ros.cards.schema import CardValidationError, StrategyCard, load_card
from ros.data.firm_registry import build_firm_registry
from ros.engine.primitives import list_primitives
from ros.engine.templates import list_templates
from ros.governance.library import LibraryEntry, StrategyLibrary, make_entry_id

FUND_CONTEXT = """\
Long-only Indian equity fund, NIFTY500 universe, benchmarked to NIFTY 500.
Fully invested -- the mandate does not permit holding cash as a strategy.
No shorting, no leverage, no derivatives.
Held data: NSE factor index daily closes only (no volumes, no constituents,
no fundamentals, no Indian risk-free series). All index history is BACKFILLED
and price-return, not total-return.
Realistic round-trip cost for factor-sleeve rotation is ~30bp, not 5bp."""

TEMPLATE_DOCS = """\
fixed_weight              constant target weights
vol_target                dilute a fixed mix with cash to cap ex-ante volatility
markowitz_l1              mean-variance: maximise forecast return net of cost,
                          subject to a hard risk cap and an l1 leash to a strategic mix
ts_momentum               long-only trend following, inverse-vol sized
inverse_vol               naive risk parity
equal_risk_contribution   risk parity proper
min_variance              long-only minimum variance
equal_weight              1/N"""


@dataclass
class AgenticResult:
    """Everything the agent layer produced, all of it advisory."""
    triage: Optional[S.TriageVerdict] = None
    analysis: Optional[S.PaperAnalysis] = None
    proposal: Optional[S.CardProposal] = None
    critique: Optional[S.AmbiguityReport] = None
    data_mapping: Optional[S.FeasibilityMapping] = None
    template_match: Optional[S.TemplateMatch] = None
    results_critique: Optional[S.ResultsCritique] = None
    librarian: Optional[S.LibrarianAnswer] = None
    card_path: Optional[str] = None
    card_valid: bool = False
    card_errors: List[str] = field(default_factory=list)
    human_review_queue: List[str] = field(default_factory=list)
    ledger: Optional[UsageLedger] = None
    stage_notes: Dict[str, List[str]] = field(default_factory=dict)
    library_entry_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k in ("triage", "analysis", "proposal", "critique", "data_mapping",
                  "template_match", "results_critique", "librarian"):
            v = getattr(self, k)
            out[k] = json.loads(v.model_dump_json()) if v is not None else None
        out.update({
            "card_path": self.card_path,
            "card_valid": self.card_valid,
            "card_errors": self.card_errors,
            "human_review_queue": self.human_review_queue,
            "llm_usage": self.ledger.to_dict() if self.ledger else None,
            "stage_notes": self.stage_notes,
            "library_entry_path": self.library_entry_path,
        })
        return out


class AgenticPipeline:
    """Runs the interpretation half of the pipeline. Computation stays elsewhere."""

    def __init__(self, transport: Optional[Transport] = None, mode: str = "auto",
                 fixtures: Optional[Dict[str, Any]] = None,
                 library: Optional[StrategyLibrary] = None):
        self.ledger = UsageLedger()
        self.transport = transport or build_transport(mode, fixtures)
        self.registry = build_firm_registry()
        # The read/write ends of the "agents get better with time" loop:
        # each stage below fetches relevant_precedent() for its own role
        # before it acts, and run_interpretation() banks what THIS run
        # found so the next paper's agents can draw on it. See
        # ros/governance/library.py's own docstring on relevant_precedent
        # for why this is informational-only, never decision-making.
        self.library = library or StrategyLibrary()

    def _agent(self, cls):
        return cls(self.transport, self.ledger)

    def _precedent(self, role: str, card_id_prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.library.relevant_precedent(role, card_id_prefix=card_id_prefix)

    # ------------------------------------------------------------------
    def triage(self, title: str, abstract: str) -> S.TriageVerdict:
        """Step 00. Cheap screen so Opus only reads what survives."""
        return self._agent(A.TriageAgent).run(
            title, abstract, precedent=self._precedent("triage"))

    def analyse_paper(self, pdf_path: str) -> S.PaperAnalysis:
        """Step 01. Read the rendered document."""
        return self._agent(A.PaperAnalystAgent).run(pdf_path)

    def draft_card(self, analysis: S.PaperAnalysis, mode: str) -> S.CardProposal:
        """Step 02. Draft a card. Still a proposal."""
        return self._agent(A.CardDrafterAgent).run(
            analysis, mode=mode,
            registry_names=self.registry.names(),
            templates=list_templates(),
            primitives=list_primitives(),
            fund_context=FUND_CONTEXT,
            precedent=self._precedent("card_drafter"))

    def critique_card(self, pdf_path: str, proposal: S.CardProposal) -> S.AmbiguityReport:
        """Step 02, adversarial second pass."""
        return self._agent(A.AmbiguityCriticAgent).run(
            pdf_path, proposal, precedent=self._precedent("ambiguity_critic"))

    def map_data(self, analysis: S.PaperAnalysis) -> S.FeasibilityMapping:
        """Step 03, advisory. The deterministic gate still decides."""
        return self._agent(A.DataMapperAgent).run(
            [r.model_dump() for r in analysis.data_requirements],
            self.registry.to_dict(),
            precedent=self._precedent("data_mapper"))

    def match_template(self, analysis: S.PaperAnalysis, assets: List[str]) -> S.TemplateMatch:
        return self._agent(A.TemplateMatcherAgent).run(
            analysis, list_templates(), TEMPLATE_DOCS, assets,
            precedent=self._precedent("template_matcher"))

    def critique_results(self, diagnostics: Dict[str, Any], card_summary: str) -> S.ResultsCritique:
        return self._agent(A.ResultsCriticAgent).run(
            diagnostics, card_summary, precedent=self._precedent("results_critic"))

    def consult_library(self, question: str, summaries: List[Dict[str, Any]]) -> S.LibrarianAnswer:
        return self._agent(A.LibrarianAgent).run(question, summaries)

    # ------------------------------------------------------------------
    def run_interpretation(self, pdf_path: str, mode: str, out_dir: str,
                           card_name: Optional[str] = None) -> AgenticResult:
        """Steps 01-03 end to end: paper in, validated card proposal out.

        Stops at Gate A by design. The deterministic pipeline takes it from there.
        """
        res = AgenticResult(ledger=self.ledger)

        res.analysis = self.analyse_paper(pdf_path)
        res.proposal = self.draft_card(res.analysis, mode)
        res.critique = self.critique_card(pdf_path, res.proposal)
        res.data_mapping = self.map_data(res.analysis)
        res.template_match = self.match_template(
            res.analysis, res.analysis.assets_studied)

        # The drafted card re-enters through the ordinary front door.
        os.makedirs(out_dir, exist_ok=True)
        name = card_name or f"{_slug(res.analysis.title)}_{mode}.yaml"
        res.card_path = os.path.join(out_dir, name)
        with open(res.card_path, "w", encoding="utf-8") as fh:
            fh.write(res.proposal.card_yaml)
        try:
            load_card(res.card_path)
            res.card_valid = True
        except (CardValidationError, Exception) as exc:   # noqa: BLE001
            res.card_valid = False
            res.card_errors = [str(exc)]

        res.human_review_queue = self._build_review_queue(res)
        res.stage_notes = self._extract_stage_notes(res)
        if res.card_valid:
            res.library_entry_path = self._bank_precedent(res)
        return res

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_stage_notes(res: AgenticResult) -> Dict[str, List[str]]:
        """Deterministic extraction from the agents' own structured output --
        no extra model call, no freeform summarisation. This is the "code
        computes" half of the loop: the MODEL already produced findings as
        Pydantic fields; turning the material ones into short precedent
        strings is plain Python, same discipline as everywhere else in this
        repo that a model's structured output feeds a report."""
        notes: Dict[str, List[str]] = {}

        if res.critique:
            card_drafter_notes = (
                [f"missed by first pass: {m}" for m in res.critique.missed_by_first_pass]
                + [f"material finding on {f.field}: {f.issue}" for f in res.critique.findings
                   if f.materiality == S.Materiality.high])
            if card_drafter_notes:
                notes["card_drafter"] = card_drafter_notes

        if res.data_mapping:
            proxy_notes = [f"{m.requirement} -> proxy ({m.matched_series}): {m.proxy_risk}"
                           for m in res.data_mapping.matches
                           if m.match_type == "proxy" and m.proxy_risk]
            if proxy_notes:
                notes["data_mapper"] = proxy_notes

        if res.template_match:
            if res.template_match.template is None:
                notes["template_matcher"] = [
                    f"no registered template fit: {res.template_match.missing_capability}"]
            else:
                notes["template_matcher"] = [
                    f"matched '{res.template_match.template}': {res.template_match.reasoning}"]

        if res.results_critique:
            crit_notes = [f"{f.severity}: {f.observation} -- {f.why_suspicious}"
                         for f in res.results_critique.findings
                         if f.severity in ("blocking", "serious")]
            if crit_notes:
                notes["results_critic"] = crit_notes

        if res.triage and not res.triage.relevant and res.triage.reject_reason:
            notes["triage"] = [f"rejected: {res.triage.reject_reason}"]

        return notes

    def _bank_precedent(self, res: AgenticResult) -> Optional[str]:
        """Writes a PRELIMINARY library entry (outcome="AGENTIC_DRAFT") so the
        NEXT similar paper's agents get today's stage_notes as precedent --
        even though this run stops at Gate A and has no governed Step 08
        verdict yet. This is a SEPARATE, distinguishable entry from the real
        one run_pipeline.py writes after Gate B; it never substitutes for
        it, and outcome="AGENTIC_DRAFT" is how a reader (or
        relevant_precedent's own caller) tells the two apart."""
        if not res.stage_notes:
            return None
        try:
            card = load_card(res.card_path)
        except Exception:   # noqa: BLE001 -- an invalid card has nothing fingerprintable
            return None
        eid = make_entry_id(card.paper.id, card.fingerprint())
        entry = LibraryEntry(
            entry_id=eid, card_id=card.paper.id, mode=card.intent.mode,
            created_utc=datetime.now(timezone.utc).isoformat(),
            card_fingerprint=card.fingerprint(),
            outcome="AGENTIC_DRAFT",
            stage_notes=res.stage_notes,
            reuse_notes=["Written by the agentic interpretation pass (Steps 01-03), "
                        "before Gate A/B -- advisory precedent only, not a governed verdict."])
        return self.library.write(entry)

    # ------------------------------------------------------------------
    @staticmethod
    def _build_review_queue(res: AgenticResult) -> List[str]:
        """What a human must look at before Gate A can pass.

        Routing by the model's own calibration is the point: a low-confidence
        material field costs one minute of human attention, and a
        high-confidence wrong field costs a quarter.
        """
        q: List[str] = []

        if res.analysis:
            if res.analysis.overall_confidence != S.Confidence.high:
                q.append(f"Paper analysis confidence is {res.analysis.overall_confidence.value} "
                         f"-- re-read the paper before trusting the card.")
            for c in res.analysis.extraction_concerns:
                q.append(f"Extraction concern: {c}")
            for eq in res.analysis.equations:
                if eq.confidence != S.Confidence.high:
                    q.append(f"Verify {eq.label} on page {eq.evidence_page} against the rendered "
                             f"page -- it governs {eq.governs}.")
            if len(res.analysis.accounting_bases_present) > 1:
                q.append(f"Paper reports results on {len(res.analysis.accounting_bases_present)} "
                         f"accounting bases: {res.analysis.accounting_bases_present}. Confirm the "
                         f"card's replication targets are pinned to exactly one.")
            if res.analysis.hyperparameters_selected_in_sample:
                q.append(f"In-sample hyperparameter selection admitted for "
                         f"{res.analysis.hyperparameters_selected_in_sample} -- confirm "
                         f"n_configs_tried reflects it.")

        if res.critique:
            for f in res.critique.findings:
                if f.materiality == S.Materiality.high:
                    q.append(f"Critic (material): {f.field} -- {f.issue}")
            for m in res.critique.missed_by_first_pass:
                q.append(f"Critic says the draft wrongly treats this as settled: {m}")

        if res.data_mapping:
            for m in res.data_mapping.matches:
                if m.match_type == "proxy":
                    q.append(f"Approve proxy for {m.requirement} -> {m.matched_series}: "
                             f"{m.proxy_risk}")

        if res.template_match and res.template_match.template is None:
            q.append(f"No registered template fits. Engineer to review spec: "
                     f"{res.template_match.missing_capability}")

        if res.proposal:
            q += [f"Open question from drafter: {o}" for o in res.proposal.open_questions_for_human]

        if not res.card_valid:
            q.append(f"DRAFTED CARD DOES NOT VALIDATE: {res.card_errors}")

        return q


def _slug(text: str, n: int = 48) -> str:
    keep = "".join(c.lower() if c.isalnum() else "_" for c in text)
    while "__" in keep:
        keep = keep.replace("__", "_")
    return keep.strip("_")[:n] or "untitled"


def reconcile_feasibility(deterministic, mapping: Optional[S.FeasibilityMapping]) -> Dict[str, Any]:
    """Compare the deterministic verdict with the model's advice.

    Agreement is reassuring. Disagreement is the interesting case and is
    surfaced, never silently resolved -- the deterministic verdict always stands,
    and the model's dissent becomes a procurement question for a human.
    """
    if mapping is None:
        return {"available": False}
    llm = {m.requirement: m for m in mapping.matches}
    rows = []
    for r in deterministic.resolutions:
        m = llm.get(r.requirement)
        if m is None:
            rows.append({"requirement": r.requirement, "deterministic": r.status,
                         "llm": "not_assessed", "agree": None})
            continue
        det_simple = {"AVAILABLE": "exact", "DEGRADED": "exact",
                      "PROXY": "proxy", "UNAVAILABLE": "none"}.get(r.status, "none")
        rows.append({
            "requirement": r.requirement,
            "deterministic": r.status,
            "llm": m.match_type,
            "agree": det_simple == m.match_type,
            "llm_reasoning": m.reasoning,
        })
    disagreements = [r for r in rows if r["agree"] is False]
    return {
        "available": True,
        "rows": rows,
        "n_disagreements": len(disagreements),
        "disagreements": disagreements,
        "note": ("The deterministic verdict stands. A disagreement means the model believes a "
                 "substitution exists that the registry does not declare -- that is a "
                 "procurement question for a human, not a licence to proceed."),
        "procurement_suggestions": mapping.procurement_suggestions,
    }
