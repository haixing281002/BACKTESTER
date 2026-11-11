# Quant AI Researcher
"""Phase 4: calibrate Gate B by simulation. No threshold is written anywhere by this script.

Part 1 simulates strategies with a known truth and records every statistic the gates read, one row per simulated
strategy, into docs/gate_b/calibration/sim_stats.csv.gz. Thresholds are then only comparisons on that table, so a
candidate can be tried without re-simulating (scripts/gate_v2/analyse.py). Part 2 is scripts/gate_v2/reference.py.

No named strategy is used in either part. Reproducible: one seed per (scenario, simulation), from --seed.

    python scripts/gate_v2/calibrate.py simulate --sims 1000
"""
from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from ros import config
from ros.metrics import core, legacy_v1
from ros.validation import gate_evidence as ev
from ros.validation.portfolio import factor_fingerprint
from ros.validation.research import walk_forward_split

OUT = os.path.join(REPO, *config.calibration().get("out_dir", "docs/gate_b/calibration").split("/"))
DAYS = round(12.7 * 252)
CASH_ANNUAL = float(config.calibration()["cash_annual"])    # the simulation's own cash level; returns are simulated above it
CASH = core.daily_cash(CASH_ANNUAL)
BENCH_VOL, BENCH_EXCESS = 0.16, 0.07    # benchmark: 16% vol, 7% a year above cash
STRAT_VOL, RHO = 0.17, 0.80             # the brief: about 17% vol, about 0.8 correlation to the benchmark
T_DF = 5                                # the brief: Student-t, df 4 to 5
GARCH_A, GARCH_B = 0.08, 0.90           # GARCH(1,1): a shock's weight and persistence
N_VARIANTS = 10                         # near-identical versions, to test the floor on V
LEVELS = (0.0, 0.25, 0.5, 0.75, 1.0)
SELECTION_N = (20, 100)
BOOK_IR = 0.30                          # the simulated existing book
V_FLOORS = {"1overT": 1.0 / 12.7, "0p25": 0.25, "1p0": 1.0}


def garch_t(n: int, ann_vol: float, rng: np.random.Generator) -> np.ndarray:
    """Zero-mean daily shocks with Student-t tails and clustered volatility, scaled to this annual volatility."""
    z = rng.standard_t(T_DF, size=n) * np.sqrt((T_DF - 2) / T_DF)
    uncond = (ann_vol ** 2) / core.ANN
    omega = uncond * (1 - GARCH_A - GARCH_B)
    h, out = uncond, np.empty(n)
    for i in range(n):
        out[i] = np.sqrt(h) * z[i]
        h = omega + GARCH_A * out[i] ** 2 + GARCH_B * h
    return out


def market(rng) -> np.ndarray:
    """The benchmark's return above cash."""
    return garch_t(DAYS, BENCH_VOL, rng) + BENCH_EXCESS / core.ANN


def factors(mkt_x, rng) -> pd.DataFrame:
    """Three investable long-only factor indices above cash: market exposure, a premium, and their own noise."""
    out = {}
    for name, beta, premium, idio in (("size", 1.05, 0.04, 0.10), ("momentum", 1.00, 0.05, 0.09), ("value", 0.95, 0.03, 0.08)):
        out[name] = beta * mkt_x + premium / core.ANN + garch_t(DAYS, idio, rng)
    return pd.DataFrame(out)


def strategy_x(mkt_x, excess_sharpe, rng) -> np.ndarray:
    """Return above cash with the brief's volatility and correlation, and this true information ratio to the benchmark."""
    beta = RHO * STRAT_VOL / BENCH_VOL
    idio = STRAT_VOL * np.sqrt(1 - RHO ** 2)
    te = np.sqrt(STRAT_VOL ** 2 + BENCH_VOL ** 2 - 2 * RHO * STRAT_VOL * BENCH_VOL)
    alpha = excess_sharpe * te + (1 - beta) * BENCH_EXCESS
    return beta * mkt_x + alpha / core.ANN + garch_t(DAYS, idio, rng)


