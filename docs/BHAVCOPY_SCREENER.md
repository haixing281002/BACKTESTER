# 5-year stock panel from two sources: NSE bhavcopy + Screener.in

This is a data path that uses **only** NSE bhavcopy and Screener.in. `assert_sources()` in
`ros/data/bhavcopy_screener_panel.py` refuses anything else. The window is the last five years because
that is all the public bhavcopy tooling here reaches.

## Run it

```bash
python -m ros.data.nse_bhavcopy_download --years 5            # daily raw files -> cache/ (resumable)
python scripts/bhavcopy_screener_build.py symbols             # who was ever in the top-500 by traded value
python scripts/bhavcopy_screener_build.py fetch-screener      # public Screener pages -> scr/ (2.5 s apart)
python scripts/bhavcopy_screener_build.py build               # data/raw/master/bhavcopy_screener_panel.csv
python -m pytest tests/test_bhavcopy_screener.py -q           # offline tests
```

`cache/` and `scr/` are gitignored. Screener data stays on your machine and is not redistributed.

## What each source gives, and what that costs

| | gives | limit |
|---|---|---|
| NSE bhavcopy | daily raw OHLC, quantity, traded value, ISIN, all main-board stocks | prices are raw (unadjusted); no market cap |
| Screener.in | current market cap and price (so today's shares), face value, FY equity capital, latest promoter % | restated, **not point in time**; only companies that exist today |

## The signal this supports: rupee turnover

`turnover_window` = trailing sum of (daily traded value / market cap), where market cap on day *t* is the
split-adjusted close rescaled to today's share basis times today's shares. Both numerator and denominator are
rupees, so it does not depend on split or bonus basis (a test checks this).

## Caveats that travel with every number

- **Survivorship.** A stock that delisted inside the window has no Screener page, so no shares and no turnover.
  `coverage_report()` says how much of the universe that is. Treat it as a bias, not a rounding error.
- **Shares are today's shares.** Issuance (QIPs, rights, ESOPs) inside the window is not captured.
- **Universe** is top-N by trailing traded value, not by market cap, and not an official index.
- **Corporate actions** are neutralised by a threshold on daily gross return (a heuristic).
- **Free-float fraction** is a current promoter-holding snapshot, a sensitivity input only.
- Screener fetching follows its own guide: public pages only, no login, one session, a delay between pages.

See `docs/SCREENER_FETCH_GUIDE.md` for how the Screener fetch works (URLs, page anatomy, parsing helpers, rules and gotchas).
