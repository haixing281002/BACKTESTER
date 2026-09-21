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


HEADLINE_MAX = 100


def _check_headline(text: str, ctx: str) -> List[str]:
    """A headline longer than one line is not a headline.

    Optional everywhere -- a card written before this existed still loads, and
    the summary falls back to a truncated first clause with an ellipsis so a
    reader can see it was cut rather than written. What is NOT allowed is a
    headline that is itself a paragraph, because then the one-page sheet is the
    document again.
    """
    t = " ".join(str(text or "").split())
    if t and len(t) > HEADLINE_MAX:
        return [f"{ctx}: headline is {len(t)} chars; keep it under "
                f"{HEADLINE_MAX} -- it has to fit one line on a decision sheet"]
    return []


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
    # One line a human can rule on without reading the paragraph below it.
    # Written by the model, because compressing an argument is a judgement --
    # mechanical extraction can only TRUNCATE, and a headline cut mid-sentence
    # is what made the old gate unreadable. The full text always stays below it;
    # this is a pointer, never a replacement.
    headline: str = ""

    def validate(self, ctx: str) -> List[str]:
        errs = []
        errs += _check_headline(self.headline, ctx)
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


GRANULARITIES = {"tick", "minute", "daily", "weekly", "monthly", "quarterly"}
VERIFY_SOURCES = {"paper", "master_universe", "firm_registry", "index_factsheet",
                  "supplied_by_human", "UNVERIFIED"}


@dataclass
class DataSpec:
    """One field of the dataset this paper DESERVES, designed from the paper.

    Not selected from what the fund happens to hold. The order matters: design
    the right dataset first, then discover what is available. Inverting that --
    starting from the eight series on the shelf -- is how a paper gets quietly
    reshaped into whatever the existing data can answer, which is a different
    paper.

    `why_granularity` and `why_history` exist because those two choices are
    where cost and correctness trade off hardest, and both are usually made by
    habit. A 21-day skip cannot be computed from monthly closes; twenty years of
    tick data answers a question nobody asked.
    """
    field: str = ""
    granularity: str = "daily"
    history_from: str = ""
    why: str = ""                      # what the mechanism needs it for
    why_granularity: str = ""          # why not coarser, why not finer
    why_history: str = ""              # why this start date
    adjustments: str = ""              # corporate actions, float, publication date
    minimum_viable: bool = False       # in the smallest honest subset?

    def validate(self, ctx: str) -> List[str]:
        errs = []
        if not self.field.strip():
            errs.append(f"{ctx}: field is required")
        if self.granularity not in GRANULARITIES:
            errs.append(f"{ctx}: granularity '{self.granularity}' not in "
                        f"{sorted(GRANULARITIES)}")
        if not self.why.strip():
            errs.append(f"{ctx}: say what the mechanism needs this for")
        if not self.why_granularity.strip():
            errs.append(f"{ctx}: say why this granularity and not coarser -- it "
                        f"is the choice that decides what the data costs")
        return errs


@dataclass
class DataPlan:
    """The dataset this paper deserves, and the argument that it is the right one.

    The section a human reads to answer "are we testing this properly, or
    testing what we happen to own?"
    """
    ideal: List[DataSpec] = field(default_factory=list)
    rejected_alternatives: List[Dict[str, str]] = field(default_factory=list)
    optimality_argument: str = ""
    granularity_verdict: str = ""      # the headline call, with its reason
    what_would_change_the_answer: str = ""

    def validate(self, ctx: str = "data_plan") -> List[str]:
        errs = []
        if not self.ideal:
            errs.append(f"{ctx}: ideal is empty -- the card must say what dataset "
                        f"this paper deserves before anyone checks what we hold")
        for i, d in enumerate(self.ideal):
            errs += d.validate(f"{ctx}.ideal[{i}]")
        if not self.optimality_argument.strip():
            errs.append(f"{ctx}: state why THIS dataset is the right way to test "
                        f"this paper in Indian equities")
        if not any(d.minimum_viable for d in self.ideal) and self.ideal:
            errs.append(f"{ctx}: mark at least one field minimum_viable -- without "
                        f"a smallest honest subset, every request reads as essential "
                        f"and none can be traded off")
        for i, r in enumerate(self.rejected_alternatives):
            if not isinstance(r, dict) or not r.get("option") or not r.get("why_not"):
                errs.append(f"{ctx}.rejected_alternatives[{i}]: needs 'option' "
                            f"and 'why_not'")
        return errs


@dataclass
class SecuritySelection:
    """How securities are chosen, and -- if named -- which ones and on whose word.

    A rule is always required. An explicit list is optional and dangerous: a
    model naming Indian stocks from memory produces a plausible, unverifiable
    list, which is worse than no list because it looks checked. So a list must
    say what confirmed it, and `UNVERIFIED` is a legal value that the
    completeness check and Gate A both surface rather than a field to leave blank.
    """
    rule: str = ""                     # how the cross-section is selected
    explicit_securities: List[str] = field(default_factory=list)
    verified_against: str = ""         # see VERIFY_SOURCES
    as_of: str = ""                    # membership is a date-dependent fact
    why_these: str = ""

    def validate(self, ctx: str = "selection") -> List[str]:
        errs = []
        if not self.rule.strip():
            errs.append(f"{ctx}: rule is required -- a named list without a rule "
                        f"cannot be re-derived on any other date")
        if self.explicit_securities:
            if not self.verified_against:
                errs.append(f"{ctx}: a named list needs verified_against (use "
                            f"'UNVERIFIED' if nothing confirmed it -- a list that "
                            f"looks checked and is not is the worse failure)")
            elif self.verified_against not in VERIFY_SOURCES:
                errs.append(f"{ctx}: verified_against '{self.verified_against}' "
                            f"not in {sorted(VERIFY_SOURCES)}")
            if not self.as_of:
                errs.append(f"{ctx}: a named list needs as_of -- index membership "
                            f"is true on a date, not in general")
        return errs


