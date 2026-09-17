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


# Cap segments, deepest to shallowest. Used to judge whether a universe matches
# the segment a paper studied: a small-cap anomaly tested on NIFTY 50 is not a
# test of it, and a large-cap result measured on micro caps is not either.
SEGMENTS = ("mega", "large", "large_mid", "mid", "mid_small", "small", "micro", "all")
_SEG_RANK = {"mega": 0, "large": 1, "large_mid": 1.5, "mid": 2,
             "mid_small": 2.5, "small": 3, "micro": 4, "all": 2}


@dataclass
class UniverseDef:
    """An investable universe, ours or a paper's."""
    name: str
    market: str                       # IN / US / JP / global ...
    description: str
    approx_breadth: Optional[int] = None
    asset_class: str = "equity"
    caveats: List[str] = field(default_factory=list)
    cap_segment: str = "all"
    sector: Optional[str] = None      # None = broad market
    in_mandate: bool = True           # may the fund HOLD it, not merely test on it
    history_from: str = "2005-04-01"
    required_instruments: List[str] = field(default_factory=list)


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
def _slug(name: str) -> str:
    return (name.lower().replace(" constituents", "").replace(" ", "_")
            .replace("-", "_"))


def _u(name, breadth, segment, desc, in_mandate=True, sector=None,
       history_from="2005-04-01", instruments=None) -> UniverseDef:
    return UniverseDef(
        name=name, market="IN", description=desc, approx_breadth=breadth,
        cap_segment=segment, sector=sector, in_mandate=in_mandate,
        history_from=history_from,
        required_instruments=list(instruments) if instruments else [
            f"{_slug(name)}_constituent_prices",
            f"{_slug(name)}_membership_history",
            f"{_slug(name)}_free_float_marketcap"],
        caveats=INDIA_EQUITY_CAVEATS)


