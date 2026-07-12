# Daily Report And Obsidian Update Playbook

## Source Discovery

Use two source families on every automation run:

- Gmail daily reports.
- Local Obsidian Markdown notes from `/Users/icemelon/Documents/obsidian`.

The iCloud Obsidian folder `/Users/icemelon/Library/Mobile Documents/iCloud~md~obsidian/Documents` may exist, but use it only if it contains matching notes. The local Documents vault is the default because it currently contains the LEI wiki and inbox notes.

## Gmail Selection

- Query: `"TheMarketMemo Daily Report" -in:spam -in:trash`
- Prefer the newest email whose subject matches `TheMarketMemo Daily Report - YYYY-MM-DD` and does not contain `test`.
- If multiple same-date reports exist, compare bodies. Use the non-test sender copy as canonical when bodies match.
- If the newest report has no body content, log it as `missing-body` and search the next newest candidate.

## Obsidian Selection

Scan Markdown files using these case-insensitive terms:

- `LEI`
- `TheMarketMemo`
- `The Market Memo`
- `marketmemo`
- `@TheMarketMemo`

Treat a note as a candidate when either its path or content matches. Ignore `.obsidian/`, `.git/`, attachments, binary files, and non-Markdown files.

Use `references/obsidian-source-log.md` to decide whether a note is new or modified:

- Key by vault-relative path plus source URL when available.
- Record file modified time, size, content SHA/checksum, and processed status.
- If a matching note path is absent from the log, process it.
- If the path exists but modified time, size, or checksum changed, process it as `modified`.
- If the path exists and checksum is unchanged, skip it.

On the first Obsidian-enabled run, process existing unlogged matching notes in manageable batches instead of forcing everything into one run. Prefer 10-20 notes per run, prioritizing `Wiki/Sources`, `Wiki/Authors/LEI.md`, `Wiki/Methods/*LEI*`, `Wiki/Principles`, then `Inbox`.

## Extraction Schema

For each Gmail report, extract:

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

For each Obsidian note, extract:

- `vault_path`
- `relative_path`
- `file_modified_time`
- `content_sha`
- `frontmatter_title`
- `source_url`
- `author_or_handle`
- `note_type` such as source, author profile, method, principle, observation, inbox capture, or weekly report
- `principles_added`
- `principles_reinforced`
- `ticker_and_asset_stances`
- `risk_or_invalidation_signals`
- `source_quotes_or_evidence`
- `links_to_related_obsidian_notes`

## Merge Rules

- Update `lei-investment-principles.md` in Chinese, by theme, not by day.
- Add a new bullet only when the report contributes a distinct concept, evidence point, or caveat.
- For repeated ideas, append the report date to the principle's evidence list.
- Preserve contradictions under `Revision Watch`.
- Keep `source-log.md` append-only except for fixing factual metadata mistakes.
- Preserve source metadata exactly, but write principle names, synthesis, practical-use notes, and revision notes in Chinese.
- Keep `obsidian-source-log.md` append-only except for correcting path/checksum metadata.
- Save Obsidian note extracts under `references/obsidian-notes/YYYY-MM-DD-slug.md`; if the note has no reliable date, use the file modified date.
- Do not copy large Obsidian notes wholesale unless the source itself is short. Prefer a compact extract with source path, source URL, key quotes, extracted views, and what changed in the principle library.
- If an Obsidian note is a processed wiki page that already summarizes an Inbox source, prefer the wiki source page as the primary reference and log the raw Inbox note as related evidence only when needed.

## Automation Memory

Automation runs should maintain `/Users/icemelon/.codex/automations/lei/memory.md` with:

- last processed Gmail message ID
- last processed report date
- last processed Obsidian candidate count
- Obsidian notes processed, skipped, or queued
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
5. Synchronize GitHub through GitHub Connect / GitHub connector. Do not rely on SSH push because this project has previously failed on SSH authentication/port access.
