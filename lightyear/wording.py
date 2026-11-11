# Quant AI Researcher
"""Comparison words must follow the numbers (added 2026-10-30).

A model-written sentence such as "lower volatility (16.8% against 15.9%)" is wrong: 16.8 is the larger number. Every
text field that reaches the page or the workbook is scanned for "<comparative> <metric> (a% against b%)" and the
comparative is REGENERATED from a and b: "lower" only when a < b, "higher" only when a > b, and the two numbers equal
gives "the same". The original wording is kept in results["wording_corrections"] so a reader can see what was changed.
"""
import re

PAIRS = {"lower": "higher", "smaller": "larger", "shallower": "deeper", "less": "more", "fewer": "more",
         "cheaper": "dearer", "slower": "faster", "lighter": "heavier", "narrower": "wider", "weaker": "stronger"}
LESS_WORDS = set(PAIRS)                                     # the word that means "a is the smaller number"
MORE_WORDS = set(PAIRS.values()) | {"bigger", "greater", "steeper"}
SYNONYM_OF_MORE = {"bigger": "smaller", "greater": "lower", "steeper": "shallower"}
_RX = re.compile(r"\b(" + "|".join(sorted(LESS_WORDS | MORE_WORDS, key=len, reverse=True)) + r")\b"
                 r"(\s+[A-Za-z][A-Za-z \-']{0,50}?)\s*\((-?\d+(?:\.\d+)?)\s*%?\s*(?:against|vs\.?|versus)\s*(-?\d+(?:\.\d+)?)\s*%?\)",
                 re.IGNORECASE)


def _less_word(word):
    w = word.lower()
    if w in LESS_WORDS:
        return w
    if w in SYNONYM_OF_MORE:
        return SYNONYM_OF_MORE[w]
    return next(k for k, v in PAIRS.items() if v == w)


def _more_word(word):
    w = word.lower()
    if w in MORE_WORDS:
        return w
    return PAIRS[w]


_VOL = re.compile(r"volatility(?: of)?\s*\(?\s*(-?\d+(?:\.\d+)?)\s*%\s*(?:against|vs\.?|versus)\s*(-?\d+(?:\.\d+)?)\s*%\)?", re.IGNORECASE)
_RISK_CLAIM = re.compile(r"\b(did not come from|didn't come from|does not come from|not from|without|with no|at no|came with less|with less|carries less)"
                         r"\s+(extra|more|additional|added)?\s*(risk|volatility)\b", re.IGNORECASE)


def fix_risk_claim(text):
    """A sentence that quotes the strategy's volatility against the benchmark's and then claims the return came at no
    extra risk must agree with the two numbers: when the strategy's volatility is the HIGHER number the claim is replaced
    by 'came with more volatility'. Returns (text, changes)."""
    changes = []
    m = _VOL.search(text or "")
    if not m:
        return text, changes
    a, b = float(m.group(1)), float(m.group(2))
    if a <= b:
        return text, changes

    def repl(c):
        new = "came with more volatility"
        changes.append((c.group(0), new))
        return new

    return _RISK_CLAIM.sub(repl, text), changes


def fix_sentence(text):
    """Return (corrected text, list of (old phrase, new phrase))."""
    text, changes = fix_risk_claim(text)

    def repl(m):
        word, a, b = m.group(1), float(m.group(3)), float(m.group(4))
        if abs(a - b) < 1e-12:
            new = "the same"
        else:
            new = _less_word(word) if a < b else _more_word(word)
        if word[0].isupper():
            new = new.capitalize()
        if new.lower() != word.lower():
            changes.append((m.group(0), m.group(0).replace(word, new, 1)))
        return m.group(0).replace(word, new, 1)

    out = _RX.sub(repl, text or "")
    return out, changes


def fix_results(results):
    """Correct every prose field of a results.json dict in place; return the list of corrections made."""
    corrections = []
    for key in ("headline", "decisive_criterion"):
        if isinstance(results.get(key), str):
            results[key], ch = fix_sentence(results[key])
            corrections += [{"field": key, "was": o, "now": n} for o, n in ch]
    for key in ("strengths", "weaknesses", "notes"):
        items = results.get(key) or []
        for i, s in enumerate(items):
            if isinstance(s, str):
                items[i], ch = fix_sentence(s)
                corrections += [{"field": f"{key}[{i}]", "was": o, "now": n} for o, n in ch]
    for row in results.get("paper_vs_backtest") or []:
        if isinstance(row, dict) and isinstance(row.get("why_different"), str):
            row["why_different"], ch = fix_sentence(row["why_different"])
            corrections += [{"field": "paper_vs_backtest.why_different", "was": o, "now": n} for o, n in ch]
    if corrections:
        results["wording_corrections"] = corrections
    return corrections


def check_results(results):
    """Return the comparisons that are still wrong (should be empty after fix_results)."""
    bad = []
    for key in ("headline", "decisive_criterion", "strengths", "weaknesses", "notes"):
        v = results.get(key)
        for s in (v if isinstance(v, list) else [v]):
            if isinstance(s, str):
                _, ch = fix_sentence(s)
                bad += [o for o, _ in ch]
    return bad
