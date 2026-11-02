# NIFTY 500 universe v2: coverage report

Quant AI Researcher by Harshil Pahuja

Built 2026-11-02T10:36+05:30 from the holdings workbook, the Alpha Lab pull of 2026-10-30 and the NSE-rebuilt spells (git 6e09344).

## Definition of 100%

A date is 100% covered when every NSE member on that date is in the universe (members = NSE count), every member has an ISIN, and every member has an Ace close within the engine's 5-session carry. The last condition is NOT met on any date before 2022: the names below are in the universe and cannot be traded. Nothing is rounded up.

## By review date

| review_date | members_v2 | isin_in_ace_master | isin_nse_only | ace_priced | unpriced | members_v1 | v1_priced | nse_members | v2_vs_nse_off | v1_vs_nse_off |
|---|---|---|---|---|---|---|---|---|---|---|
| 2013-09-27 | 500 | 469 | 31 | 468 | 32 | 460 | 460 | 500 | 30 | 66 |
| 2014-03-31 | 500 | 476 | 24 | 475 | 25 | 473 | 473 | 500 | 0 | 27 |
| 2014-09-30 | 500 | 482 | 18 | 481 | 19 | 479 | 479 | 500 | 0 | 21 |
| 2015-03-31 | 500 | 484 | 16 | 483 | 17 | 481 | 481 | 500 | 0 | 19 |
| 2015-09-30 | 500 | 485 | 15 | 484 | 16 | 482 | 482 | 500 | 0 | 18 |
| 2016-03-31 | 500 | 485 | 15 | 484 | 16 | 482 | 482 | 500 | 0 | 18 |
| 2016-09-30 | 501 | 488 | 13 | 487 | 14 | 484 | 484 | 501 | 0 | 17 |
| 2017-03-31 | 501 | 490 | 11 | 490 | 11 | 487 | 487 | 501 | 0 | 14 |
| 2017-10-03 | 501 | 494 | 7 | 494 | 7 | 487 | 487 | 501 | 0 | 56 |
| 2018-04-02 | 501 | 494 | 7 | 494 | 7 | 492 | 492 | 501 | 0 | 57 |
| 2018-10-01 | 501 | 496 | 5 | 496 | 5 | 492 | 492 | 501 | 0 | 101 |
| 2019-04-01 | 501 | 496 | 5 | 496 | 5 | 494 | 494 | 501 | 0 | 7 |
| 2019-09-30 | 501 | 498 | 3 | 498 | 3 | 496 | 496 | 501 | 0 | 5 |
| 2020-03-31 | 501 | 498 | 3 | 498 | 3 | 496 | 496 | 501 | 0 | 5 |
| 2020-09-30 | 501 | 499 | 2 | 499 | 2 | 498 | 498 | 501 | 0 | 3 |
| 2021-03-31 | 501 | 499 | 2 | 499 | 2 | 498 | 498 | 501 | 0 | 3 |
| 2021-09-30 | 501 | 500 | 1 | 500 | 1 | 499 | 499 | 501 | 0 | 2 |
| 2022-03-31 | 501 | 500 | 1 | 500 | 1 | 499 | 499 | 501 | 0 | 2 |
| 2022-09-30 | 501 | 500 | 1 | 500 | 1 | 499 | 499 | 501 | 0 | 2 |
| 2023-03-31 | 501 | 500 | 1 | 500 | 1 | 499 | 499 | 501 | 0 | 2 |
| 2023-10-03 | 501 | 500 | 1 | 500 | 1 | 499 | 499 | 501 | 0 | 2 |
| 2024-04-01 | 501 | 500 | 1 | 500 | 1 | 499 | 499 | 501 | 0 | 2 |
| 2024-09-30 | 500 | 499 | 1 | 499 | 1 | 498 | 498 | 500 | 0 | 2 |
| 2025-04-01 | 500 | 500 | 0 | 500 | 0 | 499 | 499 | 500 | 0 | 1 |
| 2025-09-30 | 501 | 501 | 0 | 500 | 1 | 500 | 499 | 500 | 1 | 2 |
| 2026-04-01 | 500 | 500 | 0 | 500 | 0 | 500 | 500 | 500 | 0 | 0 |
| 2026-09-30 | 504 | 504 | 0 | 503 | 1 | 504 | 503 | 500 | 52 | 52 |

## By year (every trading day)

