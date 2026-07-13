#!/usr/bin/env python3
"""Generate a reproducible global semiconductor regime report."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 global-semiconductor-regime-monitor/1.0"
RULE_VERSION = "1.0.0"
SWING_WINDOW = 3
ATR_WINDOW = 14
HORIZONS = (1, 3, 5, 10)


@dataclass(frozen=True)
class Instrument:
    symbol: str
    label: str
    region: str
    role: str
    weight: float = 1.0


INSTRUMENTS = [
    Instrument("SOXX", "iShares Semiconductor ETF", "美国", "anchor", 2.0),
    Instrument("SMH", "VanEck Semiconductor ETF", "美国", "anchor", 2.0),
    Instrument("XSD", "SPDR S&P Semiconductor ETF", "美国", "anchor", 1.5),
    Instrument("QQQ", "Nasdaq 100 ETF", "美国", "macro", 1.0),
    Instrument("NVDA", "Nvidia", "美国", "leader"),
    Instrument("AVGO", "Broadcom", "美国", "leader"),
    Instrument("AMD", "AMD", "美国", "leader"),
    Instrument("MU", "Micron", "美国", "leader"),
    Instrument("ASML", "ASML ADR", "美国", "leader"),
    Instrument("LRCX", "Lam Research", "美国", "leader"),
    Instrument("AMAT", "Applied Materials", "美国", "leader"),
    Instrument("KLAC", "KLA", "美国", "leader"),
    Instrument("TSM", "TSMC ADR", "美国", "leader"),
    Instrument("SKHY", "SK hynix ADR", "美国", "optional"),
    Instrument("091160.KS", "KODEX Semiconductor ETF", "韩国", "anchor", 2.0),
    Instrument("000660.KS", "SK hynix", "韩国", "leader", 1.5),
    Instrument("005930.KS", "Samsung Electronics", "韩国", "leader", 1.5),
    Instrument("^KS11", "KOSPI", "韩国", "macro", 0.5),
    Instrument("00891.TW", "Taiwan Semiconductor ETF", "台湾", "anchor", 2.0),
    Instrument("2330.TW", "TSMC", "台湾", "leader", 1.5),
    Instrument("2454.TW", "MediaTek", "台湾", "leader"),
    Instrument("^TWII", "Taiwan Weighted", "台湾", "macro", 0.5),
    Instrument("512480.SS", "Mainland Semiconductor ETF", "中国", "anchor", 2.0),
    Instrument("159995.SZ", "China Chip ETF", "中国", "anchor", 2.0),
    Instrument("588200.SS", "STAR Chip ETF", "中国", "anchor", 2.0),
    Instrument("000688.SS", "STAR 50", "中国", "macro", 0.5),
    Instrument("SPY", "S&P 500 ETF", "宏观", "macro"),
    Instrument("^VIX", "VIX", "宏观", "macro"),
    Instrument("^TNX", "10Y Treasury Yield Proxy", "宏观", "macro"),
    Instrument("CL=F", "WTI Crude Futures", "宏观", "macro"),
    Instrument("DX-Y.NYB", "Dollar Index", "宏观", "macro"),
    Instrument("HYG", "High Yield Bond ETF", "宏观", "macro"),
]

BY_SYMBOL = {item.symbol: item for item in INSTRUMENTS}
REGIONS = ("美国", "韩国", "台湾", "中国")
CRITICAL = ("SOXX", "SMH", "QQQ")


@dataclass
class PriceSeries:
    symbol: str
    label: str
    dates: list[str]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]
    source: str

    @property
    def last(self) -> float | None:
        return self.closes[-1] if self.closes else None

    @property
    def last_date(self) -> str | None:
        return self.dates[-1] if self.dates else None


@dataclass
class Structure:
    symbol: str
    as_of: str
    state: str
    high_relation: str
    low_relation: str
    close: float
    change_1d: float | None
    change_5d: float | None
    drawdown_60d: float | None
    atr: float | None
    ma20: float | None
    ma50: float | None
    above_ma20: bool | None
    trend_turn_steps: int
    extension_risk: bool
    readiness: float
    top_risk: float
    prior_reaction_high: float | None
    prior_reaction_low: float | None
    evidence: list[str]


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def average(values: Iterable[float | None], weights: Iterable[float] | None = None) -> float | None:
    vals = list(values)
    if weights is None:
        clean = [v for v in vals if v is not None]
        return statistics.fmean(clean) if clean else None
    pairs = [(v, w) for v, w in zip(vals, weights) if v is not None and w > 0]
    if not pairs:
        return None
    return sum(v * w for v, w in pairs) / sum(w for _, w in pairs)


def pct_change(values: list[float], periods: int) -> float | None:
    if len(values) <= periods or values[-periods - 1] == 0:
        return None
    return (values[-1] / values[-periods - 1] - 1) * 100


def mean_tail(values: list[float], periods: int) -> float | None:
    return statistics.fmean(values[-periods:]) if len(values) >= periods else None


def ema(values: list[float], periods: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (periods + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def true_ranges(series: PriceSeries) -> list[float]:
    result: list[float] = []
    for idx, (high, low) in enumerate(zip(series.highs, series.lows)):
        if idx == 0:
            result.append(high - low)
            continue
        previous = series.closes[idx - 1]
        result.append(max(high - low, abs(high - previous), abs(low - previous)))
    return result


def fetch_json(url: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except Exception as exc:  # public feeds occasionally throttle
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    assert last_error is not None
    raise last_error


def fetch_yahoo(item: Instrument) -> PriceSeries:
    encoded = urllib.parse.quote(item.symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=2y&interval=1d&events=history"
    payload = fetch_json(url)
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    result = chart["result"][0]
    timestamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    raw_closes = quote.get("close", [None] * len(timestamps))
    adjusted = result.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose")
    rows = []
    for idx, ts in enumerate(timestamps):
        raw_close = raw_closes[idx]
        raw_open = quote.get("open", [None] * len(timestamps))[idx]
        raw_high = quote.get("high", [None] * len(timestamps))[idx]
        raw_low = quote.get("low", [None] * len(timestamps))[idx]
        raw_volume = quote.get("volume", [None] * len(timestamps))[idx]
        values = (raw_open, raw_high, raw_low, raw_close)
        if any(v is None or not math.isfinite(float(v)) for v in values):
            continue
        # Apply the close adjustment factor to the full OHLC bar. This preserves
        # valid candle/swing geometry through ETF distributions and stock splits.
        factor = 1.0
        if adjusted and idx < len(adjusted) and adjusted[idx] is not None and raw_close:
            factor = float(adjusted[idx]) / float(raw_close)
        rows.append(
            (
                datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                float(raw_open) * factor, float(raw_high) * factor,
                float(raw_low) * factor, float(raw_close) * factor,
                0.0 if raw_volume is None else float(raw_volume),
            )
        )
    if len(rows) < 40:
        raise RuntimeError(f"insufficient history: {len(rows)} rows")
    return PriceSeries(
        item.symbol, item.label,
        [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows],
        [r[3] for r in rows], [r[4] for r in rows], [r[5] for r in rows],
        f"Yahoo chart JSON ({item.symbol})",
    )


def fetch_tencent(item: Instrument) -> PriceSeries:
    """Fetch forward-adjusted mainland daily bars from Tencent's public feed."""
    suffix = "sh" if item.symbol.endswith(".SS") else "sz"
    code = item.symbol.split(".", 1)[0]
    market_code = f"{suffix}{code}"
    param = urllib.parse.quote(f"{market_code},day,,,500,qfq", safe=",")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
    payload = fetch_json(url)
    node = payload.get("data", {}).get(market_code, {})
    rows = node.get("qfqday") or node.get("day") or []
    parsed = []
    for row in rows:
        if len(row) < 6:
            continue
        try:
            parsed.append(
                (row[0], float(row[1]), float(row[3]), float(row[4]),
                 float(row[2]), float(row[5]))
            )
        except (TypeError, ValueError):
            continue
    if len(parsed) < 40:
        raise RuntimeError(f"insufficient Tencent history: {len(parsed)} rows")
    return PriceSeries(
        item.symbol, item.label,
        [r[0] for r in parsed], [r[1] for r in parsed], [r[2] for r in parsed],
        [r[3] for r in parsed], [r[4] for r in parsed], [r[5] for r in parsed],
        f"Tencent qfq daily ({market_code})",
    )


