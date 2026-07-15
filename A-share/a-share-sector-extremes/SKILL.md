---
name: a-share-sector-extremes
description: Scan the currently configured A-share semiconductor, 科创50, and communications sectors for human extremes using dynamically fetched Futu index or industry constituents, 5/10/20/50/200-day equal-weight breadth, synthetic sector price structure, extreme persistence, and constituent overlap. Use when the user asks to compare or monitor these three A-share technology sectors, find whether they are washed out or crowded, or explicitly add one verified sector to the daily monitor.
---

# A股板块人性极端扫描

Run the complete current board set (半导体、科创50、通信):

```bash
python3 /Users/icemelon/Documents/invest/hawtim-skills/A-share/a-share-sector-extremes/scripts/generate_sector_report.py
```

Run a subset, or a verified Futu plate code supplied by the user:

```bash
python3 scripts/generate_sector_report.py --boards communication,coal
python3 scripts/generate_sector_report.py --plate SH.LIST0061 --name 通信设备
```

Read `references/board-definitions.json` before changing a board definition.

Rules:

1. Fetch and archive constituents on every run. Never silently use a fixed stock list.
2. Use equal-weight breadth. Do not call it index-weighted breadth.
3. Treat 5/10-day breadth as repair-speed observations. Treat 20-day ≤15% and ≥85% as alert thresholds only; require synthetic-price structure and later breadth repair before calling a bottom confirmation.
4. Keep official index, industry plate, and concept-union definitions explicit. A concept union is a monitoring basket, not an official investable index.
5. If valid 20-day coverage is below 75%, output `数据不足 / 不作极端判断` for that board.
6. Report consecutive extreme-session counts and pairwise constituent overlap. Do not treat strongly overlapping boards as independent confirmations.
7. The scan is risk monitoring, never an automatic trade instruction.
