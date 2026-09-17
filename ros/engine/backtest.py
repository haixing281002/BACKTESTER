"""Step 05 -- BUILD + EXECUTE. Deterministic daily portfolio accounting.

Implements the paper's appendix A accounting exactly, generalised so any card can
use it:

  non-rebalance day:  V_t = V_{t-1} * ( sum_i w_i(1+r_i) + c(1+r_f) )
                      weights drift with realised returns
  rebalance day:      drift first, then trade to the target,
                      cost = (s/2) * sum_i |w_hat_i - w_i| * V_t,
                      charged to cash; turnover = half the traded fraction

Two properties the engine guarantees, because they are where backtests lie:

1. CAUSALITY. Signals are computed on the frame, then shifted by (1 + lag_days)
   before use: the weights applied to day t's return are decided using data up to
   day t-1-lag at the latest. A signal is never used to trade the bar that
   produced it.

2. NO SURVIVORSHIP DRIFT. The investable column set is fixed at construction and
   every date in the snapshot has complete data for it, so the engine cannot
   quietly widen its universe as history fills in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ros.engine.templates import Allocator, AllocatorContext


class LookaheadError(RuntimeError):
    """Raised when the engine detects a signal that could not have been known."""


def rebalance_dates(index: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    """Trading dates on which a rebalance occurs, using the LAST trading day of
    each period present in the data -- never a calendar date that may not trade."""
    s = pd.Series(index, index=index)
    if freq == "daily":
        return index
    codes = {"weekly": "W", "monthly": "M", "quarterly": "Q",
             "annual": "Y", "calendar_year_end": "Y"}
    if freq not in codes:
        raise ValueError(f"unsupported rebalance frequency '{freq}'")
    return pd.DatetimeIndex(s.groupby(index.to_period(codes[freq])).last().values)


def _alpha_row(alp, date, cross_sectional: bool):
    """The allocator's alpha vector for `date`, or None if it must not trade."""
    row = alp.loc[date]
    if not cross_sectional and row.isna().any():
        return None
    return row.to_numpy(dtype=float)


@dataclass
class BacktestResult:
    name: str
    value: pd.Series                 # portfolio NAV, starts at 1.0
    weights: pd.DataFrame            # post-trade risky weights, by date
    returns: pd.Series               # daily simple portfolio returns
    turnover: pd.Series              # per-day turnover (half traded fraction)
    costs: pd.Series                 # per-day cost in NAV fraction
    cash_weight: pd.Series
    rebalances: pd.DatetimeIndex
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def cash_drag_days(self) -> int:
        return int((self.cash_weight > 1e-6).sum())


