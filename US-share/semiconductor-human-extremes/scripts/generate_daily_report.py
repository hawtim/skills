#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a daily breadth and crowding monitor for the U.S. semiconductor sector."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
TZ, NY_TZ = ZoneInfo("Asia/Shanghai"), ZoneInfo("America/New_York")
UA = "Mozilla/5.0 semiconductor-human-extremes-monitor/1.0"
# iShares moved the former CSV endpoint to this public product-data API.  The
# component's own web application uses the same request to populate its
# "Holdings > All" table.
HOLDINGS_URL = (
    "https://www.ishares.com/varnish-api/blk-one01-product-data/product-data/api/v2/get-product-data?"
    "appSubType=ISHARES&appType=PRODUCT_PAGE&component=holdings.all&locale=en_US&"
    "portfolioId=239705&targetSite=us-ishares&userType=individual&excludeContent=true&"
    "asOfDate=&includeConfig=true"
)
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d&events=history"
SECTOR_TICKERS = ("SOXX", "SMH", "XSD", "SOXL", "SOXS", "DRAM")
# TradingView's NASDAQ:SOX is the Philadelphia Semiconductor Index.  Yahoo's
# chart endpoint exposes the same price benchmark under ^SOX.
PRICE_TICKERS = SECTOR_TICKERS + ("^SOX",)
# SMH's benchmark is the MVIS US Listed Semiconductor 25 Index.  VanEck's
# public web table is cookie-gated in unattended runs, so maintain this liquid
# 25-name reference basket for equal-weight *breadth* only.  It is never used
# as an official SMH weight calculation; refresh it whenever the provider
# releases a revised constituent file.
SMH_BREADTH_TICKERS = (
    "NVDA", "TSM", "AVGO", "ASML", "AMD", "MU", "AMAT", "LRCX", "KLAC",
    "INTC", "QCOM", "ADI", "MRVL", "MCHP", "NXPI", "ON", "TXN", "MPWR",
    "TER", "SWKS", "QRVO", "ARM", "GFS", "ENTG", "UMC",
)
FUTU_OPTIONS_SCRIPT = ROOT / "scripts" / "fetch_futu_option_sentiment.py"
BROAD_SNAPSHOT = ROOT.parent / "market-human-extremes" / "data" / "latest_snapshot.json"


@dataclass
class Series:
    ticker: str
    dates: list[date]
    closes: list[float]
    volumes: list[float | None]

    @property
    def last(self): return self.closes[-1] if self.closes else None
    @property
    def last_date(self): return self.dates[-1] if self.dates else None


def fetch_text(url: str, accept: str = "text/plain,*/*") -> str:
    error = None
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8-sig", errors="replace")
        except Exception as exc:
            error = exc
            if attempt == 0: time.sleep(.4)
    raise RuntimeError(error)


