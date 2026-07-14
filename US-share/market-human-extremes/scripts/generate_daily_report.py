#!/usr/bin/env python3
"""Create a fail-closed daily U.S. market human-extremes monitor."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import secrets
import socket
import ssl
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
TV_HOST = "data.tradingview.com"
TV_BREADTH = {
    "S&P 500": {20: "INDEX:S5TW", 50: "INDEX:S5FI", 200: "INDEX:S5TH"},
    "Nasdaq-100": {20: "INDEX:NDTW", 50: "INDEX:NDFI", 200: "INDEX:NDTH"},
    "Russell 2000": {20: "INDEX:R2TW", 50: "INDEX:R2FI", 200: "INDEX:R2TH"},
}


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


def _read_exact(sock: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk: raise RuntimeError("TradingView websocket closed")
        data += chunk
    return data


def _ws_send(sock: socket.socket, payload: bytes, opcode: int = 1) -> None:
    """Send one masked client-to-server WebSocket frame without extra packages."""
    length, header = len(payload), bytearray([0x80 | opcode])
    if length < 126: header.append(0x80 | length)
    elif length < 65536: header.extend((0x80 | 126,)) or header.extend(length.to_bytes(2, "big"))
    else: header.extend((0x80 | 127,)) or header.extend(length.to_bytes(8, "big"))
    mask = os.urandom(4)
    header.extend(mask)
    sock.sendall(bytes(header) + bytes(value ^ mask[i % 4] for i, value in enumerate(payload)))


def _ws_recv(sock: socket.socket) -> bytes | None:
    first, second = _read_exact(sock, 2)
    opcode, length = first & 0x0F, second & 0x7F
    if length == 126: length = int.from_bytes(_read_exact(sock, 2), "big")
    elif length == 127: length = int.from_bytes(_read_exact(sock, 8), "big")
    masked = bool(second & 0x80)
    mask = _read_exact(sock, 4) if masked else None
    payload = _read_exact(sock, length)
    if mask: payload = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
    if opcode == 8: return None
    if opcode == 9:
        _ws_send(sock, payload, 10)
        return b""
    if opcode not in (0, 1): return b""
    return payload


def _tv_message(method: str, params: list) -> str:
    body = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(body)}~m~{body}"


def _tv_payloads(text: str):
    """Yield JSON packets from TradingView's length-prefixed text protocol."""
    cursor = 0
    while True:
        start = text.find("~m~", cursor)
        if start < 0: return
        match = re.match(r"~m~(\d+)~m~", text[start:])
        if not match: return
        end = start + match.end() + int(match.group(1))
        body = text[start + match.end():end]
        cursor = end
        try: yield json.loads(body)
        except json.JSONDecodeError: continue


def fetch_tradingview_breadth(today: date) -> dict:
    """Get the current public INDEX:* breadth quotes in a single quote session."""
    raw = [symbol for periods in TV_BREADTH.values() for symbol in periods.values()]
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET /socket.io/websocket?from=symbols/INDEX-S5TH/&date=" + datetime.now(timezone.utc).strftime("%Y_%m_%d-%H_%M") + " HTTP/1.1\r\n"
        f"Host: {TV_HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
        "Origin: https://www.tradingview.com\r\nUser-Agent: " + UA + "\r\n\r\n"
    ).encode("ascii")
    session = "qs_" + secrets.token_hex(12)
    tcp = socket.create_connection((TV_HOST, 443), timeout=15)
    sock = ssl.create_default_context().wrap_socket(tcp, server_hostname=TV_HOST)
    sock.settimeout(15)
    try:
        sock.sendall(request)
        headers = b""
        while b"\r\n\r\n" not in headers:
            headers += sock.recv(4096)
            if len(headers) > 65536: raise RuntimeError("TradingView websocket headers too large")
        if b" 101 " not in headers.split(b"\r\n", 1)[0]: raise RuntimeError("TradingView websocket upgrade rejected")
        commands = [
            ("set_auth_token", ["unauthorized_user_token"]),
            ("quote_create_session", [session]),
            ("quote_set_fields", [session, "lp", "lp_time", "short_name", "description"]),
        ] + [("quote_add_symbols", [session, symbol]) for symbol in raw]
        for method, params in commands: _ws_send(sock, _tv_message(method, params).encode("utf-8"))
        quotes, packets_seen, deadline = {}, [], time.monotonic() + 15
        while len(quotes) < len(raw) and time.monotonic() < deadline:
            frame = _ws_recv(sock)
            if frame is None: break
            packets_seen.append(frame.decode("utf-8", errors="replace")[:160])
            for packet in _tv_payloads(frame.decode("utf-8", errors="replace")):
                if packet.get("m") != "qsd" or len(packet.get("p", [])) < 2: continue
                item = packet["p"][1]
                symbol, values = item.get("n"), item.get("v", {})
                if symbol in raw and values.get("lp") is not None:
                    quote_time = values.get("lp_time")
                    quote_date = date.fromtimestamp(float(quote_time), timezone.utc) if quote_time else today
                    quotes[symbol] = {"value": float(values["lp"]), "date": quote_date}
        missing = sorted(set(raw) - set(quotes))
        if missing: raise RuntimeError("TradingView breadth quotes missing: " + ", ".join(missing) + "; packets=" + repr(packets_seen[:3]))
        return {market: {days: quotes[symbol] for days, symbol in periods.items()} for market, periods in TV_BREADTH.items()}
    finally:
        sock.close()


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


