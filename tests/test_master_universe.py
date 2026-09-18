"""The master universe file, and the three ways it can silently lie.

You build this file by hand from several sources. Parsing it is the easy half.
The half that matters is refusing one that would produce a confident wrong
answer, because once a backtest has run on it the report looks identical either
way -- there is no downstream test that catches a survivor-only universe.

So most of this file is about refusal.
"""
import numpy as np
import pandas as pd
import pytest

from ros.data.master import (MasterUniverseError, engine_inputs, load_master)

DATES = pd.bdate_range("2015-01-01", periods=800)


def write_master(tmp_path, n=40, n_dead=8, drop_dead_rows=True,
                 membership=True, name="m.csv", seed=3, **overrides):
    """A long master CSV. `n_dead` names delist partway; `drop_dead_rows`
    controls whether the file keeps them (honest) or omits them (survivor-only)."""
    rng = np.random.default_rng(seed)
    rows = []
    for j in range(n):
        sec = f"INE{j:03d}A01"
        death = (len(DATES) - 300 + j * 15) if j < n_dead else len(DATES)
        px = 100 * np.cumprod(1 + rng.normal(3e-4, 0.015, len(DATES)))
        for i, d in enumerate(DATES):
            alive = i < death
            if not alive and drop_dead_rows:
                continue
            rows.append(dict(date=d.date(), security_id=sec, symbol=f"S{j:03d}",
                             adj_close=round(px[i], 2) if alive else "",
                             in_universe=1 if alive else 0,
                             adv=round(abs(rng.normal(500, 200)), 1),
                             free_float_mcap=round(px[i] * 1e5, 0),
                             sector="financials" if j % 3 else "energy"))
    df = pd.DataFrame(rows)
    if not membership:
        df = df.drop(columns=["in_universe"])
    for k, v in overrides.items():
        df[k] = v
    path = tmp_path / name
    df.to_csv(path, index=False)
    return str(path)


# ---------------------------------------------------------------------------
# It parses what a human would actually build
# ---------------------------------------------------------------------------
def test_a_well_formed_file_yields_every_panel(tmp_path):
    mu = load_master(write_master(tmp_path))
    assert mu.prices.shape == (800, 40)
    assert mu.membership.shape == mu.prices.shape
    assert mu.membership.dtypes.eq(bool).all()
    for panel in (mu.adv, mu.free_float_mcap, mu.sector, mu.symbols):
        assert panel is not None and panel.shape == mu.prices.shape


@pytest.mark.parametrize("renames,values", [
    ({"date": "TradeDate", "security_id": "ISIN", "adj_close": "AdjustedClose",
      "in_universe": "IsMember"}, {"IsMember": {1: "Y", 0: "N"}}),
    ({"date": "as_of", "security_id": "SecId", "adj_close": "px_adj",
      "in_universe": "index_member"}, {"index_member": {1: True, 0: False}}),
    ({"date": "DT", "security_id": "entity_id", "adj_close": "close_adj",
      "in_universe": "active"}, {"active": {1: "TRUE", 0: "FALSE"}}),
])
def test_column_spellings_are_resolved(tmp_path, renames, values):
    """You will assemble this from several sources and nobody agrees on a name."""
    src = write_master(tmp_path)
    df = pd.read_csv(src).rename(columns=renames)
    for col, mapping in values.items():
        df[col] = df[col].map(mapping)
    p = tmp_path / "odd.csv"
    df.to_csv(p, index=False)
    mu = load_master(str(p))
    assert mu.prices.shape[1] == 40 and mu.membership.dtypes.eq(bool).all()


def test_a_plain_close_column_is_accepted_when_there_is_no_adjusted_one(tmp_path):
    df = pd.read_csv(write_master(tmp_path)).rename(columns={"adj_close": "close"})
    p = tmp_path / "c.csv"
    df.to_csv(p, index=False)
    assert load_master(str(p)).prices.shape[1] == 40


# ---------------------------------------------------------------------------
# REFUSALS -- each of these produces a normal-looking, wrong backtest
# ---------------------------------------------------------------------------
def test_a_survivor_only_file_is_refused(tmp_path):
    """The one that cannot be corrected downstream."""
    p = write_master(tmp_path, n_dead=0, name="surv.csv")
    with pytest.raises(MasterUniverseError) as e:
        load_master(p)
    msg = str(e.value)
    assert "final date" in msg and "back-filled" in msg


def test_the_survivorship_signature_is_a_ratio_not_a_guess(tmp_path):
    honest = load_master(write_master(tmp_path), strict=False)
    assert honest.diagnosis.survivor_ratio < 0.9
    surv = load_master(write_master(tmp_path, n_dead=0, name="s.csv"), strict=False)
    assert surv.diagnosis.survivor_ratio > 0.98
    assert honest.diagnosis.usable and not surv.diagnosis.usable


def test_a_missing_membership_column_is_refused_by_default(tmp_path):
    p = write_master(tmp_path, membership=False, name="nomem.csv")
    with pytest.raises(MasterUniverseError, match="no membership column"):
        load_master(p)


def test_a_missing_membership_column_can_be_downgraded_deliberately(tmp_path):
    """Allowed only when the file genuinely omits non-members, and said out loud."""
    p = write_master(tmp_path, membership=False, name="nomem2.csv")
    mu = load_master(p, require_membership=False)
    assert mu.diagnosis.usable
    assert any("no membership column" in w for w in mu.diagnosis.warnings)
    assert mu.membership.equals(mu.prices.notna())


def test_duplicate_rows_are_refused(tmp_path):
    src = write_master(tmp_path)
    df = pd.read_csv(src)
    p = tmp_path / "dup.csv"
    pd.concat([df, df.head(3)]).to_csv(p, index=False)
    with pytest.raises(MasterUniverseError, match="duplicate"):
        load_master(str(p))