# The Indian equity universes this fund could test on.
#
# `in_mandate` says whether the fund may HOLD it. Everything here may be TESTED
# on, because establishing that a mechanism is REAL is a different question from
# being allowed to run it. A paper validated on Microcap 250 tells you the effect
# exists AND that this fund cannot harvest it -- both worth recording, and the
# second only discoverable if the first was allowed to run.
#
# This list is meant to grow. Adding a universe is a data-owner decision: one
# entry here and every future paper can be routed to it.
INDIAN_UNIVERSES: Dict[str, UniverseDef] = {u.name: u for u in [
    # ---- broad market, by depth ----
    _u("NIFTY 50 constituents", 50, "mega",
       "Headline large-cap index. Fifty names supports very few independent "
       "cross-sectional bets: a decile is five stocks."),
    _u("NIFTY Next 50 constituents", 50, "large",
       "Ranks 51-100. Often where a large-cap anomaly actually lives, because "
       "NIFTY 50 is too concentrated to disperse."),
    _u("NIFTY 100 constituents", 100, "large",
       "Closest in concentration and liquidity to the S&P 500's role in the US "
       "market. The default for a large-cap paper."),
    _u("NIFTY 200 constituents", 200, "large_mid",
       "Large and upper-mid. Doubles the cross-section of NIFTY 100 while "
       "staying comfortably liquid."),
    _u("NIFTY 500 constituents", 500, "all",
       "The fund's mandate universe: roughly 93% of NSE free-float market cap. "
       "The default when a mechanism needs breadth."),
    _u("NIFTY Total Market constituents", 750, "all",
       "Ranks 1-750. The broadest investable Indian cross-section and the "
       "closest analogue to a CRSP-style 'all stocks' universe.",
       in_mandate=False),
    # ---- cap segments ----
    _u("NIFTY Midcap 150 constituents", 150, "mid",
       "Ranks 101-250. Inside the mandate, and where a great many Indian "
       "anomalies concentrate."),
    _u("NIFTY Smallcap 250 constituents", 250, "small",
       "Ranks 251-500. Inside the mandate by construction, but the depth and "
       "circuit-limit caveats bind hardest here."),
    _u("NIFTY Microcap 250 constituents", 250, "micro",
       "Ranks 501-750. Outside the mandate. Useful chiefly to establish whether "
       "an effect is a micro-cap artefact -- which is what a great many "
       "published small-cap anomalies turn out to be.",
       in_mandate=False),
    _u("NIFTY LargeMidcap 250 constituents", 250, "large_mid",
       "Top 100 plus Midcap 150. A liquidity-aware broad universe."),
    _u("NIFTY MidSmallcap 400 constituents", 400, "mid_small",
       "Midcap 150 plus Smallcap 250. Excludes the mega caps that dominate "
       "cap-weighted results."),
    # ---- sector ----
    _u("NIFTY Bank constituents", 12, "large",
       "Banking. Twelve names: far too thin for a cross-sectional sort, usable "
       "only for a sector-level timing mechanism.", sector="financials"),
    _u("NIFTY Financial Services constituents", 20, "large",
       "Banks, NBFCs and insurers. Still thin for a sort.", sector="financials"),
    _u("NIFTY IT constituents", 10, "large",
       "Ten names. Sector timing only.", sector="technology"),
    _u("NIFTY Pharma constituents", 20, "large_mid",
       "Pharmaceuticals and healthcare.", sector="healthcare"),
    _u("NIFTY FMCG constituents", 15, "large",
       "Consumer staples.", sector="consumer_staples"),
    _u("NIFTY Auto constituents", 15, "large_mid",
       "Automobiles and components.", sector="consumer_discretionary"),
    _u("NIFTY Metal constituents", 15, "mid",
       "Metals and mining. Highly cyclical; results are regime-dependent.",
       sector="materials"),
    _u("NIFTY Energy constituents", 10, "large",
       "Oil, gas and power. Dominated by two or three names.", sector="energy"),
    # ---- what we actually hold today ----
    UniverseDef(
        name="NSE factor sleeves", market="IN", approx_breadth=8,
        cap_segment="all", sector=None, in_mandate=True,
        history_from="2005-04-01",
        description="The eight NSE single- and multi-factor indices the fund "
                    "holds daily closes for. NOT a cross-section of stocks: a "
                    "small set of pre-built long-only return streams. The only "
                    "universe in this catalogue testable TODAY.",
        required_instruments=["NIFTY500 MOMENTUM 50", "NIFTY500 QUALITY 50",
                              "NIFTY500 VALUE 50", "NIFTY500 LOW VOLATILITY 50",
                              "NIFTY ALPHA 50"],
        caveats=INDIA_EQUITY_CAVEATS),
]}

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
    target_is_known: bool = False
    recorded_pair: bool = False
    requirements: Optional["MechanismRequirements"] = None
    fit: Optional["UniverseFit"] = None
    ranked: List["UniverseFit"] = field(default_factory=list)

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
        elif self.target_is_known:
            L.append("  correspondence  : model-chosen (not the recorded default)")
        if self.fit is not None:
            L.append(f"  fit for this mechanism : score {self.fit.score:.0f}")
            for r in self.fit.reasons_for:
                L.append(f"      for    : {' '.join(r.split())}")
            for r in self.fit.reasons_against:
                L.append(f"      against: {' '.join(r.split())}")
        if self.ranked:
            L.append("  alternatives the code ranked:")
            for f in self.ranked:
                mark = " <- chosen" if f.universe.name == self.target else ""
                flag = "" if f.usable else "  [disqualified]"
                L.append(f"      {f.score:6.1f}  {f.universe.name}{flag}{mark}")
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
            "This source universe is not in the translation table. Matching is "
            "exact rather than fuzzy, because guessing wrong silently backtests "
            "the wrong universe. Either the paper studies something genuinely "
            "new -- in which case a human adds it -- or Stage 01 described it in "
            "unfamiliar words. Either way the universe CHOICE below still "
            "stands on its own: an unrecognised source does not invalidate a "
            "well-argued target.")

    # A target that is not a recorded pair is NOT an error. The recorded pairs
    # are defaults, not a whitelist: the same S&P 500 paper belongs on NIFTY 100
    # for large-cap purity, NIFTY 500 for breadth, or Microcap 250 if the
    # question is whether the effect is an artefact. What must hold is that the
    # target is a real Indian universe and that the choice fits the mechanism.
    if tgt and tgt not in INDIAN_UNIVERSES:
        chk.divergences.append(
            f"'{tgt}' is not an Indian universe this fund knows. Add it to "
            f"INDIAN_UNIVERSES in ros/data/universes.py, or pick from: "
            f"{', '.join(sorted(INDIAN_UNIVERSES)[:6])}, ...")
    elif tgt:
        chk.target_is_known = True
        chk.recorded_pair = match is not None
        if match is None and options:
            chk.notes.append(
                f"'{tgt}' is a model-chosen target rather than the default for "
                f"'{canon}' (default: "
                f"{', '.join(t.target for t in options if t.target)}). That is "
                f"allowed and often right -- but the fit below, not the table, "
                f"is what justifies it.")

    # Score the choice against what the mechanism was said to need.
    needs = getattr(translation, "mechanism_needs", None)
    if needs is not None and tgt in INDIAN_UNIVERSES:
        req = MechanismRequirements(
            needs_cross_section=needs.needs_cross_section,
            min_names=needs.min_names, cap_segment=needs.cap_segment,
            sector=needs.sector, min_history_years=needs.min_history_years,
            must_be_in_mandate=needs.must_be_in_mandate, notes=needs.notes)
        chk.requirements = req
        chk.fit = score_universe(INDIAN_UNIVERSES[tgt], req)
        ranked = propose_universes(req, include_unusable=True)
        # Always show the chosen one, even when it ranks below the cut. A
        # reviewer comparing it to the alternatives needs both on the page.
        top = ranked[:5]
        if all(f.universe.name != tgt for f in top):
            top += [f for f in ranked if f.universe.name == tgt]
        chk.ranked = top
        if chk.fit.disqualifying:
            chk.divergences.append(
                f"the chosen universe is disqualified for this mechanism: "
                f"{'; '.join(chk.fit.disqualifying)}")
        else:
            best = next((f for f in ranked if f.usable), None)
            if best and best.universe.name != tgt and best.score > chk.fit.score + 15:
                chk.notes.append(
                    f"'{best.universe.name}' scores {best.score:.0f} against "
                    f"{chk.fit.score:.0f} for the chosen '{tgt}'. Not wrong, but "
                    f"the card should say why the better-fitting option was "
                    f"passed over.")
        if not INDIAN_UNIVERSES[tgt].in_mandate:
            chk.notes.append(
                "OUT OF MANDATE. A result here establishes whether the effect is "
                "real; it is not something this fund can run, and must never be "
                "reported as though it were.")

    # Which instruments would a faithful test need? Prefer the registry's list
    # over the card's -- the card is the model's proposal, the table is the
    # institution's decision.
    # What a faithful test needs, in order of authority: the recorded pair, then
    # the target universe's own entry, then whatever the card claimed. The card
    # is the model's proposal and ranks last on purpose.
    if match:
        needed = list(match.required_instruments)
    elif tgt in INDIAN_UNIVERSES and INDIAN_UNIVERSES[tgt].required_instruments:
        needed = list(INDIAN_UNIVERSES[tgt].required_instruments)
    else:
        needed = list(getattr(translation, "required_instruments", []) or [])
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


