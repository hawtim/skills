---
name: lei-invest
description: Maintain and apply LEI/TheMarketMemo U.S. equity investing principles from recurring TheMarketMemo Daily Report emails and local Obsidian notes. Use when the user invokes "$lei-invest", asks to update LEI's investment philosophy from Gmail daily reports or Obsidian notes, wants evidence-backed summaries of LEI's fragmented market thinking, or needs U.S. stock/ETF analysis grounded in the accumulated LEI reference library under US-share/lei-invest.
---

# LEI Invest

## Purpose

Maintain an evidence-backed investment philosophy library for LEI (@TheMarketMemo) from daily Gmail reports and local Obsidian notes, then use that library when analyzing U.S. equities, QQQ/TQQQ, market breadth, momentum, and portfolio process.

Always load:

- `references/lei-investment-principles.md`
- `references/source-log.md`
- `references/obsidian-source-log.md`

Load `references/daily-report-update-playbook.md` when updating from a new daily report, Obsidian note, or automation run.

## Core Workflow

1. Search Gmail for `"TheMarketMemo Daily Report" -in:spam -in:trash`.
2. Scan the local Obsidian vault at `/Users/icemelon/Documents/obsidian` for new or modified Markdown notes matching `LEI`, `TheMarketMemo`, `The Market Memo`, `marketmemo`, or `@TheMarketMemo`.
3. Select the newest non-test daily report. Treat subjects containing `direct send test`, `test`, or duplicate same-day content as fallback candidates only.
4. Read every selected source and extract:
   - new or reinforced investment principles
   - concrete market judgments
   - ticker, ETF, index, and asset-class stances
   - quoted source claims and original post IDs
   - contradictions, caveats, or changes from prior principles
5. Save Gmail reports under `references/daily-reports/themarketmemo-daily-report-YYYY-MM-DD.md`.
6. Save Obsidian note extracts under `references/obsidian-notes/YYYY-MM-DD-slug.md`.
7. Update `references/source-log.md` for Gmail sources and `references/obsidian-source-log.md` for Obsidian sources.
8. Update `references/lei-investment-principles.md` in Chinese by merging new evidence into existing principles instead of appending disconnected notes.
9. Commit and synchronize only the new/updated `US-share/lei-invest` files and intentional `US-share/README.md` updates.

## Using The Principles

- Treat source facts, LEI's stated views, and Codex/user inference as separate layers.
- Prefer the cumulative principle library over a single daily report when answering strategic questions.
- Cite `source-log.md` and the relevant daily report files when explaining why a principle exists.
- When applying the framework to a current market question, verify current market data separately. This skill preserves LEI's philosophy; it is not a live data feed.

## Quality Rules

- Do not invent post IDs, tickers, market data, or author intent.
- Preserve uncertainty when a daily report says there was no new activity.
- Preserve local Obsidian note paths and source URLs exactly when available.
- If a report repeats an old idea without new evidence, update the source log and only add a brief reinforcement note.
- If a new report conflicts with the existing library, add a `Revision Watch` note rather than silently replacing the old principle.
- Keep the library concise enough to load quickly, write the cumulative principle library in Chinese, and make every major principle traceable to at least one dated source.

## Output Style

When summarizing this skill for the user, write in Chinese by default. Keep recommendations evidence-bound and include a non-investment-advice note for actionable investment outputs.