def fetch_holdings() -> list[dict]:
    payload = json.loads(fetch_text(HOLDINGS_URL, "application/json"))
    try:
        points = payload["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"]["dataPointsByNameMap"]
        tickers = points["ticker"]["value"]
        weights = points["holdingPercent"]["value"]
        asset_classes = points["assetClass"]["value"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("unexpected SOXX official holdings response") from exc
    if not (len(tickers) == len(weights) == len(asset_classes)):
        raise RuntimeError("SOXX official holdings fields have inconsistent lengths")
    holdings = []
    for raw, weight, asset_class in zip(tickers, weights, asset_classes):
        try: value = float(weight)
        except (TypeError, ValueError): continue
        # Breadth is defined over listed equity constituents; cash, collateral,
        # and derivatives should not dilute it or masquerade as missing prices.
        if str(asset_class).lower() == "equity" and raw and value > 0:
            holdings.append({"ticker": str(raw).replace(".", "-"), "weight_pct": value})
    if len(holdings) < 15: raise RuntimeError(f"unexpected SOXX holdings count: {len(holdings)}")
    return sorted(holdings, key=lambda item: item["weight_pct"], reverse=True)


def fetch_price(ticker: str) -> Series:
    url = YAHOO.format(symbol=urllib.parse.quote(ticker, safe=""))
    payload = json.loads(fetch_text(url, "application/json"))["chart"]["result"][0]
    quote = payload["indicators"]["quote"][0]
    adjusted = payload.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose") or quote["close"]
    raw_volume = quote.get("volume") or [None] * len(adjusted)
    points = [(datetime.fromtimestamp(ts, timezone.utc).date(), float(value), float(volume) if volume is not None and math.isfinite(float(volume)) else None) for ts, value, volume in zip(payload.get("timestamp", []), adjusted, raw_volume) if value is not None and math.isfinite(float(value))]
    now = datetime.now(NY_TZ)
    if points and now.weekday() < 5 and 570 <= now.hour * 60 + now.minute < 975 and points[-1][0] == now.date(): points.pop()
    return Series(ticker, [x[0] for x in points], [x[1] for x in points], [x[2] for x in points])


def fetch_prices(tickers: list[str]) -> tuple[dict[str, Series], list[str]]:
    data, errors = {}, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_price, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try: data[ticker] = future.result()
            except Exception as exc: errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
    return data, errors


def ma(values: list[float], days: int): return statistics.fmean(values[-days:]) if len(values) >= days else None
def ret(values: list[float], days: int): return (values[-1] / values[-days - 1] - 1) * 100 if len(values) > days and values[-days - 1] else None
def stale(observation: date | None, days: int, today: date): return observation is None or (today - observation).days > days
def fmt(value, suffix=""): return "UNAVAILABLE" if value is None else f"{value:.2f}{suffix}"


def above(series: Series, days: int) -> bool | None:
    average = ma(series.closes, days)
    return None if series.last is None or average is None else series.last > average


def breadth(holdings: list[dict], prices: dict[str, Series], days: int) -> dict:
    valid = []
    for holding in holdings:
        series = prices.get(holding["ticker"])
        signal = above(series, days) if series else None
        if signal is not None: valid.append({**holding, "above": signal})
    total_weight = sum(x["weight_pct"] for x in holdings)
    valid_weight = sum(x["weight_pct"] for x in valid)
    if not valid:
        return {"equal": None, "weighted": None, "coverage": 0, "top5": None, "rest": None, "above_count": 0, "valid_count": 0}
    top5 = valid[:5]
    rest = valid[5:]
    return {
        "equal": 100 * sum(x["above"] for x in valid) / len(valid),
        "weighted": 100 * sum(x["weight_pct"] * x["above"] for x in valid) / valid_weight,
        "coverage": 100 * valid_weight / total_weight,
        "top5": 100 * sum(x["above"] for x in top5) / len(top5) if top5 else None,
        "rest": 100 * sum(x["above"] for x in rest) / len(rest) if rest else None,
        "above_count": sum(x["above"] for x in valid),
        "valid_count": len(valid),
    }


def smh_breadth(prices: dict[str, Series]) -> dict:
    """Compute an independent, equal-weight SMH reference-basket breadth."""
    holdings = [{"ticker": ticker, "weight_pct": 100 / len(SMH_BREADTH_TICKERS)} for ticker in SMH_BREADTH_TICKERS]
    return {days: breadth(holdings, prices, days) for days in (20, 50, 200)}


def dram_state(series: Series) -> str:
    metric = etf_metrics(series)
    below_ma200 = metric["ma200"] is not None and metric["close"] < metric["ma200"]
    if metric["drawdown"] <= -15 and (below_ma200 or len(series.closes) < 200):
        return "存储子行业压力 / 偏底部"
    if metric["drawdown"] >= -3 and metric["return20"] >= 15:
        return "存储子行业偏热"
    return "存储子行业中性 / 跟踪分化"


def etf_metrics(series: Series) -> dict:
    high = max(series.closes[-252:])
    return {"close": series.last, "date": series.last_date, "ma5": ma(series.closes, 5), "ma50": ma(series.closes, 50), "ma200": ma(series.closes, 200), "return20": ret(series.closes, 20), "drawdown": 100 * (series.last / high - 1)}


def ratio_return(left: Series, right: Series, days: int = 20):
    points = {d: v for d, v in zip(right.dates, right.closes)}
    ratios = [value / points[d] for d, value in zip(left.dates, left.closes) if d in points and points[d]]
    return ret(ratios, days)


def relative_volume(series: Series, days: int = 20):
    valid = [value for value in series.volumes if value is not None and value > 0]
    if not series.volumes or series.volumes[-1] is None or len(valid) < days + 1:
        return None
    baseline = statistics.fmean(valid[-days - 1:-1])
    return series.volumes[-1] / baseline if baseline else None


def json_from_command(command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "local options query failed").strip()[-500:])
    for line in reversed(result.stdout.splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict): return value
        except json.JSONDecodeError:
            continue
    raise RuntimeError("local options query returned no JSON")


