# Lightyear daily (Python) against the Barra site: reconciliation of one book

Quant AI Researcher · 2026-11-13 · read-only: no calculation, data or weight was changed to produce this.

**Headline.** The two daily return series do not match exactly. They correlate 0.9944 over 3,056 shared days; the site
earns 0.61 points a year more. Lightyear's own daily series rebuilds exactly from its trades and prices, so no error was
found in Lightyear's daily calculation. The largest cause of the gap is prices: the site uses Barra total returns
(dividends in) and Lightyear uses price returns. One upload mapping looks wrong (CGPOWER). 0.05 points a year is unexplained
in sum, and the site's own series could not be rebuilt exactly from its weights (see section 6).

## 1. What was compared

| | Lightyear | Barra site |
|---|---|---|
| Book | Run 20261111-163906-237b (Clenow rules, NIFTY 500 members, cost 0 bp, cash at 0%) | The same run's weights, uploaded 2026-11-13, weight book "Uploaded long only (unopt_lo)", no optimiser |
| First and last return | 2014-01-02 to 2026-09-18 | 2014-01-02 to 2026-06-10 |
| Trading days | 3,146 (3,076 to 2026-06-10) | 3,056 |
| Universe | NIFTY 500 members (point in time), 658 ISINs ever held | All but one of them: DALMIABHA has no Barra ID |
| Stored weights | 19,501 holdings rows to the site's last date | 19,481 rows stored, each equal to the row sent (largest difference 0) |

**Finding number one: the date range and day count are not identical.** The site's data stops on 2026-06-10 (70 Lightyear
days later are not on the site), and the site has no Muhurat or special sessions (20 Lightyear days). Everything below is on
the 3,056 days both have unless it says otherwise.

## 2. The numbers

(a) = Lightyear daily as it stands: 252 days, sample stdev, CAGR on calendar days / 365.25, risk-free rate 5%, compounded
drawdown. (b) = the same daily returns under the site's conventions (`ros/metrics/core.py` `site_block()`, a reconciliation
mode; it replaces nothing). Barra = the site's own figures, not recomputed.

| Metric | Barra | (b) Python, Barra mode, shared days | Difference (Barra - b) | (a) Lightyear daily, to 2026-06-10 | (a) Lightyear daily, whole run |
|---|---|---|---|---|---|
| Annual return | 0.1891 | 0.1830 | +0.0061 | 0.1867 | 0.1894 |
| Volatility | 0.1667 | 0.1680 | -0.0014 | 0.1689 | 0.1680 |
| Sharpe | 1.1344 | 1.0891 | +0.0453 | 0.8090 | 0.8297 |
| Sortino | 1.2623 | 1.1939 | +0.0684 | 1.0712 | 1.0996 |
| Maximum drawdown | 0.2633 | 0.2511 | +0.0121 | 0.2424 | 0.2424 |
| Hit rate (days with a gain) | 0.5815 | 0.5416 | +0.0399 | 0.5432 | 0.5442 |
| Information ratio | -0.3698 (stock-specific return only) | not computable: Lightyear has no stock-specific return | n/a | 0.4071 (against NIFTY 500) | 0.4301 |

The site's formulas themselves are confirmed: its return, volatility, Sharpe, drawdown, hit rate and information ratio
rebuild exactly from its own daily series. Its Sortino does not, to the fourth digit (1.2623 against 1.2615).

**Why the whole-run Lightyear figure (18.94%) sits closer to Barra (18.91%) than the same-days figure (18.30%).** It is a
coincidence of two offsetting things, not agreement. The whole run contains 90 days the site does not have: the 20 special
sessions (they add up to +6.80%, mostly Muhurat gains) and the 70 days after 2026-06-10 (+7.81%). Together they lift
Lightyear's figure by 0.64 points a year. The site, on its own days, earns 0.61 points a year more than Lightyear for data
reasons (section 4). The two happen to be the same size.

## 3. Bridge from Barra to Lightyear daily

