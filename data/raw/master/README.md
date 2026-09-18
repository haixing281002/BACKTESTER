# The master universe

One long CSV you build. One row per (date, security). Drop it here and run:

```bash
python -m ros.data.master data/raw/master/universe.csv
```

Run that the moment a file lands, before building anything on it. A master
universe is the foundation of every number that follows, and its failures are
invisible once a backtest has run — the report looks identical either way.

## The shape

```csv
date,security_id,symbol,adj_close,in_universe,free_float_mcap,adv,sector
2015-01-01,INE001A01036,HDFCBANK,912.4,1,412000,1840,financials
2015-01-01,INE002A01018,RELIANCE,881.0,1,905000,3110,energy
```

**Required:** a date column, a security column, and a price column.
**Everything else is optional** and unlocks specific things:

| Column | Unlocks | Without it |
|---|---|---|
| `in_universe` | honest membership | the loader refuses the file |
| `adv` | capacity and turnover checks | `turnover_capacity` must be fed ADV by hand |
| `free_float_mcap` | cap weighting, size sorts | capacity is overstated |
| `sector` | sector-aware analysis | nothing; purely optional |
| `symbol` | readable reports | IDs everywhere |

Column names are matched loosely: `TradeDate`, `as_of`, `ISIN`, `SecId`,
`AdjustedClose`, `px_adj`, `IsMember`, `index_member`, `traded_value` all resolve.
Membership accepts `1/0`, `TRUE/FALSE`, `Y/N`.

## Key on a permanent ID, never on the symbol

NSE symbols get reused and renamed — mergers, demergers, company name changes.
Use ISIN or your own internal ID as `security_id`, and let `symbol` be a
time-varying attribute of it.

Key on symbol and a rename silently splices two different companies into one
price series, which looks completely clean and is the most expensive mistake to
fix later, because every downstream artifact inherits it.

## Dead companies must be IN the file

A delisted name stays, with rows up to its last trading day and `in_universe`
flipping to 0. Do not omit it.

The loader checks the survivorship signature: what share of securities still
have data on the final date. A real long Indian panel is well under 100% —
companies delist, merge and fall out of the index. Near 100% over a long sample
means the file was built from a *current* constituent list and back-filled, and
that inflates every result in a way nothing downstream can correct. The loader
refuses it.

## Fundamentals go in a separate file

They are quarterly and carry **two** dates — the period covered and the date the
number became public. Forcing them into a daily panel means forward-filling from
period end, which is precisely the look-ahead you are trying to avoid. Keep them
long: `security_id, period_end, publication_date, field, value`.

## Declare it, so provenance travels

In `data/raw/MANIFEST.yaml`:

```yaml
master:
  file: master/universe.csv
  pit_status: point_in_time     # the field that decides whether a LIVE claim
                                # may rest on this work
  licence: "<who owns this and what may we do with it>"
  caveats:
    - "<what would mislead someone reading a result built on this>"
```

`pit_status` is mandatory and is not a formality. Typing `point_in_time` without
checking is the easiest way to mislead everyone downstream, including yourself.
