#!/usr/bin/env python3
"""Generate a gold/silver daily regime report without third-party packages."""

from __future__ import annotations

import argparse
import csv
import json
import math
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


FRED_SERIES = {
    "real_yield_10y": "DFII10",
    "usd_broad": "DTWEXBGS",
    "yield_2y": "DGS2",
    "yield_10y": "DGS10",
    "breakeven_10y": "T10YIE",
    "vix": "VIXCLS",
    "hy_oas": "BAMLH0A0HYM2",
}

PRICE_SOURCES = {
    "gold": ["xauusd", "gc.f", "gld.us"],
    "silver": ["xagusd", "si.f", "slv.us"],
}

TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"


@dataclass
class Series:
    name: str
    source: str
    points: list[tuple[date, float]]

    @property
    def latest_date(self) -> date:
        return self.points[-1][0]

    @property
    def latest_value(self) -> float:
        return self.points[-1][1]

    def ago(self, n: int) -> float | None:
        if len(self.points) <= n:
            return None
        return self.points[-1 - n][1]

    def change(self, n: int) -> float | None:
        prev = self.ago(n)
        if prev is None:
            return None
        return self.latest_value - prev

    def pct_return(self, n: int) -> float | None:
        prev = self.ago(n)
        if prev in (None, 0):
            return None
        return self.latest_value / prev - 1

    def sma(self, n: int, offset: int = 0) -> float | None:
        end = len(self.points) - offset
        start = end - n
        if start < 0 or end <= 0:
            return None
        values = [value for _, value in self.points[start:end]]
        return sum(values) / len(values)


def fetch_url(url: str, retries: int = 2) -> str:
    curl_error: Exception | None = None
    try:
        completed = subprocess.run(
            ["curl", "-sSL", "--max-time", "20", url],
            check=True,
            capture_output=True,
            text=True,
        )
        if completed.stdout.strip():
            return completed.stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        curl_error = exc

    request = urllib.request.Request(url, headers={"User-Agent": "codex-gold-regime-monitor/1.0"})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: curl={curl_error}; urllib={last_error}")


def parse_float(value: str) -> float | None:
    value = value.strip()
    if not value or value == ".":
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def fetch_fred(series_id: str, start_date: date | None = None) -> Series:
    if start_date is None:
        today = date.today()
        start_date = date(today.year, 1, 1)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date.isoformat()}"
    text = fetch_url(url)
    rows = csv.DictReader(text.splitlines())
    points: list[tuple[date, float]] = []
    for row in rows:
        raw_date = row.get("observation_date")
        raw_value = row.get(series_id)
        if not raw_date or raw_value is None:
            continue
        dt = date.fromisoformat(raw_date)
        if dt < start_date:
            continue
        value = parse_float(raw_value)
        if value is not None:
            points.append((dt, value))
    if len(points) < 40:
        raise RuntimeError(f"FRED {series_id} returned only {len(points)} usable points")
    return Series(series_id, f"FRED:{series_id}", points)


def fetch_stooq_symbol(symbol: str) -> Series:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    text = fetch_url(url)
    rows = csv.DictReader(text.splitlines())
    points: list[tuple[date, float]] = []
    for row in rows:
        raw_date = row.get("Date")
        raw_close = row.get("Close")
        if not raw_date or raw_close is None:
            continue
        value = parse_float(raw_close)
        if value is not None:
            points.append((date.fromisoformat(raw_date), value))
    if len(points) < 120:
        raise RuntimeError(f"Stooq {symbol} returned only {len(points)} usable points")
    return Series(symbol, f"Stooq:{symbol}", points)


def fetch_first_price(kind: str) -> Series:
    errors = []
    for symbol in PRICE_SOURCES[kind]:
        try:
            return fetch_stooq_symbol(symbol)
        except Exception as exc:  # keep trying fallbacks
            errors.append(f"{symbol}: {exc}")
    raise RuntimeError(f"No usable {kind} price source. " + "; ".join(errors))


def bp_change(series: Series, n: int) -> float | None:
    change = series.change(n)
    if change is None:
        return None
    return change * 100


