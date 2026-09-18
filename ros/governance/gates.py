"""Gates A and B, and the promotion ladder.

The board replaced 'promising / rejected' with a governed ladder:

    REPLICATED > INDIA_VALIDATED > ROBUST > ORTHOGONAL > PORTFOLIO_USEFUL
              > PAPER_TRADED > LIVE_CANDIDATE

Rules that make the ladder mean something:
  - rungs are strictly ordered; a strategy sits at the HIGHEST rung whose every
    criterion passes AND all lower rungs pass. No skipping.
  - an adaptation card can never claim REPLICATED. Different question, different
    evidence. It enters at INDIA_VALIDATED.
  - every rung stores its evidence; a rung with no evidence is a fail, not a pass.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from ros.cards.schema import audit_data_requests

LADDER = ["REPLICATED", "INDIA_VALIDATED", "ROBUST", "ORTHOGONAL",
          "PORTFOLIO_USEFUL", "PAPER_TRADED", "LIVE_CANDIDATE"]

_W = 96


def _wrap(text: str, width: int) -> List[str]:
    """Normalise whitespace and soft-wrap. Empty text yields no lines, so a
    criterion with no evidence renders as one line rather than a blank one."""
    flat = " ".join(str(text or "").split())
    if not flat:
        return []
    return textwrap.wrap(flat, width) or []


@dataclass
class Criterion:
    name: str
    passed: bool
    evidence: str = ""
    value: Any = None
    threshold: Any = None
    blocking: bool = True

    def render(self, width: int = _W) -> str:
        """One criterion, with its evidence WRAPPED rather than cut.

        The evidence is the only part a reviewer can disagree with, and it used
        to be truncated mid-word by the call sites -- "the covariance estimat".
        A criterion whose reasoning is cut off is a criterion nobody can check,
        which turns the gate into a row of green marks.
        """
        mark = "PASS" if self.passed else ("FAIL" if self.blocking else "warn")
        if self.value is None:
            val = ""
        elif self.threshold is None:
            val = f"  [{self.value}]"
        else:
            val = f"  [{self.value} vs {self.threshold}]"
        lines = [f"    [{mark:>4}] {self.name}{val}"]
        for line in _wrap(self.evidence, width - 11):
            lines.append(f"           {line}")
        return "\n".join(lines)


@dataclass
class GateResult:
    gate: str
    owner: str
    criteria: List[Criterion] = field(default_factory=list)
    decision: str = "PENDING"        # APPROVE | REJECT | FIX | OBSERVE | PENDING
    rationale: str = ""

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria if c.blocking)

    @property
    def warnings(self) -> List[Criterion]:
        return [c for c in self.criteria if not c.passed and not c.blocking]

    def render(self) -> str:
        head = f"  {self.gate} (owner: {self.owner}) -> {'PASS' if self.passed else 'BLOCKED'}"
        body = "\n".join(c.render() for c in self.criteria)
        tail = f"\n    decision: {self.decision}" + (f" -- {self.rationale}" if self.rationale else "")
        return head + "\n" + body + tail

    def to_dict(self) -> Dict[str, Any]:
        return {"gate": self.gate, "owner": self.owner, "decision": self.decision,
                "passed": self.passed, "rationale": self.rationale,
                "criteria": [asdict(c) for c in self.criteria]}


def _call(tag, headline, detail, who=""):
    return {"tag": tag, "headline": headline, "detail": detail, "who": who}


def judgement_calls(card, translation_check=None) -> List[Dict[str, str]]:
    """Every choice on this card that a model made and a human may overturn.

    The criteria list below is an audit trail: it proves each thing was checked.
    It is not a decision aid, because a reviewer reading twenty-four green rows
    learns only that nothing tripped. What a human actually signs at Gate A is
    this: the specific judgements, each with what was chosen, on what basis, and
    who can say otherwise.

    Pulled from the card rather than restated, so this can never drift from what
    the run will actually do.
    """
    out: List[Dict[str, str]] = []
    ut, st, cv = (card.universe_translation, card.strategy,
                  getattr(card, "convertibility", None))

    if ut is not None:
        detail = " ".join((ut.rationale or "no rationale given").split())
        if ut.why_not_alternatives:
            detail += ("  RUNNERS-UP: "
                       + " ".join(ut.why_not_alternatives.split()))
        out.append(_call("UNIVERSE",
                         f"{ut.source_universe} -> {ut.target_universe or '(none)'}"
                         + (f"  [{ut.grade}]" if ut.grade else ""),
                         detail, "researcher"))
    if translation_check is not None:
        for note in translation_check.notes:
            if "OUT OF MANDATE" in note.upper():
                out.append(_call("MANDATE", "the chosen universe is OUT OF MANDATE",
                                 " ".join(note.split()), "pm"))

    if st is not None and st.is_long_short:
        out.append(_call(
            "LONG-ONLY", "the paper is long-short; this fund cannot short",
            " ".join(st.long_only_adaptation.split()) or "NOT STATED",
            "pm"))
    if card.portfolio.mandate_allow_cash is False and card.portfolio.allow_cash:
        out.append(_call(
            "MANDATE", "the paper holds cash; the mandate is fully invested",
            "Two different strategies, not two views of one. Which governs the "
            "promotion decision is the fund's call, not the card's.", "pm"))

    if cv is not None:
        out.append(_call("CONVERTIBLE?", f"{cv.verdict}  (confidence {cv.confidence})",
                         "WEAKEST LINK: " + " ".join(cv.weakest_link.split()),
                         "researcher"))

    out.append(_call(
        "NUMBERS",
        f"{card.costs.spread_bps:.0f}bp round trip, lag {card.signal.lag_days}d"
        + (f", lookback {card.signal.lookback_days}d"
           if card.signal.lookback_days else ""),
        "A US paper's 5bp is the commonest way an Indian backtest lies, and "
        "lag 0 trades on a price nobody had. Both are cheap to reject here.",
        "researcher"))

    bp = getattr(card, "backtest_plan", None)
    if bp is not None:
        bar = "; ".join(bp.must_beat) or "NOTHING NAMED"
        out.append(_call(
            "THE BAR", f"sample {bp.sample_start} -> {bp.sample_end}",
            f"MUST BEAT: {bar}.  Named before the run so it cannot move "
            f"afterwards. If this is not the bar you would hold it to, say so "
            f"now.", "pm"))

    sel = getattr(card, "selection", None)
    if sel is not None and sel.explicit_securities and \
            sel.verified_against in ("", "UNVERIFIED"):
        out.append(_call(
            "SECURITIES",
            f"{len(sel.explicit_securities)} names, UNVERIFIED",
            "A list recalled rather than checked is plausible and unverifiable, "
            "which is worse than no list because it looks checked: "
            + ", ".join(sel.explicit_securities), "data_owner"))

    for a in card.material_ambiguities:
        out.append(_call(
            "AMBIGUITY",
            f"{a.field}   [resolved, confidence {a.confidence}"
            + (f", p.{a.evidence_page}]" if a.evidence_page else "]"),
            " ".join(a.resolution.split()), "researcher"))

    for q in card.open_questions:
        out.append(_call(
            "OPEN", " ".join(q.question.split()),
            ("BLOCKS THE RUN" if q.blocks_run else
             "assumed meanwhile: " + " ".join(q.what_i_assumed.split())),
            q.ask_of))
    return out


def gate_a_brief(card, result, translation_check=None) -> str:
    """What a human is being asked to sign, before the audit trail.

    Gate A had all of this and none of it was converted: the asks sat 250 lines
    below the criteria, the evidence was truncated mid-word, and the judgement
    calls were spread across four sections a reviewer had to assemble in their
    head. The gate is five minutes of somebody's attention. This is what those
    five minutes should be spent on.
    """
    W = _W
    blocking = [c for c in result.criteria if not c.passed and c.blocking]
    warns = result.warnings
    L = ["  " + "=" * W,
         "  GATE A  --  WHAT YOU ARE BEING ASKED TO SIGN",
         "  " + "=" * W,
         f"  {card.paper.id}   ({card.intent.mode})",
         f"  {len(result.criteria)} criteria checked   "
         f"{len(blocking)} blocking   {len(warns)} worth a look"]

    if blocking:
        L += ["", "  " + "-" * W,
              "  STOP. THESE BLOCK THE GATE -- nothing runs until they are fixed.",
              "  " + "-" * W]
        for i, c in enumerate(blocking, 1):
            L.append(f"  {i}. {c.name}"
                     + ("" if c.value is None else f"   [{c.value}]"))
            for line in _wrap(c.evidence, W - 8):
                L.append(f"       {line}")

    calls = judgement_calls(card, translation_check)
    L += ["", "  " + "-" * W,
          "  THE JUDGEMENT CALLS. A model made each of these. You can overturn "
          "any of them.",
          "  " + "-" * W]
    for cl in calls:
        who = f"   <- {cl['who']}" if cl["who"] else ""
        tag = f"  [{cl['tag']}] "
        head_lines = _wrap(cl["headline"] + who, W - len(tag)) or [""]
        L.append("")
        L.append(tag + head_lines[0])
        for line in head_lines[1:]:
            L.append(" " * len(tag) + line)
        for line in _wrap(cl["detail"], W - 8):
            L.append(f"       {line}")

    reqs = sorted(getattr(card, "data_requests", []) or [],
                  key=lambda r: {"blocking": 0, "high": 1,
                                 "nice_to_have": 2}.get(r.priority, 9))
    L += ["", "  " + "-" * W,
          "  WHAT SAYING NO COSTS. Every ask has a fallback; this is what each "
          "fallback gives up.",
          "  " + "-" * W]
    if not reqs:
        claim = " ".join(getattr(card, "no_further_data_needed", "").split())
        if claim:
            L.append("")
            for line in _wrap("Nothing is being asked for, and here is why: "
                              + claim, W - 6):
                L.append(f"     {line}")
        else:
            L += ["", "     Nothing is asked for and nothing says why not. That "
                      "is a strong claim",
                  "     about a paper somebody just read, and nobody has argued "
                  "it."]
    for r in reqs:
        tag = {"blocking": "BLOCKING", "high": "would help",
               "nice_to_have": "optional"}.get(r.priority, r.priority)
        L.append("")
        L.append(f"  [{tag}] {r.item}")
        for label, val in (("if declined", r.without_it), ("unlocks", r.unlocks)):
            for i, line in enumerate(_wrap(val, W - 20)):
                L.append(f"       {label if i == 0 else '':<13} {line}")

    if warns:
        L += ["", "  " + "-" * W, "  WORTH A SECOND LOOK (does not block)",
              "  " + "-" * W]
        for c in warns:
            L.append(f"    - {c.name}"
                     + ("" if c.value is None else f"   [{c.value}]"))

    L += ["", "  " + "-" * W,
          "  NOTHING ABOVE IS DECIDED. Gate A produces this checklist; the "
          "decision is a",
          "  named human's, and no code in this repo assigns one.",
          "  " + "=" * W]
    return "\n".join(L)


def gate_a(card, feasibility, extraction_quality=None,
           translation_check=None) -> GateResult:
    """GATE A -- HUMAN INTERPRETATION CONTROL.

    Owned by the researcher. Confirms we understand the paper before we spend a
    day coding it. Everything here is cheap; everything after it is not.

    Two questions dominate the rest and are asked first: WHICH UNIVERSE will
    this be tested on, and WHAT EXACTLY is the strategy? Both are Stage 01
    interpretation, both are wrong often enough to matter, and both are far
    cheaper to correct here than after a run.
    """
    c: List[Criterion] = []

    c.append(Criterion(
        "card validates against schema", not card.validate(),
        evidence="; ".join(card.validate()) or "schema clean"))

    # ---- what are we testing this on? ------------------------------------
    ut = getattr(card, "universe_translation", None)
    if ut is None:
        c.append(_missing(
            "universe translation recorded", "a source and a target universe",
            "the card does not say which universe the paper studied or which "
            "Indian universe replaces it. Without that, the choice of tickers "
            "is an unrecorded judgement nobody signed for"))
    else:
        c.append(Criterion(
            "universe translation recorded", True,
            value=f"{ut.source_universe} -> {ut.target_universe or '(none)'}",
            evidence=" ".join((ut.rationale or "no rationale given").split())))

        if translation_check is not None:
            tc = translation_check
            c.append(Criterion(
                "source universe is a recorded correspondence",
                tc.recognised_source and not tc.divergences,
                value=("recognised" if tc.recognised_source else "UNKNOWN"),
                evidence="; ".join(tc.divergences) or
                         "matches ros/data/universes.py",
                blocking=False))
            c.append(Criterion(
                "the fund can obtain this universe",
                not tc.missing,
                value=tc.computed_resolution,
                threshold="direct or sleeve_proxy",
                evidence=(f"missing: {', '.join(tc.missing)}" if tc.missing
                          else f"{len(tc.held)} instruments held")))
            c.append(Criterion(
                "translation risks acknowledged", bool(tc.caveats),
                value=len(tc.caveats), threshold=">=1", blocking=False,
                evidence="a translation with nothing to lose has not been examined"))

    # ---- is Gate A verifying, or designing? ------------------------------
    # These three exist so a human at Gate A confirms a plan rather than filling
    # one in. Stage 02 is where the work happens; if the card cannot say what
    # dataset it wants, which securities, and what will be run, it is not done.
    dp = getattr(card, "data_plan", None)
    if dp is None:
        c.append(_missing(
            "dataset designed from the paper", "a data plan",
            "the card names no dataset of its own, so it can only shop from what "
            "the fund already holds -- and a paper reshaped to fit the available "
            "data is a different paper"))
    else:
        errs = dp.validate()
        c.append(Criterion(
            "dataset designed from the paper", not errs,
            value=f"{len(dp.ideal)} field(s), "
                  f"{sum(1 for d in dp.ideal if d.minimum_viable)} minimum-viable",
            evidence="; ".join(errs) or
                     " ".join(dp.granularity_verdict.split())))
        c.append(Criterion(
            "alternatives were rejected, not skipped",
            len(dp.rejected_alternatives) >= 1,
            value=len(dp.rejected_alternatives), threshold=">=1", blocking=False,
            evidence="; ".join(r.get("option", "?") for r in
                               dp.rejected_alternatives)
                     or "a dataset with no rejected alternative was assumed"))

    sel = getattr(card, "selection", None)
    if sel is None or not sel.rule.strip():
        c.append(_missing(
            "securities selection stated", "a rule",
            "a selection nobody can re-derive on another date is not a strategy"))
    else:
        c.append(Criterion(
            "securities selection stated", True,
            value=(f"{len(sel.explicit_securities)} named"
                   if sel.explicit_securities else "rule only"),
            evidence=" ".join(sel.rule.split())))
        if sel.explicit_securities:
            verified = sel.verified_against not in ("", "UNVERIFIED")
            c.append(Criterion(
                "named securities are verified", verified,
                value=sel.verified_against or "NOTHING",
                threshold="not UNVERIFIED",
                evidence=(f"{len(sel.explicit_securities)} names as of "
                          f"{sel.as_of or 'no date'}") if verified else
                         "a list recalled rather than checked is plausible and "
                         "unverifiable, which is worse than no list"))

    bp = getattr(card, "backtest_plan", None)
    if bp is None:
        c.append(_missing(
            "the run is specified", "a backtest plan",
            "without it Gate A is designing the run rather than verifying it: "
            "the window, the warmup, the benchmarks and the failure criteria are "
            "all still open"))
    else:
        errs = bp.validate()
        c.append(Criterion(
            "the run is specified", not errs,
            value=f"{bp.sample_start} -> {bp.sample_end}",
            evidence="; ".join(errs) or
                     f"{len(bp.benchmarks)} benchmark(s), "
                     f"{len(bp.must_beat)} must-beat"))
        c.append(Criterion(
            "failure is defined before the run",
            bool(bp.failure_looks_like.strip()),
            evidence=" ".join(bp.failure_looks_like.split()) or
                     "a plan that cannot fail is not a test, and a criterion "
                     "written after the numbers is not a criterion"))

    # ---- what is the model asking a human for? ---------------------------
    reqs = getattr(card, "data_requests", []) or []
    qs = getattr(card, "open_questions", []) or []
    blocking_reqs = [r for r in reqs if r.priority == "blocking"]
    blocking_qs = [q for q in qs if q.blocks_run]

    # "data requests carry a fallback" used to sit here, and it could not fail:
    # DataRequest.validate() rejects an empty `without_it` and load_card() then
    # raises, so every card reaching this gate had already passed it. With no
    # requests at all, all() returned True as well. It was a green row that
    # verified nothing. These two check what the schema cannot.
    audit = audit_data_requests(card)
    c.append(Criterion(
        "the card asked for something, or argued it need not",
        audit["stance"] != "silent",
        value={"asked": f"{audit['n']} request(s)",
               "argued_none": "argues none is needed",
               "silent": "nothing asked, nothing argued"}[audit["stance"]],
        blocking=False,
        evidence=audit["detail"]))
    c.append(Criterion(
        "fallbacks are decisions you could take", audit["ok"],
        value=f"{audit['n']} request(s)",
        evidence="; ".join(audit["weak"]) or
                 "each request says what happens if you decline it, and what "
                 "that costs the test"))
    c.append(Criterion(
        "no request is blocking", not blocking_reqs,
        value=f"{len(blocking_reqs)} blocking", threshold=0,
        evidence="; ".join(r.item for r in blocking_reqs)
                 or "nothing is being waited on"))
    c.append(Criterion(
        "open questions carry a working assumption",
        all(q.what_i_assumed.strip() or q.blocks_run for q in qs),
        value=f"{len(qs)} question(s)", blocking=False,
        evidence="; ".join(q.question for q in qs
                           if not q.what_i_assumed.strip() and not q.blocks_run)
                 or "the run can proceed under stated assumptions"))
    c.append(Criterion(
        "no question blocks the run", not blocking_qs,
        value=f"{len(blocking_qs)} blocking", threshold=0,
        evidence="; ".join(q.question for q in blocking_qs)
                 or "no question stops work"))

    # ---- can this become something the fund could hold? ------------------
    # Non-blocking on purpose. "not_convertible" is a legitimate and valuable
    # answer; what is NOT acceptable is the card never saying, because then the
    # judgement lands on whoever happens to read the gate.
    cv = getattr(card, "convertibility", None)
    if cv is None:
        c.append(Criterion(
            "convertibility assessed", False, blocking=False,
            value="no verdict",
            evidence="the card never says whether any of this could become a "
                     "strategy this fund could hold. That judgement then falls "
                     "to whoever reads the gate, which is Stage 02's work "
                     "landing here"))
    else:
        c.append(Criterion(
            "convertibility assessed", True, value=cv.verdict,
            blocking=False,
            evidence=f"weakest link: {' '.join(cv.weakest_link.split())}"))
        c.append(Criterion(
            "what would settle it is named",
            bool(cv.decisive_evidence.strip()), blocking=False,
            evidence=" ".join(cv.decisive_evidence.split()) or
                     "without this, the data requests below are wishes rather "
                     "than tests of the thing actually in doubt"))
        if cv.verdict == "convertible_with_data" and not reqs:
            c.append(Criterion(
                "verdict agrees with the asks", False,
                value="contradiction",
                evidence="the verdict says this needs data the fund does not "
                         "hold, and the card asks for none. One of the two is "
                         "wrong, and both are the model's own statements"))

    # ---- what exactly is the strategy? -----------------------------------
    st = getattr(card, "strategy", None)
    if st is None:
        c.append(_missing(
            "strategy reconstructed", "an executable restatement",
            "the card names a template but never states, in words a second "
            "person could implement from, what the paper's strategy IS"))
    else:
        errs = st.validate()
        c.append(Criterion(
            "strategy reconstructed to an executable level", not errs,
            value=st.signal_name or "(unnamed)",
            evidence="; ".join(errs) or " ".join(st.signal_definition.split())))
        c.append(Criterion(
            "long-only adaptation stated",
            not st.is_long_short or bool(st.long_only_adaptation.strip()),
            value="long-short source" if st.is_long_short else "already long-only",
            evidence=(" ".join(st.long_only_adaptation.split()) if st.is_long_short
                      else "paper is long-only; nothing to adapt")))
        c.append(Criterion(
            "the engine can express this strategy",
            st.engine_template != "NEEDS_NEW_TEMPLATE",
            value=st.engine_template or "(unset)",
            evidence=(" ".join(st.template_gap.split())
                      if st.engine_template == "NEEDS_NEW_TEMPLATE"
                      else "maps to a registered allocator template")))
        c.append(Criterion(
            "strategy read with confidence", st.confidence == "high",
            value=st.confidence, threshold="high", blocking=False,
            evidence=f"pages {st.evidence_pages}" if st.evidence_pages
                     else "no page citations -- unverifiable"))

    unresolved = card.unresolved_ambiguities
    c.append(Criterion(
        "all ambiguities resolved", not unresolved,
        value=len(unresolved), threshold=0,
        evidence="unresolved: " + ", ".join(a.field for a in unresolved) if unresolved
                 else f"{len(card.ambiguities)} ambiguities logged and resolved"))

    low = [a for a in card.material_ambiguities if a.confidence == "low"]
    c.append(Criterion(
        "no low-confidence material interpretation", not low,
        value=len(low), threshold=0, blocking=False,
        evidence="low-confidence: " + ", ".join(a.field for a in low) if low else "none"))

    c.append(Criterion(
        "data feasibility resolved", feasibility.can_proceed,
        value=feasibility.verdict, threshold="GO or GO_WITH_PROXY",
        evidence="; ".join(feasibility.blocking) or "no blocking data gaps"))

    if card.intent.mode == "replication":
        c.append(Criterion(
            "replication targets defined", bool(card.replication_targets),
            value=len(card.replication_targets), threshold=">=1",
            evidence="targets pinned to a single accounting basis"))
    else:
        c.append(Criterion(
            "transferred mechanism stated", bool(card.intent.transferred_mechanism),
            evidence=card.intent.transferred_mechanism or "MISSING"))
        c.append(Criterion(
            "broken source assumptions enumerated", bool(card.intent.broken_assumptions),
            value=len(card.intent.broken_assumptions), threshold=">=1", blocking=False,
            evidence="; ".join(card.intent.broken_assumptions) or "none listed -- suspicious"))

    if extraction_quality is not None:
        c.append(Criterion(
            "source text is machine-readable", extraction_quality.usable,
            evidence="; ".join(extraction_quality.warnings) or "clean extraction",
            blocking=True))
        c.append(Criterion(
            "equations verified against rendered page",
            extraction_quality.mean_math_density < 0.05,
            value=f"{extraction_quality.mean_math_density:.1%}", threshold="<5%",
            blocking=False,
            evidence="high math density: formulas were hand-checked, not trusted from text"))

    return GateResult("GATE A -- interpretation", "researcher", c)


def _missing(name: str, threshold: Any, why: str) -> Criterion:
    """A criterion whose evidence never arrived.

    It fails, and it fails *visibly*. The alternative -- omitting the row --
    makes GateResult.passed an `all()` over a shorter list, so a gate can report
    PASS precisely because the test that would have blocked it never ran. That
    is the one failure mode this whole file exists to prevent.
    """
    return Criterion(name, False, value="NOT COMPUTED", threshold=threshold,
                     evidence=f"NO EVIDENCE: {why}")


def gate_b(card, research: Dict[str, Any], portfolio: Dict[str, Any],
           thresholds: Optional[Dict[str, float]] = None) -> GateResult:
    """GATE B -- INVESTMENT DECISION. Owned by PM / IC.

    Deliberately strict on orthogonality and incremental IR: those are the two
    criteria that separate 'a real effect' from 'a real effect we are already paid for'.
    """
    t = {"min_oos_sharpe": 0.30, "max_corr_to_book": 0.80, "min_delta_ir": 0.05,
         "min_dsr": 0.95, "max_turnover": 4.0, "min_alpha_t": 2.0}
    t.update(thresholds or {})
    c: List[Criterion] = []

    # Every criterion below appears on the sheet whether or not its evidence
    # arrived. See _missing(): a checklist that quietly gets shorter is worse
    # than one that fails, because a human signing it cannot see what is absent.
    dsr = research.get("deflated_sharpe", {})
    if "deflated_sharpe_prob" in dsr:
        c.append(Criterion(
            "deflated Sharpe clears selection bias",
            dsr["deflated_sharpe_prob"] >= t["min_dsr"],
            value=f"{dsr['deflated_sharpe_prob']:.2f}", threshold=t["min_dsr"],
            evidence=dsr.get("interpretation", "")))
    else:
        c.append(_missing("deflated Sharpe clears selection bias", t["min_dsr"],
                          dsr.get("error", "the deflated Sharpe calculation did not run")))

    oos = research.get("oos_min_sharpe")
    if oos is not None:
        c.append(Criterion(
            "positive Sharpe in every out-of-sample window",
            oos >= t["min_oos_sharpe"],
            value=f"{oos:.2f}", threshold=t["min_oos_sharpe"],
            evidence="worst walk-forward window"))
    else:
        c.append(_missing("positive Sharpe in every out-of-sample window",
                          t["min_oos_sharpe"],
                          "the walk-forward analysis did not run"))

    sig = research.get("bootstrap_p_not_positive")
    if sig is not None:
        c.append(Criterion(
            "advantage over benchmark is significant",
            sig <= 0.05, value=f"{sig:.3f}", threshold="<=0.05",
            evidence="paired stationary-bootstrap P(Sharpe difference <= 0)"))
    else:
        c.append(_missing("advantage over benchmark is significant", "<=0.05",
                          "the paired bootstrap did not run"))

    # These two compare against what the fund already runs. With an empty book
    # there is genuinely nothing to compare to -- that is not a failure, but it
    # is also not a pass, so it is shown as an unmet warning rather than left
    # off the sheet for a human to not notice.
    corr = portfolio.get("max_corr_to_book")
    if corr is not None:
        c.append(Criterion(
            "differentiated from existing book",
            corr <= t["max_corr_to_book"],
            value=f"{corr:.2f}", threshold=f"<={t['max_corr_to_book']}",
            evidence="max correlation to any existing signal"))
    else:
        c.append(Criterion(
            "differentiated from existing book", False, blocking=False,
            value="NO COMPARISON", threshold=f"<={t['max_corr_to_book']}",
            evidence="nothing else in the book to compare against"))

    dir_ = portfolio.get("best_delta_ir")
    if dir_ is not None:
        c.append(Criterion(
            "improves the book's information ratio",
            dir_ >= t["min_delta_ir"],
            value=f"{dir_:+.3f}", threshold=f">={t['min_delta_ir']}",
            evidence="incremental IR at a realistic sleeve size"))
    else:
        c.append(Criterion(
            "improves the book's information ratio", False, blocking=False,
            value="NO COMPARISON", threshold=f">={t['min_delta_ir']}",
            evidence="nothing else in the book to measure an increment against"))

    at = portfolio.get("alpha_t_hac")
    if at is not None:
        c.append(Criterion(
            "alpha survives the factor fingerprint",
            abs(at) >= t["min_alpha_t"],
            value=f"{at:.2f}", threshold=f"|t|>={t['min_alpha_t']}",
            evidence="HAC t-stat of alpha vs known factor sleeves"))
    else:
        # A test that could not be run is NOT a test that passed. Dropping the
        # row would shrink the checklist silently and let `passed` go True
        # having never asked the question that matters most on this desk --
        # whether the alpha is anything more than sleeves the fund already owns.
        c.append(Criterion(
            "alpha survives the factor fingerprint", False,
            value="NOT COMPUTED", threshold=f"|t|>={t['min_alpha_t']}",
            evidence=portfolio.get("alpha_t_hac_error",
                                   "the factor regression did not run")))

    mand = portfolio.get("mandate", {})
    if mand:
        c.append(Criterion(
            "implementable within mandate", bool(mand.get("passes")),
            evidence="; ".join(mand.get("violations", [])) or "no mandate violations"))

    to = portfolio.get("annual_turnover")
    if to is not None:
        c.append(Criterion(
            "turnover within operational tolerance", to <= t["max_turnover"],
            value=f"{to:.0%}", threshold=f"<={t['max_turnover']:.0%}", blocking=False,
            evidence="annualised two-way turnover"))

    return GateResult("GATE B -- investment decision", "PM / IC", c)


@dataclass
class PromotionRung:
    rung: str
    criteria: List[Criterion] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.criteria) and all(c.passed for c in self.criteria if c.blocking)


def evaluate_ladder(card, rung_criteria: Dict[str, List[Criterion]]) -> Dict[str, Any]:
    """Walk the ladder in order, stopping at the first rung that fails.

    An adaptation card starts at INDIA_VALIDATED: REPLICATED is marked N/A rather
    than passed, so an adaptation can never be reported as a replication.
    """
    results: List[Dict[str, Any]] = []
    attained: Optional[str] = None
    stopped_at: Optional[str] = None

    for rung in LADDER:
        if rung == "REPLICATED" and card.intent.mode == "adaptation":
            results.append({"rung": rung, "status": "N/A",
                            "note": "adaptation card: replication is a different question",
                            "criteria": []})
            continue
        crits = rung_criteria.get(rung)
        if crits is None:
            results.append({"rung": rung, "status": "NOT_EVALUATED", "criteria": []})
            if stopped_at is None:
                stopped_at = rung
            break
        r = PromotionRung(rung, crits)
        results.append({
            "rung": rung, "status": "PASS" if r.passed else "FAIL",
            "criteria": [asdict(c) for c in crits],
            "failed": [c.name for c in crits if not c.passed and c.blocking],
        })
        if r.passed:
            attained = rung
        else:
            stopped_at = rung
            break

    return {
        "card_id": card.paper.id,
        "mode": card.intent.mode,
        "attained_rung": attained,
        "stopped_at": stopped_at,
        "ladder": results,
    }


def render_ladder(lad: Dict[str, Any]) -> str:
    lines = ["STEP 08 -- PROMOTION LADDER",
             f"  card: {lad['card_id']} ({lad['mode']})",
             f"  attained: {lad['attained_rung'] or 'NONE'}   stopped at: {lad['stopped_at'] or '--'}",
             ""]
    for r in lad["ladder"]:
        lines.append(f"  {r['rung']:<18} {r['status']}")
        if r.get("note"):
            lines.append(f"      {r['note']}")
        for c in r.get("criteria", []):
            mk = "PASS" if c["passed"] else ("FAIL" if c["blocking"] else "warn")
            v = "" if c["value"] is None else f"  [{c['value']} vs {c['threshold']}]"
            lines.append(f"      [{mk:>4}] {c['name']}{v}")
            if c.get("evidence"):
                lines.append(f"             {c['evidence']}")
    return "\n".join(lines)
