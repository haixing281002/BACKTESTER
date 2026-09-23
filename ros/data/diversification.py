"""Whether a candidate set of held series actually diversifies -- measured, not
assumed.

WHY THIS EXISTS

`ros/data/universes.py` scores a universe by breadth, cap segment, sector and
history -- all metadata about what an index IS. None of that says whether two
indices actually MOVE independently. A time-series mechanism (TSMOM, a
risk-parity overlay, anything that "diversifies across streams") lives or dies
on the second question, and nothing in this repo answered it mechanically
before this module: the closest precedent was a researcher computing a 20x20
correlation matrix by hand in a one-off script for one card, a piece of work
that then had no home to be reused from for the next paper.

That is the actual failure mode this fixes. A fund holding N index-level
sleeves derived from the same underlying market (NIFTY-family factor and
cap-segment indices, in this fund's case) will keep producing "8-sleeve"
candidate sets that all cluster in the 0.7-0.95 pairwise correlation range,
because they are 20 different cuts of the same ~500 large/mid-cap names. A
mechanism whose evidence (in its own source market) rests on genuine
cross-asset-class independence cannot be faithfully tested on that set no
matter how cleverly the 8 are chosen -- and the fix is not a cleverer
selection, it is naming the ceiling and asking for the data that would raise
it (stock-level breadth, a different asset class, a non-equity exposure
proxy), which is exactly what a `data_request` on the card is for.

WHEN TO USE IT

At Stage 01/02, once `ros.data.universes.propose_universes` has ranked
candidates by fit, and before `universe.assets` / `selection.explicit_securities`
is written down: run `diversification_report` on whatever the fund actually
holds that could plausibly serve the mechanism, using REAL price history (not
metadata), and put the honest floor in `universe.description` and
`data_plan.rejected_alternatives` -- as prose, the way every other Stage 01
finding reaches the card. This module computes; it does not decide anything
and it does not touch the card schema.

This deliberately requires market data (a price frame), so it belongs at
Stage 01/02 drafting time or later -- never inside `run_interpret.py`, which
must never read a price series (see CLAUDE.md, "Stages 00 to Gate A need NO
MARKET DATA").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Above this pairwise correlation, two series are "the same bet" rather than
# two independent ones. Not a magic constant: it is the threshold the model
# used, and stated, when it excluded NIFTY200-scope near-duplicates of held
# NIFTY500 factor sleeves in this fund's own card history (0.93-0.97 measured).
DEFAULT_REDUNDANCY_THRESHOLD = 0.90


def returns_frame(price_frame: pd.DataFrame, names: List[str]) -> pd.DataFrame:
    """Daily simple returns for the requested columns, aligned and dropna'd.

    Rows where ANY requested series is missing are dropped, so the correlation
    below is computed on a common window across every candidate -- a series
    that only recently launched will shrink the window for everyone, and that
    is visible in `DiversificationReport.n_obs`, not silently averaged away.
    """
    missing = [n for n in names if n not in price_frame.columns]
    if missing:
        raise KeyError(f"not held: {missing}")
    return price_frame[names].pct_change().dropna()


@dataclass
class DiversificationReport:
    candidates: List[str]
    n_obs: int
    correlation: pd.DataFrame
    pairwise_min: float
    pairwise_mean: float
    pairwise_max: float
    weakest_pair: Tuple[str, str, float]     # most independent -- the pair worth keeping
    strongest_pair: Tuple[str, str, float]   # most redundant -- the pair worth cutting
    near_duplicates: List[Tuple[str, str, float]]
    redundancy_threshold: float

    @property
    def verdict(self) -> str:
        if self.pairwise_mean >= 0.85:
            return "COLLAPSED: this set is effectively one bet measured several times"
        if self.pairwise_mean >= 0.70:
            return "THIN: correlated enough that little of the theoretical benefit of holding several streams survives"
        if self.pairwise_mean >= 0.50:
            return "MODEST: some genuine dispersion, but far from the near-zero correlation a multi-asset-class paper usually relies on"
        return "GENUINE: meaningful independence across this set"

    def render(self) -> str:
        L = [
            f"  DIVERSIFICATION -- {len(self.candidates)} candidate(s), "
            f"{self.n_obs} common daily observations",
            f"    pairwise correlation: min {self.pairwise_min:.3f}  "
            f"mean {self.pairwise_mean:.3f}  max {self.pairwise_max:.3f}",
            f"    most independent pair : {self.weakest_pair[0]} / {self.weakest_pair[1]}"
            f"  (r = {self.weakest_pair[2]:.3f})",
            f"    most redundant pair   : {self.strongest_pair[0]} / {self.strongest_pair[1]}"
            f"  (r = {self.strongest_pair[2]:.3f})",
        ]
        if self.near_duplicates:
            L.append(f"    near-duplicates (r >= {self.redundancy_threshold:.2f}):")
            for a, b, r in self.near_duplicates:
                L.append(f"      {a}  /  {b}   r = {r:.3f}")
        else:
            L.append(f"    no pair at or above the r >= {self.redundancy_threshold:.2f} "
                     f"redundancy threshold")
        L.append(f"    verdict: {self.verdict}")
        return "\n".join(L)


def diversification_report(
    price_frame: pd.DataFrame,
    candidates: List[str],
    redundancy_threshold: float = DEFAULT_REDUNDANCY_THRESHOLD,
) -> DiversificationReport:
    """Measure, from real price history, how independent a candidate set is.

    Raises on fewer than 2 candidates or a name the frame does not hold --
    both are Stage 01 errors (a typo'd series name, a set too small to have a
    pairwise anything), not a reason to silently return an empty report.
    """
    if len(candidates) < 2:
        raise ValueError("diversification_report needs at least 2 candidates")
    rets = returns_frame(price_frame, candidates)
    corr = rets.corr()

    pairs: List[Tuple[str, str, float]] = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            pairs.append((a, b, float(corr.loc[a, b])))

    vals = [r for _, _, r in pairs]
    weakest = min(pairs, key=lambda p: p[2])
    strongest = max(pairs, key=lambda p: p[2])
    dupes = sorted((p for p in pairs if p[2] >= redundancy_threshold),
                   key=lambda p: -p[2])

    return DiversificationReport(
        candidates=list(candidates), n_obs=int(len(rets)), correlation=corr,
        pairwise_min=float(np.min(vals)), pairwise_mean=float(np.mean(vals)),
        pairwise_max=float(np.max(vals)), weakest_pair=weakest,
        strongest_pair=strongest, near_duplicates=dupes,
        redundancy_threshold=redundancy_threshold,
    )


def greedy_diverse_subset(
    price_frame: pd.DataFrame,
    candidates: List[str],
    k: int,
    must_include: Optional[List[str]] = None,
) -> List[str]:
    """The k candidates that minimise pairwise redundancy, chosen greedily.

    Starts from `must_include` (or, absent that, the single most negatively/
    least-correlated pair in the whole candidate set) and repeatedly adds
    whichever remaining candidate has the LOWEST maximum correlation to
    everything already chosen -- a minimax rule, so one already-diverse
    series cannot be joined by its near-duplicate just because the near-
    duplicate is well correlated with everything else.

    This is a selection AID, not a verdict: it tells you the best available
    k-subset, not whether that subset is good enough for the mechanism. Read
    `diversification_report` on its output before trusting it.
    """
    if k < 2:
        raise ValueError("k must be >= 2")
    if k > len(candidates):
        raise ValueError(f"k={k} exceeds {len(candidates)} candidates")
    rets = returns_frame(price_frame, candidates)
    corr = rets.corr()

    chosen: List[str] = list(must_include or [])
    if not chosen:
        best_pair, best_r = None, 2.0
        for i, a in enumerate(candidates):
            for b in candidates[i + 1:]:
                r = corr.loc[a, b]
                if r < best_r:
                    best_pair, best_r = (a, b), r
        chosen = list(best_pair)

    remaining = [c for c in candidates if c not in chosen]
    while len(chosen) < k and remaining:
        best_c, best_score = None, 2.0
        for c in remaining:
            worst_corr_to_chosen = max(abs(corr.loc[c, s]) for s in chosen)
            if worst_corr_to_chosen < best_score:
                best_c, best_score = c, worst_corr_to_chosen
        chosen.append(best_c)
        remaining.remove(best_c)
    return chosen