def scenario_series(kind: str, level: float, n: int, rng):
    """(strategy, benchmark, factors, versions or None, n_selected_from) with returns including cash."""
    idx = pd.bdate_range("2014-01-01", periods=DAYS)
    mx = market(rng)
    fx = factors(mx, rng)
    if kind == "level":
        sx = strategy_x(mx, level, rng)
        versions = None
        n_sel = 1
    elif kind == "pure_factor":
        # zero alpha by construction: a fixed mix of the factors, plus a little tracking noise
        sx = 0.30 * mx + 0.25 * fx["size"].to_numpy() + 0.30 * fx["momentum"].to_numpy() + 0.15 * fx["value"].to_numpy() + garch_t(DAYS, 0.03, rng)
        versions = None
        n_sel = 1
    elif kind == "selection":
        # best of n strategies with no skill, chosen in-sample on Sharpe
        all_x = np.column_stack([strategy_x(mx, 0.0, rng) for _ in range(n)])
        k = int(np.argmax(all_x.mean(axis=0) / all_x.std(axis=0, ddof=1)))
        sx = all_x[:, k]
        versions = pd.DataFrame(all_x + CASH, index=idx, columns=[f"v{i}" for i in range(n)])
        n_sel = n
    else:
        raise ValueError(kind)
    r = pd.Series(sx + CASH, index=idx)
    b = pd.Series(mx + CASH, index=idx)
    fdf = pd.DataFrame(fx.to_numpy() + CASH, index=idx, columns=fx.columns)
    fdf.insert(0, "market", b)
    return r, b, fdf, versions, n_sel


