# NIFTY 500 point-in-time membership, 18 Apr 2013 to 21 Oct 2026

Who was in the NIFTY 500 on any trading day, rebuilt from NSE's own documents and checked
against 128 independent NSE snapshots. Built 21 Oct 2026.

## Files

| File | What it is |
|---|---|
| `nifty500_membership.csv` | **The file to use.** One row per membership spell: `symbol`, `isin`, `company_name`, `industry`, `start_date`, `end_date`, `last_day_in_index`, `entry_type`, `start_source`, `end_reason`, `isin_at_start`. 1,374 rows. |
| `nifty500_changes.csv` | Every inclusion, exclusion and symbol rename with its effective date and the NSE document it came from. 1,675 rows. |
| `nifty500_month_end.csv` | Constituents at every month-end trading day (Apr 2013 to Sep 2026) plus 20 Oct 2026, long format. 81,632 rows. |
| `nifty500_validation.csv` | The 128 checks against NSE snapshots and their results. |
| `build/` | The scripts that produced these files (they expect the downloaded NSE sources listed below). |

### Reading `nifty500_membership.csv`

- A stock is a member on day `d` when `start_date <= d < end_date` (blank `end_date` = still a member).
- `start_date` is NSE's effective date. "Effective March 28 (close of March 27)" means the stock is in the
  index from the 28th, so `start_date = 28th`. `end_date` works the same way, and `last_day_in_index`
  is the last trading day the stock was a member.
- `symbol` is the NSE symbol **valid during that row**. When NSE renames a symbol (ZOMATO to ETERNAL,
  TATAMOTORS to TMPV), the row is closed and a new row opens under the new symbol with
  `start_source = renamed (same company)`. So on any date the symbols match that day's bhavcopy.
- `isin` is the ISIN at the end of the spell. If the ISIN changed during the spell (face-value splits),
  the earlier one is in `isin_at_start`.
- `entry_type`:
  - `regular`: normal membership.
  - `demerger_placeholder`: NSE's zero-price stand-in for a company being demerged (symbols like
    `DUMMYTATAM`). Not tradable. **Drop these for strategy universes.**
  - `demerger_temporary`: the spun-off company after it lists, kept in the index for a few days and
    then removed (for example JIOFIN in Aug to Sep 2023). Tradable, but usually left out of a universe.

```python
import pandas as pd
m = pd.read_csv("data/raw/nifty500/nifty500_membership.csv", parse_dates=["start_date", "end_date"])

def nifty500_on(date, regular_only=True):
    d = pd.Timestamp(date)
    x = m[(m.start_date <= d) & (m.end_date.isna() | (m.end_date > d))]
    if regular_only:
        x = x[x.entry_type == "regular"]
    return x[["symbol", "isin", "company_name"]]

nifty500_on("2019-06-28")   # 501 rows; 501 = 500 companies + Tata Motors DVR (in the index until Aug 2024)
```

Expect 500 or 501 regular members (501 while TATAMTRDVR was a separate line, Apr 2016 to Aug 2024),
plus 0 to 4 placeholders during demergers.

## How it was built

Three NSE sources, each used for what it is authoritative on:

1. **Month-end constituent files**, Apr 2013 to Mar 2022: `niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_data<Mon><Year>.zip`
   (108 files; NSE stopped publishing NIFTY 500 in these after Mar 2022). These set who was a member
   at each month-end.
2. **NSE's inclusion/exclusion log** `archives.nseindia.com/content/indices/IndexInclExcl.xls`
   (NIFTY 500 sheet, to Sep 2020) and **NSE Indices press releases** (`niftyindices.com/press-releases`,
   every equity release since Jun 2020, 148 used). These give the exact effective date of each change, and
   after Mar 2022 they are the only record: the list is rolled forward from the 31 Mar 2022 file one
   press release at a time (semi-annual reviews, one-off replacements, demergers, revocations).
3. **NSE bhavcopy** (ISIN per symbol per day) and **NSE `symbolchange.csv`** to follow companies through
   symbol renames and ISIN changes. Two renames missing from `symbolchange.csv` (e.g. BURGERKING to
   RBA) were caught by matching ISINs.

