---
name: pipeline-stage-checkpoint
description: "Enforce the fund's 4th non-negotiable (CLAUDE.md) -- a model never advances to the next pipeline stage without being told to. Use this after completing ANY stage of this repo's pipeline (Stage 00 through Gate B) in-session, whether working through a slash command, run_interpret.py/run_pipeline.py, or a direct scripts/*.py backtest. Also use when reviewing whether a past turn violated this rule."
---

# Pipeline stage checkpoint

CLAUDE.md's 4th non-negotiable, verbatim:

> A model never advances to the next stage without being told to. Every stage
> in the pipeline table — not just Gate A and Gate B — ends with the model
> stopping, showing what it produced, and waiting for the operator to say to
> continue.

This applies whether the pipeline is driven through `run_interpret.py` /
`run_pipeline.py`, a direct `scripts/*.py` backtest, or performed in-session
by following `.claude/commands/*.md`. It is a CODE-level rule where code is
running (see `universal_backtester/checkpoint.py` and `run_pipeline.py`'s own
`_checkpoint()`), and a CONVERSATION-level rule when a model is doing the
work itself, in the chat, rather than running a script.

## What this means in practice, at the code level

Every stage-producing script in this repo already enforces this via the
shared `checkpoint()` helper:

```python
from universal_backtester.checkpoint import checkpoint

if not checkpoint("STAGE 2 OF 4 -- BACKTEST EXECUTED", produced, auto_approve=args.auto_approve):
    return
```

`produced` is a running list of every local output file's absolute path
written so far — printed before the pause, so a human approving stage N can
actually see what stage N wrote. `--auto-approve` (an argparse flag every
script and `run_pipeline.py` exposes) skips every pause deliberately, for
batch runs; a non-interactive run (piped stdin, a subprocess, no tty) skips
it too but says so explicitly rather than blocking forever.

**When adding a new stage-producing script**, wire it in the same way: import
`checkpoint()`, track a `produced: list` from the top of `main()`, append
every output path as it's written, and call `checkpoint(...)` at each natural
stage boundary (after data loads, after the backtest runs, after each major
output group is written, and once more at the very end). See
`scripts/alquist_2018_india_small_cap_backtest.py` or
`scripts/asness_2015_india_value_longshort_backtest.py` for the full pattern
across 4-5 stages.

**When adding a check for this**, `tests/test_universal_backtester_checkpoint.py`
is the reference: it verifies `--auto-approve` and a non-interactive stdin
both skip cleanly, that "approve"/"yes" continue, that anything else halts,
and that printed paths are absolute.

## What this means in practice, in a conversation (no code running)

When you (the model) are working through a stage yourself — reading a paper
for Stage 00/01, drafting a card for Stage 02, assembling Gate A — do not
write "moving to Stage 01" or "now let's draft the card" and continue in the
same turn. Instead:

1. Finish the current stage's actual work.
2. Report what you produced (the verdict, the card section, the gate queue —
   whatever this stage's output is).
3. Stop. End the turn. Wait for the operator's next message before starting
   the next stage.

This holds even in a multi-paper session, and even when you're confident the
operator will say yes — "continuing since you'll probably approve" is exactly
the failure this rule exists to prevent. Gate A and Gate B are where a
*decision* gets recorded; this is a narrower, more frequent checkpoint so a
paper never runs ahead of the human reading it.

## Where NOT to over-apply this

This rule is about the **research pipeline's own stages** (00 through Gate B,
Steps 03-08, and the direct backtest scripts' own internal stages). It is not
a blanket rule that every reply in this repo must be one sentence long —
engineering work on the pipeline itself (writing code, fixing a bug, building
a test, answering a question about the architecture) is not "advancing a
pipeline stage" and does not require a pause after every file edit. If it's
ambiguous which regime you're in, ask.