def fetch_series(item: Instrument) -> PriceSeries:
    return fetch_tencent(item) if item.region == "中国" else fetch_yahoo(item)


def collect() -> tuple[dict[str, PriceSeries], list[str]]:
    data: dict[str, PriceSeries] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_series, item): item for item in INSTRUMENTS}
        for future in as_completed(futures):
            item = futures[future]
            try:
                data[item.symbol] = future.result()
            except Exception as exc:
                errors.append(f"{item.symbol}: {type(exc).__name__}: {exc}")
    return data, sorted(errors)


def swing_points(values: list[float], mode: str, window: int = SWING_WINDOW) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for idx in range(window, len(values) - window):
        segment = values[idx - window: idx + window + 1]
        value = values[idx]
        target = max(segment) if mode == "high" else min(segment)
        if value == target and segment.count(target) == 1:
            points.append((idx, value))
    return points


def resample_weekly(series: PriceSeries) -> PriceSeries:
    buckets: list[list[int]] = []
    keys: list[tuple[int, int]] = []
    for idx, raw_date in enumerate(series.dates):
        parsed = date.fromisoformat(raw_date)
        iso = parsed.isocalendar()
        key = (iso[0], iso[1])
        if not keys or keys[-1] != key:
            keys.append(key)
            buckets.append([])
        buckets[-1].append(idx)
    return PriceSeries(
        series.symbol, series.label,
        [series.dates[idxs[-1]] for idxs in buckets],
        [series.opens[idxs[0]] for idxs in buckets],
        [max(series.highs[i] for i in idxs) for idxs in buckets],
        [min(series.lows[i] for i in idxs) for idxs in buckets],
        [series.closes[idxs[-1]] for idxs in buckets],
        [sum(series.volumes[i] for i in idxs) for idxs in buckets],
        f"{series.source}; weekly resample",
    )


