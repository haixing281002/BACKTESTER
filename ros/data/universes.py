"""Universe translation: what the paper studied -> what we can test in India.

THE PROBLEM THIS SOLVES

A paper says "we sort S&P 500 constituents on book-to-market". Our fund is
long-only NIFTY 500. Somebody has to decide that NIFTY 500 is the analogue of
the S&P 500, that the sort survives the move, and what breaks on the way.

That decision must not be re-derived from scratch every time a paper arrives.
If it is, the same paper read twice produces two different universes, and the
strategy library stops being comparable across entries -- which is the whole
point of keeping one.

So the mapping lives here, in code, as a recorded institutional decision with
its caveats attached. The model's job at Stage 01 is to identify WHICH source
universe a paper used and whether the mechanism survives the move; it is not to
invent the correspondence. That split is the repo's rule applied to universes:
the model interprets, the code computes, and a human signs at Gate A.

WHAT IS DELIBERATELY NOT HERE

Nothing in this file asserts that a translation is a good idea. `grade` records
how close the correspondence is and `transfer_risks` records what is known to
break; neither approves anything. A LOOSE mapping is not rejected here -- it is
surfaced at Gate A with its risks, and a named human rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# How closely the Indian universe corresponds to the one the paper studied.
EXACT = "exact"     # same construction, same market
CLOSE = "close"     # same role in its market; differences are documented
LOOSE = "loose"     # defensible analogue, materially different composition
NONE = "none"       # no honest correspondence exists
GRADES = (EXACT, CLOSE, LOOSE, NONE)

# How we would actually represent the target universe with data.
DIRECT = "direct"                 # we hold exactly these instruments
SLEEVE_PROXY = "sleeve_proxy"     # stand in with factor sleeves we hold
NEEDS_DATA = "needs_data"         # real, testable, but we must acquire data
INFEASIBLE = "infeasible"         # cannot be tested by this fund at all
RESOLUTIONS = (DIRECT, SLEEVE_PROXY, NEEDS_DATA, INFEASIBLE)


# ---------------------------------------------------------------------------
# Caveats that attach to ANY developed-market -> India equity translation.
# These are the reasons a US result does not simply carry over, and they are
# stated once here rather than rediscovered per paper.
# ---------------------------------------------------------------------------
INDIA_EQUITY_CAVEATS = [
    "FREE FLOAT: median promoter holding in NIFTY 500 names is roughly half the "
    "share count. The investable universe is materially smaller than the name "
    "count suggests, and capacity binds earlier than a US study would imply.",

    "DEPTH: traded value in the lower half of NIFTY 500 is a small fraction of "
    "the equivalent Russell names. A signal that rebalances into small names at "
    "US turnover rates is not executable here at the printed price.",

    "CIRCUIT LIMITS: individual scrips halt at price bands. Momentum and "
    "reversal signals cannot transact on exactly the moves that generate them, "
    "and a backtest using the close will silently assume they could.",

    "CORPORATE ACTIONS: bonus, split and demerger density is high. An "
    "unadjusted or partially adjusted price series breaks any cross-sectional "
    "signal, usually by manufacturing a spurious extreme.",

    "SAMPLE LENGTH: reliable NSE history begins around 2003-2005. US studies "
    "routinely use 1926 onward. A twenty-year Indian sample contains far fewer "
    "independent regimes, so the same t-statistic carries less evidence.",

    "COSTS: STT, stamp duty, exchange charges and impact. 30bp round trip is a "
    "floor for index sleeves and optimistic for single-stock rotation at "
    "mid-cap depth. A paper's 5bp assumption never transfers.",

    "MEMBERSHIP HISTORY: point-in-time index constituents are not freely "
    "available. Reconstructing who was in NIFTY 500 on a past date is the "
    "single hardest data problem in this translation, and getting it wrong "
    "imports survivorship bias that flatters every result.",
]

LONG_ONLY_CAVEATS = [
    "LONG-ONLY: this fund cannot short. Most academic factor premia are "
    "reported as long-short spreads, and the long leg alone has historically "
    "captured only part of the spread while carrying far more market beta. A "
    "long-only version of a long-short paper is a DIFFERENT strategy and must "
    "never be scored against the paper's numbers.",

    "SHORT-LEG ALPHA: where a paper reports leg-level returns, the short leg "
    "often carries the larger and more reliable half. Discarding it is not a "
    "haircut on the result; it can remove most of it.",
]


@dataclass
class UniverseDef:
    """An investable universe, ours or a paper's."""
    name: str
    market: str                       # IN / US / JP / global ...
    description: str
    approx_breadth: Optional[int] = None
    asset_class: str = "equity"
    caveats: List[str] = field(default_factory=list)


