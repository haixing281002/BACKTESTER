# Quant AI Researcher
"""The analyst read at Gate A (Wave 6, Step 9): one page written by the model BEFORE any backtest is run.

The read is a file in the run folder, analyst_read.json, with fixed headings. When the card is approved the read is
pinned with it: its own sha256, the card's sha256, and one sha256 over the card's bytes followed by the read's bytes.
After that the file cannot be changed without the page saying so: a read whose bytes no longer match the pin is shown
as changed and its text is withheld. The read is an opinion written by a model. It is never a decision, it computes no
number, and Gate B does not read it.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

FILE = "analyst_read.json"
HEADINGS = [("claims", "What the paper claims"), ("why_it_should_work", "Why it should work"), ("expect_in_india", "What to expect in India"),
            ("data_and_feasibility", "Data and feasibility"), ("risks_and_traps", "Risks and traps"),
            ("what_would_change_my_mind", "What would change my mind")]
READS = ("backtest as written", "backtest with listed changes", "do not backtest")
BEFORE, AFTER = "before any backtest", "after the fact"


def _bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def load(run_dir: str) -> dict[str, Any] | None:
    """The read as written, or None when the run has none. Raises ValueError when a heading is missing or the read is
    not one of the three allowed."""
    p = os.path.join(run_dir, FILE)
    if not os.path.isfile(p):
        return None
    d = json.loads(_bytes(p).decode("utf-8"))
    missing = [k for k, _ in HEADINGS if not str(d.get(k) or "").strip()] + [k for k in ("read", "read_reason") if not str(d.get(k) or "").strip()]
    if missing:
        raise ValueError(f"{FILE} is missing: {missing}")
    if d["read"] not in READS:
        raise ValueError(f"{FILE} read must be one of {READS}, got {d['read']!r}")
    return d


def pin(run_dir: str, card_path: str, at: str, written: str = BEFORE) -> dict[str, Any] | None:
    """Hash the read with the card. None when there is no read or no card to pin it to."""
    p = os.path.join(run_dir, FILE)
    if not os.path.isfile(p) or not os.path.isfile(card_path):
        return None
    load(run_dir)
    card, read = _bytes(card_path), _bytes(p)
    return {"sha256": hashlib.sha256(read).hexdigest(), "card_sha256": hashlib.sha256(card).hexdigest(),
            "card_and_read_sha256": hashlib.sha256(card + read).hexdigest(), "pinned_at": at, "written": written}


def for_page(run_dir: str, pinned: dict[str, Any] | None) -> dict[str, Any]:
    """What the page shows: the read under its fixed headings with its pin, or why there is nothing to show."""
    try:
        d = load(run_dir)
    except (ValueError, json.JSONDecodeError) as e:
        return {"status": "invalid", "why": str(e)[:200]}
    if d is None:
        return {"status": "none", "why": "No analyst read was written for this run."}
    sha = hashlib.sha256(_bytes(os.path.join(run_dir, FILE))).hexdigest()
    if pinned and pinned.get("sha256") != sha:
        return {"status": "changed", "why": "The read on disk is not the one that was pinned with the card, so it is not shown.", "pin": pinned}
    return {"status": "pinned" if pinned else "not pinned", "pin": pinned, "written": (pinned or {}).get("written", BEFORE),
            "sections": [{"heading": h, "text": d[k]} for k, h in HEADINGS], "read": d["read"], "read_reason": d["read_reason"],
            "listed_changes": list(d.get("listed_changes") or []), "label": "Written by the model. An opinion, not a decision."}
