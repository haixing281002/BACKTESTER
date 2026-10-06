"""Turn gate_b().to_dict() criteria into rows the page and the workbook can both show.

Each row says whether the criterion was computed at all, how its value compares with its threshold
(operator, number, |abs|), and the result:  PASS / FAIL (blocking) / FAIL (advisory) / not computed.
'Advisory' (blocking=False) criteria still have a real result when a value exists: an advisory criterion
with a number that misses its threshold is a FAIL (advisory), not "not computed".
"""
import re

NOT_COMPUTED = re.compile(r"no comparison|not computed|n/?a|none|^$", re.I)
THR = re.compile(r"^\s*(\|t\|)?\s*(<=|>=|<|>)?\s*(-?\d+(?:\.\d+)?)\s*(%)?\s*$")


def to_num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    pct = s.endswith("%")
    try:
        x = float(s.rstrip("%"))
    except ValueError:
        return None
    return x / 100 if pct else x


def parse_threshold(t):
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return None, float(t), False
    m = THR.match(str(t or ""))
    if not m:
        return None, None, False
    x = float(m.group(3)) / (100 if m.group(4) else 1)
    return m.group(2), x, bool(m.group(1))


def _cmp(v, op, thr):
    return {"<=": v <= thr, ">=": v >= thr, "<": v < thr, ">": v > thr}[op]


def rows(criteria):
    out = []
    for c in criteria or []:
        name = c.get("name", "")
        blocking = c.get("blocking", True) is not False
        v_raw, t_raw = c.get("value"), c.get("threshold")
        v = None if NOT_COMPUTED.search(str(v_raw if v_raw is not None else "")) and to_num(v_raw) is None else to_num(v_raw)
        op, thr, is_abs = parse_threshold(t_raw)
        row = {"name": name, "blocking": blocking, "value_raw": v_raw, "threshold_raw": t_raw, "value": v,
               "op": op, "threshold": thr, "abs": is_abs, "evidence": c.get("evidence", ""), "passed_reported": bool(c.get("passed"))}
        if v is None or thr is None:
            row["result"] = "PASS" if c.get("passed") else ("not computed" if v is None else ("FAIL" if blocking else "FAIL (advisory)"))
        else:
            if op is None:   # bare number: infer the direction that reproduces gate_b()'s own verdict
                op = ">=" if (v >= thr) == bool(c.get("passed")) else "<="
                row["op"] = op
            ok = _cmp(abs(v) if is_abs else v, op, thr)
            row["result"] = "PASS" if ok else ("FAIL" if blocking else "FAIL (advisory)")
            row["agrees_with_gate_b"] = ok == bool(c.get("passed"))
        out.append(row)
    return out
