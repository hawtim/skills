---
name: lei-invest
description: Maintain and apply LEI/TheMarketMemo U.S. equity investing principles from recurring TheMarketMemo Daily Report emails. Use when the user invokes "$lei-invest", asks to update LEI's investment philosophy from Gmail daily reports, wants evidence-backed summaries of LEI's fragmented market thinking, or needs U.S. stock/ETF analysis grounded in the accumulated LEI reference library under US-share/lei-invest.
---

# LEI Invest

## Purpose

Maintain an evidence-backed investment philosophy library for LEI (@TheMarketMemo) from daily Gmail reports, then use that library when analyzing U.S. equities, QQQ/TQQQ, market breadth, momentum, and portfolio process.

Always load:

- `references/lei-investment-principles.md`
- `references/source-log.md`

Load `references/daily-report-update-playbook.md` when updating from a new daily report or automation run.

## Core Workflow

1. Search Gmail for `"TheMarketMemo Daily Report" -in:spam -in:trash`.
2. Select the newest non-test daily report. Treat subjects containing `direct send test`, `test`, or duplicate same-day content as fallback candidates only.
3. Read the selected email body and extract:
   - new or reinforced investment principles
   - concrete market judgments
   - ticker, ETF, index, and asset-class stances
   - quoted source claims and original post IDs
   - contradictions, caveats, or changes from prior principles
4. Save the report under `references/daily-reports/themarketmemo-daily-report-YYYY-MM-DD.md`.
5. Update `references/source-log.md` with the email ID, subject, sender, timestamp, report date, original post IDs, and whether it changed the cumulative view.
6. Update `references/lei-investment-principles.md` by merging the new evidence into existing principles instead of appending disconnected notes.
7. Commit and push only the new/updated `US-share/lei-invest` files and intentional `US-share/README.md` updates to `git@github.com:hawtim/skills.git`.

## Using The Principles

- Treat source facts, LEI's stated views, and Codex/user inference as separate layers.
- Prefer the cumulative principle library over a single daily report when answering strategic questions.
- Cite `source-log.md` and the relevant daily report files when explaining why a principle exists.
- When applying the framework to a current market question, verify current market data separately. This skill preserves LEI's philosophy; it is not a live data feed.

## Quality Rules

- Do not invent post IDs, tickers, market data, or author intent.
- Preserve uncertainty when a daily report says there was no new activity.
- If a report repeats an old idea without new evidence, update the source log and only add a brief reinforcement note.
- If a new report conflicts with the existing library, add a `Revision Watch` note rather than silently replacing the old principle.
- Keep the library concise enough to load quickly, but make every major principle traceable to at least one dated source.

## Output Style

When summarizing this skill for the user, write in Chinese by default. Keep recommendations evidence-bound and include a non-investment-advice note for actionable investment outputs.
