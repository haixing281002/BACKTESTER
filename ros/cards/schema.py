"""Strategy Card schema -- Step 02 of the pipeline.

The Strategy Card is the ONLY interface between paper interpretation (AI, fallible)
and the deterministic engine. Nothing in the engine reads the PDF. If a paper cannot
be expressed as a card, it cannot be run: that is the point, not a limitation.

Design rule: a card is data, never code. Adding a new paper must never require
editing the engine -- only writing a new YAML card, and (rarely) registering one
small signal function in ros/engine/primitives.py.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Controlled vocabularies. Free text here is how silent divergence starts.
# ---------------------------------------------------------------------------
MODES = {"replication", "adaptation"}
CONFIDENCE = {"high", "medium", "low"}
FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "annual"}
REBALANCE = {"daily", "weekly", "monthly", "quarterly", "annual", "calendar_year_end"}
DATA_KINDS = {
    "price", "total_return_index", "volume", "fundamental", "membership",
    "corporate_action", "risk_free_rate", "macro", "factor_return", "publication_date",
}


def _wrap(text: str, width: int) -> List[str]:
    """Soft-wrap for the human-facing blocks. Long prose in a terminal is prose
    nobody reads, and these blocks exist to be read."""
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


class CardValidationError(ValueError):
    """Raised when a card is structurally unusable. Never downgraded to a warning."""


@dataclass
class DataRequirement:
    """One series the paper needs. Step 03 resolves each of these to
    available / proxy / unavailable."""
    name: str
    kind: str
    frequency: str = "daily"
    start: Optional[str] = None
    mandatory: bool = True
    purpose: str = ""
    evidence_page: Optional[int] = None
    # Set by the feasibility gate, not by the card author.
    acceptable_proxies: List[str] = field(default_factory=list)

    def validate(self, ctx: str) -> List[str]:
        errs = []
        if self.kind not in DATA_KINDS:
            errs.append(f"{ctx}: data kind '{self.kind}' not in {sorted(DATA_KINDS)}")
        if self.frequency not in FREQUENCIES:
            errs.append(f"{ctx}: frequency '{self.frequency}' not in {sorted(FREQUENCIES)}")
        return errs


@dataclass
class Ambiguity:
    """An interpretation decision that a human must own at Gate A.

    Every ambiguity carries a resolution BEFORE the backtest runs. An unresolved
    ambiguity blocks the pipeline -- the engine must never pick a default silently.
    """
    field: str
    issue: str
    resolution: str = ""
    confidence: str = "low"
    evidence_page: Optional[int] = None
    material: bool = True  # does this plausibly move the headline metric?

    def validate(self, ctx: str) -> List[str]:
        errs = []
        if self.confidence not in CONFIDENCE:
            errs.append(f"{ctx}: confidence '{self.confidence}' not in {sorted(CONFIDENCE)}")
        if not self.resolution.strip():
            errs.append(f"{ctx}: ambiguity '{self.field}' has no resolution (Gate A blocker)")
        return errs


@dataclass
class ReplicationTarget:
    """A number printed in the paper that our run must reproduce.

    This is what turns 'we coded something' into 'we replicated the paper'.
    A card with no replication targets can never clear the REPLICATED rung.
    """
    portfolio: str
    metric: str
    value: float
    tolerance: float = 0.10       # relative tolerance unless absolute_tolerance set
    absolute_tolerance: Optional[float] = None
    evidence_page: Optional[int] = None


PRIORITIES = {"blocking", "high", "nice_to_have"}
ASK_OF = {"data_owner", "pm", "researcher", "anyone"}


@dataclass
class DataRequest:
    """Something the model wants FROM YOU, in order to test this properly.

    Distinct from `data_requirements`, which says what the PAPER needs and is
    resolved mechanically against the registry. A DataRequest is addressed to a
    human: here is what I would ask for, here is what it buys, and here is what
    I will do instead if you say no.

    That last field is the one that matters. A request with no stated fallback
    is a demand, and a demand at Gate A stops the work. A request that says
    "without it I will use a flat 6% proxy and sweep 4-8%, which makes every
    cash result rate-dependent" lets a human decide whether that is good enough
    for the question being asked.
    """
    item: str = ""
    why: str = ""                       # what the mechanism needs it for
    unlocks: str = ""                   # what becomes possible with it
    without_it: str = ""                # the fallback, and what it costs
    priority: str = "high"              # blocking | high | nice_to_have
    format_hint: str = ""               # so a human knows what to send
    evidence_page: Optional[int] = None

    def validate(self, ctx: str) -> List[str]:
        errs = []
        if not self.item.strip():
            errs.append(f"{ctx}: item is required")
        if self.priority not in PRIORITIES:
            errs.append(f"{ctx}: priority '{self.priority}' not in {sorted(PRIORITIES)}")
        if not self.without_it.strip():
            errs.append(f"{ctx}: state `without_it` -- a request with no fallback "
                        f"is a demand, and a demand at Gate A stops the work")
        return errs


@dataclass
class OpenQuestion:
    """Something the model cannot settle from the paper and is asking a human.

    An Ambiguity carries a resolution the model chose. An OpenQuestion is the
    honest other case: the paper does not say, the choice is the fund's to make,
    and the model has taken a position it wants confirmed rather than assumed.

    `what_i_assumed` is mandatory. A question with no working assumption blocks
    the pipeline for no reason -- the run can proceed under a stated guess, and
    a human can overturn it. A question with no assumption is the model asking
    someone else to do its job.
    """
    question: str = ""
    why_it_matters: str = ""
    what_i_assumed: str = ""
    ask_of: str = "researcher"          # data_owner | pm | researcher | anyone
    blocks_run: bool = False
    evidence_page: Optional[int] = None

    def validate(self, ctx: str) -> List[str]:
        errs = []
        if not self.question.strip():
            errs.append(f"{ctx}: question is required")
        if self.ask_of not in ASK_OF:
            errs.append(f"{ctx}: ask_of '{self.ask_of}' not in {sorted(ASK_OF)}")
        if not self.blocks_run and not self.what_i_assumed.strip():
            errs.append(f"{ctx}: state `what_i_assumed` or set blocks_run -- a "
                        f"question with neither stalls the run for no reason")
        return errs


@dataclass
class MechanismNeeds:
    """What the PAPER's mechanism needs from a universe, read at Stage 01.

    Every field is a claim about the paper, not about India. They are what
    ros/data/universes.py scores the catalogue against, so getting them right is
    the whole job: `min_names` in particular should be what the paper's own
    construction implies (ten buckets wanting ten names each is 100), not a
    round number picked to make a preferred universe win.
    """
    needs_cross_section: bool = True
    min_names: int = 100
    cap_segment: str = "all"            # mega|large|large_mid|mid|mid_small|small|micro|all
    sector: Optional[str] = None        # set only for a sector-specific paper
    min_history_years: float = 10.0
    must_be_in_mandate: bool = False    # True only if the run must be holdable
    notes: str = ""

    def validate(self, ctx: str = "mechanism_needs") -> List[str]:
        from ros.data.universes import SEGMENTS
        errs = []
        if self.cap_segment not in SEGMENTS:
            errs.append(f"{ctx}: cap_segment '{self.cap_segment}' not in {SEGMENTS}")
        if self.min_names < 1:
            errs.append(f"{ctx}: min_names must be >= 1")
        return errs


@dataclass
class UniverseTranslation:
    """What the paper studied, and what we will actually test it on.

    A paper sorts S&P 500 constituents; this fund is long-only NIFTY 500.
    Somebody has to decide the Indian analogue and own what breaks on the way.
    Recording that decision ON THE CARD -- rather than leaving it implicit in a
    choice of tickers -- is what lets two papers be compared later, and what
    lets a reader six months on see which correspondence was approved and why.

    `grade` and `resolution` come from ros/data/universes.py, which holds the
    correspondences as recorded institutional decisions rather than re-deriving
    them per paper. `transfer_risks` is what a human signs for at Gate A.
    """
    source_universe: str = ""          # as the paper describes it
    source_breadth: Optional[int] = None
    source_selection_rule: str = ""    # how the paper picks from its universe
    target_universe: str = ""          # the Indian analogue
    grade: str = ""                    # exact | close | loose | none
    resolution: str = ""               # direct | sleeve_proxy | needs_data | infeasible
    rationale: str = ""
    transfer_risks: List[str] = field(default_factory=list)
    required_instruments: List[str] = field(default_factory=list)
    evidence_page: Optional[int] = None
    # What the mechanism needed, and what else was on the table. Recording the
    # runners-up is what stops a universe choice being unfalsifiable later: a
    # reader can see the alternatives were considered rather than assumed away.
    mechanism_needs: Optional[MechanismNeeds] = None
    alternatives_considered: List[str] = field(default_factory=list)
    why_not_alternatives: str = ""

    def validate(self, ctx: str = "universe_translation") -> List[str]:
        from ros.data.universes import GRADES, RESOLUTIONS, NONE
        errs = []
        if not self.source_universe:
            errs.append(f"{ctx}: source_universe is required")
        if self.grade and self.grade not in GRADES:
            errs.append(f"{ctx}: grade '{self.grade}' not in {GRADES}")
        if self.resolution and self.resolution not in RESOLUTIONS:
            errs.append(f"{ctx}: resolution '{self.resolution}' not in {RESOLUTIONS}")
        if self.grade and self.grade != NONE and not self.target_universe:
            errs.append(f"{ctx}: grade '{self.grade}' requires a target_universe")
        # A translation with no stated risk is not a clean translation; it is an
        # unexamined one. Every recorded correspondence in universes.py carries
        # at least one, so an empty list means nobody looked.
        if self.target_universe and not self.transfer_risks:
            errs.append(f"{ctx}: no transfer_risks listed -- a translation with "
                        f"nothing to lose has not been examined")
        if self.mechanism_needs is not None:
            errs += self.mechanism_needs.validate()
        return errs


@dataclass
class StrategyReconstruction:
    """The paper's strategy, restated mechanically enough to be executable.

    Stage 01's real output. Prose like "we buy cheap stocks" is not a strategy;
    this is the level of detail at which a template can be chosen, or a human
    told exactly what is missing.

    `long_only_adaptation` is mandatory when the paper is long-short, because
    this fund cannot short. Dropping the short leg is not a haircut -- academic
    factor premia often live substantially in it -- so the adaptation is
    recorded, not assumed.
    """
    signal_name: str = ""
    signal_definition: str = ""        # unambiguous, executable prose
    inputs_required: List[str] = field(default_factory=list)
    cross_sectional: bool = False      # ranks securities vs times one series
    formation_rule: str = ""           # how the signal becomes a selection
    weighting_rule: str = ""           # how selection becomes weights
    holding_period: str = ""
    rebalance_frequency: str = ""
    is_long_short: bool = False
    long_only_adaptation: str = ""     # required when is_long_short
    constraints: List[str] = field(default_factory=list)
    engine_template: str = ""          # a registered template, or NEEDS_NEW_TEMPLATE
    template_gap: str = ""             # spec for a human, when no template fits
    confidence: str = "low"
    evidence_pages: List[int] = field(default_factory=list)

    def validate(self, ctx: str = "strategy") -> List[str]:
        errs = []
        if self.confidence not in CONFIDENCE:
            errs.append(f"{ctx}: confidence '{self.confidence}' not in {sorted(CONFIDENCE)}")
        if not self.signal_definition.strip():
            errs.append(f"{ctx}: signal_definition is required -- prose like "
                        f"'buy cheap stocks' is not a strategy")
        if self.is_long_short and not self.long_only_adaptation.strip():
            errs.append(f"{ctx}: paper is long-short and this fund cannot short. "
                        f"State long_only_adaptation explicitly; dropping the "
                        f"short leg silently changes the strategy")
        if self.engine_template == "NEEDS_NEW_TEMPLATE" and not self.template_gap.strip():
            errs.append(f"{ctx}: engine_template is NEEDS_NEW_TEMPLATE but "
                        f"template_gap does not say what to build")
        return errs


@dataclass
class Universe:
    description: str = ""
    asset_class: str = "equity"
    geography: str = ""
    assets: List[str] = field(default_factory=list)
    benchmark: Optional[str] = None
    cash_asset: Optional[str] = None


@dataclass
class Signal:
    """What the paper computes. `template` names an allocator in the engine registry;
    `params` are its arguments. No free-form code lives in the card."""
    name: str = ""
    template: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    lookback_days: Optional[int] = None
    lag_days: int = 0
    description: str = ""


@dataclass
class PortfolioSpec:
    rebalance: str = "monthly"
    long_only: bool = True
    max_gross: float = 1.0
    allow_cash: bool = True
    target_vol: Optional[float] = None
    start: Optional[str] = None
    end: Optional[str] = None
    # The FUND's mandate, which is not the paper's spec. When this differs from
    # `allow_cash`, the pipeline runs both: the faithful variant (does the
    # mechanism work?) and the mandate variant (may we actually run it?).
    # Conflating the two is how an un-runnable strategy reaches an IC deck.
    mandate_allow_cash: Optional[bool] = None


@dataclass
class CostSpec:
    spread_bps: float = 5.0        # full bid-ask spread in bps; charged at half
    cost_model: str = "half_spread"
    impact_bps_per_pct_adv: Optional[float] = None
    borrow_bps: Optional[float] = None


@dataclass
class Paper:
    id: str
    title: str = ""
    authors: List[str] = field(default_factory=list)
    date: Optional[str] = None
    source_file: Optional[str] = None
    source_sha256: Optional[str] = None
    url: Optional[str] = None


@dataclass
class Intent:
    """The board's first non-negotiable upgrade: replication and India-investability
    validation are different questions and must never share a verdict."""
    mode: str = "replication"
    parent_card: Optional[str] = None
    rationale: str = ""
    transferred_mechanism: str = ""   # for adaptations: what actually carries over
    broken_assumptions: List[str] = field(default_factory=list)


@dataclass
class StrategyCard:
    paper: Paper
    intent: Intent
    universe: Universe
    signal: Signal
    portfolio: PortfolioSpec
    costs: CostSpec
    # Stage 01 outputs. Optional so cards written before this existed still
    # load, but Gate A reports their absence rather than passing over it.
    universe_translation: Optional[UniverseTranslation] = None
    strategy: Optional[StrategyReconstruction] = None
    data_requirements: List[DataRequirement] = field(default_factory=list)
    ambiguities: List[Ambiguity] = field(default_factory=list)
    replication_targets: List[ReplicationTarget] = field(default_factory=list)
    benchmark_templates: List[Dict[str, Any]] = field(default_factory=list)
    # What the model wants FROM a human, and what it cannot settle alone. These
    # are the card's two outward-facing sections: everything else describes the
    # paper, these describe what is still needed to do it justice.
    data_requests: List[DataRequest] = field(default_factory=list)
    open_questions: List[OpenQuestion] = field(default_factory=list)
    n_configs_tried: int = 1     # feeds the deflated Sharpe ratio; understating it is a lie
    notes: str = ""
    card_version: str = "1.0"

    # ---------------- validation ----------------
    def validate(self) -> List[str]:
        errs: List[str] = []
        if self.intent.mode not in MODES:
            errs.append(f"intent.mode '{self.intent.mode}' not in {sorted(MODES)}")
        if self.intent.mode == "adaptation" and not self.intent.transferred_mechanism:
            errs.append("adaptation cards must state intent.transferred_mechanism")
        # A YAML list item containing an unquoted colon silently becomes a dict.
        # Catch it at load time rather than letting it surface as a type error
        # three steps later, in the middle of a report.
        for i, b in enumerate(self.intent.broken_assumptions):
            if not isinstance(b, str):
                errs.append(
                    f"intent.broken_assumptions[{i}] is {type(b).__name__}, not a string "
                    f"-- an unquoted ':' in a YAML list item parses as a mapping; quote it")
        if self.portfolio.rebalance not in REBALANCE:
            errs.append(f"portfolio.rebalance '{self.portfolio.rebalance}' not in {sorted(REBALANCE)}")
        if not self.signal.template:
            errs.append("signal.template is required (must name an engine template)")
        if not self.universe.assets:
            errs.append("universe.assets is empty")
        if self.signal.lag_days < 0:
            errs.append("signal.lag_days must be >= 0")
        if self.n_configs_tried < 1:
            errs.append("n_configs_tried must be >= 1")
        for i, d in enumerate(self.data_requirements):
            errs += d.validate(f"data_requirements[{i}]")
        for i, a in enumerate(self.ambiguities):
            errs += a.validate(f"ambiguities[{i}]")
        if self.intent.mode == "replication" and not self.replication_targets:
            errs.append("replication cards must carry at least one replication_target")
        if self.universe_translation is not None:
            errs += self.universe_translation.validate()
        if self.strategy is not None:
            errs += self.strategy.validate()
        for i, r in enumerate(self.data_requests):
            errs += r.validate(f"data_requests[{i}]")
        for i, q in enumerate(self.open_questions):
            errs += q.validate(f"open_questions[{i}]")
        return errs

    @property
    def blocking_requests(self) -> List[DataRequest]:
        return [r for r in self.data_requests if r.priority == "blocking"]

    @property
    def blocking_questions(self) -> List[OpenQuestion]:
        return [q for q in self.open_questions if q.blocks_run]

    def require_valid(self) -> "StrategyCard":
        errs = self.validate()
        if errs:
            raise CardValidationError(
                "Strategy Card failed validation:\n  - " + "\n  - ".join(errs))
        return self

    @property
    def unresolved_ambiguities(self) -> List[Ambiguity]:
        return [a for a in self.ambiguities if not a.resolution.strip()]

    @property
    def material_ambiguities(self) -> List[Ambiguity]:
        return [a for a in self.ambiguities if a.material]

    def fingerprint(self) -> str:
        """Stable hash of the card's economic content. Two cards with the same
        fingerprint are the same experiment and must not be counted twice."""
        econ = {
            "assets": sorted(self.universe.assets),
            "benchmark": self.universe.benchmark,
            "template": self.signal.template,
            "params": self.signal.params,
            "lookback": self.signal.lookback_days,
            "lag": self.signal.lag_days,
            "rebalance": self.portfolio.rebalance,
            "target_vol": self.portfolio.target_vol,
            "long_only": self.portfolio.long_only,
            "allow_cash": self.portfolio.allow_cash,
            "spread_bps": self.costs.spread_bps,
            "start": self.portfolio.start,
            "end": self.portfolio.end,
        }
        blob = yaml.safe_dump(econ, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def at_a_glance(self) -> str:
        """The nine fields a reviewer checks first, on one screen.

        Gate A's job is to make five minutes count. A reviewer who reads only
        this block should be able to say "that is not the strategy I expected"
        or "that lag cannot be right" -- which are the two objections that are
        cheap here and expensive after a run.

        Every value is read off the card. Nothing is defaulted for display: a
        blank means the card does not say, and a card that does not say is a
        Gate A item rather than something to fill in politely.
        """
        ut, st = self.universe_translation, self.strategy
        unset = "-- not stated --"

        universe = (ut.target_universe if ut and ut.target_universe
                    else (self.universe.description.split(".")[0][:46]
                          if self.universe.description else unset))
        source = f"  (from: {ut.source_universe})" if ut and ut.source_universe else ""
        signal = st.signal_name if st and st.signal_name else (
            self.signal.name or self.signal.template or unset)
        kind = ("cross-sectional" if st and st.cross_sectional else
                "time-series" if st else "?")
        lookback = (f"{self.signal.lookback_days}d" if self.signal.lookback_days
                    else unset)
        lag = f"{self.signal.lag_days}d"
        weights = (" ".join(st.weighting_rule.split())[:60] if st and st.weighting_rule
                   else self.signal.template or unset)
        rebalance = (st.rebalance_frequency if st and st.rebalance_frequency
                     else self.portfolio.rebalance)
        benchmark = self.universe.benchmark or unset
        costs = (f"{self.costs.spread_bps:.0f}bp round trip ({self.costs.cost_model})"
                 if self.costs.spread_bps else unset)

        n_amb = len(self.ambiguities)
        unresolved = len(self.unresolved_ambiguities)
        material = len(self.material_ambiguities)
        low = [a.field for a in self.material_ambiguities if a.confidence == "low"]
        amb = (f"{n_amb} logged, {material} material, {unresolved} UNRESOLVED"
               if unresolved else f"{n_amb} logged, {material} material, all resolved")
        conf = st.confidence if st else unset

        mandate = []
        if self.portfolio.long_only:
            mandate.append("long-only")
        if st and st.is_long_short:
            mandate.append("SOURCE IS LONG-SHORT")
        if self.portfolio.mandate_allow_cash is False and self.portfolio.allow_cash:
            mandate.append("mandate forbids cash; paper uses it")

        W = 96
        L = ["  " + "-" * W,
             f"  STRATEGY CARD AT A GLANCE   {self.paper.id}",
             "  " + "-" * W,
             f"    universe   : {universe}{source}",
             f"    signal     : {signal}   [{kind}]",
             f"    lookback   : {lookback:<14} lag: {lag}",
             f"    weights    : {weights}",
             f"    rebalance  : {rebalance:<14} benchmark: {benchmark}",
             f"    costs      : {costs}",
             f"    ambiguities: {amb}",
             f"    confidence : {conf}"]
        if low:
            L.append(f"                 LOW on: {', '.join(low)}")
        if mandate:
            L.append(f"    mandate    : {'; '.join(mandate)}")
        if st and st.engine_template:
            L.append(f"    engine     : {st.engine_template}"
                     + ("   NO TEMPLATE FITS -- a human must build one first"
                        if st.engine_template == "NEEDS_NEW_TEMPLATE" else ""))
        L.append("  " + "-" * W)
        return "\n".join(L)

    def asks(self) -> str:
        """What the model wants from a human, formatted for Gate A.

        Gate A is a conversation, not a form. This is the model's half of it:
        here is what I would ask you for, what it buys, and what I will do if
        you say no; and here is what the paper does not settle, with the
        position I have taken meanwhile.
        """
        if not self.data_requests and not self.open_questions:
            return ("  NOTHING IS BEING ASKED FOR.\n"
                    "  No data request and no open question on this card. That "
                    "is a strong claim --\n  it says no further data would "
                    "improve this test and the paper settled everything.\n"
                    "  Worth confirming rather than assuming nobody looked.")

        W = 96
        L = ["  " + "=" * W, "  WHAT WOULD MAKE THIS TEST BETTER", "  " + "=" * W]
        order = {"blocking": 0, "high": 1, "nice_to_have": 2}
        for r in sorted(self.data_requests, key=lambda x: order.get(x.priority, 9)):
            tag = {"blocking": "BLOCKING", "high": "would help",
                   "nice_to_have": "optional"}.get(r.priority, r.priority)
            L.append("")
            L.append(f"  [{tag}] {r.item}")
            for label, val in (("why", r.why), ("unlocks", r.unlocks),
                               ("if declined", r.without_it),
                               ("format", r.format_hint)):
                if str(val or "").strip():
                    for i, line in enumerate(_wrap(" ".join(str(val).split()), W - 18)):
                        L.append(f"      {label if i == 0 else '':<12} {line}")

        if self.open_questions:
            L.append("")
            L.append("  " + "-" * W)
            L.append("  QUESTIONS THE PAPER DOES NOT SETTLE")
            L.append("  " + "-" * W)
            for q in self.open_questions:
                who = {"pm": "for the PM", "data_owner": "for the data owner",
                       "researcher": "for the researcher"}.get(q.ask_of, "for anyone")
                stop = "  [BLOCKS THE RUN]" if q.blocks_run else ""
                L.append("")
                for i, line in enumerate(_wrap(" ".join(q.question.split()), W - 8)):
                    L.append(f"  {'Q:' if i == 0 else '  '} {line}")
                L.append(f"      {who}{stop}")
                for label, val in (("matters because", q.why_it_matters),
                                   ("I assumed", q.what_i_assumed)):
                    if str(val or "").strip():
                        for i, line in enumerate(
                                _wrap(" ".join(str(val).split()), W - 22)):
                            L.append(f"      {label if i == 0 else '':<16} {line}")
        L.append("")
        L.append("  " + "=" * W)
        return "\n".join(L)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_yaml(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.to_dict(), fh, sort_keys=False, width=100)


# Sections that themselves contain a dataclass, so _build knows to descend.
_NESTED = {}


def _build(cls, blob, name):
    if blob is None:
        return cls() if name != "paper" else None
    if not isinstance(blob, dict):
        raise CardValidationError(f"card section '{name}' must be a mapping, got {type(blob)}")
    allowed = {f for f in cls.__dataclass_fields__}
    unknown = set(blob) - allowed
    if unknown:
        # Silent key-drop is how a card and a run diverge. Refuse instead.
        raise CardValidationError(f"card section '{name}' has unknown keys: {sorted(unknown)}")
    kw = dict(blob)
    # One level of nesting, declared explicitly. A generic recursive builder
    # would have to guess from type hints, and guessing wrong here silently
    # hands the engine a dict where it expects a dataclass.
    for key, sub in _NESTED.get(cls, {}).items():
        if isinstance(kw.get(key), dict):
            kw[key] = _build(sub, kw[key], f"{name}.{key}")
    return cls(**kw)


_NESTED[UniverseTranslation] = {"mechanism_needs": MechanismNeeds}


def load_card(path: str) -> StrategyCard:
    """Load and validate a Strategy Card from YAML. Unknown keys are an error."""
    with open(path, encoding="utf-8") as fh:
        blob = yaml.safe_load(fh) or {}

    known = {"paper", "intent", "universe", "signal", "portfolio", "costs",
             "data_requirements", "ambiguities", "replication_targets",
             "benchmark_templates", "n_configs_tried", "notes", "card_version",
             "universe_translation", "strategy", "data_requests",
             "open_questions"}
    unknown = set(blob) - known
    if unknown:
        raise CardValidationError(f"card has unknown top-level keys: {sorted(unknown)}")
    if "paper" not in blob:
        raise CardValidationError("card is missing required section 'paper'")

    card = StrategyCard(
        paper=_build(Paper, blob["paper"], "paper"),
        intent=_build(Intent, blob.get("intent"), "intent"),
        universe=_build(Universe, blob.get("universe"), "universe"),
        signal=_build(Signal, blob.get("signal"), "signal"),
        portfolio=_build(PortfolioSpec, blob.get("portfolio"), "portfolio"),
        costs=_build(CostSpec, blob.get("costs"), "costs"),
        data_requirements=[_build(DataRequirement, d, f"data_requirements[{i}]")
                           for i, d in enumerate(blob.get("data_requirements") or [])],
        ambiguities=[_build(Ambiguity, a, f"ambiguities[{i}]")
                     for i, a in enumerate(blob.get("ambiguities") or [])],
        replication_targets=[_build(ReplicationTarget, r, f"replication_targets[{i}]")
                             for i, r in enumerate(blob.get("replication_targets") or [])],
        benchmark_templates=blob.get("benchmark_templates") or [],
        n_configs_tried=blob.get("n_configs_tried", 1),
        notes=blob.get("notes", ""),
        card_version=blob.get("card_version", "1.0"),
        universe_translation=(
            _build(UniverseTranslation, blob["universe_translation"],
                   "universe_translation")
            if blob.get("universe_translation") else None),
        strategy=(_build(StrategyReconstruction, blob["strategy"], "strategy")
                  if blob.get("strategy") else None),
        data_requests=[_build(DataRequest, r, f"data_requests[{i}]")
                       for i, r in enumerate(blob.get("data_requests") or [])],
        open_questions=[_build(OpenQuestion, q, f"open_questions[{i}]")
                        for i, q in enumerate(blob.get("open_questions") or [])],
    )
    return card.require_valid()
