"""Allocator templates -- Step 05, the 'template-constrained generation' the board
approved. A Strategy Card names a template and supplies params; it never supplies code.

Every template implements:
    target_weights(ctx) -> np.ndarray of risky-asset weights (cash is the remainder)

`ctx` is an AllocatorContext carrying only information available at the rebalance
date. Templates cannot see the future because they cannot see the price frame --
only the pre-computed causal inputs the backtester hands them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

_TEMPLATES: Dict[str, Callable[..., "Allocator"]] = {}


def template(name: str):
    def deco(cls):
        if name in _TEMPLATES:
            raise ValueError(f"template '{name}' already registered")
        _TEMPLATES[name] = cls
        cls.template_name = name
        return cls
    return deco


def build_allocator(name: str, assets: List[str], **params) -> "Allocator":
    if name not in _TEMPLATES:
        raise KeyError(f"unknown template '{name}'. Registered: {sorted(_TEMPLATES)}")
    return _TEMPLATES[name](assets=assets, **params)


def list_templates() -> List[str]:
    return sorted(_TEMPLATES)


@dataclass
class AllocatorContext:
    """Everything an allocator may look at on a rebalance date."""
    date: pd.Timestamp
    current_weights: np.ndarray       # drifted risky weights, pre-trade
    sigma_bench: Optional[float]      # trailing vol of the strategic mix
    cov: Optional[np.ndarray]         # annualised covariance matrix
    alpha: Optional[np.ndarray]       # expected return over the rebalance horizon
    rf_period: float = 0.0            # risk-free return over the rebalance horizon
    # Cross-sectional fields. A 500-name universe cannot use `cov`: a 500x500
    # rolling covariance is gigabytes of matrices a ranking allocator never
    # reads. Cross-sectional templates get per-asset vols and an eligibility
    # mask instead. Both are already lag-shifted by the time they arrive here.
    eligible: Optional[np.ndarray] = None   # bool: investable, as known on this date
    vols: Optional[np.ndarray] = None       # per-asset trailing vol, annualised
    extras: Dict[str, Any] = None


class Allocator:
    template_name = "abstract"
    requires: tuple = ()               # context fields that must be non-None

    def __init__(self, assets: List[str], **params):
        self.assets = list(assets)
        self.n = len(assets)
        self.params = params

    def ready(self, ctx: AllocatorContext) -> bool:
        return all(getattr(ctx, f) is not None for f in self.requires)

    def target_weights(self, ctx: AllocatorContext) -> np.ndarray:
        raise NotImplementedError

    def describe(self) -> Dict[str, Any]:
        return {"template": self.template_name, "assets": self.assets, "params": self.params}


def _as_vector(weights, assets: List[str]) -> np.ndarray:
    """Accept a dict {asset: w} or a list, return an ndarray aligned to `assets`."""
    if isinstance(weights, dict):
        missing = [a for a in assets if a not in weights]
        if missing:
            raise KeyError(f"strategic weights missing assets: {missing}")
        extra = [k for k in weights if k not in assets]
        if extra:
            raise KeyError(f"strategic weights name unknown assets: {extra}")
        return np.array([float(weights[a]) for a in assets])
    v = np.asarray(weights, dtype=float)
    if v.shape != (len(assets),):
        raise ValueError(f"expected {len(assets)} weights, got {v.shape}")
    return v


# ---------------------------------------------------------------------------
@template("fixed_weight")
class FixedWeight(Allocator):
    """Constant target weights. The benchmark every dynamic template must beat."""

    def __init__(self, assets, weights, **kw):
        super().__init__(assets, weights=weights, **kw)
        self.w = _as_vector(weights, self.assets)

    def target_weights(self, ctx: AllocatorContext) -> np.ndarray:
        return self.w.copy()


@template("vol_target")
class VolTarget(Allocator):
    """Volatility control: dilute a fixed mix with cash to cap ex-ante vol.

    Paper eq. (1):  w_hat = (sigma_tgt / sigma_t) * w_tgt   if sigma_t > sigma_tgt
                    w_hat = w_tgt                           otherwise

    Long-only and unlevered: the scale factor is capped at 1, so the portfolio
    de-risks into cash but never levers up in calm regimes.
    """
    requires = ("sigma_bench",)

    def __init__(self, assets, weights, target_vol, max_scale=1.0, **kw):
        super().__init__(assets, weights=weights, target_vol=target_vol,
                         max_scale=max_scale, **kw)
        self.w = _as_vector(weights, self.assets)
        self.target_vol = float(target_vol)
        self.max_scale = float(max_scale)

    def target_weights(self, ctx: AllocatorContext) -> np.ndarray:
        if ctx.sigma_bench is None or not np.isfinite(ctx.sigma_bench) or ctx.sigma_bench <= 0:
            return self.w.copy()
        scale = min(self.max_scale, self.target_vol / ctx.sigma_bench)
        return self.w * scale


@template("markowitz_l1")
class MarkowitzL1(Allocator):
    """Paper eq. (3): maximise next-period net return subject to a hard risk cap
    and an l1 leash to a strategic mix.

        maximise    alpha'w + rf(1 - 1'w) - (s/2)||w - w_t||_1
        subject to  w >= 0,  1'w <= 1
                    || w - (1'w) w_tgt ||_1 <= l1_budget * 1'w
                    sqrt(w' Sigma w) <= sigma_tgt

    The l1 leash is what keeps this from being a naive mean-variance optimiser:
    it bounds how far the RELATIVE mix may stray from the strategic allocation,
    which is the standard defence against error-maximisation in Markowitz.
    """
    requires = ("cov", "alpha")

    def __init__(self, assets, strategic_weights, target_vol, spread_bps=5.0,
                 l1_budget=1.0, solver="CLARABEL", **kw):
        super().__init__(assets, strategic_weights=strategic_weights,
                         target_vol=target_vol, spread_bps=spread_bps,
                         l1_budget=l1_budget, solver=solver, **kw)
        self.w_tgt = _as_vector(strategic_weights, self.assets)
        self.target_vol = float(target_vol)
        self.half_spread = float(spread_bps) / 1e4 / 2.0
        self.l1_budget = float(l1_budget)
        self.solver = solver
        self._fail_count = 0
        self._solve_count = 0

    def target_weights(self, ctx: AllocatorContext) -> np.ndarray:
        import cvxpy as cp

        Sigma = np.asarray(ctx.cov, dtype=float)
        alpha = np.asarray(ctx.alpha, dtype=float)
        if not np.all(np.isfinite(Sigma)) or not np.all(np.isfinite(alpha)):
            return ctx.current_weights.copy()

        # symmetrise and PSD-project: a rolling sample covariance on a short
        # window is frequently indefinite by a rounding epsilon, which the conic
        # solver rejects outright.
        Sigma = 0.5 * (Sigma + Sigma.T)
        evals, evecs = np.linalg.eigh(Sigma)
        evals = np.clip(evals, 1e-12, None)
        Sigma = evecs @ np.diag(evals) @ evecs.T
        L = np.linalg.cholesky(Sigma + 1e-12 * np.eye(self.n))

        w = cp.Variable(self.n)
        gross = cp.sum(w)
        obj = (alpha @ w
               + ctx.rf_period * (1.0 - gross)
               - self.half_spread * cp.norm1(w - ctx.current_weights))
        cons = [
            w >= 0,
            gross <= 1.0,
            cp.norm1(w - gross * self.w_tgt) <= self.l1_budget * gross,
            cp.norm(L.T @ w, 2) <= self.target_vol,
        ]
        self._solve_count += 1
        try:
            prob = cp.Problem(cp.Maximize(obj), cons)
            prob.solve(solver=self.solver)
            if w.value is None or prob.status not in ("optimal", "optimal_inaccurate"):
                raise RuntimeError(prob.status)
        except Exception:
            self._fail_count += 1
            # Documented fallback: hold. Never silently substitute a different
            # strategy -- a solver failure is recorded and surfaced in diagnostics.
            return ctx.current_weights.copy()

        return np.clip(np.asarray(w.value, dtype=float), 0.0, None)

    def diagnostics(self) -> Dict[str, Any]:
        return {"solves": self._solve_count, "solver_failures": self._fail_count}


@template("inverse_vol")
class InverseVol(Allocator):
    """Naive risk parity: weights proportional to 1/sigma_i, scaled to the vol target."""
    requires = ("cov",)

    def __init__(self, assets, target_vol=None, **kw):
        super().__init__(assets, target_vol=target_vol, **kw)
        self.target_vol = target_vol

    def target_weights(self, ctx):
        sd = np.sqrt(np.diag(np.asarray(ctx.cov, dtype=float)))
        if not np.all(np.isfinite(sd)) or np.any(sd <= 0):
            return ctx.current_weights.copy()
        w = (1.0 / sd)
        w = w / w.sum()
        return _scale_to_vol(w, ctx.cov, self.target_vol)


@template("equal_risk_contribution")
class EqualRiskContribution(Allocator):
    """Risk parity proper: each asset contributes equally to portfolio variance.

    Solved by the standard convex surrogate
        min 0.5 w'Sigma w - sum(log w),
    whose optimum has equal risk contributions after normalisation.
    """
    requires = ("cov",)

    def __init__(self, assets, target_vol=None, **kw):
        super().__init__(assets, target_vol=target_vol, **kw)
        self.target_vol = target_vol

    def target_weights(self, ctx):
        import warnings

        import cvxpy as cp
        Sigma = np.asarray(ctx.cov, dtype=float)
        Sigma = 0.5 * (Sigma + Sigma.T)
        ev, evec = np.linalg.eigh(Sigma)
        # The log barrier is poorly conditioned when a short-window covariance is
        # near-singular -- which, with 11 daily observations over five correlated
        # sleeves, it frequently is. Floor the eigenvalues harder than elsewhere so
        # the barrier stays finite, and count inaccurate solves rather than letting
        # cvxpy print a warning per rebalance.
        Sigma = evec @ np.diag(np.clip(ev, 1e-8, None)) @ evec.T
        y = cp.Variable(self.n, pos=True)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                prob = cp.Problem(cp.Minimize(0.5 * cp.quad_form(y, cp.psd_wrap(Sigma))
                                              - cp.sum(cp.log(y))))
                prob.solve(solver=cp.CLARABEL)
            if y.value is None:
                raise RuntimeError("no solution")
            if prob.status == "optimal_inaccurate":
                self._inaccurate = getattr(self, "_inaccurate", 0) + 1
        except Exception:
            self._failures = getattr(self, "_failures", 0) + 1
            return ctx.current_weights.copy()
        w = np.asarray(y.value, dtype=float)
        w = w / w.sum()
        return _scale_to_vol(w, Sigma, self.target_vol)

    def diagnostics(self) -> Dict[str, Any]:
        return {"solver_failures": getattr(self, "_failures", 0),
                "inaccurate_solves": getattr(self, "_inaccurate", 0)}


@template("min_variance")
class MinVariance(Allocator):
    """Long-only global minimum-variance portfolio, scaled to the vol target."""
    requires = ("cov",)

    def __init__(self, assets, target_vol=None, **kw):
        super().__init__(assets, target_vol=target_vol, **kw)
        self.target_vol = target_vol

    def target_weights(self, ctx):
        import cvxpy as cp
        Sigma = np.asarray(ctx.cov, dtype=float)
        Sigma = 0.5 * (Sigma + Sigma.T)
        ev, evec = np.linalg.eigh(Sigma)
        Sigma = evec @ np.diag(np.clip(ev, 1e-12, None)) @ evec.T
        w = cp.Variable(self.n)
        try:
            cp.Problem(cp.Minimize(cp.quad_form(w, cp.psd_wrap(Sigma))),
                       [w >= 0, cp.sum(w) == 1]).solve(solver=cp.CLARABEL)
            if w.value is None:
                raise RuntimeError("no solution")
        except Exception:
            return ctx.current_weights.copy()
        ww = np.clip(np.asarray(w.value, dtype=float), 0, None)
        ww = ww / ww.sum()
        return _scale_to_vol(ww, Sigma, self.target_vol)


@template("equal_weight")
class EqualWeight(Allocator):
    """1/N. Included because it is the benchmark most optimisers fail to beat."""

    def __init__(self, assets, target_vol=None, **kw):
        super().__init__(assets, target_vol=target_vol, **kw)
        self.target_vol = target_vol

    def target_weights(self, ctx):
        w = np.ones(self.n) / self.n
        if self.target_vol is None or ctx.cov is None:
            return w
        return _scale_to_vol(w, ctx.cov, self.target_vol)


def _scale_to_vol(w: np.ndarray, cov, target_vol: Optional[float]) -> np.ndarray:
    """Dilute a unit-gross portfolio with cash to hit a vol target. Never levers."""
    if target_vol is None or cov is None:
        return w
    v = float(np.sqrt(max(w @ np.asarray(cov, dtype=float) @ w, 0.0)))
    if not np.isfinite(v) or v <= 0:
        return w
    return w * min(1.0, target_vol / v)


@template("ts_momentum")
class TimeSeriesMomentum(Allocator):
    """Long-only time-series momentum (Moskowitz-Ooi-Pedersen style).

    Hold only sleeves whose trailing return is positive; size them inverse to
    their own volatility so each contributes comparable risk; then scale the whole
    book to the volatility target.

    Added to demonstrate the extension path: a structurally different paper needed
    ONE template and ONE primitive branch. The engine, the accounting, the
    validation suite and the governance ladder were not touched.
    """
    requires = ("alpha", "cov")

    def __init__(self, assets, target_vol=None, vol_weighted=True,
                 min_positive=1, **kw):
        super().__init__(assets, target_vol=target_vol, vol_weighted=vol_weighted,
                         min_positive=min_positive, **kw)
        self.target_vol = target_vol
        self.vol_weighted = bool(vol_weighted)
        self.min_positive = int(min_positive)

    def target_weights(self, ctx: AllocatorContext) -> np.ndarray:
        mom = np.asarray(ctx.alpha, dtype=float)
        cov = np.asarray(ctx.cov, dtype=float)
        if not np.all(np.isfinite(mom)) or not np.all(np.isfinite(cov)):
            return ctx.current_weights.copy()

        signal = (mom > 0).astype(float)
        if signal.sum() < self.min_positive:
            # No sleeve in an uptrend: hold cash rather than force an allocation.
            return np.zeros(self.n)

        if self.vol_weighted:
            sd = np.sqrt(np.diag(cov))
            sd = np.where(sd > 0, sd, np.nan)
            w = signal / sd
            w = np.nan_to_num(w, nan=0.0)
        else:
            w = signal
        if w.sum() <= 0:
            return np.zeros(self.n)
        w = w / w.sum()
        return _scale_to_vol(w, cov, self.target_vol)


@template("cross_sectional")
class CrossSectional(Allocator):
    """Rank a cross-section, hold the top slice, weight it. Long-only.

    The shape almost every equity anomaly paper takes: score every security,
    sort, buy the winners, sell the losers, rebalance. This fund cannot sell
    the losers, so only the long leg is built -- and that is a DIFFERENT
    STRATEGY from the paper's, never to be scored against its numbers. The card
    must say so in `strategy.long_only_adaptation`; the schema refuses it
    otherwise.

    Parameters
    ----------
    n_hold      : how many names to hold. Mutually exclusive with `quantile`.
    quantile    : top fraction to hold (0.1 = top decile).
    weighting   : equal | signal | inverse_vol
    max_weight  : per-name cap, applied after weighting and renormalised.
    ascending   : True if a LOW score is good (cheapness, low vol).
    min_names   : refuse to trade below this many eligible names.

    What this deliberately does NOT do
    ----------------------------------
    It does not neutralise sector, size or beta. A long-only top-decile book
    built on almost any score is a large active bet on whatever the score
    correlates with, and reporting its return as alpha is the single most
    common way a cross-sectional backtest misleads. Stage 07's factor
    fingerprint exists to catch exactly that, and it is where this template's
    output has to survive.
    """
    requires = ("alpha", "eligible")

    def __init__(self, assets, n_hold=None, quantile=None, weighting="equal",
                 max_weight=None, ascending=False, min_names=10, **kw):
        super().__init__(assets, n_hold=n_hold, quantile=quantile,
                         weighting=weighting, max_weight=max_weight,
                         ascending=ascending, min_names=min_names, **kw)
        if (n_hold is None) == (quantile is None):
            raise ValueError("cross_sectional needs exactly one of n_hold or quantile")
        if weighting not in ("equal", "signal", "inverse_vol"):
            raise ValueError(f"unknown weighting '{weighting}'")
        self.n_hold = int(n_hold) if n_hold is not None else None
        self.quantile = float(quantile) if quantile is not None else None
        self.weighting = weighting
        self.max_weight = float(max_weight) if max_weight is not None else None
        self.ascending = bool(ascending)
        self.min_names = int(min_names)
        self._skipped = 0
        self._held: List[int] = []

    def target_weights(self, ctx: AllocatorContext) -> np.ndarray:
        score = np.asarray(ctx.alpha, dtype=float)
        ok = np.asarray(ctx.eligible, dtype=bool) & np.isfinite(score)
        n_ok = int(ok.sum())

        # Too thin a cross-section is not a portfolio. Ranking 4 names into
        # deciles produces weights, and they mean nothing.
        if n_ok < self.min_names:
            self._skipped += 1
            return ctx.current_weights.copy()

        k = self.n_hold if self.n_hold is not None else max(
            1, int(round(self.quantile * n_ok)))
        k = min(k, n_ok)

        idx = np.flatnonzero(ok)
        s = score[idx]
        # Rank by score. argsort is ascending, so a "high is good" signal is
        # negated rather than reversed -- reversing would make ties break the
        # opposite way and quietly change the book at every rebalance.
        order = np.argsort(s if self.ascending else -s, kind="stable")
        chosen = idx[order[:k]]
        self._held.append(k)

        w = np.zeros(self.n)
        if self.weighting == "equal":
            w[chosen] = 1.0 / k
        elif self.weighting == "signal":
            v = score[chosen]
            v = (v.max() - v) if self.ascending else (v - v.min())
            # A flat or single-name slice has no spread to weight by; fall back
            # to equal rather than dividing by zero.
            w[chosen] = (v / v.sum()) if v.sum() > 0 else 1.0 / k
        else:                                          # inverse_vol
            if ctx.vols is None:
                w[chosen] = 1.0 / k
            else:
                sd = np.asarray(ctx.vols, dtype=float)[chosen]
                inv = np.where(np.isfinite(sd) & (sd > 0), 1.0 / sd, np.nan)
                w[chosen] = (np.nan_to_num(inv) / np.nansum(inv)
                             if np.isfinite(inv).any() else 1.0 / k)

        if self.max_weight is not None:
            # One pass of cap-and-redistribute. Not iterated to a fixed point:
            # a second pass can re-breach the cap, and silently looping would
            # hide a cap set too tight for the number of names held.
            w = np.minimum(w, self.max_weight)
            tot = w.sum()
            if tot > 0:
                w = w / tot
        return w

    def diagnostics(self) -> Dict[str, Any]:
        return {"rebalances_skipped_thin_universe": self._skipped,
                "mean_names_held": (float(np.mean(self._held)) if self._held else 0.0)}
