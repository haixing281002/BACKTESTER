# Quant AI Researcher
"""The analyst read at Gate B: a model's page on what the book's risk exposures say and how the strategy could be made
better. Written after the backtest, from the run's own files and, when it is there, the Barra site step's result.

The read is a file in the run folder, gate_b_read.json, with fixed headings and a list of suggestions. Each suggestion
is a change to TEST in a new run on a new card, never a change to this run. The read is an opinion written by a model:
it does not vote, it may not say approve or reject, it computes no number, and Gate B's status does not read it. When a
person records the decision, the read's sha256 is written into the decision record, so what they had in front of them
is fixed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

FILE = "gate_b_read.json"
HEADINGS = [("what_the_exposures_say", "What the risk exposures say"), ("where_the_return_came_from", "Where the return came from"),
            ("risks_carried", "Risks the book carries"), ("what_this_read_cannot_tell", "What this read cannot tell")]
SUGGESTION_KEYS = ("change", "why", "how_to_test")
# the read does not vote: none of the four decisions, and no advice on which to record
_VOTE = re.compile(r"\b(approve[ds]?|reject(?:ed|s)?|should (?:pass|fail)|recommend(?:s|ed)? (?:approval|rejection))\b", re.IGNORECASE)


def _bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def load(run_dir: str) -> dict[str, Any] | None:
    """The read as written, or None when the run has none. Raises ValueError when a heading or a suggestion field is
    missing, or when the text votes."""
    p = os.path.join(run_dir, FILE)
    if not os.path.isfile(p):
        return None
    d = json.loads(_bytes(p).decode("utf-8"))
    missing = [k for k, _ in HEADINGS if not str(d.get(k) or "").strip()]
    sug = d.get("suggestions")
    if not isinstance(sug, list) or not sug:
        missing.append("suggestions")
    else:
        missing += [f"suggestions[{i}].{k}" for i, s in enumerate(sug) for k in SUGGESTION_KEYS if not str((s or {}).get(k) or "").strip()]
    if missing:
        raise ValueError(f"{FILE} is missing: {missing}")
    text = " ".join([str(d[k]) for k, _ in HEADINGS] + [str(s[k]) for s in sug for k in SUGGESTION_KEYS])
    vote = _VOTE.search(text)
    if vote:
        raise ValueError(f"{FILE} votes on the decision ({vote.group(0)!r}); a read may not")
    return d


def sha256(run_dir: str) -> str | None:
    p = os.path.join(run_dir, FILE)
    return hashlib.sha256(_bytes(p)).hexdigest() if os.path.isfile(p) else None


def for_page(run_dir: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the page shows: the read under its fixed headings, or why there is nothing to show. After a decision, a read
    whose bytes differ from the ones recorded with the decision is shown as changed and its text is withheld."""
    try:
        d = load(run_dir)
    except (ValueError, json.JSONDecodeError) as e:
        return {"status": "invalid", "note": f"The analyst read at Gate B could not be shown: {e}"}
    if d is None:
        return {"status": "none", "note": "No analyst read at Gate B has been written for this run."}
    now = sha256(run_dir)
    pinned = (decision or {}).get("gate_b_read_sha256")
    if pinned and pinned != now:
        return {"status": "changed", "note": "The analyst read at Gate B was changed after the decision was recorded. Its text is withheld."}
    return {"status": "ok", "sections": [{"key": k, "heading": h, "text": str(d[k])} for k, h in HEADINGS],
            "suggestions": [{k: str(s[k]) for k in SUGGESTION_KEYS} for s in d["suggestions"]],
            "used_barra_site": bool(d.get("used_barra_site")), "sha256": now, "pinned": bool(pinned)}
