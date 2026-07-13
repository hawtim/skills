# Data sources and verification limits

## Primary sources

- Public Sheet: `1G1E0qtLzt1WulfUk2uSxXrm_HNKejTMwwI-4KF3OG9w`
  - Trades gid `0`
  - Data gid `827729252`
- Patreon rule page: `https://www.patreon.com/TheMarketMemo/posts/hi5zu-he-90799255`

## Independent price check

Use unadjusted Yahoo daily OHLC for execution-price and D+1–D+3 low checks. A transaction price is valid when it is inside the daily range plus 0.25% tolerance. The tolerance covers source rounding and executions around official prints.

Futu OpenD can be used for a second spot-check when available. Preserve the provider and as-of date in the report.

## Accounting limits

The Sheet contains securities transactions, dividends, and withholding taxes, but no complete external deposit/withdrawal or cash-balance ledger. Therefore:

- Current holdings and invested ETF market value can be rebuilt.
- Gross and net dividends can be rebuilt.
- The Sheet's `Total Value = ETF market value + cumulative gross dividends` can be reproduced arithmetically.
- True brokerage account assets, TWR, and an audited CAGR cannot be established.
- XIRR is an estimate under the explicit assumption that each purchase is fresh external capital and every sale/distribution is withdrawn. It is not a substitute for a complete cash ledger.

Never describe author-controlled Sheet/Patreon evidence as independent audit evidence.
