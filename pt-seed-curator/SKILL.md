---
name: pt-seed-curator
description: Score and safely curate a local qBittorrent private-tracker library. Use when reviewing seed retention, identifying low-value resources, checking redundant storage, planning moves off SSDs, or preparing recurring seed-library reports. Never use this skill to remove, pause, or modify torrents unless the user explicitly requests that action after reviewing candidates.
---

# PT Seed Curator

Inspect qBittorrent through its local Web API in read-only mode, then score physical content paths rather than individual tracker entries. Report safe retention and deletion candidates without changing torrent state.

## Workflow

1. Verify the local qBittorrent API and collect torrent state, properties, trackers, files, completion dates, and content paths.
2. Group tasks by normalized `content_path`. Count only one physical copy for disk usage; retain the list of all associated tracker tasks.
3. Apply the hard guards in `references/scoring.md`. A protected group is never a deletion candidate.
4. For unprotected groups, obtain a current external content rating. Prefer Douban for film and TV; use an appropriate well-known source for games, books, courses, and music. Record source, score, and match confidence. Do not treat an uncertain title match as a low score.
5. Score content value first, then adjust for effective PT value, scarcity, version quality, and storage cost. Treat a tracker as effective only when the user confirms the associated site still has meaningful utility.
6. Report groups as `keep`, `review later`, or `deletion candidate`. Include: external rating, score, physical size, all tracker tasks, earliest eligible review date, and reason.

## Safety rules

- Keep all Hegre resources on the permanent whitelist unless the user explicitly removes that preference.
- Do not nominate a group until every associated task has passed the completion and seeding guard.
- Use the newest completion date and shortest seeding duration among associated tasks.
- Do not infer that multiple tracker tasks consume multiple copies of disk space.
- Do not call pause, delete, recheck, move, category, tag, or tracker-mutating endpoints during an audit.
- Before any requested deletion, show exact hashes, paths, tracker tasks, space that would really be released, and the recovery consequence. Require explicit confirmation.
- When deletion is confirmed, remove both the qBittorrent tasks and their data. After qBittorrent reports success, verify every confirmed content path is absent and compare disk free space. If any path remains, identify the exact residual path and, under the same explicit confirmation, remove it or report the technical block. Do not report reclaimed space until filesystem verification succeeds.

## Recurring reports

For a scheduled audit, repeat the read-only workflow. Email only new or changed deletion candidates; if there are none, send a concise all-clear. The report must state that no automatic deletion occurred.

Read [references/scoring.md](references/scoring.md) before assigning scores.