@dataclass
class BacktestPlan:
    """Exactly what will be run, so Gate A is verification and not design.

    If a human has to work out the sample window, the warmup, the benchmarks or
    what would count as failure, then Stage 02 did not finish and Gate A is
    doing the work. This section is where that stops.
    """
    sample_start: str = ""
    sample_end: str = ""
    why_this_window: str = ""
    warmup_days: Optional[int] = None
    why_warmup: str = ""
    rebalance_rule: str = ""
    weights_rule: str = ""
    explicit_weights: Dict[str, float] = field(default_factory=dict)
    benchmarks: List[Dict[str, str]] = field(default_factory=list)
    must_beat: List[str] = field(default_factory=list)
    success_looks_like: str = ""
    failure_looks_like: str = ""
    known_failure_modes: List[str] = field(default_factory=list)

    def validate(self, ctx: str = "backtest_plan") -> List[str]:
        errs = []
        for f_ in ("sample_start", "sample_end", "rebalance_rule", "weights_rule"):
            if not str(getattr(self, f_) or "").strip():
                errs.append(f"{ctx}: {f_} is required")
        if not self.why_this_window.strip():
            errs.append(f"{ctx}: say why this window -- an unargued sample is the "
                        f"easiest place to pick a period that flatters the result")
        if not self.benchmarks:
            errs.append(f"{ctx}: name at least one benchmark, with why_this. The "
                        f"promotion question is never 'is the Sharpe good'")
        for i, b in enumerate(self.benchmarks):
            if not isinstance(b, dict) or not b.get("name") or not b.get("why_this"):
                errs.append(f"{ctx}.benchmarks[{i}]: needs 'name' and 'why_this'")
        if not self.success_looks_like.strip() or not self.failure_looks_like.strip():
            errs.append(f"{ctx}: state success_looks_like AND failure_looks_like. "
                        f"A plan that cannot fail is not a test")
        if self.explicit_weights:
            tot = sum(self.explicit_weights.values())
            if tot > 1.0 + 1e-6:
                errs.append(f"{ctx}: explicit_weights sum to {tot:.4f}; this fund "
                            f"is unlevered")
            if any(w < 0 for w in self.explicit_weights.values()):
                errs.append(f"{ctx}: a negative explicit weight -- this fund "
                            f"cannot short")
        return errs


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
    # Which data_plan field(s) this request would supply, named exactly.
    # Declared rather than guessed: the link is what lets the code say a
    # minimum-viable field is NOT in hand, and a fuzzy match would quietly
    # mark the gap closed -- the failure this exists to catch.
    satisfies: List[str] = field(default_factory=list)
    # One line a human can rule on without reading the paragraph below it.
    # Written by the model, because compressing an argument is a judgement --
    # mechanical extraction can only TRUNCATE, and a headline cut mid-sentence
    # is what made the old gate unreadable. The full text always stays below it;
    # this is a pointer, never a replacement.
    headline: str = ""

    def validate(self, ctx: str) -> List[str]:
        errs = _check_headline(self.headline, ctx)
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
    # One line a human can rule on without reading the paragraph below it.
    # Written by the model, because compressing an argument is a judgement --
    # mechanical extraction can only TRUNCATE, and a headline cut mid-sentence
    # is what made the old gate unreadable. The full text always stays below it;
    # this is a pointer, never a replacement.
    headline: str = ""

    def validate(self, ctx: str) -> List[str]:
        errs = _check_headline(self.headline, ctx)
        if not self.question.strip():
            errs.append(f"{ctx}: question is required")
        if self.ask_of not in ASK_OF:
            errs.append(f"{ctx}: ask_of '{self.ask_of}' not in {sorted(ASK_OF)}")
        if not self.blocks_run and not self.what_i_assumed.strip():
            errs.append(f"{ctx}: state `what_i_assumed` or set blocks_run -- a "
                        f"question with neither stalls the run for no reason")
        return errs


INDIA_CATEGORIES = ("data", "timing", "execution", "cost", "validity")


@dataclass
class IndiaNote:
    """An India requirement a MODEL derived by reading the paper.

    ros/india_requirements.py derives requirements mechanically from properties
    of the reconstructed strategy -- does it rank securities, does it read a
    fundamental, how fast does it trade. That is the floor, and it is a floor
    precisely because no model can argue it away: `lag_days >= 1` and the 30bp
    cost fire whatever anyone thinks.

    But the matching is keyword-based, so it is deaf to anything a paper does
    that nobody wrote a pattern for. This is where that gap gets closed: a model
    reads the paper and states the India-specific requirement the rules missed.

    Two constraints make that safe rather than merely broader.

    First, a note can only ADD. It cannot remove or downgrade a rules
    requirement, and it is never blocking -- a model may not invent a hard stop
    any more than it may remove one. Gate A shows it, a human may act on it, and
    promoting one into a rule is a code change somebody reviews.

    Second, `addresses` names which strategy input this covers, so the code can
    check that the model actually looked at the inputs the patterns missed
    instead of writing notes about whatever was easiest. That check is the point
    of the field: an unaddressed input used to be a line of prose asking a human
    to be careful, which is not a mechanism.
    """
    category: str = "data"
    item: str = ""
    why: str = ""
    triggered_by: str = ""              # what in the paper raised it
    addresses: List[str] = field(default_factory=list)
    evidence_page: Optional[int] = None

    def validate(self, ctx: str) -> List[str]:
        errs = []
        if self.category not in INDIA_CATEGORIES:
            errs.append(f"{ctx}: category '{self.category}' not in "
                        f"{list(INDIA_CATEGORIES)}")
        if not self.item.strip():
            errs.append(f"{ctx}: item is required")
        if not self.why.strip():
            errs.append(f"{ctx}: say WHY India demands this of this strategy. A "
                        f"requirement with no reason cannot be argued down, only "
                        f"obeyed or ignored")
        if not self.triggered_by.strip():
            errs.append(f"{ctx}: say what in the paper raised it -- a requirement "
                        f"nobody can trace to the strategy is one nobody can "
                        f"retract when the strategy changes")
        return errs