def relation(new: float, old: float, tolerance: float, high: bool) -> str:
    if new > old + tolerance:
        return "HH" if high else "HL"
    if new < old - tolerance:
        return "LH" if high else "LL"
    return "EH" if high else "EL"


def analyze(series: PriceSeries) -> Structure:
    atr_values = true_ranges(series)
    atr = mean_tail(atr_values, ATR_WINDOW)
    ma20 = mean_tail(series.closes, 20)
    ma50 = mean_tail(series.closes, 50)
    ema5, ema10, ema20 = (ema(series.closes, n) for n in (5, 10, 20))
    highs = swing_points(series.highs, "high")
    lows = swing_points(series.lows, "low")
    tolerance = (atr or max(series.last or 1, 1) * 0.01) * 0.35
    high_rel, low_rel = "NA", "NA"
    prior_high = prior_low = None
    if len(highs) >= 2:
        high_rel = relation(highs[-1][1], highs[-2][1], tolerance, True)
        prior_high = highs[-1][1]
    if len(lows) >= 2:
        low_rel = relation(lows[-1][1], lows[-2][1], tolerance, False)
        prior_low = lows[-1][1]

    close = series.closes[-1]
    evidence: list[str] = []
    state = "区间/冲突"
    broke_reaction_low = prior_low is not None and close < prior_low - tolerance * 0.25
    broke_reaction_high = prior_high is not None and close > prior_high + tolerance * 0.25
    if high_rel == "LH" and broke_reaction_low:
        state = "阶段顶部确认"
        evidence.append("反弹形成更低高点，收盘跌破最近反应低点")
    elif low_rel == "HL" and broke_reaction_high:
        state = "阶段底部确认"
        evidence.append("回踩形成更高低点，收盘突破最近反应高点")
    elif broke_reaction_low:
        state = "顶部观察"
        evidence.append("收盘已跌破最近反应低点，等待更低高点确认阶段顶部")
    elif broke_reaction_high:
        state = "底部观察"
        evidence.append("收盘已突破最近反应高点，等待更高低点确认阶段底部")
    elif high_rel == "HH" and low_rel == "HL":
        state = "上升趋势"
        evidence.append("更高高点与更高低点同时成立")
    elif high_rel == "LH" and low_rel == "LL":
        state = "下降趋势确认"
        evidence.append("更低高点与更低低点同时成立")
    elif high_rel == "LH":
        state = "顶部观察"
        evidence.append("反弹未能形成有意义的新高")
    elif low_rel == "HL":
        state = "底部观察"
        evidence.append("回踩暂未形成新低，但尚未突破反应高点")
    elif high_rel == "HH" and low_rel == "LL":
        state = "区间/冲突"
        evidence.append("高点上移但低点下移，波动扩张")

    if len(lows) >= 2 and series.lows[-1] < lows[-1][1] and close > lows[-1][1]:
        if state in ("下降趋势确认", "区间/冲突"):
            state = "底部观察"
        evidence.append("盘中新低被收盘收回，出现失败破底")

    steps = 0
    if ema5 and close > ema5[-1]:
        steps += 1
    if len(ema5) >= 4 and ema5[-1] > ema5[-4]:
        steps += 1
    if ema5 and ema10 and ema5[-1] > ema10[-1]:
        steps += 1
    if ema5 and ema10 and ema20 and ema5[-1] > ema10[-1] > ema20[-1]:
        steps += 1
    extension = bool(atr and ema20 and abs(close - ema20[-1]) > 3 * atr)
    if ma20 is not None:
        evidence.append("收盘位于20日均线上方" if close >= ma20 else "收盘位于20日均线下方")

    state_readiness = {
        "下降趋势确认": 18, "阶段顶部确认": 20, "顶部观察": 38,
        "区间/冲突": 46, "底部观察": 54, "阶段底部确认": 74, "上升趋势": 84,
    }[state]
    below_ma20_penalty = 12 if ma20 is not None and close < ma20 else 0
    below_ma50_penalty = 8 if ma50 is not None and close < ma50 else 0
    readiness = clamp(
        state_readiness + (steps - 2) * 4 - below_ma20_penalty
        - below_ma50_penalty - (8 if extension else 0)
    )
    state_top = {
        "阶段顶部确认": 90, "顶部观察": 72, "下降趋势确认": 65,
        "区间/冲突": 50, "底部观察": 34, "阶段底部确认": 22, "上升趋势": 20,
    }[state]
    top_risk = clamp(
        state_top + (8 if extension else 0)
        + (7 if ma20 is not None and close < ma20 else 0)
        + (5 if ma50 is not None and close < ma50 else 0)
    )
    drawdown = None
    if len(series.highs) >= 60:
        high60 = max(series.highs[-60:])
        drawdown = (close / high60 - 1) * 100
    return Structure(
        series.symbol, series.last_date or "", state, high_rel, low_rel, close,
        pct_change(series.closes, 1), pct_change(series.closes, 5), drawdown,
        atr, ma20, ma50, None if ma20 is None else close >= ma20,
        steps, extension, round(readiness, 1), round(top_risk, 1),
        prior_high, prior_low, evidence,
    )