| year | days | members_min | members_max | priced_min | priced_max | priced_mean | unpriced_mean | v1_members_min | v1_priced_mean |
|---|---|---|---|---|---|---|---|---|---|
| 2013 | 145 | 489 | 500 | 457 | 468 | 466.2 | 33.8 | 460 | 461.9 |
| 2014 | 244 | 500 | 500 | 467 | 481 | 474.7 | 25.3 | 466 | 472.7 |
| 2015 | 248 | 500 | 500 | 481 | 484 | 482.8 | 17.2 | 479 | 480.8 |
| 2016 | 247 | 500 | 501 | 484 | 487 | 484.8 | 16.2 | 481 | 482.3 |
| 2017 | 248 | 501 | 501 | 487 | 495 | 490.7 | 10.3 | 484 | 486.2 |
| 2018 | 246 | 501 | 501 | 494 | 496 | 495.0 | 6.0 | 492 | 491.9 |
| 2019 | 245 | 500 | 501 | 493 | 499 | 496.2 | 4.8 | 494 | 494.4 |
| 2020 | 252 | 501 | 501 | 498 | 499 | 498.8 | 2.2 | 496 | 497.3 |
| 2021 | 248 | 501 | 501 | 499 | 500 | 499.5 | 1.5 | 498 | 498.5 |
| 2022 | 248 | 501 | 501 | 499 | 500 | 499.9 | 1.1 | 499 | 498.9 |
| 2023 | 246 | 501 | 501 | 499 | 500 | 499.5 | 1.5 | 499 | 498.5 |
| 2024 | 249 | 500 | 501 | 497 | 500 | 499.3 | 1.7 | 498 | 498.3 |
| 2025 | 249 | 500 | 501 | 499 | 501 | 500.1 | 0.9 | 498 | 499.1 |
| 2026 | 201 | 500 | 504 | 499 | 504 | 501.6 | 2.4 | 500 | 501.3 |

## The workbook's truncated pulls

| date | v2_members | nse_members | only_v2 | only_nse | v1_members |
|---|---|---|---|---|---|
| 2017-09-29 | 501 | 501 |  |  | 487 |
| 2018-06-29 | 501 | 501 |  |  | 492 |
| 2018-09-28 | 501 | 501 |  |  | 492 |

## Unpriced members (in the universe, cannot be traded)

