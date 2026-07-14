# 数据来源

| 数据 | 来源 | 频率 | 用途 |
|---|---|---:|---|
| SOXX 成分股与权重 | iShares SOXX 官方 `Holdings > All` 产品数据接口 | 日 | 宽度宇宙与权重 |
| 成分股、SOXX、SMH、XSD、SOXL、SOXS、`^SOX` | Yahoo Finance chart JSON | 日 | 均线、回撤、杠杆代理与行业趋势锚 |

- SOXX 是行业权重宇宙；SMH 和 XSD 是趋势/风格交叉核对，避免单一 ETF 结构主导叙事。
- TradingView 的 `NASDAQ:SOX` 是费城半导体指数；脚本用 `^SOX` 日线作行业价格趋势锚。它不含成分股宽度，不能取代 SOXX 当日持仓计算。
- 持仓接口返回的现金、抵押品与期货项目不属于股票宽度宇宙；脚本只保留 `assetClass = Equity` 的正权重成分股，并保存每日快照。
- SOXL/SOXX 只是杠杆多头偏好的价格代理。它可能受波动率、路径和再平衡影响，不能当成直接资金流或散户调查。
- 当成分股 ticker 在 Yahoo 不可用时记录为缺失；只有覆盖合格后才计算宽度和状态。