def breadth_zone(value: float | None, low: int = 15, high: int = 85) -> str:
    if value is None: return "数据不足"
    if value <= low: return f"底部极端区（≤{low}%）"
    if value >= high: return f"顶部极端区（≥{high}%）"
    return "中间区"


def gauge(value: float | None, low: int = 15, high: int = 85, slots: int = 24) -> str:
    if value is None: return "UNAVAILABLE"
    chars = ["─"] * (slots + 1)
    chars[round(low / 100 * slots)] = "┊"
    chars[round(high / 100 * slots)] = "┊"
    chars[max(0, min(slots, round(value / 100 * slots)))] = "●"
    return "".join(chars)


def price_metrics(prices: dict[str, Series]) -> dict:
    output = {}
    for symbol in ("SPY", "QQQ", "IWM"):
        series = prices[symbol]
        high = max(series.values[-252:])
        output[symbol] = {"close": series.last, "date": series.last_date, "ma5": ma(series.values, 5), "ma50": ma(series.values, 50), "ma200": ma(series.values, 200), "change20": change(series.values, 20), "drawdown": (series.last / high - 1) * 100}
    output["VIX"] = {"close": prices["^VIX"].last, "date": prices["^VIX"].last_date}
    return output


def decide(aaii, naaim, market, breadth, today: date):
    if not aaii or not naaim or not market or not breadth: return "数据不足 / 不作极端判断", [], "关键来源（含市场宽度）不可用，不能识别极端。"
    freshness = [(aaii["date"], 10), (naaim["date"], 10), (market["VIX"]["date"], 3)] + [(market[s]["date"], 3) for s in ("SPY", "QQQ", "IWM")]
    freshness += [(item["date"], 3) for periods in breadth.values() for item in periods.values()]
    if any(is_stale(d, max_days, today) for d, max_days in freshness): return "数据不足 / 不作极端判断", [], "关键观测超过新鲜度窗口。"
    spread = aaii["bullish"] - aaii["bearish"]
    retail_top, retail_bottom = aaii["bullish"] >= 45 and spread >= 10, aaii["bearish"] >= 45 and spread <= -10
    manager_top, manager_bottom = naaim["exposure"] >= 85, naaim["exposure"] <= 30
    healthy = [market[s]["close"] >= market[s]["ma50"] >= 0 and market[s]["close"] >= market[s]["ma200"] for s in ("SPY", "QQQ", "IWM")]
    stressed = [market[s]["change20"] is not None and market[s]["change20"] <= -7 or market[s]["close"] < market[s]["ma200"] for s in ("SPY", "QQQ", "IWM")]
    price_top, price_bottom = sum(healthy) >= 2 and market["SPY"]["drawdown"] >= -5, sum(stressed) >= 2
    vix_top, vix_bottom = market["VIX"]["close"] <= 18, market["VIX"]["close"] >= 20
    breadth_top = all(periods[20]["value"] >= 85 and periods[50]["value"] >= 80 for periods in breadth.values())
    breadth_bottom = all(periods[20]["value"] <= 15 and periods[50]["value"] <= 25 for periods in breadth.values())
    b_line = "｜".join(f"{name} 20/50/200={periods[20]['value']:.1f}/{periods[50]['value']:.1f}/{periods[200]['value']:.1f}%" for name, periods in breadth.items())
    evidence = [f"AAII 多空差 {spread:+.1f}pct", f"NAAIM 曝险 {naaim['exposure']:.2f}", f"SPY 20 日变化 {fmt(market['SPY']['change20'], '%')}，距 252 日高点 {fmt(market['SPY']['drawdown'], '%')}", f"VIX {market['VIX']['close']:.2f}", "宽度：" + b_line]
    top_count, bottom_count = sum((retail_top, manager_top, price_top, vix_top, breadth_top)), sum((retail_bottom, manager_bottom, price_bottom, vix_bottom, breadth_bottom))
    if retail_top and manager_top and price_top and vix_top and breadth_top: return "顶部人性极端（警戒）", evidence, "停止追高，按既定再平衡纪律检查集中度与杠杆；这不是做空信号。"
    if retail_bottom and manager_bottom and price_bottom and vix_bottom and breadth_bottom:
        if market["SPY"]["ma5"] and market["SPY"]["close"] >= market["SPY"]["ma5"]: return "底部人性极端（确认改善）", evidence, "短期价格已修复；仅在既定长期计划允许时分批恢复风险预算。"
        return "底部人性极端（观察）", evidence, "建立观察清单，等待 SPY 重回 5 日线；不是立即抄底。"
    # Price strength plus a low VIX is normal in a bull market, not “human extreme”.
    # Require at least one crowd-positioning layer for a partial extreme as well.
    if top_count >= 3 and bottom_count == 0 and (retail_top or manager_top): return "偏顶部 / 待确认", evidence, "降低追高意愿，等待其余层级确认。"
    if bottom_count >= 3 and top_count == 0 and (retail_bottom or manager_bottom): return "偏底部 / 待确认", evidence, "承认压力但不接飞刀，等待价格确认。"
    if top_count and bottom_count: return "信号分歧", evidence, "调查、仓位或价格没有同向，不强行给方向结论。"
    return "未进入人性极端", evidence, "维持既定风险预算，不把正常波动解释成转折。"