# ---------------------------------------------------------------------------
# CHOOSING a universe, rather than looking one up
#
# A fixed source->target table cannot answer "where is this paper best tested?"
# The same S&P 500 paper belongs on NIFTY 100 if it needs large-cap purity, on
# NIFTY 500 if it needs breadth, and on Microcap 250 if the question is whether
# the effect is a micro-cap artefact. That is a judgement about the MECHANISM,
# not about the index.
#
# So the split is: the model reads the paper and states what the mechanism
# NEEDS; this code scores every Indian universe against those needs and ranks
# them; the model picks from the ranked list and justifies; a human signs at
# Gate A. The choice is open. The justification is checked.
# ---------------------------------------------------------------------------
@dataclass
class MechanismRequirements:
    """What a paper's mechanism needs from a universe, as read at Stage 01.

    Every field is a claim about the PAPER, not about India. Getting these right
    is the whole job: they are what the ranking below consumes.
    """
    needs_cross_section: bool = True
    # How many names the sort needs to mean anything. A top-decile strategy
    # wants ~10 names in the held bucket, so 10 buckets x 10 names = 100. State
    # the number the paper's construction implies, not a round guess.
    min_names: int = 100
    cap_segment: str = "all"            # the segment the PAPER studied
    sector: Optional[str] = None        # set only for a sector-specific paper
    min_history_years: float = 10.0
    must_be_in_mandate: bool = False    # True only if the run must be holdable
    notes: str = ""

    def validate(self) -> List[str]:
        errs = []
        if self.cap_segment not in SEGMENTS:
            errs.append(f"cap_segment '{self.cap_segment}' not in {SEGMENTS}")
        if self.min_names < 1:
            errs.append("min_names must be >= 1")
        return errs


