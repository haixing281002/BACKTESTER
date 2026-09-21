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

from ros.cards.schema import audit_data_requests, reconcile_data_plan

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

    def render(self, terse: bool = False) -> str:
        """The audit trail: proof each thing was checked.

        `terse` drops the evidence from PASSING rows. In the Gate A document
        every passing criterion's evidence is the card text rendered in full
        further up, so repeating it there was the single largest source of
        duplication in the report -- the universe rationale appeared twice, the
        minimum-viable field five times. A FAILING row always keeps its
        evidence: that is the one place the reason is not written anywhere else.
        """
        head = f"  {self.gate} (owner: {self.owner}) -> {'PASS' if self.passed else 'BLOCKED'}"
        rows = []
        for c in self.criteria:
            if terse and c.passed:
                val = "" if c.value is None else f"   [{c.value}]"
                rows.append(f"    [PASS] {c.name}{val}")
            else:
                rows.append(c.render())
        tail = f"\n    decision: {self.decision}" + (f" -- {self.rationale}" if self.rationale else "")
        return head + "\n" + "\n".join(rows) + tail

    def to_dict(self) -> Dict[str, Any]:
        return {"gate": self.gate, "owner": self.owner, "decision": self.decision,
                "passed": self.passed, "rationale": self.rationale,
                "criteria": [asdict(c) for c in self.criteria]}


def _india_for(card):
    """Derive the India requirements for a card, or None if that is not possible.

    Imported lazily: india_requirements imports nothing from governance today,
    but a gate reaching into a derivation module is the kind of edge that turns
    into a cycle later, and the cost of being careful here is one line.
    """
    try:
        from ros.india_requirements import derive
        return derive(card)
    except Exception:
        return None


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


def _where_this_runs(card, tc) -> List[str]:
    """WHERE the strategy operates, in Indian terms, as facts rather than prose.

    The universe section used to print ABOVE the gate header, which made the
    most consequential call at Stage 01 read as preamble to the thing a human
    was signing. And the brief's own [UNIVERSE] line carried the argument for
    the choice without ever saying what the choice IS in instruments: how many
    names, held or missing, inside the mandate or outside it.
    """
    W = _W
    ut = card.universe_translation
    if ut is None and tc is None:
        return []
    L = ["", "  " + "-" * W,
         "  WHERE THIS RUNS. The Indian universe, as instruments rather than "
         "as an argument.",
         "  " + "-" * W, ""]

    target = (tc.target if tc is not None else ut.target_universe) or "(none chosen)"
    L.append(f"    universe   : {target}"
             + (f"   [{ut.grade}]" if ut is not None and ut.grade else ""))
    if ut is not None and ut.mechanism_needs is not None:
        mn = ut.mechanism_needs
        L.append(f"    needs      : >= {mn.min_names} names, {mn.cap_segment} cap, "
                 f"{mn.min_history_years:g}y history, "
                 + ("ranks a cross-section" if mn.needs_cross_section
                    else "times one stream"))

    if tc is not None:
        L.append(f"    resolution : {tc.computed_resolution}"
                 + (f"   (card claims {tc.claimed_resolution})"
                    if tc.claimed_resolution and
                    tc.claimed_resolution != tc.computed_resolution else ""))
        if tc.held:
            L.append(f"    HELD ({len(tc.held)}): " + ", ".join(tc.held[:8])
                     + (" ..." if len(tc.held) > 8 else ""))
        if tc.missing:
            L.append(f"    MISSING ({len(tc.missing)}): " + ", ".join(tc.missing[:8])
                     + (" ..." if len(tc.missing) > 8 else ""))
            L.append("               -> these have to be supplied before anything runs")
        else:
            L.append("    MISSING: nothing. Every instrument this universe needs "
                     "is already held.")
        # Out of mandate is a fact about what the fund may HOLD, and it changes
        # what a result means, so it cannot sit in a notes list further down.
        for note in tc.notes:
            if "OUT OF MANDATE" in note.upper():
                L.append("")
                L.append("    !! OUT OF MANDATE -- the fund may TEST here but may not HOLD here.")
                for line in _wrap(note, W - 9):
                    L.append(f"       {line}")
        if tc.ranked:
            L.append("")
            L.append("    the code ranked these against what the mechanism needs "
                     "(the model chose; the code only scores):")
            for f in tc.ranked[:5]:
                u = f.universe
                flags = []
                if u.name == target:
                    flags.append("<- CHOSEN")
                if not u.in_mandate:
                    flags.append("OUT OF MANDATE")
                if f.disqualifying:
                    flags.append("disqualified")
                L.append(f"      {f.score:>5.1f}  {u.name:<38} n~{u.approx_breadth:<5}"
                         + ("  " + ", ".join(flags) if flags else ""))
    return L


