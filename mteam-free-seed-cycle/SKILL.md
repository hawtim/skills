---
name: mteam-free-seed-cycle
description: Safely discover, score, and run a single M-Team FREE torrent cycle through the official API and local qBittorrent, then verify live peer demand and upload potential. Use when a user wants to build upload through legitimate FREE downloads, inspect current FREE candidates, or automate a bounded M-Team new-user seed workflow.
---

# M-Team FREE Seed Cycle

Use the official API with an API Access Token and qBittorrent's local Web API. Treat all tracker credentials, tokens, torrent files, and passkeys as secrets.

## Workflow

1. Check the current official M-Team account, API, client, and promotion rules. Do not rely on remembered thresholds; new-user requirements and discounts can change.
2. Query the newest page once. Keep only visible, normal, `FREE` candidates that fit the user's disk budget and remaining FREE window.
3. Rank candidates by freshness, incomplete peers, size, and seeder competition. Prefer new releases with active leechers, but do not infer live demand from tracker-list counts alone.
4. Inspect qBittorrent before writing: require free disk space greater than the torrent size plus 30%, and require active-download count below the chosen ceiling.
5. Preview first. Add at most one torrent only after explicit user authorization. Never use `skip_checking` for a new download; it is for verified cross-seed content only.
6. Immediately query qBittorrent again. Confirm that the task is downloading, the tracker is working, and it has real incomplete peers. Record initial upload/download counters.
7. After completion, retain the torrent for the user-approved period and observe upload for 30-60 minutes before judging the candidate. Do not pause, delete, move, or modify existing torrents unless separately requested.

## Candidate rules

Use a short polling cadence (about 3-5 minutes) and stay within M-Team's published API limits. Score candidates in this order:

- Current `FREE` status and enough time to finish.
- Very recent publish time, ideally within 20 minutes.
- Meaningful leecher count relative to seeders.
- Moderate size that can finish in time and still yield worthwhile uploads.
- Availability of local slots and disk space.

Reject a candidate if it is not explicitly `FREE`, is banned/invisible, exceeds the one-shot size limit, has no safe FREE window, or would exhaust disk/concurrency budgets. Do not use anomalous traffic, unauthorized clients, fake reporting, or passkey sharing.

## Helper

Run [scripts/mteam_free_cycle.py](scripts/mteam_free_cycle.py) with an external JSON config. It never writes credentials to the skill folder.

```powershell
python scripts/mteam_free_cycle.py preview --config C:\secure\mteam.json
python scripts/mteam_free_cycle.py add --config C:\secure\mteam.json --id 123456 --confirm
python scripts/mteam_free_cycle.py status --config C:\secure\mteam.json --hash <info-hash>
```

Read [references/config.md](references/config.md) before the first run. `preview` and `status` are read-only. `add` adds only the selected torrent and refuses to use `skip_checking`.

## Interpreting results

Use server-side seed/leech counts only for coarse filtering. The useful post-add signal is qBittorrent's connected peers with `progress < 1` plus observed `upspeed`. A torrent with a large list count but no locally connected incomplete peers is a weak upload candidate.