def fetch_option_sentiment() -> dict:
    if not FUTU_OPTIONS_SCRIPT.exists(): raise RuntimeError("Futu option helper is not installed")
    return json_from_command([sys.executable, str(FUTU_OPTIONS_SCRIPT)])


def fetch_broad_confirmation(today: date) -> dict:
    """Read the broad monitor as an optional confirmation layer, never a gate."""
    unavailable = {"available": False, "reason": "大盘人性监测快照不可用"}
    if not BROAD_SNAPSHOT.exists(): return unavailable
    try:
        snapshot = json.loads(BROAD_SNAPSHOT.read_text(encoding="utf-8"))
        observed = date.fromisoformat(snapshot["report_date"])
        if (today - observed).days > 7: return {**unavailable, "reason": "大盘人性监测快照过期"}
        aaii, naaim, market, breadth = snapshot["aaii"], snapshot["naaim"], snapshot["market"], snapshot["breadth"]
        aaii_fear = aaii["bearish"] >= 45 and aaii["bearish"] - aaii["bullish"] >= 10
        naaim_low = naaim["exposure"] <= 30
        vix_high = market["VIX"]["close"] >= 20
        breadth_values = [breadth[name]["20"]["value"] for name in ("S&P 500", "Nasdaq-100", "Russell 2000")]
        broad_washout = all(value <= 15 for value in breadth_values)
        return {"available": True, "date": str(observed), "aaii": aaii, "naaim": naaim, "vix": market["VIX"], "breadth20": breadth_values, "signals": {"AAII 极端看空": aaii_fear, "NAAIM 低仓位": naaim_low, "VIX 压力": vix_high, "大盘宽度洗出": broad_washout}, "score": sum((aaii_fear, naaim_low, vix_high, broad_washout))}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {**unavailable, "reason": f"大盘人性监测格式异常：{exc}"}


def previous_breadth(today: date) -> tuple[float | None, bool]:
    path = ROOT / "data" / "history.jsonl"
    if not path.exists(): return None, False
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("report_date") != str(today): rows.append(row)
        except json.JSONDecodeError:
            continue
    if not rows: return None, False
    recent = rows[-5:]
    values = []
    for row in recent:
        try: values.append(float(row["metrics"]["breadth"]["20"]["equal"]))
        except (KeyError, TypeError, ValueError): continue
    return (values[-1] if values else None), any(value <= 15 for value in values)


def breadth_zone(value, low: int, high: int) -> str:
    if value is None: return "数据不足"
    if value <= low: return f"底部极端区（≤{low}%）"
    if value >= high: return f"顶部极端区（≥{high}%）"
    return "中间区"


def gauge(value, low: int, high: int, slots: int = 24) -> str:
    """Show the current breadth reading against the two fixed extreme lines."""
    if value is None: return "UNAVAILABLE"
    chars = ["─"] * (slots + 1)
    chars[round(low / 100 * slots)] = "┊"
    chars[round(high / 100 * slots)] = "┊"
    chars[max(0, min(slots, round(value / 100 * slots)))] = "●"
    return "".join(chars)


def put_call(row: dict) -> float | None:
    calls, puts = row.get("call_volume"), row.get("put_volume")
    return puts / calls if calls and puts is not None else None


def flow_text(flow: dict | None) -> str:
    if not flow or not flow.get("is_final"): return "UNAVAILABLE（非完整收盘）"
    return f"{flow['net_flow'] / 1_000_000:+.2f}m"


