#!/usr/bin/env python3
"""Build a daily breadth and crowding monitor for the U.S. semiconductor sector."""

from __future__ import annotations

import argparse
import json
import math
import statistics
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
ETF_TICKERS = ("SOXX", "SMH", "XSD", "SOXL", "SOXS")


@dataclass
class Series:
    ticker: str
    dates: list[date]
    closes: list[float]

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
    adjusted = payload.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose") or payload["indicators"]["quote"][0]["close"]
    points = [(datetime.fromtimestamp(ts, timezone.utc).date(), float(value)) for ts, value in zip(payload.get("timestamp", []), adjusted) if value is not None and math.isfinite(float(value))]
    now = datetime.now(NY_TZ)
    if points and now.weekday() < 5 and 570 <= now.hour * 60 + now.minute < 975 and points[-1][0] == now.date(): points.pop()
    return Series(ticker, [x[0] for x in points], [x[1] for x in points])


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
    if not valid: return {"equal": None, "weighted": None, "coverage": 0, "top5": None, "rest": None}
    top5 = valid[:5]
    rest = valid[5:]
    return {
        "equal": 100 * sum(x["above"] for x in valid) / len(valid),
        "weighted": 100 * sum(x["weight_pct"] * x["above"] for x in valid) / valid_weight,
        "coverage": 100 * valid_weight / total_weight,
        "top5": 100 * sum(x["above"] for x in top5) / len(top5) if top5 else None,
        "rest": 100 * sum(x["above"] for x in rest) / len(rest) if rest else None,
    }


def etf_metrics(series: Series) -> dict:
    high = max(series.closes[-252:])
    return {"close": series.last, "date": series.last_date, "ma5": ma(series.closes, 5), "ma50": ma(series.closes, 50), "ma200": ma(series.closes, 200), "return20": ret(series.closes, 20), "drawdown": 100 * (series.last / high - 1)}


def ratio_return(left: Series, right: Series, days: int = 20):
    points = {d: v for d, v in zip(right.dates, right.closes)}
    ratios = [value / points[d] for d, value in zip(left.dates, left.closes) if d in points and points[d]]
    return ret(ratios, days)


def classify(metrics: dict) -> tuple[str, list[str], str]:
    b20, b50, b200 = (metrics["breadth"][n] for n in (20, 50, 200))
    soxx, smh = metrics["etf"]["SOXX"], metrics["etf"]["SMH"]
    leverage = metrics["soxl_soxx_20d"]
    if min(b20["coverage"], b50["coverage"], b200["coverage"]) < 75:
        return "数据不足 / 不作极端判断", [], "成分股价格覆盖不足 75% 权重。"
    if any(stale(metrics["etf"][ticker]["date"], 3, metrics["today"]) for ticker in ETF_TICKERS):
        return "数据不足 / 不作极端判断", [], "行业 ETF 观测超过新鲜度窗口。"
    near_high = soxx["drawdown"] >= -3 and smh["drawdown"] >= -3
    trend_up = near_high and soxx["close"] > soxx["ma50"] > 0 and soxx["close"] > soxx["ma200"] and smh["close"] > smh["ma50"] and smh["close"] > smh["ma200"]
    saturated = b20["equal"] >= 85 and b50["equal"] >= 80
    leadership_gap = b50["top5"] - b50["rest"] if b50["top5"] is not None and b50["rest"] is not None else 0
    fragile = trend_up and b20["equal"] <= 60 and leadership_gap >= 25
    leveraged_long = leverage is not None and leverage >= 12
    stress = soxx["drawdown"] <= -15 or soxx["close"] < soxx["ma200"]
    washed_out = b20["equal"] <= 15 and b50["equal"] <= 25
    leveraged_unwind = leverage is not None and leverage <= -12
    evidence = [f"SOXX 距 252 日高点 {soxx['drawdown']:.2f}% / SMH {smh['drawdown']:.2f}%", f"等权宽度：20 日 {b20['equal']:.1f}%｜50 日 {b50['equal']:.1f}%｜200 日 {b200['equal']:.1f}%", f"权重宽度：20 日 {b20['weighted']:.1f}%｜50 日 {b50['weighted']:.1f}%｜200 日 {b200['weighted']:.1f}%", f"50 日龙头差（前五大 - 其余）{leadership_gap:+.1f}pct", f"SOXL/SOXX 20 日变化 {fmt(leverage, '%')}（杠杆情绪代理）"]
    if trend_up and (saturated or fragile) and leveraged_long:
        return "半导体顶部人性极端（警戒）", evidence, "停止追高，检查行业集中度和杠杆；这不是做空指令。"
    if stress and washed_out and leveraged_unwind:
        if soxx["close"] >= soxx["ma5"]: return "半导体底部人性极端（确认改善）", evidence, "极端压力开始修复；仅按既定长期计划分批恢复风险预算。"
        return "半导体底部人性极端（观察）", evidence, "建立观察清单，等待 SOXX 重回 5 日线；不是立即抄底。"
    if trend_up and (saturated or fragile or leveraged_long): return "半导体偏顶部 / 待确认", evidence, "行业出现拥挤或集中证据，降低追高意愿。"
    if stress and (washed_out or leveraged_unwind): return "半导体偏底部 / 待确认", evidence, "承认压力但不接飞刀，等待价格修复。"
    return "半导体未进入人性极端", evidence, "维持既定风险预算，不把单日行业波动解释成转折。"


