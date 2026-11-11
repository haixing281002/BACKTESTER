# Quant AI Researcher
"""A failure is logged and counted, or it stops the run; it is never swallowed (checkup 2026-11-06, Wave 2 item 10)."""
import logging
import os
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.cards.schema import load_card
from ros.engine import templates
from ros.governance import gates

CARD = "examples/cards/devanathan_2026_india_factor_adaptation.yaml"


def test_gate_a_fails_loudly_when_the_india_requirements_cannot_be_derived(monkeypatch):
    import ros.india_requirements as ir
    monkeypatch.setattr(ir, "derive", lambda card: (_ for _ in ()).throw(RuntimeError("derive broke")))
    with pytest.raises(RuntimeError, match="derive broke"):
        gates._india_for(load_card(CARD))


def test_completeness_does_not_quietly_skip_the_india_checks(monkeypatch):
    import ros.india_requirements as ir
    from ros.cards import completeness
    monkeypatch.setattr(ir, "derive", lambda card: (_ for _ in ()).throw(RuntimeError("derive broke")))
    with pytest.raises(RuntimeError, match="derive broke"):
        completeness.assess(load_card(CARD))


def test_a_min_variance_solver_failure_is_logged_and_counted(monkeypatch, caplog):
    cp = pytest.importorskip("cvxpy")
    alloc = templates.build_allocator("min_variance", ["a", "b"]) if hasattr(templates, "build_allocator") else None
    if alloc is None:
        pytest.skip("no build_allocator")

    class Ctx:
        cov = np.eye(2)
        current_weights = np.array([0.5, 0.5])

    monkeypatch.setattr(cp.Problem, "solve", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("solver down")))
    with caplog.at_level(logging.WARNING):
        w = alloc.target_weights(Ctx())
    assert np.allclose(w, [0.5, 0.5])
    assert alloc.diagnostics()["solver_failures"] == 1
    assert "solver failed" in caplog.text


def test_a_page_whose_tables_cannot_be_read_is_recorded_not_dropped(monkeypatch):
    import pdfplumber.page

    from ros.cards.extract import extract_document
    monkeypatch.setattr(pdfplumber.page.Page, "extract_tables",
                        lambda self, *a, **k: (_ for _ in ()).throw(ValueError("bad table")))
    doc = extract_document(os.path.join(REPO, "tests", "fixtures", "synthetic_paper.pdf"))
    assert doc.pages[0].table_error.startswith("ValueError")
    assert any("Tables could not be read" in w for w in doc.quality.warnings)
