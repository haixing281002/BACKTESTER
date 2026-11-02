# Quant AI Researcher by Harshil Pahuja
"""STEP 7: explain every change between Clenow runs: baseline -> (a) universe v2, old start -> (b) universe v1, new start
-> final (v2, new start). Everything is read from each run's own files (out/results_raw.json, out/*.csv, holdings.csv,
trades.csv, daily_returns.csv); nothing is estimated.

    python scripts/universe_v2/step7_compare_runs.py --baseline <dir> --a <dir> --b <dir> [--final <dir>]

Writes data/processed/universe/reports/clenow_v2_comparison.md and the CSVs behind it (comparison_summary.csv,
comparison_gate_b.csv, comparison_years.csv, comparison_universe_names.csv, comparison_start_effect.csv).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import al_common as C

LABELS = {"baseline": "baseline (v1, old start)", "a": "(a) v2, old start", "b": "(b) v1, new start", "final": "final (v2, new start)"}


def load(run_dir: str) -> dict:
    with open(os.path.join(run_dir, "out", "results_raw.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    perf = {r["name"]: r for r in raw["performance"]}
    strat = next(v for k, v in perf.items() if k.startswith("Stocks on the Move"))
    nifty = next(v for k, v in perf.items() if k.startswith("NIFTY 500 (price"))
    crit = {c["name"]: c for c in raw["gate_b"]["criteria"]}
    years = pd.read_csv(os.path.join(run_dir, "out", "calendar_year_returns.csv"))
    cap = pd.read_csv(os.path.join(run_dir, "out", "cap_mix_by_year.csv"))
    hold = pd.read_csv(os.path.join(run_dir, "holdings.csv"), parse_dates=["date"])
    trades = pd.read_csv(os.path.join(run_dir, "trades.csv"), parse_dates=["date", "signal_date"])
    dr = pd.read_csv(os.path.join(run_dir, "daily_returns.csv"), parse_dates=["date"])
    contrib = pd.read_csv(os.path.join(run_dir, "out", "contributors.csv"))
    uni = raw.get("universe") or {}
    raw.setdefault("first_fill", str(trades["date"].min().date()))       # runs before 2026-11-02 did not record it
    ff = raw.get("factor_fingerprint") or {}
    ffn = raw.get("factor_fingerprint_no_filter_variant") or {}
    return {"dir": run_dir, "raw": raw, "strat": strat, "nifty": nifty, "crit": crit, "years": years, "cap": cap, "hold": hold,
            "trades": trades, "dr": dr, "contrib": contrib, "uni": uni, "ff": ff, "ffn": ffn,
            "summary": {
                "run": os.path.basename(run_dir.rstrip("/\\")), "first_signal": raw["sched_first"], "first_fill": raw.get("first_fill", ""),
                "universe": uni.get("source", "holdings_workbook (pre-field)"), "cagr": strat["cagr"], "nifty_cagr": nifty["cagr"],
                "excess_cagr": strat["cagr"] - nifty["cagr"], "vol": strat["vol"], "sharpe": strat["sharpe_card"], "max_dd": strat["max_dd"],
                "nifty_max_dd": nifty["max_dd"], "turnover_2way": raw["turnover_two_way_annual"], "names_mean": raw["holdings_check"]["mean_names"],
                "names_ever": raw["holdings_check"]["names_ever_held"], "cash_mean": raw["cash"]["mean_share"],
                "deflated_sharpe": raw["deflated_sharpe"].get("deflated_sharpe_prob"),
                "worst_wf_sharpe": min(w["sharpe"] for w in raw["walk_forward"]),
                "paired_p_vs_nifty": raw["bootstrap"]["paired_sharpe_diff_vs_strategy"]["NIFTY 500"]["p_not_positive"],
                "alpha_t": ff.get("alpha_t_hac"), "alpha_t_no_filter": ffn.get("alpha_t_hac"), "alpha_ann": ff.get("alpha_ann"),
                "small_cap_share_mean": float(cap["small"].mean()) if "small" in cap else None,
                "gate_b_pass": sum(1 for c in crit.values() if c.get("passed")), "gate_b_n": len(crit),
                "first_signal_members": uni.get("first_signal_members"), "first_signal_priced": uni.get("first_signal_priced"),
                "never_priced": len(uni.get("never_priced", [])),
            }}


def pct(x, d=1):
    return "" if x is None or pd.isna(x) else f"{x * 100:.{d}f}%"


def num(x, d=2):
    return "" if x is None or pd.isna(x) else f"{x:.{d}f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    for k in ("baseline", "a", "b", "final"):
        ap.add_argument(f"--{k}")
    args = ap.parse_args()
    runs = {k: load(getattr(args, k)) for k in ("baseline", "a", "b", "final") if getattr(args, k)}
    keys = list(runs)
    S = pd.DataFrame([dict(label=LABELS[k], **runs[k]["summary"]) for k in keys])
    C.write_csv(S, os.path.join(C.REPORTS, "comparison_summary.csv"))

    # ---- Gate B, every criterion per run
    names = list(runs[keys[0]]["crit"])
    g = pd.DataFrame([{"criterion": n, **{LABELS[k]: f"{runs[k]['crit'][n].get('value')} ({'PASS' if runs[k]['crit'][n].get('passed') else 'FAIL'})"
                                           for k in keys}, "threshold": runs[keys[0]]["crit"][n].get("threshold")} for n in names])
    C.write_csv(g, os.path.join(C.REPORTS, "comparison_gate_b.csv"))

    # ---- year by year
    Y = None
    for k in keys:
        y = runs[k]["years"][["year", "strategy", "nifty500"]].rename(columns={"strategy": f"strategy {k}", "nifty500": f"nifty {k}"})
        Y = y if Y is None else Y.merge(y, on="year", how="outer")
    Y["highlight"] = Y["year"].map(lambda y: "2014: first year, earliest universe" if y == 2014 else ("2017-2018: Alpha Lab gap" if y in (2017, 2018) else ""))
    C.write_csv(Y, os.path.join(C.REPORTS, "comparison_years.csv"))

    # ---- universe attribution: names and trades the universe change added or removed
    pairs = [(p, q) for p, q in (("baseline", "a"), ("b", "final")) if p in runs and q in runs]
    attr_rows, trade_rows = [], []
    for p, q in pairs:
        hp, hq = runs[p]["hold"], runs[q]["hold"]
        only_q, only_p = set(hq["symbol"]) - set(hp["symbol"]), set(hp["symbol"]) - set(hq["symbol"])
        cq = runs[q]["contrib"].set_index("symbol") if "symbol" in runs[q]["contrib"] else pd.DataFrame()
        cp = runs[p]["contrib"].set_index("symbol") if "symbol" in runs[p]["contrib"] else pd.DataFrame()
        pnl_col = "pnl_rs" if "pnl_rs" in cq.columns else None
        for s in sorted(only_q):
            hh = hq[hq["symbol"] == s]
            attr_rows.append({"pair": f"{LABELS[p]} -> {LABELS[q]}", "symbol": s, "side": "only in the v2 run", "first_held": hh["date"].min().date(),
                              "last_held": hh["date"].max().date(), "rebalances_held": len(hh),
                              "pnl_rs": float(cq.loc[s, pnl_col]) if pnl_col and s in cq.index else None})
        for s in sorted(only_p):
            hh = hp[hp["symbol"] == s]
            attr_rows.append({"pair": f"{LABELS[p]} -> {LABELS[q]}", "symbol": s, "side": "only in the v1 run", "first_held": hh["date"].min().date(),
                              "last_held": hh["date"].max().date(), "rebalances_held": len(hh),
                              "pnl_rs": float(cp.loc[s, pnl_col]) if pnl_col and s in cp.index else None})
        tp, tq = runs[p]["trades"], runs[q]["trades"]
        for y in sorted(set(tp["date"].dt.year) | set(tq["date"].dt.year)):
            a_, b_ = tp[tp["date"].dt.year == y], tq[tq["date"].dt.year == y]
            trade_rows.append({"pair": f"{LABELS[p]} -> {LABELS[q]}", "year": y, "trades_v1": len(a_), "trades_v2": len(b_),
                               "buys_v1": int((a_["action"] == "BUY").sum()), "buys_v2": int((b_["action"] == "BUY").sum()),
                               "names_only_v2": len(set(b_["symbol"]) - set(a_["symbol"])), "names_only_v1": len(set(a_["symbol"]) - set(b_["symbol"])),
                               "gap_years": "yes" if y in (2017, 2018) else ""})
    A = pd.DataFrame(attr_rows)
    T = pd.DataFrame(trade_rows)
    C.write_csv(A, os.path.join(C.REPORTS, "comparison_universe_names.csv"))
    C.write_csv(T, os.path.join(C.REPORTS, "comparison_universe_trades_by_year.csv"))

    # ---- start effect: the first sessions of January 2014
    st_rows = []
    for k in keys:
        d = runs[k]["dr"]
        head = d[(d["date"] >= "2014-01-01") & (d["date"] <= "2014-01-08")]
        cum_s = float((1 + head["strategy"]).prod() - 1)
        cum_b = float((1 + head["benchmark"]).prod() - 1)
        t = runs[k]["trades"]
        first = t.sort_values("date").head(1)
        st_rows.append({"run": LABELS[k], "first_signal": runs[k]["raw"]["sched_first"], "first_fill": first["date"].iloc[0].date() if len(first) else "",
                        "buys_at_first_fill": int((t["date"] == first["date"].iloc[0]).sum()) if len(first) else 0,
                        "strategy_2014-01-02_to_01-08": cum_s, "nifty_2014-01-02_to_01-08": cum_b,
                        "invested_share_first_session": float(runs[k]["hold"][runs[k]["hold"]["date"] == runs[k]["hold"]["date"].min()]["weight"].sum()) if len(runs[k]["hold"]) else None})
    ST = pd.DataFrame(st_rows)
    C.write_csv(ST, os.path.join(C.REPORTS, "comparison_start_effect.csv"))

    # ---- decomposition
    def dec(metric):
        v = {k: runs[k]["summary"][metric] for k in keys}
        out = {}
        if "baseline" in v and "a" in v:
            out["universe effect, old start (a - baseline)"] = v["a"] - v["baseline"]
        if "baseline" in v and "b" in v:
            out["start-rule effect, v1 (b - baseline)"] = v["b"] - v["baseline"]
        if "final" in v and "b" in v:
            out["universe effect, new start (final - b)"] = v["final"] - v["b"]
        if "final" in v and "a" in v:
            out["start-rule effect, v2 (final - a)"] = v["final"] - v["a"]
        if "final" in v and "baseline" in v:
            out["total (final - baseline)"] = v["final"] - v["baseline"]
        return out

    # ---- the report
    L = ["# Clenow on NIFTY 500: baseline -> universe v2 -> start rule", "", C.SIGNATURE, "",
         "Every number below is read from the run's own files; no run was edited. Runs:", ""]
    for k in keys:
        L.append(f"- {LABELS[k]}: `{runs[k]['dir']}` (first signal {runs[k]['raw']['sched_first']}, first fill {runs[k]['raw'].get('first_fill', '')}, "
                 f"universe {runs[k]['summary']['universe']})")
    L += ["", "## Headline", ""]
    head = S[["label", "cagr", "nifty_cagr", "excess_cagr", "vol", "sharpe", "max_dd", "turnover_2way", "names_mean", "cash_mean", "alpha_t", "alpha_t_no_filter",
              "deflated_sharpe", "worst_wf_sharpe", "paired_p_vs_nifty", "gate_b_pass"]].copy()
    for c in ("cagr", "nifty_cagr", "excess_cagr", "vol", "max_dd", "cash_mean"):
        head[c] = head[c].map(pct)
    for c in ("sharpe", "alpha_t", "alpha_t_no_filter"):
        head[c] = head[c].map(num)
    for c in ("deflated_sharpe", "worst_wf_sharpe", "paired_p_vs_nifty"):
        head[c] = head[c].map(lambda x: num(x, 3))
    head["turnover_2way"] = head["turnover_2way"].map(lambda x: num(x, 1))
    head["names_mean"] = head["names_mean"].map(lambda x: num(x, 1))
    L += [C.md_table(head), "", "## Decomposition", ""]
    for metric, fmt in (("cagr", pct), ("sharpe", num), ("max_dd", pct), ("excess_cagr", pct), ("turnover_2way", lambda x: num(x, 2))):
        L.append(f"**{metric}**: " + "; ".join(f"{k} = {fmt(v) if fmt is not pct else f'{v * 100:+.2f} pts'}" for k, v in dec(metric).items()))
    L += ["", "## Gate B, every criterion", "", C.md_table(g), "",
          "## Year by year (2014 and 2017-2018 highlighted)", ""]
    Yf = Y.copy()
    for c in Yf.columns:
        if c.startswith(("strategy", "nifty")):
            Yf[c] = Yf[c].map(pct)
    L += [C.md_table(Yf), ""]
    L += ["## Universe attribution", ""]
    if len(T):
        L += [C.md_table(T), ""]
    if len(A):
        for pair, grp in A.groupby("pair"):
            q = grp[grp["side"] == "only in the v2 run"]
            p = grp[grp["side"] == "only in the v1 run"]
            L.append(f"**{pair}**: {len(q)} names held only with v2 (total P&L {q['pnl_rs'].sum():,.0f} Rs where known), "
                     f"{len(p)} names held only with v1 (total P&L {p['pnl_rs'].sum():,.0f} Rs).")
            L.append("Only with v2: " + ", ".join(f"{r.symbol} ({r.first_held}..{r.last_held})" for r in q.itertuples()))
            L.append("Only with v1: " + ", ".join(f"{r.symbol} ({r.first_held}..{r.last_held})" for r in p.itertuples()))
            L.append("")
    L += ["## Start rule: the first sessions of 2014", "", C.md_table(ST.assign(**{c: ST[c].map(pct) for c in ST.columns if "2014" in c})), ""]
    L += ["## Universe-sensitive red flags, re-checked", ""]
    for k in keys:
        s = runs[k]["summary"]
        y14 = runs[k]["years"].set_index("year")
        L.append(f"- {LABELS[k]}: 2014 strategy {pct(y14.loc[2014, 'strategy'])} vs NIFTY {pct(y14.loc[2014, 'nifty500'])} "
                 f"(early survivorship: {s['first_signal_priced'] or '?'} of {s['first_signal_members'] or '?'} first-signal members priced, "
                 f"{s['never_priced']} names never priced); small-cap NAV share {pct(s['small_cap_share_mean'])}; "
                 f"factor alpha t {num(s['alpha_t'])} headline, {num(s['alpha_t_no_filter'])} no-filter; alpha {pct(s['alpha_ann'])} a year.")
    L += ["", "## Note for the data owner", "",
          ("The '<DATA_ROOT_ADJUSTED>' folder is empty on this machine. The unpriced names in each run's Notes are in the "
           "universe but have no Ace price for the dates they were members; price history for them is the only fix for the remaining "
           "survivorship bias. PIRAMALFIN and GUJENERGY in the lists above are the Ace master's current symbols for the DHFL and "
           "GUJGASLTD ISIN keys.")]
    with open(os.path.join(C.REPORTS, "clenow_v2_comparison.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
