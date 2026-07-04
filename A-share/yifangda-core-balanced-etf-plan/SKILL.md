---
name: yifangda-core-balanced-etf-plan
description: Explicitly triggered A-share core balanced ETF rulebook for the user's 易方达 growth/cash-flow/dividend portfolio. Use only when the user invokes "$yifangda-core-balanced-etf-plan", says "启用易方达核心均衡计划", "按易方达三 ETF 组合评估", or otherwise explicitly asks to apply this named plan to 159259, 159222, and 515180. Do not use merely because the user shares generic ETF holdings, costs, profit/loss, or market data.
---

# Yifangda Core Balanced ETF Plan

## Purpose

Use this skill only after explicit invocation. Evaluate the next action for the user's 易方达 A 股核心均衡 ETF portfolio:

- 159259 成长ETF易方达: offensive growth sleeve.
- 159222 自由现金流ETF易方达: quality cash-flow core.
- 515180 红利ETF易方达: defensive dividend sleeve.

The default reference principal is 400,000 yuan, but all amounts must scale proportionally when the user provides a different principal cap. Percentage weights and trigger thresholds do not scale.

Always load `references/execution-plan.md` before giving a recommendation. Treat that reference as the controlling rulebook.

Do not apply this skill to ordinary portfolio reviews or unrelated ETF holdings unless the user explicitly invokes the trigger phrase.

Use `data/operation-log.csv` as the canonical operation-log schema when the user asks to track, append, reconcile, or review historical actions. Do not invent past trades; only record operations the user explicitly reports.

Use `scripts/backtest_core_balanced_plan.py` when the user asks to pull historical ETF data or backtest this plan. The script defaults to Yahoo Finance daily data, supports scalable principal with `--principal`, and writes price, NAV, operation-log, and summary CSV files. State the script assumptions when citing results: close-price execution, fractional shares, no fees/slippage/taxes, full principal deployment by schedule, and ordinary month-end rebalance only after principal is deployed.

## Required Inputs

Ask for missing inputs only when they materially change the action. Otherwise, proceed with explicit assumptions.

Minimum useful inputs:

- Current market value, cost, and P/L for each ETF held.
- User's intended principal cap. Default to 400,000 yuan only if the user does not specify a different amount.
- Cash or remaining principal available toward the stated principal cap.
- Portfolio drawdown from the latest stage high, or enough data to infer it.
- Whether the action requested is initial build, regular DCA, principal add, rebalance, trim, or risk review.
- Any newly reported trade actions that should be appended to the operation log.

Covered ETFs:

| Code | Name | Target Weight |
|---:|---|---:|
| 159259 | 成长ETF易方达 | 30% |
| 159222 | 自由现金流ETF易方达 | 40% |
| 515180 | 红利ETF易方达 | 30% |

## Evaluation Workflow

1. Load `references/execution-plan.md`.
2. Classify the request as one of: initial build, regular DCA, principal add, rebalance, risk pause, trim, or plan exception.
3. Calculate current principal invested, ETF weights, remaining capacity to the user's principal cap, and portfolio drawdown.
   - If the user gives a principal cap different from 400,000 yuan, calculate a scale factor: `user_principal_cap / 400000`.
   - Apply the scale factor to all reference amounts in `references/execution-plan.md`.
   - Do not scale target weights, drawdown thresholds, profit thresholds, or rebalance bands.
4. Check hard restrictions before recommending any buy:
   - Principal ETF position must not exceed the user's stated principal cap.
   - 159259 must not remain above 40% weight.
   - 159222 must not remain below 32% weight after principal is fully deployed unless the user explicitly accepts a more aggressive tilt.
   - 515180 must not remain below 24% weight after principal is fully deployed unless the user explicitly accepts a more aggressive tilt.
   - If portfolio loss exceeds 15%, require a market/regime review before mechanical buying.
5. Apply the relevant trigger table from the reference:
   - Initial build schedule.
   - Regular DCA rules.
   - Regime tilt rules.
   - Rebalance bands.
   - Risk pause rules.
6. Produce a clear action decision: buy, hold, pause, trim, rebalance, or review first.

## Output Format

Respond in Chinese unless the user asks otherwise. Keep the recommendation operational and rule-linked.

Use this structure:

1. **结论**: one clear next action and whether it is allowed by the plan.
2. **账户状态**: principal invested, remaining principal capacity, current ETF weights, drawdown if available.
3. **规则检查**: which triggers are met or not met.
4. **具体操作**: amounts by ETF, or "do nothing" if no action is allowed.
5. **后续触发点**: exact next drawdown, profit, time, or rebalance threshold to watch.
6. **禁止事项**: any action the plan forbids in the current state.

When inputs are incomplete, label the result as a conditional review and state exactly which missing data would change the decision.

## Style

Be strict. Do not optimize around the plan unless the user explicitly asks to revise the plan. If a suggested action violates the plan, say so plainly and propose the closest plan-compliant action.
