# Individual-stock data — local only, never committed

This folder is where the fund's individual-stock-level data lives **on your
machine only**. It is gitignored (`data/raw/stocks/*`, see the repo's
`.gitignore`) — nothing here is pushed to GitHub, ever. That's deliberate,
for two reasons:

1. **Size.** GitHub hard-blocks any single file over 100MB in a normal push.
   Stock-level history across NIFTY 500+ names for a couple of decades will
   blow past that easily.
2. **This is the right boundary anyway.** The fund's *code* — loaders,
   engine, allocators — belongs in the repo and is shared. The fund's *data*
   does not need to be, and keeping it out avoids repo bloat, avoids Git
   LFS cost, and matches how `data/raw/MANIFEST.yaml` already treats
   supplied data: declared and described in the repo, held locally.

## How to get your data in

1. Drop your file(s) directly into this folder (`data/raw/stocks/`).
2. Tell the loader what you actually have — this README will be updated
   with the **exact, verified schema** the first time a real file is
   inspected here. Until then, the loader (`universal_backtester/data.py`,
   `load_stock_universe()`) is written to accept either of the two most
   common shapes stock-level exports come in, and will tell you clearly
   which one it detected, or that neither matched:

   - **Long/tidy format** — one row per (date, security): columns for
     `Date`, a security identifier (`ISIN`, `Symbol`, or `Ticker` — ISIN
     preferred, per this repo's own README warning: *"Key the file on ISIN
     or an internal ID, never on the NSE symbol: symbols get reused and a
     rename splices two companies into one series"*), and `Open/High/Low
     /Close/Volume` (Volume optional).
   - **Wide format** — one column per security, a shared `Date` column,
     Close-only (matches the "banner workbook" shape this repo's index
     data already uses).

3. If your file also carries index membership (which names were in NIFTY
   500 / 200 / etc. on which date), say so explicitly — **a cross-section
   needs `membership`, never just a price file with holes in it.** A
   survivor-only stock file (only names that are still listed today) is the
   single most common way a backtest silently flatters itself: delisted
   names vanish, so the book never owns anything that went to zero. See
   `ros/engine/backtest.py`'s and `universal_backtester/engine.py`'s own
   `membership=` handling — both refuse to run on a fixed-but-incomplete
   price frame for exactly this reason.

## Not verified yet

Nothing in this README describes a schema that has actually been checked
against a real file — the two zip files this was built for (38MB, 162MB)
had not arrived when this was written. Treat every "expected" column name
above as a best guess from common NSE/BSE data-vendor conventions, not a
confirmed fact. The loader raises a clear, readable error naming exactly
what it found instead of guessing silently, and this README gets corrected
against the first real file, not before.