| Step | Annual return | Volatility | Sharpe | Maximum drawdown |
|---|---|---|---|---|
| Barra site | 0.1891 | 0.1667 | 1.1344 | 0.2633 |
| Data differences on shared days (section 4) | -0.0061 | +0.0014 | -0.0453 | -0.0121 |
| = (b) Python, Barra mode, 3,056 shared days | 0.1830 | 0.1680 | 1.0891 | 0.2511 |
| Add the 20 Lightyear-only sessions (still Barra conventions) | 0.1873 | 0.1683 | 1.1129 | 0.2575 |
| 250 to 252 days; mean x 250 to CAGR on calendar days; summed to compounded drawdown | 0.1867 | 0.1689 | 1.1054 | 0.2424 |
| Subtract the 5% risk-free rate in Sharpe (0.05 / 0.1689) | | | 0.8090 | |
| = (a) Lightyear daily to 2026-06-10 | 0.1867 | 0.1689 | 0.8090 | 0.2424 |
| Add the 70 days after the site's last date | 0.1894 | 0.1680 | 0.8297 | 0.2424 |
| = (a) Lightyear daily, whole run | 0.1894 | 0.1680 | 0.8297 | 0.2424 |

Every step after the first line is arithmetic on Lightyear's own series, so it closes with no residual. Sortino is not
bridged step by step: the site divides by the stdev of the negative days, Lightyear by a downside deviation below the
risk-free rate, and the two are different measures (1.1939 in Barra mode, 1.0712 in Lightyear's). The only part with a
residual is the first step, the data differences.

## 4. The daily series, date by date

- 3,056 shared days. Correlation 0.9944. Mean absolute gap 3.6 bp, median 1.2 bp.
- Equal within 0.01 bp on 341 days; within 1 bp on 1,365; within 5 bp on 2,457; more than 10 bp apart on 238; more than
  50 bp apart on 14.
- Sum of (site - Lightyear) over the shared days: +7.44%, which is +0.608 points a year.

Both sides were then rebuilt stock by stock (`recon_stock_days.csv`, 92,448 stock-days). Lightyear's rebuild, position value
/ NAV times the Ace adjusted-close return, reproduces `daily_returns.csv` exactly (largest difference under 0.0000001 bp).
For each stock-day, site contribution - Lightyear contribution = w_L x (r_B - r_L) (price effect) + (w_S - w_L) x r_B
(weight effect).

| Cause | Size, points a year | Evidence | Class |
|---|---|---|---|
| **Prices: dividends.** Site return above Lightyear's by 0.1% to 5% | +1.43 | 612 stock-days, median gap 0.64%, clustered in July to September and February (the dividend months). Not checked against a dividend file. Examples: COALINDIA 2023-11-21 (-3.90% against +0.49%), CARERATING 2014-09-24 (-4.42% against +0.34%), VEDL 2022-05-06 (-11.06% against -3.28%), IDFC 2023-02-13 (-14.32% against -2.20%) | (ii) convention: Lightyear is price return, stated on every label |
| **Prices: site return below Lightyear's by 0.1% to 5%** | -0.72 | 172 stock-days. 155 of them sit within two sessions of an opposite gap in the same stock: the same price move booked on different days, so most of this nets against the row above. The largest name is CGPOWER (next row but one) | (iii) data timing; partly the mapping below |
| **Prices: one-day gaps of 5% or more** | -0.11 | 25 stock-days: CGPOWER 2023-04-25 (+1.22% against -11.83%), CGPOWER 2023-02-03, plus the two large dividends above (VEDL, IDFC), which belong with dividends | mapping and dividends |
| **Mapping: CGPOWER looks mapped to the wrong Barra ID** | -0.24 (inside the three rows above) | ISIN INE067A01029 was uploaded as INDAFG1. Over 355 held days the two return series correlate 0.37; every other name's median is 0.99995. The bridge also puts INE299U01018 (a different company after the 2016 demerger) on the same ID | (iii) upload bridge error; fix proposed below |
| **Calendar: first site day after a Lightyear-only session** | +0.19 | 20 days, listed below. On the site's own series the day after carries part of the missing session | (ii) convention |
| **Lightyear wholly in cash, the site still holds** | +0.09 | 216 days. Lightyear's return is exactly 0; the site's book keeps about 0.9% invested (its smallest weight sum is 0.94%, never 0) and moves 2.9 bp a day on average | (iii) site or upload behaviour: no row is uploaded for an all-cash date |
| **Weights: drift and rounding** on days where returns agree within 0.1% | +0.09 | 90,383 stock-days. Mean invested weight 80.81% in Lightyear, 80.87% on the site. The site drifts its weights with total returns, Lightyear with price returns | (ii) follows from dividends |
| **Name not on the site: DALMIABHA** (INE439L01019, no Barra ID) | -0.03 | 92 stock-days, 2016-07-08 to 2016-12-07, weight about 3% | (iii) no Barra ID |
| **Weights: on one side only that day** | +0.02 | 301 stock-days; mostly PIRAMALFIN in 2016, held under two Barra IDs in this comparison's own keying, which nets to zero | artefact of this check |
| **Idle cash** | 0.00 | The card's cash rate is 0% on this run; the site pays nothing on cash | none on this run |
| **250 against 252, mean x 250 against CAGR** | 0.00 | Removed in set (b); confirmed by the bridge closing | (ii) |
| **Unexplained** | +0.05 net | See section 6 | open |

The rows are measured two ways and do not add to 0.608 line by line: by date, the 216 cash days give +0.086, the 20
days after a special session +0.190 and the other 2,820 days +0.333. By stock, the other 2,820 days give +0.681 and the
days after a special session -0.205. The difference between the two views is the residual of section 6.

**Lightyear-only sessions (20), with Lightyear's return in bp:** 2014-03-22 (+41.8), 2014-10-23 (+72.0), 2015-02-28
(+136.7), 2015-11-11 (+40.0), 2016-10-30 (+75.1), 2017-10-19 (-30.8), 2018-11-07 (+2.5), 2019-10-27 (+167.4), 2020-02-01
(-270.5), 2020-11-14 (+80.0), 2021-11-04 (+100.6), 2022-10-24 (+79.5), 2023-11-12 (+136.9), 2024-01-20 (+39.6),
2024-03-02 (+89.1), 2024-05-18 (+133.9), 2024-11-01 (+81.0), 2025-02-01 (-22.2), 2025-10-21 (+57.0), 2026-02-01 (-330.2).

**Weight timing.** A site weight dated t earns the return of t+1 (a lag of 0 or 2 days fits far worse: mean error 3.9 and
4.1 bp against 1.6 bp). Lightyear fills at the execution day's close, so the upload date is the execution date. Two
execution dates fall on Muhurat sessions (2015-11-11, 2018-11-07) and were uploaded on the next site day: 9 rows.

## 5. The 20 largest stock-day differences

| Date | Stock | Lightyear weight | Site weight | Lightyear return | Barra return | Difference, bp of the book | Cause |
|---|---|---|---|---|---|---|---|
| 2016-11-15 | DALMIABHA | 4.18% | 0 | -12.49% | none | +52.2 | no Barra ID |
| 2016-11-11 | DALMIABHA | 4.45% | 0 | -10.14% | none | +45.2 | no Barra ID |
| 2020-02-03 | DLF | 3.36% | 3.66% | +0.85% | -11.36% | -44.5 | calendar: Barra's return spans Saturday 2020-02-01 |
| 2023-04-25 | CGPOWER | 3.39% | 3.37% | +1.22% | -11.83% | -44.0 | mapping (wrong Barra ID) |
| 2026-02-02 | MUTHOOTFIN | 4.36% | 4.76% | +1.20% | -7.69% | -41.8 | calendar: spans Sunday 2026-02-01 |
| 2026-02-02 | MCX | 3.12% | 3.49% | +3.96% | -8.16% | -40.9 | calendar |
| 2026-02-02 | BANKINDIA | 3.84% | 4.11% | +0.82% | -7.57% | -34.3 | calendar |
| 2023-02-13 | IDFC | 2.73% | 2.74% | -14.32% | -2.20% | +33.1 | dividend (price fell by the payout) |
| 2015-11-13 | SAMMAANCAP | 0 | 3.07% | 0 | -10.22% | -31.4 | calendar: bought on Muhurat 2015-11-11, uploaded one site day later |
| 2016-11-09 | PIRAMALFIN | 2.86% | 0 | -10.48% | -2.93% | +30.0 | artefact: two Barra IDs for one ISIN in this check |
| 2016-11-09 | PIRAMALFIN (INDDVO1) | 0 | 2.83% | 0 | -10.48% | -29.7 | the other half of the row above |
| 2026-02-02 | INDIANB | 3.81% | 3.91% | -0.99% | -8.43% | -29.2 | calendar |
| 2023-02-03 | CGPOWER | 3.10% | 3.08% | +1.03% | -8.18% | -28.4 | mapping |
| 2026-02-02 | HINDCOPPER | 2.01% | 2.05% | +1.89% | -10.99% | -26.3 | calendar |
| 2022-05-06 | VEDL | 3.31% | 3.22% | -11.06% | -3.28% | +26.1 | dividend |
| 2026-02-02 | NATIONALUM | 2.75% | 3.03% | +4.38% | -4.09% | -24.4 | calendar |
| 2015-03-02 | INDUSINDBK | 4.00% | 3.83% | +3.05% | +9.25% | +23.2 | calendar: spans Saturday 2015-02-28 |
| 2016-07-22 | DALMIABHA | 3.35% | 0 | +6.73% | none | -22.5 | no Barra ID |
| 2016-11-11 | PIRAMALFIN (INDDVO1) | 0 | 2.62% | 0 | -8.53% | -22.3 | artefact, as above |
| 2016-11-11 | PIRAMALFIN | 2.51% | 0 | -8.53% | -4.68% | +21.4 | artefact, as above |

By cause: calendar 9, no Barra ID 3, artefact of this check 4, mapping 2, dividend 2.

## 6. What could not be verified

- **The site's daily series is not exactly its weights times the Barra return file.** Stored drifted weight on t-1 times
  the Barra daily return of t (the file at the returns service) misses the site's own series by 1.6 bp a day on average, by
  more than 1 bp on 607 days, and by up to 103 bp. In sum it is small (-0.57% over the period, 0.05 points a year), but it
  hides two larger opposite pieces: -0.35 points a year on ordinary days and +0.40 on the 20 days after a special session.
  The errors are no larger on upload dates than on other days, so it is not weight timing. It looks tied to days with large
  single-stock returns. Which return source the site itself uses was not established. Until it is, the per-stock sizes in
  section 4 carry an error of this order.
- **Dividends** are inferred from the size, sign and season of the gaps, not confirmed against a dividend file.
- **CGPOWER**: the low correlation is measured; which Barra ID is the right one was not confirmed.
- **Why the site keeps about 0.9% invested** on Lightyear's all-cash days was not established.
- **The site's Sortino** does not rebuild to the fourth digit.
- **IC** (the "next day's specific return" rule) cannot be checked: no stock-level specific returns are on file.

## 7. Excel 'Daily calculations' against Python set (a)

The sheet carries Lightyear's own daily formulas (252 days, CAGR, risk-free rate, compounded drawdown). The daily beta was
the one formula that differed in form from Python; it was corrected earlier today (covariance over variance on returns
minus the card's cash rate). The workbook-against-Python tests pass on the current code. **This run's workbook on disk must
be rebuilt once more before it is read**: it was last built while the sheet briefly showed the Barra-mode formulas.

## 8. Classification and proposed fixes

**(i) Lightyear errors to fix: none found.** Lightyear's daily series rebuilds exactly from its own trades and prices, and
set (b) differs from Barra only through data.

**(ii) Legitimate convention differences, to leave and document:**
250 against 252 days; mean x 250 against CAGR; Sharpe and Sortino with or without the risk-free rate; summed against
compounded drawdown; price returns against total returns (dividends); Muhurat and special sessions; the site's data end.

**(iii) Barra-side or upload issues (none changes a Lightyear result):**

| Item | Proposed fix | Where |
|---|---|---|
| CGPOWER uploaded under a Barra ID whose returns do not track it | Confirm the right ID for INE067A01029 against the site's own security list; correct the bridge row; add a check that refuses any ISIN whose return correlation with its Barra ID is under 0.9 | the tester's bridge, not Lightyear |
| DALMIABHA has no Barra ID | Ask the data owner for the ID, or accept and keep reporting it as unmapped | the tester's bridge |
| The site keeps about 0.9% invested on all-cash days | Find out what the site does on a date with no upload row; if needed upload an explicit all-cash row | the tester's upload |
| The site's series differs from its weights times the return file | Ask the site's owner which return source the analytics use, and whether large returns are treated | the site |

## 9. Files

- Site figures and the daily series: `barra_site.json`, `crosscheck.json`, `t7_daily.csv` in the tester's folder for this run.
- Stock-day table and class totals: `recon_stock_days.csv`, `recon_summary.json` (same folder); script
  `scripts/reconcile_stock_days.py` in the tester.
- Set (b): `ros/metrics/core.py` `site_block()`; pinned by `tests/test_formula_reference.py`.

Nothing was changed as a result of these findings. The decision on each item is yours.

Quant AI Researcher
