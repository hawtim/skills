# ETF Theme Daily Report Playbook

## Objective

Produce a daily market and plan-compliance report for the A-share technology ETF account. The report should help the user decide whether today is a no-action day, watch day, ordinary add day, rebalance day, or margin-dip-buying candidate.

## Data Checklist

Use the freshest available data and label the timestamp:

1. Market indices:
   - 上证指数
   - 深证成指
   - 创业板指
   - 科创 50
   - 北证 50 if relevant
2. Theme and sector proxies:
   - 半导体
   - 半导体设备/材料
   - 电子
   - 通信/5G/光模块
   - AI 硬件/算力
   - 机器人
   - 信创/国产软件/网络安全
3. Account ETFs:
   - 159530 机器人ETF易方达
   - 159994 通信ETF银华
   - 515260 电子ETF华宝
   - 159516 半导体设备材料ETF国泰
   - 159538 信创ETF富国
4. Macro and liquidity:
   - 人民币汇率
   - 北向/南向 or broad foreign-flow context when available
   - 利率、央行、流动性 headlines
   - US tech/Nasdaq/semiconductor overnight read-through when relevant
5. News:
   - Domestic policy
   - Export controls/sanctions
   - Semiconductor capex/equipment/materials news
   - AI hardware/cloud capex news
   - Major earnings/preannouncements
   - ETF/index methodology/fund liquidity changes

## Market Temperature Classification

Classify the day with one label:

| Label | Meaning |
|---|---|
| `risk-on` | Broad market and technology themes are supported by price action and news. |
| `neutral` | Mixed signals; no strong action bias. |
| `risk-off` | Broad weakness, weak liquidity, or negative news; avoid aggressive adds. |
| `panic` | Sharp broad selloff, disorderly selling, or multiple plan drawdown triggers near activation. |
| `overheated` | Fast gains, crowded headlines, extended prices, or weights breaching upper bands. |

## Plan Rule Lens

Use the execution plan as the action authority:

- Principal cap is user-defined, with 400,000 yuan as default.
- Target weights: 30% / 25% / 20% / 15% / 10%.
- Margin only activates at portfolio drawdown thresholds: 10%, 15%, 20%.
- 159516 must not remain above 20%.
- 159538 must not remain above 13%.
- If fully invested, ordinary price dips are not automatically add signals.
- If not fully invested, down days can be ordinary principal build opportunities, not margin opportunities.

## Overheating and Washout Signals

Use a balanced set of signs; do not rely on one indicator:

Overheating signs:

- Several ETFs up strongly in a short window.
- Theme ETF weight drifts above upper band.
- News flow becomes one-sided bullish and broad.
- Large gap-ups followed by intraday fading.
- Price far above recent moving averages, if data is available.

Washout or potential opportunity signs:

- Portfolio drawdown approaches execution-plan thresholds.
- Multiple themes fall sharply on no durable thesis break.
- Selling is broad but volume climaxes and stabilizes.
- Leaders stop falling before laggards.
- Position weights are below lower bands and there is unused principal.

## Daily Action Posture

Use one of these:

| Posture | Meaning |
|---|---|
| `no action` | No plan rule is triggered. |
| `watch` | Close to a trigger; define exact next level. |
| `ordinary principal add` | User is not fully invested and plan allows a tranche. |
| `rebalance review` | Weight bands are breached. |
| `margin eligible` | Drawdown threshold is reached and financing rules allow it. |
| `de-risk / repay margin` | Margin exit or risk-control rule is triggered. |
| `plan exception` | The user asks for an action outside the plan; explain deviation risk. |

## Evidence Rules

- Date-stamp current market data.
- Use direct source links when browsing live data.
- Separate facts, assumptions, and judgment.
- If unable to fetch data, say which fields are stale or missing.
- Do not present forecasts as facts.
