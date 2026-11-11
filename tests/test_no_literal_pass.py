# Quant AI Researcher
"""No check may report a hard-coded pass. A check whose result is the literal True cannot fail, so it proves nothing
and makes a page of green look checked. Two did: the run script's 'every holding was a member' and the spec audit's
'cash share reported'. This test reads the source of everything that produces check results and fails on any pass
that is a literal True instead of a computed value."""
import ast
import glob
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_SOURCES = (["lightyear/spec_audit.py", "lightyear/contract.py", "ros/governance/gates.py", "run_pipeline.py"]
                 + sorted(os.path.relpath(p, REPO).replace(os.sep, "/")
                          for p in glob.glob(os.path.join(REPO, "scripts", "*_india_backtest.py"))))


# Literal passes that CAN fail: each sits on the success branch of an if/raise whose other branch records the failure.
# Every entry needs its reason. A check that can never fail does not belong here; it belongs in the report.
ALLOWED = {
    ("ros/governance/gates.py", "universe translation recorded"): "else of the branch that records it as missing",
    ("ros/governance/gates.py", "securities selection stated"): "else of the branch that records it as missing",
    ("ros/governance/gates.py", "convertibility assessed"): "else of the branch that records it as missing",
    ("ros/governance/gates.py", "leg structure stated"):
        "CANNOT FAIL (long_only_adaptation optional since the 2026-09-28 mandate); left for the operator's ruling",
    ("lightyear/contract.py", "other costings labelled appendix"): "reached only after the loop above raised on any mismatch",
}


def _name(call) -> str:
    a = call.args[0] if getattr(call, "args", None) else None
    return a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else ""


def _true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _literal_passes(path: str) -> list[str]:
    with open(os.path.join(REPO, path), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in ("passed", "pass", "ok") and _true(v):
                    label = next((vv.value for kk, vv in zip(node.keys, node.values) if isinstance(kk, ast.Constant)
                                  and kk.value in ("check", "item", "name") and isinstance(vv, ast.Constant)), "")
                    if (path, label) not in ALLOWED:
                        out.append(f"{path}:{node.lineno} {{'{k.value}': True}} {label}")
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if (name in ("add", "Criterion") and len(node.args) >= 2 and _true(node.args[1])
                    and (path, _name(node)) not in ALLOWED):
                out.append(f"{path}:{node.lineno} {name}('{_name(node)}', True, ...)")
            for kw in node.keywords:
                if kw.arg in ("passed", "ok") and _true(kw.value):
                    out.append(f"{path}:{node.lineno} {name}({kw.arg}=True)")
    return out


@pytest.mark.parametrize("path", CHECK_SOURCES)
def test_no_check_reports_a_literal_pass(path):
    found = _literal_passes(path)
    assert not found, "a check returns a hard-coded pass:\n" + "\n".join(found)


def test_the_scan_would_catch_one(tmp_path):
    """Guard the guard: a planted literal pass in each shape is found."""
    planted = tmp_path / "planted.py"
    planted.write_text('checks.append({"check": "x", "passed": True})\nadd("y", True, "z")\nCriterion("w", True)\n'
                       'Criterion("v", passed=True)\n', encoding="utf-8")
    rel = os.path.relpath(planted, REPO)
    assert len(_literal_passes(rel)) == 4
