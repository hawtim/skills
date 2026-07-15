---
name: star50-human-extremes
description: Monitor STAR 50 / 科创50 human extremes using current index constituents, 5/10/20/50/200-day equal-weight breadth, STAR 50 price structure, and a two-stage washout confirmation. Use when the user asks whether A-share technology or 科创50 is crowded, washed out, near a technology-sector top or bottom, or requests a daily 科创50 monitor.
---

# 科创50人性极端

Run:

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/A-share/star50-human-extremes/scripts/generate_daily_report.py
```

Always read `references/framework.md` before interpretation.

Rules:

1. Use Futu index constituents for `SH.000688`; archive the daily universe. Never substitute a static list.
2. Treat 5/10-day breadth as repair-speed observations. Use 20-day breadth ≤15% plus index stress as a washout candidate; require price back above its 5-day average and 20-day breadth +5pct day-over-day for confirmation.
3. Use equal-weight breadth only. Do not claim official index-weight breadth without verified daily constituent weights.
4. If valid 20-day price coverage is below 75%, output `数据不足 / 不作极端判断`.
5. This is risk monitoring, not a trading instruction.
