---
name: etf-theme-execution-plan
description: Explicitly triggered ETF theme account rulebook for the user's China A-share technology ETF plan. Use only when the user invokes "$etf-theme-execution-plan", says "启用ETF主题计划", "按ETF主题账户计划评估", or otherwise explicitly asks to apply this named execution plan to 159530, 159994, 515260, 159516, and 159538. Do not use merely because the user shares generic holdings, ETF positions, costs, profit/loss, or margin data.
---

# ETF Theme Execution Plan

## Purpose

Use this skill only after explicit invocation. Evaluate the next action for the user's dedicated technology ETF theme account. The plan uses 400,000 yuan as the default reference principal, but must scale all amounts proportionally when the user provides a different principal cap. Treat margin financing as temporary dip-buying ammunition only.

Always load `references/execution-plan.md` before giving a recommendation. Treat that reference as the controlling rulebook.

Do not apply this skill to ordinary portfolio reviews or unrelated ETF holdings unless the user explicitly invokes the trigger phrase.

Use `data/operation-log.csv` as the canonical operation-log schema when the user asks to track, append, reconcile, or review historical actions. Do not invent past trades; only record operations the user explicitly reports.

Use `scripts/backtest_etf_plan.py` when the user asks to pull historical ETF data or backtest this plan. The script defaults to Yahoo Finance daily data, supports Eastmoney as an optional source, scales the principal amount with `--principal`, and writes price, NAV, operation-log, and summary CSV files. State the script assumptions when citing results: close-price execution, fractional shares, no fees/slippage/interest/taxes, and deterministic drawdown triggers for subjective plan language.

## Required Inputs

Ask for missing inputs only when they materially change the action. Otherwise, proceed with explicit assumptions.

Minimum useful inputs:

- Current market value, cost, and P/L for each ETF held.
- User's intended principal cap. Default to 400,000 yuan only if the user does not specify a different amount.
- Cash or remaining principal available toward the stated principal cap.
- Whether margin financing is currently used, and the margin amount if used.
- Portfolio drawdown from the latest stage high, or enough data to infer it.
- Whether the action requested is initial build, regular DCA, principal add, margin dip-buying, margin exit, or rebalance.
- Any newly reported trade actions that should be appended to the operation log.

Covered ETFs:

| Code | Name | Target Weight |
|---:|---|---:|
| 159530 | 机器人ETF易方达 | 30% |
| 159994 | 通信ETF银华 | 25% |
| 515260 | 电子ETF华宝 | 20% |
| 159516 | 半导体设备材料ETF国泰 | 15% |
| 159538 | 信创ETF富国 | 10% |

## Evaluation Workflow

1. Load `references/execution-plan.md`.
2. Classify the request as one of: initial build, regular DCA, principal add, margin dip-buying, margin exit, rebalance, risk pause, or plan exception.
3. Calculate current principal invested, ETF weights, remaining capacity to the user's principal cap, and any margin usage.
   - If the user gives a principal cap different from 400,000 yuan, calculate a scale factor: `user_principal_cap / 400000`.
   - Apply the scale factor to all reference amounts in `references/execution-plan.md`, including initial-build tranches, principal adds, and margin dip-buying tiers.
   - Do not scale percentage thresholds such as target weights, drawdown triggers, profit triggers, or rebalance bands.
4. Check hard restrictions before recommending any buy:
   - Principal ETF position must not exceed the user's stated principal cap.
   - Margin buying is forbidden unless portfolio drawdown from stage high is at least 10%.
   - Margin dip-buying must not become permanent principal.
   - 159516 must not remain above 20% weight.
   - 159538 must not remain above 13% weight.
   - If portfolio loss exceeds 15%, require a theme review before mechanical buying.
5. Apply the relevant trigger table from the reference:
   - Initial build schedule.
   - Regular DCA rules.
   - Principal add rules.
   - Margin dip-buying rules.
   - Margin exit rules.
   - Rebalance bands.
6. Produce a clear action decision: buy, hold, pause, reduce, repay margin, rebalance, or review first.

## Output Format

Respond in Chinese unless the user asks otherwise. Keep the recommendation operational and rule-linked.

Use this structure:

1. **结论**: one clear next action and whether it is allowed by the plan.
2. **账户状态**: principal invested, remaining principal capacity, margin usage, current ETF weights, drawdown if available.
3. **规则检查**: which triggers are met or not met.
4. **具体操作**: amounts by ETF, or "do nothing" if no action is allowed.
5. **后续触发点**: exact next drawdown, profit, loss, time, or rebalance threshold to watch.
6. **禁止事项**: any action the plan forbids in the current state.

When inputs are incomplete, label the result as a conditional review and state exactly which missing data would change the decision.

## Style

Be strict. Do not optimize around the plan unless the user explicitly asks to revise the plan. If a suggested action violates the plan, say so plainly and propose the closest plan-compliant action.
