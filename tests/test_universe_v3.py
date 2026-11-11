# Quant AI Researcher
"""Universe v3 (scripts/universe_v3/build_v3.py): NSE effective dates, ISINs keyed the way Ace's panels are."""
import importlib.util
import os
import sys

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.data import nifty500

spec = importlib.util.spec_from_file_location("build_v3", os.path.join(REPO, "scripts", "universe_v3", "build_v3.py"))
b3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b3)

SM = pd.DataFrame({"isin": ["INE001X01047", "INE002X01010", "INE003X01015"], "nse_symbol": ["NEWSYM", "BETA", "GAMMA"]})


def _nse(rows):
    cols = ["symbol", "isin", "isin_at_start", "company_name", "start_date", "end_date", "entry_type"]
    return pd.DataFrame(rows, columns=cols)


def test_a_rename_with_an_isin_change_is_one_spell_on_the_isin_ace_uses():
    nse = _nse([["OLDSYM", "INE001X01013", None, "Alpha", "2016-03-28", "2019-06-01", "regular"],
                ["NEWSYM", "INE001X01047", "INE001X01013", "Alpha", "2019-06-01", None, "regular"]])
    sp, unmapped = b3.build_spells(nse, SM)
    assert len(sp) == 1 and sp["isin"].iloc[0] == "INE001X01047" and unmapped.empty
    assert sp["start_date"].iloc[0] == pd.Timestamp("2016-03-28") and pd.isna(sp["end_date"].iloc[0])


def test_an_old_isin_maps_by_issuer_code_and_placeholders_are_dropped():
    nse = _nse([["ALPHA", "INE001X01013", None, "Alpha", "2014-01-01", "2015-01-01", "regular"],
                ["DUMMYBETA", "INE999X01019", None, "Placeholder", "2014-01-01", "2014-01-10", "demerger_placeholder"]])
    sp, _ = b3.build_spells(nse, SM)
    assert list(sp["isin"]) == ["INE001X01047"]


def test_a_member_ace_does_not_know_stays_in_the_universe_under_nse_isin():
    nse = _nse([["GONE", "INE777Y01011", None, "Gone Ltd", "2014-01-01", "2016-01-01", "regular"]])
    sp, unmapped = b3.build_spells(nse, SM)
    assert list(sp["isin"]) == ["INE777Y01011"] and len(unmapped) == 1


def test_membership_is_half_open_on_the_effective_dates():
    nse = _nse([["BETA", "INE002X01010", None, "Beta", "2016-04-01", "2016-09-30", "regular"]])
    sp, _ = b3.build_spells(nse, SM)
    assert b3.members_on(sp, pd.Timestamp("2016-04-01")) == {"INE002X01010"}
    assert b3.members_on(sp, pd.Timestamp("2016-09-30")) == set()
    assert b3.members_on(sp, pd.Timestamp("2016-03-31")) == set()


@pytest.mark.skipif(not os.path.isfile(nifty500.V3_SPELLS), reason="universe v3 not built on this machine")
def test_the_built_v3_has_nse_member_counts_and_fixes_2016_q2():
    v3 = nifty500.load_membership(source="nifty500_members_v3")
    for d in ("2014-06-02", "2016-04-01", "2020-06-01", "2024-03-28"):
        n = len(b3.members_on(v3, pd.Timestamp(d)))
        assert 500 <= n <= 504, (d, n)             # NSE counts 501 while the Tata Motors DVR was a member
    v2 = nifty500.load_membership(source="nifty500_members_v2")
    d = pd.Timestamp("2016-05-02")
    a, b = b3.members_on(v3, d), b3.members_on(v2, d)
    assert 60 <= len(a - b) <= 90 and 60 <= len(b - a) <= 90, "v2 is a quarter late in 2016 Q2; v3 is not"