@dataclass
class Translation:
    """A recorded correspondence from a source universe to an Indian one."""
    source: str
    target: str
    grade: str
    rationale: str
    transfer_risks: List[str] = field(default_factory=list)
    required_instruments: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        errs = []
        if self.grade not in GRADES:
            errs.append(f"grade '{self.grade}' not in {GRADES}")
        if self.grade != NONE and not self.target:
            errs.append("a translation that is not 'none' must name a target")
        return errs


# ---------------------------------------------------------------------------
# The fund's own universes. What we could test, given the right data -- NOT a
# claim that we hold the data. ros/data/firm_registry.py owns that question.
# ---------------------------------------------------------------------------
INDIAN_UNIVERSES: Dict[str, UniverseDef] = {
    "NIFTY 500 constituents": UniverseDef(
        name="NIFTY 500 constituents", market="IN", approx_breadth=500,
        description="The fund's mandate universe: roughly 93% of NSE free-float "
                    "market cap, spanning large, mid and small caps.",
        caveats=INDIA_EQUITY_CAVEATS),
    "NIFTY 100 constituents": UniverseDef(
        name="NIFTY 100 constituents", market="IN", approx_breadth=100,
        description="Large-cap subset. Closest in concentration and liquidity to "
                    "the S&P 500's role in the US market.",
        caveats=INDIA_EQUITY_CAVEATS),
    "NIFTY 50 constituents": UniverseDef(
        name="NIFTY 50 constituents", market="IN", approx_breadth=50,
        description="Headline large-cap index. The analogue of a Nikkei 225 or "
                    "FTSE 100 in role, not in breadth.",
        caveats=INDIA_EQUITY_CAVEATS),
    "NIFTY Midcap 150 constituents": UniverseDef(
        name="NIFTY Midcap 150 constituents", market="IN", approx_breadth=150,
        description="Mid-cap segment; inside the fund's NIFTY 500 scope.",
        caveats=INDIA_EQUITY_CAVEATS),
    "NIFTY Smallcap 250 constituents": UniverseDef(
        name="NIFTY Smallcap 250 constituents", market="IN", approx_breadth=250,
        description="Small-cap segment. Inside NIFTY 500 by construction but the "
                    "depth caveats bind hardest here.",
        caveats=INDIA_EQUITY_CAVEATS),
    "NSE factor sleeves": UniverseDef(
        name="NSE factor sleeves", market="IN", approx_breadth=8,
        description="The eight NSE single- and multi-factor indices the fund "
                    "holds daily closes for. Not a cross-section of stocks: a "
                    "small set of pre-built return streams.",
        caveats=INDIA_EQUITY_CAVEATS),
}

FUND_MANDATE_UNIVERSE = "NIFTY 500 constituents"


# ---------------------------------------------------------------------------
# Known source universes and their Indian correspondence.
#
# `required_instruments` says what a faithful test would need, in the fund's own
# vocabulary, so Stage 03 can resolve it and Gate A can show a human exactly
# what to supply.
# ---------------------------------------------------------------------------
def _t(source, target, grade, rationale, risks=(), instruments=()) -> Translation:
    return Translation(source=source, target=target, grade=grade,
                       rationale=rationale,
                       transfer_risks=list(risks),
                       required_instruments=list(instruments))


