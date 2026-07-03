---
name: etf-theme-daily-report
description: Explicitly triggered daily report skill for the user's A-share technology ETF theme account. Use only when the user invokes "$etf-theme-daily-report", says "生成ETF主题日报", "ETF主题日报", or when an explicit scheduled task asks for this named daily report. Produce a daily macro, sector, news, overheating, risk, and plan-action review for 159530, 159994, 515260, 159516, and 159538. Do not use for ordinary portfolio reviews unless explicitly invoked.
---

# ETF Theme Daily Report

## Purpose

Generate a daily Chinese report for the user's A-share technology ETF theme account. The report should connect market context to the execution plan without becoming an automatic trading instruction.

Always load:

- `references/daily-report-playbook.md`
- `references/daily-report-prompt.md`

If the user asks whether to buy, add, rebalance, or use margin, also apply the sibling execution-plan skill rules from `../etf-theme-execution-plan/references/execution-plan.md` when available.

## Covered ETFs

| Code | Name | Target Weight |
|---:|---|---:|
| 159530 | 机器人ETF易方达 | 30% |
| 159994 | 通信ETF银华 | 25% |
| 515260 | 电子ETF华宝 | 20% |
| 159516 | 半导体设备材料ETF国泰 | 15% |
| 159538 | 信创ETF富国 | 10% |

## Required Inputs

Use live/current data when the report date is today or recent. If live data is unavailable, state the limitation and use the latest available data supplied by the user or existing backtest files.

Minimum useful inputs:

- Report date.
- Current holdings, if any.
- Current cash, principal cap, and margin usage, if any.
- Latest close or intraday prices for the 5 ETFs.
- Relevant market/news context.

## Report Workflow

1. Determine report date and data freshness.
2. Gather or use supplied data for:
   - Major A-share indices and ChiNext/STAR/technology sentiment.
   - Semiconductor, semiconductor equipment/materials, electronics, communications, AI hardware, robotics, and Xinchuang/security-software themes.
   - The 5 ETF prices, daily change, short-term trend, and recent drawdown.
   - Major policy, macro, liquidity, rates, FX, overseas tech, export-control, earnings, and industry news.
3. Classify the day:
   - `risk-on`, `neutral`, `risk-off`, `panic`, or `overheated`.
4. Check whether the execution plan is touched:
   - Principal add/DCA opportunity.
   - Rebalance band breach.
   - Margin dip-buying threshold.
   - Margin exit condition.
   - No-action day.
5. Produce an answer-first daily report in Chinese.

## Output Structure

Use this structure unless the user asks for a different format:

1. **一句话结论**: action posture for the account.
2. **市场温度**: macro, liquidity, A-share sentiment, risk appetite.
3. **板块复盘**: semiconductor/equipment, electronics, communication/AI hardware, robotics, Xinchuang.
4. **重大利好/利空**: only material items, with source/date where possible.
5. **ETF 状态表**: latest price/change, trend, drawdown, target/current weight if holdings are known.
6. **过热/恐慌判断**: whether the theme is crowded, overheated, washed out, or merely correcting.
7. **计划规则检查**: whether any add, rebalance, margin, or pause rule is triggered.
8. **明日观察清单**: concrete levels, signals, and news to watch.
9. **风险提示**: data gaps and what would change the conclusion.

## Style

Be strict about separating market color from executable action. Do not recommend margin merely because a sector fell sharply; margin requires the execution-plan drawdown rule. If evidence is incomplete, label the report as provisional.