def serial(value):
    if isinstance(value, dict): return {k: serial(v) for k, v in value.items()}
    return value.isoformat() if isinstance(value, date) else value


def report(today, aaii, naaim, market, breadth, state, evidence, action, errors):
    lines = [f"# 美股人性极端监测｜{today}", "", "## 今日结论", "", f"**{state}**", "", action, "", "## 五层证据", ""] + [f"- {x}" for x in evidence]
    lines += ["", "| 指标 | 最新值 | 观测日 |", "|---|---:|---|"]
    lines += [f"| AAII 看多/中性/看空 | {fmt(aaii['bullish'], '%')} / {fmt(aaii['neutral'], '%')} / {fmt(aaii['bearish'], '%')} | {aaii['date']} |" if aaii else "| AAII | UNAVAILABLE | — |", f"| NAAIM 权益曝险 | {fmt(naaim['exposure'])} | {naaim['date']} |" if naaim else "| NAAIM | UNAVAILABLE | — |"]
    for s in ("SPY", "QQQ", "IWM"):
        lines.append(f"| {s} 收盘 / 20 日变化 / 252 日回撤 | {fmt(market[s]['close'])} / {fmt(market[s]['change20'], '%')} / {fmt(market[s]['drawdown'], '%')} | {market[s]['date']} |" if market else f"| {s} | UNAVAILABLE | — |")
    lines.append(f"| VIX | {fmt(market['VIX']['close'])} | {market['VIX']['date']} |" if market else "| VIX | UNAVAILABLE | — |")
    lines += ["", "## 宽度温度计（0% → 100%）", "", "宽度是 **指数成分股中站上对应均线的比例**，不是价格的历史百分位。`┊` 为极端线，`●` 为当前位置；20/200 日使用 15%／85%，50 日使用 25%／80%。", "", "| 市场 | 20 日宽度 | 20 日位置 | 50 日宽度 | 50 日位置 | 200 日宽度 | 200 日位置 |", "|---|---:|---|---:|---|---:|---|"]
    for name in TV_BREADTH:
        periods = breadth.get(name) if breadth else None
        if not periods:
            lines.append(f"| {name} | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |")
            continue
        lines.append(f"| {name} | {periods[20]['value']:.2f}%（{breadth_zone(periods[20]['value'])}） | `{gauge(periods[20]['value'])}` | {periods[50]['value']:.2f}%（{breadth_zone(periods[50]['value'], 25, 80)}） | `{gauge(periods[50]['value'], 25, 80)}` | {periods[200]['value']:.2f}%（{breadth_zone(periods[200]['value'])}） | `{gauge(periods[200]['value'])}` |")
    lines += ["", "## 怎么读", "", "- 20 日最敏感：≤15% 表示短线普遍洗出，≥85% 表示短线参与面普遍拥挤。", "- 50 日确认中期参与度；大盘顶部／底部的升级要求三个市场的 20 日与 50 日宽度同时同向极端。", "- 200 日用于长期结构：高位表示长期趋势仍有广泛支撑，不能单独视为卖出信号。", "", "## 普通投资者的纪律", "", "- 顶部警戒：不追高、不加杠杆；不是做空指令。", "- 底部观察：不因恐慌单独抄底，等待价格修复。", "", "## 数据质量与来源", "", f"- AAII：{AAII if aaii else 'UNAVAILABLE'}", f"- NAAIM：{NAAIM if naaim else 'UNAVAILABLE'}", "- 价格：Yahoo Finance chart JSON；宽度：TradingView `INDEX:*` 公开报价流。"]
    if errors: lines += ["", "### 采集错误", ""] + [f"- {x}" for x in errors]
    return "\n".join(lines) + "\n"


