"""Text I/O must not depend on the machine's locale.

A paper is full of Greek letters and maths symbols, and they travel: paper ->
extraction -> Strategy Card -> report -> library -> lineage record. Every one of
those hops is a text file.

Python picks the encoding for `open()` from the locale when you do not name one.
That is utf-8 on this repo's CI and on macOS, and cp1252 on a default Windows
install -- so code that reads and writes cards and reports perfectly well here
raises UnicodeDecodeError or UnicodeEncodeError on a colleague's laptop, on the
same input. It did: `python -m pytest` on Windows died reading this repo's own
source, and `run_pipeline.py` produced completely empty output because the
UnicodeEncodeError discarded a block-buffered stdout.

These tests fail on the machine that introduces the regression, not on the one
that eventually suffers it.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", "outputs", ".venv", "venv"}

# Binary modes carry no encoding, and these helpers are encoding-aware already.
BINARY = {"rb", "wb", "ab", "r+b", "w+b", "rb+", "wb+"}


def _sources():
    for p in sorted(ROOT.rglob("*.py")):
        if SKIP_DIRS & set(p.parts):
            continue
        yield p


def _mode_of(call: ast.Call) -> str:
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        return str(call.args[1].value)
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return "r"


def _names_encoding(call: ast.Call) -> bool:
    return any(kw.arg == "encoding" for kw in call.keywords)


def test_every_text_open_names_its_encoding():
    offenders = []
    for p in _sources():
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            # builtin open(...) only -- pdfplumber.open, tarfile.open, zipfile
            # and friends have their own signatures and no encoding argument.
            if not (isinstance(fn, ast.Name) and fn.id == "open"):
                continue
            if _mode_of(node) in BINARY or _names_encoding(node):
                continue
            offenders.append(f"{p.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not offenders, (
        "open() without encoding= falls back to the locale codepage, which is "
        "cp1252 on a default Windows install:\n  " + "\n  ".join(offenders))


def test_every_read_text_names_its_encoding():
    offenders = []
    for p in _sources():
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("read_text", "write_text")
                    and not _names_encoding(node)):
                offenders.append(f"{p.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not offenders, (
        "Path.read_text/write_text without encoding= is locale dependent:\n  "
        + "\n  ".join(offenders))


def test_the_repo_is_readable_as_cp1252_would_never_manage():
    """The concrete failure: our own sources are not cp1252-decodable.

    This is why the guards above exist rather than a convention in a doc.
    """
    undecodable = []
    for p in _sources():
        raw = p.read_bytes()
        try:
            raw.decode("cp1252")
        except UnicodeDecodeError:
            undecodable.append(p.relative_to(ROOT).as_posix())
    assert undecodable, (
        "No source file needs utf-8 any more. If that is deliberate these "
        "guards are still correct, but this canary no longer proves anything.")


@pytest.mark.parametrize("sym", ["σ", "≤", "→", "α"])
def test_a_card_round_trips_symbols_from_a_paper(tmp_path, sym):
    """sigma, <=, -> and alpha survive save/load. On Windows they used to not."""
    from ros.cards.schema import load_card
    card = load_card("cards/devanathan_2026_india_factor_adaptation.yaml")
    # rationale and title are free text lifted straight out of the paper, so
    # they are exactly where a sigma or a <= arrives from.
    card.intent.rationale = f"target {sym} vol; weights {sym} 1"
    card.paper.title = f"Dynamic {sym}-targeting"
    dst = tmp_path / "card.yaml"
    card.to_yaml(str(dst))
    back = load_card(str(dst))
    assert sym in back.intent.rationale
    assert sym in back.paper.title
