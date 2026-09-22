"""Two rules this repo learned the hard way.

1. THERE IS NO DEFAULT PAPER. The repo was built around one worked example and
   its filename leaked into entry points, Colab cells and command defaults. A
   default paper is worse than none: a run that quietly analysed last week's PDF
   looks identical to one that analysed yours, and that surfaces only after a
   Gate A queue has been reviewed and signed against the wrong work.

2. STAGES 00 TO GATE A NEED NO MARKET DATA. Reading a paper, choosing the
   universe, reconstructing the strategy and assembling the queue touch no price
   series. Keeping that true is what lets any paper be taken to Gate A today,
   with the data shortfall as the deliverable rather than a blocker.
"""
import ast
import os
import pathlib
import subprocess
import sys

import pytest

from ros.papers import (NoPaperGiven, artifact_paths, ask_for_a_paper,
                        find_papers, require_paper, slugify)

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = str(ROOT / "docs/devanathan_2026_simple_dynamic_sbg.pdf")


def _run(*args, **kw):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=900, **kw)


# ---------------------------------------------------------------------------
# No default paper
# ---------------------------------------------------------------------------
def test_run_interpret_refuses_to_pick_a_paper():
    r = _run("run_interpret.py")
    assert r.returncode != 0, "it ran without being told which paper"
    assert "WHICH PAPER?" in r.stdout + r.stderr


def test_the_refusal_lists_what_is_available_and_how_to_add_more():
    msg = ask_for_a_paper()
    assert "WHICH PAPER?" in msg
    assert "docs/papers/" in msg
    for p in find_papers():
        assert p in msg, f"{p} exists but was not offered"


@pytest.mark.parametrize("bad,why", [
    (None, "nothing supplied"),
    ("", "empty string"),
    ("docs/does_not_exist.pdf", "missing file"),
    ("CLAUDE.md", "not a PDF"),
])
def test_a_bad_paper_argument_never_falls_back(bad, why):
    with pytest.raises(NoPaperGiven) as e:
        require_paper(bad)
    assert "WHICH PAPER?" in str(e.value), why


def test_a_truncated_upload_is_caught(tmp_path):
    """A failed upload leaves a stub. Analysing it would produce confident noise."""
    stub = tmp_path / "paper.pdf"
    stub.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(NoPaperGiven, match="too small"):
        require_paper(str(stub))


def test_a_real_paper_resolves_with_its_identity():
    p = require_paper(EXAMPLE)
    assert p.slug == "devanathan_2026_simple_dynamic_sbg"
    assert len(p.sha256) == 64 and p.size > 100_000


def test_artifacts_are_keyed_per_paper():
    """Two papers must never share an analysis file."""
    a = artifact_paths(require_paper(EXAMPLE))
    assert a["analysis"].endswith("devanathan_2026_simple_dynamic_sbg__analysis.json")
    assert slugify("/x/Some Paper (2024) v2.pdf") == "some_paper_2024_v2"


def test_no_entry_point_hardcodes_a_specific_paper():
    """The regression this file exists for.

    `cards/` and `outputs/` legitimately name papers -- a card IS about one
    paper. Entry points and bootstraps must not.
    """
    # Every top-level script plus the ros/ package, scanned rather than listed.
    # A hand-maintained list is a list someone forgets to extend, and the last
    # sweep of this missed four files for exactly that reason.
    targets = sorted(ROOT.glob("*.py")) + sorted(ROOT.glob("ros/**/*.py"))
    offenders = []
    for f in targets:
        if "examples" in f.parts or "__pycache__" in f.parts:
            continue
        name = f.relative_to(ROOT).as_posix()
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            # A PATH or filename naming a paper is hardcoding. A prose citation
            # is correct attribution -- `ts_momentum` should say whose strategy
            # it implements, and stripping that would make the code worse.
            named = ("devanathan" in low or "moskowitz" in low)
            is_reference = any(x in low for x in
                               (".pdf", ".yaml", ".json", "cards/", "docs/"))
            if named and is_reference:
                offenders.append(f"{name}:{i}: {line.strip()}")
            if ".pdf" in low and "default" in low:
                offenders.append(f"{name}:{i}: {line.strip()}")
    assert not offenders, (
        "code on a live path still names a specific paper. Worked examples "
        "belong in examples/, which this scan skips:\n  " + "\n  ".join(offenders))


