# Quant AI Researcher
"""Gate B v2: hard blocks, an evidence scorecard, and a status of PASS or FAIL.

Code computes and reports. The decision stays PENDING until a named human records one, and nothing here can set it.
Hard blocks that could be run must all pass. The scorecard feeds the human and blocks nothing by itself. A test with
nothing to run on (no book, no AUM, no mandate limits) is shown as not run and listed beside the status: it never counts
as a pass, and it does not hold the gate up (operator's ruling, 2026-11-05).

Thresholds come only from config/gate_thresholds.yaml.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

GATE_V2 = "v2"
PASS, FAIL = "PASS", "FAIL"
GREEN, AMBER, RED, NOT_RUN = "green", "amber", "red", "not run"


@dataclass
class Row:
    key: str
    name: str
    status: str
    value: Any = None
    threshold: Any = None
    evidence: str = ""


@dataclass
class GateV2Result:
    status: str
    hard_blocks: list[Row] = field(default_factory=list)
    scorecard: list[Row] = field(default_factory=list)
    tests_not_run: list[str] = field(default_factory=list)
    gate_version: str = GATE_V2
    thresholds_status: str = ""
    decision: str = "PENDING"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _higher(v, green, amber):
    if v is None or math.isnan(v):
        return NOT_RUN
    return GREEN if v >= green else (AMBER if v >= amber else RED)


def _lower(v, green, amber):
    if v is None or math.isnan(v):
        return NOT_RUN
    return GREEN if v <= green else (AMBER if v <= amber else RED)


def mandate_row(observed: dict[str, float] | None, limits: dict[str, Any], overrides: list[dict[str, Any]] | None = None) -> Row:
    """Observed positions against config/mandate.yaml. A card cannot change the limits; each override needs a named person
    and a timestamp, and is shown as evidence."""
    missing = [k for k in ("long_only", "max_cash_share", "max_single_weight") if limits.get(k) is None]
    if missing:
        return Row("mandate", "Implementable within the fund's mandate", NOT_RUN, evidence=f"config/mandate.yaml has no value for: {', '.join(missing)}")
    if not observed:
        return Row("mandate", "Implementable within the fund's mandate", NOT_RUN, evidence="the run supplied no positions to check")
    breaches = {}
    if observed["max_cash_share"] > limits["max_cash_share"] + 1e-9:
        breaches["max_cash_share"] = f"cash reached {observed['max_cash_share']:.1%}, limit {limits['max_cash_share']:.1%}"
    if observed["max_single_weight"] > limits["max_single_weight"] + 1e-9:
        breaches["max_single_weight"] = f"a weight reached {observed['max_single_weight']:.1%}, limit {limits['max_single_weight']:.1%}"
    if limits["long_only"] and observed["min_weight"] < -1e-9:
        breaches["long_only"] = "negative weights under a long-only mandate"
    approved = {o.get("limit"): o for o in (overrides or []) if o.get("approved_by") and o.get("approved_at")}
    left = {k: v for k, v in breaches.items() if k not in approved}
    notes = list(left.values()) + [f"OVERRIDDEN by {approved[k]['approved_by']} at {approved[k]['approved_at']}: {breaches[k]}" for k in breaches if k in approved]
    return Row("mandate", "Implementable within the fund's mandate", FAIL if left else PASS, evidence="; ".join(notes) or "no breaches")


def capacity_row(cap: dict[str, Any] | None, limit: float | None) -> Row:
    if limit is None:
        return Row("capacity", "Capacity at the fund's AUM", NOT_RUN, evidence="config/gate_thresholds.yaml has no capacity limit")
    if not cap or cap.get("status") != "computed":
        unit = (cap or {}).get("unit") or {}
        at = unit.get("capital_at_limit_cr")
        more = (f"; per Rs 1 crore the 95th-percentile trade is {unit['per_cr_p95']:.4%} of 20-day traded value, so it reaches "
                f"the {limit:.0%} limit at about Rs {at:,.0f} crore" if at is not None and at == at else "")
        return Row("capacity", "Capacity at the fund's AUM", NOT_RUN, threshold=limit,
                   evidence=f"{(cap or {}).get('why', 'not computed')}{more}")
    names = cap.get("names_above_limit") or []
    return Row("capacity", "Capacity at the fund's AUM", PASS if cap["p95"] <= limit else FAIL, value=cap["p95"], threshold=limit,
               evidence=f"95th percentile of trade size / 20-day traded value; {len(names)} name(s) above the limit, {cap.get('n_no_adv', 0)} with no traded value")


def integrity_row(checks: list[dict[str, Any]] | None, reconciles: bool | None, coverage: float | None, unpriced: list[str] | None, min_coverage: float) -> Row:
    if checks is None or reconciles is None or coverage is None:
        return Row("data_integrity", "Data integrity", NOT_RUN, threshold=min_coverage, evidence="the run did not supply look-ahead checks, accounting reconciliation and priced-member coverage")
    failed = [str(c.get("check")) for c in checks if not c.get("passed")]
    ok = not failed and reconciles and coverage >= min_coverage
    bits = [f"priced-member coverage {coverage:.1%}"]
    if failed:
        bits.append("failed: " + ", ".join(failed))
    if not reconciles:
        bits.append("accounting does not reconcile")
    if unpriced:
        bits.append(f"{len(unpriced)} unpriced: " + ", ".join(unpriced))
    return Row("data_integrity", "Data integrity", PASS if ok else FAIL, value=coverage, threshold=min_coverage, evidence="; ".join(bits))


def _boot_evidence(e: dict) -> str:
    s = "share of draws where the Sharpe gap to the benchmark is at or below zero"
    if e.get("bootstrap_block") is not None:
        s += f"; mean block {e['bootstrap_block']:.1f} days ({e.get('bootstrap_block_method', 'automatic')})"
    sens = e.get("bootstrap_sensitivity") or {}
    if sens:
        s += "; at fixed blocks " + ", ".join(f"{k} days p {v:.3f}" for k, v in sens.items()) + " (reported, not judged)"
    return s


def evaluate(e: dict[str, Any], th: dict[str, Any], mandate_limits: dict[str, Any], overrides: list[dict[str, Any]] | None = None) -> GateV2Result:
    """`e` is the evidence (ros.validation.gate_evidence), `th` the loaded thresholds file. Every number is at the cost on the run's card."""
    h: list[Row] = [
        mandate_row(e.get("mandate_observed"), mandate_limits, overrides),
        capacity_row(e.get("capacity"), th["capacity"]["p95_adv_participation_max"]),
        integrity_row(e.get("checks"), e.get("reconciles"), e.get("priced_coverage"), e.get("unpriced"), th["data_integrity"]["min_priced_coverage"]),
    ]
    edge = e.get("net_edge")
    h.append(Row("net_edge", "Edge over the benchmark, at the card's cost", NOT_RUN if edge is None else (PASS if edge > 0 else FAIL), value=edge, threshold="> 0",
                 evidence="CAGR at the card's cost, minus the benchmark's"))
    p = e.get("bootstrap_p")
    p_max = th["bootstrap"]["p_max"]
    h.append(Row("bootstrap", "Paired bootstrap, at the card's cost", NOT_RUN if p is None else (PASS if p <= p_max else FAIL), value=p, threshold=f"<= {p_max}",
                 evidence=_boot_evidence(e)))

    d = th["deflated_sharpe"]
    sp = th["sub_period"]
    fa = th["factor_alpha"]
    bk = th["book"]
    pp = th["post_publication"]
    alpha, t = e.get("alpha"), e.get("alpha_t")
    one_sided = None if alpha is None or t is None else (t if alpha > 0 else -abs(t))
    n_w, n_pos, worst = e.get("sub_period_n"), e.get("sub_period_positive"), e.get("sub_period_worst")
    if not n_w:
        sub = NOT_RUN
    elif n_pos / n_w >= sp["min_windows_ahead_share"] and worst >= sp["window_floor"]:
        sub = GREEN
    elif worst >= sp["window_floor_amber"]:
        sub = AMBER
    else:
        sub = RED
    post = e.get("post_publication_edge")
    s = [Row("deflated_sharpe", "Deflated Sharpe", _higher(e.get("dsr"), d["green_min"], d["amber_min"]), value=e.get("dsr"), threshold=f">= {d['green_min']}", evidence=e.get("dsr_inputs", ""))] if d.get("enabled") else []
    s += [Row("sub_period", e.get("sub_period_name", "Sub-period stability"), sub, value=worst, threshold=f"at least {sp['min_windows_ahead_share']:.0%} of windows ahead of the benchmark, none below {sp['window_floor']}",
             evidence=e.get("sub_period_evidence", "")),
         Row("factor_alpha", "Factor alpha, one-sided", _higher(one_sided, fa["t_green_min"], fa["t_amber_min"]), value=t, threshold=f"alpha > 0 and t >= {fa['t_green_min']}", evidence=e.get("alpha_evidence", "")),
         Row("book_correlation", "Correlation to the existing book", _lower(e.get("book_corr"), bk["corr_green_max"], bk["corr_amber_max"]), value=e.get("book_corr"), threshold=f"<= {bk['corr_green_max']}"),
         Row("book_ir_gain", "Gain in the book's information ratio", _higher(e.get("book_ir_gain"), bk["ir_gain_green_min"], bk["ir_gain_amber_min"]), value=e.get("book_ir_gain"), threshold=f">= {bk['ir_gain_green_min']}"),
         Row("post_publication", "Performance after publication", NOT_RUN if post is None else (GREEN if post > pp["edge_green_min"] else (AMBER if post > pp["edge_amber_min"] else RED)), value=post, threshold=f"edge > {pp['edge_green_min']}")]

    # The return-based blocks can always be run, so a PASS always rests on them.
    required = [r for r in h if r.key in ("net_edge", "bootstrap")]
    status = FAIL if any(r.status == FAIL for r in h) or any(r.status != PASS for r in required) else PASS
    not_run = [r.name for r in h + s if r.status == NOT_RUN and r.key != "post_publication"]
    return GateV2Result(status=status, hard_blocks=h, scorecard=s, tests_not_run=not_run, thresholds_status=str(th.get("status", "")))


def all_green(result: GateV2Result, ignore: tuple[str, ...] = ()) -> bool:
    """Every scorecard row that could be run is green. Used to read a calibration, never to decide anything."""
    return all(r.status in (GREEN, NOT_RUN) for r in result.scorecard if r.key not in ignore)
