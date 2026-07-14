# 数据来源与新鲜度

| 数据 | 来源 | 频率 | 最大允许滞后 |
|---|---|---:|---:|
| AAII 看多/中性/看空 | AAII Sentiment Survey Past Results | 周 | 10 天 |
| NAAIM Exposure Index | NAAIM Exposure Index | 周 | 10 天 |
| SPY / QQQ / IWM / VIX | Yahoo Finance chart JSON | 日 | 3 天 |
| 宽度 | TradingView `INDEX:*` 图表 | 日 | 3 天 |

- AAII 衡量个人投资者未来六个月预期，必须披露三项比例和调查日期。
- NAAIM 是成员报告的美国权益平均曝险，可为负或超过 100；NAAIM 本身说明它不是预测工具。
- 自动任务从 TradingView 的公开 `INDEX:*` 报价流读取九项宽度；若任一读数不能取得或超过新鲜度窗口，就显示 `数据不足 / 不作极端判断`，而不使用图像识别或旧缓存替代。
- 周末与假期可重复使用未过期观测，必须显示原始观测日期。