Handled by hand, each from the press release named in the file:
- 13 demergers since 2022 (placeholder date, listing date, exclusion date).
- Revocations: IREDA's inclusion and V-Guard's exclusion cancelled (Mar 2024); Vodafone Idea's
  exclusion cancelled and Prism Johnson excluded instead (Sep 2024).
- TATAMTRDVR removed 30 Aug 2024 when the DVR shares were cancelled.
- 8 changes from 2013 to 2019 where the month-end file and NSE's log used different company names
  (Future Ventures, Styrolution/INEOS, Polaris, Strides, KPIT, IIFL).

## Validation

The rebuilt membership was compared, by ISIN, with **128 NSE snapshots**: all 108 month-end files and
20 copies of NSE's `ind_nifty500list.csv` (19 from archive.org, 2014 to Oct 2026, and the live file on
21 Oct 2026). **125 match exactly.** The other 3:

- 22 Jan 2014 and 31 Mar 2015: same companies, different symbol (DCB/DCBBANK, IBSEC/IBVENTURES)
  because NSE's file and the symbol change were a day or so apart. Membership agrees.
- 4 May 2022: NSE's press release (`ind_prs05042022.pdf`) makes the AARTIIND to GMRINFRA swap
  effective 4 May 2022. The archived copy of NSE's CSV from that afternoon had not yet been refreshed.
  This file follows the press release. Every snapshot from Oct 2022 onwards agrees.

The 2022 to 2026 roll-forward matched NSE at all 14 snapshots in that period, including every
demerger placeholder NSE listed (Jun 2025: ABFRL, Siemens, Raymond; May 2026: the four Vedanta
entities; Sep and Oct 2026: HEG).

## Compared with the fund's `nifty-500-list` (data API, 192.168.90.92)

At the 120 month-ends from Oct 2016 to Sep 2026, the fund's list was missing a median of 5 official
members (up to 70) and had a median of 1 name that was not a member (up to 32). It carries
445 to 493 names for most of Apr 2022 to Oct 2025, and its changes land in monthly batches up to
a month after NSE's effective date (e.g. GMRINFRA: official 4 May 2022, fund 17 Jun 2022). Prefer
this file for anything that depends on index membership.

## Caveats

- Membership only. No index weights: the NSE month-end PDFs print weights that sum to about 102%, so
  they were not carried over.
- Before Sep 2020, exact change dates come from NSE's log matched by company name. Where a change
  appears in the month-end files but not in the log, the date was set by hand (listed above). All
  month-end memberships are as NSE published them.
- After Mar 2022, there is no NSE month-end file. Membership there rests on the press releases and is
  checked at the 14 snapshot dates, not at every month-end.
- Placeholders for a few early demergers have no ISIN because NSE never published one in a file
  we hold (DUMMYSANOF, DUMMYRAYMD, DUMMYITC, DUMMYTATAM, DUMMYSKFIN).
- Sources are NSE public documents, used for internal research. Not for redistribution.

## Registering it with the pipeline (not done yet)

`ros/data/universes.py` lists `nifty500_membership_history` as a needed series. To register this file,
add to `data/raw/MANIFEST.yaml`:

```yaml
  - name: nifty500_membership_history
    kind: membership
    frequency: daily
    file: nifty500/nifty500_membership.csv
    date_column: start_date
    pit_status: point_in_time
    licence: "Rebuilt from NSE Indices public documents (month-end files, IndexInclExcl.xls, press releases); internal research use; not redistributed"
    coverage_note: "every NIFTY 500 membership spell 2013-04-18 to 2026-10-21 with NSE effective dates; symbol valid during each spell; ISIN; demerger placeholders flagged"
    caveats:
      - "Membership only, no weights."
      - "After Mar 2022 rests on NSE press releases, checked at 14 NSE snapshots rather than every month-end."
      - "Exclude entry_type demerger_placeholder (not tradable) and usually demerger_temporary from strategy universes."
```
