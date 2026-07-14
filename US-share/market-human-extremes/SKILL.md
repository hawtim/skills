---
name: market-human-extremes
description: Monitor U.S. equity market human extremes by combining AAII retail sentiment, NAAIM active-manager equity exposure, SPY/QQQ/IWM price structure, market breadth, and VIX. Use when the user asks whether U.S. equities are near a sentiment-driven top or bottom, requests a daily human-nature/extreme-positioning check, or wants a disciplined market-risk report rather than a directional prediction.
---

# Market Human Extremes

Generate a daily, evidence-first U.S. equity “人性之极” monitor. Treat surveys as crowd-positioning evidence, not forecasts: an extreme matters only when price, volatility, and breadth confirm it.

## Default run

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/US-share/market-human-extremes/scripts/generate_daily_report.py
```

It writes:

- `reports/market-human-extremes-YYYY-MM-DD.md`
- `data/latest_snapshot.json`
- `data/history.jsonl`

Read both references before interpretation:

- `references/framework.md`
- `references/data-sources.md`

## Workflow

1. Use `Asia/Shanghai` as report date and the most recently completed U.S. session; never present intraday data as a confirmed signal.
2. Run the collector. On failure, retry once. If it still fails, share only the fail-closed report; never recycle an old extreme signal.
3. Verify AAII, NAAIM, SPY, QQQ, IWM, VIX, and all nine TradingView breadth readings before calling an extreme. Render breadth as a temperature gauge rather than a raw list of numbers.
4. Apply all five layers in the framework: retail mood, active-manager exposure, price structure, breadth, and volatility. Keep disagreement as `信号分歧`.
5. Lead with the state and risk discipline. Suggest risk-budget actions such as avoid chasing, rebalance, or wait for confirmation; never issue an order, target price, or position size.

## Non-negotiable rules

- AAII and NAAIM are weekly. Repeat only fresh observations on a daily report and always show their dates.
- The TradingView layout uses `INDEX:S5TH/S5FI/S5TW`, `INDEX:NDTH/NDFI/NDTW`, and `INDEX:R2TH/R2FI/R2TW`. They respectively measure the percentage of S&P 500, Nasdaq-100, and Russell 2000 constituents above their 200/50/20-day averages. Treat them as breadth confirmation, not a stand-alone trading system.
- A `顶部` state is a risk-control alert, not a short signal. A `底部` state is a watch state, not a catch-the-falling-knife instruction.
- If AAII, NAAIM, price, VIX, or any required breadth reading is stale/unavailable, output `数据不足 / 不作极端判断`.
- Do not place trades or imply certainty.

## Output order

1. `今日结论`
2. `五层证据`
3. `宽度温度计`
4. `普通投资者的纪律`
5. `状态升级 / 失效条件`
6. `数据质量与来源`

## Validation

```bash
python3 scripts/generate_daily_report.py --self-test
python3 /Users/icemelon/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
