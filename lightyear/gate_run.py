# Quant AI Researcher
"""Score one run folder on Gate v2 from its own hand-off files. Lightyear and the re-score of past runs share this code."""
import os

import pandas as pd

from ros import config
from ros.cards.schema import load_card
from ros.governance import gate_v2
from ros.metrics import core
from ros.validation import gate_evidence as ev

from .paths import REPO


def capacity(df, trades, card=None) -> dict:
    """Trade size against 20-day ADV. Always: per Rs 1 crore of capital and the capital at which the 95th-percentile
    trade reaches the limit (no AUM assumed). At a capital size only when the card's portfolio.aum_inr_cr was set at
    Gate A (operator's ruling 2026-11-06: AUM is set only there)."""
    if trades is None or "isin" not in trades.columns:
        return {"status": "not computed", "why": "trades.csv has no isin column"}
    from ros.data import ace
    try:
        value = ace.wide("value_cr").loc[df["date"].min() - pd.Timedelta(days=60):df["date"].max()]
    except FileNotFoundError as e:
        return {"status": "not computed", "why": f"no traded value: {e}"}
    adv = core.adv_20(value)
    cap = config.gate_thresholds().get("capacity") or {}
    limit = cap.get("p95_adv_participation_max")
    out = {"unit": core.capacity_unit(trades, adv, limit), "limit_is_placeholder": bool(cap.get("limit_is_placeholder", True))}
    aum = getattr(getattr(card, "portfolio", None), "aum_inr_cr", None)
    if not aum:
        return {"status": "AUM not set at Gate A", "why": "AUM not set at Gate A", **out}
    return {"status": "computed", "aum_inr_cr": float(aum), **core.capacity(trades, adv, float(aum), limit), **out}


def _checks(rd):
    p = os.path.join(rd, "out", "checks.csv")
    if not os.path.exists(p):
        return None
    t = pd.read_csv(p)
    return [{"check": r["check"], "passed": str(r["passed"]).strip().lower() == "true"} for _, r in t.iterrows()]


def _coverage(rd):
    p = os.path.join(rd, "out", "universe_coverage.csv")
    if not os.path.exists(p):
        return None, None
    t = pd.read_csv(p)
    share = float((t["priced_mean"] * t["sessions"]).sum() / (t["members_mean"] * t["sessions"]).sum())
    names = sorted({n.strip() for cell in t["never_priced_names"].dropna() for n in str(cell).split(",") if n.strip()})
    return share, names


def _positions(holdings):
    """Largest cash share, largest weight and lowest weight across the rebalances the run recorded."""
    if holdings is None or not len(holdings):
        return None
    gross = holdings.groupby("date")["weight"].sum()
    return {"max_cash_share": float(max(0.0, 1.0 - gross.min())), "max_single_weight": float(holdings["weight"].abs().max()), "min_weight": float(holdings["weight"].min())}


def score(rd, card_path, df, trades=None, holdings=None, spec_failures=None) -> dict:
    """Gate v2 for a run, on its daily returns exactly as run: that is, at the cost on its approved card and nothing else.
    `spec_failures` is the audit's count of rules not honoured; None when no audit ran."""
    th = config.gate_thresholds()
    idx = pd.DatetimeIndex(df["date"])
    r = pd.Series(df["strategy"].fillna(0.0).to_numpy(dtype=float), index=idx)
    b = pd.Series(df["benchmark"].fillna(0.0).to_numpy(dtype=float), index=idx)
    card = load_card(card_path if os.path.isabs(card_path) else os.path.join(REPO, card_path))
    e = {"mandate_observed": _positions(holdings), "checks": _checks(rd), "reconciles": None if spec_failures is None else spec_failures == 0}
    e["priced_coverage"], e["unpriced"] = _coverage(rd)
    e["capacity"] = capacity(df, trades, card)

    series = r
    basis = f"daily returns at the card's cost, {float(card.costs.spread_bps):g}bp round trip"
    cash = core.daily_cash(config.cash_rate_for(card)[0])
    e["net_edge"] = core.cagr(core.value_from_returns(series)) - core.cagr(core.value_from_returns(b))
    boot = ev.paired_bootstrap(series, b, cash)
    e.update(bootstrap_p=boot["p"], bootstrap_max_dd_gap=boot["max_dd_gap_mean"])
    sp = ev.sub_period(series, b, cash, fits_parameters=bool(card.fits_parameters))
    e.update(sub_period_name=sp["name"], sub_period_n=sp["n"], sub_period_positive=sp["positive"], sub_period_worst=sp["worst"],
             sub_period_evidence="; ".join(f"{w['window']}: Sharpe {w['sharpe']:.2f}, benchmark {w['benchmark_sharpe']:.2f}" for w in sp["windows"]))
    fa = ev.factor_alpha(series, ev.factor_returns(idx), cash)
    if "error" not in fa:
        loo = ", ".join(f"{k} {v['alpha_t_hac']:.2f}" for k, v in fa.get("leave_one_out", {}).items())
        e.update(alpha=fa["alpha_ann"], alpha_t=fa["alpha_t_hac"], alpha_evidence=f"alpha {fa['alpha_ann']:.2%} a year, R-squared {fa['r_squared']:.2f}. t with each factor left out: {loo}. Factor indices are backfilled before launch and price-only")
    pp = core.post_publication(series, b, cash, card.paper.date)
    if pp:
        e["post_publication_edge"] = pp["edge"]
    book_path = config.fund().get("book_returns_csv")
    if book_path:
        bk = pd.read_csv(book_path, parse_dates=["date"]).set_index("date")["book"]
        e.update(ev.book_tests(series, bk, b))
    res = gate_v2.evaluate(e, th, config.mandate()).to_dict()
    res["basis"] = basis
    res["summary"] = {k: e.get(k) for k in ("net_edge", "bootstrap_p", "bootstrap_max_dd_gap", "alpha", "alpha_t", "sub_period_positive", "sub_period_n", "sub_period_worst", "post_publication_edge")}
    return res
