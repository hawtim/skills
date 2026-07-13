# Structure And Scoring Rules

## LEI Interpretation

Apply the local LEI principles as follows:

- Treat price and trend as market consensus; do not let a narrative overrule a broken structure.
- Use EMA for early warning and MA/price structure for confirmation.
- Track the turn as a process: reclaim a short average, short average turns up, short average crosses medium average, bullish alignment forms, then monitor excessive extension.
- Separate tactical trading structure from long-term compounding exposure.

## Swing Definition

- Detect daily swing points with a 3-bar window on both sides.
- Ignore differences smaller than `0.35 × ATR(14)` when comparing two swing highs or lows.
- Prefer closing-price breaks. Treat intraday violations without a confirming close as warnings.
- Compute weekly structure independently from weekly-resampled data.

## State Machine

| State | Required structure |
|---|---|
| `下降趋势确认` | Lower high plus lower low, or a lower high followed by a close below the reaction low |
| `底部观察` | Selling pressure slows, a lower low is rejected, or a higher low forms without breaking the prior reaction high |
| `阶段底部确认` | Higher low plus close above the prior reaction high |
| `上升趋势` | Higher high plus higher low |
| `顶部观察` | Rally fails to make a meaningful new high; lower high forms without a confirmed breakdown |
| `阶段顶部确认` | Lower high plus close below the prior reaction low |
| `区间/冲突` | High/low relationships disagree or regional confirmation is absent |

A lower high alone is a warning, not a confirmed top. A higher low alone is a warning, not a confirmed bottom.

## Cross-Market Confirmation

- Require at least two of the U.S., Korea, Taiwan, and China regional blocks to improve within three trading sessions before calling a global stage bottom.
- Require the U.S. anchor plus at least one Asian block to deteriorate before calling a high-confidence global stage top.
- Label wide regional dispersion as `区域背离`; do not average it away.

## Scores

Compute `入场准备度` from:

- U.S. ETF/index structure: 35%
- regional confirmation: 25%
- breadth and leadership: 20%
- macro risk environment: 20%

Compute `顶部风险度` from:

- U.S. structure/top signals: 45%
- regional top confirmation: 25%
- macro stress: 15%
- breadth deterioration: 15%

Action bands:

| Readiness | Action |
|---:|---|
| 0–39 | `NO_ENTRY` |
| 40–59 | `BOTTOM_WATCH` |
| 60–74 | `TACTICAL_ENTRY_READY` |
| 75–100 | `TREND_ENTRY_READY` |

Treat `TOP_RISK ≥ 70` as a veto on new tactical longs unless a confirmed stage bottom subsequently invalidates it.

## Closed-Loop Evaluation

For every daily signal, save benchmark returns after 1/3/5/10 trading sessions plus maximum favorable excursion and maximum adverse excursion over the first 10 sessions. Keep rule versions stable and show sample size. Shadow calibration may suggest a threshold only after 30 matured observations; it must not silently change production rules.