class Backtester:
    """Deterministic engine. Same inputs -> same bytes out, always."""

    def __init__(
        self,
        prices: pd.DataFrame,
        assets: List[str],
        rf_daily: Optional[pd.Series] = None,
        spread_bps: float = 5.0,
        lag_days: int = 0,
        allow_cash: bool = True,
        ann: int = 252,
        membership: Optional[pd.DataFrame] = None,
    ):
        missing = [a for a in assets if a not in prices.columns]
        if missing:
            raise KeyError(f"prices frame is missing assets: {missing}")
        self.assets = list(assets)
        self.prices = prices[self.assets].copy()

        # A fixed sleeve set must be complete: a NaN there is a data fault and
        # silently tolerating it would let the investable universe drift.
        #
        # A CROSS-SECTION cannot be complete. Stocks list, delist, merge and get
        # suspended, so a 500-name price frame is NaN wherever a name did not
        # trade. Passing `membership` is the caller declaring that this is a
        # changing universe and that the gaps are meaningful rather than broken.
        self.membership = None
        if membership is not None:
            miss = [a for a in self.assets if a not in membership.columns]
            if miss:
                raise KeyError(f"membership frame is missing assets: {miss}")
            self.membership = (membership[self.assets]
                               .reindex(self.prices.index).fillna(False).astype(bool))
        elif self.prices.isna().any().any():
            raise ValueError(
                "price frame contains NaNs for the investable set. Resolve this in the "
                "snapshot (require_complete) so the investable universe is fixed up front.\n"
                "If this IS a changing cross-section (stocks listing and delisting), pass "
                "`membership=` -- a boolean frame saying who was investable when -- so the "
                "gaps are declared rather than inferred.")
        self.returns = self.prices.pct_change(fill_method=None)
        self.rf = (rf_daily.reindex(self.prices.index).fillna(0.0)
                   if rf_daily is not None else pd.Series(0.0, index=self.prices.index))
        self.half_spread = float(spread_bps) / 1e4 / 2.0
        self.lag_days = int(lag_days)
        self.allow_cash = bool(allow_cash)
        self.ann = ann
        self.n = len(self.assets)

    # ------------------------------------------------------------------
    def _shift_causal(self, obj, extra_lag: int = 0):
        """Shift a signal so it is knowable strictly before the bar it trades.

        Total shift is 1 + lag_days: the +1 removes same-bar use of the close that
        produced the signal; lag_days is the card's declared implementation lag.
        """
        return obj.shift(1 + self.lag_days + extra_lag)

    def run(
        self,
        allocator: Allocator,
        rebalance: str = "monthly",
        sigma_bench: Optional[pd.Series] = None,
        alpha: Optional[pd.DataFrame] = None,
        cov: Optional[Dict[pd.Timestamp, np.ndarray]] = None,
        cov_cols: Optional[List[str]] = None,
        vols: Optional[pd.DataFrame] = None,
        rf_horizon_days: int = 21,
        name: str = "strategy",
        warmup: int = 0,
    ) -> BacktestResult:
        """Simulate `allocator` over the full price history."""
        idx = self.prices.index
        rebal = set(rebalance_dates(idx, rebalance))

        # --- causal shifting of every signal the allocator may see -------------
        sig = self._shift_causal(sigma_bench) if sigma_bench is not None else None
        alp = self._shift_causal(alpha) if alpha is not None else None
        if alp is not None:
            alp = alp[self.assets]
        cov_shift = None
        if cov is not None:
            if cov_cols is None or list(cov_cols) != self.assets:
                raise ValueError("cov_cols must be provided and match `assets` order")
            # map each date to the covariance estimated (1+lag) trading days earlier
            pos = {d: i for i, d in enumerate(idx)}
            cov_shift = {}
            for d in idx:
                j = pos[d] - (1 + self.lag_days)
                if j >= 0 and idx[j] in cov:
                    cov_shift[d] = cov[idx[j]]

        vol_shift = self._shift_causal(vols[self.assets]) if vols is not None else None

        # Eligibility is a SIGNAL and gets the same causal shift as any other:
        # index membership is known only after it is announced, and a backtest
        # that selects from tomorrow's constituents is reading the future.
        # Shifting also means a delisting is acted on one bar late, which costs
        # the strategy rather than flattering it -- the correct direction for a
        # bias we cannot remove.
        elig_arr = None
        if self.membership is not None:
            elig = self._shift_causal(self.membership).fillna(False).astype(bool)
            # A name with no price cannot be traded whatever the index says.
            elig_arr = (elig & self.prices.notna()).to_numpy(dtype=bool)

        rf_period = (1.0 + self.rf).rolling(rf_horizon_days).apply(np.prod, raw=True) - 1.0
        rf_period = rf_period.fillna(0.0)

        V = 1.0
        w = np.zeros(self.n)
        first_rebal_done = False

        vals, wts, tos, cst, csh = [], [], [], [], []
        used_rebals: List[pd.Timestamp] = []
        stale = 0            # held names marked flat because they did not trade
        n_forced = 0         # positions sold because they left the universe
        rets_arr = self.returns.to_numpy(dtype=float)

        for i, date in enumerate(idx):
            # ---- 1. drift with the day's returns -----------------------------
            if i == 0 or not first_rebal_done:
                gross_ret = 0.0
            else:
                # A held name that did not trade today carries at its last price.
                # That is the standard stale-price treatment and it is a real
                # assumption: a suspended stock is marked flat, not to whatever
                # it reopens at. Where suspension precedes bad news, this
                # flatters the run, which is why `stale_marks` is reported.
                r = np.nan_to_num(rets_arr[i], nan=0.0)
                cash_w = 1.0 - w.sum()
                gross = float(np.dot(w, 1.0 + r) + cash_w * (1.0 + self.rf.iloc[i]))
                new_V = V * gross
                w = (V * w * (1.0 + r)) / new_V
                gross_ret = new_V / V - 1.0
                V = new_V
                if elig_arr is not None:
                    stale += int(np.count_nonzero((w > 0) & np.isnan(rets_arr[i])))

            day_to = 0.0
            day_cost = 0.0

            # ---- 1b. forced exit ---------------------------------------------
            # A position that has left the investable universe is SOLD, at cost,
            # on the day we learn of it. It is not dropped and it is not left to
            # the next rebalance. Quietly zeroing a weight and renormalising the
            # rest is survivorship bias in its purest form: the book would exit
            # every delisting for free, which is the opposite of what happens.
            if elig_arr is not None and first_rebal_done:
                dead = (w > 1e-12) & ~elig_arr[i]
                if dead.any():
                    forced = float(w[dead].sum())
                    day_cost += self.half_spread * forced
                    day_to += 0.5 * forced
                    V *= (1.0 - self.half_spread * forced)
                    w = np.where(dead, 0.0, w)
                    n_forced += int(dead.sum())

            # ---- 2. rebalance ------------------------------------------------
            if date in rebal and i >= warmup:
                ctx = AllocatorContext(
                    date=date,
                    current_weights=w.copy(),
                    sigma_bench=(float(sig.loc[date]) if sig is not None
                                 and pd.notna(sig.loc[date]) else None),
                    cov=(cov_shift.get(date) if cov_shift is not None else None),
                    # A fixed sleeve set requires every alpha to be finite: a
                    # NaN there means the estimator has not warmed up and the
                    # allocator must not trade. A CROSS-SECTION is never all
                    # finite -- newly listed names have no history yet -- so
                    # there the mask decides who is selectable, not the NaNs.
                    alpha=(_alpha_row(alp, date, elig_arr is not None)
                           if alp is not None else None),
                    eligible=(elig_arr[i] if elig_arr is not None else None),
                    vols=(vol_shift.iloc[i].to_numpy(dtype=float)
                          if vol_shift is not None else None),
                    rf_period=float(rf_period.iloc[i]),
                    extras={},
                )
                if allocator.ready(ctx):
                    target = np.asarray(allocator.target_weights(ctx), dtype=float)
                    if target.shape != (self.n,):
                        raise ValueError(
                            f"{allocator.template_name} returned {target.shape}, expected {(self.n,)}")
                    target = np.clip(target, 0.0, None)
                    if not self.allow_cash:
                        # mandate: stay fully invested. Re-normalise rather than
                        # silently holding cash the fund is not allowed to hold.
                        tot = target.sum()
                        target = target / tot if tot > 0 else np.ones(self.n) / self.n
                    if target.sum() > 1.0 + 1e-9:
                        target = target / target.sum()

                    traded = np.abs(target - w).sum()
                    day_cost = self.half_spread * traded
                    day_to = 0.5 * traded
                    V = V * (1.0 - day_cost)
                    w = target
                    first_rebal_done = True
                    used_rebals.append(date)

            vals.append(V)
            wts.append(w.copy())
            tos.append(day_to)
            cst.append(day_cost)
            csh.append(1.0 - w.sum())

        value = pd.Series(vals, index=idx, name=name)
        weights = pd.DataFrame(wts, index=idx, columns=self.assets)
        rets = value.pct_change().fillna(0.0)

        meta = {"template": allocator.template_name, "params": allocator.params,
                "rebalance": rebalance, "lag_days": self.lag_days,
                "spread_bps": self.half_spread * 2 * 1e4, "allow_cash": self.allow_cash,
                "n_rebalances": len(used_rebals), "warmup_days": warmup}
        if elig_arr is not None:
            # Both of these are ways a cross-sectional backtest can flatter
            # itself, so they are reported rather than left implicit.
            meta["changing_universe"] = True
            meta["forced_exits"] = n_forced
            meta["stale_marks"] = stale
            meta["mean_eligible"] = float(elig_arr.sum(axis=1).mean())
        if hasattr(allocator, "diagnostics"):
            meta["allocator_diagnostics"] = allocator.diagnostics()

        return BacktestResult(
            name=name, value=value, weights=weights, returns=rets,
            turnover=pd.Series(tos, index=idx), costs=pd.Series(cst, index=idx),
            cash_weight=pd.Series(csh, index=idx),
            rebalances=pd.DatetimeIndex(used_rebals), meta=meta)


