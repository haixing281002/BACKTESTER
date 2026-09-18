"""How complete is this card, measured against the standard a good one sets.

WHY SCORE A CARD AT ALL

A card that validates is not a card that is any good. The schema catches
structural holes -- no signal definition, a long-short paper with no stated
adaptation -- but it cannot tell the difference between six ambiguities each
carrying a page citation and a resolution, and one ambiguity saying "unclear,
proceeded anyway". Both validate. Only one is worth a reviewer's five minutes.

So the checks here are drawn from what a strong card actually contains, and each
one names the failure it prevents rather than asserting a house style. A card
scoring 60% is not badly formatted; it is a card whose reader cannot tell which
judgements were made or why.

WHAT THIS IS NOT

It is not a gate and it does not block. Gate A blocks on specific things a human
must confirm. This is a completeness report: it tells the person drafting the
card what a reviewer will find thin, while it is still cheap to fix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple


@dataclass
class Check:
    section: str
    name: str
    passed: bool
    weight: int                  # how much this matters, 1-3
    detail: str = ""
    matters: str = ""            # the failure it prevents

    def render(self) -> str:
        mark = "ok  " if self.passed else ("MISS" if self.weight >= 3 else "thin")
        out = [f"    [{mark}] {self.section:<22} {self.name}"]
        if self.detail:
            out.append(f"             {self.detail}")
        if not self.passed and self.matters:
            out.append(f"             -> {self.matters}")
        return "\n".join(out)


@dataclass
class Completeness:
    checks: List[Check] = field(default_factory=list)

    @property
    def score(self) -> float:
        total = sum(c.weight for c in self.checks)
        got = sum(c.weight for c in self.checks if c.passed)
        return got / total if total else 0.0

    @property
    def missing(self) -> List[Check]:
        return [c for c in self.checks if not c.passed]

    @property
    def serious(self) -> List[Check]:
        return [c for c in self.checks if not c.passed and c.weight >= 3]

    def render(self, only_missing: bool = False) -> str:
        L = [f"  CARD COMPLETENESS   {self.score:.0%}"
             f"   ({len(self.checks) - len(self.missing)} of {len(self.checks)} checks)"]
        if self.serious:
            L.append(f"  {len(self.serious)} of the gaps are the kind a reviewer "
                     f"cannot work around.")
        L.append("")
        shown = self.missing if only_missing else self.checks
        seen = set()
        for c in shown:
            if c.section not in seen:
                seen.add(c.section)
            L.append(c.render())
        if not shown:
            L.append("    nothing missing.")
        return "\n".join(L)


def _txt(v) -> str:
    return " ".join(str(v or "").split())


def assess(card) -> Completeness:
    """Score a card against what a strong one contains."""
    out = Completeness()

    def check(section, name, passed, weight, detail="", matters=""):
        out.checks.append(Check(section=section, name=name, passed=bool(passed),
                                weight=weight, detail=detail, matters=matters))

    # ---- provenance -----------------------------------------------------
    pa = card.paper
    check("paper", "source PDF recorded", bool(pa.source_file), 3,
          pa.source_file or "",
          "without the source file nothing can re-read the paper this came from")
    check("paper", "sha256 of the paper", bool(pa.source_sha256), 3,
          pa.source_sha256 or "",
          "a result that cannot be tied to specific bytes cannot be reproduced "
          "once the file is edited or replaced")
    check("paper", "authors and date", bool(pa.authors and pa.date), 1,
          f"{len(pa.authors or [])} author(s), {pa.date or 'no date'}",
          "needed to find the paper again and to spot a superseded version")

    # ---- intent ---------------------------------------------------------
    it = card.intent
    check("intent", "rationale stated", len(_txt(it.rationale)) > 80, 2,
          f"{len(_txt(it.rationale))} chars",
          "a card with no rationale cannot be argued with, only accepted")
    if it.mode == "adaptation":
        check("intent", "transferred mechanism", len(_txt(it.transferred_mechanism)) > 60, 3,
              "", "an adaptation that does not say WHAT transferred is untestable: "
                  "there is nothing to check the result against")
        n_broken = len(it.broken_assumptions or [])
        check("intent", "broken assumptions", n_broken >= 2, 3,
              f"{n_broken} listed",
              "every adaptation breaks something. A card listing none has not "
              "been examined, and the unexamined break is what kills the result")
    else:
        check("intent", "replication targets", bool(card.replication_targets), 3,
              f"{len(card.replication_targets)} pinned",
              "a replication with no target numbers can never fail, which makes "
              "it not a replication")

    # ---- universe translation ------------------------------------------
    ut = card.universe_translation
    check("universe", "translation recorded", ut is not None, 3, "",
          "without it, the choice of assets is an unrecorded judgement and two "
          "papers cannot be compared later")
    if ut is not None:
        check("universe", "source named precisely", len(_txt(ut.source_universe)) > 3, 2,
              _txt(ut.source_universe)[:60],
              "'US stocks' is not a universe; the construction is what transfers")
        check("universe", "selection rule", bool(_txt(ut.source_selection_rule)), 2,
              "", "how the paper picks from its universe is half the strategy")
        check("universe", "rationale for the target", len(_txt(ut.rationale)) > 80, 3,
              "", "the universe choice is the single most consequential call at "
                  "Stage 01 and it needs an argument, not a preference")
        check("universe", "transfer risks", len(ut.transfer_risks or []) >= 2, 3,
              f"{len(ut.transfer_risks or [])} listed",
              "a translation with nothing to lose has not been examined")
        check("universe", "mechanism needs", ut.mechanism_needs is not None, 2, "",
              "without stated needs the universe ranking has nothing to score "
              "against, so the choice cannot be checked")
        check("universe", "alternatives considered", len(ut.alternatives_considered or []) >= 1, 2,
              f"{len(ut.alternatives_considered or [])} named",
              "a choice with no recorded runners-up is unfalsifiable later")
        check("universe", "why not the alternatives", bool(_txt(ut.why_not_alternatives)), 2,
              "", "naming alternatives without saying why they lost is a gesture")
        check("universe", "page citation", ut.evidence_page is not None, 1, "",
              "so a reviewer can verify the source universe in one look")

    # ---- strategy -------------------------------------------------------
    st = card.strategy
    check("strategy", "reconstruction present", st is not None, 3, "",
          "a template name is not a strategy; a second person cannot implement "
          "from it")
    if st is not None:
        check("strategy", "signal definition", len(_txt(st.signal_definition)) > 120, 3,
              f"{len(_txt(st.signal_definition))} chars",
              "every window, lag and skip, or the engine runs something else "
              "that still produces numbers")
        check("strategy", "inputs listed", len(st.inputs_required or []) >= 1, 2,
              f"{len(st.inputs_required or [])} listed",
              "what the signal READS is what Stage 03 resolves and what the "
              "India requirements key on")
        check("strategy", "formation rule", bool(_txt(st.formation_rule)), 2, "",
              "how the signal becomes a selection")
        check("strategy", "weighting rule", bool(_txt(st.weighting_rule)), 2, "",
              "how the selection becomes weights")
        check("strategy", "constraints", len(st.constraints or []) >= 1, 2,
              f"{len(st.constraints or [])} listed",
              "the constraints ARE the strategy in a risk-capped mechanism")
        check("strategy", "page citations", len(st.evidence_pages or []) >= 1, 2,
              f"pages {st.evidence_pages or 'none'}",
              "an uncited reconstruction cannot be verified, only trusted")
        check("strategy", "read at high confidence", st.confidence == "high", 1,
              st.confidence,
              "below high, a human must re-read the governing pages")
        if st.is_long_short:
            check("strategy", "long-only adaptation", bool(_txt(st.long_only_adaptation)), 3,
                  "", "this fund cannot short and the dropped leg often carries "
                      "most of the published spread")

    # ---- engine + execution --------------------------------------------
    check("signal", "template named", bool(card.signal.template), 3, "",
          "nothing can run without one")
    check("signal", "lookback stated", card.signal.lookback_days is not None, 2, "",
          "an unstated window means the engine picks one silently")
    check("signal", "lag >= 1", card.signal.lag_days >= 1, 3,
          f"{card.signal.lag_days}d",
          "NSE closes publish after the close; lag 0 trades on a price nobody had")
    check("signal", "description", len(_txt(card.signal.description)) > 40, 1, "",
          "a line saying why these parameters, for the next reader")

    # ---- portfolio and mandate -----------------------------------------
    po = card.portfolio
    check("portfolio", "sample window", bool(po.start and po.end), 2,
          f"{po.start or '?'} -> {po.end or '?'}",
          "an unbounded sample silently changes when the data does")
    check("portfolio", "mandate stance recorded", po.mandate_allow_cash is not None, 2,
          f"mandate_allow_cash={po.mandate_allow_cash}",
          "when the paper holds cash and the fund cannot, the two runs answer "
          "different questions and both are needed")

    # ---- costs ----------------------------------------------------------
    check("costs", "cost not copied from the paper", card.costs.spread_bps >= 20.0, 3,
          f"{card.costs.spread_bps:.0f}bp",
          "a US paper's 5bp is the single most common way an Indian backtest "
          "lies; 30bp is this fund's floor for sleeve rotation")

    # ---- evidence and honesty ------------------------------------------
    n_req = len(card.data_requirements)
    check("data", "requirements enumerated", n_req >= 1, 3, f"{n_req} listed",
          "Stage 03 has nothing to resolve without them")
    check("data", "each requirement has a purpose",
          all(_txt(d.purpose) for d in card.data_requirements) and n_req >= 1, 2,
          "", "a series with no stated purpose cannot be argued out of the card")

    n_amb = len(card.ambiguities)
    check("ambiguities", "logged", n_amb >= 3, 3, f"{n_amb} logged",
          "a paper that raised fewer than three judgement calls was probably "
          "not read closely; the example card carries six")
    check("ambiguities", "all resolved", not card.unresolved_ambiguities, 3,
          f"{len(card.unresolved_ambiguities)} unresolved",
          "an unresolved ambiguity means the engine will pick a default silently")
    check("ambiguities", "materiality flagged",
          any(a.material for a in card.ambiguities), 2, "",
          "without it a reviewer cannot tell which calls move the headline")
    check("ambiguities", "page citations",
          sum(1 for a in card.ambiguities if a.evidence_page) >= max(1, n_amb // 2), 1,
          f"{sum(1 for a in card.ambiguities if a.evidence_page)} of {n_amb} cited",
          "so the reviewer can check the ones that matter")

    check("benchmarks", "free alternatives run", len(card.benchmark_templates) >= 2, 3,
          f"{len(card.benchmark_templates)} defined",
          "the promotion question is not 'is the Sharpe good', it is whether "
          "this beats what the fund can already do for nothing")

    check("honesty", "n_configs_tried reflects the paper", card.n_configs_tried >= 1, 2,
          f"{card.n_configs_tried}",
          "the deflated Sharpe rests entirely on this number and nothing "
          "verifies it")
    check("honesty", "promotion question stated", len(_txt(card.notes)) > 60, 1, "",
          "one line on what would make this worth running")

    # ---- the dataset this paper deserves --------------------------------
    dp = getattr(card, "data_plan", None)
    check("data plan", "dataset designed from the paper", dp is not None, 3, "",
          "without it the card can only shop from what the fund already holds, "
          "and a paper quietly becomes whatever the existing data can answer")
    if dp is not None:
        check("data plan", "fields specified", len(dp.ideal) >= 1, 3,
              f"{len(dp.ideal)} field(s)", "nothing to procure against")
        check("data plan", "granularity argued",
              all(_txt(d.why_granularity) for d in dp.ideal) and bool(dp.ideal), 3,
              "", "granularity is where cost and correctness trade off hardest "
                  "and it is usually chosen by habit: a 21-day skip cannot be "
                  "computed monthly, and tick data answers nobody's question here")
        check("data plan", "history argued",
              all(_txt(d.why_history) for d in dp.ideal) and bool(dp.ideal), 2,
              "", "a start date nobody argued for is a start date that was "
                  "chosen by what the vendor happened to sell")
        check("data plan", "adjustments named",
              all(_txt(d.adjustments) for d in dp.ideal) and bool(dp.ideal), 2,
              "", "two vendors sell a file with the same NAME and only one lets "
                  "you run the strategy; the adjustments are the difference")
        check("data plan", "minimum viable subset marked",
              any(d.minimum_viable for d in dp.ideal), 3,
              f"{sum(1 for d in dp.ideal if d.minimum_viable)} of {len(dp.ideal)}",
              "without a smallest honest subset every request reads as essential "
              "and none can be traded off against cost")
        check("data plan", "alternatives rejected", len(dp.rejected_alternatives) >= 1, 2,
              f"{len(dp.rejected_alternatives)} considered",
              "a dataset with no rejected alternative was not designed, it was "
              "assumed")
        check("data plan", "optimality argued", len(_txt(dp.optimality_argument)) > 80, 3,
              "", "the section exists to answer 'are we testing this properly or "
                  "testing what we own'. Without the argument it answers neither")
        check("data plan", "what would change the answer",
              bool(_txt(dp.what_would_change_the_answer)), 1, "",
              "names the data that would overturn the conclusion, so a null "
              "result can be told apart from an underpowered one")

    # ---- which securities, and on whose word ----------------------------
    sel = getattr(card, "selection", None)
    check("selection", "rule stated", sel is not None and bool(_txt(sel.rule)), 3, "",
          "a selection nobody can re-derive on another date is not a strategy")
    if sel is not None and sel.explicit_securities:
        # Same name as the Gate A criterion on purpose: one concern should not
        # have two labels across the two surfaces a reviewer reads.
        check("selection", "named securities are verified",
              sel.verified_against not in ("", "UNVERIFIED"), 3,
              f"{len(sel.explicit_securities)} names, "
              f"verified_against={sel.verified_against or 'MISSING'}",
              "a model naming Indian stocks from memory produces a plausible, "
              "unverifiable list -- worse than no list, because it looks checked")
        check("selection", "named securities are dated", bool(sel.as_of), 2,
              sel.as_of or "", "index membership is true on a date, not in general")

    # ---- what will actually be run --------------------------------------
    bp = getattr(card, "backtest_plan", None)
    check("backtest plan", "plan present", bp is not None, 3, "",
          "if a human has to work out the window, the warmup or the benchmarks "
          "then Stage 02 did not finish and Gate A is doing the work")
    if bp is not None:
        check("backtest plan", "sample window argued",
              bool(bp.sample_start and bp.sample_end and _txt(bp.why_this_window)), 3,
              f"{bp.sample_start or '?'} -> {bp.sample_end or '?'}",
              "an unargued sample is the easiest place to pick a period that "
              "flatters the result")
        check("backtest plan", "warmup stated", bp.warmup_days is not None, 2,
              f"{bp.warmup_days}d" if bp.warmup_days is not None else "",
              "without it the estimator's burn-in silently becomes part of the "
              "track record, and runs start on different dates")
        check("backtest plan", "weights rule", bool(_txt(bp.weights_rule)), 3, "",
              "how a selection becomes a portfolio is half the result")
        check("backtest plan", "benchmarks with reasons",
              bool(bp.benchmarks) and all(b.get("why_this") for b in bp.benchmarks), 3,
              f"{len(bp.benchmarks)} named",
              "the promotion question is whether this beats what the fund can "
              "already do for nothing, so the comparator needs an argument")
        check("backtest plan", "must-beat list", len(bp.must_beat) >= 1, 2,
              f"{len(bp.must_beat)} named",
              "naming what it has to beat BEFORE the run is what stops the bar "
              "moving afterwards")
        check("backtest plan", "failure is defined",
              bool(_txt(bp.success_looks_like)) and bool(_txt(bp.failure_looks_like)), 3,
              "", "a plan that cannot fail is not a test, and a success criterion "
                  "written after the numbers is not a criterion")
        check("backtest plan", "failure modes anticipated",
              len(bp.known_failure_modes) >= 1, 1,
              f"{len(bp.known_failure_modes)} listed",
              "the ways this specific mechanism is known to break in India")

    # ---- what the model is asking for ----------------------------------
    check("asks", "data requests recorded", len(card.data_requests) >= 1, 2,
          f"{len(card.data_requests)} request(s)",
          "if nothing more would improve this test, say so explicitly; silence "
          "reads as nobody having asked")
    check("asks", "every request has a fallback",
          all(_txt(r.without_it) for r in card.data_requests), 3, "",
          "a request with no fallback is a demand, and a demand at Gate A "
          "stops the work rather than informing it")
    check("asks", "open questions recorded", len(card.open_questions) >= 1, 1,
          f"{len(card.open_questions)} question(s)",
          "the things the paper does not settle are what a human is for")
    return out