def one_sim(args) -> dict:
    kind, level, n, sim, seed = args
    rng = np.random.default_rng([seed, abs(hash_key(kind, level, n)), sim])
    r, b, fdf, versions, n_sel = scenario_series(kind, level, n, rng)
    row = {"scenario": kind, "level": level, "n": n, "sim": sim}

    t0 = r.index[0] - pd.offsets.BDay(1)        # synthetic business-day calendar: its own day before the first return
    vr, vb = core.value_from_returns(r, start=t0), core.value_from_returns(b, start=t0)
    row.update(sharpe=core.sharpe(r, CASH), bench_sharpe=core.sharpe(b, CASH), edge=core.cagr(vr) - core.cagr(vb), ir=core.information_ratio(r, b))

    # one index matrix for this simulation: both gates read paired draws
    x, y = r.to_numpy(), b.to_numpy()
    idx = core.stationary_bootstrap_indices(DAYS, 2000, 21, rng)     # same stream as the approved run: v1 and the 21-day row
    d = core.sharpe_draws(x, idx, CASH) - core.sharpe_draws(y, idx, CASH)
    row["boot_p_21"] = float((d <= 0).mean())
    # v2 reads the Politis-White block; 5 and 63 days are reported beside it. Their draws use their own stream, so every
    # other statistic here is drawn exactly as in the approved calibration.
    rng_b = np.random.default_rng([seed, abs(hash_key(kind, level, n)), sim, 1])
    row["boot_block"] = core.auto_mean_block(x, y, x - y)
    # information only: the same rule on squared returns, where volatility clustering (which a Sharpe feels) shows
    row["boot_block_sq"] = core.auto_mean_block(x * x, y * y, (x - y) ** 2)
    for key, L in (("boot_p", row["boot_block"]), ("boot_p_5", 5), ("boot_p_63", 63)):
        ix = core.stationary_bootstrap_indices(DAYS, 2000, L, rng_b)
        dd = core.sharpe_draws(x, ix, CASH) - core.sharpe_draws(y, ix, CASH)
        row[key] = float((dd <= 0).mean())
    per_year = DAYS / ((r.index[-1] - r.index[0]).days / 365.25)
    row["v1_boot_p"] = legacy_v1.paired_geometric_p(x, y, CASH, idx, per_year)

    # factor alpha
    rf = pd.Series(CASH, index=r.index)
    fit = factor_fingerprint(r, fdf, rf)
    row.update(alpha=fit["alpha_ann"], alpha_t=fit["alpha_t_hac"], r2=fit["r_squared"])

    # sub-period stability, on the Sharpe gap to the benchmark, plus the same on the information ratio
    sp = ev.sub_period(r, b, CASH, n_windows=4)
    row.update(sp_n=sp["n"], sp_pos=sp["positive"], sp_worst=sp["worst"])
    w = ev.windows(r.index, 4)
    irs = [core.information_ratio(r.loc[days], b.loc[days]) for _, _, days, _ in core.split_windows(r.index, [lo for lo, _ in w] + [w[-1][1]])]
    row.update(sp_ir_pos=int(sum(i > 0 for i in irs)), sp_ir_worst=float(min(irs)))

    # deflated Sharpe, every combination of how the bar could be set
    x_ex = r - CASH
    sr_d, sk, ku = float(x_ex.mean() / x_ex.std(ddof=1)), core.skew(x_ex), core.kurtosis(x_ex)
    bench_sr = row["bench_sharpe"]

    def psr(bar):
        return core.probabilistic_sharpe(sr_d, bar / np.sqrt(core.ANN), DAYS, sk, ku)

    if versions is not None:
        active = versions.sub(b, axis=0)
        rho_active = float(active.corr().to_numpy()[np.triu_indices(n_sel, k=1)].mean())
        rho_raw = float(versions.corr().to_numpy()[np.triu_indices(n_sel, k=1)].mean())
        v_obs = float(np.var([core.sharpe(versions[c], CASH) for c in versions.columns], ddof=1))
    else:
        rho_active = rho_raw = float("nan")
        v_obs = float("nan")
    row.update(rho_active=rho_active, rho_raw=rho_raw, v_obs=v_obs)
    for fl, vf in V_FLOORS.items():
        v = max(v_obs, vf) if not np.isnan(v_obs) else vf
        for basis, rho in (("active", rho_active), ("raw", rho_raw)):
            n_eff = core.effective_trials(n_sel, rho) if n_sel > 1 else 1.0
            sr0 = core.expected_max_sharpe(n_eff, v)
            row[f"dsr_zero_{basis}_{fl}"] = psr(sr0)
            row[f"dsr_bench_{basis}_{fl}"] = psr(bench_sr + sr0)
    # N stated but near-identical versions: the same strategy with a little noise, to test the floor on V
    if kind == "level":
        noisy = np.column_stack([r.to_numpy() + garch_t(DAYS, 0.02, rng) for _ in range(N_VARIANTS)])
        v_var = float(np.var((noisy.mean(axis=0) - CASH) / noisy.std(axis=0, ddof=1) * np.sqrt(core.ANN), ddof=1))
        act = noisy - b.to_numpy()[:, None]
        rho_n = float(np.corrcoef(act, rowvar=False)[np.triu_indices(N_VARIANTS, k=1)].mean())
        row.update(n10_rho=rho_n, n10_v_obs=v_var)
        n_eff = core.effective_trials(N_VARIANTS, rho_n)
        row["dsr_n10_nofloor_bench"] = psr(bench_sr + core.expected_max_sharpe(n_eff, v_var))
        for fl, vf in V_FLOORS.items():
            row[f"dsr_n10_{fl}_bench"] = psr(bench_sr + core.expected_max_sharpe(n_eff, max(v_var, vf)))

    # the book: an independent existing strategy of the same shape, with a modest edge
    book = pd.Series(strategy_x(b.to_numpy() - CASH, BOOK_IR, rng) + CASH, index=r.index)
    row.update({k: v for k, v in ev.book_tests(r, book, b).items()})

    # gate v1, exactly as it stands: deflated Sharpe with V = 1, worst window after 5 years on the geometric Sharpe
    lo_hi = walk_forward_split(r.index)
    worst_v1 = min(legacy_v1.sharpe_geometric(vr.loc[lo:hi], r.loc[lo:hi], rf.loc[lo:hi]) for lo, hi in lo_hi)
    row["v1_oos_worst"] = float(worst_v1)
    for nv1 in (1, 13):
        row[f"v1_dsr_n{nv1}"] = psr(core.expected_max_sharpe(nv1, 1.0) if nv1 > 1 else 0.0)
    return row


def hash_key(kind: str, level: float, n: int) -> int:
    return sum(ord(c) * (i + 1) for i, c in enumerate(kind)) * 10007 + int(level * 100) * 101 + n


def simulate(sims: int, seed: int, workers: int) -> None:
    from multiprocessing import Pool
    jobs = []
    for s in range(sims):
        jobs += [("level", lv, 1, s, seed) for lv in LEVELS]
        jobs.append(("pure_factor", 0.0, 1, s, seed))
        jobs += [("selection", 0.0, n, s, seed) for n in SELECTION_N]
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    with Pool(workers) as p:
        rows = []
        for i, row in enumerate(p.imap_unordered(one_sim, jobs, chunksize=8), start=1):
            rows.append(row)
            if i % 800 == 0:
                print(f"{i}/{len(jobs)} in {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows).sort_values(["scenario", "level", "n", "sim"]).reset_index(drop=True)
    p = os.path.join(OUT, "sim_stats.csv.gz")
    df.to_csv(p, index=False, float_format="%.6g")
    print(f"{len(df)} simulated strategies -> {p} in {time.time() - t0:.0f}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["simulate"])
    ap.add_argument("--sims", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20261105)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    a = ap.parse_args()
    simulate(a.sims, a.seed, a.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
