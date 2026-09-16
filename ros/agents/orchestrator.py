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
from typing import Any, Dict, List, Optional

from ros.agents import analysts as A
from ros.agents import schemas as S
from ros.agents.client import Transport, UsageLedger, build_transport
from ros.cards.schema import CardValidationError, StrategyCard, load_card
from ros.data.firm_registry import build_firm_registry
from ros.engine.primitives import list_primitives
from ros.engine.templates import list_templates

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
        })
        return out


class AgenticPipeline:
    """Runs the interpretation half of the pipeline. Computation stays elsewhere."""

    def __init__(self, transport: Optional[Transport] = None, mode: str = "auto",
                 fixtures: Optional[Dict[str, Any]] = None):
        self.ledger = UsageLedger()
        self.transport = transport or build_transport(mode, fixtures)
        self.registry = build_firm_registry()

    def _agent(self, cls):
        return cls(self.transport, self.ledger)

    # ------------------------------------------------------------------
    def triage(self, title: str, abstract: str) -> S.TriageVerdict:
        """Step 00. Cheap screen so Opus only reads what survives."""
        return self._agent(A.TriageAgent).run(title, abstract)

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
            fund_context=FUND_CONTEXT)

    def critique_card(self, pdf_path: str, proposal: S.CardProposal) -> S.AmbiguityReport:
        """Step 02, adversarial second pass."""
        return self._agent(A.AmbiguityCriticAgent).run(pdf_path, proposal)

    def map_data(self, analysis: S.PaperAnalysis) -> S.FeasibilityMapping:
        """Step 03, advisory. The deterministic gate still decides."""
        return self._agent(A.DataMapperAgent).run(
            [r.model_dump() for r in analysis.data_requirements],
            self.registry.to_dict())

    def match_template(self, analysis: S.PaperAnalysis, assets: List[str]) -> S.TemplateMatch:
        return self._agent(A.TemplateMatcherAgent).run(
            analysis, list_templates(), TEMPLATE_DOCS, assets)

    def critique_results(self, diagnostics: Dict[str, Any], card_summary: str) -> S.ResultsCritique:
        return self._agent(A.ResultsCriticAgent).run(diagnostics, card_summary)

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
        with open(res.card_path, "w") as fh:
            fh.write(res.proposal.card_yaml)
        try:
            load_card(res.card_path)
            res.card_valid = True
        except (CardValidationError, Exception) as exc:   # noqa: BLE001
            res.card_valid = False
            res.card_errors = [str(exc)]

        res.human_review_queue = self._build_review_queue(res)
        return res

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
