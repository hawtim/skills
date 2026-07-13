---
name: a-share-macro-regime
description: Generate a Chinese pre-open A-share macro regime report for non-professional investors. Use when the user asks whether A-shares are suitable to trade today, requests a daily 08:30 Asia/Shanghai A-share risk email, or needs domestic trend, breadth, liquidity, RMB, offshore China equities, Nasdaq Golden Dragon China Index, YINN/YANG, global risk, policy events, and saved holdings combined into one risk posture.
---

# A-Share Macro Regime

## Purpose

Generate an answer-first pre-open A-share trading-environment report. Translate domestic, offshore, FX, liquidity, and policy evidence into `进攻`, `偏进攻`, `中性`, `偏防守`, or `防守`.

Always load:

- `references/framework.md`
- `references/data-sources.md`

Use `portfolio.json` only when it contains actual holdings. Never invent holdings.

## Default Run

Run the deterministic collector first:

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/A-share/a-share-macro-regime/scripts/generate_daily_report.py
```

It writes:

- `reports/a-share-macro-regime-YYYY-MM-DD.md`
- `data/latest_snapshot.json`
- `data/history.jsonl`

## Workflow

1. Use `Asia/Shanghai` as the report clock. At 08:30, use the last completed A-share close plus the completed U.S. overnight session. Label holidays and stale sessions.
2. Run the collector and read the report and snapshot.
3. Verify same-day PBOC operations, policy releases, major official statistics, RMB fixes, and material overnight China-related developments with primary sources.
4. Apply a transparent `-10` to `+10` policy/event overlay directly to the 0–100 quantitative base score only when evidence can change liquidity, earnings, valuation, FX, or risk appetite. State the arithmetic; do not silently override the base score.
5. Preserve hard-veto rules. Qualitative optimism cannot lift a hard-veto posture.
6. Interpret Nasdaq Golden Dragon China Index, KWEB/FXI/MCHI, and YINN/YANG as offshore lead/confirmation signals. Never treat a 3x daily ETF as a multi-day fundamental index.
7. If `portfolio.json` contains positions, map the regime to each holding's style, industry, duration, policy, commodity, FX, and concentration exposure. Otherwise retain the unconfigured placeholder.
8. Replace the report's event placeholder, save the exact final email body, and send it through Gmail to `me` with subject `A股宏观交易环境 - YYYY-MM-DD｜<姿态>`.
9. Commit only the generated report/snapshot/history and intentional files in this skill, then push to `git@github.com:hawtim/skills.git`.

## Decision Contract

- Lead with whether today is better for trading or capital preservation.
- Keep `市场环境` separate from `个人持仓动作`.
- Treat the score as a risk-budget guide, not a forecast or order instruction.
- Do not use old-style real-time northbound net-flow claims. After the disclosure change, use available official historical turnover/holding data and state the limitation.
- Do not label a policy headline bullish without a transmission channel to liquidity, earnings, valuation, or risk premium.
- If critical coverage is below 70%, output `数据不足 / 以防守为主`.
- Mark every value with its observation date; show `UNAVAILABLE` and `STALE` explicitly.
- Never place trades.

## Output Order

1. `今日结论`
2. `开盘前怎么做`
3. `六模块温度表`
4. `A股内部结构`
5. `离岸中国风险温度`
6. `流动性、人民币与政策事件`
7. `个人持仓联动`
8. `反证与升级/降级条件`
9. `数据质量与来源`

## Validation

Run before shipping skill changes:

```bash
python3 scripts/generate_daily_report.py --self-test
python3 /Users/icemelon/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