@dataclass
class UniverseFit:
    universe: UniverseDef
    score: float
    reasons_for: List[str] = field(default_factory=list)
    reasons_against: List[str] = field(default_factory=list)
    disqualifying: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.disqualifying

    def render(self) -> str:
        head = (f"  {self.universe.name:<42} score {self.score:5.1f}"
                f"   n~{self.universe.approx_breadth}"
                f"   {'in mandate' if self.universe.in_mandate else 'OUT OF MANDATE'}")
        L = [head]
        for r in self.disqualifying:
            L.append(f"      DISQUALIFIED: {r}")
        for r in self.reasons_against:
            L.append(f"      against: {r}")
        for r in self.reasons_for:
            L.append(f"      for    : {r}")
        return "\n".join(L)


def _years_since(date_str: str) -> float:
    from datetime import date
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
    except (ValueError, AttributeError):
        return 0.0
    return (date.today() - date(y, m, d)).days / 365.25


def score_universe(u: UniverseDef, req: MechanismRequirements) -> UniverseFit:
    """Score one universe against a mechanism's needs. Deterministic and stated.

    The score is only a ranking aid. What matters is `reasons_against` and
    `disqualifying`, which is what a human reads at Gate A.
    """
    fit = UniverseFit(universe=u, score=0.0)
    n = u.approx_breadth or 0

    # --- breadth --------------------------------------------------------
    if req.needs_cross_section:
        if n >= req.min_names * 2:
            fit.score += 25
            fit.reasons_for.append(
                f"{n} names against {req.min_names} needed: room for the sort to "
                f"disperse and for buckets to stay populated as names drop out")
        elif n >= req.min_names:
            fit.score += 15
            fit.reasons_for.append(f"{n} names meets the {req.min_names} needed")
        elif n >= req.min_names * 0.5:
            fit.score -= 10
            fit.reasons_against.append(
                f"only {n} names against {req.min_names} needed. Buckets will be "
                f"thin and a single stock can move the result")
        else:
            fit.disqualifying.append(
                f"{n} names cannot support a sort needing {req.min_names}. "
                f"Ranking this few into buckets produces weights that mean nothing")
    elif n <= 12:
        fit.score += 10
        fit.reasons_for.append(
            f"{n} streams suits a time-series mechanism, which judges each "
            f"series against its own history rather than against its peers")

    # --- cap segment ----------------------------------------------------
    gap = abs(_SEG_RANK.get(u.cap_segment, 2) - _SEG_RANK.get(req.cap_segment, 2))
    if gap == 0:
        fit.score += 20
        fit.reasons_for.append(f"matches the paper's {req.cap_segment} segment")
    elif gap <= 1:
        fit.score += 8
        fit.reasons_for.append(
            f"{u.cap_segment} is adjacent to the paper's {req.cap_segment}")
    else:
        fit.score -= 12 * gap
        fit.reasons_against.append(
            f"{u.cap_segment} is far from the paper's {req.cap_segment}. An "
            f"effect measured in one cap segment routinely fails in another, so "
            f"a null here would not disprove the paper")

    # --- sector ---------------------------------------------------------
    if req.sector:
        if u.sector == req.sector:
            fit.score += 25
            fit.reasons_for.append(f"sector-specific paper, sector-matched universe")
        elif u.sector is None:
            fit.score -= 5
            fit.reasons_against.append(
                f"broad universe for a {req.sector}-specific mechanism: the "
                f"effect would be diluted by everything that is not {req.sector}")
        else:
            fit.disqualifying.append(
                f"{u.sector} universe for a {req.sector} paper: wrong sector")
    elif u.sector is not None:
        fit.score -= 20
        fit.reasons_against.append(
            f"a {u.sector} universe narrows a broad-market mechanism to one "
            f"sector, which tests something the paper did not claim")

    # --- history --------------------------------------------------------
    yrs = _years_since(u.history_from)
    if yrs >= req.min_history_years:
        fit.score += 10
    else:
        fit.score -= 8
        fit.reasons_against.append(
            f"~{yrs:.0f}y of history against {req.min_history_years:.0f}y wanted")

    # --- mandate --------------------------------------------------------
    if u.in_mandate:
        fit.score += 10
        fit.reasons_for.append("inside the fund's mandate: a positive result is "
                               "directly actionable")
    else:
        if req.must_be_in_mandate:
            fit.disqualifying.append(
                "outside the mandate, and this run was required to be holdable")
        else:
            fit.reasons_against.append(
                "OUTSIDE the mandate. Valid for establishing whether the effect "
                "is real; a positive result here is NOT something this fund can "
                "run, and must never be reported as though it were")
    return fit


