---
name: hi5-portfolio-monitor
description: Verify and monitor TheMarketMemo Hi5 ETF portfolio from its public trade sheet. Use when the user asks to audit Hi5 returns or transactions, backtest the author's buys, study the following three trading days, track a newly disclosed Hi5 buy, or generate a Chinese daily Hi5 entry-timing report for IWY, RSP, SPMO/MOAT, VNQ, and PFF.
---

# Hi5 Portfolio Monitor

Generate an evidence-bound Chinese report. Treat it as decision support, never as an order instruction.

Always read:

- `references/rulebook.md`
- `references/data-sources.md`
- `references/decision-policy.md`

## Default run

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/US-share/hi5-portfolio-monitor/scripts/generate_daily_report.py
```

The script refreshes the public Google Sheet and independent Yahoo OHLC data, then writes:

- `reports/daily/hi5-daily-YYYY-MM-DD.md`
- `reports/research/hi5-validation-latest.md`
- `data/trade-log.csv`
- `data/backtests/latest/event-study.csv`
- `data/backtests/latest/summary.json`
- `data/latest_snapshot.json`
- `data/history.jsonl`
- `data/signal_ledger.json`

## Workflow

1. Fetch the `Trades` and `Data` tabs. Preserve a source snapshot and hash before analysis.
2. Rebuild positions from Buy/Sell rows; keep gross dividends and withholding tax separate.
3. Validate each execution price against an independent unadjusted daily OHLC bar.
4. Segment the 2023 initial build, annual August rebalances, and recurring purchases. Never apply today's rule retroactively.
5. Evaluate future opportunity only over D+1 through D+3. Report 0.5%, 1%, and 2% near-low bands; do not call every miss a stage high.
6. Compare the author's price with D+1 open, D+4 open, and a preregistered staged-entry policy. Keep opportunity cost visible.
7. Preserve first-seen timestamps for new sheet rows. Historical rows imported on first run are backfill, not proof of contemporaneous publication.
8. If sources are stale or price coverage falls below 95%, output `DATA_INSUFFICIENT / 不新增风险`.

## Decision contract

- Lead with `今日许可`, latest disclosed buy, D-stage, and per-ETF action band.
- Start with a 25% observation position only after a newly disclosed buy is detected; never infer that the user already holds it.
- During D+1 to D+3, prefer prices at or below the author's execution or volatility-based limits.
- On D+4, scale the remaining purchase down when price has risen; show the exact deployed fraction and invalidation conditions.
- Separate the author's spreadsheet arithmetic, a cash-flow XIRR estimate, and unavailable TWR. Never present the author's `Total CAGR` as audited CAGR.
- Never place a trade.

## Validation

```bash
python3 scripts/generate_daily_report.py --self-test
python3 -m unittest discover -s tests -p 'test_*.py'
python3 /Users/icemelon/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