CROSS_SECTION_INSTRUMENTS = [
    "nifty500_constituent_prices",      # daily adjusted close, per stock
    "nifty500_membership_history",      # who was in the index, as-was
    "nifty500_free_float_marketcap",    # for weighting and for size sorts
]

_TRANSLATIONS: List[Translation] = [
    _t("S&P 500", "NIFTY 100 constituents", CLOSE,
       "Both are the headline large-cap cross-section of their market. NIFTY 100 "
       "matches the S&P 500's concentration and liquidity profile more closely "
       "than NIFTY 500 does, which reaches considerably deeper into mid and "
       "small caps.",
       risks=["The S&P 500 is ~80% of US market cap across 500 names; NIFTY 100 "
              "is a similar share of NSE cap across 100. Breadth differs by 5x, "
              "so cross-sectional dispersion and the number of independent bets "
              "are not comparable.",
              "A paper relying on 500 names for statistical power has 100 here. "
              "Sorting into deciles leaves 10 stocks a bucket."],
       instruments=["nifty100_constituent_prices", "nifty100_membership_history",
                    "nifty100_free_float_marketcap"]),

    _t("S&P 500", FUND_MANDATE_UNIVERSE, LOOSE,
       "Chosen when a paper's mechanism needs breadth more than it needs "
       "large-cap purity -- decile sorts, dispersion trades, anything that "
       "starves at 100 names. Matches the fund's mandate exactly, at the cost "
       "of reaching further down the cap scale than the paper did.",
       risks=["NIFTY 500 includes small caps the S&P 500 has no equivalent of. "
              "Results will be flattered by illiquidity premia the paper never "
              "collected, and capacity will bind far earlier."],
       instruments=CROSS_SECTION_INSTRUMENTS),

    _t("Russell 1000", FUND_MANDATE_UNIVERSE, CLOSE,
       "Both are the broad investable domestic cross-section including mid caps. "
       "This is the cleanest correspondence available for the fund's mandate.",
       risks=["Russell 1000 has twice the names. Decile breakpoints are built on "
              "half the sample here."],
       instruments=CROSS_SECTION_INSTRUMENTS),

    _t("Russell 2000", "NIFTY Smallcap 250 constituents", LOOSE,
       "Small-cap analogue by role. Inside the fund's scope, but the depth and "
       "circuit-limit caveats bind hardest in this segment.",
       risks=["Russell 2000 small is not Indian small. Free float, promoter "
              "concentration and traded depth differ by an order of magnitude.",
              "Most published small-cap anomalies do not survive realistic "
              "Indian impact costs."],
       instruments=["nifty_smallcap250_constituent_prices",
                    "nifty_smallcap250_membership_history"]),

    _t("CRSP all US common stocks", FUND_MANDATE_UNIVERSE, LOOSE,
       "The broadest cross-section the fund may hold. CRSP reaches into micro "
       "caps that have no investable Indian counterpart for a fund of any size.",
       risks=["CRSP includes thousands of micro caps. Anomalies measured there "
              "are frequently micro-cap artefacts that vanish in the top 500."],
       instruments=CROSS_SECTION_INSTRUMENTS),

    _t("FTSE 100", "NIFTY 50 constituents", CLOSE,
       "Headline large-cap index of a single market; same role, similar breadth.",
       risks=["50 names supports very few independent cross-sectional bets."],
       instruments=["nifty50_constituent_prices", "nifty50_membership_history"]),

    _t("Nikkei 225", "NIFTY 50 constituents", LOOSE,
       "Headline domestic large-cap index. The Nikkei is price-weighted, which "
       "NIFTY is not -- any weighting-sensitive result does not carry.",
       risks=["Price weighting vs free-float weighting changes the index's own "
              "return, so a benchmark-relative claim is not comparable."],
       instruments=["nifty50_constituent_prices", "nifty50_membership_history"]),

    _t("Fama-French factor portfolios", "NSE factor sleeves", LOOSE,
       "The fund holds eight NSE factor indices. They are the nearest thing we "
       "own to academic factor portfolios -- but they are long-only, index-"
       "constructed and backfilled, not long-short research portfolios.",
       risks=["FF factors are LONG-SHORT and dollar-neutral. NSE sleeves are "
              "long-only index baskets. A loading on one is not a loading on "
              "the other.",
              "NSE sleeve methodology was fixed years after the backfilled "
              "history it reports."],
       instruments=["NIFTY500 MOMENTUM 50", "NIFTY500 QUALITY 50",
                    "NIFTY500 VALUE 50", "NIFTY500 LOW VOLATILITY 50",
                    "NIFTY ALPHA 50"]),

    _t("Global futures (multi-asset)", "NSE factor sleeves", LOOSE,
       "Trend and carry studies run on dozens of futures markets across equities, "
       "bonds, currencies and commodities. A long-only Indian equity fund holds "
       "none of them. Where the mechanism is asset-agnostic -- a per-stream "
       "signal sized by trailing risk -- the fund's factor sleeves are such a "
       "set of streams and the mechanism can be tested on them.",
       risks=["The original result rests on 50+ weakly correlated markets. Five "
              "single-country equity sleeves correlate 0.74-0.94, so the "
              "diversification that carried the paper is simply absent.",
              "Futures are deep and cheap and permit shorting. Indian sleeve "
              "replication is cash equity, long-only, at far higher cost.",
              "A trend signal that may go short earns on both sides. Truncating "
              "at zero removes roughly half the signal's opportunity set."],
       instruments=["NIFTY500 MOMENTUM 50", "NIFTY500 QUALITY 50",
                    "NIFTY500 VALUE 50", "NIFTY500 LOW VOLATILITY 50",
                    "NIFTY ALPHA 50"]),

    _t("MSCI World", "", NONE,
       "A single-country long-only Indian fund has no analogue for a global "
       "developed-market universe. A paper whose mechanism depends on "
       "cross-country dispersion does not transfer; one whose mechanism is "
       "security-level may still, on an Indian cross-section.",
       risks=["Test the MECHANISM on an Indian universe, never the result."]),

    _t("MSCI Emerging Markets", "", NONE,
       "India is one constituent of this universe, not an analogue for it. "
       "Cross-country allocation mechanisms do not transfer to a single market.",
       risks=["Test the MECHANISM on an Indian universe, never the result."]),

    _t("US multi-asset (equity / bond / gold)", "NSE factor sleeves", LOOSE,
       "A long-only equity fund holds no bonds and no gold. Where a paper's "
       "mechanism is asset-agnostic -- allocate across a small set of "
       "long-only sleeves under a risk cap -- the fund's factor sleeves are "
       "such a set and the mechanism can be tested on them.",
       risks=["The paper's diversification benefit comes from weak or negative "
              "cross-asset correlation. Equity factor sleeves correlate "
              "0.74-0.94 pairwise, so most of that benefit cannot transfer.",
              "Any cash-holding mechanism conflicts with a fully-invested "
              "mandate and must be run twice: faithful and mandate-compliant."],
       instruments=["NIFTY500 MOMENTUM 50", "NIFTY500 QUALITY 50",
                    "NIFTY500 VALUE 50", "NIFTY500 LOW VOLATILITY 50",
                    "NIFTY ALPHA 50"]),
]

