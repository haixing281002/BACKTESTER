# Quant AI Researcher
"""Test-suite guard: a test may write only inside its own tmp_path.

Every test is wrapped by a fixture that lists the repository's files (size and mtime) before and after it runs and
fails the test if anything changed. Writing under outputs/ is allowed only for a test that opts in explicitly with
@pytest.mark.writes_outputs. This exists because the suite once appended entries to the real strategy library and
renamed a file under data/raw/ while it ran.
"""
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}


def _snapshot() -> dict:
    out = {}
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[os.path.relpath(p, REPO).replace(os.sep, "/")] = (st.st_size, st.st_mtime_ns)
    return out


def pytest_configure(config):
    config.addinivalue_line("markers", "writes_outputs: the test may write under outputs/ (explicit opt-in)")


@pytest.fixture(autouse=True)
def _no_writes_outside_tmp_path(request):
    before = _snapshot()
    yield
    after = _snapshot()
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    if request.node.get_closest_marker("writes_outputs"):
        changed = [p for p in changed if not p.startswith("outputs/")]
    if changed:
        pytest.fail(f"test changed {len(changed)} file(s) inside the repository (only tmp_path is allowed): "
                    f"{changed[:15]}", pytrace=False)
