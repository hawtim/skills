---
name: weekly-momentum-report
description: Explicitly triggered weekly U.S. equity momentum report skill for TheMarketMemo Patreon weekly momentum posts. Use when the user invokes "$weekly-momentum-report", asks for the weekly momentum analysis email, or an automation asks for this named weekly report. Generate a concise Chinese action-focused report with ETF/index/sector takeaways, complete first-class and second-class stock lists, Gmail delivery, and repository archival under US-share/weekly-momentum-report/reports.
---

# Weekly Momentum Report

## Purpose

Generate the user's weekly U.S. market momentum report from TheMarketMemo's Patreon weekly momentum post, email it through Gmail, and archive the completed Markdown report in this skills repository.

Always load:

- `references/report-playbook.md`

## Default Inputs

- Weekly Patreon collection: `https://www.patreon.com/collection/2080847?view=expanded`
- Momentum indicator explanation: `https://www.patreon.com/TheMarketMemo/posts/quan-shi-chang-159083909`
- Full Market Momentum Dashboard: `https://docs.google.com/spreadsheets/d/1_xv9pPrxhx9A4OyhrvyTTJuKNXk8rn0m-eAWvnbdXWI/edit?gid=1224425390#gid=1224425390`
- Default recipient: `hawtimzhang@gmail.com`
- Default subject: `每周动量分析周报 - YYYY-MM-DD`

## Workflow

1. Determine the report date in `Asia/Shanghai`. Use the post publication date when it is clearly the relevant weekly issue; otherwise use the automation run date.
2. Fetch the latest weekly momentum post from the Patreon collection or direct post URL supplied by the user.
3. Extract actionable ETF/index/sector commentary from the author's text.
4. Extract every ticker from both stock tables:
   - First class: `各行业板块综合动量评分最高的股票`
   - Second class: `短期动量大幅提高的股票`
5. Interpret momentum using the indicator model:
   - `Rank = 0.2*20R + 0.4*60R + 0.4*120R`
   - Treat `Rank` as medium-term momentum quality.
   - Treat `20R`, `REL5`, and `REL20` as short-term acceleration, cooling, or relative-strength confirmation.
6. Produce a concise Chinese report using the output structure below.
7. Send the completed report through Gmail. If sending is unavailable, create a Gmail draft and state the reason in the task output.
8. Save the exact completed report body as Markdown in `US-share/weekly-momentum-report/reports/weekly-momentum-report-YYYY-MM-DD.md`.
9. Commit and push the saved report and any intentional skill updates to `git@github.com:hawtim/skills.git`.

## Output Structure

Use this structure unless the user asks otherwise:

```markdown
**本周结论**
1-3 sentences on the market regime and confirmed rotation.

**主关注**
1. Theme/ETF direction: key ETFs and why.
   Action: stock tickers or confirmation signals.

**次关注**
Secondary ETFs/themes and stocks to monitor.

**暂不关注**
Weak sectors/themes and what not to chase.

**第一类：综合动量领导股**
Grouped complete ticker list.

**第二类：短期动量提高**
Grouped complete ticker list.

**一句话行动清单**
What to watch, what confirms the thesis, what invalidates it.

延伸链接:
- 动量指标说明: link.
- 全市场动量观察表: link.

来源: weekly post link. 非投资建议。
```

## Delivery And Archival

- Use the Gmail connector when available.
- Send to `hawtimzhang@gmail.com` unless the user specifies another recipient.
- Keep the email body in Markdown unless the user asks for polished HTML.
- Save the same Markdown report body that was sent or drafted.
- Use repository-relative paths when saving reports.
- Before pushing, check the repository status and avoid committing unrelated user changes.
- If git push is unavailable, leave the report file committed locally when possible and explain the push failure.

## Quality Bar

- One missing ticker is a report failure. Re-check dense table areas manually or with zoomed crops.
- ETF/sector comments from the author's text must be represented when actionable.
- Separate confirmed source facts from inferred analysis.
- Prefer short actionable phrasing over long narrative.
- Never invent table rows, tickers, or publication details.
