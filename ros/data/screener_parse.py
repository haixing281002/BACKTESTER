"""Helpers to turn the raw Screener tables (secs.pkl) into numbers.

    from ros.data.screener_parse import load, row, num
    secs, meta = load("scr", "AIAENG")
    pl = secs["profit-loss"][0]            # first column = row labels, other columns = periods ('Mar 2024', ..., 'TTM')
    sales = row(pl, ["Sales", "Revenue"])  # -> {'Mar 2015': 1234.0, ...}
"""
import json, os, pickle, re
import numpy as np


def num(v):
    """Screener cell -> float or None. Handles '1,234', '12%', '', NaN and stray '.' ."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    t = str(v).replace(",", "").replace("%", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def row(df, prefixes):
    """First row whose label starts with any prefix (case-insensitive). Screener appends ' +' / ' -' to expandable
    rows, so trailing '+', '-' and spaces are stripped before matching. Returns {column: float}."""
    lab = df.iloc[:, 0].astype(str).str.replace(r"[\s\+\-]+$", "", regex=True).str.strip()
    for p in prefixes:
        hit = lab.index[lab.str.lower().str.startswith(p.lower())]
        if len(hit):
            return {c: num(v) for c, v in zip(df.columns[1:], df.iloc[hit[0], 1:])}
    return {}


def load(root, sym):
    d = os.path.join(root, sym.upper())
    secs = pickle.load(open(os.path.join(d, "secs.pkl"), "rb"))
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf8"))
    return secs, meta


def annual_columns(pl):
    """Fiscal-year columns of the P&L table, excluding 'TTM' and odd-length periods like '18m'."""
    return [c for c in pl.columns[1:] if c != "TTM" and not re.search(r"\d+m$", str(c))]