def assert_causal(signal: pd.DataFrame | pd.Series, returns: pd.DataFrame | pd.Series,
                  tol: float = 0.35, label: str = "signal",
                  horizons: Sequence[int] = (0, 1)) -> None:
    """Look-ahead tripwire.

    Checks the correlation between signal[t] and returns[t + h] for each h in
    `horizons`. Two distinct leak classes are covered:

      h = 0  the signal knows the bar it trades (an off-by-one in the shift)
      h = 1  the signal knows tomorrow (a negative shift left in by accident)

    A genuine causal signal correlates weakly with both. This does not PROVE
    causality -- only the shift logic does -- but it catches the mistakes that
    silently inflate every downstream number, and it is cheap enough to run on
    every input to every backtest.
    """
    s = pd.DataFrame(signal).astype(float)
    r = pd.DataFrame(returns).astype(float)
    for h in horizons:
        rh = r.shift(-h)
        common = s.index.intersection(rh.index)
        for c in s.columns:
            if c not in rh.columns:
                continue
            a, b = s.loc[common, c], rh.loc[common, c]
            m = a.notna() & b.notna()
            if m.sum() < 60:
                continue
            sa, sb = a[m].std(), b[m].std()
            if sa == 0 or sb == 0:
                continue
            rho = float(np.corrcoef(a[m], b[m])[0, 1])
            if abs(rho) > tol:
                raise LookaheadError(
                    f"{label}/{c}: |corr(signal[t], return[t+{h}])| = {abs(rho):.2f} > {tol}. "
                    f"The signal appears to know {'the bar it trades' if h == 0 else f'{h} bar(s) ahead'}.")
