"""What it takes to backtest THIS strategy in India, honestly.

Gate A used to say "you are missing nifty500_constituent_prices". True, and
nearly useless: it names a file, not a specification. Two vendors will sell you
something with that name and only one of them will let you run the strategy.

This module derives the real requirement from what Stage 01 reconstructed. The
model says what the strategy IS; these rules say what India demands of it. That
split is the repo's rule applied to data procurement: the judgement about the
paper is the model's, the consequences are mechanical.

Nothing here is about a specific paper. Every rule keys on a property of the
strategy -- does it rank securities, does it read a fundamental, how often does
it trade, which cap segment -- so a paper nobody has written yet gets the same
treatment.

WHAT IS DELIBERATELY NOT HERE

Current statutory rates. STT, stamp duty and exchange charges change, and a
number baked into a repo is a number that goes quietly stale and gets trusted
anyway. The cost rules name the COMPONENTS and require the desk to supply its
own current figures. The one number that is stated is the 30bp sleeve floor,
because CLAUDE.md already fixes it as a non-negotiable for this fund.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

DATA, TIMING, EXECUTION, COST, VALIDITY = (
    "data", "timing", "execution", "cost", "validity")
CATEGORY_TITLES = {
    DATA: "DATA YOU WOULD HAVE TO SUPPLY",
    TIMING: "TIMING -- what the lag and the calendar must respect",
    EXECUTION: "EXECUTION -- India-specific hazards for THIS strategy",
    COST: "COSTS -- what must be charged, and who supplies the number",
    VALIDITY: "WHAT WOULD INVALIDATE THE TEST",
}

# Keyword families. Matching is deliberately crude and says so: a miss here
# means a requirement is not raised, so the renderer prints what it matched on
# and invites a human to add anything it did not see.
# Word-bounded and specific on purpose. The first draft matched bare "book" and
# bare "cap", so "scales the book to a volatility target" demanded publication
# dates and "capped at unlevered" demanded free-float market cap. A spurious
# MUST is worse than a missed one: it sends someone to a data vendor for a field
# the strategy never reads, and the next reader trusts the block less.
_FUNDAMENTAL = re.compile(
    r"book\s*(value|equity|to\s*market)|\bb\s*/\s*m\b|\bp\s*/\s*[eb]\b|"
    r"\bearnings\b|\beps\b|\bsales\b|\brevenue\b|\baccruals?\b|"
    r"\bro[ace]\b|\bmargins?\b|\bdebt\b|shareholders?\s*equity|"
    r"cash\s*flow|\bebitda?\b|dividend\s*yield|\bpayout\b|\bvaluation\b|"
    r"\bfundamentals?\b|balance\s*sheet|\bprofits?\b|\bassets?\b", re.I)
_VOLUME = re.compile(
    r"\bvolumes?\b|\bturnover\b|\bliquidity\b|\badv\b|traded\s*value|"
    r"\bamihud\b|\billiquidity\b", re.I)
_PRICE = re.compile(
    r"\bprices?\b|\bclose\b|\breturns?\b|\bmomentum\b|\breversal\b|"
    r"\bvolatilit(y|ies)\b|\bbeta\b", re.I)
_MOMENTUM = re.compile(
    r"\bmomentum\b|\breversals?\b|\btrend\b|\bbreakout\b|52.?week", re.I)
_CAPWEIGHT = re.compile(
    r"market\s*cap|\bmcap\b|cap.?weight|value.?weight|free.?float|"
    r"\bsize\s*(sort|factor|decile)", re.I)
_RISKWEIGHT = re.compile(
    r"inverse.?vol|risk\s*parity|\bcovariance\b|risk\s*contribution", re.I)
# The rules had NO cash rule at all, while CLAUDE.md fixes it as a standing
# fact of this fund: there is no Indian risk-free series, so an un-invested
# residual earns a declared constant. A card whose whole mechanism de-risks
# into cash raised nothing about the series that mechanism runs on.
_CASH = re.compile(
    r"\bcash\b|risk.?free|\brf\b|\bt.?bills?\b|\brepo\b|\bmibor\b|"
    r"overnight\s*rate|\bdeposits?\b|\byields?\b", re.I)

FAST_REBALANCE = {"daily", "weekly"}
THIN_SEGMENTS = {"small", "mid_small", "micro"}


RULES, MODEL = "rules", "model"


@dataclass
class Requirement:
    category: str
    item: str
    why: str
    blocking: bool = True
    triggered_by: str = ""
    # WHERE this came from, and it is never decoration. A rules requirement is
    # mechanical: it fires from a property of the strategy and no model can talk
    # it away. A model requirement is a reading of the paper -- broader, and
    # exactly as fallible as the reading. Merging them without saying which is
    # which would let a model's opinion inherit the authority of the floor.
    source: str = RULES
    evidence_page: Optional[int] = None

    def render(self, width: int = 88) -> str:
        mark = "MUST" if self.blocking else "note"
        tag = "" if self.source == RULES else "  <- from the paper, by a model"
        out = [f"    [{mark}] {self.item}{tag}"]
        for line in _wrap(self.why, width - 11):
            out.append(f"           {line}")
        if self.triggered_by:
            out.append(f"           (because: {self.triggered_by})")
        if self.evidence_page:
            out.append(f"           (paper p.{self.evidence_page})")
        return "\n".join(out)


def _wrap(text: str, width: int) -> List[str]:
    words, lines, cur = " ".join(text.split()).split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


@dataclass
class IndiaRequirements:
    requirements: List[Requirement] = field(default_factory=list)
    matched_on: List[str] = field(default_factory=list)
    unmatched_inputs: List[str] = field(default_factory=list)
    # Of the inputs the patterns did not recognise, the ones a model note picked
    # up -- and the ones still nobody has looked at. The second list is the
    # point: an unmatched input used to be a line of prose asking a human to be
    # careful, which is not a mechanism.
    addressed_inputs: List[str] = field(default_factory=list)
    unaddressed_inputs: List[str] = field(default_factory=list)

    def of(self, category: str) -> List[Requirement]:
        return [r for r in self.requirements if r.category == category]

    @property
    def blocking(self) -> List[Requirement]:
        return [r for r in self.requirements if r.blocking]

    @property
    def from_model(self) -> List[Requirement]:
        return [r for r in self.requirements if r.source == MODEL]

    def render(self) -> str:
        L = ["  WHAT IT TAKES TO BACKTEST THIS STRATEGY IN INDIA", ""]
        L.append("  Derived from the strategy as reconstructed at Stage 01, not from")
        L.append("  the paper's own assumptions. A US paper's data and cost model do")
        L.append("  not transfer; these are the Indian equivalents.")
        for cat in (DATA, TIMING, EXECUTION, COST, VALIDITY):
            items = self.of(cat)
            if not items:
                continue
            L.append("")
            L.append(f"  {CATEGORY_TITLES[cat]}")
            for r in items:
                L.append(r.render())
        L.append("")
        L.append(f"  {len(self.blocking)} of {len(self.requirements)} are blocking.")
        if self.matched_on:
            for line in _wrap(
                    f"Raised by: {', '.join(self.matched_on)}. If any of those is not "
                    f"actually true of this strategy, the requirement it raised is "
                    f"spurious -- say so rather than going shopping for it.", 84):
                L.append(f"  {line}")
        if self.from_model:
            L.append("")
            for line in _wrap(
                    f"{len(self.from_model)} of these were read out of the paper by "
                    f"a model rather than derived from the strategy's properties. "
                    f"They are marked, they never block, and they are exactly as "
                    f"reliable as the reading that produced them.", 84):
                L.append(f"  {line}")
        if self.unmatched_inputs:
            L.append("")
            L.append("  INPUTS THE PATTERNS COULD NOT READ:")
            for i in self.addressed_inputs:
                L.append(f"      [covered by a model note] {i}")
            for i in self.unaddressed_inputs:
                L.append(f"      [NOBODY HAS LOOKED]       {i}")
            if self.unaddressed_inputs:
                for line in _wrap(
                        "Keyword matching is shallow, so an input it cannot read "
                        "raises no requirement and says nothing -- which is how a "
                        "requirement goes missing. Add an `india_notes` entry "
                        "addressing each one, or say in the entry why none is "
                        "needed. Gate A tracks these until they are answered.", 84):
                    L.append(f"      {line}")
        return "\n".join(L)


def derive(card, translation_check: Optional[Any] = None) -> IndiaRequirements:
    """Everything this specific strategy needs, in an Indian context."""
    req = IndiaRequirements()
    def add(category, item, why, blocking=True, triggered_by=""):
        req.requirements.append(Requirement(
            category=category, item=item, why=why,
            blocking=blocking, triggered_by=triggered_by))

    st = getattr(card, "strategy", None)
    ut = getattr(card, "universe_translation", None)
    universe = (ut.target_universe if ut else "") or "(no universe chosen)"
    segment = (ut.mechanism_needs.cap_segment
               if ut and ut.mechanism_needs else "all")
    rebalance = ((st.rebalance_frequency if st and st.rebalance_frequency
                  else card.portfolio.rebalance) or "").lower()
    inputs = list(st.inputs_required) if st else []
    # Each pattern is matched against the field that can actually establish it.
    # Keying everything on one merged blob made "half-spread turnover cost" --
    # a term in the objective -- look like a volume input, and demanded ADV from
    # a strategy that never reads a volume.
    # Volume is a DATA FIELD: a strategy that reads one lists it in
    # inputs_required, per the schema. Matching the definition too made "minus
    # half-spread turnover cost" -- a term in the objective, not a data read --
    # demand ADV. A fundamental is different: a definition naming
    # book-to-market establishes the read even when inputs are sloppy.
    fields = " ".join(inputs)
    reads = " ".join(inputs + ([st.signal_definition] if st else []))
    does = " ".join([st.weighting_rule, st.formation_rule,
                     st.signal_definition] if st else [])
    blob = f"{reads} {does}"
    cross = bool(st and st.cross_sectional)
    sleeves = universe == "NSE factor sleeves"

    for pat, field, label in ((_FUNDAMENTAL, reads, "a fundamental input"),
                             (_VOLUME, fields, "a volume/liquidity input"),
                             (_MOMENTUM, does, "a momentum/reversal signal"),
                             (_CAPWEIGHT, does, "cap-based weighting or sorting"),
                             (_RISKWEIGHT, does, "risk-based weighting")):
        if pat.search(field):
            req.matched_on.append(label)
    # An input is "read" when SOME pattern recognises it, so a rule that fires
    # on it counts. Leaving _CASH out of this set reported an input as unseen
    # while the cash rule was raising a requirement from it two lines above.
    req.unmatched_inputs = [i for i in inputs
                            if not (_PRICE.search(i) or _FUNDAMENTAL.search(i)
                                    or _VOLUME.search(i) or _CASH.search(i))]

    # ---------------- DATA --------------------------------------------
    if cross:
        add(DATA, f"Daily close for every constituent of {universe}, adjusted for "
                  f"bonuses, splits, rights and demergers",
            "Indian corporate-action density is high. A 1:1 bonus halves the "
            "price, so an unadjusted series does not add noise -- it manufactures "
            "extremes, and extremes are exactly what a sort selects on. You would "
            "systematically buy corporate actions.",
            triggered_by="the strategy ranks securities against each other")
        add(DATA, f"Point-in-time membership of {universe}: who was in it on each "
                  f"past date, with effective dates",
            "The single largest available error. Today's constituents pulled back "
            "through history gives a universe where every name survived and stayed "
            "good enough to remain in the index. A vendor file with exactly the "
            "index's name-count is survivor-only; a real point-in-time file for a "
            "20-year window is far wider and mostly empty.",
            triggered_by="a changing cross-section")
        add(DATA, "Final traded or settlement value for every name that left",
            "The engine liquidates at the last known price. If the series simply "
            "stops at the last print before a suspension, a failure books as a "
            "small loss instead of its real one -- and suspension usually precedes "
            "the bad news.",
            triggered_by="names leave the universe during the test")
    elif sleeves:
        add(DATA, "Daily close for the chosen NSE factor sleeves -- already held",
            "The only universe in the catalogue testable today. Note these are "
            "PRICE-RETURN and BACKFILLED: dividends are absent and the sleeve "
            "rules were fixed years after the history they report.",
            blocking=False,
            triggered_by="the strategy allocates across pre-built streams")

    if _CAPWEIGHT.search(does):
        add(DATA, "FREE-FLOAT market cap, not total market cap",
            "Median promoter holding in large Indian names is a substantial share "
            "of the register, so investable value is well below total cap. Size "
            "sorts on total cap rank the wrong stocks and capacity estimates built "
            "on it are materially too optimistic.",
            triggered_by="weighting or sorting references market cap")

    if _FUNDAMENTAL.search(reads):
        add(DATA, "Every fundamental with TWO dates: the period it covers AND the "
                  "date it became public",
            "Indian results are filed weeks after period end. Aligning a figure to "
            "its fiscal period and trading the next day uses a number nobody had. "
            "It is the classic look-ahead and it makes value and quality signals "
            "look superb. Without the publication date you cannot set a defensible "
            "lag, so this is not a refinement -- it decides whether the test means "
            "anything.",
            triggered_by="the signal reads a fundamental")
        add(DATA, "A restatement policy: as-first-reported, or as-restated",
            "Restatements leak hindsight backwards. As-first-reported is what a "
            "manager could have acted on; as-restated is what auditors concluded "
            "later. State which you bought, because the two answer different "
            "questions and only one is tradeable.",
            blocking=False, triggered_by="the signal reads a fundamental")

    if _VOLUME.search(fields) or cross:
        add(DATA, "Daily traded value (ADV) per name",
            "It decides whether the backtest is fiction. turnover_capacity takes "
            "ADV as an argument because the fund holds none. Without it you cannot "
            "say what AUM this strategy supports, and a book that trades a multiple "
            "of daily volume in a single position is not a strategy.",
            blocking=bool(_VOLUME.search(fields)),
            triggered_by="capacity cannot be assessed without it")

    # ---------------- TIMING ------------------------------------------
    add(TIMING, "lag_days >= 1 on any signal built from a close",
        "NSE index closes publish after the close, so a signal computed on date t "
        "cannot be traded at t's close. This is a repo non-negotiable and the "
        "engine shifts by 1 + lag_days regardless.",
        triggered_by="every price-based signal")

    if _FUNDAMENTAL.search(reads):
        add(TIMING, "lag must exceed the filing lag, set from publication dates",
            "A fundamental signal needs a lag derived from when the figure was "
            "actually published, not a round number. Picking one without the "
            "publication-date field is guessing, and guessing short is exactly "
            "the error that flatters the result.",
            triggered_by="the signal reads a fundamental")

    if cross:
        add(TIMING, "Index reconstitution dates for the chosen universe",
            "NSE indices are rebalanced on a published schedule. A cross-sectional "
            "book inherits forced turnover on those dates whether or not its own "
            "signal changed, and that turnover is real and chargeable. A backtest "
            "that ignores it understates cost and overstates capacity.",
            blocking=False, triggered_by="a changing index universe")

    # ---------------- EXECUTION ---------------------------------------
    if _MOMENTUM.search(does):
        add(EXECUTION, "Circuit-limit and trading-halt history",
            "Individual scrips halt at price bands. A momentum or reversal signal "
            "cannot transact on precisely the moves that generate it, and a "
            "backtest using the close silently assumes it could. This is the single "
            "most over-optimistic assumption in Indian momentum research.",
            blocking=False,
            triggered_by="a momentum, reversal or trend signal")

    if segment in THIN_SEGMENTS or (cross and segment == "all"):
        add(EXECUTION, "An impact model calibrated to Indian depth, not a flat spread",
            f"Traded value in the {segment} segment falls away sharply below the "
            "largest names. A flat spread charges the same to trade a mega cap and "
            "a thin mid cap, which is where a sleeve-level cost assumption stops "
            "being conservative and starts being wrong.",
            triggered_by=f"cap segment '{segment}'")

    if rebalance in FAST_REBALANCE:
        add(EXECUTION, f"A {rebalance} rebalance needs execution modelling, not a "
                       f"round-trip assumption",
            "At this frequency cost dominates signal for most Indian equity "
            "strategies. If the edge survives only at daily rebalancing and dies "
            "monthly, the finding is about the cost model, not the signal.",
            triggered_by=f"rebalance = {rebalance}")

    if st is not None and st.is_long_short:
        add(EXECUTION, "Leg-level returns from the paper, if it reports them",
            "The long-only adaptation drops the short leg. To say what that cost, "
            "you need what the legs earned separately -- the short leg frequently "
            "carries the larger and more reliable half. If the paper does not break "
            "them out, record that as an extraction concern: the size of the "
            "adaptation is then unknown rather than small.",
            blocking=False,
            triggered_by="a long-short source in a long-only fund")

    # ---------------- COST --------------------------------------------
    if sleeves:
        add(COST, "30bp round trip, the fund's floor for index-sleeve rotation",
            "Fixed as a non-negotiable for this fund. A US paper's 5bp does not "
            "transfer and copying it is the commonest way an Indian backtest lies.",
            triggered_by="sleeve-level trading")
    else:
        add(COST, "A single-stock cost stack the desk supplies: STT, stamp duty, "
                  "exchange and SEBI charges, brokerage, and IMPACT",
            "Deliberately not a number in this repo. Statutory rates change and a "
            "baked-in figure goes stale while still being trusted. What does not "
            "change is that single-stock rotation costs materially more than the "
            "30bp sleeve floor, and that impact -- the part that scales with your "
            "size and the name's depth -- is usually larger than every statutory "
            "component combined.",
            triggered_by="trading individual securities")
    if _CASH.search(blob) or card.portfolio.allow_cash:
        add(DATA, "An Indian short-rate series -- overnight (MIBOR) or 91-day T-bill",
            "There is no risk-free series in this repo, so any un-invested "
            "residual earns a DECLARED CONSTANT and every cash-holding result is "
            "swept 4-8%. A constant is wrong in level and wrong in SHAPE: it "
            "cannot de-risk you into a rate-cut cycle, which is exactly when a "
            "cash-holding mechanism is supposed to earn its keep. Until a real "
            "series arrives, no cash-timing claim from this run is safe.",
            blocking=False,
            triggered_by="the strategy can hold cash")

    add(COST, "The breakeven cost at which the edge disappears",
        "Report it alongside the headline. For Indian equity the binding "
        "constraint is usually capacity rather than Sharpe, and a strategy whose "
        "breakeven sits near a plausible cost is not an edge, it is a rounding "
        "error with a backtest.",
        blocking=False, triggered_by="every strategy")

    # ---------------- VALIDITY ----------------------------------------
    if cross:
        add(VALIDITY, "A survivor-only price file", 
            "Silently inflates every result. The engine refuses NaN prices without "
            "a declared membership frame precisely so this cannot happen by "
            "accident, but a file that simply omits the dead names looks clean.",
            triggered_by="a cross-sectional strategy")
        add(VALIDITY, "Unadjusted or partially adjusted prices",
            "Manufactures the extremes a sort selects on.",
            triggered_by="a cross-sectional strategy")
    if _FUNDAMENTAL.search(reads):
        add(VALIDITY, "Fundamentals aligned to fiscal period end",
            "Look-ahead. Requires publication dates to avoid, which is why they are "
            "listed as blocking above.",
            triggered_by="the signal reads a fundamental")
    add(VALIDITY, "Backfilled history supporting a LIVE claim",
        "Whatever is supplied, declare pit_status honestly in the manifest. "
        "Backfilled history is fine for asking whether a mechanism exists and is "
        "not fine as the basis for allocating capital. The ladder caps at ROBUST "
        "for exactly this reason.",
        blocking=False, triggered_by="every strategy")

    if translation_check is not None and getattr(translation_check, "missing", None):
        add(DATA, f"Series the fund does not hold: "
                  f"{', '.join(translation_check.missing)}",
            "Named in the fund's own vocabulary so Stage 03 can resolve them once "
            "supplied. The manifest stanza for each is printed below.",
            triggered_by="the chosen universe, checked against the registry")
    # ---------------- what the MODEL read out of the paper --------------
    # Merged last so a rules requirement is never displaced by one, and marked
    # so a reader can always tell a mechanical consequence from a reading.
    for n in getattr(card, "india_notes", []) or []:
        req.requirements.append(Requirement(
            category=n.category, item=n.item, why=n.why,
            blocking=False,                     # a model may add, never block
            triggered_by=n.triggered_by, source=MODEL,
            evidence_page=n.evidence_page))

    # Did the model look at the inputs the patterns could not read?
    #
    # ONLY `addresses` counts. The first version also scanned each note's item
    # and triggered_by for any shared word over four characters, and a note
    # about index METHODOLOGY-REVISION history silently "covered" an input
    # called "analyst REVISION breadth score". Loose matching here fails in the
    # worst direction: it marks a gap closed that nobody looked at, which is the
    # exact failure this field exists to catch.
    #
    # Substring either way within `addresses`, so a note declaring "promoter
    # pledge" covers an input written "the issuer's promoter pledge
    # disclosures" -- but the model has to NAME what it is covering.
    claims = [a.strip().lower()
              for n in (getattr(card, "india_notes", []) or [])
              for a in n.addresses if a.strip()]
    for i in req.unmatched_inputs:
        low = i.lower()
        hit = any(a in low or low in a for a in claims)
        (req.addressed_inputs if hit else req.unaddressed_inputs).append(i)
    return req
