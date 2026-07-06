# 黄金白银日度监控｜2026-07-07 14:30｜Asia/Shanghai

## 结论
- Regime: DATA_INVALID
- Score: 0 / 100
- MACRO_ACTION: NO_TRADE
- EXECUTION_ACTION: DATA_INVALID_NO_EXECUTION
- 建议战术仓目标：0.00%
- 当前战术仓：0.00%
- 建议变动：+0.00% 组合净值
- 战略底仓：HOLD_CORE（数据无效时不做日线调整）

## 一句话原因
关键数据源未能在超时窗口内返回，系统按规则进入 `DATA_INVALID / NO_TRADE`，不生成加仓、减仓或执行建议。

## 四模块评分
| 模块 | 得分 | 上限 | 状态 | 核心变化 |
|---|---:|---:|---|---|
| 宏观转向 | 0 | 0 | DATA_INVALID | 关键宏观或价格数据未通过 |
| 资金流确认 | 0 | 0 | UNAVAILABLE | 未进入慢变量拉取 |
| 价格结构 | 0 | 0 | DATA_INVALID | 价格数据未完成确认 |
| 风险环境 | 0 | 0 | DATA_INVALID | 风险数据未完成确认 |

## 数据质量审计
- 数据质量：FAIL
- 失败原因：No usable gold price source. xauusd: Stooq xauusd returned only 0 usable points; gc.f: Stooq gc.f returned only 0 usable points; gld.us: Stooq gld.us returned only 0 usable points
- 计划数据源：FRED official CSV endpoints；Stooq public daily CSV。
- 系统行为：不静默失败；保存本报告和机器快照；等待下次自动化或手动重跑。

## 反证与后续
- 一旦关键数据恢复，重新运行脚本并按完整状态机评分。
- 数据恢复前，不应把新闻、金价短期波动或主观判断替代量化规则。

非投资建议；不自动下单。
