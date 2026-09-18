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
from typing import Dict, List, Literal, Optional

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


class UniverseTranslationFinding(BaseModel):
    """Which universe the paper studied, and which Indian one replaces it.

    The model IDENTIFIES the source and proposes a target; the recorded
    correspondences live in ros/data/universes.py and the code checks the
    proposal against them. Inventing a mapping here would mean the same paper
    read twice produces two different universes, and the strategy library stops
    being comparable across entries.
    """
    source_universe: str = Field(
        description="As the paper CONSTRUCTS it, not as its abstract summarises "
                    "it: 'S&P 500 ex-financials, NYSE breakpoints', not 'US stocks'")
    source_breadth: Optional[int] = Field(
        default=None, description="How many securities the paper's universe holds")
    source_selection_rule: str = Field(
        description="How the paper picks from its universe, or 'none' if fixed")
    target_universe: str = Field(
        description="The Indian analogue, named exactly as ros/data/universes.py "
                    "does. Empty if no honest correspondence exists.")
    grade: str = Field(description="exact / close / loose / none")
    rationale: str = Field(description="Why this target, and what drove the choice "
                                       "when several were available")
    transfer_risks: List[str] = Field(
        description="What breaks in THIS translation specifically. The generic "
                    "India caveats attach automatically -- do not repeat them.")
    required_instruments: List[str] = Field(
        description="What a faithful test needs, in the fund's vocabulary")
    evidence_page: Optional[int] = None
    confidence: Confidence


class StrategyReconstructionFinding(BaseModel):
    """The paper's strategy, mechanical enough that a second person could
    implement it from these words alone and get the same portfolio."""
    signal_name: str
    signal_definition: str = Field(
        description="Every window, lag and skip. How ties break. What happens to "
                    "missing data. Vagueness here is an Ambiguity, not a guess.")
    inputs_required: List[str] = Field(
        description="Data fields consumed, specifically: 'daily adjusted close', "
                    "'as-reported EPS with publication date'")
    cross_sectional: bool = Field(
        description="True if it RANKS securities against each other; False if it "
                    "times one stream against its own history")
    formation_rule: str = Field(description="How the signal becomes a selection")
    weighting_rule: str = Field(description="How the selection becomes weights")
    holding_period: str
    rebalance_frequency: str
    is_long_short: bool = Field(
        description="True if the headline result involves a short leg. This fund "
                    "cannot short, so this forces an explicit adaptation.")
    long_only_adaptation: str = Field(
        default="",
        description="REQUIRED when is_long_short. What was dropped and what it "
                    "plausibly cost -- the short leg often carries the larger half "
                    "of the spread, so this is not a haircut, it can remove most "
                    "of the result.")
    constraints: List[str]
    engine_template: str = Field(
        description="A template from ros.engine.templates.list_templates(), or "
                    "NEEDS_NEW_TEMPLATE. Do not force a bad fit.")
    template_gap: str = Field(
        default="",
        description="REQUIRED when engine_template is NEEDS_NEW_TEMPLATE: a spec "
                    "a human can implement from -- inputs, outputs, constraints, "
                    "objective")
    evidence_pages: List[int]
    confidence: Confidence


class DataSpecFinding(BaseModel):
    """One field of the dataset this paper DESERVES, designed from the paper.

    Not selected from what the fund holds. Design first, check availability
    after -- inverting that reshapes a paper into whatever the existing data can
    answer, which is a different paper with the same title.
    """
    field: str
    granularity: str = Field(description="tick / minute / daily / weekly / monthly / quarterly")
    history_from: str
    why: str = Field(description="what the MECHANISM needs it for")
    why_granularity: str = Field(
        description="why not coarser AND why not finer. The choice that decides "
                    "what the data costs, and it is usually made by habit")
    why_history: str = Field(description="why this start date; what the window includes")
    adjustments: str = Field(
        description="corporate actions, free float, publication dates. Two vendors "
                    "sell a file with the same NAME and only one lets you run it")
    minimum_viable: bool = Field(
        description="True only if the answer is NOT INTERPRETABLE without it. Most "
                    "fields improve what you may CLAIM, not what the answer is")


class DataPlanFinding(BaseModel):
    ideal: List[DataSpecFinding]
    rejected_alternatives: List[Dict[str, str]] = Field(
        description="each {option, why_not}. A dataset with no rejected "
                    "alternative was not designed, it was assumed")
    granularity_verdict: str
    optimality_argument: str = Field(
        description="why THIS dataset is the right way to test THIS paper in "
                    "Indian equities -- optimal, not merely sufficient")
    what_would_change_the_answer: str = Field(
        description="which fields could move the verdict, versus which only "
                    "change what may be claimed from it")


class SecuritySelectionFinding(BaseModel):
    rule: str = Field(description="always required; a named list without a rule "
                                  "cannot be re-derived on another date")
    explicit_securities: List[str] = Field(
        default_factory=list,
        description="optional and dangerous. Naming stocks from memory produces a "
                    "plausible unverifiable list, which is WORSE than no list "
                    "because it looks checked")
    verified_against: str = Field(
        default="",
        description="paper / master_universe / firm_registry / index_factsheet / "
                    "supplied_by_human / UNVERIFIED. Use UNVERIFIED honestly "
                    "rather than naming a source you did not check")
    as_of: str = Field(default="",
                       description="membership is true on a DATE, not in general")
    why_these: str = ""


class BacktestPlanFinding(BaseModel):
    """Exactly what will be run, so Gate A verifies rather than designs."""
    sample_start: str
    sample_end: str
    why_this_window: str = Field(
        description="an unargued sample is the easiest place to pick a period "
                    "that flatters the result")
    warmup_days: Optional[int] = None
    why_warmup: str = ""
    rebalance_rule: str
    weights_rule: str
    explicit_weights: Dict[str, float] = Field(default_factory=dict)
    benchmarks: List[Dict[str, str]] = Field(
        description="each {name, why_this}. Name the do-nothing option, the "
                    "off-the-shelf product that would replace this for zero "
                    "turnover, and a stripped-down version isolating the machinery")
    must_beat: List[str] = Field(
        description="named BEFORE the run, so the bar cannot move afterwards")
    success_looks_like: str
    failure_looks_like: str = Field(
        description="mandatory. A plan that cannot fail is not a test")
    known_failure_modes: List[str]


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

    # Stage 01's two heaviest outputs. See .claude/commands/ingest.md.
    universe_translation: Optional[UniverseTranslationFinding] = None
    strategy: Optional[StrategyReconstructionFinding] = None
    # Stage 02's deliverable. See .claude/commands/draft-card.md.
    data_plan: Optional[DataPlanFinding] = None
    selection: Optional[SecuritySelectionFinding] = None
    backtest_plan: Optional[BacktestPlanFinding] = None

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
