"""Typed contracts for every LLM output in the pipeline.

The single most important design rule in this package:

    THE MODEL NEVER RETURNS FREE TEXT THAT ANYTHING DOWNSTREAM CONSUMES.

Every agent emits one of these Pydantic models. If the model cannot produce a
valid instance, the call fails loudly rather than handing prose to a parser.
That is what keeps an LLM inside a deterministic pipeline: the blast radius of
a hallucination is bounded by the schema, and everything past the schema is
ordinary validated data.

Two conventions run through all of these:

  evidence_page   every factual claim carries the page it came from, so a human
                  at Gate A can check it in seconds instead of re-reading a PDF.
  confidence      the model's own calibration, used to route work to humans --
                  low confidence on a material field is a Gate A blocker, not a
                  footnote.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Materiality(str, Enum):
    """Does getting this wrong change the headline number?"""
    high = "high"
    medium = "medium"
    low = "low"


# ---------------------------------------------------------------------------
# Step 00 -- TRIAGE. Cheap, high volume: is this paper worth a full read?
# ---------------------------------------------------------------------------
class TriageVerdict(BaseModel):
    relevant: bool = Field(description="Could this plausibly inform a long-only Indian equity fund?")
    asset_class: str = Field(description="equity / multi_asset / fixed_income / fx / commodity / other")
    geography: str = Field(description="Primary market studied, e.g. US, India, global")
    is_cross_sectional: bool = Field(description="True if it ranks securities; False if it times a single series")
    requires_shorting: bool
    requires_derivatives: bool
    requires_intraday_data: bool
    one_line_summary: str
    reject_reason: Optional[str] = Field(
        default=None, description="If not relevant, the single clearest reason. Null otherwise.")
    confidence: Confidence


# ---------------------------------------------------------------------------
# Step 01 -- INGEST. Replaces regex scanning with actual reading.
# ---------------------------------------------------------------------------
class DataRequirementFinding(BaseModel):
    name: str = Field(description="Canonical series name, e.g. SPY_adj_close, DFF_fed_funds")
    kind: str = Field(description="price / volume / fundamental / macro / factor_return / risk_free_rate / membership")
    frequency: str = Field(description="daily / weekly / monthly / quarterly / annual")
    why_needed: str
    mandatory: bool
    evidence_page: int


class ReportedResult(BaseModel):
    """A number printed in the paper, WITH the accounting basis it was computed on.

    `basis` is the field that regex extraction cannot produce and that makes the
    difference between a falsifiable replication target and an unfalsifiable one.
    """
    portfolio: str
    metric: str = Field(description="cagr / vol / sharpe / max_dd / mean_dd / turnover / other")
    value: float = Field(description="Decimal, not percent: 11.6% -> 0.116")
    basis: str = Field(description="e.g. 'pre-tax nominal', 'inflation-adjusted', 'post-tax bracket B3', 'lagged data'")
    is_headline: bool = Field(description="True only for the paper's primary, pre-tax, full-sample table")
    evidence_page: int


class EquationFinding(BaseModel):
    """An equation the model read from the rendered page, restated in plain notation.

    Flagged separately because extracted PDF text mangles mathematics: a human
    must confirm these against the page before they become card fields.
    """
    label: str = Field(description="e.g. 'eq 1', 'eq 3', 'volatility estimator'")
    plain_statement: str = Field(description="The equation restated unambiguously in words or ASCII")
    governs: str = Field(description="Which card field this equation determines")
    evidence_page: int
    confidence: Confidence


class PaperAnalysis(BaseModel):
    """What Step 01 produces instead of a bag of regex hits."""
    title: str
    authors: List[str]
    year: Optional[int] = None
    code_url: Optional[str] = Field(default=None, description="Open-source replication code, if the paper publishes any")

    universe_description: str
    asset_class: str
    geography: str
    assets_studied: List[str]
    benchmark: str

    core_mechanism: str = Field(
        description="What actually generates the excess return, in two sentences. "
                    "Not the abstract -- the mechanism.")
    rebalance_frequency: str
    lookback_days: Optional[int] = None
    implementation_lag_days: Optional[int] = Field(
        default=None, description="Lag the PAPER assumes, not what we would need")
    costs_assumed_bps: Optional[float] = None
    long_only: bool
    uses_leverage: bool
    holds_cash: bool = Field(description="Does the strategy hold cash as part of its mechanism?")

    sample_start: Optional[str] = None
    sample_end: Optional[str] = None

    data_requirements: List[DataRequirementFinding]
    reported_results: List[ReportedResult]
    equations: List[EquationFinding]

    accounting_bases_present: List[str] = Field(
        description="Every distinct basis the paper reports results on. More than one means "
                    "naive target harvesting produces an unfalsifiable replication test.")
    hyperparameters_selected_in_sample: List[str] = Field(
        description="Any parameter the paper admits choosing by searching the full sample. "
                    "These inflate the trial budget for the deflated Sharpe ratio.")

    overall_confidence: Confidence
    extraction_concerns: List[str] = Field(
        description="Anything that made reading this document unreliable: scanned pages, "
                    "figures-only results, ambiguous notation.")


# ---------------------------------------------------------------------------
# Step 02 -- STRATEGY CARD + adversarial ambiguity hunt
# ---------------------------------------------------------------------------
class AmbiguityFinding(BaseModel):
    field: str = Field(description="Dotted card path, e.g. 'metrics.sharpe', 'costs.cost_model'")
    issue: str = Field(description="What the paper leaves genuinely under-specified")
    why_it_matters: str = Field(description="The concrete way a replication diverges if read the other way")
    proposed_resolution: str
    materiality: Materiality
    confidence: Confidence
    evidence_page: Optional[int] = None


class AmbiguityReport(BaseModel):
    findings: List[AmbiguityFinding]
    missed_by_first_pass: List[str] = Field(
        description="Fields the drafting agent recorded as unambiguous that are not.")


class CardProposal(BaseModel):
    """A draft Strategy Card. NOT a card until it validates against the YAML schema
    and a human signs it off at Gate A."""
    card_yaml: str = Field(description="Complete Strategy Card YAML, schema-conformant")
    mode: Literal["replication", "adaptation"]
    transferred_mechanism: Optional[str] = Field(
        default=None, description="Required for adaptation cards: what actually carries over")
    broken_assumptions: List[str] = Field(
        default_factory=list,
        description="Assumptions the source paper relies on that do not hold in our setting")
    template_choice_reasoning: str
    n_configs_estimate: int = Field(
        description="Honest count of configurations the PAPER tried, including sweeps in appendices")
    open_questions_for_human: List[str]


# ---------------------------------------------------------------------------
# Step 03 -- FEASIBILITY. Semantic matching instead of string equality.
# ---------------------------------------------------------------------------
class RequirementMatch(BaseModel):
    requirement: str
    match_type: Literal["exact", "proxy", "none"]
    matched_series: Optional[str] = None
    reasoning: str
    proxy_risk: Optional[str] = Field(
        default=None, description="If a proxy: what economic claim changes by substituting it")
    confidence: Confidence


class FeasibilityMapping(BaseModel):
    matches: List[RequirementMatch]
    procurement_suggestions: List[str] = Field(
        description="What to buy or license to unblock this paper, most valuable first")


# ---------------------------------------------------------------------------
# Step 05 -- TEMPLATE SELECTION. The model picks; it does not write engine code.
# ---------------------------------------------------------------------------
class TemplateMatch(BaseModel):
    template: Optional[str] = Field(
        description="Name of a REGISTERED template, or null if none fits")
    reasoning: str
    param_mapping: str = Field(description="YAML fragment for signal.params")
    missing_capability: Optional[str] = Field(
        default=None,
        description="If no template fits: precisely what an allocator would need to do. "
                    "A human writes it; the model does not.")
    confidence: Confidence


# ---------------------------------------------------------------------------
# Step 06/07 -- ADVERSARIAL REVIEW OF OUR OWN RESULTS
# ---------------------------------------------------------------------------
class CritiqueFinding(BaseModel):
    observation: str = Field(description="The specific number or pattern that is suspicious")
    severity: Literal["blocking", "serious", "note"]
    why_suspicious: str
    suggested_test: str = Field(description="A concrete additional check that would settle it")


class ResultsCritique(BaseModel):
    """An agent whose ONLY job is to attack our own backtest.

    Run with no stake in the outcome and given the full diagnostic table, this is
    where an LLM is genuinely strong: it reads a lag-sensitivity curve that rises
    and says 'that means no timing information', which is a pattern-recognition
    task, not a numerical one.
    """
    findings: List[CritiqueFinding]
    headline_verdict: Literal["result_is_credible", "result_is_fragile", "result_is_not_real"]
    one_paragraph_summary: str


# ---------------------------------------------------------------------------
# Step 08 -- LIBRARY. Semantic recall over the research graph.
# ---------------------------------------------------------------------------
class PriorWorkHit(BaseModel):
    entry_id: str
    why_similar: str
    supersedes_this: bool = Field(
        description="True if the prior entry already answers the question this card asks")


class LibrarianAnswer(BaseModel):
    hits: List[PriorWorkHit]
    recommendation: Literal["proceed", "proceed_with_narrower_question", "do_not_run"]
    reasoning: str
