#!/usr/bin/env python3
"""Create a fail-closed daily U.S. market human-extremes monitor."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
TZ, NY_TZ = ZoneInfo("Asia/Shanghai"), ZoneInfo("America/New_York")
UA = "Mozilla/5.0 market-human-extremes-monitor/1.0"
AAII = "https://www.aaii.com/sentimentsurvey/sent_results"
NAAIM = "https://naaim.org/programs/naaim-exposure-index/"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d&events=history"


@dataclass
class Series:
    key: str
    dates: list[date]
    values: list[float]

    @property
    def last(self): return self.values[-1] if self.values else None
    @property
    def last_date(self): return self.dates[-1] if self.dates else None


def fetch(url: str, accept: str = "text/html,*/*") -> str:
    error = None
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            error = exc
            if attempt == 0: time.sleep(.4)
    raise RuntimeError(error)


def fetch_price(symbol: str) -> Series:
    payload = json.loads(fetch(YAHOO.format(symbol=urllib.parse.quote(symbol, safe="")), "application/json"))["chart"]["result"][0]
    adjusted = payload.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose") or payload["indicators"]["quote"][0]["close"]
    points = [(datetime.fromtimestamp(ts, timezone.utc).date(), float(value)) for ts, value in zip(payload.get("timestamp", []), adjusted) if value is not None and math.isfinite(float(value))]
    now = datetime.now(NY_TZ)
    if points and now.weekday() < 5 and 570 <= now.hour * 60 + now.minute < 975 and points[-1][0] == now.date(): points.pop()
    return Series(symbol, [x[0] for x in points], [x[1] for x in points])


def fetch_aaii(today: date) -> dict:
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fetch(AAII)))
    months = {name: n for n, name in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
    matches = re.findall(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%", plain)
    rows = []
    for month, day, bull, neutral, bear in matches:
        year = today.year - 1 if months[month] > today.month + 1 else today.year
        rows.append((date(year, months[month], int(day)), float(bull), float(neutral), float(bear)))
    if not rows: raise RuntimeError("AAII historical table not found")
    obs, bullish, neutral, bearish = max(rows)
    return {"date": obs, "bullish": bullish, "neutral": neutral, "bearish": bearish, "source": AAII}


def fetch_naaim() -> dict:
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fetch(NAAIM)))
    rows = [(datetime.strptime(d, "%m/%d/%Y").date(), float(v)) for d, v in re.findall(r"\b(\d{2}/\d{2}/\d{4})\s+(-?\d+(?:\.\d+)?)\s+-?\d", plain)]
    if not rows: raise RuntimeError("NAAIM table not found")
    obs, exposure = max(rows)
    return {"date": obs, "exposure": exposure, "source": NAAIM}


def ma(values: list[float], days: int): return statistics.fmean(values[-days:]) if len(values) >= days else None
def change(values: list[float], days: int): return (values[-1] / values[-days - 1] - 1) * 100 if len(values) > days and values[-days - 1] else None
def is_stale(obs: date | None, days: int, today: date): return obs is None or (today - obs).days > days
def fmt(value, suffix=""): return "UNAVAILABLE" if value is None else f"{value:.2f}{suffix}"


def price_metrics(prices: dict[str, Series]) -> dict:
    output = {}
    for symbol in ("SPY", "QQQ", "IWM"):
        series = prices[symbol]
        high = max(series.values[-252:])
        output[symbol] = {"close": series.last, "date": series.last_date, "ma5": ma(series.values, 5), "ma50": ma(series.values, 50), "ma200": ma(series.values, 200), "change20": change(series.values, 20), "drawdown": (series.last / high - 1) * 100}
    output["VIX"] = {"close": prices["^VIX"].last, "date": prices["^VIX"].last_date}
    return output


def decide(aaii, naaim, market, today: date):
    if not aaii or not naaim or not market: return "数据不足 / 不作极端判断", [], "关键来源不可用，不能识别极端。"
    freshness = [(aaii["date"], 10), (naaim["date"], 10), (market["VIX"]["date"], 3)] + [(market[s]["date"], 3) for s in ("SPY", "QQQ", "IWM")]
    if any(is_stale(d, max_days, today) for d, max_days in freshness): return "数据不足 / 不作极端判断", [], "关键观测超过新鲜度窗口。"
    spread = aaii["bullish"] - aaii["bearish"]
    retail_top, retail_bottom = aaii["bullish"] >= 45 and spread >= 10, aaii["bearish"] >= 45 and spread <= -10
    manager_top, manager_bottom = naaim["exposure"] >= 85, naaim["exposure"] <= 30
    healthy = [market[s]["close"] >= market[s]["ma50"] >= 0 and market[s]["close"] >= market[s]["ma200"] for s in ("SPY", "QQQ", "IWM")]
    stressed = [market[s]["change20"] is not None and market[s]["change20"] <= -7 or market[s]["close"] < market[s]["ma200"] for s in ("SPY", "QQQ", "IWM")]
    price_top, price_bottom = sum(healthy) >= 2 and market["SPY"]["drawdown"] >= -5, sum(stressed) >= 2
    vix_top, vix_bottom = market["VIX"]["close"] <= 18, market["VIX"]["close"] >= 20
    evidence = [f"AAII 多空差 {spread:+.1f}pct", f"NAAIM 曝险 {naaim['exposure']:.2f}", f"SPY 20 日变化 {fmt(market['SPY']['change20'], '%')}，距 252 日高点 {fmt(market['SPY']['drawdown'], '%')}", f"VIX {market['VIX']['close']:.2f}", "宽度：TradingView INDEX:* 待人工/授权源核验（不纳入自动极端触发）。"]
    top_count, bottom_count = sum((retail_top, manager_top, price_top, vix_top)), sum((retail_bottom, manager_bottom, price_bottom, vix_bottom))
    if retail_top and manager_top and price_top and vix_top: return "顶部人性极端（警戒）", evidence, "停止追高，按既定再平衡纪律检查集中度与杠杆；这不是做空信号。"
    if retail_bottom and manager_bottom and price_bottom and vix_bottom:
        if market["SPY"]["ma5"] and market["SPY"]["close"] >= market["SPY"]["ma5"]: return "底部人性极端（确认改善）", evidence, "短期价格已修复；仅在既定长期计划允许时分批恢复风险预算。"
        return "底部人性极端（观察）", evidence, "建立观察清单，等待 SPY 重回 5 日线；不是立即抄底。"
    # Price strength plus a low VIX is normal in a bull market, not “human extreme”.
    # Require at least one crowd-positioning layer for a partial extreme as well.
    if top_count >= 2 and bottom_count == 0 and (retail_top or manager_top): return "偏顶部 / 待确认", evidence, "降低追高意愿，等待其余层级确认。"
    if bottom_count >= 2 and top_count == 0 and (retail_bottom or manager_bottom): return "偏底部 / 待确认", evidence, "承认压力但不接飞刀，等待价格确认。"
    if top_count and bottom_count: return "信号分歧", evidence, "调查、仓位或价格没有同向，不强行给方向结论。"
    return "未进入人性极端", evidence, "维持既定风险预算，不把正常波动解释成转折。"


def serial(value):
    if isinstance(value, dict): return {k: serial(v) for k, v in value.items()}
    return value.isoformat() if isinstance(value, date) else value


def report(today, aaii, naaim, market, state, evidence, action, errors):
    lines = [f"# 美股人性极端监测｜{today}", "", "## 今日结论", "", f"**{state}**", "", action, "", "## 五层证据", ""] + [f"- {x}" for x in evidence]
    lines += ["", "| 指标 | 最新值 | 观测日 |", "|---|---:|---|"]
    lines += [f"| AAII 看多/中性/看空 | {fmt(aaii['bullish'], '%')} / {fmt(aaii['neutral'], '%')} / {fmt(aaii['bearish'], '%')} | {aaii['date']} |" if aaii else "| AAII | UNAVAILABLE | — |", f"| NAAIM 权益曝险 | {fmt(naaim['exposure'])} | {naaim['date']} |" if naaim else "| NAAIM | UNAVAILABLE | — |"]
    for s in ("SPY", "QQQ", "IWM"):
        lines.append(f"| {s} 收盘 / 20 日变化 / 252 日回撤 | {fmt(market[s]['close'])} / {fmt(market[s]['change20'], '%')} / {fmt(market[s]['drawdown'], '%')} | {market[s]['date']} |" if market else f"| {s} | UNAVAILABLE | — |")
    lines.append(f"| VIX | {fmt(market['VIX']['close'])} | {market['VIX']['date']} |" if market else "| VIX | UNAVAILABLE | — |")
    lines += ["", "## 普通投资者的纪律", "", "- 顶部警戒：不追高、不加杠杆；不是做空指令。", "- 底部观察：不因恐慌单独抄底，等待价格修复。", "- 宽度：若图中 20/50 日宽度在三个市场同时 ≥85 或 ≤15，或指数创新高而宽度未创新高，人工标记为额外警示。", "", "## 数据质量与来源", "", f"- AAII：{AAII if aaii else 'UNAVAILABLE'}", f"- NAAIM：{NAAIM if naaim else 'UNAVAILABLE'}", "- 价格：Yahoo Finance chart JSON；宽度：TradingView INDEX:*，当前仅人工核验。"]
    if errors: lines += ["", "### 采集错误", ""] + [f"- {x}" for x in errors]
    return "\n".join(lines) + "\n"


def run():
    today, errors = datetime.now(TZ).date(), []
    aaii = naaim = market = None
    try: aaii = fetch_aaii(today)
    except Exception as exc: errors.append(f"AAII: {type(exc).__name__}: {exc}")
    try: naaim = fetch_naaim()
    except Exception as exc: errors.append(f"NAAIM: {type(exc).__name__}: {exc}")
    try: market = price_metrics({s: fetch_price(s) for s in ("SPY", "QQQ", "IWM", "^VIX")})
    except Exception as exc: errors.append(f"市场价格: {type(exc).__name__}: {exc}")
    state, evidence, action = decide(aaii, naaim, market, today)
    body = report(today, aaii, naaim, market, state, evidence, action, errors)
    (ROOT / "reports").mkdir(exist_ok=True); (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "reports" / f"market-human-extremes-{today}.md").write_text(body, encoding="utf-8")
    snapshot = {"report_date": str(today), "state": state, "aaii": serial(aaii), "naaim": serial(naaim), "market": serial(market), "errors": errors}
    (ROOT / "data" / "latest_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (ROOT / "data" / "history.jsonl").open("a", encoding="utf-8") as handle: handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    print(body); return 0 if not errors else 1


def self_test():
    today = date(2026, 7, 15)
    aaii = {"date": date(2026, 7, 9), "bullish": 50., "neutral": 20., "bearish": 30., "source": "test"}; naaim = {"date": date(2026, 7, 8), "exposure": 90., "source": "test"}
    line = {"close": 100., "date": date(2026, 7, 14), "ma5": 99., "ma50": 95., "ma200": 90., "change20": 3., "drawdown": -2.}
    market = {"SPY": line, "QQQ": line.copy(), "IWM": line.copy(), "VIX": {"close": 15., "date": date(2026, 7, 14)}}
    assert decide(aaii, naaim, market, today)[0] == "顶部人性极端（警戒）"
    market["VIX"]["date"] = date(2026, 7, 1); assert decide(aaii, naaim, market, today)[0] == "数据不足 / 不作极端判断"


if __name__ == "__main__":
    args = argparse.ArgumentParser(); args.add_argument("--self-test", action="store_true"); parsed = args.parse_args()
    if parsed.self_test: self_test(); print("self-test: ok")
    else: raise SystemExit(run())
