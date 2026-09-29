"""The "agents get better with time" loop: StrategyLibrary.relevant_precedent()
(the read side), ros/agents/analysts.py's _precedent_block() (how it reaches a
prompt), and AgenticPipeline's deterministic stage-notes extraction + the
AGENTIC_DRAFT write-back (the write side) that actually closes the loop.

Nothing here tests prose quality -- these are the same SAFETY-property tests
as test_agents.py: is the extraction actually deterministic (no extra model
call), does precedent actually reach the next run, and does the write-back
stay clearly separate from a real governed Step 08 verdict.
"""
import json
from datetime import datetime, timezone

import pytest

from ros.agents import schemas as S
from ros.agents.analysts import _precedent_block
from ros.agents.orchestrator import AgenticPipeline
from ros.governance.library import LibraryEntry, StrategyLibrary, make_entry_id

FIX = "ros/agents/fixtures/devanathan_2026.json"


def _fixtures():
    return json.load(open(FIX, encoding="utf-8"))


def _entry(lib: StrategyLibrary, card_id: str, role: str, notes, outcome="PROMOTED",
          created_utc=None, fingerprint=None) -> str:
    eid = make_entry_id(card_id, f"fp_{card_id}")
    e = LibraryEntry(
        entry_id=eid, card_id=card_id, mode="adaptation",
        created_utc=created_utc or datetime.now(timezone.utc).isoformat(),
        card_fingerprint=f"fp_{card_id}", outcome=outcome,
        factor_fingerprint=fingerprint or {},
        stage_notes={role: notes})
    lib.write(e)
    return eid


# ---------------------------------------------------------------------------
# Read side: StrategyLibrary.relevant_precedent()
# ---------------------------------------------------------------------------
def test_relevant_precedent_falls_back_to_most_recent_without_a_fingerprint(tmp_path):
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "paper_a", "card_drafter", ["older note"],
          created_utc="2024-01-01T00:00:00+00:00")
    _entry(lib, "paper_b", "card_drafter", ["newer note"],
          created_utc="2025-01-01T00:00:00+00:00")

    hits = lib.relevant_precedent("card_drafter")
    assert [h["notes"] for h in hits] == [["newer note"], ["older note"]]


def test_relevant_precedent_only_returns_entries_carrying_that_roles_notes(tmp_path):
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "paper_a", "card_drafter", ["a card-drafter note"])
    _entry(lib, "paper_b", "results_critic", ["a results-critic note"])

    hits = lib.relevant_precedent("card_drafter")
    assert len(hits) == 1
    assert hits[0]["card_id"] == "paper_a"


def test_relevant_precedent_respects_k_and_card_id_prefix(tmp_path):
    lib = StrategyLibrary(str(tmp_path))
    for i in range(3):
        _entry(lib, f"momentum_family_{i}", "card_drafter", [f"note {i}"])
    _entry(lib, "unrelated_paper", "card_drafter", ["unrelated note"])

    hits = lib.relevant_precedent("card_drafter", card_id_prefix="momentum_family_", k=2)
    assert len(hits) == 2
    assert all(h["card_id"].startswith("momentum_family_") for h in hits)


def test_relevant_precedent_ranks_by_cosine_similarity_when_a_fingerprint_is_given(tmp_path):
    lib = StrategyLibrary(str(tmp_path))
    close = {"mkt": 1.0, "size": 0.9, "value": 0.1}
    far = {"mkt": 0.1, "size": -0.9, "value": 1.0}
    _entry(lib, "close_paper", "card_drafter", ["close note"], fingerprint=close)
    _entry(lib, "far_paper", "card_drafter", ["far note"], fingerprint=far)

    hits = lib.relevant_precedent("card_drafter", factor_fingerprint=close, threshold=0.5)
    assert [h["card_id"] for h in hits] == ["close_paper"]


def test_relevant_precedent_is_empty_when_nothing_qualifies(tmp_path):
    lib = StrategyLibrary(str(tmp_path))
    assert lib.relevant_precedent("card_drafter") == []


# ---------------------------------------------------------------------------
# How precedent reaches a prompt: analysts._precedent_block()
# ---------------------------------------------------------------------------
def test_precedent_block_is_none_for_empty_or_missing_precedent():
    assert _precedent_block(None) is None
    assert _precedent_block([]) is None
    assert _precedent_block([{"card_id": "x", "outcome": "PROMOTED", "notes": []}]) is None


