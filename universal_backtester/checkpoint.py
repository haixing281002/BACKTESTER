"""A human checkpoint for a local backtest script, matching run_pipeline.py's
per-stage Gate A/Steps 03-07/Gate B pause: print what's been produced SO FAR
(absolute, clickable local paths) and stop for a typed approval before the
next stage runs. Every stage-producing script in this repo uses the same
pattern -- see run_pipeline.py's own `_checkpoint()` for the governed-card
path; this is the same idea for the plain scripts/*.py execution scripts.

NOTE (2026-10-06): run_pipeline.py's own `_checkpoint()` now defaults to NOT
pausing -- CLAUDE.md's "no human intervention up to Gate B" -- with a new
`--interactive` flag to opt back into the old pause-every-stage behavior.
This module's default (`auto_approve=False`, i.e. pause unless the caller's
own `--auto-approve` flag is passed) was NOT changed to match, because the
three scripts that call it (alquist/asness/accord_stock_selection) are not
part of the governed card chain this rule targets -- they are direct,
manually-invoked backtest scripts. If one of them is wired into the
autonomous Gate-A-to-Gate-B chain, flip its own `--auto-approve` default the
same way run_pipeline.py's `--interactive` flag does, rather than changing
this shared helper's default out from under scripts that still want a pause.

--auto-approve skips every pause deliberately (batch runs, CI). A
non-interactive run (piped stdin, a subprocess with no tty) skips it too,
but says so explicitly each time, rather than silently blocking forever on
input that will never come -- the same discipline as run_pipeline.py's gate.
"""
from __future__ import annotations

import os
import sys
from typing import List


def checkpoint(stage_name: str, produced: List[str], auto_approve: bool = False) -> bool:
    """Print `stage_name` and every path in `produced` (as absolute paths),
    then pause for a human's typed approval before the caller continues to
    the next stage. Returns True to continue, False to halt (the caller
    must stop immediately on False -- nothing past this point should run).
    """
    print(f"\n{'=' * 78}\n{stage_name}\n{'=' * 78}")
    if produced:
        print("Outputs produced so far this run:")
        for p in produced:
            print(f"  {os.path.abspath(p)}")
    else:
        print("(no outputs produced yet)")

    if auto_approve:
        print(f"\n[--auto-approve: continuing past {stage_name} without a pause]")
        return True
    if not sys.stdin.isatty():
        print(f"\n[no interactive terminal detected (stdin is not a TTY) -- continuing past "
              f"{stage_name} automatically. Run this in a real terminal, or pass --auto-approve "
              f"explicitly, for this to be a deliberate choice rather than an accident of how "
              f"this was run.]")
        return True

    answer = input(f"\n{stage_name} complete -- outputs listed above. Type 'approve' to "
                   f"continue to the next stage, anything else to halt here: ").strip().lower()
    if answer in ("approve", "y", "yes"):
        return True
    print(f"\nHALTED at {stage_name} -- not approved. No further steps ran past this point.")
    return False