| symbol | isin | company_name | first | last | dates |
|---|---|---|---|---|---|
| ABGSHIP | INE067H01016 | ABG Shipyard Ltd. | 2013-09-27 | 2016-03-31 | 6 |
| ADVENTHTL | INE28GN01010 | Advent Hotels International Ltd. | 2025-09-30 | 2025-09-30 | 1 |
| AMTEKAUTO | INE130C01021 | Amtek Auto Ltd. | 2013-09-27 | 2017-03-31 | 8 |
| BHUSANSTL | INE824B01021 | Tata Steel BSL Ltd. | 2017-03-31 | 2018-04-02 | 3 |
| CASTEXTECH | INE068D01021 | Amtek India Ltd. | 2013-09-27 | 2016-03-31 | 6 |
| COREEDUTEC | INE247G01024 | CORE Education & Technologies Ltd. | 2013-09-27 | 2014-03-31 | 2 |
| COX&KINGS | INE008I01026 | Cox & Kings Ltd. | 2013-09-27 | 2019-09-30 | 12 |
| DISHMAN | INE385W01011 | Dishman Carbogen Amcis Ltd. | 2013-09-27 | 2016-09-30 | 7 |
| DRDATSONS | INE928K01013 | Dr. Datsons Labs Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| ELDERPHARM | INE975A01015 | Elder Pharmaceuticals Ltd. | 2013-09-27 | 2014-09-30 | 3 |
| ESSAROIL | INE011A01019 | Essar Oil Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| ESSDEE | INE825H01017 | Ess Dee Aluminium Ltd. | 2014-03-31 | 2016-03-31 | 5 |
| FKONCO | INE575G01010 | Fresenius Kabi Oncology Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| GEODESIC | INE371D01029 | Geodesic Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| GTOFFSHORE | INE892H01017 | GOL Offshore Ltd. | 2013-09-27 | 2014-03-31 | 2 |
| GUJNRECOKE | INE110D01013 | Gujarat NRE Coke Ltd. | 2013-09-27 | 2015-03-31 | 4 |
| INFINITE | INE486J01014 | Infinite Computer Solutions (India) Ltd | 2014-03-31 | 2014-03-31 | 1 |
| INNOIND | INE549I01011 | Innoventive Industries Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| ISEC | INE763G01038 | ICICI Securities Ltd. | 2018-10-01 | 2024-09-30 | 13 |
| JBCHEPHARM | INE572A01036 | JB Chemicals & Pharmaceuticals Ltd. - (Amalgamated) | 2026-09-30 | 2026-09-30 | 1 |
| JMTAUTOLTD | INE988E01036 | JMT Auto Ltd. | 2016-09-30 | 2017-03-31 | 2 |
| JPASSOCIAT | INE455F01025 | Jaiprakash Associates Ltd. | 2013-09-27 | 2019-04-01 | 12 |
| JPINFRATEC | INE099J01015 | Jaypee Infratech Ltd. | 2013-09-27 | 2016-09-30 | 7 |
| KEMROCK | INE990B01012 | Kemrock Industries and Exports Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| KWALITY | INE775B01025 | Kwality Ltd. | 2016-09-30 | 2018-04-02 | 4 |
| LITL | INE785C01048 | Lanco Infratech Ltd. | 2013-09-27 | 2016-09-30 | 7 |
| MANPASAND | INE122R01018 | Manpasand Beverages Ltd. | 2016-09-30 | 2018-10-01 | 5 |
| ORBITCORP | INE628H01015 | Orbit Corporation Ltd. | 2013-09-27 | 2014-03-31 | 2 |
| POLARIS | INE763A01023 | Polaris Financial Technology Ltd. | 2013-09-27 | 2017-10-03 | 5 |
| PSL | INE474B01017 | PSL Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| RASOYPR | INE904G01038 | Rasoya Proteins Ltd. | 2014-03-31 | 2015-03-31 | 3 |
| REIAGROLTD | INE385B01031 | Rei Agro Ltd. | 2013-09-27 | 2014-09-30 | 3 |
| RELCAPITAL | INE013A01015 | Reliance Capital Ltd. | 2013-09-27 | 2020-03-31 | 13 |
| ROLTA | INE293A01013 | Rolta India Ltd. | 2013-09-27 | 2017-03-31 | 8 |
| SHILPI | INE510K01019 | Shilpi Cable Tech Ltd. CABLES - | 2017-03-31 | 2017-10-03 | 2 |
| SHREEASHTA | INE538H01024 | Shree Ashtavinayak Cine Vision Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| SHRENUJ | INE633A01028 | Shrenuj & Co. Ltd. | 2013-09-27 | 2016-03-31 | 6 |
| SINTEX | INE429C01035 | Sintex Industries Ltd. | 2013-09-27 | 2016-09-30 | 7 |
| SKUMARSYNF | INE772A01016 | S. Kumars Nationwide Ltd. | 2013-09-27 | 2014-03-31 | 2 |
| SPTL | INE501W01021 | Sintex Plastics Technology Ltd. | 2018-04-02 | 2019-04-01 | 3 |
| SRIPIPES | INE943C01027 | Srikalahasthi Pipes Ltd. | 2015-09-30 | 2016-03-31 | 2 |
| TATASTLBSL | INE824B01021 | Tata Steel BSL Ltd. | 2013-09-27 | 2021-03-31 | 10 |
| TULIP | INE122H01027 | Tulip Telecom Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| UBHOLDINGS | INE696A01025 | United Breweries (Holdings) Ltd. | 2013-09-27 | 2013-09-27 | 1 |
| UTTAMSTL | INE699A01011 | Uttam Galva Steels Ltd. | 2013-09-27 | 2016-03-31 | 6 |

## Start rule warm-up (Sep-2013 review list before the 2013-12-31 signal)

465 of 500 members have 100 carried closes in the 100 sessions before the signal; 467 are priced on the signal day. Members short of warm-up:

