# Source Log

## Processed Gmail Reports

| Report Date | Gmail ID | Subject | Sender | Email Timestamp | Status | Key Source IDs | Cumulative Impact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-12 | `19f54927a4c2277c` | TheMarketMemo Daily Report - 2026-07-12 | ZhangHawtim hawtim@icloud.com | 2026-07-12 12:24:56 Asia/Shanghai | processed | 2075450308512423967 | No new LEI activity; reinforced QQQ resilience vs Mag7 weakness and breadth-risk framework. |
| 2026-07-12 | `19f54aa0dc2f8d74` | TheMarketMemo Daily Report - 2026-07-12 (direct send test) | hawtimzhang@gmail.com | 2026-07-12 12:50:58 Asia/Shanghai | duplicate-test | 2075450308512423967 | Body matched canonical same-day report; not used as primary source. |
| 2026-07-11 | `19f548e56b703c89` | TheMarketMemo Daily Report - 2026-07-11 | ZhangHawtim hawtim@icloud.com | 2026-07-12 12:20:26 Asia/Shanghai | processed | 2075450308512423967 | Added Mag7-vs-QQQ divergence evidence and reinforced index-mechanism thinking. |
| 2026-07-10 | `19f548e55ae4b606` | TheMarketMemo Daily Report - 2026-07-10 | ZhangHawtim hawtim@icloud.com | 2026-07-12 12:20:24 Asia/Shanghai | processed | 2075068192419201291; 2075078853794668728; 2075082011014766884 | Added debt-vs-equity, inflation hedge, U.S. capital magnetism, and practical simplicity principles. |
| 2026-07-09 | `19f548e50b63f2df` | TheMarketMemo Daily Report - 2026-07-09 | ZhangHawtim hawtim@icloud.com | 2026-07-12 12:20:23 Asia/Shanghai | processed | 2074713423393530091; 2074721860432847161; 2074751053992775996; 2074898778537226517; 2072585720850698386 | Added breadth percentages, technical bear-market breadth, and NQ structural consolidation framework. |
| 2026-07-08 | `19f548e4f6bbe3a2` | TheMarketMemo Daily Report - 2026-07-08 | ZhangHawtim hawtim@icloud.com | 2026-07-12 12:20:21 Asia/Shanghai | processed | 2074349745687212536; 2074368102889058487 | Added QQQ breadth deterioration, AI-assisted holdings analysis, and index-vs-stock risk. |
| 2026-07-07 | `19f386b169b9d025` | TheMarketMemo Daily Report - 2026-07-07 | ZhangHawtim hawtim@icloud.com | 2026-07-07 01:12:33 Asia/Shanghai | missing-body | none in email body | Email only says the report was saved elsewhere; no investment content processed. |

## Canonical Report Files

- `references/daily-reports/themarketmemo-daily-report-2026-07-08.md`
- `references/daily-reports/themarketmemo-daily-report-2026-07-09.md`
- `references/daily-reports/themarketmemo-daily-report-2026-07-10.md`
- `references/daily-reports/themarketmemo-daily-report-2026-07-11.md`
- `references/daily-reports/themarketmemo-daily-report-2026-07-12.md`

## Source Handling Notes

- 2026-07-12 had both a canonical report and a same-body direct-send test. The non-test email is canonical.
- All initial daily reports were fetched from Gmail search query `"TheMarketMemo Daily Report" -in:spam -in:trash`.
- Future automation runs should skip already processed Gmail IDs unless the body content differs and the source log explains why.