CONVERTIBILITY_VERDICTS = ("convertible", "convertible_with_data",
                           "mechanism_only", "not_convertible")


@dataclass
class Convertibility:
    """Can this paper become a strategy THIS fund could actually run?

    Everything else on the card answers "what does the paper say" and "how would
    we test it". This answers the question the fund is actually paying to have
    answered, and it is the one a completeness score cannot reach: a card can be
    99% complete and describe a beautiful test of something the fund could never
    hold.

    It is deliberately a MODEL'S OPINION, clearly labelled, and it decides
    nothing. A `not_convertible` verdict does not block Gate A -- it is a
    finding, and a well-argued one is worth more than a run. What it does is
    stop a human having to reconstruct the judgement from eleven other sections.

    `what_must_be_true` is the load-bearing field. A mechanism transfers as a
    CHAIN -- the effect exists, it exists in this segment, it survives costs, it
    survives long-only, it has capacity -- and the chain is only as good as its
    weakest link. Writing the links out separately is what makes the weak one
    visible instead of averaged away in a paragraph.
    """
    verdict: str = ""
    what_must_be_true: List[str] = field(default_factory=list)
    weakest_link: str = ""              # which link you least believe, and why
    decisive_evidence: str = ""         # what would settle it either way
    if_it_fails: str = ""               # what a null result would teach us
    capacity_note: str = ""             # what size this could carry, if it works
    confidence: str = "medium"          # low | medium | high
    evidence_page: Optional[int] = None
    # One line a human can rule on without reading the paragraph below it.
    # Written by the model, because compressing an argument is a judgement --
    # mechanical extraction can only TRUNCATE, and a headline cut mid-sentence
    # is what made the old gate unreadable. The full text always stays below it;
    # this is a pointer, never a replacement.
    headline: str = ""

    def validate(self, ctx: str = "convertibility") -> List[str]:
        errs = _check_headline(self.headline, ctx)
        if self.verdict not in CONVERTIBILITY_VERDICTS:
            errs.append(f"{ctx}: verdict '{self.verdict}' not in "
                        f"{list(CONVERTIBILITY_VERDICTS)}")
        if self.confidence not in CONFIDENCE:
            errs.append(f"{ctx}: confidence '{self.confidence}' not in "
                        f"{sorted(CONFIDENCE)}")
        # A chain with one link is a claim, not a chain. Two is the minimum at
        # which "weakest" means anything.
        if len(self.what_must_be_true) < 2:
            errs.append(f"{ctx}: list at least 2 things that must be true -- a "
                        f"mechanism transfers as a chain, and one link is an "
                        f"assertion rather than an argument")
        if not self.weakest_link.strip():
            errs.append(f"{ctx}: name the weakest link -- a chain whose author "
                        f"believes every link equally has not been examined")
        return errs


# A fallback is a sentence a human can decide against. These are the strings
# that occupy the field without doing its job; the schema cannot tell them from
# a real answer because it only checks that something was typed.
_NON_ANSWERS = {"", "-", "--", "n/a", "na", "none", "nothing", "tbd", "todo",
                "unknown", "not applicable", "no fallback", "unclear", "?"}
_FALLBACK_MIN_CHARS = 25


def reconcile_data_plan(card, feasibility=None) -> Dict[str, Any]:
    """Is the card RUNNING on the dataset it designed, or on what was lying around?

    These are different questions and the report used to answer only the first.
    Feasibility resolves the card's `data_requirements` -- a list of registry
    NAMES -- and says GO when every name resolves, proxies and degraded series
    included. `data_plan.ideal` is the dataset the paper deserves, and its
    `minimum_viable` fields are the ones without which the answer is not
    interpretable. Nothing compared the two.

    So a card could mark "total-return daily series" and "a real Indian short
    rate" as minimum-viable, hold neither -- price-return indices and a declared
    constant stand in -- and Gate A would print "Nothing. Every series this card
    needs is already held." Every series it NAMED, yes. Not the dataset it
    designed, and that is the sentence a reviewer was reading.

    A request naming a field in `satisfies` is the model saying, in its own
    words, that the field is not in hand. That is the only non-guessing link
    available, and it is declared rather than matched.
    """
    dp = getattr(card, "data_plan", None)
    if dp is None or not dp.ideal:
        return {"checked": False, "need": [], "not_in_hand": [], "proxied": [],
                "degraded": []}

    claimed = {c.strip().lower()
               for r in (getattr(card, "data_requests", []) or [])
               for c in r.satisfies if c.strip()}
    need, not_in_hand = [], []
    for d in dp.ideal:
        if not d.minimum_viable:
            continue
        need.append(d.field)
        if d.field.strip().lower() in claimed:
            not_in_hand.append(d.field)

    proxied, degraded = [], []
    for r in getattr(feasibility, "resolutions", []) or []:
        if r.status == "PROXY":
            proxied.append(f"{r.requirement} -> {r.resolved_to or '?'}")
        elif r.status == "DEGRADED":
            degraded.append(r.requirement)
    return {"checked": True, "need": need, "not_in_hand": not_in_hand,
            "proxied": proxied, "degraded": degraded}


