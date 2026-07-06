# Gold Regime Rules

## Scope

Run a daily gold tactical-regime monitor. The system gives advice for the tactical sleeve only; the strategic gold core is checked monthly and is not driven by daily noise. Default output is a recommendation and target weight, not automatic execution.

## Portfolio Layers

| Layer | Default Range | Purpose | Daily Model |
|---|---:|---|---|
| Strategic core | 3%-7%, target 5% | Currency, fiscal, geopolitical, and tail-risk hedge | Monthly rebalance only |
| Tactical sleeve | 0%-5%, cap 5% | Real-yield decline, USD weakness, and trend capture | Daily state machine |

Hard cap: strategic plus tactical gold exposure must not exceed 12% of total portfolio value.

## Required Critical Data

If any critical series is unavailable or stale beyond three U.S. trading days, output `DATA_INVALID / NO_TRADE`:

- Gold close: XAUUSD, continuous COMEX gold, or a clearly labeled proxy.
- 10Y real yield: FRED `DFII10`.
- Broad USD: FRED `DTWEXBGS`.

Auxiliary daily data:

- 2Y yield: FRED `DGS2`.
- 10Y nominal yield: FRED `DGS10`.
- 10Y breakeven: FRED `T10YIE`.
- VIX: FRED `VIXCLS`.
- HY OAS: FRED `BAMLH0A0HYM2`.
- GLD close or holdings when available.

Slow variables:

- CFTC COT COMEX Gold managed money net long.
- World Gold Council global gold ETF flow and holdings.
- Central-bank demand for narrative only.

## Feature Definitions

```text
return_N(x) = x[t] / x[t-N] - 1
change_bp_N(yield) = (yield[t] - yield[t-N]) * 100
sma_N(price) = N-day simple moving average
slope_N(series) = series[t] - series[t-N]
percentile_252(x) = current value percentile over the last 252 valid observations
```

Price structure:

```text
ma20 = SMA(gold_close, 20)
ma50 = SMA(gold_close, 50)
ma100 = SMA(gold_close, 100)
weekly_ma10 = 10-week moving average
trend_positive = ma20 > ma50 and ma20 > ma20[t-5]
weekly_confirmed = weekly_close > weekly_ma10
distance_to_ma50 = gold_close / ma50 - 1
```

Macro features:

```text
real_yield_20d_bp = change_bp_20(real_yield_10y)
usd_20d_return = return_20(usd_broad)
policy_20d_bp = change_bp_20(implied_policy_rate or DGS2 fallback)
breakeven_20d_bp = change_bp_20(breakeven_10y)
hy_oas_20d_bp = change_bp_20(hy_oas)
vix_10d_change = vix[t] - vix[t-10]
```

## Score

Macro turn, max 40:

- 10Y real yield 20D decline >= 10 bp: +15; between -10 and +10 bp: +7; rise >= 10 bp: +0.
- Broad USD 20D return <= -1%: +10; between -1% and +1%: +5; >= +1%: +0.
- Policy path 20D decline >= 15 bp: +10; small change: +5; rise >= 15 bp: +0.
- Breakeven rising while real yield falls: +5.

Flow confirmation, max 20 when available:

- GLD holdings 10D increase: +10; unchanged/unavailable: +5 or `UNAVAILABLE`; decrease: +0.
- Global gold ETF latest net inflow: +5; neutral/unavailable: +2 or `UNAVAILABLE`; outflow: +0.
- COT net-long percentile 40-80 and weekly increase: +5; >90: +0; other: +2.

When flow inputs are unavailable, shrink the active denominator instead of assigning zero confirmation.

Technical structure, max 30:

- Gold close above MA20: +10.
- MA20 > MA50 and MA20 rising: +10.
- Weekly close above 10-week MA: +5.
- Distance to MA50 <= 8%: +5.
- If distance to MA50 > 15%, subtract 5 from this module, floor at zero.

Risk environment, max 10:

- VIX 10D change >= +3 or HY OAS 20D change >= +20 bp, and USD is not strong while real yield is not rising: +5.
- If both VIX/credit stress and the rate/USD filter are satisfied: +10.
- If risk rises while USD and real yield rise together: +0.

Total:

```text
raw_score = macro_score + flow_score + technical_score + risk_score
score = round(raw_score / active_weight * 100)
```

## Hard Vetoes

Directly output `EXIT_TACTICAL` if any condition is true:

1. `real_yield_20d_bp >= +20bp` and `usd_20d_return >= +2%` and `gold_close < ma50`.
2. `score < 40` for five consecutive valid trading days.
3. Gold closes below MA100 while GLD holdings fall over 10D and real yield rises over 10D.
4. Policy path rises >= 25 bp over 20D and gold breaks below MA50.

## Tactical State Machine

| Score Condition | Target Tactical Weight | Action |
|---|---:|---|
| `<40` | 0% | Exit tactical sleeve |
| `40-54` | 0%-1/3 cap | Watch or reduce existing tactical to max 1/3 cap |
| `55-59` | 1/3 cap | Hold small existing sleeve; no new add |
| `60-74` for 2 days | 1/3 cap | Build or top up to 1/3 cap |
| `75-85` for 2 days | 2/3 cap | Add to 2/3 cap |
| `>85` | Max 2/3 cap | Do not chase; crowded watch |

With a 5% tactical cap, 1/3 cap is 1.67%, and 2/3 cap is 3.33%.

Reduction rules:

- Score falls from >=60 to <55 for three consecutive days: sell one third of current tactical sleeve.
- If two of these are true, reduce tactical to no more than 1/3 cap: real yield 20D up >=20 bp; USD regains MA50 and is up >=2% over 20D; gold breaks MA50 with falling MA20.
- Hard veto: clear tactical sleeve.
- Distance to MA50 >10%, COT >85 percentile, and real yield no longer falling: sell one third.
- Distance to MA50 >15%, COT >90 percentile, and GLD holdings no longer increasing: sell another third.

## Output Shape

Use the Chinese report template:

```markdown
# 黄金白银日度监控｜YYYY-MM-DD HH:mm｜Asia/Shanghai

## 结论
- Regime:
- Score:
- 建议战术仓目标:
- 当前战术仓:
- 建议变动:
- 战略底仓:

## 一句话原因

## 四模块评分

## 关键数据

## 白银伴随观察

## 触发器

## 未来 7 天事件风险

## Agent 审计摘要
```

Narrative labels must be one of `CONFIRMED_BY_FACTORS`, `PARTIALLY_CONFIRMED`, or `NARRATIVE_ONLY`.
