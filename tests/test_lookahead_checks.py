# Quant AI Researcher
"""The look-ahead checks (ros/validation/lookahead.py) pass a causal signal and catch a planted one-day leak."""
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.validation import lookahead as la

DATES = pd.bdate_range("2023-01-02", periods=200)
PRICES = pd.DataFrame(100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.01, (200, 5)), axis=0)),
                      index=DATES, columns=list("ABCDE"))


def causal(p):
    return p.pct_change(20)


def leaky(p):                                     # reads tomorrow's close: a one-day leak
    return p.shift(-1).pct_change(20)


def book(signal_fn):
    def run(p):                                   # the weights DECIDED each day: hold the top 2 by signal
        return signal_fn(p).rank(axis=1, ascending=False).le(2).astype(float) / 2
    return run


def test_the_truncation_check_passes_a_causal_signal_and_catches_a_one_day_leak():
    dates = DATES[[60, 100, 150]]
    assert la.truncation_check(causal, PRICES, dates)["passed"] is True
    assert la.truncation_check(leaky, PRICES, dates)["passed"] is False


def test_the_scramble_check_passes_a_causal_book_and_catches_a_one_day_leak():
    rng = np.random.default_rng(1)
    assert la.scramble_check(book(causal), PRICES, DATES[120], rng)["passed"] is True
    assert la.scramble_check(book(leaky), PRICES, DATES[120], np.random.default_rng(1))["passed"] is False


def test_scrambling_leaves_everything_up_to_the_cut_off_untouched():
    s = la.scramble_after(PRICES, DATES[120], np.random.default_rng(2))
    assert s.loc[:DATES[120]].equals(PRICES.loc[:DATES[120]]) and not s.loc[DATES[121]:].equals(PRICES.loc[DATES[121]:])