def weekly_confirmed(series: Series) -> tuple[bool | None, float | None]:
    weekly: list[tuple[tuple[int, int], date, float]] = []
    last_key = None
    for dt, value in series.points:
        iso = dt.isocalendar()
        key = (iso.year, iso.week)
        if key != last_key:
            weekly.append((key, dt, value))
            last_key = key
        else:
            weekly[-1] = (key, dt, value)
    if len(weekly) < 10:
        return None, None
    latest = weekly[-1][2]
    ma10 = sum(row[2] for row in weekly[-10:]) / 10
    return latest > ma10, ma10


def fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}{suffix}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.{digits}f}%"


def days_old(dt: date, as_of: date) -> int:
    return max((as_of - dt).days, 0)


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    history = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            history.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return history


def append_history(path: Path, snapshot: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_history(path)
    compact = {
        "as_of": snapshot["as_of"],
        "generated_at": snapshot["generated_at"],
        "data_status": snapshot["data_status"],
        "regime": snapshot["regime"],
        "score": snapshot["score"],
        "macro_score": snapshot["macro_score"],
        "flow_score": snapshot["flow_score"],
        "technical_score": snapshot["technical_score"],
        "risk_score": snapshot["risk_score"],
        "action": snapshot["action"],
        "tactical_target_weight": snapshot["tactical_target_weight"],
    }
    without_same_asof = [row for row in existing if row.get("as_of") != snapshot["as_of"]]
    without_same_asof.append(compact)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in without_same_asof) + "\n", encoding="utf-8")


def consecutive_scores(history: list[dict], current_score: int, predicate) -> int:
    scores = [row.get("score") for row in history if isinstance(row.get("score"), int)]
    scores.append(current_score)
    count = 0
    for score in reversed(scores):
        if predicate(score):
            count += 1
        else:
            break
    return count