def _what_it_takes(card, feasibility, india) -> List[str]:
    """What data this needs, where the fund stands today, and what India demands.

    Three answers to one question -- can this be run, and at what price -- that
    were printed in three places: the data plan below the gate, the feasibility
    shortfall at the very end of the report, and the India requirements after
    both. A reviewer deciding whether to buy data had to assemble them.
    """
    W = _W
    dp = getattr(card, "data_plan", None)
    if dp is None and feasibility is None and india is None:
        return []
    L = ["", "  " + "-" * W,
         "  WHAT IT TAKES TO RUN THIS, AND WHAT YOU ALREADY HAVE",
         "  " + "-" * W]

    # The dataset itself is NOT summarised here. card.plan_data() renders it in
    # full immediately above this block in the Gate A document, and a summary
    # that repeats it is how the same paragraph came to appear five times in one
    # report. This block answers only what the card cannot: do we HAVE it.

    rec = reconcile_data_plan(card, feasibility)
    if rec["checked"]:
        L += ["", "    ARE WE RUNNING ON THAT DATASET, OR ON WHAT WE HAVE?"]
        if rec["not_in_hand"]:
            L.append(f"      {len(rec['not_in_hand'])} of {len(rec['need'])} "
                     f"MINIMUM-VIABLE field(s) are NOT in hand -- the card asks "
                     f"for them itself:")
            for f in rec["not_in_hand"]:
                L.append(f"        {f}")
            L.append("      A run is still possible. It is not the test this card "
                     "specified, and any")
            L.append("      result has to be read as the proxy's answer, not the "
                     "design's.")
        else:
            L.append(f"      The card marks {len(rec['need'])} field(s) "
                     f"minimum-viable and links no open request to any of them, "
                     f"so by its own account the design is satisfied.")
        if rec["proxied"]:
            L.append(f"      standing in: " + "; ".join(rec["proxied"]))
        if rec["degraded"]:
            L.append(f"      degraded ({len(rec['degraded'])}): "
                     + ", ".join(rec["degraded"][:4])
                     + (" ..." if len(rec["degraded"]) > 4 else ""))

    if feasibility is not None:
        counts = feasibility.counts() if hasattr(feasibility, "counts") else {}
        L += ["", f"    WHERE YOU STAND: {feasibility.verdict}"
                  + ("   " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                     if counts else "")]
        for r in getattr(feasibility, "resolutions", []):
            if r.status == "AVAILABLE":
                continue
            L.append(f"      [{r.status}] {r.requirement}"
                     + (f" -> {r.resolved_to}" if r.resolved_to else ""))
            for line in _wrap(r.reason, W - 16):
                L.append(f"               {line}")
        if not any(r.status != "AVAILABLE"
                   for r in getattr(feasibility, "resolutions", [])):
            L.append("      Every series on this card is held outright. Nothing "
                     "to buy, nothing to proxy.")

    if india is not None:
        musts = india.blocking
        from_model = india.from_model
        L += ["", f"    WHAT INDIA DEMANDS OF THIS STRATEGY "
                  f"({len(musts)} non-negotiable of "
                  f"{len(india.requirements)} derived"
                  + (f"; {len(from_model)} read from the paper by a model)"
                     if from_model else ")")]
        for r in musts:
            L.append(f"      [{r.category.upper()}] {r.item}")
            for line in _wrap(r.why, W - 14):
                L.append(f"             {line}")
        for r in from_model:
            L.append(f"      [{r.category.upper()}] {r.item}"
                     f"   <- from the paper, by a model"
                     + (f" (p.{r.evidence_page})" if r.evidence_page else ""))
            for line in _wrap(r.why, W - 14):
                L.append(f"             {line}")
        rest = len(india.requirements) - len(musts) - len(from_model)
        if rest:
            L.append(f"      + {rest} advisory requirement(s) in full below, under "
                     f"WHAT IT TAKES TO RUN THIS IN INDIA.")
        if india.unaddressed_inputs:
            L.append("")
            L.append("      ! NOBODY HAS LOOKED AT THESE. The rules match on "
                     "keywords, so an input they")
            L.append("        cannot read raises nothing and stays silent -- which "
                     "is how a requirement")
            L.append("        goes missing. A model should address each in "
                     "`india_notes`:")
            for u in india.unaddressed_inputs:
                L.append(f"          {u}")
    return L