| symbol | isin | company_name | closes_last_100 | closes_last_200 | priced_on_signal |
|---|---|---|---|---|---|
| ABGSHIP | INE067H01016 | ABG Shipyard Ltd. | 0 | 0 | False |
| AMTEKAUTO | INE130C01021 | Amtek Auto Ltd. | 0 | 0 | False |
| AMTEKINDIA | INE068D01021 | Amtek India Ltd. | 0 | 0 | False |
| BHUSANSTL | INE824B01021 | Tata Steel BSL Ltd. | 0 | 0 | False |
| COREEDUTEC | INE247G01024 | CORE Education & Technologies Ltd. | 0 | 0 | False |
| COX&KINGS | INE008I01026 | Cox & Kings Ltd. | 0 | 0 | False |
| DISHMAN | INE385W01011 | Dishman Pharmaceuticals & Chemicals Ltd. | 0 | 0 | False |
| DRDATSONS | INE928K01013 | Dr. Datsons Labs Ltd. | 0 | 0 | False |
| ELDERPHARM | INE975A01015 | Elder Pharmaceuticals Ltd. | 0 | 0 | False |
| ESSAROIL | INE011A01019 | Essar Oil Ltd. | 0 | 0 | False |
| ESSDEE | INE825H01017 | Ess Dee Aluminium Ltd. | 0 | 0 | False |
| FKONCO | INE575G01010 | Fresenius Kabi Oncology Ltd. | 0 | 0 | False |
| GTOFFSHORE | INE892H01017 | GOL Offshore Ltd. | 0 | 0 | False |
| GUJNRECOKE | INE110D01013 | Gujarat NRE Coke Ltd. | 0 | 0 | False |
| INFINITE | INE486J01014 | Infinite Computer Solutions (India) Ltd | 0 | 0 | False |
| INNOIND | INE549I01011 | Innoventive Industries Ltd. | 0 | 0 | False |
| JPASSOCIAT | INE455F01025 | Jaiprakash Associates Ltd. | 0 | 0 | False |
| JPINFRATEC | INE099J01015 | Jaypee Infratech Ltd. | 0 | 0 | False |
| LITL | INE785C01048 | Lanco Infratech Ltd. | 0 | 0 | False |
| ORBITCORP | INE628H01015 | Orbit Corporation Ltd. | 0 | 0 | False |
| POLARIS | INE763A01023 | Polaris Financial Technology Ltd. | 0 | 0 | False |
| PSL | INE474B01017 | PSL Ltd. | 0 | 0 | False |
| RASOYPR | INE904G01038 | Rasoya Proteins Ltd. | 0 | 0 | False |
| REIAGROLTD | INE385B01031 | Rei Agro Ltd. | 0 | 0 | False |
| RELCAPITAL | INE013A01015 | Reliance Capital Ltd. | 0 | 0 | False |
| ROLTA | INE293A01013 | Rolta India Ltd. | 0 | 0 | False |
| SHREEASHTA | INE538H01024 | Shree Ashtavinayak Cine Vision Ltd. | 0 | 0 | False |
| SHRENUJ | INE633A01028 | Shrenuj & Co. Ltd. | 0 | 0 | False |
| SINTEX | INE429C01035 | Sintex Industries Ltd. | 0 | 0 | False |
| SKUMARSYNF | INE772A01016 | S. Kumars Nationwide Ltd. | 0 | 0 | False |
| TULIP | INE122H01027 | Tulip Telecom Ltd. | 0 | 0 | False |
| UBHOLDINGS | INE696A01025 | United Breweries (Holdings) Ltd. | 0 | 0 | False |
| UTTAMSTL | INE699A01011 | Uttam Galva Steels Ltd. | 0 | 0 | False |
| DYNAMATECH | INE221B01012 | Dynamatic Technologies Ltd. | 53 | 142 | True |
| ZODIACLOTH | INE206B01013 | Zodiac Clothing Co. Ltd. | 71 | 167 | True |

## Price-history splice check (ISIN-stem matches and DHFL)