def test_no_worked_example_is_shipped_in_the_users_card_folder():
    """The harm was never "cards/ contains cards". It was WHOSE cards.

    This has now been wrong twice in opposite directions. First it globbed the
    filesystem and fired on a researcher's own five drafts. Then it checked what
    git tracks -- and fired again on the same five, the moment the researcher
    committed them, which is how work gets off one laptop and is not a defect.

    Its own docstring said "a card a researcher wrote is none of this test's
    business" while it had no way to tell authorship from tracking. So assert
    what actually caused the original incident instead: a worked EXAMPLE sitting
    in cards/, which check_setup.py then globbed alphabetically and loaded on
    every run, so a fresh clone read a card about somebody else's paper.
    """
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "cards/"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    in_cards = {os.path.basename(t) for t in tracked
                if t.endswith((".yaml", ".yml"))}
    examples = {p.name for p in (ROOT / "examples/cards").glob("*.yaml")}
    duplicated = sorted(in_cards & examples)
    assert not duplicated, (
        f"worked example(s) {duplicated} are shipped in cards/. That is the "
        f"leak: check_setup.py globbed cards/*.yaml, took the first "
        f"alphabetically, and read a card about somebody else's paper on every "
        f"run. Examples live in examples/cards/, off every code path.")
    assert (ROOT / "examples/cards").is_dir(), "the examples went missing"


def test_no_live_path_loads_an_arbitrary_card_from_the_users_folder():
    """The mechanism of the original incident, guarded directly.

    Whatever is in cards/ belongs to the researcher. Nothing may reach in and
    pick one -- a card is named on the command line or not loaded at all.
    """
    import re
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = str(path.relative_to(ROOT))
        if rel.startswith(("examples/", "tests/", ".git")):
            continue
        for i, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.search(r"glob[^\n]*[\"\']cards/\*", line) and "examples/" not in line:
                offenders.append(f"{rel}:{i}: {line.strip()}")
    # check_setup.py may COUNT them; it may not LOAD one. A count has no
    # alphabetical first element that becomes somebody else's paper.
    real = [o for o in offenders if "len(" not in o and "load_card" in o]
    assert not real, (
        "a live path globs cards/ and loads one:\n  " + "\n  ".join(real))
    assert list((ROOT / "examples/cards").glob("*.yaml")), "no examples left"


def test_nothing_on_a_live_path_globs_the_users_cards_and_loads_one():
    """Listing cards/ to help someone is fine. Loading cards[0] is not."""
    import re
    bad = []
    for f in sorted(ROOT.glob("*.py")) + sorted(ROOT.glob("ros/**/*.py")):
        if "examples" in f.parts or "__pycache__" in f.parts:
            continue
        text = f.read_text(encoding="utf-8")
        # Follow the assignment: flag only when the variable bound to a
        # cards/ glob is the one indexed and loaded. Proximity alone flagged
        # check_setup.py, which globs cards/ to COUNT them and loads an example.
        for m in re.finditer(
                r"(\w+)\s*=\s*sorted\(\s*glob\.glob\(\s*['\"]cards/\*", text):
            var = m.group(1)
            line = text[:m.start()].count("\n") + 1
            if re.search(rf"load_card\(\s*{var}\[0\]", text):
                bad.append(f"{f.relative_to(ROOT).as_posix()}:{line}")
    assert not bad, ("this loads whichever card sorts first, which is how a run "
                     f"silently read the wrong paper: {bad}")


def test_the_paper_command_tells_the_model_to_ask():
    cmd = (ROOT / ".claude/commands/paper.md").read_text(encoding="utf-8")
    assert "ask_for_a_paper" in cmd
    assert "no default paper" in cmd.lower()