def run():
    today, errors = datetime.now(TZ).date(), []
    aaii = naaim = market = breadth = None
    try: aaii = fetch_aaii(today)
    except Exception as exc: errors.append(f"AAII: {type(exc).__name__}: {exc}")
    try: naaim = fetch_naaim()
    except Exception as exc: errors.append(f"NAAIM: {type(exc).__name__}: {exc}")
    try: market = price_metrics({s: fetch_price(s) for s in ("SPY", "QQQ", "IWM", "^VIX")})
    except Exception as exc: errors.append(f"市场价格: {type(exc).__name__}: {exc}")
    try: breadth = fetch_tradingview_breadth(today)
    except Exception as exc: errors.append(f"TradingView 宽度: {type(exc).__name__}: {exc}")
    state, evidence, action = decide(aaii, naaim, market, breadth, today)
    body = report(today, aaii, naaim, market, breadth, state, evidence, action, errors)
    (ROOT / "reports").mkdir(exist_ok=True); (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "reports" / f"market-human-extremes-{today}.md").write_text(body, encoding="utf-8")
    snapshot = {"report_date": str(today), "state": state, "aaii": serial(aaii), "naaim": serial(naaim), "market": serial(market), "breadth": serial(breadth), "errors": errors}
    (ROOT / "data" / "latest_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    aaii = {"date": date(2026, 7, 9), "bullish": 50., "neutral": 20., "bearish": 30., "source": "test"}; naaim = {"date": date(2026, 7, 8), "exposure": 90., "source": "test"}
    line = {"close": 100., "date": date(2026, 7, 14), "ma5": 99., "ma50": 95., "ma200": 90., "change20": 3., "drawdown": -2.}
    market = {"SPY": line, "QQQ": line.copy(), "IWM": line.copy(), "VIX": {"close": 15., "date": date(2026, 7, 14)}}
    breadth = {name: {days: {"value": 90., "date": date(2026, 7, 14)} for days in (20, 50, 200)} for name in TV_BREADTH}
    assert decide(aaii, naaim, market, breadth, today)[0] == "顶部人性极端（警戒）"
    market["VIX"]["date"] = date(2026, 7, 1); assert decide(aaii, naaim, market, breadth, today)[0] == "数据不足 / 不作极端判断"


if __name__ == "__main__":
    args = argparse.ArgumentParser(); args.add_argument("--self-test", action="store_true"); parsed = args.parse_args()
    if parsed.self_test: self_test(); print("self-test: ok")
    else: raise SystemExit(run())
