# NIFTY 500 constituent updates

The holdings workbook (see `docs/DATA_SOURCES.md`) ends at its last quarterly
snapshot. When NSE's next semi-annual review has happened (effective end-March
or end-September) and the run extends past it, `ros.data.nifty500.staleness()`
says so. Drop the post-review constituent list here as one CSV per snapshot:

```
data/raw/nifty500_updates/2026-09-30.csv
```

- File name is the snapshot date, `YYYY-MM-DD.csv`, later than the workbook's
  last snapshot.
- Required column: `isin`. Optional: `symbol`, `company_name`, and sub-index
  flags `in_nifty50`, `in_next50`, `in_nifty100`, `in_midcap150`,
  `in_smallcap250` (1/0).
- About 500 rows; fewer than 480 is refused as a truncated list. Duplicate or
  malformed ISINs are refused.

The CSV is read as one more snapshot, cached with the workbook, and tracked in
git so a clone reproduces the same membership. Nothing is downloaded.
