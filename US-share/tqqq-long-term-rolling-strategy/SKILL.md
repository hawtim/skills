---
name: tqqq-long-term-rolling-strategy
description: Explicitly triggered U.S. TQQQ long-term rolling investment strategy skill based on TheMarketMemo's TQQQ strategy post. Use when the user invokes "$tqqq-long-term-rolling-strategy", asks to apply the TQQQ长期滚动策略/TQQQ long-term rolling strategy, wants this TQQQ/JEPQ/SGOV/QQQ/VXN rulebook reviewed, or asks to backtest/update the strategy under US-share/tqqq-long-term-rolling-strategy.
---

# TQQQ Long-Term Rolling Strategy

## Purpose

Use this skill only after explicit invocation. Evaluate, document, or backtest the user's TQQQ long-term rolling strategy built around TQQQ, JEPQ, SGOV, QQQ, VXN, QQQ puts, and NQ/MNQ hedge logic.

Always load `references/rulebook.md` before giving a recommendation. Treat that reference as the controlling rulebook.

Use `scripts/backtest_tqqq_strategy.py` when the user asks to run or refresh a backtest. The script defaults to Futu OpenD data, writes daily prices, dividends, NAV, operation logs, summary CSV, and a Markdown report. State the script assumptions when citing results: close-price execution, fractional shares, no fees/slippage/taxes/borrowing costs, dividend cash received on payable date, QQQ short proxy for NQ/MNQ hedge, VXN trigger disabled unless VXN history is provided, and QQQ put insurance not valued without option-chain history.

## Required Inputs

Ask for missing inputs only when they materially change the action. Otherwise proceed with explicit assumptions.

Minimum useful inputs:

- Account equity or reference principal. Default to 100,000 USD for backtests.
- Current holdings in TQQQ, JEPQ, SGOV, and cash if reviewing a live account.
- Whether NQ/MNQ hedges or QQQ puts are already open.
- Strategy start date and end date for backtests.
- Whether to include hedge proxy. Default to include it for rule-conforming backtests.

## Workflow

1. Load `references/rulebook.md`.
2. Classify the request as live review, Futu watchlist sync, backtest, rule update, or report/archive update.
3. For live review, calculate current weights, QQQ 200-day moving average status, TQQQ drawdown from recent high, DCA eligibility, BTD triggers, hedge state, and rebalance triggers.
4. For backtests, run `scripts/backtest_tqqq_strategy.py` with explicit dates and source, then read `summary.csv` and the generated Markdown report before responding.
5. Separate source rules from deterministic backtest approximations. Do not present option-insurance payoffs or futures execution as exact unless the needed contract and option-chain data are present.
6. End with one operational conclusion: buy TQQQ, buy SGOV, hold, rebalance, hedge, unhedge, or review manually.

## Output Format

Respond in Chinese unless the user asks otherwise. Keep the recommendation operational and rule-linked.

Use this structure:

1. **结论**: one clear next action and whether it is allowed by the plan.
2. **账户状态**: weights, cash reserve, QQQ 200MA status, TQQQ drawdown, hedge/insurance state.
3. **规则检查**: DCA, BTD, hedge, rebalance, black-swan insurance.
4. **具体操作**: amounts or percentages by instrument, or "do nothing" if no action is allowed.
5. **后续触发点**: exact next price, moving-average, drawdown, VXN, or weight threshold.
6. **限制说明**: any rule component that needs manual judgment or richer data.

## Style

Be strict and source-linked. Do not optimize around the rulebook unless the user explicitly asks to revise it. Label any model simplification as a backtest approximation, not as the original author's exact result.
