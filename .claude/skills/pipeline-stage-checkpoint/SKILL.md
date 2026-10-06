---
name: pipeline-stage-checkpoint
description: "Enforce the fund's pipeline-pause rule (CLAUDE.md, changed 2026-10-06) -- the chain from Stage 00 through Stage 07 now runs without pausing for a human; Gate B is the ONE stop. Use this after completing ANY stage of this repo's pipeline (Stage 00 through Gate B) in-session, whether working through a slash command, run_interpret.py/run_pipeline.py, or a direct scripts/*.py backtest. Also use when reviewing whether a past turn violated this rule, in either direction -- pausing where it shouldn't, or reaching Gate B without stopping."
---

# Pipeline stage checkpoint

**Changed 2026-10-06.** This used to require a pause after every stage,
Gate A included. It no longer does. CLAUDE.md now reads:

> Up to and including Gate A, nothing asks for approval... After Gate A: still
> no human intervention, straight through to Gate B.

Gate A still gets assembled and displayed in full — the card, `plain_summary()`,
a local link to the YAML file, the completeness score, the asks — exactly as
before. What changed is whether anything WAITS for a response to it. It does
not. The chain runs from Stage 00 straight through Gate A's display and on
through Stage 07 in one continuous pass. **Gate B is the only stop.**

This applies whether the pipeline is driven through `run_interpret.py` /
`run_pipeline.py`, a direct `scripts/*.py` backtest, or performed in-session by
following `.claude/commands/*.md`.

## What still stops the chain — defects, never approvals

The one thing that halts progress before Gate B is a real problem, not a
missing sign-off:

- **Gate A reports `BLOCKED`** (unresolved material ambiguities, a missing
  universe translation, a schema error): fix the card and redraft it
  yourself — `/critique-card` then `/draft-card` again — the same way you'd
  iterate on your own work. Do not stop to ask; a human not having looked yet
  was never the problem, an actually-wrong card is.
- **Data genuinely is not available** (Stage 03/`/map-data` finds a real
  shortfall against the registry): report it plainly. This is a procurement
  fact, not a request for permission, and it is not a reason to fabricate a
  substitute series to keep moving.
- **Triage fails** (Stage 00 finds the paper irrelevant): stop working on
  *this paper*, record why, and move to the next one if there is one.

None of these are the old "wait for the operator" pause. They are places the
chain cannot honestly continue, which is a different thing from a place it
is choosing not to without being told.

## What this means at the code level

Every stage-producing script still carries the shared `checkpoint()` helper
(`universal_backtester/checkpoint.py`, `run_pipeline.py`'s own
`_checkpoint()`) — it is not being removed, because a human may still want to
step through a run manually. But the DEFAULT for a run under this chain is now
`--auto-approve`: pass it (or the moral equivalent for a script that doesn't
expose the flag) so the run proceeds stage-to-stage on its own, the way the
in-session conversation now does. `produced`, the running list of every local
output file's absolute path, still gets tracked and still gets printed at
each stage boundary and at the end — the chain not pausing to ask doesn't mean
it stops showing its work.

**When adding a new stage-producing script**, wire it the same way as before:
import `checkpoint()`, track `produced: list` from the top of `main()`, append
every output path as it's written, call `checkpoint(..., auto_approve=True)`
(or respect a flag that defaults to it) at each natural stage boundary. See
`scripts/alquist_2018_india_small_cap_backtest.py` or
`scripts/asness_2015_india_value_longshort_backtest.py` for the pattern.

## What this means in a conversation (no code running)

When you (the model) are working through Stage 00 through Stage 07 yourself —
reading a paper, drafting a card, assembling Gate A, running validation —
finish each stage, report what you produced, and **continue to the next stage
in the same turn.** This is the opposite of the old rule: "moving to Stage 01"
in the same turn a stage finished is now the correct behavior, not the failure
it used to be.

The one place this reverses is Gate B:

1. Finish Stage 07 (portfolio validation) and `/critique-results`.
2. Assemble the Gate B briefing (`/gate-b`).
3. **Stop. End the turn.** Print the evidence-supports line and the exact
   `run_pipeline.py --decision ...` command a human runs. Wait for the
   operator's next message. Do not record a decision yourself, ever — that
   remains the one thing no amount of autonomy upstream changes.

## At the end, always print the local file links

Whichever stage you stop at — Gate B in the normal case, or an earlier defect
that genuinely blocks progress — print the absolute local path to every file
this run wrote or read: the paper, the analysis JSON, the card YAML, the Gate A
document (if saved to a file), the report, any charts, any workbook. `produced`
already tracks this at the code level; surface all of it, not just the last
file written.

## Where NOT to over-apply this

This rule is about the **research pipeline's own stages** (00 through Gate B).
It is not a blanket rule that every reply in this repo must run to completion
unprompted — engineering work on the pipeline itself (writing code, fixing a
bug, building a test, answering a question about the architecture) is not
"advancing a pipeline stage" and is unaffected by this skill either way. If
it's ambiguous which regime you're in, ask.
