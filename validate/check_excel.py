"""Evaluate the exported workbook's FORMULAS and compare them to the engine.

openpyxl writes formula strings; it does not compute them. So a workbook can
look perfect, open cleanly, and still be full of arithmetic that has never once
been evaluated. Shipping an "audit workbook" nobody has actually calculated is
worse than shipping none, because it invites trust it has not earned.

This module runs the formulas through a real evaluator and checks the answers
against the engine. It caught a genuine bug the first time it ran: the CAGR
formula interpolated years without brackets, so `1/{years}` expanded to
`1/(days)/365.25` -- which Excel reads left to right as `(1/days)/365.25`
rather than `1/(days/365.25)`. Every date-scaled metric came out near zero.
Reading the formula could not show that; evaluating it could.

Needs the optional `formulas` package:  python -m pip install formulas
"""
from __future__ import annotations

import warnings
from typing import Dict, Optional, Tuple

import numpy as np

# Row -> label on the Metrics sheet, in the order write_workbook lays them out.
METRIC_ROWS = {
    2: "final_nav", 3: "cagr", 4: "ann_vol", 5: "max_dd", 6: "cash_cagr",
    7: "sharpe_geometric", 8: "sharpe_conventional", 9: "total_cost",
    10: "turnover", 11: "n_rebalances",
}
MAX_DIFF_ROW = 13


def evaluate(path: str) -> Dict[str, float]:
    """Return the Metrics sheet as {label: computed value}."""
    import formulas                                   # optional dependency

    warnings.filterwarnings("ignore")
    sol = formulas.ExcelModel().loads(path).finish().calculate()

    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    out: Dict[str, float] = {}
    for row, label in list(METRIC_ROWS.items()) + [(MAX_DIFF_ROW, "max_nav_diff")]:
        cell = sol.get(f"'[{base}]METRICS'!B{row}")
        if cell is None:
            continue
        try:
            out[label] = float(np.asarray(cell.value).ravel()[0])
        except (TypeError, ValueError):
            continue
    return out


def compare(path: str, engine: Dict[str, float],
            tol: float = 1e-9) -> Tuple[bool, list]:
    """Compare evaluated Excel formulas against the engine's own numbers.

    Returns (all_ok, rows) where each row is (label, excel, engine, diff, ok).
    """
    got = evaluate(path)
    rows = []
    ok_all = True
    for label, eng_val in engine.items():
        if label not in got:
            continue
        diff = abs(got[label] - float(eng_val))
        ok = diff <= tol
        ok_all &= ok
        rows.append((label, got[label], float(eng_val), diff, ok))
    if "max_nav_diff" in got:
        ok = abs(got["max_nav_diff"]) <= 1e-8
        ok_all &= ok
        rows.append(("max_nav_diff (in-sheet)", got["max_nav_diff"], 0.0,
                     abs(got["max_nav_diff"]), ok))
    return ok_all, rows


def available() -> Optional[str]:
    """None if the evaluator is installed, otherwise why it is not."""
    try:
        import formulas  # noqa: F401
        return None
    except Exception as e:                            # noqa: BLE001
        return f"{type(e).__name__}: {e}"