def classify(metrics: dict) -> tuple[str, list[str], str]:
    b20, b50, b200 = (metrics["breadth"][n] for n in (20, 50, 200))
    soxx, smh, sox = metrics["etf"]["SOXX"], metrics["etf"]["SMH"], metrics["etf"]["^SOX"]
    leverage = metrics["soxl_soxx_20d"]
    if min(b20["coverage"], b50["coverage"], b200["coverage"]) < 75:
        return "数据不足 / 不作极端判断", [], "成分股价格覆盖不足 75% 权重。"
    if any(stale(metrics["etf"][ticker]["date"], 3, metrics["today"]) for ticker in PRICE_TICKERS):
        return "数据不足 / 不作极端判断", [], "行业指数或 ETF 观测超过新鲜度窗口。"
    near_high = soxx["drawdown"] >= -3 and smh["drawdown"] >= -3
    trend_up = near_high and soxx["close"] > soxx["ma50"] > 0 and soxx["close"] > soxx["ma200"] and smh["close"] > smh["ma50"] and smh["close"] > smh["ma200"] and sox["close"] > sox["ma50"] and sox["close"] > sox["ma200"]
    saturated = b20["equal"] >= 85 and b50["equal"] >= 80
    leadership_gap = b50["top5"] - b50["rest"] if b50["top5"] is not None and b50["rest"] is not None else 0
    fragile = trend_up and b20["equal"] <= 60 and leadership_gap >= 25
    leveraged_long = leverage is not None and leverage >= 12
    stress = soxx["drawdown"] <= -15 or soxx["close"] < soxx["ma200"]
    short_washout = b20["equal"] <= 15
    leveraged_unwind = leverage is not None and leverage <= -12
    options = metrics.get("option_sentiment", {}).get("underlyings", {})
    option_fear = all(
        options.get(ticker, {}).get("call_volume", 0) and options.get(ticker, {}).get("put_volume", 0)
        and options[ticker]["put_volume"] / options[ticker]["call_volume"] >= 1.25
        and (options[ticker].get("iv_rank") or 0) >= 80
        for ticker in ("SOXX", "SMH")
    )
    prior_b20, prior_washout = metrics.get("previous_b20"), metrics.get("prior_washout", False)
    breadth_rebound = prior_b20 is not None and b20["equal"] >= prior_b20 + 5
    price_repaired = soxx["close"] >= soxx["ma5"] and sox["close"] >= sox["ma5"]
    recent_washout = short_washout or prior_washout
    broad_score = metrics.get("broad_confirmation", {}).get("score") if metrics.get("broad_confirmation", {}).get("available") else None
    evidence = [f"SOXX 距 252 日高点 {soxx['drawdown']:.2f}% / SMH {smh['drawdown']:.2f}% / SOX {sox['drawdown']:.2f}%", f"等权宽度：20 日 {b20['equal']:.1f}%（{b20['above_count']}/{b20['valid_count']}）｜50 日 {b50['equal']:.1f}%（{b50['above_count']}/{b50['valid_count']}）｜200 日 {b200['equal']:.1f}%（{b200['above_count']}/{b200['valid_count']}）", f"权重宽度：20 日 {b20['weighted']:.1f}%｜50 日 {b50['weighted']:.1f}%｜200 日 {b200['weighted']:.1f}%", f"50 日龙头差（前五大 - 其余）{leadership_gap:+.1f}pct", f"SOXL/SOXX 20 日变化 {fmt(leverage, '%')}（杠杆情绪代理）", f"短线洗出：{'是' if short_washout else '否'}｜价格修复：{'是' if price_repaired else '否'}｜20 日宽度回升：{'是' if breadth_rebound else '否'}", f"大盘人性确认层：{'UNAVAILABLE' if broad_score is None else f'{broad_score}/4（仅加分，不是必要条件）'}"]
    if option_fear: evidence.append("行业期权恐慌确认：SOXX、SMH Put/Call 成交比 ≥1.25 且 IV Rank ≥80。")
    if trend_up and (saturated or fragile) and leveraged_long:
        return "半导体顶部人性极端（警戒）", evidence, "停止追高，检查行业集中度和杠杆；这不是做空指令。"
    if recent_washout and price_repaired and breadth_rebound:
        return "半导体短线底部（确认改善）", evidence, "价格已收回 5 日线且宽度开始回升；仅按既定长期计划分批恢复风险预算。"
    if stress and short_washout:
        if option_fear or leveraged_unwind:
            return "半导体短线洗出（底部候选，情绪确认）", evidence, "短线极端抛压已出现；等待 SOXX/SOX 重回 5 日线并见到宽度回升，再确认底部。"
        return "半导体短线洗出（底部候选）", evidence, "20 日宽度已进入极端区；等待 SOXX/SOX 重回 5 日线并见到宽度回升。"
    if trend_up and (saturated or fragile or leveraged_long): return "半导体偏顶部 / 待确认", evidence, "行业出现拥挤或集中证据，降低追高意愿。"
    if stress and leveraged_unwind: return "半导体偏底部 / 待确认", evidence, "承认压力但不接飞刀，等待价格修复。"
    return "半导体未进入人性极端", evidence, "维持既定风险预算，不把单日行业波动解释成转折。"