def test_claude_md_carries_the_rule():
    """CLAUDE.md loads automatically, so this is what actually reaches a session."""
    md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "no default paper" in md.lower()
    assert "run_interpret.py" in md


# ---------------------------------------------------------------------------
# Gate A without data
# ---------------------------------------------------------------------------
def test_run_interpret_reaches_gate_a_with_the_workbook_absent(tmp_path):
    """The claim, tested by removing the data rather than by reading the code."""
    xlsx = ROOT / "data/raw/NSE_Broad_Factor_Indices_Historical_Data.xlsx"
    stash = tmp_path / xlsx.name
    had = xlsx.exists()
    if had:
        xlsx.rename(stash)
    try:
        r = _run("run_interpret.py", "--pdf", EXAMPLE,
                 "--card", "examples/cards/devanathan_2026_india_factor_adaptation.yaml")
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert "GATE A" in r.stdout
        assert "decision: PENDING" in r.stdout
        assert "WHAT THIS PAPER WOULD NEED FROM YOU" in r.stdout
    finally:
        if had:
            stash.rename(xlsx)


def test_run_interpret_never_imports_a_data_loader():
    """Structural, not behavioural: the next edit must not quietly add one."""
    tree = ast.parse((ROOT / "run_interpret.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    banned = {"ros.data.loaders", "ros.data.snapshot", "ros.runner",
              "ros.engine.backtest"}
    assert not (imported & banned), (
        f"run_interpret.py imports {imported & banned}; it must reach Gate A "
        f"without touching market data")


def test_it_says_what_to_supply_when_data_is_missing(tmp_path):
    """A shortfall is the deliverable of this script, so it must be printed."""
    r = _run("run_interpret.py", "--pdf", EXAMPLE,
             "--card", "examples/cards/devanathan_2026_replication.yaml")
    assert "WHAT THIS PAPER WOULD NEED FROM YOU" in r.stdout
    assert "MANIFEST.yaml" in r.stdout
    assert "pit_status" in r.stdout, "the honesty field must reach the operator"


def test_an_uninterpreted_paper_says_what_to_run_next():
    """A paper with no card is a normal state, not an error to puzzle over."""
    r = _run("run_interpret.py", "--pdf", str(ROOT / "docs/ai_research_operating_system.pdf"))
    assert r.returncode == 2
    assert "NOTHING HAS BEEN INTERPRETED" in r.stdout
    assert "/ingest" in r.stdout


# ---------------------------------------------------------------------------
# outputs/ must not ship another paper's work
#
# Worse than the cards case. A committed strategy library means a fresh clone
# answers "has this question been asked before?" with somebody else's answers,
# and trials_for_family() -- which feeds the deflated Sharpe -- inherits their
# trial budget. Both silently change the significance of YOUR results.
# ---------------------------------------------------------------------------
def test_outputs_ships_with_no_run_artifacts():
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "outputs/"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    allowed = {"outputs/.gitkeep", "outputs/README.md"}
    stray = [t for t in tracked if t not in allowed]
    assert not stray, (
        "outputs/ is tracking run artifacts. A committed library makes a fresh "
        f"clone inherit another paper's trial count:\n  " + "\n  ".join(stray))


def test_the_strategy_library_starts_empty_on_a_fresh_clone():
    """The root that matters: StrategyLibrary defaults to outputs/library."""
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "outputs/library/"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    assert not tracked, (
        f"{len(tracked)} library entries are committed. /librarian would report "
        f"prior work that is not this fund's, and trials_for_family would count "
        f"trials from another research programme.")


def test_outputs_is_gitignored_so_runs_do_not_get_committed():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "outputs/*" in ignore
    assert "!outputs/README.md" in ignore, "the explanation must survive the ignore"


def test_the_worked_example_outputs_are_kept_for_reference():
    """Gitignoring the folder must not mean losing what a finished run looks like."""
    ex = ROOT / "examples/outputs"
    assert ex.is_dir()
    assert list((ex / "library").glob("*.json")), "no example library entry"
    assert list((ex / "reports").glob("*.txt")), "no example report"