def test_an_unrecognised_membership_value_is_refused_not_guessed(tmp_path):
    """Reading 'maybe' as False drops a stock and looks exactly like a delisting."""
    df = pd.read_csv(write_master(tmp_path))
    df["in_universe"] = df["in_universe"].astype(object)
    df.loc[5, "in_universe"] = "maybe"
    p = tmp_path / "junk.csv"
    df.to_csv(p, index=False)
    with pytest.raises(MasterUniverseError, match="neither true nor false"):
        load_master(str(p))


def test_unparseable_dates_are_refused_not_dropped(tmp_path):
    df = pd.read_csv(write_master(tmp_path))
    df.loc[7, "date"] = "not-a-date"
    p = tmp_path / "baddate.csv"
    df.to_csv(p, index=False)
    with pytest.raises(MasterUniverseError, match="unparseable date"):
        load_master(str(p))


def test_a_missing_price_column_is_refused_with_the_accepted_spellings(tmp_path):
    df = pd.read_csv(write_master(tmp_path)).drop(columns=["adj_close"])
    p = tmp_path / "nopx.csv"
    df.to_csv(p, index=False)
    with pytest.raises(MasterUniverseError) as e:
        load_master(str(p))
    assert "no price column" in str(e.value)


def test_a_missing_key_column_lists_what_it_looked_for(tmp_path):
    df = pd.read_csv(write_master(tmp_path)).drop(columns=["security_id"])
    p = tmp_path / "nosec.csv"
    df.to_csv(p, index=False)
    with pytest.raises(MasterUniverseError) as e:
        load_master(str(p))
    assert "security_id" in str(e.value) and "isin" in str(e.value).lower()


# ---------------------------------------------------------------------------
# Warnings that are not refusals
# ---------------------------------------------------------------------------
def test_missing_adv_warns_about_capacity(tmp_path):
    df = pd.read_csv(write_master(tmp_path)).drop(columns=["adv"])
    p = tmp_path / "noadv.csv"
    df.to_csv(p, index=False)
    mu = load_master(str(p))
    assert mu.diagnosis.usable
    assert any("capacity" in w for w in mu.diagnosis.warnings)


def test_total_cap_without_free_float_warns(tmp_path):
    df = pd.read_csv(write_master(tmp_path)).drop(columns=["free_float_mcap"])
    df["market_cap"] = 1e8
    p = tmp_path / "nofree.csv"
    df.to_csv(p, index=False)
    mu = load_master(str(p))
    assert any("FREE FLOAT" in w for w in mu.diagnosis.warnings)


# ---------------------------------------------------------------------------
# It reaches the engine, and the engine behaves
# ---------------------------------------------------------------------------
def test_the_panels_drive_a_cross_sectional_backtest(tmp_path):
    from ros.engine.backtest import Backtester
    from ros.engine.templates import build_allocator

    mu = load_master(write_master(tmp_path))
    px, mem = engine_inputs(mu)
    bt = Backtester(prices=px, assets=list(px.columns), spread_bps=80,
                    lag_days=1, allow_cash=True, membership=mem)
    res = bt.run(allocator=build_allocator("cross_sectional", list(px.columns),
                                           n_hold=10, min_names=5),
                 rebalance="monthly",
                 alpha=px.pct_change(252, fill_method=None), warmup=20)
    assert np.isfinite(res.value).all() and (res.value > 0).all()
    assert res.meta["changing_universe"] is True
    assert res.meta["forced_exits"] > 0, (
        "no position was ever sold out of the universe, so the delistings in "
        "this file are not reaching the engine")


def test_restrict_trims_dates_and_drops_empty_securities(tmp_path):
    mu = load_master(write_master(tmp_path))
    sub = mu.restrict(start="2016-01-01", end="2016-12-31")
    assert sub.prices.index.min() >= pd.Timestamp("2016-01-01")
    assert sub.prices.index.max() <= pd.Timestamp("2016-12-31")
    assert all(sub.prices[c].notna().any() for c in sub.prices.columns)


def test_engine_inputs_aligns_membership_to_prices(tmp_path):
    mu = load_master(write_master(tmp_path))
    px, mem = engine_inputs(mu)
    assert list(px.columns) == list(mem.columns)
    assert px.index.equals(mem.index)
    assert mem.dtypes.eq(bool).all()


# ---------------------------------------------------------------------------
# Declaring it, so provenance travels
# ---------------------------------------------------------------------------
def test_a_declared_master_requires_the_honesty_fields(tmp_path):
    from ros.data import intake
    csv = write_master(tmp_path, name="u.csv")
    man = tmp_path / "MANIFEST.yaml"
    man.write_text("master:\n  file: u.csv\n", encoding="utf-8")
    old = intake.RAW_DIR
    try:
        intake.RAW_DIR = str(tmp_path)
        with pytest.raises(intake.ManifestError) as e:
            intake.read_master_declaration(str(man))
        assert "pit_status" in str(e.value) and "licence" in str(e.value)
    finally:
        intake.RAW_DIR = old


def test_a_fully_declared_master_loads(tmp_path):
    from ros.data import intake
    write_master(tmp_path, name="u.csv")
    man = tmp_path / "MANIFEST.yaml"
    man.write_text(
        "master:\n  file: u.csv\n  pit_status: point_in_time\n"
        '  licence: "internal"\n', encoding="utf-8")
    old = intake.RAW_DIR
    try:
        intake.RAW_DIR = str(tmp_path)
        mu, decl = intake.load_declared_master(str(man))
        assert mu is not None and decl["pit_status"] == "point_in_time"
        assert mu.prices.shape[1] == 40
    finally:
        intake.RAW_DIR = old