def audit_data_requests(card) -> Dict[str, Any]:
    """Are the card's asks real, and are the fallbacks usable?

    Lives here so Gate A and the completeness report cannot drift: one concern,
    one implementation, two surfaces.

    This exists because the obvious check -- "every request has a `without_it`"
    -- CANNOT FAIL. DataRequest.validate() already rejects an empty one, and
    load_card() raises, so any card that reaches Gate A has passed it by
    construction. A criterion that always passes is worse than no criterion: it
    occupies a row that looks verified. And with an empty request list `all()`
    returns True, so a card that asked for nothing scored the same as one that
    asked well.

    So this checks the two things the schema genuinely cannot:

      1. that the card asked for something, or explicitly argued that nothing
         more would help (`no_further_data_needed`) -- silence is not a claim;
      2. that each fallback is a decision a human could take, rather than a
         placeholder typed to satisfy the field.
    """
    reqs = list(getattr(card, "data_requests", []) or [])
    claim = " ".join(str(getattr(card, "no_further_data_needed", "") or "").split())

    weak = []
    for r in reqs:
        txt = " ".join(str(r.without_it or "").split())
        if txt.strip().lower().rstrip(".").strip() in _NON_ANSWERS:
            weak.append(f"{r.item}: fallback is a placeholder ({txt or 'empty'!r})")
        elif len(txt) < _FALLBACK_MIN_CHARS:
            weak.append(f"{r.item}: fallback is too short to act on ({txt!r})")

    if reqs:
        stance, detail = "asked", ("; ".join(weak) or
                                   f"{len(reqs)} request(s), each with a fallback "
                                   f"a human can decide against")
    elif len(claim) >= 40:
        stance, detail = "argued_none", claim
    else:
        stance = "silent"
        detail = ("nothing is asked for and nothing says why not. 'No further "
                  "data would improve this test' is a strong claim about a "
                  "paper somebody just read; unargued, it is indistinguishable "
                  "from nobody having looked. State it in "
                  "`no_further_data_needed` or ask for something.")

    # `ok` judges the fallbacks that exist; silence is a separate finding, so a
    # card with no requests has no bad fallbacks and must not be marked as
    # having one. Keeping the two apart is what lets each name its own failure.
    return {"ok": not weak, "n": len(reqs), "weak": weak, "stance": stance,
            "complete": (not weak) and stance != "silent", "detail": detail}


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


# The groups a reviewer thinks in. Named after the STRATEGY, never after the
# pipeline: a reader wants "universe", "signal", "the bar" -- not "stage 02c"
# or "what the deterministic reader saw". Order is the order they are read in.
GROUPS = ("PAPER", "UNIVERSE", "SIGNAL", "PORTFOLIO", "COSTS", "DATA",
          "SECURITIES", "THE RUN", "THE BAR", "RISKS", "VERDICT", "DECIDE",
          "ASKS")

# What a flag means to the person reading the line.
BLOCK, DECIDE, GUESS, NOTE = "BLOCK", "DECIDE", "GUESS", ""