def _line(text, fallback, width=86):
    """A headline if the model wrote one, else a visibly TRUNCATED first clause.

    The ellipsis is the honesty: a reader can tell at a glance whether they are
    reading something somebody composed for this sheet or the first 86
    characters of a paragraph that continues below.
    """
    h = " ".join(str(text or "").split())
    if h:
        return h
    f = " ".join(str(fallback or "").split())
    if len(f) <= width:
        return f or "-- not stated --"
    cut = f[:width].rsplit(" ", 1)[0]
    return cut + " ..."


def gate_a_summary(card, result, translation_check=None, feasibility=None,
                   india=None, completeness=None) -> str:
    """ONE PAGE. Everything a human must personally rule on, with pointers.

    The full document renders the card once, which was the right fix for saying
    things three times -- and still runs to seven hundred lines, because the
    card is seven hundred lines of argued work. A reviewer does not need the
    argument to decide; they need to know WHAT they are deciding, WHO owns it,
    and WHERE to read the argument if a line looks wrong.

    So every row here is one line plus a section pointer. Nothing is summarised
    away: the pointer leads to the full text, which is directly below.

    The one-liners come from the card's `headline` fields, written by the model
    at Stage 02, because compressing an argument to a line is a judgement.
    Mechanical extraction can only truncate, and a headline cut mid-sentence is
    what made the previous gate unreadable. Where a card carries none, the row
    falls back to a visibly truncated clause rather than pretending.

    The ORDERING is mechanical and deliberately not the model's: blocking items,
    then the things this repo has learned are most often wrong -- a low
    confidence material call, an unverified list, a design running on proxies --
    then everything else. A model that ranked its own work would put the item it
    was most pleased with first.
    """
    W = _W
    blocking = [c for c in result.criteria if not c.passed and c.blocking]
    rows = []           # (priority, who, where, line, note)

    def row(pri, who, where, line, note=""):
        rows.append((pri, who, where, line, note))

    for c in blocking:
        row(0, "STOP", "top", c.name, " ".join(c.evidence.split())[:140])

    cv = getattr(card, "convertibility", None)
    if cv is not None:
        row(1, "researcher", "S6",
            _line(cv.headline, f"{cv.verdict}: {cv.weakest_link}"),
            f"verdict {cv.verdict}, confidence {cv.confidence}")

    ut = card.universe_translation
    if ut is not None:
        risk = ut.transfer_risks[0] if ut.transfer_risks else ""
        row(2, "researcher", "S1",
            f"{ut.source_universe} -> {ut.target_universe or '(none)'}"
            f"  [{ut.grade or '?'}]", _line("", risk))
    if translation_check is not None:
        for n in translation_check.notes:
            if "OUT OF MANDATE" in n.upper():
                row(1, "pm", "S1", "chosen universe is OUT OF MANDATE",
                    "the fund may TEST here and may not HOLD here")
        if translation_check.missing:
            row(0, "data_owner", "S1",
                f"{len(translation_check.missing)} instrument(s) MISSING",
                ", ".join(translation_check.missing[:3]))

    st = card.strategy
    if st is not None and st.is_long_short:
        row(2, "pm", "S2", "paper is long-short; this fund cannot short",
            _line("", st.long_only_adaptation))
    if st is not None and st.engine_template == "NEEDS_NEW_TEMPLATE":
        row(1, "researcher", "S2", "no registered template fits this strategy",
            "a human implements it before anything runs")

    rec = reconcile_data_plan(card, feasibility)
    if rec["checked"] and rec["not_in_hand"]:
        row(1, "pm", "S3",
            f"{len(rec['not_in_hand'])} of {len(rec['need'])} minimum-viable "
            f"field(s) NOT in hand",
            "a legitimate run, but not the test this card specified")

    sel = getattr(card, "selection", None)
    if sel is not None and sel.explicit_securities and \
            sel.verified_against in ("", "UNVERIFIED"):
        row(1, "data_owner", "S4",
            f"{len(sel.explicit_securities)} named securities are UNVERIFIED",
            "a recalled list looks checked and is not")

    bp = getattr(card, "backtest_plan", None)
    if bp is not None:
        row(3, "pm", "S5",
            f"the bar: must beat {', '.join(bp.must_beat)[:70]}",
            f"sample {bp.sample_start} -> {bp.sample_end}, named before the run")
    row(3, "researcher", "S2",
        f"costs {card.costs.spread_bps:.0f}bp round trip, lag "
        f"{card.signal.lag_days}d",
        "a US paper's 5bp is the commonest way an Indian backtest lies")

    for a in card.material_ambiguities:
        pri = 1 if a.confidence == "low" else 3
        row(pri, "researcher", "S7",
            _line(a.headline, f"{a.field}: {a.resolution}"),
            f"{a.field}, confidence {a.confidence}"
            + (f", p.{a.evidence_page}" if a.evidence_page else ""))

    for q in card.open_questions:
        row(0 if q.blocks_run else 2, q.ask_of, "S7",
            _line(q.headline, q.question),
            "BLOCKS THE RUN" if q.blocks_run
            else "assumed: " + _line("", q.what_i_assumed, 70))

    order = {"blocking": 0, "high": 2, "nice_to_have": 4}
    for r in getattr(card, "data_requests", []) or []:
        row(order.get(r.priority, 3), "data_owner", "S8",
            _line(r.headline, r.item),
            f"[{r.priority}] if declined: " + _line("", r.without_it, 60))

    if india is not None and india.unaddressed_inputs:
        row(2, "researcher", "S3",
            f"{len(india.unaddressed_inputs)} strategy input(s) reached no "
            f"India rule", "nobody has looked at these")

    rows.sort(key=lambda t: t[0])
    L = ["  " + "=" * W,
         "  GATE A  --  ONE PAGE.  Everything you personally decide.",
         "  " + "=" * W,
         f"  {card.paper.id}   ({card.intent.mode})",
         f"  {len(rows)} item(s) to rule on   |   {len(blocking)} blocking"
         + (f"   |   card completeness {completeness.score:.0%}"
            if completeness is not None else ""),
         "",
         "  Every line points into the full document below. Nothing here "
         "replaces it;",
         "  if a line looks wrong, S<n> is where the argument for it is "
         "written out.",
         "  " + "-" * W,
         f"  {'#':<3} {'WHO':<11} {'GO':<4} WHAT YOU ARE RULING ON",
         "  " + "-" * W]
    for i, (pri, who, where, line, note) in enumerate(rows, 1):
        mark = "STOP" if pri == 0 else where
        for j, seg in enumerate(_wrap(line, W - 22)):
            L.append(f"  {str(i) + '.' if j == 0 else '':<3} "
                     f"{who if j == 0 else '':<11} {mark if j == 0 else '':<4} "
                     f"{seg}")
        for seg in _wrap(note, W - 24):
            L.append(f"  {'':<3} {'':<11} {'':<4}   {seg}")
    L += ["  " + "-" * W,
          "  NOTHING HERE IS DECIDED. The decision is a named human's, and no "
          "code",
          "  in this repo assigns one.",
          "  " + "=" * W]
    return "\n".join(L)


