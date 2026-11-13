# Quant AI Researcher
"""EXPERIMENT: score candidate Gate B tests on one good candidate and on series that should fail.

Reads research/gate_b_tests/config.yaml (pass marks fixed before the run). Writes docs/gate_b/experiment_tests/:
scores.csv (one row per series and test) and summary.csv (one row per test). Changes nothing the gate reads.

    python scripts/gate_v2/experiment_tests.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import yaml
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import reference as ref  # noqa: E402  the random-book builder of the gate calibration (scripts/gate_v2/reference.py)

from ros import config  # noqa: E402
from ros.metrics import core, qi, se  # noqa: E402
from ros.validation import gate_evidence as ev  # noqa: E402
from ros.validation.portfolio import factor_fingerprint  # noqa: E402

CFG = yaml.safe_load(open(os.path.join(REPO, "research", "gate_b_tests", "config.yaml"), encoding="utf-8"))
OUT = os.path.join(REPO, "docs", "gate_b", "experiment_tests")
HURDLE_A = config.hurdle_annual()
HURDLE_D = config.hurdle_daily()
HURDLE_M = (1 + HURDLE_A) ** (1 / 12) - 1
N_BOOT, SEED = int(CFG["n_boot"]), int(CFG["boot_seed"])


def score(r: pd.Series, b: pd.Series, r_cost: pd.Series | None) -> dict[str, float]:
    """Every candidate statistic for one daily return series against the benchmark. `r_cost` is the same series at the
    higher round-trip cost (None when it cannot be built)."""
    df = pd.concat([r, b], axis=1).dropna()
    x, y = df.iloc[:, 0].to_numpy(dtype=float), df.iloc[:, 1].to_numpy(dtype=float)
    n, out = len(x), {}
    gap = x - y
    same = bool(np.allclose(gap, 0.0))
    # 1. the current gate test, exactly as the gate runs it
    out["boot_daily"] = ev.paired_bootstrap(r, b, HURDLE_D, n_boot=N_BOOT, seed=SEED, sensitivity=())["p"]
    # 6. worst drawdown shallower than the index, on the same paired draws
    block = core.auto_mean_block(x, y, gap)
    ix = core.stationary_bootstrap_indices(n, N_BOOT, block, np.random.default_rng(SEED))
    out["dd_shallower"] = float((core.max_drawdown_draws(x, ix) < core.max_drawdown_draws(y, ix)).mean())
    # 3. probabilistic Sharpe against the benchmark's Sharpe (daily, over the risk-free rate)
    ex, eb = x - HURDLE_D, y - HURDLE_D
    sr, bar = ex.mean() / ex.std(ddof=1), eb.mean() / eb.std(ddof=1)
    out["psr"] = core.probabilistic_sharpe(float(sr), float(bar), n, float(stats.skew(ex)), float(stats.kurtosis(ex, fisher=False)))
    # 4. alpha against the index alone, with an intercept, HAC t
    fit = {"error": "the series is the benchmark"} if same else factor_fingerprint(df.iloc[:, 0], df.iloc[:, [1]].rename(columns={df.columns[1]: "market"}), pd.Series(HURDLE_D, index=df.index))
    out["capm_alpha_t"] = float("nan") if "error" in fit else float(fit["alpha_t_hac"])
    # 5. active return t-stat
    years = n / 252.0
    out["active_t"] = 0.0 if same else float(core.information_ratio(df.iloc[:, 0], df.iloc[:, 1]) * np.sqrt(years))
    # monthly series: calendar months compounded from the daily returns
    ms, mb = se.monthly_returns(df.iloc[:, 0]).to_numpy(), se.monthly_returns(df.iloc[:, 1]).to_numpy()
    im = core.stationary_bootstrap_indices(len(ms), N_BOOT, float(CFG["monthly_block"]), np.random.default_rng(SEED))
    # 2. paired bootstrap on monthly Sharpe
    d = core.sharpe_draws(ms, im, HURDLE_M) - core.sharpe_draws(mb, im, HURDLE_M)
    d = d[np.isfinite(d)]
    out["boot_monthly"] = float((d <= 0).mean())
    # 7. upside capture above downside capture, share of monthly draws
    S, B = ms[im], mb[im]
    up, dn = B >= 0, B < 0
    with np.errstate(divide="ignore", invalid="ignore"):
        uc = (np.where(up, S, 0).sum(1) / up.sum(1)) / (np.where(up, B, 0).sum(1) / up.sum(1))
        dc = (np.where(dn, S, 0).sum(1) / dn.sum(1)) / (np.where(dn, B, 0).sum(1) / dn.sum(1))
    ok = np.isfinite(uc) & np.isfinite(dc)
    out["capture"] = 0.0 if same else float((uc[ok] > dc[ok]).mean())
    # 8. rolling 3-year alpha positive
    ro = qi.rolling(ms, mb, 36, HURDLE_A)
    out["roll3y"] = float("nan") if ro is None else (0.0 if same else float(ro["positive_alpha_share"]))
    # 9. edge left at the higher cost
    t0 = df.index[0] - pd.Timedelta(days=1)
    out["edge_at_cost"] = float("nan") if r_cost is None else float(core.cagr_from_returns(r_cost.reindex(df.index).fillna(0.0), t0) - core.cagr_from_returns(df.iloc[:, 1], t0))
    out["edge"] = float(core.cagr_from_returns(df.iloc[:, 0], t0) - core.cagr_from_returns(df.iloc[:, 1], t0))
    return out


def passed(key: str, v: float) -> bool | None:
    t = CFG["tests"][key]
    if v != v:
        return None
    return bool(v <= t["mark"]) if t["rule"].startswith("p <=") else (bool(v > t["mark"]) if ">=" not in t["rule"] else bool(v >= t["mark"]))


def main() -> int:
    rd = os.path.join(REPO, *CFG["run_dir"].split("/"))
    dr = pd.read_csv(os.path.join(rd, "daily_returns.csv"), parse_dates=["date"]).set_index("date")
    b = dr["benchmark"].fillna(0.0)
    hi = float(CFG["high_cost_bp"])
    rows = []

    def add(group, name, r, bench, r_cost):
        s = score(r, bench, r_cost)
        for k in CFG["tests"]:
            rows.append({"group": group, "series": name, "test": k, "value": s[k], "pass": passed(k, s[k]), "edge": s["edge"]})
        print(f"{group:10s} {name[:50]:50s} " + " ".join(f"{k}={s[k]:.3f}" for k in CFG["tests"]), flush=True)

    # the good candidate: its own daily returns, and the same trades at the higher cost
    trades = pd.read_csv(os.path.join(rd, "trades.csv"))
    turn = core.two_way_turnover_from_trades(trades, dr.index)
    add("candidate", "Clenow run", dr["strategy"].fillna(0.0), b, core.returns_at_cost(dr["strategy"].fillna(0.0), turn, hi, 0.0))
    # its comparators (no trades on file for them, so no higher-cost series)
    cmp = pd.read_csv(os.path.join(rd, "comparators.csv"), parse_dates=["date"]).set_index("date")
    for c in cmp.columns:
        add("comparator", c, cmp[c].fillna(0.0), b, None)
    add("should fail", "NIFTY 500 itself", b, b, b)
    # reference books on the same universe and calendar, from Ace prices
    rets, elig, _idx = ref.load()
    bench = b.reindex(rets.index).fillna(0.0)
    every = lambda names: names   # noqa: E731
    add("should fail", "Equal-weight NIFTY 500 members", ref.book_returns(rets, elig, 0.0, every), bench, ref.book_returns(rets, elig, hi, every))
    base = int(CFG["random_seed_base"])
    for k in range(int(CFG["random_books"])):
        # one generator per book; the same seed replays the same monthly picks for the higher-cost copy
        def pick(names, rng):
            return rng.choice(names, size=min(30, len(names)), replace=False)

        r0 = ref.book_returns(rets, elig, 0.0, lambda names, rng=np.random.default_rng([base, k]): pick(names, rng))
        r1 = ref.book_returns(rets, elig, hi, lambda names, rng=np.random.default_rng([base, k]): pick(names, rng))
        add("random", f"Random 30 #{k}", r0, bench, r1)
    os.makedirs(OUT, exist_ok=True)
    sc = pd.DataFrame(rows)
    sc.to_csv(os.path.join(OUT, "scores.csv"), index=False, float_format="%.6g")
    summ = []
    for k, t in CFG["tests"].items():
        g = sc[sc["test"] == k]
        one = lambda name: g[g["series"] == name].iloc[0]   # noqa: E731
        rnd = g[g["group"] == "random"]
        rate = float(rnd["pass"].fillna(False).astype(bool).mean())
        clenow, idx, ew = one("Clenow run"), one("NIFTY 500 itself"), one("Equal-weight NIFTY 500 members")
        keep = bool(clenow["pass"]) and not bool(idx["pass"]) and not bool(ew["pass"]) and rate <= 0.05
        summ.append({"test": k, "label": t["label"], "pass_mark": f"{t['rule'].replace('mark', str(t['mark']))}", "clenow_value": clenow["value"], "clenow_pass": clenow["pass"],
                     "index_pass": idx["pass"], "equal_weight_value": ew["value"], "equal_weight_pass": ew["pass"],
                     "comparators_passing": int(g[g["group"] == "comparator"]["pass"].fillna(False).astype(bool).sum()), "comparators": int((g["group"] == "comparator").sum()),
                     "random_pass_rate": rate, "random_books": len(rnd), "random_median": float(rnd["value"].median()),
                     "verdict": "keep" if keep else ("drop: passes too many random books" if rate > 0.10 else ("fails the candidate" if not bool(clenow["pass"]) else "borderline"))})
    pd.DataFrame(summ).to_csv(os.path.join(OUT, "summary.csv"), index=False, float_format="%.6g")
    print(pd.DataFrame(summ).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