def region_summary(structures: dict[str, Structure]) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for region in REGIONS:
        items = [item for item in INSTRUMENTS if item.region == region and item.symbol in structures]
        anchors = [item for item in items if item.role == "anchor"]
        scored = anchors or [item for item in items if item.role != "macro"]
        readiness = average([structures[x.symbol].readiness for x in scored], [x.weight for x in scored])
        top_risk = average([structures[x.symbol].top_risk for x in scored], [x.weight for x in scored])
        above = [structures[x.symbol].above_ma20 for x in items if structures[x.symbol].above_ma20 is not None and x.role != "macro"]
        breadth = 100 * sum(bool(x) for x in above) / len(above) if above else None
        states = [structures[x.symbol].state for x in scored]
        dominant = max(set(states), key=states.count) if states else "UNAVAILABLE"
        output[region] = {
            "readiness": None if readiness is None else round(readiness, 1),
            "top_risk": None if top_risk is None else round(top_risk, 1),
            "breadth": None if breadth is None else round(breadth, 1),
            "state": dominant,
            "symbols": [x.symbol for x in items],
        }
    return output


def macro_score(data: dict[str, PriceSeries], structures: dict[str, Structure]) -> tuple[float, list[str]]:
    score = 50.0
    notes: list[str] = []
    vix = data.get("^VIX")
    if vix and vix.last is not None:
        if vix.last >= 35:
            score -= 25; notes.append("VIX≥35，尾部风险高")
        elif vix.last >= 25:
            score -= 12; notes.append("VIX≥25，波动压制风险偏好")
        elif vix.last <= 18:
            score += 8; notes.append("VIX≤18，波动环境温和")
    qqq = structures.get("QQQ")
    if qqq and qqq.above_ma20:
        score += 10; notes.append("QQQ位于20日均线上方")
    elif qqq and qqq.above_ma20 is False:
        score -= 10; notes.append("QQQ位于20日均线下方")
    tnx = data.get("^TNX")
    if tnx and len(tnx.closes) > 5:
        change = tnx.closes[-1] - tnx.closes[-6]
        if change >= 2.5:
            score -= 8; notes.append("10Y收益率代理5日上升约25bp以上")
        elif change <= -2.5:
            score += 5; notes.append("10Y收益率代理5日回落约25bp以上")
    oil = data.get("CL=F")
    oil5 = pct_change(oil.closes, 5) if oil else None
    if oil5 is not None and oil5 >= 10:
        score -= 8; notes.append("油价5日上涨≥10%，通胀/供应链风险上升")
    dollar = data.get("DX-Y.NYB")
    dollar5 = pct_change(dollar.closes, 5) if dollar else None
    if dollar5 is not None and dollar5 >= 2:
        score -= 5; notes.append("美元5日上涨≥2%，全球流动性偏紧")
    hyg = structures.get("HYG")
    if hyg and hyg.above_ma20 is False:
        score -= 7; notes.append("HYG跌至20日均线下方，信用风险偏好转弱")
    return round(clamp(score), 1), notes or ["宏观代理未形成显著加分或扣分"]


def coverage(data: dict[str, PriceSeries]) -> tuple[float, list[str]]:
    critical_ok = sum(symbol in data for symbol in CRITICAL)
    asian_ok = 0
    missing = [symbol for symbol in CRITICAL if symbol not in data]
    for region in ("韩国", "台湾", "中国"):
        anchors = [x.symbol for x in INSTRUMENTS if x.region == region and x.role == "anchor"]
        if any(symbol in data for symbol in anchors):
            asian_ok += 1
        else:
            missing.append(f"{region} anchor")
    score = (critical_ok / len(CRITICAL) * 60) + (min(asian_ok, 2) / 2 * 40)
    return round(score, 1), missing


