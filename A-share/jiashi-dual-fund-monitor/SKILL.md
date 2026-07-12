---
name: jiashi-dual-fund-monitor
description: Use when the user explicitly invokes "$jiashi-dual-fund-monitor", asks for the named 嘉实双基金组合监控, or a scheduled task requests its daily, weekly, or quarterly report for 000043 and 017730 A. Do not use for generic fund reviews or unrelated portfolios.
---

# Jiashi Dual Fund Monitor

## Purpose

Monitor the named two-fund portfolio, reconstruct positions from confirmed transactions, and apply its fixed rules. Keep every action evidence-linked and subject to human confirmation.

Always read `references/monitoring-rules.md`. Read `references/data-sources.md` when gathering current data. Read the matching file in `templates/` before writing a report. For scheduled runs, also read `references/scheduled-prompts.md`.

## Fixed Portfolio

| Code | Fund | Role | Initial Plan | Final Cap |
|---:|---|---|---:|---:|
| 000043 | 嘉实美国成长股票（QDII） | 美国大盘成长核心仓 | ¥150,000 | ¥200,000 |
| 017730 | 嘉实全球产业升级股票发起式（QDII）A | 全球科技与半导体增强仓 | ¥50,000 | ¥100,000 |

Use `data/operation-log.csv` as the canonical transaction source. Record only confirmed transactions supplied by the user. Use `scripts/portfolio_monitor.py` to reconstruct holdings or evaluate deterministic price bands.

## Workflow

1. Classify the request as manual review, daily report, weekly report, quarterly report, or transaction-log update.
2. Load the controlling rule reference and the relevant template.
3. Read and validate the transaction log. Never infer unreported purchases.
4. Gather dated NAV, benchmark, announcement, and market evidence. Label QDII NAV lag explicitly.
5. Run the portfolio script when holdings or action amounts are involved.
6. Apply price, fund, fundamental, and portfolio gates in that order.
7. Output one posture: `无动作`, `观察`, `加仓候选`, `暂停加仓`, `再平衡复核`, or `减仓/替换复核`.
8. State the exact rule, data time, missing evidence, and next trigger. Mark every transaction suggestion `需人工确认：是`.

## Transaction Updates

Map App or platform CSV exports into the canonical schema before appending. Validate fund code, A share class, confirmed amount, confirmed shares, confirmed NAV, fee, and duplicate IDs. Preserve the source filename or user report in `source`; do not overwrite raw exports.

## Guardrails

- Do not execute purchases, redemptions, or account actions.
- Do not treat a daily move or headline as a standalone trade signal.
- Do not recommend an add when strategy, manager, fundamentals, overlap, freshness, score, or capacity checks fail.
- Do not exceed ¥200,000 in 000043, ¥100,000 in 017730 A, or ¥300,000 combined.
- Do not present delayed NAV and overnight proxy movement as the same observation.
- If required data is missing, issue an `观察` report with no transaction amount.

Respond in Chinese unless the user asks otherwise.