@dataclass
class Fact:
    """ONE displayable line from the card. The whole card is a list of these.

    This exists because Gate A kept needing renderer surgery. Every card field
    was bespoke prose behind a bespoke name -- `rationale`, `why_not_alternatives`,
    `optimality_argument`, `weakest_link`, `without_it` -- so any renderer had
    to know all of them, and what came out read like a tour of the pipeline
    rather than a strategy card: which stage produced what, which part the code
    scored, where the audit trail lived.

    Shape the data once and the display is a projection. A renderer walks facts,
    groups them and prints; it never learns a field name, and adding a card
    section means yielding more facts rather than editing a report.

    `value` is the line. `detail` is the argument behind it, shown or not
    depending on how much room the surface has. `flag` is the only editorial
    judgement in the structure: BLOCK stops the run, DECIDE is a human's call,
    GUESS is something asserted without a source.
    """
    group: str
    label: str
    value: str
    detail: str = ""
    owner: str = ""                  # "" | pm | researcher | data_owner
    flag: str = ""                   # "" | BLOCK | DECIDE | GUESS
    page: Optional[int] = None
    ref: str = ""                    # the card field, for anyone tracing it back

    @property
    def text(self) -> str:
        return " ".join(str(self.value or "").split())


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
    # Stage 02's job: design the dataset, name the securities, state the plan.
    # If a human has to supply any of these at Gate A, Stage 02 did not finish.
    data_plan: Optional[DataPlan] = None
    selection: Optional[SecuritySelection] = None
    backtest_plan: Optional[BacktestPlan] = None
    data_requirements: List[DataRequirement] = field(default_factory=list)
    ambiguities: List[Ambiguity] = field(default_factory=list)
    replication_targets: List[ReplicationTarget] = field(default_factory=list)
    benchmark_templates: List[Dict[str, Any]] = field(default_factory=list)
    # What the model wants FROM a human, and what it cannot settle alone. These
    # are the card's two outward-facing sections: everything else describes the
    # paper, these describe what is still needed to do it justice.
    data_requests: List[DataRequest] = field(default_factory=list)
    open_questions: List[OpenQuestion] = field(default_factory=list)
    # Asking for nothing is a legitimate position and a strong claim. Stating it
    # here turns it into one somebody can disagree with; leaving it blank makes
    # "no further data would help" indistinguishable from nobody having looked.
    no_further_data_needed: str = ""
    # India requirements a MODEL read out of the paper, on top of the ones the
    # rules derive mechanically. Additive and never blocking -- see IndiaNote.
    india_notes: List[IndiaNote] = field(default_factory=list)
    # The model's opinion on the question the fund is actually paying for.
    # Decides nothing; a `not_convertible` verdict is a finding, not a block.
    convertibility: Optional[Convertibility] = None
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
        if self.convertibility is not None:
            errs += self.convertibility.validate()
        for i, n in enumerate(self.india_notes):
            errs += n.validate(f"india_notes[{i}]")
        for i, q in enumerate(self.open_questions):
            errs += q.validate(f"open_questions[{i}]")
        for section in (self.data_plan, self.selection, self.backtest_plan):
            if section is not None:
                errs += section.validate()
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

    def facts(self) -> List[Fact]:
        """The whole card as a flat list of displayable lines.

        Every surface that shows the card reads this, so they cannot drift and
        none of them needs to know a field name.
        """
        F: List[Fact] = []

        def add(group, label, value, detail="", owner="", flag="", page=None,
                ref=""):
            v = " ".join(str(value or "").split())
            if v:
                F.append(Fact(group=group, label=label, value=v,
                              detail=" ".join(str(detail or "").split()),
                              owner=owner, flag=flag, page=page, ref=ref))

        pa = self.paper
        add("PAPER", "title", pa.title, ref="paper.title")
        add("PAPER", "source", pa.source_file or "NOT RECORDED",
            flag="" if pa.source_file else GUESS, ref="paper.source_file")
        add("PAPER", "sha256", pa.source_sha256 or "NOT RECORDED",
            flag="" if pa.source_sha256 else GUESS, ref="paper.source_sha256")
        add("PAPER", "asking", self.intent.mode, self.intent.rationale,
            ref="intent.mode")
        add("PAPER", "mechanism", self.intent.transferred_mechanism,
            ref="intent.transferred_mechanism")

        ut = self.universe_translation
        if ut is not None:
            add("UNIVERSE", "tested on",
                f"{ut.target_universe or '(none)'}"
                + (f"   [{ut.grade}]" if ut.grade else ""),
                ut.rationale, owner="researcher", flag=DECIDE,
                page=ut.evidence_page, ref="universe_translation.target_universe")
            add("UNIVERSE", "paper used", ut.source_universe,
                ut.source_selection_rule, ref="universe_translation.source_universe")
            add("UNIVERSE", "not instead", ", ".join(ut.alternatives_considered),
                ut.why_not_alternatives, ref="universe_translation.alternatives_considered")
            mn = ut.mechanism_needs
            if mn is not None:
                add("UNIVERSE", "needs",
                    f">= {mn.min_names} names, {mn.cap_segment} cap, "
                    f"{mn.min_history_years:g}y history, "
                    + ("ranks a cross-section" if mn.needs_cross_section
                       else "times one stream"),
                    ref="universe_translation.mechanism_needs")
            for r in ut.transfer_risks:
                add("RISKS", "transfer", r, ref="universe_translation.transfer_risks")
        for b in self.intent.broken_assumptions:
            add("RISKS", "broken", b, ref="intent.broken_assumptions")

        st = self.strategy
        if st is not None:
            add("SIGNAL", "name", st.signal_name or self.signal.name,
                ref="strategy.signal_name")
            add("SIGNAL", "kind",
                "cross-sectional (ranks securities)" if st.cross_sectional
                else "time-series (times one stream)", ref="strategy.cross_sectional")
            add("SIGNAL", "definition", st.signal_definition,
                ref="strategy.signal_definition")
            add("SIGNAL", "selection", st.formation_rule, ref="strategy.formation_rule")
            add("SIGNAL", "weights", st.weighting_rule, ref="strategy.weighting_rule")
            add("SIGNAL", "reads", ", ".join(st.inputs_required),
                ref="strategy.inputs_required")
            for k in st.constraints:
                add("SIGNAL", "constraint", k, ref="strategy.constraints")
            add("SIGNAL", "engine", st.engine_template,
                st.template_gap, flag=(BLOCK if st.engine_template ==
                                       "NEEDS_NEW_TEMPLATE" else ""),
                ref="strategy.engine_template")
            add("SIGNAL", "read at", f"{st.confidence} confidence"
                + (f", pages {st.evidence_pages}" if st.evidence_pages
                   else ", NO PAGES CITED"),
                flag="" if st.confidence == "high" else GUESS,
                ref="strategy.confidence")
            if st.is_long_short:
                add("PORTFOLIO", "long-only",
                    "the paper is LONG-SHORT; this fund cannot short",
                    st.long_only_adaptation, owner="pm", flag=DECIDE,
                    ref="strategy.long_only_adaptation")
        add("SIGNAL", "lookback",
            f"{self.signal.lookback_days}d" if self.signal.lookback_days else "",
            ref="signal.lookback_days")
        add("SIGNAL", "lag", f"{self.signal.lag_days}d",
            "NSE closes publish after the close",
            flag=BLOCK if self.signal.lag_days < 1 else "", ref="signal.lag_days")

        po = self.portfolio
        add("PORTFOLIO", "rebalance", po.rebalance, ref="portfolio.rebalance")
        add("PORTFOLIO", "sample", f"{po.start or '?'} -> {po.end or '?'}",
            ref="portfolio.start")
        if po.mandate_allow_cash is False and po.allow_cash:
            add("PORTFOLIO", "cash",
                "the paper holds cash; the mandate is fully invested",
                "two different strategies, not two views of one",
                owner="pm", flag=DECIDE, ref="portfolio.mandate_allow_cash")
        add("COSTS", "charged",
            f"{self.costs.spread_bps:.0f}bp round trip ({self.costs.cost_model})",
            "a US paper's 5bp is the commonest way an Indian backtest lies",
            owner="researcher", flag=DECIDE if self.costs.spread_bps < 20 else "",
            ref="costs.spread_bps")

        dp = self.data_plan
        if dp is not None:
            add("DATA", "granularity", dp.granularity_verdict,
                ref="data_plan.granularity_verdict")
            for d in dp.ideal:
                add("DATA", "MUST HAVE" if d.minimum_viable else "would help",
                    f"{d.field} -- {d.granularity}, from {d.history_from or '?'}",
                    " ".join(x for x in (d.why, d.why_granularity, d.why_history,
                                         d.adjustments) if x),
                    ref="data_plan.ideal")
            for r in dp.rejected_alternatives:
                add("DATA", "not", r.get("option", "?"), r.get("why_not", ""),
                    ref="data_plan.rejected_alternatives")
            add("DATA", "why this", dp.optimality_argument,
                ref="data_plan.optimality_argument")
            add("DATA", "would change it", dp.what_would_change_the_answer,
                ref="data_plan.what_would_change_the_answer")

        sel = self.selection
        if sel is not None:
            add("SECURITIES", "rule", sel.rule, sel.why_these,
                ref="selection.rule")
            if sel.explicit_securities:
                unverified = sel.verified_against in ("", "UNVERIFIED")
                add("SECURITIES", "named",
                    f"{len(sel.explicit_securities)}: "
                    + ", ".join(sel.explicit_securities),
                    f"verified against {sel.verified_against or 'NOTHING'}"
                    f" as of {sel.as_of or 'no date'}",
                    owner="data_owner" if unverified else "",
                    flag=GUESS if unverified else "", ref="selection.explicit_securities")

        bp = self.backtest_plan
        if bp is not None:
            add("THE RUN", "window", f"{bp.sample_start} -> {bp.sample_end}",
                bp.why_this_window, ref="backtest_plan.sample_start")
            add("THE RUN", "warmup",
                f"{bp.warmup_days}d" if bp.warmup_days is not None
                else "NOT STATED", bp.why_warmup, ref="backtest_plan.warmup_days")
            add("THE RUN", "rebalance", bp.rebalance_rule,
                ref="backtest_plan.rebalance_rule")
            add("THE RUN", "weights", bp.weights_rule, ref="backtest_plan.weights_rule")
            if bp.explicit_weights:
                add("THE RUN", "strategic mix",
                    ", ".join(f"{k} {v:.0%}" for k, v in bp.explicit_weights.items()),
                    ref="backtest_plan.explicit_weights")
            for b in bp.benchmarks:
                add("THE BAR", "measured vs", b.get("name", "?"),
                    b.get("why_this", ""), ref="backtest_plan.benchmarks")
            for m in bp.must_beat:
                add("THE BAR", "must beat", m, owner="pm", flag=DECIDE,
                    ref="backtest_plan.must_beat")
            add("THE BAR", "success", bp.success_looks_like,
                ref="backtest_plan.success_looks_like")
            add("THE BAR", "failure", bp.failure_looks_like,
                ref="backtest_plan.failure_looks_like")
            for f_ in bp.known_failure_modes:
                add("RISKS", "known break", f_, ref="backtest_plan.known_failure_modes")

        cv = self.convertibility
        if cv is not None:
            add("VERDICT", "can we hold it",
                f"{cv.verdict}   ({cv.confidence} confidence)",
                cv.headline, owner="researcher", flag=DECIDE,
                page=cv.evidence_page, ref="convertibility.verdict")
            for i, link in enumerate(cv.what_must_be_true, 1):
                add("VERDICT", f"must be true {i}", link,
                    ref="convertibility.what_must_be_true")
            add("VERDICT", "weakest link", cv.weakest_link,
                ref="convertibility.weakest_link")
            add("VERDICT", "would settle it", cv.decisive_evidence,
                ref="convertibility.decisive_evidence")
            add("VERDICT", "if it fails", cv.if_it_fails,
                ref="convertibility.if_it_fails")
            add("VERDICT", "capacity", cv.capacity_note,
                ref="convertibility.capacity_note")

        for a in self.ambiguities:
            add("DECIDE", a.field, a.headline or a.resolution, a.resolution,
                owner="researcher",
                flag=DECIDE if a.material else "",
                page=a.evidence_page, ref="ambiguities")
        for q in self.open_questions:
            add("DECIDE", "open question", q.headline or q.question,
                (q.question + "  ASSUMED: " + q.what_i_assumed)
                if q.what_i_assumed else q.question,
                owner=q.ask_of, flag=BLOCK if q.blocks_run else DECIDE,
                page=q.evidence_page, ref="open_questions")

        for r in self.data_requests:
            add("ASKS", r.priority, r.headline or r.item,
                f"{r.item}. IF DECLINED: {r.without_it}",
                owner="data_owner",
                flag=BLOCK if r.priority == "blocking" else "",
                page=r.evidence_page, ref="data_requests")
        add("ASKS", "nothing else", self.no_further_data_needed,
            ref="no_further_data_needed")
        for n in self.india_notes:
            add("RISKS", f"india/{n.category}", n.item, n.why,
                page=n.evidence_page, ref="india_notes")
        return F

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

    def convertibility_block(self) -> str:
        """The model's answer to the question the fund is actually paying for.

        Clearly labelled as an opinion, because it is the only section on the
        card that is one. Everything else states what the paper says or what
        will be run; this says whether any of it can become something this fund
        could hold, and a human is free to disagree in one line.
        """
        W = 96
        cv = self.convertibility
        if cv is None:
            return ("  NO CONVERTIBILITY VERDICT ON THIS CARD.\n"
                    "  The card says what the paper is and how it would be "
                    "tested, but never says\n  whether it could become "
                    "something this fund can hold. That judgement then falls\n"
                    "  to whoever reads it at Gate A, which is Stage 02's work "
                    "landing on the gate.")
        label = {
            "convertible": "CONVERTIBLE -- the fund could run this with data it holds",
            "convertible_with_data": "CONVERTIBLE ONLY WITH DATA WE DO NOT HOLD",
            "mechanism_only": "TESTABLE AS A QUESTION, NOT HOLDABLE BY THIS FUND",
            "not_convertible": "NOT CONVERTIBLE -- the mechanism does not survive "
                               "the translation",
        }.get(cv.verdict, cv.verdict)
        L = ["  " + "=" * W, "  CAN THIS BECOME A STRATEGY WE COULD RUN?  "
                             "(the model's opinion, not a decision)",
             "  " + "=" * W, "",
             f"  {label}",
             f"  confidence: {cv.confidence}"
             + (f"   pages: {cv.evidence_page}" if cv.evidence_page else ""),
             "",
             "  EVERY ONE OF THESE MUST BE TRUE. The chain is as good as its "
             "weakest link:"]
        for i, link in enumerate(cv.what_must_be_true, 1):
            for j, line in enumerate(_wrap(" ".join(str(link).split()), W - 10)):
                L.append(f"    {str(i) + '.' if j == 0 else '':<4}{line}")
        for label_, val in (("WEAKEST LINK", cv.weakest_link),
                            ("WHAT WOULD SETTLE IT", cv.decisive_evidence),
                            ("WHAT A NULL RESULT WOULD TEACH US", cv.if_it_fails),
                            ("CAPACITY, IF IT WORKS", cv.capacity_note)):
            if str(val or "").strip():
                L += ["", f"  {label_}"]
                for line in _wrap(" ".join(str(val).split()), W - 6):
                    L.append(f"      {line}")
        L += ["", "  " + "=" * W]
        return "\n".join(L)

    def asks(self, requests_only: bool = False) -> str:
        """What the model wants from a human, formatted for Gate A.

        Gate A is a conversation, not a form. This is the model's half of it:
        here is what I would ask you for, what it buys, and what I will do if
        you say no; and here is what the paper does not settle, with the
        position I have taken meanwhile.
        """
        W = 96
        if not self.data_requests and (requests_only or not self.open_questions):
            claim = " ".join(self.no_further_data_needed.split())
            if not claim:
                return ("  NOTHING IS BEING ASKED FOR, AND NOTHING SAYS WHY NOT.\n"
                        "  No data request, no open question, no argument that "
                        "none is needed. That is\n  a strong claim about a paper "
                        "somebody has just read, and unargued it cannot be\n"
                        "  told apart from nobody having looked. Gate A surfaces "
                        "it as a gap.")
            L = ["  " + "=" * W, "  NOTHING IS BEING ASKED FOR -- AND HERE IS WHY",
                 "  " + "=" * W, ""]
            for line in _wrap(claim, W - 6):
                L.append(f"      {line}")
            L += ["", "  This is the model claiming the test is already as good as "
                      "it can be.",
                  "  Disagreeing with it is cheaper now than after the run.",
                  "  " + "=" * W]
            return "\n".join(L)

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

        if self.open_questions and not requests_only:
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

    # plan() is kept as the composition of the three parts below. Gate A
    # renders the parts separately so each lands where a reviewer decides on
    # it -- the dataset next to what the fund actually holds, the run next to
    # the bar it has to clear -- instead of arriving as one block that repeats
    # what the brief already said.
    def plan_data(self, W: int = 96, banner: bool = True) -> str:
        """The dataset this paper deserves, in full."""
        dp = self.data_plan
        L = (["  " + "=" * W, "  THE DATASET THIS PAPER DESERVES", "  " + "=" * W]
             if banner else [])
        if dp is None:
            L += ["", "  NO DATA PLAN ON THIS CARD.",
                  "  Without one the card can only shop from what the fund holds,",
                  "  and a paper quietly becomes whatever the existing data can answer."]
            return "\n".join(L)
        if dp.granularity_verdict:
            L.append("")
            for i, line in enumerate(_wrap(" ".join(dp.granularity_verdict.split()), W - 16)):
                L.append(f"  {'granularity:' if i == 0 else '':<14} {line}")
        for d in dp.ideal:
            tag = "MINIMUM VIABLE" if d.minimum_viable else "improves the claim"
            L += ["", f"  [{tag}] {d.field}",
                  f"      {d.granularity}, from {d.history_from or '?'}"]
            for label, val in (("why", d.why), ("granularity", d.why_granularity),
                               ("history", d.why_history),
                               ("adjustments", d.adjustments)):
                if str(val or "").strip():
                    for i, line in enumerate(_wrap(" ".join(str(val).split()), W - 20)):
                        L.append(f"      {label if i == 0 else '':<14} {line}")
        if dp.rejected_alternatives:
            L += ["", "  " + "-" * W, "  CONSIDERED AND REJECTED", "  " + "-" * W]
            for r in dp.rejected_alternatives:
                L.append("")
                L.append(f"  x {r.get('option', '?')}")
                for i, line in enumerate(_wrap(
                        " ".join(str(r.get("why_not", "")).split()), W - 12)):
                    L.append(f"      {line}")
        for label, val in (("WHY THIS IS THE RIGHT DATASET", dp.optimality_argument),
                           ("WHAT WOULD CHANGE THE ANSWER",
                            dp.what_would_change_the_answer)):
            if str(val or "").strip():
                L += ["", f"  {label}"]
                for line in _wrap(" ".join(str(val).split()), W - 6):
                    L.append(f"      {line}")
        return "\n".join(L)

    def plan_selection(self, W: int = 96, banner: bool = True) -> str:
        """Which securities, and on whose word."""
        sel = self.selection
        L = (["  " + "=" * W, "  WHICH SECURITIES", "  " + "=" * W]
             if banner else [])
        if sel is None:
            L.append("  NO SELECTION RULE. A selection nobody can re-derive on "
                     "another date is not a strategy.")
            return "\n".join(L)
        for i, line in enumerate(_wrap(" ".join(sel.rule.split()), W - 12)):
            L.append(f"  {'rule:' if i == 0 else '':<8} {line}")
        if sel.explicit_securities:
            flag = ("" if sel.verified_against not in ("", "UNVERIFIED")
                    else "   <-- NOT VERIFIED; treat as a guess")
            L.append(f"  named:   {len(sel.explicit_securities)} securities, "
                     f"verified against {sel.verified_against or 'NOTHING'}"
                     f" as of {sel.as_of or 'no date'}{flag}")
            for nm in sel.explicit_securities:
                L.append(f"             {nm}")
        if sel.why_these:
            for i, line in enumerate(_wrap(" ".join(sel.why_these.split()), W - 12)):
                L.append(f"  {'why:' if i == 0 else '':<8} {line}")
        return "\n".join(L)

    def plan_run(self, W: int = 96, banner: bool = True) -> str:
        """Exactly what will be run, and the bar it has to clear."""
        bp = self.backtest_plan
        L = (["  " + "=" * W, "  WHAT WILL BE RUN", "  " + "=" * W]
             if banner else [])
        if bp is None:
            L.append("  NO BACKTEST PLAN. Gate A would be designing the run "
                     "rather than verifying it.")
            return "\n".join(L)
        L.append(f"    sample     : {bp.sample_start} -> {bp.sample_end}"
                 + (f"   warmup {bp.warmup_days}d"
                    if bp.warmup_days is not None else "   warmup NOT STATED"))
        for label, val in (("why window", bp.why_this_window),
                           ("why warmup", bp.why_warmup),
                           ("rebalance", bp.rebalance_rule),
                           ("weights", bp.weights_rule)):
            if str(val or "").strip():
                for i, line in enumerate(_wrap(" ".join(str(val).split()), W - 20)):
                    L.append(f"    {label if i == 0 else '':<12} {line}")
        if bp.explicit_weights:
            tot = sum(bp.explicit_weights.values())
            L.append(f"    strategic  : " + ", ".join(
                f"{k} {v:.0%}" for k, v in bp.explicit_weights.items())
                + f"   (sum {tot:.0%})")
        if bp.benchmarks:
            L.append("")
            L.append("    BENCHMARKS -- what this is measured against, and why")
            for b in bp.benchmarks:
                L.append(f"      {b.get('name', '?')}")
                for line in _wrap(" ".join(str(b.get("why_this", "")).split()), W - 14):
                    L.append(f"          {line}")
        if bp.must_beat:
            L.append("")
            L.append("    MUST BEAT (named before the run, so the bar cannot move after)")
            for m in bp.must_beat:
                L.append(f"      - {m}")
        for label, val in (("SUCCESS", bp.success_looks_like),
                           ("FAILURE", bp.failure_looks_like)):
            if str(val or "").strip():
                L.append("")
                L.append(f"    {label} LOOKS LIKE")
                for line in _wrap(" ".join(str(val).split()), W - 8):
                    L.append(f"      {line}")
        if bp.known_failure_modes:
            L.append("")
            L.append("    KNOWN WAYS THIS BREAKS IN INDIA")
            for f_ in bp.known_failure_modes:
                for i, line in enumerate(_wrap(" ".join(str(f_).split()), W - 10)):
                    L.append(f"      {'-' if i == 0 else ' '} {line}")
        return "\n".join(L)

    def plan(self) -> str:
        """The dataset, the securities and the run -- what Gate A verifies.

        Stage 02's deliverable. If a human reading this has to work out the
        window, the warmup, the benchmarks or what would count as failure, then
        Stage 02 did not finish and Gate A is doing the design.
        """
        W = 96
        return "\n".join([self.plan_data(W), "", self.plan_selection(W), "",
                           self.plan_run(W), "", "  " + "=" * W])

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
    for key, sub in _LISTED.get(cls, {}).items():
        if isinstance(kw.get(key), list):
            kw[key] = [_build(sub, v, f"{name}.{key}[{i}]") if isinstance(v, dict)
                       else v for i, v in enumerate(kw[key])]
    return cls(**kw)


