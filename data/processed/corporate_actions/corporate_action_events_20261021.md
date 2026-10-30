# Corporate-action event list for sign-off: Clenow momentum

Built only from the cached NSE bhavcopy (cache/, 2021-10-04 to 2026-10-05). Nothing fetched. Nothing here is signed off.
Full list with evidence per row: `outputs/lightyear/20261016-102923-bdc1/corporate_action_events.csv`

## What was classified
- Names: every ISIN that was in the top 550 by 60-day traded value on any day.
- Days checked: every day whose close-to-close ratio is outside 0.72-1.40 (245 days), every day within two sessions of an ISIN change, and every in-band fall of 14-28% that sits within 6% of a standard split/bonus ratio.
- Evidence used (bhavcopy only): ISIN change on the same symbol; closeness of the price ratio to a standard split/bonus ratio (3%/6% band); whether the day's traded value jumped (a corporate action does not move value, news does); whether share volume was rescaled afterwards.
- NSE's own PREV field was checked and is NOT used: it equals the previous close even on 10-for-1 splits (e.g. TATASTEEL 2022-07-28), so it carries no adjustment information here.

## Counts
- Rows: 734  (of which 263 are labelled to be adjusted; 124 of those fall on a day the stock was in the top 550.)
- SPLIT/BONUS (adjust): 250   DEMERGER (adjust): 13   REAL (keep): 471
- Revised 2026-10-16 at the operator's Gate A notes: IRCTC 2021-10-28 (5-for-1 split) added, it was missing; TATAMOTORS 2025-10-14, SIEMENS 2025-04-07, ABFRL 2025-05-22 and VEDL 2026-04-30 changed from SPLIT/BONUS to DEMERGER at the observed one-day ratio. ALLCARGO 2024-01-02 and CUPID 2026-03-09 are unchanged and still to verify.
- Out-of-band days labelled REAL: 5: ADANIENT 2023-02-01, ZEEL 2024-01-23, IEX 2025-07-24 (named by the operator) plus ALLCARGO 2024-01-02 and CUPID 2026-03-09, which look more like a demerger and a bonus and need a human look.
- Rows needing a human decision (confidence below high, or any out-of-band day): 121.
- In-band REAL rows (466) are ordinary falls of 14-28% near a ratio with no sign of an action. Kept as real.

## Known weak spots
- A bonus or demerger ex-date often has a loud traded value (index inclusion, arbitrage), so the value test alone cannot always tell it from news. Out-of-band moves near a standard ratio are therefore labelled SPLIT/BONUS at medium confidence even when value jumped.
- DEMERGER rows have no standard ratio to use; the factor is the observed one-day ratio, which leaves the day's market move inside the adjustment. Low confidence, human check needed.
- Six special weekend or holiday sessions that the index workbook has are not in the bhavcopy cache: 2023-11-12, 2024-01-20, 2024-03-02, 2024-05-18, 2025-02-01, 2026-02-01. They are treated as non-trading days for stocks.