def test_precedent_block_names_the_source_card_and_outcome_for_each_note():
    block = _precedent_block([
        {"card_id": "momentum_paper", "outcome": "REJECTED",
         "notes": ["forgot a liquidity floor"]},
    ])
    assert block is not None
    assert "momentum_paper" in block["text"]
    assert "REJECTED" in block["text"]
    assert "forgot a liquidity floor" in block["text"]
    assert "not a rule" in block["text"], "must be framed as context, never as a decision"


# ---------------------------------------------------------------------------
# Write side: AgenticPipeline extracts notes deterministically and banks them
# ---------------------------------------------------------------------------
def test_run_interpretation_extracts_stage_notes_without_any_extra_model_call(tmp_path):
    fx = _fixtures()
    lib = StrategyLibrary(str(tmp_path / "library"))
    pipe = AgenticPipeline(mode="replay", fixtures=fx, library=lib)
    res = pipe.run_interpretation(
        "docs/devanathan_2026_simple_dynamic_sbg.pdf", "adaptation", str(tmp_path / "cards"))

    # card_drafter: derived from the critique's own high-materiality findings
    # and missed_by_first_pass -- both present in the fixture.
    assert any("metrics.sharpe" in n for n in res.stage_notes.get("card_drafter", []))

    # data_mapper: exactly the two "proxy" matches in the fixture carry a
    # proxy_risk; the "none" matches must NOT show up as notes.
    dm_notes = res.stage_notes.get("data_mapper", [])
    assert len(dm_notes) == 2
    assert any("DFF_fed_funds" in n for n in dm_notes)
    assert not any("SPY_adj_close" in n for n in dm_notes)

    # template_matcher: fixture matched a real template, not null.
    assert any("markowitz_l1" in n for n in res.stage_notes.get("template_matcher", []))

    # No LLM call was made for this extraction -- ReplayTransport only ever
    # serves the fixed fixture keys, so if extraction had triggered an extra
    # call for an unknown agent name it would have raised KeyError already.
    assert res.ledger is not None


def test_run_interpretation_banks_a_preliminary_agentic_draft_entry(tmp_path):
    fx = _fixtures()
    lib = StrategyLibrary(str(tmp_path / "library"))
    pipe = AgenticPipeline(mode="replay", fixtures=fx, library=lib)
    res = pipe.run_interpretation(
        "docs/devanathan_2026_simple_dynamic_sbg.pdf", "adaptation", str(tmp_path / "cards"))

    assert res.card_valid, "fixture card must validate for this test to mean anything"
    assert res.library_entry_path is not None

    written = json.load(open(res.library_entry_path, encoding="utf-8"))
    assert written["outcome"] == "AGENTIC_DRAFT", (
        "must be distinguishable from a real Step 08 verdict, never mistaken for one")
    assert written["stage_notes"] == res.stage_notes
    assert written["gates"] == [], "no gate has run yet -- this entry predates Gate A"


def test_a_second_run_on_a_similar_paper_receives_the_first_runs_precedent(tmp_path):
    """The actual closed loop: run once, then confirm the NEXT run's
    card_drafter precedent fetch surfaces what the first run's critique
    caught -- proving the write-back a run banks is the same thing a later
    run's agents are handed, not two disconnected halves."""
    fx = _fixtures()
    lib = StrategyLibrary(str(tmp_path / "library"))
    pipe = AgenticPipeline(mode="replay", fixtures=fx, library=lib)
    first = pipe.run_interpretation(
        "docs/devanathan_2026_simple_dynamic_sbg.pdf", "adaptation", str(tmp_path / "cards"))
    assert first.stage_notes.get("card_drafter")

    precedent = pipe._precedent("card_drafter")
    assert precedent, "the next run's card_drafter fetch must see the first run's notes"
    all_notes = [n for hit in precedent for n in hit["notes"]]
    assert any("metrics.sharpe" in n for n in all_notes)


def test_bank_precedent_is_a_noop_when_there_is_nothing_to_bank(tmp_path):
    """An invalid card, or a run with no extractable stage notes, must not
    write a hollow library entry."""
    fx = _fixtures()
    fx = dict(fx)
    fx["card_drafter"] = dict(fx["card_drafter"])
    fx["card_drafter"]["card_yaml"] = "paper: {id: x}\nnot_a_real_section: 1\n"
    lib = StrategyLibrary(str(tmp_path / "library"))
    pipe = AgenticPipeline(mode="replay", fixtures=fx, library=lib)
    res = pipe.run_interpretation(
        "docs/devanathan_2026_simple_dynamic_sbg.pdf", "adaptation", str(tmp_path / "cards"))

    assert not res.card_valid
    assert res.library_entry_path is None
    assert lib.all() == []
