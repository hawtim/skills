---
name: a-share-semiconductor-human-extremes
description: Generate a daily Chinese A-share semiconductor human-extremes report using industry breadth, semiconductor/chip/equipment ETF trend and volume proxies, and two-stage bottom confirmation. Use when the user asks whether A-share semiconductors are washed out, crowded, at a potential sector top or bottom, or requests an A-share semiconductor daily monitor.
---

# A股半导体人性极端

Run the deterministic collector:

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/A-share/a-share-semiconductor-human-extremes/scripts/generate_daily_report.py
```

For a marked real-time snapshot during A-share trading hours, run `--intraday`. It writes a time-stamped report and never overwrites the close-history ledger.

Always read `references/framework.md` before interpreting the output.

## Rules

1. Use the current Futu A-share “半导体” industry plate (`SH.LIST0002`) as the equal-weight breadth universe; archive it each day. Do not call it an ETF holding universe or claim weighted breadth without verified daily ETF weights.
2. Treat 20-day breadth ≤15% as `短线洗出 / 底部候选`, not a buy signal.
3. Upgrade only when the broad semiconductor ETF is back above its 5-day average and 20-day breadth is at least 5 percentage points above the prior session after a recent washout.
4. Use 512480 semiconductor ETF, 159995 chip ETF, and 159516/561980 equipment ETFs as cross-checks and turnover-based crowding proxies. Keep equipment/materials as a subindustry, not a substitute for the broad semiconductor verdict.
5. If valid-price coverage is below 75%, emit `数据不足 / 不作极端判断`.
6. Show the latest 22 completed trading sessions with 5/10/20/50/200-day breadth. Treat 5/10-day values as repair-speed observations, not independent human-extreme signals.
7. Use Tencent qfq daily bars as the primary price source. If its WAF/HTTP path is unavailable, switch the batch once to Futu OpenD daily bars, throttled below its 60 historical-K requests per 30 seconds limit.
8. Describe exclusions explicitly: fewer than 20 completed sessions is a new-listing history limit; an unavailable symbol is a source-coverage gap. Do not expose either as an opaque `RuntimeError`.
9. Never turn this monitor into an automatic order, valuation, price target, or unverified retail/institutional-sentiment claim.

## Validation

```bash
python3 scripts/generate_daily_report.py --self-test
python3 /Users/icemelon/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