def serial(value):
    if isinstance(value, dict): return {key: serial(item) for key, item in value.items()}
    return value.isoformat() if isinstance(value, date) else value


def build_report(metrics: dict, state: str, evidence: list[str], action: str, errors: list[str]) -> str:
    today = metrics["today"]
    b = metrics.get("breadth", {})
    lines = [f"# 半导体人性极端监测｜{today}", "", "## 今日结论", "", f"**{state}**", "", action, "", "## 证据", ""] + [f"- {item}" for item in evidence]
    lines += ["", "## 宽度与覆盖", "", "| 周期 | 等权宽度 | 权重宽度 | 覆盖权重 |", "|---|---:|---:|---:|"]
    for days in (20, 50, 200): lines.append(f"| {days} 日 | {fmt(b[days]['equal'], '%')} | {fmt(b[days]['weighted'], '%')} | {fmt(b[days]['coverage'], '%')} |" if days in b else f"| {days} 日 | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |")
    if metrics.get("etf"):
        lines += ["", "## 行业 ETF", "", "| 指标 | 收盘 | 20 日变化 | 252 日回撤 | 观测日 |", "|---|---:|---:|---:|---|"]
        for ticker in ("SOXX", "SMH", "XSD", "SOXL", "SOXS"):
            item = metrics["etf"].get(ticker, {}); lines.append(f"| {ticker} | {fmt(item.get('close'))} | {fmt(item.get('return20'), '%')} | {fmt(item.get('drawdown'), '%')} | {item.get('date', '—')} |")
    lines += ["", "## 风险纪律", "", "- 20/50 日宽度极高并不保证立即见顶；它只说明参与度普遍扩散。", "- 指数创新高、等权宽度走弱且龙头差扩大，才是集中度风险证据。", "- SOXL/SOXX 是杠杆偏好代理，不是资金流或散户调查。", "", "## 数据质量与来源", "", "- SOXX 成分与权重：iShares 官方 Holdings > All 产品数据；当日持仓快照已保存。", "- 价格：Yahoo Finance chart JSON。"]
    if errors: lines += ["", "### 采集错误", ""] + [f"- {item}" for item in errors]
    return "\n".join(lines) + "\n"


def run() -> int:
    today, errors, holdings, prices = datetime.now(TZ).date(), [], [], {}
    try: holdings = fetch_holdings()
    except Exception as exc: errors.append(f"SOXX holdings: {type(exc).__name__}: {exc}")
    if holdings:
        prices, price_errors = fetch_prices([x["ticker"] for x in holdings] + list(ETF_TICKERS)); errors.extend(price_errors)
    metrics = {"today": today, "breadth": {}, "etf": {}}
    try:
        metrics["breadth"] = {days: breadth(holdings, prices, days) for days in (20, 50, 200)}
        metrics["etf"] = {ticker: etf_metrics(prices[ticker]) for ticker in ETF_TICKERS}
        metrics["soxl_soxx_20d"] = ratio_return(prices["SOXL"], prices["SOXX"])
        state, evidence, action = classify(metrics)
    except Exception as exc:
        errors.append(f"calculation: {type(exc).__name__}: {exc}"); state, evidence, action = "数据不足 / 不作极端判断", [], "关键来源或计算不可用，不能识别极端。"
    body = build_report(metrics, state, evidence, action, errors)
    for folder in (ROOT / "reports", ROOT / "data"): folder.mkdir(exist_ok=True)
    (ROOT / "reports" / f"semiconductor-human-extremes-{today}.md").write_text(body, encoding="utf-8")
    (ROOT / "data" / f"soxx-universe-{today}.json").write_text(json.dumps(holdings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    snapshot = {"report_date": str(today), "state": state, "metrics": serial(metrics), "errors": errors}
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
    etf = {ticker: {"close": 100., "date": date(2026, 7, 14), "ma5": 98., "ma50": 95., "ma200": 90., "return20": 4., "drawdown": -2.} for ticker in ETF_TICKERS}
    broad = {n: {"equal": 90., "weighted": 90., "coverage": 100., "top5": 100., "rest": 85.} for n in (20, 50, 200)}
    assert classify({"today": today, "breadth": broad, "etf": etf, "soxl_soxx_20d": 15.})[0] == "半导体顶部人性极端（警戒）"
    broad[20]["coverage"] = 50.
    assert classify({"today": today, "breadth": broad, "etf": etf, "soxl_soxx_20d": 15.})[0] == "数据不足 / 不作极端判断"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test: self_test(); print("self-test: ok")
    else: raise SystemExit(run())