def compute(args: argparse.Namespace) -> tuple[dict, str]:
    now = datetime.now(TZ) if args.run_at is None else datetime.fromisoformat(args.run_at).astimezone(TZ)
    as_of = now.date()

    fred = {name: fetch_fred(series_id) for name, series_id in FRED_SERIES.items()}
    gold = fetch_first_price("gold")
    silver = fetch_first_price("silver")

    real_20 = bp_change(fred["real_yield_10y"], 20)
    real_10 = bp_change(fred["real_yield_10y"], 10)
    usd_20 = fred["usd_broad"].pct_return(20)
    usd_10 = fred["usd_broad"].pct_return(10)
    policy_20 = bp_change(fred["yield_2y"], 20)
    breakeven_20 = bp_change(fred["breakeven_10y"], 20)
    vix_10 = fred["vix"].change(10)
    hy_20 = bp_change(fred["hy_oas"], 20)

    ma20 = gold.sma(20)
    ma50 = gold.sma(50)
    ma100 = gold.sma(100)
    ma20_5 = gold.sma(20, offset=5)
    weekly_ok, weekly_ma10 = weekly_confirmed(gold)
    distance_to_ma50 = None if ma50 in (None, 0) else gold.latest_value / ma50 - 1

    macro_score = 0
    macro_reasons: list[str] = []
    if real_20 is not None and real_20 <= -10:
        macro_score += 15
        macro_reasons.append("REAL_YIELD_20D_DOWN")
    elif real_20 is not None and real_20 < 10:
        macro_score += 7
        macro_reasons.append("REAL_YIELD_20D_NEUTRAL")

    if usd_20 is not None and usd_20 <= -0.01:
        macro_score += 10
        macro_reasons.append("USD_20D_DOWN")
    elif usd_20 is not None and usd_20 < 0.01:
        macro_score += 5
        macro_reasons.append("USD_20D_NEUTRAL")

    if policy_20 is not None and policy_20 <= -15:
        macro_score += 10
        macro_reasons.append("POLICY_PATH_DOWN")
    elif policy_20 is not None and policy_20 < 15:
        macro_score += 5
        macro_reasons.append("POLICY_PATH_NEUTRAL")

    if breakeven_20 is not None and real_20 is not None and breakeven_20 > 0 and real_20 < 0:
        macro_score += 5
        macro_reasons.append("BREAKEVEN_UP_REAL_YIELD_DOWN")

    technical_score = 0
    technical_reasons: list[str] = []
    if ma20 is not None and gold.latest_value > ma20:
        technical_score += 10
        technical_reasons.append("PRICE_ABOVE_MA20")
    if ma20 is not None and ma50 is not None and ma20_5 is not None and ma20 > ma50 and ma20 > ma20_5:
        technical_score += 10
        technical_reasons.append("MA20_ABOVE_MA50_AND_RISING")
    if weekly_ok:
        technical_score += 5
        technical_reasons.append("WEEKLY_ABOVE_10W_MA")
    if distance_to_ma50 is not None and distance_to_ma50 <= 0.08:
        technical_score += 5
        technical_reasons.append("NOT_EXTENDED_VS_MA50")
    if distance_to_ma50 is not None and distance_to_ma50 > 0.15:
        technical_score = max(technical_score - 5, 0)
        technical_reasons.append("OVERHEATED_VS_MA50")

    flow_score = 0
    flow_active_weight = 0
    flow_status = "UNAVAILABLE"
    flow_reasons = ["GLD_HOLDINGS_UNAVAILABLE", "COT_UNAVAILABLE", "WGC_FLOW_UNAVAILABLE"]

    risk_filter_ok = (usd_20 is not None and usd_20 < 0.01) and (real_20 is not None and real_20 <= 0)
    vix_stress = vix_10 is not None and vix_10 >= 3
    credit_stress = hy_20 is not None and hy_20 >= 20
    if risk_filter_ok and vix_stress and credit_stress:
        risk_score = 10
        risk_reason = "VIX_AND_CREDIT_STRESS_WITH_RATE_USD_FILTER"
    elif risk_filter_ok and (vix_stress or credit_stress):
        risk_score = 5
        risk_reason = "RISK_STRESS_WITH_RATE_USD_FILTER"
    else:
        risk_score = 0
        risk_reason = "RISK_PREMIUM_NOT_CONFIRMED"

    active_weight = 40 + 30 + 10 + flow_active_weight
    raw_score = macro_score + technical_score + risk_score + flow_score
    score = round(raw_score / active_weight * 100) if active_weight else 0

    data_ages = {
        "price_days": days_old(gold.latest_date, as_of),
        "real_yield_days": days_old(fred["real_yield_10y"].latest_date, as_of),
        "usd_days": days_old(fred["usd_broad"].latest_date, as_of),
        "gld_holdings_days": None,
        "cot_days": None,
        "global_etf_flow_days": None,
    }
    critical_ok = all(age is not None and age <= args.max_critical_age_days for age in [
        data_ages["price_days"],
        data_ages["real_yield_days"],
        data_ages["usd_days"],
    ])

    history_path = DATA_DIR / "gold_history.jsonl"
    history = load_history(history_path)
    score_below_40_count = consecutive_scores(history, score, lambda value: value < 40)
    score_add_count = consecutive_scores(history, score, lambda value: value >= 60)
    score_add2_count = consecutive_scores(history, score, lambda value: 75 <= value <= 85)

    hard_vetoes = []
    if real_20 is not None and usd_20 is not None and ma50 is not None:
        if real_20 >= 20 and usd_20 >= 0.02 and gold.latest_value < ma50:
            hard_vetoes.append("REAL_YIELD_UP_USD_UP_PRICE_BELOW_MA50")
    if score_below_40_count >= 5:
        hard_vetoes.append("SCORE_BELOW_40_5D")
    if policy_20 is not None and ma50 is not None and policy_20 >= 25 and gold.latest_value < ma50:
        hard_vetoes.append("POLICY_PATH_UP_PRICE_BELOW_MA50")

    tactical_cap = args.tactical_cap_weight
    current_tactical = args.current_tactical_weight
    action = "HOLD"
    regime = "WATCH"
    target = min(current_tactical, tactical_cap / 3)
    missing_confirmations: list[str] = []

    if not critical_ok:
        data_status = "FAIL"
        regime = "DATA_INVALID"
        action = "NO_TRADE"
        target = current_tactical
        missing_confirmations.append("关键数据过期或缺失，禁止生成交易动作")
    else:
        data_status = "DEGRADED" if flow_status == "UNAVAILABLE" else "PASS"
        if hard_vetoes:
            regime = "EXIT_TACTICAL"
            action = "EXIT_TACTICAL"
            target = 0.0
        elif score < 40:
            regime = "EXIT_TACTICAL"
            action = "EXIT_TACTICAL"
            target = 0.0
        elif score < 55:
            regime = "WATCH"
            action = "WATCH_OR_REDUCE_TO_1_3_CAP"
            target = min(current_tactical, tactical_cap / 3)
        elif score < 60:
            regime = "HOLD"
            action = "HOLD_SMALL_TACTICAL_ONLY"
            target = min(max(current_tactical, 0.0), tactical_cap / 3)
            missing_confirmations.append("分数未达到 60，不新增战术仓")
        elif score < 75:
            regime = "ADD_1" if score_add_count >= 2 else "WATCH"
            action = "ADD_TACTICAL_1" if score_add_count >= 2 else "WAIT_FOR_2D_CONFIRMATION"
            target = tactical_cap / 3 if score_add_count >= 2 else current_tactical
            if score_add_count < 2:
                missing_confirmations.append("需要连续 2 个有效交易日 score >= 60")
        elif score <= 85:
            regime = "ADD_2" if score_add2_count >= 2 else "WATCH"
            action = "ADD_TACTICAL_2" if score_add2_count >= 2 else "WAIT_FOR_2D_CONFIRMATION"
            target = tactical_cap * 2 / 3 if score_add2_count >= 2 else current_tactical
            if score_add2_count < 2:
                missing_confirmations.append("需要连续 2 个有效交易日 75 <= score <= 85")
        else:
            regime = "CROWDED_WATCH"
            action = "DO_NOT_CHASE"
            target = min(current_tactical, tactical_cap * 2 / 3)

    proposed_trade_weight = target - current_tactical
    if abs(proposed_trade_weight) > args.max_single_day_change_weight:
        proposed_trade_weight = math.copysign(args.max_single_day_change_weight, proposed_trade_weight)
        target = current_tactical + proposed_trade_weight
        missing_confirmations.append("单日变动被最大单日战术调整幅度限制")

    reason_codes = macro_reasons + technical_reasons + flow_reasons + [risk_reason] + hard_vetoes
    top_reason = "、".join((macro_reasons + technical_reasons + [risk_reason])[:3]) or "关键因子未形成一致确认"

    silver_ma20 = silver.sma(20)
    silver_ma50 = silver.sma(50)
    silver_dist_ma50 = None if silver_ma50 in (None, 0) else silver.latest_value / silver_ma50 - 1

    snapshot = {
        "as_of": as_of.isoformat(),
        "generated_at": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "data_status": data_status,
        "regime": regime,
        "score": score,
        "score_change_1d": None,
        "macro_score": macro_score,
        "flow_score": flow_score,
        "technical_score": technical_score,
        "risk_score": risk_score,
        "active_weight": active_weight,
        "hard_veto": bool(hard_vetoes),
        "hard_vetoes": hard_vetoes,
        "core_target_weight": args.core_target_weight,
        "tactical_target_weight": round(target, 4),
        "current_tactical_weight": round(current_tactical, 4),
        "proposed_trade_weight": round(proposed_trade_weight, 4),
        "action": action,
        "execution_action": "MANUAL_CHECK_REQUIRED",
        "execution_blocked": False,
        "reason_codes": reason_codes,
        "data_ages": data_ages,
        "sources": {
            "gold_price": gold.source,
            "silver_price": silver.source,
            **{name: series.source for name, series in fred.items()},
        },
        "metrics": {
            "gold_close": gold.latest_value,
            "gold_date": gold.latest_date.isoformat(),
            "ma20": ma20,
            "ma50": ma50,
            "ma100": ma100,
            "weekly_ma10": weekly_ma10,
            "distance_to_ma50": distance_to_ma50,
            "real_yield_10y": fred["real_yield_10y"].latest_value,
            "real_yield_20d_bp": real_20,
            "real_yield_10d_bp": real_10,
            "usd_broad": fred["usd_broad"].latest_value,
            "usd_20d_return": usd_20,
            "usd_10d_return": usd_10,
            "policy_20d_bp": policy_20,
            "breakeven_20d_bp": breakeven_20,
            "vix_10d_change": vix_10,
            "hy_oas_20d_bp": hy_20,
            "silver_close": silver.latest_value,
            "silver_date": silver.latest_date.isoformat(),
            "silver_ma20": silver_ma20,
            "silver_ma50": silver_ma50,
            "silver_distance_to_ma50": silver_dist_ma50,
        },
    }

    if history:
        last_score = history[-1].get("score")
        if isinstance(last_score, int):
            snapshot["score_change_1d"] = score - last_score

    report = render_report(now, snapshot, top_reason, missing_confirmations)
    return snapshot, report