def gate_a_document(card, result, translation_check=None, feasibility=None,
                    india=None, completeness=None) -> str:
    """GATE A IS THE CARD, rendered once, in the order a human decides in.

    The card already contains everything a reviewer needs -- it is the best
    artifact this pipeline produces. What Gate A kept doing was RETELLING it:
    a brief that quoted some sections, then plan() and asks() printing those
    same sections again below, then a criteria list carrying the same text a
    third time as "evidence". Measured on the worked example, the universe
    rationale appeared twice, the convertibility weakest link three times and a
    minimum-viable data field five times, across 888 lines.

    So this renders each part of the card EXACTLY ONCE, placed where the
    decision about it gets made -- the dataset next to what the fund actually
    holds, the run next to the bar it must clear, the ambiguities next to the
    questions they raise -- and interleaves only what the card cannot know:
    the universe fit the code scored, the feasibility position, the India rules,
    and the checklist.

    Nothing is summarised and nothing is dropped. The only thing made shorter is
    the chrome.
    """
    W = _W
    blocking = [c for c in result.criteria if not c.passed and c.blocking]
    warns = result.warnings
    pa = card.paper

    def rule(ch="-"):
        return "  " + ch * W

    def head(n, title):
        # "S<n>" so the one-page sheet's pointers resolve by a literal search.
        return ["", rule("="), f"  S{n}. {title}", rule("=")]

    L = [rule("="),
         "  GATE A  --  THE STRATEGY CARD, AS A HUMAN READS IT",
         rule("="),
         f"  {pa.id}   ({card.intent.mode})",
         f"  {pa.title}" if pa.title else "",
         f"  paper: {pa.source_file or 'NOT RECORDED'}",
         f"  sha256: {pa.source_sha256 or 'NOT RECORDED'}",
         f"  {len(result.criteria)} criteria checked   {len(blocking)} blocking   "
         f"{len(warns)} worth a look"
         + (f"   card completeness {completeness.score:.0%}"
            if completeness is not None else "")]
    L = [x for x in L if x != ""] if False else L

    if blocking:
        L += ["", rule("!"),
              "  STOP. THESE BLOCK THE GATE -- nothing runs until they are fixed.",
              rule("!")]
        for i, c in enumerate(blocking, 1):
            L.append(f"  {i}. {c.name}"
                     + ("" if c.value is None else f"   [{c.value}]"))
            for line in _wrap(c.evidence, W - 8):
                L.append(f"       {line}")

    L += ["", rule("-"), "  AT A GLANCE", rule("-")]
    L.append(card.at_a_glance())

    # 1 -- where, as instruments. Card's translation + the code's scoring.
    L += head(1, "WHERE THIS RUNS")
    L += _where_this_runs(card, translation_check)[1:]   # drop its own rule
    ut = card.universe_translation
    if ut is not None:
        L += ["", "  WHY HERE AND NOT SOMEWHERE ELSE (the model's argument)"]
        for line in _wrap(ut.rationale, W - 6):
            L.append(f"      {line}")
        if ut.why_not_alternatives:
            L += ["", "  WHY NOT THE RUNNERS-UP"]
            for line in _wrap(ut.why_not_alternatives, W - 6):
                L.append(f"      {line}")
        if ut.transfer_risks:
            L += ["", "  WHAT BREAKS IN THIS TRANSLATION (particular to this paper)"]
            for r in ut.transfer_risks:
                for i, line in enumerate(_wrap(r, W - 10)):
                    L.append(f"      {'-' if i == 0 else ' '} {line}")
    if translation_check is not None and translation_check.caveats:
        # The catalogued caveats for this correspondence: generic to Indian
        # equities rather than to this paper, and attached by the registry
        # rather than argued by the model. Kept here because removing the old
        # STEP 02c preamble would otherwise have dropped them entirely.
        L += ["", "  CATALOGUED CAVEATS FOR THIS CORRESPONDENCE (attach to every "
                  "result computed here)"]
        for cav in translation_check.caveats:
            for i, line in enumerate(_wrap(cav, W - 10)):
                L.append(f"      {'-' if i == 0 else ' '} {line}")

    # 2 -- what it actually is.
    L += head(2, "WHAT THE STRATEGY IS")
    st = card.strategy
    if st is None:
        L.append("  NO RECONSTRUCTION. A template name is not a strategy.")
    else:
        L.append(f"  {st.signal_name or '(unnamed)'}   "
                 f"[{'cross-sectional' if st.cross_sectional else 'time-series'}]"
                 f"   engine: {st.engine_template or '(unset)'}"
                 f"   confidence: {st.confidence}")
        for label, val in (("signal", st.signal_definition),
                           ("formation", st.formation_rule),
                           ("weighting", st.weighting_rule),
                           ("rebalance", st.rebalance_frequency),
                           ("holding", st.holding_period),
                           ("inputs", ", ".join(st.inputs_required))):
            if str(val or "").strip():
                for i, line in enumerate(_wrap(str(val), W - 16)):
                    L.append(f"    {label if i == 0 else '':<11} {line}")
        for k in st.constraints:
            for i, line in enumerate(_wrap(k, W - 16)):
                L.append(f"    {'constraint' if i == 0 else '':<11} {line}")
        if st.is_long_short:
            L += ["", "  THIS FUND CANNOT SHORT. What was dropped, and what it cost:"]
            for line in _wrap(st.long_only_adaptation or "NOT STATED", W - 6):
                L.append(f"      {line}")
            L.append("      A DIFFERENT strategy from the paper's. Never scored "
                     "against its numbers.")
        if st.engine_template == "NEEDS_NEW_TEMPLATE":
            L += ["", "  NO REGISTERED TEMPLATE FITS. A human implements this first:"]
            for line in _wrap(st.template_gap, W - 6):
                L.append(f"      {line}")
        L.append(f"    pages      {st.evidence_pages or 'none cited'}")

    # 3 -- the dataset, in full, then whether we have it.
    L += head(3, "THE DATASET THIS PAPER DESERVES, AND WHAT WE HOLD")
    L.append(card.plan_data(W, banner=False))
    L += _what_it_takes(card, feasibility, india)[1:]

    # 4 / 5 -- securities and the run.
    L += head(4, "WHICH SECURITIES")
    L.append(card.plan_selection(W, banner=False))
    L += head(5, "WHAT WILL BE RUN, AND THE BAR IT MUST CLEAR")
    L.append(card.plan_run(W, banner=False))

    # 6 -- the model's opinion, clearly labelled.
    L += head(6, "CAN THIS BECOME SOMETHING WE COULD HOLD?")
    L.append(card.convertibility_block())

    # 7 -- what a human personally owns.
    L += head(7, "THE JUDGEMENT CALLS -- a model made each; you can overturn any")
    for cl in judgement_calls(card, translation_check):
        if cl["tag"] in ("UNIVERSE", "CONVERTIBLE?", "THE BAR", "LONG-ONLY"):
            continue          # rendered in full in sections 1, 2, 5 and 6
        who = f"   <- {cl['who']}" if cl["who"] else ""
        tag = f"  [{cl['tag']}] "
        hl = _wrap(cl["headline"] + who, W - len(tag)) or [""]
        L.append("")
        L.append(tag + hl[0])
        for line in hl[1:]:
            L.append(" " * len(tag) + line)
        for line in _wrap(cl["detail"], W - 8):
            L.append(f"       {line}")

    # 8 -- the asks.
    # requests only -- the open questions are judgement calls and were rendered
    # in section 7. Printing them in both places is what made the volatility-cap
    # question appear twice in one document.
    L += head(8, "WHAT THE MODEL IS ASKING YOU FOR, AND WHAT SAYING NO COSTS")
    L.append(card.asks(requests_only=True))

    # 9 -- the checklist, terse.
    L += head(9, "THE CHECKLIST")
    if completeness is not None:
        L.append(completeness.render(only_missing=True))
        L.append("")
    L.append(result.render(terse=True))
    if warns:
        L += ["", "  WORTH A SECOND LOOK (does not block)"]
        for c in warns:
            L.append(f"    - {c.name}"
                     + ("" if c.value is None else f"   [{c.value}]"))

    L += ["", rule("="),
          "  NOTHING ABOVE IS DECIDED. Gate A produces this document; the "
          "decision is a",
          "  named human's, and no code in this repo assigns one.",
          rule("=")]
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

    # ---- is the run the card's own design, or a proxy of it? -------------
    # Feasibility answers "does every NAMED series resolve", which is GO even
    # when proxies and degraded series stand in. The card's own minimum-viable
    # dataset is a different question and nothing asked it, so a card could
    # design a dataset, hold none of it, and read "no shortfall".
    rec = reconcile_data_plan(card, feasibility)
    if rec["checked"] and rec["need"]:
        c.append(Criterion(
            "the run uses the dataset the card designed",
            not rec["not_in_hand"],
            value=(f"{len(rec['not_in_hand'])} of {len(rec['need'])} "
                   f"minimum-viable not in hand" if rec["not_in_hand"]
                   else f"all {len(rec['need'])} minimum-viable satisfied"),
            blocking=False,
            evidence=("named in full in the dataset section -- the card asks "
                      "for them itself, so it is running on a substitute for "
                      "its own minimum viable dataset"
                      if rec["not_in_hand"] else
                      "no open request names a minimum-viable field")))

    # ---- did anyone look at what the rules could not read? ---------------
    # Non-blocking: an unread input is a gap in coverage, not a proven fault.
    # But it must be a tracked row rather than a line of prose, because the
    # failure mode is silence -- a requirement that never gets raised.
    india = _india_for(card)
    if india is not None and india.unmatched_inputs:
        unread = india.unaddressed_inputs
        c.append(Criterion(
            "every strategy input reached the India rules", not unread,
            value=(f"{len(unread)} unread" if unread else
                   f"all {len(india.unmatched_inputs)} covered"),
            threshold=0, blocking=False,
            evidence=("; ".join(unread) + " -- keyword matching could not read "
                      "these, and no india_notes entry addresses them, so no "
                      "India requirement was raised from them at all"
                      if unread else
                      "inputs the patterns could not read are covered by "
                      "india_notes entries")))

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
