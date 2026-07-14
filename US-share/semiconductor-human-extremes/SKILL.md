---
name: semiconductor-human-extremes
description: Monitor potential sentiment-driven extremes in U.S. semiconductors through SOXX constituent breadth, leadership concentration, SOXX/SMH trend, and SOXL leverage appetite. Use when the user asks whether the semiconductor sector is crowded, broadly healthy, near a sector top or washout bottom, or requests a daily semiconductor human-extremes report.
---

# Semiconductor Human Extremes

Generate a daily sector monitor. It measures how broadly semiconductor stocks participate, whether leadership is concentrated, and whether leveraged-sector appetite confirms the move. It is a risk-monitoring framework, not a buy, sell, or short system.

## Default run

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/US-share/semiconductor-human-extremes/scripts/generate_daily_report.py
```

It saves the report, latest snapshot, historical snapshots, and a dated SOXX constituent/weight snapshot under `data/`.

Always read:

- `references/framework.md`
- `references/data-sources.md`

## Workflow

1. Run the collector and retry once only if it fails.
2. Verify that at least 75% of SOXX constituent weight has valid 200-day price history and that SOXX, SMH, SOXL and SOXS are fresh.
3. Lead with the state, then show the 20/50/200-day breadth-position bars (current reading, stock count, and fixed extreme lines), cap-weight breadth, top-five versus remainder breadth, SOXX/SMH/SOX trend, and the SOXL/SOXX proxy.
4. Interpret strong price plus low volatility as normal unless breadth saturation/concentration and leverage appetite also point to crowding.
5. If coverage is insufficient, output `数据不足 / 不作极端判断`; never substitute an old constituent list or quote.

## Rules

- Use the current SOXX holdings only for daily monitoring and archive each daily universe snapshot. Do not use current holdings alone for historical backtests.
- Label SOXL/SOXX as a leveraged-risk-appetite proxy, not a direct survey or a causal signal.
- Treat TradingView `NASDAQ:SOX` (Philadelphia Semiconductor Index) as a sector price-trend cross-check, not as a substitute for constituent breadth.
- Treat a bottom state as an observation point until SOXX regains its 5-day average. Treat a top state as a risk-control alert, not a short signal.
- Keep general U.S. market sentiment (AAII/NAAIM) in the broad-market monitor; do not claim it is semiconductor-specific.
- Never place trades, give price targets, or invent unavailable holdings/quotes.

## Validation

```bash
python3 scripts/generate_daily_report.py --self-test
python3 /Users/icemelon/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