def data_row(label: str, latest: str, d5: str, d10: str, d20: str, note: str) -> str:
    return f"| {label} | {latest} | {d5} | {d10} | {d20} | {note} |"


def render_report(now: datetime, snapshot: dict, top_reason: str, missing_confirmations: list[str]) -> str:
    metrics = snapshot["metrics"]
    data_status = snapshot["data_status"]
    narrative = "PARTIALLY_CONFIRMED" if data_status == "DEGRADED" else ("CONFIRMED_BY_FACTORS" if data_status == "PASS" else "NARRATIVE_ONLY")

    rows = [
        data_row("Gold close", fmt(metrics["gold_close"]), "见历史库", "见历史库", "见历史库", f"{snapshot['sources']['gold_price']} / {metrics['gold_date']}"),
        data_row("10Y real yield", fmt(metrics["real_yield_10y"], 2, "%"), "N/A", fmt(metrics["real_yield_10d_bp"], 1, "bp"), fmt(metrics["real_yield_20d_bp"], 1, "bp"), "FRED DFII10"),
        data_row("Broad USD", fmt(metrics["usd_broad"]), "N/A", fmt_pct(metrics["usd_10d_return"]), fmt_pct(metrics["usd_20d_return"]), "FRED DTWEXBGS"),
        data_row("2Y yield / policy proxy", "FRED DGS2", "N/A", "N/A", fmt(metrics["policy_20d_bp"], 1, "bp"), "隐含政策利率未接入，使用 2Y 降级代理"),
        data_row("10Y breakeven", "FRED T10YIE", "N/A", "N/A", fmt(metrics["breakeven_20d_bp"], 1, "bp"), "通胀预期代理"),
        data_row("GLD holdings", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "MVP 未接入官方持仓"),
        data_row("VIX", "FRED VIXCLS", "N/A", fmt(metrics["vix_10d_change"], 2), "N/A", "风险偏好代理"),
        data_row("HY OAS", "FRED BAMLH0A0HYM2", "N/A", "N/A", fmt(metrics["hy_oas_20d_bp"], 1, "bp"), "信用风险代理"),
    ]

    missing_text = "\n".join(f"  {i + 1}. {item}" for i, item in enumerate(missing_confirmations)) or "  1. 暂无额外确认条件缺口。"
    hard_veto_text = ", ".join(snapshot["hard_vetoes"]) if snapshot["hard_vetoes"] else "无"
    flow_note = "资金流模块未确认，GLD 持仓、COT、WGC ETF 流量未纳入分子和分母。"
    invalidator = "10Y 实际利率重新上行且美元 20 日转强，或金价跌破 MA50/MA100 并伴随资金流走弱。"

    return f"""# 黄金白银日度监控｜{now:%Y-%m-%d %H:%M}｜Asia/Shanghai

## 结论
- Regime: {snapshot['regime']}
- Score: {snapshot['score']} / 100（昨日：{snapshot['score_change_1d'] if snapshot['score_change_1d'] is not None else 'N/A'}）
- MACRO_ACTION: {snapshot['action']}
- EXECUTION_ACTION: {snapshot['execution_action']}
- 建议战术仓目标：{snapshot['tactical_target_weight'] * 100:.2f}%
- 当前战术仓：{snapshot['current_tactical_weight'] * 100:.2f}%
- 建议变动：{snapshot['proposed_trade_weight'] * 100:+.2f}% 组合净值
- 战略底仓：HOLD_CORE（默认月度检查，目标 {snapshot['core_target_weight'] * 100:.2f}%）

## 一句话原因
主导变化的是 {top_reason}。{flow_note}

## 四模块评分
| 模块 | 得分 | 上限 | 状态 | 核心变化 |
|---|---:|---:|---|---|
| 宏观转向 | {snapshot['macro_score']} | 40 | {'支持' if snapshot['macro_score'] >= 25 else '中性/压制'} | 10Y 实际利率 20D {fmt(metrics['real_yield_20d_bp'], 1, 'bp')}；美元 20D {fmt_pct(metrics['usd_20d_return'])} |
| 资金流确认 | {snapshot['flow_score']} | 0 | 未确认 | GLD/COT/WGC 未接入，按规则缩放总分 |
| 价格结构 | {snapshot['technical_score']} | 30 | {'支持' if snapshot['technical_score'] >= 20 else '中性/压制'} | Gold vs MA20 {fmt(metrics['ma20'])} / MA50 {fmt(metrics['ma50'])} / MA100 {fmt(metrics['ma100'])} |
| 风险环境 | {snapshot['risk_score']} | 10 | {'支持' if snapshot['risk_score'] > 0 else '中性/压制'} | VIX 10D {fmt(metrics['vix_10d_change'])}；HY OAS 20D {fmt(metrics['hy_oas_20d_bp'], 1, 'bp')} |

## 关键数据
| 指标 | 最新值 | 5D | 10D | 20D | 解释 |
|---|---:|---:|---:|---:|---|
{chr(10).join(rows)}

## 白银伴随观察
- Silver close: {fmt(metrics['silver_close'])}（{snapshot['sources']['silver_price']} / {metrics['silver_date']}）
- Silver MA20 / MA50: {fmt(metrics['silver_ma20'])} / {fmt(metrics['silver_ma50'])}
- Silver distance to MA50: {fmt_pct(metrics['silver_distance_to_ma50'])}
- 解释：白银当前仅作为贵金属风险偏好与工业属性的伴随观察，不覆盖黄金战术状态机。

## 触发器
- 已触发：
  - [ ] 加仓触发
  - [ ] 分批减仓触发
  - [{'x' if snapshot['hard_veto'] else ' '}] 硬性否决：{hard_veto_text}
  - [ ] 过热止盈
- 尚未满足的确认条件：
{missing_text}

## 未来 7 天事件风险
- FOMC、CPI、PCE、非农、国债拍卖和财政事件需要人工复核；当前 MVP 未接入官方日历。
- 事件日历只提高审查等级，不因日历本身自动交易。

## Agent 审计摘要
- 数据质量：{data_status}
- 叙事标签：{narrative}
- 数据年龄：price {snapshot['data_ages']['price_days']} 天；real yield {snapshot['data_ages']['real_yield_days']} 天；USD {snapshot['data_ages']['usd_days']} 天。
- 反证：{invalidator}

来源：{', '.join(sorted(set(snapshot['sources'].values())))}。非投资建议；不自动下单。
"""


