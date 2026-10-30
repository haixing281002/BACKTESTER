# Corporate-action event list (derived, signed off)

`corporate_action_events_20261021.csv` is a byte-exact copy of `outputs/lightyear/20261021-104144-801e/corporate_action_events.csv`,
the operator-reviewed list built from NSE bhavcopy CLOSE/PREV ratios on 2026-10-21 (736 rows: 469 REAL, 253 SPLIT/BONUS,
14 DEMERGER). `corporate_action_events_20261021.md` is the sign-off note that travelled with it.

sha256 `e7794b2a28a3d7cfc08dce32bc4852d62bbfaf77f1b41033e7b0e64054458b0a`

It lives here, not in a run folder, because `outputs/` is gitignored and two run scripts
(`scripts/method_nifty_equity_indices_india_backtest.py`, `scripts/oceanofpdf_com_stocks_on_the_move_andreas_clenow_india_backtest.py`)
read it. Both take `CA_EVENTS=<path>` to override it, and both write its sha256 into their run's `manifest.json`.

It is derived data, so it sits under `data/processed/` (raw inputs under `data/raw/` are never edited).

Known defect carried over, not fixed here: KARURVYSYA 2025-08-26 (ratio 0.819, a 1:5 bonus) is labelled REAL with
adjust_factor 1.0, so both scripts see a false -18% day. Fixing the list is a data change that needs sign-off.
