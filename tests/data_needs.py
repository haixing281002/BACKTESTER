# Quant AI Researcher
"""Files that are not in git (licensed market data, third-party papers). A test that needs one is marked with
the matching skip, so on a machine without the file it reports SKIPPED with the reason instead of failing."""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from ros.data import sources

SYNTHETIC_PAPER = os.path.join(REPO, "tests", "fixtures", "synthetic_paper.pdf")
REAL_PAPER = os.path.join(REPO, "docs", "devanathan_2026_simple_dynamic_sbg.pdf")

needs_nse_workbook = pytest.mark.skipif(
    not os.path.isfile(sources.NSE_INDEX_WORKBOOK),
    reason="NSE index workbook not on this machine (not in git; see SETUP.md)")
needs_real_paper = pytest.mark.skipif(
    not os.path.isfile(REAL_PAPER),
    reason="docs/devanathan_2026_simple_dynamic_sbg.pdf not on this machine (third-party papers are not in git)")