_NESTED[UniverseTranslation] = {"mechanism_needs": MechanismNeeds}
_LISTED = {DataPlan: {"ideal": DataSpec}}


def load_card(path: str) -> StrategyCard:
    """Load and validate a Strategy Card from YAML. Unknown keys are an error."""
    with open(path, encoding="utf-8") as fh:
        blob = yaml.safe_load(fh) or {}

    known = {"paper", "intent", "universe", "signal", "portfolio", "costs",
             "data_requirements", "ambiguities", "replication_targets",
             "benchmark_templates", "n_configs_tried", "notes", "card_version",
             "universe_translation", "strategy", "data_requests",
             "open_questions", "data_plan", "selection", "backtest_plan",
             "no_further_data_needed", "convertibility", "india_notes"}
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
        no_further_data_needed=blob.get("no_further_data_needed", ""),
        india_notes=[_build(IndiaNote, n, f"india_notes[{i}]")
                     for i, n in enumerate(blob.get("india_notes") or [])],
        convertibility=(_build(Convertibility, blob["convertibility"],
                               "convertibility")
                        if blob.get("convertibility") else None),
        data_plan=(_build(DataPlan, blob["data_plan"], "data_plan")
                   if blob.get("data_plan") else None),
        selection=(_build(SecuritySelection, blob["selection"], "selection")
                   if blob.get("selection") else None),
        backtest_plan=(_build(BacktestPlan, blob["backtest_plan"], "backtest_plan")
                       if blob.get("backtest_plan") else None),
    )
    return card.require_valid()