# Spellings that mean the same source universe. Kept explicit rather than
# fuzzy-matched: a near-miss that silently picks the wrong universe is worse
# than an honest "unknown" that goes to a human.
_ALIASES: Dict[str, str] = {
    "sp500": "S&P 500", "s&p500": "S&P 500", "s&p 500": "S&P 500",
    "spx": "S&P 500", "spy": "S&P 500", "standard & poor's 500": "S&P 500",
    "us large cap": "S&P 500", "us large-cap": "S&P 500",
    "russell1000": "Russell 1000", "russell 1000": "Russell 1000",
    "r1000": "Russell 1000",
    "russell2000": "Russell 2000", "russell 2000": "Russell 2000",
    "r2000": "Russell 2000", "us small cap": "Russell 2000",
    "crsp": "CRSP all US common stocks",
    "crsp universe": "CRSP all US common stocks",
    "nyse/amex/nasdaq": "CRSP all US common stocks",
    "all us stocks": "CRSP all US common stocks",
    "ftse100": "FTSE 100", "ftse 100": "FTSE 100",
    "nikkei": "Nikkei 225", "nikkei225": "Nikkei 225", "nikkei 225": "Nikkei 225",
    "fama-french": "Fama-French factor portfolios",
    "fama french": "Fama-French factor portfolios",
    "ff factors": "Fama-French factor portfolios",
    "french data library": "Fama-French factor portfolios",
    "msci world": "MSCI World", "developed markets": "MSCI World",
    "msci eafe": "MSCI World",
    "msci em": "MSCI Emerging Markets",
    "emerging markets": "MSCI Emerging Markets",
    "spy/agg/gld": "US multi-asset (equity / bond / gold)",
    "stock/bond/gold": "US multi-asset (equity / bond / gold)",
    "stock, bond and gold": "US multi-asset (equity / bond / gold)",
    "multi-asset": "US multi-asset (equity / bond / gold)",
    "futures": "Global futures (multi-asset)",
    "global futures": "Global futures (multi-asset)",
    "managed futures": "Global futures (multi-asset)",
    "58 futures markets": "Global futures (multi-asset)",
    "futures markets": "Global futures (multi-asset)",
    "cta universe": "Global futures (multi-asset)",
}