def propose_universes(req: MechanismRequirements,
                      include_unusable: bool = False) -> List[UniverseFit]:
    """Rank every Indian universe against a mechanism's needs, best first."""
    errs = req.validate()
    if errs:
        raise ValueError("MechanismRequirements is not usable: " + "; ".join(errs))
    fits = [score_universe(u, req) for u in INDIAN_UNIVERSES.values()]
    if not include_unusable:
        fits = [f for f in fits if f.usable]
    return sorted(fits, key=lambda f: -f.score)


def render_proposal(req: MechanismRequirements, top: int = 5) -> str:
    """The block Gate A shows: what was needed, and where it could be tested."""
    L = ["  WHAT THE MECHANISM NEEDS",
         f"    cross-sectional : {req.needs_cross_section}",
         f"    names for the sort: {req.min_names}",
         f"    cap segment     : {req.cap_segment}",
         f"    sector          : {req.sector or 'broad market'}",
         f"    history wanted  : {req.min_history_years:.0f} years",
         f"    must be holdable: {req.must_be_in_mandate}"]
    if req.notes:
        L.append(f"    note            : {' '.join(req.notes.split())}")
    L.append("")
    L.append(f"  BEST-FITTING INDIAN UNIVERSES (of {len(INDIAN_UNIVERSES)} known)")
    for f in propose_universes(req)[:top]:
        L.append(f.render())
    rejected = [f for f in propose_universes(req, include_unusable=True)
                if not f.usable]
    if rejected:
        L.append("")
        L.append(f"  RULED OUT ({len(rejected)}):")
        for f in rejected[:6]:
            L.append(f"    {f.universe.name:<42} {f.disqualifying[0]}")
    return "\n".join(L)
