---
description: "Full pipeline on one paper, stages 00 through Gate B"
argument-hint: "<paper.pdf>"
---

# Paper to Position — the whole chain on `$1`

## First: is there a paper?

**If `$1` is empty, do not proceed and do not pick one.** Run:

```bash
python -c "from ros.papers import ask_for_a_paper; print(ask_for_a_paper())"
```

and show the result. It lists the PDFs already in the repo and says how to add a
new one. Then ask which paper they want, and wait.

There is no default paper. A default would mean a run that quietly analysed last
week's PDF looked exactly like a run that analysed theirs — and by the time that
surfaces, a result has been built on the wrong work.

**If `$1` is given, confirm what you are about to read before reading it:**

```bash
python -c "
from ros.papers import require_paper
p = require_paper('$1')
print(f'{p.path}\n  {p.size:,} bytes   sha256 {p.short_sha}   slug: {p.slug}')"
```

Say the title back to them once you have opened page 1. If it is not the paper
they meant, it is far cheaper to find out now than after a full run.

## The chain — ONE human checkpoint, at Gate B (changed 2026-10-06)

**Up to and including Gate A, nothing asks for approval.** Work stages 00
through Gate A assembly in one continuous pass, reporting each as you finish it,
without pausing for a go-ahead between them. Gate A's own job doesn't change —
it is still the card, displayed, still shows `decision: PENDING` verbatim — but
the pipeline no longer waits there for a human to say "continue." It is
informational: the record a human can always come back and read or override,
not a blocking step.

**The only thing that still stops Stage 02 moving forward is a real defect,
never an approval.** If `/gate-a`'s assembly reports `BLOCKED` (unresolved
ambiguities, a missing universe translation, a schema error), that is a
correctness problem — fix it yourself and redraft, the same way `/critique-card`
already works, rather than escalating it to a human. A human not having looked
yet is never a reason to stop; a card that is actually wrong is.

1. `/triage $1` — is this worth a full read? If not relevant, record the
   verdict, say why, and stop **this paper only** — there is nothing further to
   build on a paper that failed triage.
2. `/ingest $1` — read the rendered PDF properly. Decides **which Indian
   universe** and **what the strategy actually is**.
3. `/draft-card <analysis.json>` — write the Strategy Card. Defaults to
   `quick`: one card, the extracted strategy and a full `backtest_plan`, to see
   whether the mechanism shows up at all. There is exactly one card,
   `cards/<slug>.yaml` — see CLAUDE.md's "One card. Always."
4. `/critique-card <card.yaml> $1` — attack your own draft. Fold anything
   material back into the card and re-validate. Iterate here, not at a human.
5. `/map-data <card.yaml>` — resolve the card's data needs against the
   registry (NSE bhavcopy via `ros/data/master.py`, cm-market, Screener
   fundamentals — see "Data sources" below). A genuine shortfall is reported
   plainly; it is a procurement fact, not a pause.
6. `/gate-a <card.yaml>` — assemble the card display. Print:
   - `card.plain_summary()` first — what this strategy actually does, in
     plain English.
   - The full `gate_a_document()`.
   - **A local link to the card file itself** — the absolute path
     (`os.path.abspath('cards/<slug>.yaml')`), so a human can open the exact
     YAML being tested. This is mandatory on every Gate A print, not optional.
   Then **continue immediately** to Stage 03 — do not wait for a response.

```bash
python run_interpret.py --pdf $1
```

runs 00 through Gate A assembly deterministically in one pass and prints the
local path to everything it writes (the analysis JSON, the card, the Gate A
document) — use it to show the operator the whole first half without them
asking.

## After Gate A: still no human intervention, straight through to Gate B

7. `/run <card.yaml>` — the deterministic pipeline, stages 03-08. Runs in full:
   data binds (03), point-in-time snapshot (04), build + execute (05), research
   validation (06), portfolio validation (07) — no pause between any of these.
8. `/critique-results <report.txt>` — attack the output yourself. Fold findings
   back in (re-run if something material changes the numbers) rather than
   handing an uncritiqued report to Gate B.
9. `/gate-b <report.txt>` — assemble the IC briefing.
   **STOP HERE.** This is the one and only place this chain stops. The
   evidence supports something; you do not decide what happens, and no amount
   of earlier autonomy changes that — `decision: PENDING` until a named human
   records one (`run_pipeline.py --decision ... --decided-by ... --rationale ...`).

## Data sources (changed 2026-10-06)

All data for this chain comes from the fund's own feeds, not the Accord
Fintech panel (kept on disk, opt-in only — see CLAUDE.md): NSE bhavcopy
(`ros/data/nse_bhavcopy_ingest.py` → `ros/data/master.py`'s master CSV,
declared in `data/raw/MANIFEST.yaml`), cm-market for point lookups, and
Screener.in for fundamentals. Use all three where the card's `data_plan` or
`data_requirements` call for them rather than defaulting to whichever is
already loaded.

## At the end: list every file this run produced

After Gate B assembly (or after any stage, if asked to stop early), print the
local, absolute path to every file this run wrote or read — the paper, the
analysis JSON, the card YAML, the Gate A document (if saved), the report, any
charts, any workbook. A result nobody can open from the paths in front of them
is not a result they can act on.

Throughout: you interpret, code computes, a human allocates. If you find
yourself about to estimate a statistic in conversation, write code instead. If
you find yourself about to say "so we should approve this" anywhere before Gate
B, stop — that is not yours, ever, no matter how much of the chain now runs
without a pause.
