"""Step 07 -- PORTFOLIO VALIDATION.

Step 06 asks 'is the result real?'. Step 06 passing is necessary and nowhere near
sufficient. Step 07 asks the only question a PM cares about:

    does adding this to the book we already run make the book better,
    after costs, given what we already own?

A strategy with a standalone Sharpe of 1.2 that is 0.95-correlated to the existing
book adds nothing. That is the single most common way a 'validated' signal turns
out to be worthless, and it is why the fingerprint and orthogonality checks below
are gating rather than informational.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ros.validation.metrics import ANN, ann_vol, cagr, cvar, max_drawdown

try:
    import statsmodels.api as sm
except ImportError:  # pragma: no cover
    sm = None


def _align(a: pd.Series, b: pd.Series):
    df = pd.concat([a, b], axis=1).dropna()
    return df.iloc[:, 0], df.iloc[:, 1]


def benchmark_relative(strategy_ret: pd.Series, bench_ret: pd.Series,
                       rf_daily: Optional[pd.Series] = None,
                       ann: int = ANN) -> Dict[str, float]:
    """Beta, annualised alpha, tracking error, information ratio, capture ratios.

    For a long-only benchmarked fund these matter more than standalone Sharpe:
    the fund is not choosing between this strategy and cash, it is choosing
    between this strategy and its current benchmark exposure.
    """
    s, b = _align(strategy_ret, bench_ret)
    if len(s) < 100:
        return {"error": "insufficient overlap"}
    rf = rf_daily.reindex(s.index).fillna(0.0) if rf_daily is not None else pd.Series(0.0, index=s.index)
    se, be = s - rf, b - rf

    var_b = float(be.var(ddof=1))
    beta = float(se.cov(be) / var_b) if var_b > 0 else float("nan")
    alpha_daily = float(se.mean() - beta * be.mean())
    active = s - b
    te = float(active.std(ddof=1) * np.sqrt(ann))

    up = b > 0
    dn = b < 0
    return {
        "beta": beta,
        "alpha_ann": float((1.0 + alpha_daily) ** ann - 1.0),
        "tracking_error": te,
        "information_ratio": float(active.mean() * ann / te) if te > 0 else float("nan"),
        "active_return_ann": float(active.mean() * ann),
        "correlation": float(s.corr(b)),
        "up_capture": float(s[up].mean() / b[up].mean()) if up.sum() > 20 and b[up].mean() != 0 else float("nan"),
        "down_capture": float(s[dn].mean() / b[dn].mean()) if dn.sum() > 20 and b[dn].mean() != 0 else float("nan"),
        "n_obs": int(len(s)),
    }


def factor_fingerprint(strategy_ret: pd.Series, factor_rets: pd.DataFrame,
                       rf_daily: Optional[pd.Series] = None,
                       ann: int = ANN) -> Dict[str, Any]:
    """Regress strategy excess return on factor-sleeve excess returns.

    Reports HAC (Newey-West) t-stats, because daily strategy returns are
    autocorrelated and heteroskedastic and OLS t-stats on them are optimistic
    by a wide margin.

    The fingerprint is what stops the library filling up with the same bet under
    different names: two cards with the same loading vector are the same trade.
    """
    if sm is None:
        return {"error": "statsmodels not installed"}
    df = pd.concat([strategy_ret.rename("y"), factor_rets], axis=1).dropna()
    if len(df) < 200:
        return {"error": f"insufficient overlap ({len(df)})"}
    rf = rf_daily.reindex(df.index).fillna(0.0) if rf_daily is not None else 0.0
    y = df["y"] - rf
    X = df.drop(columns=["y"]).sub(rf, axis=0)
    X = sm.add_constant(X)

    lags = int(np.ceil(4 * (len(df) / 100.0) ** (2.0 / 9.0)))
    fit = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})

    loadings = {k: float(v) for k, v in fit.params.items() if k != "const"}
    tstats = {k: float(v) for k, v in fit.tvalues.items() if k != "const"}
    vec = np.array([loadings[k] for k in sorted(loadings)])
    norm = float(np.linalg.norm(vec))
    return {
        "alpha_ann": float((1.0 + float(fit.params["const"])) ** ann - 1.0),
        "alpha_t_hac": float(fit.tvalues["const"]),
        "alpha_p_hac": float(fit.pvalues["const"]),
        "loadings": loadings,
        "t_stats_hac": tstats,
        "r_squared": float(fit.rsquared),
        "hac_lags": lags,
        "n_obs": int(len(df)),
        "fingerprint": {k: round(v / norm, 4) for k, v in sorted(loadings.items())} if norm > 0 else {},
        "residual_vol_ann": float(fit.resid.std(ddof=1) * np.sqrt(ann)),
        "interpretation": (
            f"R^2 = {fit.rsquared:.2f} against known factor sleeves; "
            f"alpha t-stat (HAC) = {float(fit.tvalues['const']):.2f}."),
    }


def signal_similarity(candidate_ret: pd.Series,
                      existing: Dict[str, pd.Series]) -> pd.DataFrame:
    """Correlation and residual-vol-retained against everything already in the book."""
    rows = []
    for nm, s in existing.items():
        a, b = _align(candidate_ret, s)
        if len(a) < 100:
            continue
        rho = float(a.corr(b))
        beta = float(a.cov(b) / b.var(ddof=1)) if b.var(ddof=1) > 0 else np.nan
        resid = a - beta * b
        rows.append({
            "existing_signal": nm,
            "correlation": rho,
            "beta_to_existing": beta,
            "residual_vol_retained": float(resid.std(ddof=1) / a.std(ddof=1)),
        })
    return pd.DataFrame(rows).sort_values("correlation", ascending=False) if rows else pd.DataFrame()


def incremental_ir(candidate_ret: pd.Series, book_ret: pd.Series,
                   bench_ret: pd.Series, weights: List[float] = (0.05, 0.10, 0.20),
                   rf_daily: Optional[pd.Series] = None, ann: int = ANN) -> pd.DataFrame:
    """Blend the candidate into the existing book at several sleeve sizes and
    measure the change in information ratio versus the benchmark.

    This, not standalone Sharpe, is the promotion criterion the board specified.
    A positive incremental IR at a sleeve size the fund would actually allocate
    is the whole test.
    """
    df = pd.concat([candidate_ret.rename("c"), book_ret.rename("b"),
                    bench_ret.rename("m")], axis=1).dropna()
    if len(df) < 200:
        return pd.DataFrame([{"error": "insufficient overlap"}])

    def ir(x: pd.Series) -> float:
        a = x - df["m"]
        sd = a.std(ddof=1)
        return float(a.mean() * ann / (sd * np.sqrt(ann))) if sd > 0 else float("nan")

    base_ir = ir(df["b"])
    rows = [{"sleeve_weight": 0.0, "blended_ir": base_ir, "delta_ir": 0.0,
             "blended_te": float((df["b"] - df["m"]).std(ddof=1) * np.sqrt(ann)),
             "blended_cagr": float((1 + df["b"]).prod() ** (ann / len(df)) - 1)}]
    for w in weights:
        blend = (1 - w) * df["b"] + w * df["c"]
        rows.append({
            "sleeve_weight": w,
            "blended_ir": ir(blend),
            "delta_ir": ir(blend) - base_ir,
            "blended_te": float((blend - df["m"]).std(ddof=1) * np.sqrt(ann)),
            "blended_cagr": float((1 + blend).prod() ** (ann / len(df)) - 1),
        })
    return pd.DataFrame(rows)


def turnover_capacity(result, aum_inr_cr: float, adv_inr_cr: float,
                      max_participation: float = 0.10,
                      ann: int = ANN) -> Dict[str, Any]:
    """Crude but honest capacity check: can the book trade its own turnover?

    Deliberately simple. Its purpose is to catch the strategy that needs 280%
    annual turnover in names that trade 5 crore a day -- a constraint no amount
    of Sharpe fixes.
    """
    to_ann = float(result.turnover.mean() * ann)
    n_reb = max(len(result.rebalances), 1)
    per_reb_frac = to_ann / (n_reb / ((result.value.index[-1] - result.value.index[0]).days / 365.25))
    notional_per_reb = aum_inr_cr * per_reb_frac * 2.0   # buys + sells
    tradable_per_day = adv_inr_cr * max_participation
    return {
        "annual_turnover": to_ann,
        "rebalances_per_year": n_reb / ((result.value.index[-1] - result.value.index[0]).days / 365.25),
        "notional_per_rebalance_inr_cr": notional_per_reb,
        "tradable_per_day_inr_cr": tradable_per_day,
        "days_to_execute_rebalance": (notional_per_reb / tradable_per_day
                                      if tradable_per_day > 0 else float("inf")),
        "aum_inr_cr": aum_inr_cr,
        "max_participation": max_participation,
    }


def mandate_check(result, long_only: bool = True, allow_cash: bool = False,
                  max_cash: float = 0.0, max_single_weight: float = 1.0) -> Dict[str, Any]:
    """Does the realised position path actually obey the fund's mandate?

    Run on the OUTPUT, not the config, because a template can satisfy its own
    constraints and still violate a mandate the template never knew about --
    which is exactly what happens when a US total-return paper is dropped into
    a fully-invested Indian equity fund.
    """
    w = result.weights
    cash = result.cash_weight
    viol: List[str] = []
    max_cash_obs = float(cash.max())
    mean_cash_obs = float(cash.mean())
    if not allow_cash and max_cash_obs > max_cash + 1e-6:
        viol.append(
            f"holds up to {max_cash_obs:.1%} cash (mean {mean_cash_obs:.1%}) but the "
            f"mandate permits {max_cash:.1%}")
    if long_only and float(w.min().min()) < -1e-9:
        viol.append("negative weights present under a long-only mandate")
    mx = float(w.max().max())
    if mx > max_single_weight + 1e-6:
        viol.append(f"max single-sleeve weight {mx:.1%} exceeds limit {max_single_weight:.1%}")
    return {
        "max_cash": max_cash_obs, "mean_cash": mean_cash_obs,
        "max_single_weight": mx,
        "days_holding_cash": int((cash > 1e-6).sum()),
        "pct_days_holding_cash": float((cash > 1e-6).mean()),
        "violations": viol,
        "passes": not viol,
    }
