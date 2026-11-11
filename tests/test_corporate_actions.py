# Quant AI Researcher
"""Demergers Ace leaves unadjusted (ros/data/corporate_actions.py): the factor rule, the back-adjustment, the sourced
table, and the gap check's 'probable unadjusted corporate action' flag."""
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.data import corporate_actions as ca


def test_the_factor_is_the_ex_date_open_over_the_cum_close():
    f, method, why = ca.factor_for(ex_open=1906.0, ex_close=2000.0, cum_close=3156.1)      # RAYMOND 2024
    assert abs(f - 1906.0 / 3156.1) < 1e-12 and method == ca.METHOD and why == ""


def test_a_stale_open_falls_back_to_the_close_ratio():
    f, method, _ = ca.factor_for(ex_open=573.3, ex_close=109.75, cum_close=637.0)         # ADANIENT 2015
    assert abs(f - 109.75 / 637.0) < 1e-12 and method == ca.METHOD_FALLBACK


def test_a_factor_outside_zero_to_one_is_not_applied():
    f, _, why = ca.factor_for(ex_open=110.0, ex_close=110.0, cum_close=100.0)
    assert np.isnan(f) and "not applied" in why


def test_prices_before_the_ex_date_are_scaled_and_raw_prices_never_change():
    d = pd.DataFrame({"date": pd.to_datetime(["2024-07-09", "2024-07-10", "2024-07-11", "2024-07-12"] * 2),
                      "isin": ["P"] * 4 + ["Q"] * 4,
                      "close": [100.0, 100.0, 60.0, 61.0] * 2, "unadj_close": [100.0, 100.0, 60.0, 61.0] * 2})
    t = pd.DataFrame({"parent_isin": ["P", "P"], "ex_date": pd.to_datetime(["2024-07-11", "2024-07-12"]),
                      "factor": [0.6, 0.5]})
    out = ca.apply(d, t)
    p = out[out["isin"] == "P"]["close"].tolist()
    assert p == [100 * 0.6 * 0.5, 100 * 0.6 * 0.5, 60 * 0.5, 61.0]          # two events compound
    assert out[out["isin"] == "Q"]["close"].tolist() == [100.0, 100.0, 60.0, 61.0]
    assert out["unadj_close"].tolist() == d["unadj_close"].tolist()


def test_the_sourced_table_has_one_row_per_event_and_every_parent_isin():
    ev = ca.sourced_events()
    assert len(ev) >= 40 and not ev.duplicated(["parent_isin", "ex_date"]).any()
    assert set(ev["status"]) <= {"CONFIRMED", "PARTIAL"}
    raymond = ev[(ev["parent_symbol"] == "RAYMOND") & (ev["ex_date"] == pd.Timestamp("2024-07-11"))]
    assert len(raymond) == 1 and raymond["parent_isin"].iloc[0] == "INE301A01014"


def test_a_big_drop_with_a_new_listing_is_flagged_unless_it_is_a_known_demerger():
    listings = pd.DataFrame({"company_name": ["Raymond Lifestyle Ltd.", "Other Co"],
                             "first_date": ["2024-09-05", "2024-08-01"]})
    near = ca.new_listing_near("Raymond Ltd.", pd.Timestamp("2024-07-11"), listings)
    assert near is True
    assert ca.probable_unadjusted_action(-0.37, False, near, known_demerger=False) is True
    assert ca.probable_unadjusted_action(-0.37, False, near, known_demerger=True) is False
    assert ca.probable_unadjusted_action(-0.37, True, near, known_demerger=False) is False      # factor changed: a split
    assert ca.new_listing_near("Raymond Ltd.", pd.Timestamp("2023-01-01"), listings) is False
