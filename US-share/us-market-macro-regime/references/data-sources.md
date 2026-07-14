# 数据源与新鲜度

## 优先级

1. 官方/原始来源：Federal Reserve、U.S. Treasury、BLS、BEA、FRED、Cboe、AAII、FINRA。
2. 交易所或指数提供方：Nasdaq、NYSE、Cboe。
3. 可复现的公开行情接口：Yahoo chart JSON，用于 ETF/指数趋势代理。
4. 新闻只用于发现事件；关键结论回到政策文件、统计发布或公司/交易所原文核验。

## 脚本数据

| 数据 | 首选 | 允许滞后 |
|---|---|---:|
| SPY/QQQ/IWM/RSP/VIX/VIX3M/UUP/HYG/LQD/ARKK | Yahoo chart JSON | 3 个自然日；周末/假期需注明 |
| 2Y、10Y、10Y 实际利率 | FRED CSV | 4 个自然日 |
| HY OAS | FRED CSV | 5 个自然日 |
| Cboe put/call | Cboe Daily Market Statistics | 2 个交易日 |
| AAII 情绪 | AAII survey | 10 个自然日（周频） |
| FINRA margin debt | FINRA | 45 个自然日（月频） |

## 频率纪律

- 周频/月频数据只解释中期拥挤度，不驱动单日交易结论。
- 08:30 上海时间使用最近一个完整美股收盘，期货或盘后数据必须单独标识。
- 使用代理品时写清“代理”，例如 UUP 不是 DXY，HYG/LQD 不是官方信用利差。
- 源失败时显示 `UNAVAILABLE`；不沿用未知日期的旧值。

## 当日事件核验

优先检查：Federal Reserve 日历与声明、BLS/BEA/Census 发布日历、U.S. Treasury 公告。宏观日历聚合页可用于发现线索，但不能成为唯一证据。
