"""checkpoint(): the per-stage human-approval pause used by the plain
scripts/*.py execution scripts (the same pattern run_pipeline.py uses for
Gate A/Steps 03-07/Gate B, extracted so every local script can pause and
show its outputs-so-far too)."""
from unittest.mock import patch

from universal_backtester.checkpoint import checkpoint


def test_auto_approve_skips_the_pause_and_continues():
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input") as mock_input:
        result = checkpoint("STEP 1", [], auto_approve=True)
    assert result is True
    mock_input.assert_not_called()


def test_non_interactive_stdin_skips_the_pause_and_continues():
    with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as mock_input:
        result = checkpoint("STEP 1", [], auto_approve=False)
    assert result is True
    mock_input.assert_not_called()


def test_typing_approve_continues():
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="approve"):
        assert checkpoint("STEP 1", []) is True


def test_typing_yes_continues():
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="yes"):
        assert checkpoint("STEP 1", []) is True


def test_typing_anything_else_halts():
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="no"):
        assert checkpoint("STEP 1", []) is False


def test_produced_paths_are_printed_as_absolute_paths(capsys):
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="approve"):
        checkpoint("STEP 1", ["relative/path.csv"])
    out = capsys.readouterr().out
    assert "relative/path.csv" in out
    # printed path must actually be absolute, not the relative one verbatim
    import os
    assert os.path.abspath("relative/path.csv") in out