def canonical_source(name: str) -> Optional[str]:
    """Resolve a paper's wording to a known source universe, or None.

    Matching is exact on a normalised string. Deliberately not fuzzy: guessing
    wrong here silently backtests the wrong universe, which is a worse outcome
    than routing an unrecognised name to a human at Gate A.
    """
    if not name:
        return None
    key = " ".join(name.strip().lower().split())
    if key in _ALIASES:
        return _ALIASES[key]
    for t in _TRANSLATIONS:
        if t.source.lower() == key:
            return t.source
    return None


def translations_for(source: str) -> List[Translation]:
    """Every recorded Indian correspondence for a source universe, best first."""
    canon = canonical_source(source) or source
    hits = [t for t in _TRANSLATIONS if t.source == canon]
    return sorted(hits, key=lambda t: GRADES.index(t.grade))


def known_sources() -> List[str]:
    return sorted({t.source for t in _TRANSLATIONS})


def target_universe(name: str) -> Optional[UniverseDef]:
    return INDIAN_UNIVERSES.get(name)


def caveats_for(target: str, long_only: bool = True) -> List[str]:
    """Everything a human should see before approving a translation."""
    out: List[str] = []
    u = INDIAN_UNIVERSES.get(target)
    if u:
        out.extend(u.caveats)
    if long_only:
        out.extend(LONG_ONLY_CAVEATS)
    return out


