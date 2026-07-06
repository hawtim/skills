---
name: gold-silver-regime-monitor
description: Explicitly triggered precious-metals monitoring skill. Use when the user invokes "$gold-silver-regime-monitor", asks for a gold/silver daily regime report, or when an automation asks for the daily 14:30 precious-metals monitor. Generate a Chinese gold tactical-regime report with macro, flow, technical, risk, data-quality, Gmail delivery, and repository archival under Precious-metals/gold-silver-regime-monitor/reports.
---

# Gold Silver Regime Monitor

## Purpose

Generate the user's daily precious-metals monitor. Gold is the fully specified regime model; silver is tracked as a companion market signal until a separate silver state machine is defined.

Always load:

- `references/gold-regime-rules.md`

Prefer running the bundled script first:

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/Precious-metals/gold-silver-regime-monitor/scripts/generate_daily_report.py
```

## Default Delivery

- Default recipient: `hawtimzhang@gmail.com`
- Default subject: `黄金白银日度监控 - YYYY-MM-DD HH:mm`
- Default report directory: `Precious-metals/gold-silver-regime-monitor/reports`
- Default machine snapshot directory: `Precious-metals/gold-silver-regime-monitor/data`

## Workflow

1. Determine the run timestamp in `Asia/Shanghai`. For scheduled runs, use the 14:30 trigger time in the title and file name when available; for manual reruns, use the actual run time and note it.
2. Run `scripts/generate_daily_report.py` to collect public data, compute factors, and write:
   - `reports/gold-silver-regime-report-YYYY-MM-DD-HHmm.md`
   - `data/gold_snapshot.json`
   - `data/gold_history.jsonl`
3. Read the generated Markdown report before sending. If the report says `DATA_INVALID`, do not convert it into a trade suggestion.
4. Send the completed Markdown report through Gmail to `hawtimzhang@gmail.com`. Prefer passing the report body inline. If `body_file` upload fails, retry with inline Markdown before falling back to a draft. If sending fails, create a Gmail draft to the same recipient and state the failure reason.
5. Commit only the generated report, snapshot/history files, and intentional skill changes, then push to `git@github.com:hawtim/skills.git`.

## Data Rules

- Critical modules are gold price, 10Y real yield, and broad USD. If any critical module is missing or stale beyond the allowed window, output `DATA_INVALID / NO_TRADE`.
- FRED data must come from FRED CSV/API endpoints, not scraped pages.
- Public price data may use spot, futures, or ETF proxies, but the report must label the chosen source. Do not mix symbols inside the same moving-average calculation.
- GLD holdings, COT, and World Gold Council ETF flow can be `UNAVAILABLE` in the MVP. Missing flow factors must shrink the active score denominator; never treat missing flow as zero confirmation.
- Separate `MACRO_ACTION` from `EXECUTION_ACTION`. A favorable gold regime does not automatically mean a domestic ETF or leveraged product is suitable to buy.

## Output Requirements

The report must be answer-first and in Chinese:

1. **结论**: regime, score, tactical target, proposed change, core posture.
2. **一句话原因**: largest drivers of the daily state.
3. **四模块评分**: macro, flow, technical, risk, status, and changes.
4. **关键数据**: latest value and 5D/10D/20D changes for gold, real yield, USD, 2Y, breakeven, VIX, HY OAS, plus silver companion trend.
5. **触发器**: add/reduce/hard-veto/overheat status and missing confirmations.
6. **数据质量审计**: source dates, staleness, unavailable modules, and conflict notes.
7. **反证条件**: what would invalidate the conclusion.

## Boundaries

- Do not place trades or imply trades were executed.
- Do not use geopolitical or central-bank-buying narratives as standalone action reasons.
- Do not overwrite the state machine with market commentary.
- Do not hide unavailable data; mark it as `UNAVAILABLE`, `STALE`, or `DATA_INVALID`.