def write_outputs(snapshot: dict, report: str, now: datetime) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"gold-silver-regime-report-{now:%Y-%m-%d-%H%M}.md"
    if report_path.exists():
        suffix = 1
        while True:
            candidate = REPORT_DIR / f"gold-silver-regime-report-{now:%Y-%m-%d-%H%M}-rerun{suffix}.md"
            if not candidate.exists():
                report_path = candidate
                break
            suffix += 1
    snapshot_path = DATA_DIR / "gold_snapshot.json"
    report_path.write_text(report, encoding="utf-8")
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    append_history(DATA_DIR / "gold_history.jsonl", snapshot)
    return report_path, snapshot_path


def failure_snapshot_and_report(now: datetime, error: Exception) -> tuple[dict, str]:
    message = str(error)
    snapshot = {
        "as_of": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "data_status": "FAIL",
        "regime": "DATA_INVALID",
        "score": 0,
        "score_change_1d": None,
        "macro_score": 0,
        "flow_score": 0,
        "technical_score": 0,
        "risk_score": 0,
        "active_weight": 0,
        "hard_veto": False,
        "hard_vetoes": [],
        "core_target_weight": 0.05,
        "tactical_target_weight": 0.0,
        "current_tactical_weight": 0.0,
        "proposed_trade_weight": 0.0,
        "action": "NO_TRADE",
        "execution_action": "DATA_INVALID_NO_EXECUTION",
        "execution_blocked": True,
        "reason_codes": ["CRITICAL_DATA_FETCH_FAILED"],
        "data_ages": {
            "price_days": None,
            "real_yield_days": None,
            "usd_days": None,
            "gld_holdings_days": None,
            "cot_days": None,
            "global_etf_flow_days": None,
        },
        "sources": {
            "planned": "FRED official CSV endpoints and Stooq public daily CSV",
        },
        "error": message,
    }
    report = f"""# 黄金白银日度监控｜{now:%Y-%m-%d %H:%M}｜Asia/Shanghai

## 结论
- Regime: DATA_INVALID
- Score: 0 / 100
- MACRO_ACTION: NO_TRADE
- EXECUTION_ACTION: DATA_INVALID_NO_EXECUTION
- 建议战术仓目标：0.00%
- 当前战术仓：0.00%
- 建议变动：+0.00% 组合净值
- 战略底仓：HOLD_CORE（数据无效时不做日线调整）

## 一句话原因
关键数据源未能在超时窗口内返回，系统按规则进入 `DATA_INVALID / NO_TRADE`，不生成加仓、减仓或执行建议。

## 四模块评分
| 模块 | 得分 | 上限 | 状态 | 核心变化 |
|---|---:|---:|---|---|
| 宏观转向 | 0 | 0 | DATA_INVALID | 关键宏观或价格数据未通过 |
| 资金流确认 | 0 | 0 | UNAVAILABLE | 未进入慢变量拉取 |
| 价格结构 | 0 | 0 | DATA_INVALID | 价格数据未完成确认 |
| 风险环境 | 0 | 0 | DATA_INVALID | 风险数据未完成确认 |

## 数据质量审计
- 数据质量：FAIL
- 失败原因：{message}
- 计划数据源：FRED official CSV endpoints；Stooq public daily CSV。
- 系统行为：不静默失败；保存本报告和机器快照；等待下次自动化或手动重跑。

## 反证与后续
- 一旦关键数据恢复，重新运行脚本并按完整状态机评分。
- 数据恢复前，不应把新闻、金价短期波动或主观判断替代量化规则。

非投资建议；不自动下单。
"""
    return snapshot, report


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate gold/silver regime report")
    parser.add_argument("--run-at", help="ISO timestamp for deterministic scheduled/manual reruns")
    parser.add_argument("--current-tactical-weight", type=float, default=0.0)
    parser.add_argument("--core-target-weight", type=float, default=0.05)
    parser.add_argument("--tactical-cap-weight", type=float, default=0.05)
    parser.add_argument("--max-single-day-change-weight", type=float, default=0.0167)
    parser.add_argument("--max-critical-age-days", type=int, default=5)
    parser.add_argument("--print-paths", action="store_true")
    parser.add_argument("--strict", action="store_true", help="return non-zero when critical data fetch fails")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    now = datetime.now(TZ) if args.run_at is None else datetime.fromisoformat(args.run_at).astimezone(TZ)
    try:
        snapshot, report = compute(args)
    except (urllib.error.URLError, TimeoutError, socket.timeout, RuntimeError, ValueError) as exc:
        if args.strict:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        snapshot, report = failure_snapshot_and_report(now, exc)
    report_path, snapshot_path = write_outputs(snapshot, report, now)
    if args.print_paths:
        print(f"REPORT={report_path}")
        print(f"SNAPSHOT={snapshot_path}")
    else:
        print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
