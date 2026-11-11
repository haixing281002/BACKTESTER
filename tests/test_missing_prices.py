# Quant AI Researcher
"""The missing-price rule (ros/engine/missing_prices.py) on a synthetic panel."""
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.engine import missing_prices as mp

DATES = pd.bdate_range("2024-01-01", periods=60)


def _panel():
    p = pd.DataFrame(100.0, index=DATES, columns=["HOLE", "LONG", "GONE", "NEW", "WEEKLY"])
    p.iloc[10:13, 0] = np.nan                 # a 3-session hole
    p.iloc[10:40, 1] = np.nan                 # 30 sessions without a price, no delisting on record
    p.iloc[20:, 2] = np.nan                   # stops for good; delisted on the list
    p.iloc[:5, 3] = np.nan                    # lists on day 5
    p.iloc[30:, 4] = np.nan                   # suspended, then trades one day a week (like a BZ stock)
    p.iloc[35::5, 4] = 100.0
    return p


def test_the_states_follow_the_rule():
    dl = pd.DataFrame({"isin": ["GONE"], "effective_date": [DATES[25]], "type": ["DELISTED_COMPULSORY"],
                       "acquirer_symbol": [None], "swap_ratio": [None]})
    s = mp.states(_panel(), dl)
    assert (s["HOLE"].iloc[10:13] == mp.HOLD).all() and s["HOLE"].iloc[13] == mp.TRADED
    assert (s["LONG"].iloc[10:30] == mp.HOLD).all() and (s["LONG"].iloc[30:40] == mp.SUSPENDED).all()
    assert (s["GONE"].iloc[20:25] == mp.HOLD).all(), "before the filing's effective date it is only a hole"
    assert (s["GONE"].iloc[25:] == mp.DELISTED).all()
    assert (s["NEW"].iloc[:5] == mp.NOT_LISTED).all() and s["NEW"].iloc[5] == mp.TRADED
    assert s["WEEKLY"].iloc[35] == mp.TRADED and s["WEEKLY"].iloc[36] == mp.HOLD


def test_a_series_that_stops_without_a_filing_is_a_suspension_never_an_exit():
    s = mp.states(_panel(), delistings=None)
    assert (s["GONE"].iloc[41:] == mp.SUSPENDED).all() and not (s == mp.DELISTED).any().any()


def test_flagged_events_list_each_spell_the_book_sat_through():
    dl = pd.DataFrame({"isin": ["GONE"], "effective_date": [DATES[25]], "type": ["MERGED_INTO"],
                       "acquirer_symbol": ["X"], "swap_ratio": ["1 for 1"]})
    s = mp.states(_panel(), dl)
    held = pd.DataFrame(True, index=DATES, columns=s.columns)
    ev = mp.flagged_events(s, held)
    assert set(map(tuple, ev[["isin", "kind"]].to_numpy())) >= {("LONG", "suspended"), ("GONE", "delisted")}
    assert ev[ev["isin"] == "LONG"]["sessions"].iloc[0] == 10
    assert mp.flagged_events(s, held.assign(LONG=False))["isin"].ne("LONG").all()


def test_the_sourced_list_loads_confirmed_delistings_only():
    d = mp.load_delistings()
    assert len(d) > 50 and set(d["type"]) <= set(mp.CONFIRMED_TYPES)
    assert d["effective_date"].notna().all() and not d["isin"].duplicated().any()
    hdfc = d[d["isin"] == "INE001A01036"]
    assert len(hdfc) == 1 and hdfc["effective_date"].iloc[0] == pd.Timestamp("2023-07-13")