def compute(data: dict[str, PriceSeries]) -> dict:
    structures = {symbol: analyze(series) for symbol, series in data.items() if len(series.closes) >= 55}
    weekly_structures = {}
    for symbol, series in data.items():
        weekly = resample_weekly(series)
        if len(weekly.closes) >= 55:
            weekly_structures[symbol] = analyze(weekly)
    regions = region_summary(structures)
    macro, macro_notes = macro_score(data, structures)
    us_anchors = [structures[s] for s in ("SOXX", "SMH", "XSD") if s in structures]
    us_structure = average([x.readiness for x in us_anchors]) or 0
    us_top = average([x.top_risk for x in us_anchors]) or 100
    region_readiness = [regions[r]["readiness"] for r in REGIONS]
    region_top = [regions[r]["top_risk"] for r in REGIONS]
    cross = average(region_readiness) or 0
    cross_top = average(region_top) or 100
    breadth_values = [regions[r]["breadth"] for r in REGIONS]
    breadth = average(breadth_values) or 0
    readiness = clamp(0.35 * us_structure + 0.25 * cross + 0.20 * breadth + 0.20 * macro)
    top_risk = clamp(0.45 * us_top + 0.25 * cross_top + 0.15 * (100 - macro) + 0.15 * (100 - breadth))
    coverage_score, missing = coverage(data)

    supportive_regions = sum((regions[r]["readiness"] or 0) >= 60 for r in REGIONS)
    weak_regions = sum((regions[r]["top_risk"] or 0) >= 65 for r in REGIONS)
    dispersion_values = [x for x in region_readiness if x is not None]
    dispersion = statistics.pstdev(dispersion_values) if len(dispersion_values) >= 2 else None
    divergence = bool(dispersion is not None and dispersion >= 18)

    if coverage_score < 70:
        action = "DATA_INSUFFICIENT / NO_NEW_RISK"
    elif top_risk >= 70:
        action = "TOP_RISK / NO_ENTRY"
    elif readiness < 40:
        action = "NO_ENTRY"
    elif readiness < 60:
        action = "BOTTOM_WATCH"
    elif readiness < 75:
        action = "TACTICAL_ENTRY_READY"
    else:
        action = "TREND_ENTRY_READY"
    if any(x.state in ("阶段顶部确认", "下降趋势确认") for x in us_anchors) and action in ("TACTICAL_ENTRY_READY", "TREND_ENTRY_READY"):
        action = "BOTTOM_WATCH"
    weekly_us = [weekly_structures[s] for s in ("SOXX", "SMH", "XSD") if s in weekly_structures]
    if any(x.state in ("阶段顶部确认", "下降趋势确认") for x in weekly_us) and action in ("TACTICAL_ENTRY_READY", "TREND_ENTRY_READY"):
        action = "BOTTOM_WATCH"
    global_state = "区域背离" if divergence else (
        "阶段顶部/下降确认" if weak_regions >= 2 and us_top >= 65 else
        "阶段底部/上升确认" if supportive_regions >= 2 and us_structure >= 60 else
        "底部观察" if readiness >= 40 else "下降趋势"
    )
    return {
        "rule_version": RULE_VERSION,
        "coverage_pct": coverage_score,
        "missing_critical": missing,
        "readiness": round(readiness, 1),
        "top_risk": round(top_risk, 1),
        "action": action,
        "global_state": global_state,
        "us_structure_score": round(us_structure, 1),
        "cross_market_score": round(cross, 1),
        "breadth_score": round(breadth, 1),
        "macro_score": macro,
        "macro_notes": macro_notes,
        "supportive_regions": supportive_regions,
        "weak_regions": weak_regions,
        "regional_dispersion": None if dispersion is None else round(dispersion, 1),
        "regions": regions,
        "structures": {k: asdict(v) for k, v in structures.items()},
        "weekly_structures": {k: asdict(v) for k, v in weekly_structures.items()},
    }


