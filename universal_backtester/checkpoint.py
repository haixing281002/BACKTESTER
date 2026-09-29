"""A human checkpoint for a local backtest script, matching run_pipeline.py's
per-stage Gate A/Steps 03-07/Gate B pause: print what's been produced SO FAR
(absolute, clickable local paths) and stop for a typed approval before the
next stage runs. Every stage-producing script in this repo uses the same
pattern -- see run_pipeline.py's own `_checkpoint()` for the governed-card
path; this is the same idea for the plain scripts/*.py execution scripts.

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
