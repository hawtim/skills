# Scoring and retention rules

## Hard guards

Assign `protected` and do not score for deletion when any condition applies:

- Content matches the permanent Hegre whitelist.
- Any linked torrent completed in the last 60 days.
- Any linked torrent has less than 60 days of seeding time.
- Any linked torrent has not met a user-provided tracker rule, share-ratio target, hit-and-run requirement, or retention period.
- An external rating match is ambiguous or unavailable for a media type that requires separate research.

Use the newest `completion_on` and the shortest linked `seeding_time`. The first eligible date is the later of the relevant 60-day dates. A user may explicitly replace the 60-day defaults.

## Effective PT value

Do not count a tracker merely because it reports an accepted announce. Count only sites the user identifies as active and useful. Multiple effective sites sharing a content path raise retention value but do not multiply disk cost.

## Score (0-100)

- External content score: 0-60. Use the current normalized external rating, source, vote volume when available, and match confidence. This is the dominant factor.
- Effective PT value: 0-15. Consider active useful sites, current demand, required retention, and bonus generation.
- Scarcity and version quality: 0-15. Reward few available seeders, difficult reacquisition, original discs, remuxes, special audio/subtitles, and complete collections.
- Storage efficiency: -10 to +10. Penalize very large, low-rated, single-site, easy-to-reacquire content; reward cross-seeded content paths and compact high-value resources.

## Decision bands

- 75-100: retain.
- 55-74: retain or review based on available space and personal preference.
- Below 55: deletion candidate only after all hard guards pass.

Always label the evidence source and confidence. Never downgrade a group because a search result was a same-name work, soundtrack, book, or otherwise mismatched result.
