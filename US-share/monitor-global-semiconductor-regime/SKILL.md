---
name: monitor-global-semiconductor-regime
description: Generate and maintain a Chinese daily global semiconductor regime monitor after the U.S. close. Use when the user asks for semiconductor entry readiness, stage-top or stage-bottom structure, LEI/TheMarketMemo trend confirmation, U.S.-China-Korea-Taiwan semiconductor linkage, daily semiconductor monitoring, or an automated post-close semiconductor report with signal outcome tracking and Gmail/GitHub delivery.
---

# Global Semiconductor Regime Monitor

## Purpose

Generate one evidence-bound report that answers whether the global semiconductor complex is in a downtrend, bottom watch, confirmed stage bottom, uptrend, top watch, or confirmed stage top. Treat the output as a risk-environment screen, not an order instruction.

Always load:

- `references/structure-rules.md`
- `references/universe.md`
- `references/data-sources.md`

Also load the cumulative LEI principles at `../lei-invest/references/lei-investment-principles.md` when interpreting price structure.

## Default Run

Run the deterministic collector first:

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/US-share/monitor-global-semiconductor-regime/scripts/generate_daily_report.py
```

It writes:

- `reports/global-semiconductor-regime-YYYY-MM-DD.md`
- `data/latest_snapshot.json`
- `data/history.jsonl`
- `data/signal_ledger.json`
- `data/calibration.json`

## Workflow

1. Use `Asia/Shanghai` as the report clock and the latest completed session for each market.
2. Run the collector and read the full report and machine snapshot.
3. Verify only market-moving developments: official earnings/guidance, AI capex changes, memory pricing, export controls, central-bank/inflation shocks, oil/supply-chain disruptions, and material index/ETF flows. Ignore isolated headlines that do not change price structure, estimates, breadth, or cross-market confirmation.
4. Keep source facts, LEI principles, deterministic signals, and interpretation separate.
5. Do not upgrade a bottom from one oversold day. Require a higher low and a break above the prior reaction high for a confirmed stage bottom. Mirror the rule for stage tops.
6. Preserve daily/weekly separation. Label a daily stage bottom inside a weekly downtrend as a tactical rebound, not a new primary uptrend.
7. Apply a qualitative event overlay between `-10` and `+10` only when a verified event changes rates, earnings, valuation, supply, or liquidity. Show the fact, transmission path, score, and arithmetic. Never override a hard veto silently.
8. Save the exact final email body back to the generated Markdown report.
9. Send the full report through Gmail to `me` with subject `全球半导体盘后监控 - YYYY-MM-DD｜<结构状态>`.
10. Commit only this skill's generated report, snapshot/history/ledger, and intentional skill changes. Synchronize to `hawtim/skills` without including unrelated worktree changes.

## Decision Contract

- Lead with `当前结构`, `入场准备度`, `顶部风险度`, and `今日许可`.
- Use ETF/index evidence as the regime anchor and individual leaders only as confirmation.
- Treat `入场准备度` as a readiness score, not a calibrated probability of profit.
- If critical coverage is below 70%, output `DATA_INSUFFICIENT / NO_NEW_RISK`.
- If the U.S. anchor remains `阶段顶部确认` or `下降趋势确认`, cap the action at `BOTTOM_WATCH` even when another region rebounds.
- Never place trades, claim an execution, or infer the user's holdings.

## Output Order

1. `今日结论`
2. `LEI 顶部/底部结构`
3. `中美韩台联动`
4. `核心指数与 ETF`
5. `宏观和基本面覆盖`
6. `未来 1–3 个交易日剧本`
7. `历史信号闭环`
8. `升级、降级和失效条件`
9. `数据质量与来源`

## Validation

Run before shipping skill changes:

```bash
python3 scripts/generate_daily_report.py --self-test
python3 -m unittest discover -s tests -p 'test_*.py'
python3 /Users/icemelon/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
