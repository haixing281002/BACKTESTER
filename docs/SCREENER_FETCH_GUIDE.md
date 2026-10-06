# Fetching fundamentals from Screener.in: how it works and how this repo uses it

Verified live on 6 Oct 2026 with `ros/data/screener_fetch.py` (AIAENG, WIPRO), and used to fetch 1,771 symbols for the
bhavcopy + Screener panel (see `docs/BHAVCOPY_SCREENER.md`).

## 1. What this does
Screener.in serves each company's financials as ordinary HTML tables on a public page. We download that page with a plain
HTTP GET (no login, no API key, no browser), cut out each `<section id="...">`, and let `pandas.read_html` turn the tables
into DataFrames. A second small request fetches the peers table. Everything is saved as pickle + CSV + JSON.

## 2. Files
| File | Purpose |
|---|---|
| `ros/data/screener_fetch.py` | Downloader. One or many symbols, retries, polite delay, writes pkl/CSV/JSON. |
| `ros/data/screener_parse.py` | Helpers: `num()` (cell to float), `row()` (find a row by label), `load()`, `annual_columns()`. |
| `scripts/bhavcopy_screener_build.py fetch-screener` | Resumable bulk fetch for the symbols in `scr_symbols.txt`; skips what is already in `scr/`. |
| `ros/data/bhavcopy_screener_panel.py` | Turns the saved pages into shares, promoter holding and free-float fraction per symbol. |

## 3. Setup and use
```
pip install requests pandas lxml html5lib beautifulsoup4
python -m ros.data.screener_fetch WIPRO AIAENG --out scr --delay 2.5
python -m ros.data.screener_fetch TCS INFY HCLTECH --out scr --delay 2.5
```
```python
from ros.data.screener_parse import load, row, annual_columns
secs, meta = load("scr", "WIPRO")
pl    = secs["profit-loss"][0]
sales = row(pl, ["Sales", "Revenue"])     # {'Mar 2015': 46951.0, ..., 'Mar 2026': 92624.0, 'TTM': 94968.0}
```
Check that the test passes before a bulk run: `done: 2/2 symbols`, each line `ok (consolidated)` with sections
`['quarters', 'profit-loss', 'balance-sheet', 'cash-flow', 'ratios', 'shareholding']`, `meta["name"] == "Wipro Ltd"`, and
`row(pl, ["Sales", "Revenue"])` returning about 13 period entries.

## 4. The three URLs involved
| # | URL | What comes back | Notes |
|---|---|---|---|
| 1 | `https://www.screener.in/company/<SYMBOL>/consolidated/` | Full HTML page, consolidated financials | Tried first. |
| 2 | `https://www.screener.in/company/<SYMBOL>/` | Full HTML page, standalone financials | Fallback if (1) is 404 or has no P&L. |
| 3 | `https://www.screener.in/api/company/<warehouse_id>/peers/` | HTML fragment with the peers table | Needs header `X-Requested-With: XMLHttpRequest`; the id is read from `data-warehouse-id` on the page. |

Header: only `User-Agent: Mozilla/5.0`. A page counts as valid when it contains `id="profit-loss"` and the text "Market Cap".

## 5. What the page contains
Each block is `<section id="NAME"> ... <table> ... </table> ... </section>`; first column = row labels, the rest = periods.

| Section id | Content |
|---|---|
| `quarters` | Quarterly P&L, about 13 quarters |
| `profit-loss` | Annual P&L (Mar 2015 to latest + TTM) and four small growth tables |
| `balance-sheet` | Equity Capital, Reserves, Borrowings, Total Assets and so on |
| `cash-flow` | Operating, investing, financing cash flow, free cash flow |
| `ratios` | Debtor, inventory and payable days, ROCE |
| `shareholding` | Promoters, FIIs, DIIs, Public, number of shareholders; table 0 quarterly, table 1 yearly |

The top card (`<li class="flex flex-space-between">`) gives Market Cap, Current Price, High / Low, Stock P/E, Book Value,
Dividend Yield, ROCE, ROE, Face Value; the fetch writes them to `meta.json`.

## 6. What it writes (per symbol under `scr/<SYMBOL>/`)
`secs.pkl`, `csv/<section>_<n>.csv`, `peers.pkl`, `meta.json`. Money is Rs crore as shown on the site; EPS in Rs; ratios in % or days.

## 7. Turning cells into numbers
- Row labels carry a non-breaking space and a "+" for expandable rows; `row()` strips them and matches by prefix.
- `num()` handles `'1,234'`, `'12%'`, blanks, NaN and a stray `'.'` (returns None instead of crashing). Do not turn a None into 0 silently.
- Banks and NBFCs use different labels (`Revenue`, `Financing Profit`, `Financing Margin %`, `Deposits`, `Borrowing`).
- `annual_columns(pl)` drops `'TTM'` and odd periods like `'18m'`.

## 8. Rules, and the one that matters most for backtests
- At least 1.5 s between symbols, one session, no parallel requests, cache what you download.
- Public pages only. Never log in, never bypass a block. Do not redistribute Screener's data. Check Screener's terms and robots rules
  before running at scale. `scr/` is gitignored for this reason.
- **Screener is restated latest values with no announcement dates and a market cap and price as of the fetch day.** It is not
  point-in-time. Anything built from it carries that caveat: shares are today's shares carried back, delisted companies have no page,
  and the free-float fraction is a current snapshot. Say so wherever a number built from it is shown.

## 9. Gotchas we hit
1. A `'.'` cell crashed the original parser; `to_float()` / `num()` fix it.
2. Record which view you got (`meta["view"]`): consolidated and standalone numbers differ.
3. Layout changes break it. The code relies on `<section id=...>`, `flex flex-space-between` items and `data-warehouse-id`. If a
   section disappears, check the printed `sections=[...]` list and update `SECTIONS`.
4. Balance sheet and cash flow can end in a different column than the P&L; use each table's own last column.
5. A company with no `ratios` or a short history will lack keys; test before indexing.
6. HTTP 429: raise `--delay` to 5 or more and fetch fewer symbols at once.

## 10. How this repo uses it
The bulk path is `python scripts/bhavcopy_screener_build.py fetch-screener --delay 2.0`. It reads `scr_symbols.txt` (every symbol
that was ever in the point-in-time top-N by traded value), skips symbols already present, writes `scr/_not_found.txt` for pages that
do not exist, and prints a summary. The 1,771-symbol top-1,000 universe took about 35 minutes at 2 seconds a page.

*Educational use only. Data belongs to Screener.in and its sources.*
