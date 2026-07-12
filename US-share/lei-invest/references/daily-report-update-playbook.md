# Daily Report Update Playbook

## Gmail Selection

- Query: `"TheMarketMemo Daily Report" -in:spam -in:trash`
- Prefer the newest email whose subject matches `TheMarketMemo Daily Report - YYYY-MM-DD` and does not contain `test`.
- If multiple same-date reports exist, compare bodies. Use the non-test sender copy as canonical when bodies match.
- If the newest report has no body content, log it as `missing-body` and search the next newest candidate.

## Extraction Schema

For each report, extract:

- `report_date`
- `email_id`
- `email_subject`
- `email_timestamp`
- `activity_window`
- `original_post_ids`
- `new_posts_or_replies`
- `principles_added`
- `principles_reinforced`
- `ticker_and_asset_stances`
- `risk_or_invalidation_signals`
- `quotes_or_source_claims`
- `notes_for_next_update`

## Merge Rules

- Update `lei-investment-principles.md` by theme, not by day.
- Add a new bullet only when the report contributes a distinct concept, evidence point, or caveat.
- For repeated ideas, append the report date to the principle's evidence list.
- Preserve contradictions under `Revision Watch`.
- Keep `source-log.md` append-only except for fixing factual metadata mistakes.

## Automation Memory

Automation runs should maintain `/Users/icemelon/.codex/automations/lei/memory.md` with:

- last processed Gmail message ID
- last processed report date
- files changed
- commit SHA and push status
- skipped or duplicate reason
- next action

## Commit Scope

Before committing:

1. Check repository status.
2. Stage only:
   - `US-share/lei-invest/**`
   - `US-share/README.md` when adding or updating the skill list
3. Do not stage unrelated local changes.
4. Commit message format: `Update LEI invest daily principles YYYY-MM-DD`
5. Push to `origin HEAD`.
