---
name: us-market-macro-regime
description: Generate a Chinese pre-market U.S. equity macro regime report for non-professional investors. Use when the user asks whether U.S. stocks are suitable to trade today, requests a daily 08:30 Asia/Shanghai U.S. macro/risk email, or needs VIX, Treasury yields, real yields, credit, breadth, retail sentiment, event risk, and saved holdings combined into one risk posture.
---

# U.S. Market Macro Regime

## Purpose

Generate an answer-first daily U.S. equity trading-environment report. Translate macro and cross-asset evidence into one of five postures: `进攻`, `偏进攻`, `中性`, `偏防守`, or `防守`.

Always load:

- `references/framework.md`
- `references/data-sources.md`

Use `portfolio.json` only when it contains actual holdings. Never invent holdings.

## Default Run

Run the deterministic collector first:

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/US-share/us-market-macro-regime/scripts/generate_daily_report.py
```

It writes:

- `reports/us-market-macro-regime-YYYY-MM-DD.md`
- `data/latest_snapshot.json`
- `data/history.jsonl`

## Workflow

1. Use `Asia/Shanghai` as the report clock. At 08:30, analyze the most recent completed U.S. session; never describe it as live pre-market data.
2. Run the collector and read the full report and machine snapshot.
3. Verify today's high-impact U.S. calendar and material overnight policy/geopolitical developments with primary sources. Add only events that could change rates, earnings expectations, valuation, or risk appetite.
4. Apply an event overlay between `-10` and `+10` directly to the 0–100 quantitative base score only when evidence is decision-relevant. State the exact reason and arithmetic. Do not silently override the base score.
5. Preserve hard-veto rules. A qualitative narrative cannot lift a hard-veto posture.
6. If `portfolio.json` contains positions, map macro channels to each holding and identify concentration, duration, beta, FX, credit, and event exposure. Otherwise retain the explicit unconfigured placeholder.
7. Replace the report's event placeholder, recompute the visible final score/posture if an overlay is used, and save the exact final email body back to the same Markdown file.
8. Email the report through Gmail to `me` with subject `美股宏观交易环境 - YYYY-MM-DD｜<姿态>`.
9. Commit only the generated report/snapshot/history and intentional files in this skill, then push to `git@github.com:hawtim/skills.git`.

## Decision Contract

- Lead with `今天是否适合交易`, then explain the three largest drivers.
- Keep `市场环境` separate from `个人持仓动作`.
- Treat signals as a risk budget, not a directional forecast or order instruction.
- Treat AAII as weekly, FINRA margin debt as monthly, and options put/call as noisy daily context. Never pretend they are equivalent frequencies.
- Treat retail/crowding extremes contrarianly only when confirmed by price, volatility, and credit.
- If critical coverage is below 70%, output `数据不足 / 以防守为主`; do not extrapolate missing values.
- Mark every value with its observation date and flag stale data.
- Never place trades.

## Output Order

1. `今日结论`
2. `普通投资者怎么做`
3. `六模块温度表`
4. `关键指标与变化`
5. `散户情绪与拥挤度`
6. `今日事件风险`
7. `个人持仓联动`
8. `反证与升级/降级条件`
9. `数据质量与来源`

## Validation

Run before shipping skill changes:

```bash
python3 scripts/generate_daily_report.py --self-test
python3 /Users/icemelon/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
