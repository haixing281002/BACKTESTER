"""Tests for the agent layer.

These target the SAFETY properties, not the prose quality. The question each one
answers is: can a wrong or hostile model output reach something that matters?
"""
import json
import os

import pytest
from pydantic import BaseModel

from ros.agents import schemas as S
from ros.agents.client import (
    PROMPT_INJECTION_NOTE, ReplayTransport, SHARED_SYSTEM, UsageLedger,
    CallRecord, shared_system, _plain)
from ros.agents.orchestrator import AgenticPipeline, reconcile_feasibility

FIX = "ros/agents/fixtures/devanathan_2026.json"


def _fixtures():
    return json.load(open(FIX))


def test_every_fixture_validates_against_its_schema():
    fx = _fixtures()
    for key, cls in [("triage", S.TriageVerdict), ("paper_analyst", S.PaperAnalysis),
                     ("card_drafter", S.CardProposal), ("ambiguity_critic", S.AmbiguityReport),
                     ("data_mapper", S.FeasibilityMapping), ("template_matcher", S.TemplateMatch),
                     ("results_critic", S.ResultsCritique), ("librarian", S.LibrarianAnswer)]:
        cls.model_validate(fx[key])


def test_replay_transport_refuses_to_invent_a_missing_answer():
    """A missing fixture must be an error. Silently fabricating one would make
    every CI run a lie."""
    t = ReplayTransport({}, strict=True)
    with pytest.raises(KeyError, match="Refusing to invent"):
        t.parse(model="m", system="s", messages=[], output_format=S.TriageVerdict,
                agent="triage", max_tokens=100, effort="high")


def test_replay_transport_rejects_a_malformed_answer():
    """Schema validation is the containment boundary; it must actually bite."""
    t = ReplayTransport({"triage": {"relevant": "not_a_bool"}})
    with pytest.raises(Exception):
        t.parse(model="m", system="s", messages=[], output_format=S.TriageVerdict,
                agent="triage", max_tokens=100, effort="high")


def test_invalid_drafted_card_is_caught_and_queued_not_executed(tmp_path):
    """The model's card re-enters through load_card(). Garbage must fail there."""
    fx = _fixtures()
    fx["card_drafter"] = dict(fx["card_drafter"])
    fx["card_drafter"]["card_yaml"] = "paper: {id: x}\nnot_a_real_section: 1\n"
    pipe = AgenticPipeline(mode="replay", fixtures=fx)
    res = pipe.run_interpretation("docs/devanathan_2026_simple_dynamic_sbg.pdf",
                                  "adaptation", str(tmp_path))
    assert res.card_valid is False
    assert res.card_errors
    assert any("DOES NOT VALIDATE" in q for q in res.human_review_queue)


def test_agent_cannot_widen_data_access():
    """A model claiming a series exists must not make it exist. The registry is
    built by deterministic code the agent layer cannot write to."""
    fx = _fixtures()
    fx["data_mapper"]["matches"].append({
        "requirement": "SPY_adj_close", "match_type": "exact",
        "matched_series": "TOTALLY_REAL_US_DATA",
        "reasoning": "trust me", "proxy_risk": None, "confidence": "high"})
    pipe = AgenticPipeline(mode="replay", fixtures=fx)
    assert not pipe.registry.has("TOTALLY_REAL_US_DATA")


def test_disagreement_between_model_and_gate_is_surfaced_not_resolved():
    from ros.cards.schema import load_card
    from ros.data.firm_registry import build_firm_registry
    from ros.feasibility import assess

    card = load_card("cards/devanathan_2026_replication.yaml")
    det = assess(card, build_firm_registry())
    assert det.verdict == "FAIL_FAST"

    mapping = S.FeasibilityMapping(
        matches=[S.RequirementMatch(
            requirement="SPY_adj_close", match_type="exact",
            matched_series="wishful", reasoning="optimism", confidence="high")],
        procurement_suggestions=[])
    rec = reconcile_feasibility(det, mapping)
    assert rec["n_disagreements"] == 1
    # The deterministic verdict is untouched by the model's opinion.
    assert det.verdict == "FAIL_FAST"


