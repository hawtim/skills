# 定时任务提示词

三个任务均使用 `/Users/icemelon/Documents/invest/hawtim-skills/A-share/jiashi-dual-fund-monitor`，各自维护独立 automation memory。先在本地写报告，再通过 GitHub Connect 同步到 `hawtim/skills`；不得以 `git push` 作为回退。只同步本次报告及确有必要更新的本 skill 文件，不纳入其他工作区改动。

## 每日任务

```text
使用 $jiashi-dual-fund-monitor 生成嘉实双基金每日监控报告。

固定标的：000043 嘉实美国成长股票（QDII）；017730 嘉实全球产业升级股票发起式（QDII）A。
运行时间：每个工作日 08:30 Asia/Shanghai。

读取 skill 的 monitoring-rules.md、data-sources.md、daily-report.md 和 data/operation-log.csv。获取最新已公布基金净值、净值日期、正式公告、基金经理信息、IWF 及隔夜美国大型科技/半导体/全球科技代理。明确区分 QDII 最新净值与隔夜市场窗口。

如交易日志为空，按待建仓处理，不虚构持仓。运行 scripts/portfolio_monitor.py 重建组合并检查容量和价格档位。只有价格、基金、基本面、重合度、数据时效和额度检查同时通过，才输出加仓候选；所有动作必须写“需人工确认：是”。

将完整 Markdown 保存到 reports/daily/jiashi-dual-fund-daily-YYYY-MM-DD.md。同名文件存在时使用实际运行时间或 -rerunN 后缀，并说明补跑原因。周末或明确非交易日跳过正常日报；关键数据不足时生成观察简报且金额为 0。

通过 GitHub Connect 将本次报告同步到 hawtim/skills 默认分支，commit message 为 “Add Jiashi dual fund daily report YYYY-MM-DD”。记录远端 commit SHA；同步失败时保留本地报告并记录失败原因，不运行 git push。
```

## 每周任务

```text
使用 $jiashi-dual-fund-monitor 生成嘉实双基金每周监控报告。

运行时间：每周六 10:00 Asia/Shanghai。读取完整交易日志、monitoring-rules.md、data-sources.md 和 weekly-report.md。计算本周组合收益、最大回撤、相对基准、两基金相对强弱、权重与剩余额度；更新 ADD-OBSERVE、ADD-FIRST、ADD-SECOND 和 PORT-WEIGHT 的下一触发点。检查本周公告、经理、规模、策略一致性和重合风险。

保存到 reports/weekly/jiashi-dual-fund-weekly-YYYY-MM-DD.md。所有建议需给规则 ID、失效条件和“需人工确认：是”。

通过 GitHub Connect 同步本次报告，commit message 为 “Add Jiashi dual fund weekly report YYYY-MM-DD”。记录远端 commit SHA；失败时保留本地报告并记录原因，不运行 git push。
```

## 季度披露任务

```text
使用 $jiashi-dual-fund-monitor 检查 000043 与 017730 A 是否发布了尚未处理的新季度、半年度或年度正式报告。

该任务每周检查一次。开始时读取独立 automation memory 和 reports/quarterly 目录；以基金代码、报告期和正式披露日期去重。若没有新报告期，记录 skip，不创建空报告，不提交 GitHub。

发现新披露后，读取 monitoring-rules.md、data-sources.md 和 quarterly-report.md，比较上一完整披露期：前十大持仓、新进退出、行业、国家/市场、股票仓位、规模、换手率、经理观点、相对基准、两基金重合度和风格漂移。分别更新产品评分，重点判断 000043 是否保持美国大盘成长增强定位，以及 017730 A 是否保持跨市场、跨子行业轮动。

保存到 reports/quarterly/jiashi-dual-fund-quarterly-YYYY-QN.md；半年度或年度披露在标题中注明。所有建议需写“需人工确认：是”。

通过 GitHub Connect 同步本次报告，commit message 为 “Add Jiashi dual fund quarterly report YYYY-QN”。记录远端 commit SHA；失败时保留本地报告并记录原因，不运行 git push。
```