| ticker | isin | company_name | spell_from | spell_to | sessions_in_spell | closes_in_spell | max_gap_days_in_spell | max_abs_move_in_spell | after_spell | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| KSBPUMPS | INE999A01023 | KSB Ltd. | 2013-06-03 | 2017-03-31 | 946 | 946 | 6 | 0.168 |  | clean inside the spell |
| IPAPPM | INE435A01051 | Andhra Paper Ltd. | 2016-05-02 | 2017-03-31 | 230 | 230 | 4 | 0.094 |  | clean inside the spell |
| FAGBEARING | INE513A01022 | Schaeffler India Ltd. | 2013-06-03 | 2017-07-31 | 1028 | 1027 | 6 | 0.088 |  | clean inside the spell |
| NBVENTURES | INE725A01030 | Nava Ltd. | 2013-06-03 | 2020-09-30 | 1812 | 1812 | 6 | 0.2 |  | clean inside the spell |
| ORCHIDCHEM | INE191A01027 | Orchid Pharma Ltd. | 2013-06-03 | 2015-09-30 | 576 | 576 | 6 | 0.2 |  | clean inside the spell |
| PHILIPCARB | INE602A01031 | PCBL Chemical Ltd. | 2018-10-01 | 2022-01-12 | 814 | 814 | 4 | 0.154 |  | clean inside the spell |
| SRTRANSFIN | INE721A01047 | Shriram Finance Ltd. | 2013-06-03 | 2023-01-16 | 2382 | 2382 | 6 | 0.222 |  | clean inside the spell |
| RUCHISOYA | INE619A01035 | Patanjali Foods Ltd. | 2013-06-03 | 2017-09-29 | 1070 | 1070 | 6 | 0.2 |  | clean inside the spell |
| TUBEINVEST | INE149A01033 | Cholamandalam Financial Holdings Ltd. | 2013-06-03 | 2017-05-31 | 986 | 986 | 6 | 0.117 |  | clean inside the spell |
| HEXAWARE | INE093A01041 | Hexaware Technologies Ltd. | 2013-06-03 | 2020-09-30 | 1812 | 1812 | 6 | 0.2 |  | clean inside the spell |
| SUPPETRO | INE663A01033 | Supreme Petrochem Ltd. | 2013-06-03 | 2022-04-01 | 2185 | 2185 | 6 | 0.2 |  | clean inside the spell |
| ALOKTEXT | INE270A01029 | Alok Industries Ltd. | 2013-06-03 | 2017-03-31 | 946 | 946 | 6 | 0.2 |  | clean inside the spell |
| MONNETISPA | INE743C01021 | JSW Ispat Special Products Ltd. - (Amalgamation) | 2013-06-03 | 2015-09-30 | 576 | 576 | 6 | 0.2 |  | clean inside the spell |
| MCDOWELL-N | INE854D01024 | United Spirits Ltd. | 2013-06-03 | 2024-07-16 | 2752 | 2752 | 6 | 0.175 |  | clean inside the spell |
| NIITTECH | INE591G01025 | Coforge Ltd. | 2013-06-03 | 2020-08-19 | 1782 | 1782 | 6 | 0.244 |  | clean inside the spell |
| DHFL | INE202B01038 | Piramal Finance Ltd. | 2013-06-03 | 2020-06-30 | 1746 | 1746 | 6 | 0.426 |  | CHECK |
| 3IINFOTECH | INE748C01038 | 3I Infotech Ltd. | 2013-07-01 | 2013-09-30 | 63 | 63 | 4 | 0.19 |  | clean inside the spell |
| SUJANATOW | INE333I01044 | Neueon Corporation Ltd. | 2013-06-03 | 2013-08-30 | 63 | 47 | 3 | 0.1 |  | CHECK |
| TIDEWATER | INE484C01030 | Veedol Corporation Ltd. | 2016-05-02 | 2017-09-29 | 354 | 354 | 4 | 0.16 |  | clean inside the spell |
| SEINV | INE420C01059 | Paisalo Digital Ltd. | 2013-06-03 | 2016-04-29 | 716 | 715 | 6 | 0.2 |  | clean inside the spell |
| PIPAVAVDOC | INE542F01020 | Swan Defence and Heavy Industries Ltd. | 2013-06-03 | 2016-03-17 | 690 | 689 | 6 | 0.2 |  | clean inside the spell |
| RDEL | INE542F01020 | Swan Defence and Heavy Industries Ltd. | 2016-03-18 | 2017-09-15 | 370 | 370 | 5 | 0.147 |  | clean inside the spell |
| RNAVAL | INE542F01020 | Swan Defence and Heavy Industries Ltd. | 2017-09-18 | 2019-03-29 | 380 | 380 | 5 | 0.329 |  | clean inside the spell |
| MANDHANA | INE087J01028 | GB Global Ltd. | 2013-06-03 | 2015-12-31 | 637 | 637 | 6 | 0.126 |  | clean inside the spell |
| FUTUREVENT | INE220J01025 | Future Consumer Ltd. | 2013-06-03 | 2013-06-28 | 20 | 14 | 3 | 0.005 |  | CHECK |
| IIFLWAM | INE466L01038 | 360 One Wam Ltd. | 2020-07-01 | 2023-02-16 | 658 | 658 | 5 | 0.149 |  | clean inside the spell |
| ANGELBRKG | INE732I01021 | Angel One Ltd. | 2021-04-01 | 2021-11-10 | 151 | 151 | 4 | 0.2 |  | clean inside the spell |

## Note for Rohit

The folder 'Rohit Rakhecha - Adjusted Prices' is empty on this machine. The names listed as unpriced above are in the universe but have no price in the Ace file for the dates they were index members, so a backtest can neither buy nor hold them; most are companies that later failed. Price history for them is the only fix for the remaining survivorship bias.
