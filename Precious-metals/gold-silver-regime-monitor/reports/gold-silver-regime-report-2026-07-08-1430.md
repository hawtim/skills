# 黄金白银日度监控｜2026-07-08 14:30｜Asia/Shanghai

## 结论
- Regime: DATA_INVALID
- Score: 12 / 100（昨日：-13）
- MACRO_ACTION: NO_TRADE
- EXECUTION_ACTION: MANUAL_CHECK_REQUIRED
- 建议战术仓目标：0.00%
- 当前战术仓：0.00%
- 建议变动：+0.00% 组合净值
- 战略底仓：HOLD_CORE（默认月度检查，目标 5.00%）

## 一句话原因
主导变化的是 POLICY_PATH_NEUTRAL、NOT_EXTENDED_VS_MA50、RISK_PREMIUM_NOT_CONFIRMED。资金流模块未确认，GLD 持仓、COT、WGC ETF 流量未纳入分子和分母。

## 四模块评分
| 模块 | 得分 | 上限 | 状态 | 核心变化 |
|---|---:|---:|---|---|
| 宏观转向 | 5 | 40 | 中性/压制 | 10Y 实际利率 20D 13.0bp；美元 20D 1.09% |
| 资金流确认 | 0 | 0 | 未确认 | GLD/COT/WGC 未接入，按规则缩放总分 |
| 价格结构 | 5 | 30 | 中性/压制 | Gold vs MA20 4146.20 / MA50 4393.89 / MA100 4630.87 |
| 风险环境 | 0 | 10 | 中性/压制 | VIX 10D -3.36；HY OAS 20D -3.0bp |

## 关键数据
| 指标 | 最新值 | 5D | 10D | 20D | 解释 |
|---|---:|---:|---:|---:|---|
| Gold close | 4070.70 | 见历史库 | 见历史库 | 见历史库 | Yahoo:GC=F / 2026-07-08 |
| 10Y real yield | 2.24% | N/A | 3.0bp | 13.0bp | FRED DFII10 |
| Broad USD | 120.69 | N/A | 1.09% | 1.09% | FRED DTWEXBGS |
| 2Y yield / policy proxy | FRED DGS2 | N/A | N/A | 8.0bp | 隐含政策利率未接入，使用 2Y 降级代理 |
| 10Y breakeven | FRED T10YIE | N/A | N/A | -11.0bp | 通胀预期代理 |
| GLD holdings | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | MVP 未接入官方持仓 |
| VIX | FRED VIXCLS | N/A | -3.36 | N/A | 风险偏好代理 |
| HY OAS | FRED BAMLH0A0HYM2 | N/A | N/A | -3.0bp | 信用风险代理 |

## 白银伴随观察
- Silver close: 58.72（Yahoo:SI=F / 2026-07-08）
- Silver MA20 / MA50: 63.07 / 71.05
- Silver distance to MA50: -17.36%
- 解释：白银当前仅作为贵金属风险偏好与工业属性的伴随观察，不覆盖黄金战术状态机。

## 触发器
- 已触发：
  - [ ] 加仓触发
  - [ ] 分批减仓触发
  - [ ] 硬性否决：无
  - [ ] 过热止盈
- 尚未满足的确认条件：
  1. 关键数据过期或缺失，禁止生成交易动作

## 未来 7 天事件风险
- FOMC、CPI、PCE、非农、国债拍卖和财政事件需要人工复核；当前 MVP 未接入官方日历。
- 事件日历只提高审查等级，不因日历本身自动交易。

## Agent 审计摘要
- 数据质量：FAIL
- 叙事标签：NARRATIVE_ONLY
- 数据年龄：price 0 天；real yield 2 天；USD 6 天。
- 反证：10Y 实际利率重新上行且美元 20 日转强，或金价跌破 MA50/MA100 并伴随资金流走弱。

来源：FRED:BAMLH0A0HYM2, FRED:DFII10, FRED:DGS10, FRED:DGS2, FRED:DTWEXBGS, FRED:T10YIE, FRED:VIXCLS, Yahoo:GC=F, Yahoo:SI=F。非投资建议；不自动下单。