# ---------------------------------------------------------------------------
# Checking a proposed translation
#
# Stage 01 PROPOSES a correspondence; this computes whether it holds up. The
# card may claim a resolution -- the code decides one, from what the fund
# actually holds, and any disagreement between the two goes to Gate A rather
# than being reconciled quietly in favour of either.
# ---------------------------------------------------------------------------
@dataclass
class TranslationCheck:
    source: str
    recognised_source: bool
    target: str
    registry_match: Optional[Translation]
    divergences: List[str] = field(default_factory=list)
    held: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    computed_resolution: str = INFEASIBLE
    claimed_resolution: str = ""
    caveats: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def needs_human(self) -> bool:
        """Anything a researcher must look at before this is trusted."""
        return bool(self.divergences or self.missing or not self.recognised_source)

    def render(self) -> str:
        L = [f"  source universe : {self.source}"
             + ("" if self.recognised_source else "   [NOT IN THE TRANSLATION TABLE]"),
             f"  target universe : {self.target or '(none proposed)'}"]
        if self.registry_match:
            L.append(f"  recorded grade  : {self.registry_match.grade}")
            L.append(f"  rationale       : {' '.join(self.registry_match.rationale.split())}")
        L.append(f"  resolution      : {self.computed_resolution}"
                 + (f"   (card claimed: {self.claimed_resolution})"
                    if self.claimed_resolution
                    and self.claimed_resolution != self.computed_resolution else ""))
        if self.held:
            L.append(f"  instruments held    ({len(self.held)}): " + ", ".join(self.held))
        if self.missing:
            L.append(f"  instruments MISSING ({len(self.missing)}):")
            for m in self.missing:
                L.append(f"      - {m}")
        for d in self.divergences:
            L.append(f"  ! DIVERGENCE: {d}")
        for n in self.notes:
            L.append(f"  note: {n}")
        if self.caveats:
            L.append("  what a human is signing for:")
            for c in self.caveats:
                L.append(f"      - {' '.join(c.split())}")
        return "\n".join(L)


def check_translation(translation, registry, long_only: bool = True) -> TranslationCheck:
    """Validate a card's proposed universe translation against what we hold.

    `translation` is a cards.schema.UniverseTranslation (duck-typed here to
    avoid importing the card module into the data layer). `registry` is a
    DataRegistry -- what the fund actually has.
    """
    src = getattr(translation, "source_universe", "") or ""
    tgt = getattr(translation, "target_universe", "") or ""
    canon = canonical_source(src)
    options = translations_for(canon) if canon else []
    match = next((t for t in options if t.target == tgt), None)

    chk = TranslationCheck(
        source=src, recognised_source=canon is not None, target=tgt,
        registry_match=match,
        claimed_resolution=getattr(translation, "resolution", "") or "")

    if canon is None:
        chk.notes.append(
            "This source universe is not in ros/data/universes.py. The table is "
            "matched exactly rather than fuzzily, because guessing wrong here "
            "silently backtests the wrong universe. Either the paper studies "
            "something genuinely new -- in which case a human adds it to the "
            "table -- or Stage 01 described it in unfamiliar words.")
    elif match is None:
        recorded = ", ".join(f"{t.target} ({t.grade})" for t in options) or "none"
        chk.divergences.append(
            f"the card proposes '{tgt}' for '{canon}', which is not a recorded "
            f"correspondence. Recorded: {recorded}")

    # Which instruments would a faithful test need? Prefer the registry's list
    # over the card's -- the card is the model's proposal, the table is the
    # institution's decision.
    needed = list(match.required_instruments) if match else list(
        getattr(translation, "required_instruments", []) or [])
    for inst in needed:
        (chk.held if registry.get(inst) is not None else chk.missing).append(inst)

    if not tgt:
        chk.computed_resolution = INFEASIBLE
        chk.notes.append("No Indian analogue was proposed. If the paper's "
                         "MECHANISM is security-level it may still be testable "
                         "on an Indian cross-section; if it depends on "
                         "cross-country dispersion, it does not transfer.")
    elif not needed:
        chk.computed_resolution = NEEDS_DATA
        chk.notes.append("No instruments named, so nothing could be resolved.")
    elif not chk.missing:
        chk.computed_resolution = (SLEEVE_PROXY if tgt == "NSE factor sleeves"
                                   else DIRECT)
    else:
        chk.computed_resolution = NEEDS_DATA

    if chk.claimed_resolution and chk.claimed_resolution != chk.computed_resolution:
        chk.divergences.append(
            f"the card claims resolution '{chk.claimed_resolution}' but the fund's "
            f"holdings support '{chk.computed_resolution}'. The registry decides.")

    if match:
        chk.caveats.extend(match.transfer_risks)
    chk.caveats.extend(caveats_for(tgt, long_only=long_only))
    return chk