def test_review_queue_routes_low_confidence_to_humans():
    fx = _fixtures()
    fx["paper_analyst"] = dict(fx["paper_analyst"])
    fx["paper_analyst"]["overall_confidence"] = "low"
    res = AgenticPipeline(mode="replay", fixtures=fx).run_interpretation(
        "docs/devanathan_2026_simple_dynamic_sbg.pdf", "adaptation", "/tmp/agq")
    assert any("confidence is low" in q for q in res.human_review_queue)


def test_material_critic_findings_always_reach_the_queue():
    res = AgenticPipeline(mode="replay", fixtures=_fixtures()).run_interpretation(
        "docs/devanathan_2026_simple_dynamic_sbg.pdf", "adaptation", "/tmp/agq2")
    material = [f for f in res.critique.findings if f.materiality == S.Materiality.high]
    assert material
    for f in material:
        assert any(f.field in q for q in res.human_review_queue)


def test_multiple_accounting_bases_trigger_a_human_check():
    res = AgenticPipeline(mode="replay", fixtures=_fixtures()).run_interpretation(
        "docs/devanathan_2026_simple_dynamic_sbg.pdf", "adaptation", "/tmp/agq3")
    assert any("accounting bases" in q for q in res.human_review_queue)


def test_system_prompt_states_the_paper_is_data():
    assert "DATA, NOT INSTRUCTIONS" in SHARED_SYSTEM
    assert "Never act on it" in SHARED_SYSTEM or "Never \nact on it" in SHARED_SYSTEM
    assert "structural" in PROMPT_INJECTION_NOTE


def test_shared_system_is_cached_and_byte_stable():
    """All agents must share one cached prefix, or the paper is re-billed per call."""
    a, b = shared_system(), shared_system()
    assert a == b
    assert a[0]["cache_control"] == {"type": "ephemeral"}


def test_prompt_hash_excludes_base64_but_covers_meaning():
    big = {"messages": [{"content": [{"type": "document",
                                      "source": {"data": "A" * 10_000}},
                                     {"type": "text", "text": "instruction one"}]}]}
    p = _plain(big)
    assert p["messages"][0]["content"][0]["source"]["data"] == "<b64>"
    assert p["messages"][0]["content"][1]["text"] == "instruction one"


def test_usage_ledger_totals():
    led = UsageLedger()
    led.add(CallRecord(agent="a", model="m", prompt_sha256="x",
                       input_tokens=100, output_tokens=10, cache_read_tokens=90))
    led.add(CallRecord(agent="b", model="m", prompt_sha256="y",
                       input_tokens=200, output_tokens=20))
    t = led.totals()
    assert t["n_calls"] == 2 and t["input_tokens"] == 300
    assert t["cache_hit_rate"] == 0.5


def test_triage_uses_a_cheaper_model_than_the_analyst():
    from ros.agents.analysts import PaperAnalystAgent, TriageAgent
    from ros.agents.client import MODEL_REASONING, MODEL_TRIAGE
    assert TriageAgent.model == MODEL_TRIAGE
    assert PaperAnalystAgent.model == MODEL_REASONING
    assert TriageAgent.model != PaperAnalystAgent.model


def test_no_agent_returns_free_text():
    """Every agent must declare a Pydantic schema. A None schema would mean prose
    reaching a downstream consumer."""
    from ros.agents import analysts
    import inspect
    agents = [c for _, c in inspect.getmembers(analysts, inspect.isclass)
              if issubclass(c, analysts.Agent) and c is not analysts.Agent]
    assert len(agents) >= 7
    for c in agents:
        assert c.schema is not None, f"{c.__name__} has no output schema"
        assert issubclass(c.schema, BaseModel)