def serial(value):
    if isinstance(value, dict): return {key: serial(item) for key, item in value.items()}
    return value.isoformat() if isinstance(value, date) else value


def build_report(metrics: dict, state: str, evidence: list[str], action: str, errors: list[str]) -> str:
    today = metrics["today"]
    b = metrics.get("breadth", {})
    lines = [f"# 半导体人性极端监测｜{today}", "", "## 今日结论", "", f"**{state}**", "", action, "", "## 证据", ""] + [f"- {item}" for item in evidence]
    lines += ["", "## 宽度位置（像图中 15%／85% 的读法）", "", "这里的百分比是 **SOXX 成分股中站上对应均线的比例**，不是价格的历史百分位。`┊` 是极端线，`●` 是当前位置。", "", "| 周期 | 等权读数（股票数） | 位置图（0% → 100%） | 极端线 | 当前区间 | 权重宽度 | 覆盖权重 |", "|---|---:|---|---|---|---:|---:|"]
    bounds = {20: (15, 85), 50: (25, 80), 200: (15, 85)}
    for days in (20, 50, 200):
        if days not in b:
            lines.append(f"| {days} 日 | UNAVAILABLE | UNAVAILABLE | — | 数据不足 | UNAVAILABLE | UNAVAILABLE |")
            continue
        item, (low, high) = b[days], bounds[days]
        count = f"{item['above_count']}/{item['valid_count']}" if item['equal'] is not None else "—"
        lines.append(f"| {days} 日 | {fmt(item['equal'], '%')}（{count}） | `{gauge(item['equal'], low, high)}` | {low}% / {high}% | {breadth_zone(item['equal'], low, high)} | {fmt(item['weighted'], '%')} | {fmt(item['coverage'], '%')} |")
    smh_b = metrics.get("smh_breadth", {})
    lines += ["", "## SMH 独立宽度（龙头权重层）", "", "SMH 宽度与 SOXX 分开计算，用于识别“只有龙头在修复 / 抛压”。因 VanEck 持仓网页在无人值守环境受 cookie 限制，当前使用 25 只流动性龙头参考篮子的**等权**宽度；不伪装成 SMH 官方权重宽度。", "", "| 周期 | 等权读数（股票数） | 位置图 | 当前区间 |", "|---|---:|---|---|"]
    for days in (20, 50, 200):
        item, (low, high) = smh_b.get(days, {}), bounds[days]
        count = f"{item.get('above_count', '—')}/{item.get('valid_count', '—')}" if item else "—"
        lines.append(f"| {days} 日 | {fmt(item.get('equal'), '%')}（{count}） | `{gauge(item.get('equal'), low, high)}` | {breadth_zone(item.get('equal'), low, high)} |")
    lines += ["", "- 解读：SOXX 很弱而 SMH 较强，通常表示少数大市值龙头支撑；两者同步低于 15%，才是更广泛的行业洗出。"]
    lines += ["", "## 底部判断（两阶段）", "", "| 阶段 | 当前判断 | 升级条件 |", "|---|---|---|", f"| 短线洗出 | {'已触发：20 日等权宽度 ≤15%' if b.get(20, {}).get('equal') is not None and b[20]['equal'] <= 15 else '未触发'} | 仅说明普遍抛压，不等于价格已止跌 |", f"| 短线底部确认 | {'已确认' if '确认改善' in state else '尚未确认'} | SOXX 与 SOX 收回 5 日线，且 20 日宽度较上一日回升至少 5pct |"]
    options = metrics.get("option_sentiment", {}).get("underlyings", {})
    flow = metrics.get("option_sentiment", {}).get("soxx_capital_flow")
    lines += ["", "## 行业人性确认层（期权、杠杆与资金）", "", "期权层为行业专属加分项；大盘情绪层仅作背景确认。它们都不会替代宽度或价格确认。", "", "| 标的 | Put/Call 成交比 | IV Rank | 25-delta Put–Call IV 偏度 | 解读 |", "|---|---:|---:|---:|---|"]
    for ticker in ("SOXX", "SMH", "SOXL", "SOXS"):
        item = options.get(ticker, {})
        pcr = put_call(item)
        skew = item.get("skew_25d")
        interpretation = "—"
        if ticker in ("SOXX", "SMH") and pcr is not None and item.get("iv_rank") is not None:
            interpretation = "期权恐慌确认" if pcr >= 1.25 and item["iv_rank"] >= 80 else "未达恐慌阈值"
        lines.append(f"| {ticker} | {fmt(pcr)} | {fmt(item.get('iv_rank'))} | {fmt(skew, 'pt')} | {interpretation} |")
    lines += ["", "- SOXL 相对成交量：" + fmt(metrics.get("soxl_relative_volume"), "x") + "；SOXS 相对成交量：" + fmt(metrics.get("soxs_relative_volume"), "x") + "（均为当日成交量 / 自身过去 20 日均量）。", "- SOXX 收盘成交资金流代理：" + flow_text(flow) + "。仅在富途数据完整至美东 15:55 后采用；这不是 ETF 申赎资金流。"]
    broad = metrics.get("broad_confirmation", {})
    lines += ["", "## 大盘人性确认层（仅加分）", ""]
    if broad.get("available"):
        signals = broad["signals"]
        lines += [f"- 观测日期：{broad['date']}；确认分数：{broad['score']}/4。", f"- AAII 看空 {broad['aaii']['bearish']:.1f}% / 看多 {broad['aaii']['bullish']:.1f}%：{'极端' if signals['AAII 极端看空'] else '未极端'}。", f"- NAAIM 曝险 {broad['naaim']['exposure']:.2f}：{'低仓位' if signals['NAAIM 低仓位'] else '未低仓'}。", f"- VIX {broad['vix']['close']:.2f}：{'压力确认' if signals['VIX 压力'] else '未确认'}。", f"- 标普 / 纳指 / 罗素 20 日宽度：{' / '.join(f'{value:.1f}%' for value in broad['breadth20'])}：{'全面洗出' if signals['大盘宽度洗出'] else '未全面洗出'}。"]
    else:
        lines.append(f"- UNAVAILABLE：{broad.get('reason', '未知原因')}。这不会阻止行业独立判断。")
    if metrics.get("etf"):
        lines += ["", "## 行业指数与 ETF", "", "| 指标 | 收盘 | 20 日变化 | 252 日回撤 | 观测日 |", "|---|---:|---:|---:|---|"]
        for ticker in ("^SOX", "SOXX", "SMH", "XSD", "DRAM", "SOXL", "SOXS"):
            item = metrics["etf"].get(ticker, {}); lines.append(f"| {ticker} | {fmt(item.get('close'))} | {fmt(item.get('return20'), '%')} | {fmt(item.get('drawdown'), '%')} | {item.get('date', '—')} |")
        lines += ["", f"- **DRAM 存储子行业状态：{metrics.get('dram_state', 'UNAVAILABLE')}**。DRAM 是内存/存储主题卫星，不用来替代整体半导体宽度。"]
    lines += ["", "## 怎么读", "", "- 20 日宽度最敏感：低于 15% 表示短线普遍洗出，高于 85% 表示短线普遍拥挤。", "- 50 日宽度更看中期参与度：低于 25% / 高于 80% 才进入极端区。", "- 期权恐慌确认要求 SOXX、SMH 同时满足 Put/Call 成交比 ≥1.25、IV Rank ≥80；正偏度代表下行保护更贵。", "- 大盘 AAII/NAAIM/VIX/宽度仅是半导体底部的加分项，不是必要条件。", "", "## 风险纪律", "", "- 20 日宽度极低是短线洗出，不保证最低价已经出现。", "- 只有价格收回 5 日线且宽度回升，才从“底部候选”升级到“确认改善”。", "- SOXL/SOXX 与 SOXX 成交资金流代理均不是 ETF 申赎资金流，不得单独据此下单。", "", "## 数据质量与来源", "", "- SOXX 成分与权重：iShares 官方 Holdings > All 产品数据；当日持仓快照已保存。", "- NASDAQ:SOX（费城半导体指数）作为行业价格趋势锚；脚本以 `^SOX` 获取日线。", "- 价格与成交量：Yahoo Finance chart JSON。期权与成交资金流代理：本地富途 OpenD（可选；不可用时不参与判断）。"]
    if errors: lines += ["", "### 采集错误", ""] + [f"- {item}" for item in errors]
    return "\n".join(lines) + "\n"


