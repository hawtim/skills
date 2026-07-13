# Data Sources And Freshness

## Deterministic Collector

Use Yahoo chart JSON for U.S., Korea, Taiwan, and macro daily OHLCV history. Use Tencent's forward-adjusted (`qfq`) daily feed for mainland China ETF/index history so fund distributions and splits do not create false swing breaks. Label both as public market-data proxies, not exchange-certified feeds.

| Market | Allowed age at U.S. post-close report |
|---|---:|
| U.S. ETF/index/company | 2 natural days; allow weekends/holidays explicitly |
| Korea/Taiwan/China | 3 natural days; use the latest completed local session |
| VIX/rates/oil/USD/HYG | 3 natural days |

Critical anchors are `SOXX`, `SMH`, `QQQ`, and at least one valid anchor from two Asian regions. If critical coverage is below 70%, force `DATA_INSUFFICIENT / NO_NEW_RISK`.

## Qualitative Verification

Use primary or company-owned sources for:

- earnings releases and guidance;
- hyperscaler capital expenditure;
- memory pricing or supply agreements;
- export controls and sanctions;
- central-bank, inflation, labor, and Treasury developments;
- exchange/index methodology and official flow disclosures.

Use news only to discover a development. Tie any report overlay to a source date, transmission channel, and the specific score change.

## Noise Filter

A single-company headline cannot change the global regime unless it changes at least two of:

- ETF/index price structure;
- forward estimates or company guidance;
- regional semiconductor breadth;
- cross-market confirmation;
- macro discount-rate or liquidity conditions.

Mark missing data `UNAVAILABLE`, stale data `STALE`, and inadequate critical coverage `DATA_INSUFFICIENT`. Never substitute missing values with neutral confirmation.