def update_ledger(result: dict, data: dict[str, PriceSeries], now: datetime) -> tuple[dict, dict]:
    path = ROOT / "data" / "signal_ledger.json"
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        ledger = {"version": 1, "records": []}
    benchmark = data.get("SOXX")
    if not benchmark:
        return ledger, {"status": "benchmark unavailable", "groups": {}}
    index = {d: i for i, d in enumerate(benchmark.dates)}
    for record in ledger.get("records", []):
        start = index.get(record.get("benchmark_date"))
        if start is None:
            continue
        outcomes = record.setdefault("outcomes", {})
        base = benchmark.closes[start]
        for horizon in HORIZONS:
            end = start + horizon
            key = f"return_{horizon}d_pct"
            if key not in outcomes and end < len(benchmark.closes):
                outcomes[key] = round((benchmark.closes[end] / base - 1) * 100, 3)
        end10 = start + 10
        if end10 < len(benchmark.closes):
            path_values = benchmark.closes[start + 1: end10 + 1]
            outcomes["mfe_10d_pct"] = round((max(path_values) / base - 1) * 100, 3)
            outcomes["mae_10d_pct"] = round((min(path_values) / base - 1) * 100, 3)
            record["status"] = "matured"

    benchmark_date = benchmark.last_date or now.date().isoformat()
    if not any(x.get("benchmark_date") == benchmark_date for x in ledger.get("records", [])):
        ledger.setdefault("records", []).append({
            "report_date": now.date().isoformat(), "generated_at": now.isoformat(),
            "rule_version": RULE_VERSION, "signal": result["action"],
            "readiness": result["readiness"], "top_risk": result["top_risk"],
            "benchmark_symbol": "SOXX", "benchmark_date": benchmark_date,
            "benchmark_close": benchmark.last, "outcomes": {}, "status": "open",
        })
    ledger["records"] = ledger.get("records", [])[-500:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    groups: dict[str, dict] = {}
    for signal in sorted({x.get("signal") for x in ledger["records"] if x.get("signal")}):
        matured = [x for x in ledger["records"] if x.get("signal") == signal and "return_5d_pct" in x.get("outcomes", {})]
        if not matured:
            continue
        returns = [x["outcomes"]["return_5d_pct"] for x in matured]
        groups[signal] = {
            "sample_5d": len(returns), "avg_5d_pct": round(statistics.fmean(returns), 3),
            "positive_rate_5d_pct": round(sum(x > 0 for x in returns) / len(returns) * 100, 1),
        }
    summary = {"status": "ready", "groups": groups, "total_records": len(ledger["records"])}

    matured_all = [x for x in ledger["records"] if "return_5d_pct" in x.get("outcomes", {})]
    calibration = {
        "rule_version": RULE_VERSION, "updated_at": now.isoformat(),
        "production_thresholds": {"bottom_watch": 40, "tactical_entry": 60, "trend_entry": 75},
        "matured_5d_samples": len(matured_all), "shadow_threshold": None,
        "note": "Production thresholds stay fixed until at least 30 matured observations.",
    }
    if len(matured_all) >= 30:
        candidates = []
        for threshold in range(50, 81, 5):
            selected = [x for x in matured_all if x.get("readiness", 0) >= threshold]
            if len(selected) < 10:
                continue
            returns = [x["outcomes"]["return_5d_pct"] for x in selected]
            candidates.append((statistics.fmean(returns), threshold, len(selected)))
        if candidates:
            best = max(candidates)
            calibration["shadow_threshold"] = {"readiness": best[1], "sample": best[2], "avg_5d_pct": round(best[0], 3)}
            calibration["note"] = "Shadow result only; do not change production without multi-window validation."
    (ROOT / "data" / "calibration.json").write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
    return ledger, summary


def already_processed(benchmark_date: str | None) -> bool:
    """Return true when this completed SOXX session is already in the ledger."""
    if not benchmark_date:
        return False
    path = ROOT / "data" / "signal_ledger.json"
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any(record.get("benchmark_date") == benchmark_date for record in ledger.get("records", []))


def fmt(value: float | None, suffix: str = "", digits: int = 1) -> str:
    return "UNAVAILABLE" if value is None else f"{value:.{digits}f}{suffix}"


def render(result: dict, data: dict[str, PriceSeries], errors: list[str], evaluation: dict, now: datetime) -> str:
    action_text = {
        "DATA_INSUFFICIENT / NO_NEW_RISK": "关键数据覆盖不足；不新增风险，等待数据恢复。",
        "TOP_RISK / NO_ENTRY": "阶段顶部风险占优；暂停反弹交易，等待更高低点与突破确认。",
        "NO_ENTRY": "下降结构仍占优；不因单日反弹改变判断。",
        "BOTTOM_WATCH": "可能进入底部构筑，但尚未完成结构确认；只观察确认条件。",
        "TACTICAL_ENTRY_READY": "阶段底部初步确认；仅允许分批、短止损的战术风险预算。",
        "TREND_ENTRY_READY": "结构与跨市场确认较强；可按既定计划分批恢复趋势风险预算。",
    }[result["action"]]
    region_rows = ["| 区域 | 结构 | 准备度 | 顶部风险 | 20日线上广度 |", "|---|---|---:|---:|---:|"]
    for region in REGIONS:
        item = result["regions"][region]
        region_rows.append(f"| {region} | {item['state']} | {fmt(item['readiness'])} | {fmt(item['top_risk'])} | {fmt(item['breadth'], '%')} |")
    key_symbols = ("SOXX", "SMH", "XSD", "NVDA", "MU", "TSM", "091160.KS", "000660.KS", "00891.TW", "2330.TW", "512480.SS", "159995.SZ")
    structure_rows = ["| 标的 | 日期 | 日线结构 | 周线结构 | 1日 | 5日 | 60日回撤 | 均线步骤 |", "|---|---|---|---|---:|---:|---:|---:|"]
    for symbol in key_symbols:
        item = result["structures"].get(symbol)
        weekly = result["weekly_structures"].get(symbol, {})
        if not item:
            structure_rows.append(f"| {symbol} | — | UNAVAILABLE | UNAVAILABLE | — | — | — | — |")
            continue
        structure_rows.append(
            f"| {symbol} | {item['as_of']} | {item['state']} ({item['high_relation']}/{item['low_relation']}) | "
            f"{weekly.get('state', 'UNAVAILABLE')} | "
            f"{fmt(item['change_1d'], '%')} | {fmt(item['change_5d'], '%')} | {fmt(item['drawdown_60d'], '%')} | {item['trend_turn_steps']}/4 |"
        )
    soxx = result["structures"].get("SOXX", {})
    soxx_weekly = result["weekly_structures"].get("SOXX", {})
    high_trigger = fmt(soxx.get("prior_reaction_high"), digits=2)
    low_trigger = fmt(soxx.get("prior_reaction_low"), digits=2)
    evaluation_rows = ["| 历史信号 | 5日样本 | 平均收益 | 正收益率 |", "|---|---:|---:|---:|"]
    for signal, item in evaluation.get("groups", {}).items():
        evaluation_rows.append(f"| {signal} | {item['sample_5d']} | {fmt(item['avg_5d_pct'], '%', 2)} | {fmt(item['positive_rate_5d_pct'], '%')} |")
    if len(evaluation_rows) == 2:
        evaluation_rows.append("| 尚无成熟样本 | 0 | — | — |")
    sources = []
    today = now.date()
    for symbol in key_symbols:
        series = data.get(symbol)
        if not series:
            continue
        try:
            age = (today - date.fromisoformat(series.last_date or today.isoformat())).days
        except ValueError:
            age = -1
        sources.append(f"- {symbol}: {series.last_date}（自然日滞后 {age}）｜{series.source}")
    error_text = "\n".join(f"- {x}" for x in errors) if errors else "- 无抓取错误。"
    macro_text = "\n".join(f"- {x}" for x in result["macro_notes"])
    return f"""# 全球半导体盘后监控｜{now.date().isoformat()}

> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} Asia/Shanghai｜规则版本：{RULE_VERSION}｜最近完整市场时段｜非投资建议

## 今日结论

**当前结构：{result['global_state']}｜入场准备度 {result['readiness']}/100｜顶部风险度 {result['top_risk']}/100**

**今日许可：{result['action']}**

{action_text}

- 美国结构：{result['us_structure_score']}/100
- 跨市场确认：{result['cross_market_score']}/100
- 板块广度：{result['breadth_score']}/100
- 宏观环境：{result['macro_score']}/100
- 关键覆盖：{result['coverage_pct']}%；区域离散度：{fmt(result['regional_dispersion'])}

## LEI 顶部/底部结构

- SOXX 当前状态：**{soxx.get('state', 'UNAVAILABLE')}**；高低点关系：{soxx.get('high_relation', 'NA')}/{soxx.get('low_relation', 'NA')}。
- SOXX 周线状态：**{soxx_weekly.get('state', 'UNAVAILABLE')}**；周线高低点关系：{soxx_weekly.get('high_relation', 'NA')}/{soxx_weekly.get('low_relation', 'NA')}。
- 阶段底部确认位：收盘突破最近反应高点 **{high_trigger}**，同时保留更高低点。
- 阶段顶部确认位：形成更低高点后，收盘跌破最近反应低点 **{low_trigger}**。
- 当前均线转折步骤：{soxx.get('trend_turn_steps', 0)}/4；大幅乖离风险：{'是' if soxx.get('extension_risk') else '否'}。
- 规则纪律：反弹不创新高只构成顶部观察；跌破反应低点才确认。回踩不创新低只构成底部观察；突破反应高点才确认。

## 中美韩台联动

{chr(10).join(region_rows)}

- 支持性区域数量：{result['supportive_regions']}/4；弱势/顶部风险区域数量：{result['weak_regions']}/4。
- 若区域离散度高，优先按“区域背离”处理，不用单一市场替代全球确认。

## 核心指数与 ETF

{chr(10).join(structure_rows)}

## 宏观和基本面覆盖

{macro_text}

- 本脚本量化价格、趋势、广度和宏观代理；AI资本开支、HBM/DRAM/NAND价格、设备订单及公司指引由自动化任务使用一手来源覆盖。
- 单一公司新闻不能改变全球状态，除非同时改变结构、盈利预期、区域广度或宏观风险中的至少两项。

## 未来 1–3 个交易日剧本

- **升级**：SOXX/SMH形成更高低点并收盘突破反应高点，至少一个亚洲区域同步改善。
- **维持**：指数在反应高低点之间波动，区域确认不足；继续按当前许可处理。
- **降级**：SOXX形成更低高点后跌破反应低点，且韩国/台湾或中国至少一个区域同步转弱。
- **事件失效**：重大财报或宏观事件造成跳空时，等待收盘确认，不用盘中价格直接改写结构。

## 历史信号闭环

{chr(10).join(evaluation_rows)}

- 信号记录总数：{evaluation.get('total_records', 0)}。
- 每日自动回填SOXX后续1/3/5/10日收益以及10日MFE/MAE；不足30个成熟样本前不自动改变生产阈值。

## 升级、降级和失效条件

- `BOTTOM_WATCH → TACTICAL_ENTRY_READY`：更高低点、突破反应高点、美国锚点不再处于阶段顶部/下降确认。
- `TACTICAL_ENTRY_READY → TREND_ENTRY_READY`：至少两个区域确认，ETF广度改善，宏观不存在硬压力。
- 任一入场状态失效：重新跌破确认低点、区域广度再度恶化，或事件改变盈利/贴现率路径。

## 数据质量与来源

- 关键覆盖缺口：{', '.join(result['missing_critical']) if result['missing_critical'] else '无'}。
{chr(10).join(sources)}

抓取异常：
{error_text}
"""


def write_outputs(report: str, result: dict, data: dict[str, PriceSeries], errors: list[str], now: datetime) -> Path:
    report_dir, data_dir = ROOT / "reports", ROOT / "data"
    report_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"global-semiconductor-regime-{now.date().isoformat()}.md"
    if report_path.exists():
        stamp = now.strftime("%H%M")
        report_path = report_dir / f"global-semiconductor-regime-{now.date().isoformat()}-{stamp}.md"
    report_path.write_text(report, encoding="utf-8")
    snapshot = {
        "generated_at": now.isoformat(), "result": result, "errors": errors,
        "series": {symbol: {"label": s.label, "date": s.last_date, "close": s.last, "source": s.source} for symbol, s in data.items()},
    }
    (data_dir / "latest_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    with (data_dir / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return report_path


def fixture(symbol: str, direction: int = 1, count: int = 260) -> PriceSeries:
    closes = []
    for idx in range(count):
        base = 100 + direction * idx * 0.25
        closes.append(base + math.sin(idx / 3) * 1.6)
    return PriceSeries(
        symbol, symbol, [f"2025-{(idx // 28) % 12 + 1:02d}-{idx % 28 + 1:02d}" for idx in range(count)],
        [x - 0.2 for x in closes], [x + 0.8 for x in closes], [x - 0.8 for x in closes], closes,
        [1_000_000 + idx * 100 for idx in range(count)], "fixture",
    )


def self_test() -> None:
    up = analyze(fixture("UP", 1))
    down = analyze(fixture("DOWN", -1))
    assert up.high_relation == "HH" and up.low_relation == "HL", up
    assert down.high_relation == "LH" and down.low_relation == "LL", down
    data = {item.symbol: fixture(item.symbol, 1 if item.region != "宏观" else 0) for item in INSTRUMENTS if item.symbol != "^VIX"}
    data["^VIX"] = fixture("^VIX", 0)
    data["^VIX"].closes = [18 + math.sin(i / 4) for i in range(260)]
    result = compute(data)
    assert result["coverage_pct"] == 100.0
    assert 0 <= result["readiness"] <= 100
    assert result["action"] in {"NO_ENTRY", "BOTTOM_WATCH", "TACTICAL_ENTRY_READY", "TREND_ENTRY_READY", "TOP_RISK / NO_ENTRY"}
    print("self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--force", action="store_true",
        help="Generate again even if the latest completed SOXX session was already processed.",
    )
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    now = datetime.now(TZ)
    data, errors = collect()
    if not data:
        print("No data sources succeeded", file=sys.stderr)
        return 2
    benchmark_date = data.get("SOXX").last_date if data.get("SOXX") else None
    if not args.force and already_processed(benchmark_date):
        print(f"SKIP_NO_NEW_SESSION: SOXX {benchmark_date} already processed")
        return 0
    result = compute(data)
    _, evaluation = update_ledger(result, data, now)
    report = render(result, data, errors, evaluation, now)
    path = write_outputs(report, result, data, errors, now)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