def run() -> int:
    today, errors, warnings, holdings, prices = datetime.now(TZ).date(), [], [], [], {}
    try: holdings = fetch_holdings()
    except Exception as exc: errors.append(f"SOXX holdings: {type(exc).__name__}: {exc}")
    if holdings:
        prices, price_errors = fetch_prices([x["ticker"] for x in holdings] + list(SMH_BREADTH_TICKERS) + list(PRICE_TICKERS)); errors.extend(price_errors)
    metrics = {"today": today, "breadth": {}, "etf": {}}
    try:
        metrics["breadth"] = {days: breadth(holdings, prices, days) for days in (20, 50, 200)}
        metrics["smh_breadth"] = smh_breadth(prices)
        metrics["etf"] = {ticker: etf_metrics(prices[ticker]) for ticker in PRICE_TICKERS}
        metrics["dram_state"] = dram_state(prices["DRAM"])
        metrics["soxl_soxx_20d"] = ratio_return(prices["SOXL"], prices["SOXX"])
        metrics["soxl_relative_volume"] = relative_volume(prices["SOXL"])
        metrics["soxs_relative_volume"] = relative_volume(prices["SOXS"])
        metrics["previous_b20"], metrics["prior_washout"] = previous_breadth(today)
        metrics["broad_confirmation"] = fetch_broad_confirmation(today)
        try: metrics["option_sentiment"] = fetch_option_sentiment()
        except Exception as exc:
            warnings.append(f"期权/成交资金流代理未接入：{type(exc).__name__}: {exc}")
            metrics["option_sentiment"] = {}
        state, evidence, action = classify(metrics)
    except Exception as exc:
        errors.append(f"calculation: {type(exc).__name__}: {exc}"); state, evidence, action = "数据不足 / 不作极端判断", [], "关键来源或计算不可用，不能识别极端。"
    body = build_report(metrics, state, evidence, action, errors + warnings)
    for folder in (ROOT / "reports", ROOT / "data"): folder.mkdir(exist_ok=True)
    (ROOT / "reports" / f"semiconductor-human-extremes-{today}.md").write_text(body, encoding="utf-8")
    (ROOT / "data" / f"soxx-universe-{today}.json").write_text(json.dumps(holdings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    snapshot = {"report_date": str(today), "state": state, "metrics": serial(metrics), "errors": errors, "warnings": warnings}
    (ROOT / "data" / "latest_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # A manual retry on the same day should correct that day's observation, not
    # create two contradictory daily records.
    history_path = ROOT / "data" / "history.jsonl"
    previous = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if item.get("report_date") != str(today): previous.append(item)
            except json.JSONDecodeError:
                continue
    history_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in previous + [snapshot]), encoding="utf-8")
    print(body); return 0 if not errors else 1


def self_test():
    today = date(2026, 7, 15)
    etf = {ticker: {"close": 100., "date": date(2026, 7, 14), "ma5": 98., "ma50": 95., "ma200": 90., "return20": 4., "drawdown": -2.} for ticker in PRICE_TICKERS}
    broad = {n: {"equal": 90., "weighted": 90., "coverage": 100., "top5": 100., "rest": 85., "above_count": 27, "valid_count": 30} for n in (20, 50, 200)}
    assert classify({"today": today, "breadth": broad, "etf": etf, "soxl_soxx_20d": 15.})[0] == "半导体顶部人性极端（警戒）"
    broad[20]["coverage"] = 50.
    assert classify({"today": today, "breadth": broad, "etf": etf, "soxl_soxx_20d": 15.})[0] == "数据不足 / 不作极端判断"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test: self_test(); print("self-test: ok")
    else: raise SystemExit(run())
