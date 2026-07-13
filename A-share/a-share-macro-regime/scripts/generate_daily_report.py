#!/usr/bin/env python3
"""Collect public A-share/offshore data and write a reproducible pre-open regime report."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
NY_TZ = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 a-share-macro-regime/1.0"
SYMBOLS = {
    "000001.SS": "上证综指",
    "000300.SS": "沪深300",
    "399006.SZ": "创业板指",
    "000688.SS": "科创50",
    "000852.SS": "中证1000",
    "510300.SS": "沪深300ETF成交代理",
    "511260.SS": "10年国债ETF代理",
    "CNH=X": "USD/CNH",
    "^HXC": "纳斯达克金龙中国指数",
    "KWEB": "中国互联网ETF",
    "FXI": "中国大盘股ETF",
    "MCHI": "宽基中国ETF",
    "YINN": "中国三倍做多ETF",
    "YANG": "中国三倍做空ETF",
    "^VIX": "VIX",
    "SPY": "S&P 500 ETF",
    "UUP": "美元ETF代理",
}
TENCENT = {
    "000001.SS": "sh000001",
    "000300.SS": "sh000300",
    "399006.SZ": "sz399006",
    "000688.SS": "sh000688",
    "000852.SS": "sh000852",
    "510300.SS": "sh510300",
    "511260.SS": "sh511260",
}


@dataclass
class Series:
    key: str
    label: str
    dates: list[str]
    values: list[float]
    volumes: list[float | None]
    source: str

    @property
    def last(self) -> float | None:
        return self.values[-1] if self.values else None

    @property
    def last_date(self) -> str | None:
        return self.dates[-1] if self.dates else None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def pct_change(values: list[float], periods: int) -> float | None:
    if len(values) <= periods or values[-periods - 1] == 0:
        return None
    return (values[-1] / values[-periods - 1] - 1) * 100


def mean_tail(values: list[float], periods: int) -> float | None:
    if len(values) < periods:
        return None
    return statistics.fmean(values[-periods:])


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def fetch_yahoo(symbol: str, label: str) -> Series:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1y&interval=1d&events=history"
    result = fetch_json(url)["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    adjusted = result.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose")
    closes = adjusted if adjusted and len(adjusted) == len(timestamps) else quote.get("close", [])
    raw_volumes = quote.get("volume", [None] * len(closes))
    dates, values, volumes = [], [], []
    for ts, value, volume in zip(timestamps, closes, raw_volumes):
        if value is None or not math.isfinite(float(value)):
            continue
        dates.append(datetime.fromtimestamp(ts, timezone.utc).date().isoformat())
        values.append(float(value))
        volumes.append(None if volume is None else float(volume))
    ny_now = datetime.now(NY_TZ)
    ny_minutes = ny_now.hour * 60 + ny_now.minute
    us_session_symbols = {"^HXC", "KWEB", "FXI", "MCHI", "YINN", "YANG", "^VIX", "SPY", "UUP"}
    if symbol in us_session_symbols and dates and ny_now.weekday() < 5 and 570 <= ny_minutes < 975 and dates[-1] == ny_now.date().isoformat():
        dates.pop()
        values.pop()
        volumes.pop()
    return Series(symbol, label, dates, values, volumes, f"Yahoo chart JSON ({symbol})")


def fetch_tencent(symbol: str, label: str) -> Series:
    market_symbol = TENCENT[symbol]
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_symbol},day,,,300,qfq"
    payload = fetch_json(url)
    block = payload.get("data", {}).get(market_symbol, {})
    rows = block.get("qfqday") or block.get("day") or []
    dates, values, volumes = [], [], []
    for row in rows:
        if len(row) < 3:
            continue
        try:
            close = float(row[2])
            volume = float(row[5]) if len(row) > 5 and row[5] not in (None, "") else None
        except (TypeError, ValueError):
            continue
        dates.append(str(row[0]))
        values.append(close)
        volumes.append(volume)
    if not values:
        raise ValueError(f"Tencent returned no daily rows for {market_symbol}")
    return Series(symbol, label, dates, values, volumes, f"Tencent qfq kline ({market_symbol})")


def fetch_market_series(symbol: str, label: str) -> Series:
    if symbol not in TENCENT:
        return fetch_yahoo(symbol, label)
    try:
        return fetch_tencent(symbol, label)
    except Exception:
        return fetch_yahoo(symbol, label)


def collect() -> tuple[dict[str, Series], list[str]]:
    data, errors = {}, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_market_series, symbol, label): symbol for symbol, label in SYMBOLS.items()}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                data[symbol] = future.result()
            except Exception as exc:
                errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
    return data, errors


def trend_score(series: Series | None) -> float | None:
    if not series or len(series.values) < 200:
        return None
    score, value = 50.0, series.values[-1]
    for window, points in ((20, 15), (50, 15), (200, 20)):
        ma = mean_tail(series.values, window)
        score += points if ma is not None and value >= ma else -points
    return clamp(score)


def relative_score(left: Series | None, right: Series | None) -> float | None:
    if not left or not right:
        return None
    size = min(len(left.values), len(right.values))
    if size < 50:
        return None
    ratio = [a / b for a, b in zip(left.values[-size:], right.values[-size:]) if b]
    if len(ratio) < 50:
        return None
    score = 50.0
    score += 25 if ratio[-1] >= statistics.fmean(ratio[-20:]) else -25
    score += 25 if ratio[-1] >= statistics.fmean(ratio[-50:]) else -25
    return clamp(score)


def average(items: Iterable[float | None]) -> float | None:
    clean = [x for x in items if x is not None]
    return statistics.fmean(clean) if clean else None


def neutral_average(items: Iterable[float | None]) -> float | None:
    values = list(items)
    if not any(x is not None for x in values):
        return None
    return statistics.fmean(50.0 if x is None else x for x in values)


def volume_score(series: Series | None) -> float | None:
    if not series:
        return None
    clean = [x for x in series.volumes if x is not None and x > 0]
    if len(clean) < 21:
        return None
    ratio = clean[-1] / statistics.fmean(clean[-21:-1])
    price20 = pct_change(series.values, 20)
    if price20 is None:
        return None
    if price20 >= 0:
        return clamp(50 + (ratio - 1) * 35 + min(price20, 10) * 2)
    return clamp(50 - (ratio - 1) * 35 + max(price20, -10) * 2)


def vix_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 15:
        return 90
    if value <= 20:
        return 75 - (value - 15) * 5
    if value <= 25:
        return 50 - (value - 20) * 4
    if value <= 35:
        return 30 - (value - 25) * 3
    return 0


def compute(data: dict[str, Series]) -> dict:
    sse, csi300, chinext, star, csi1000 = (data.get(k) for k in ("000001.SS", "000300.SS", "399006.SZ", "000688.SS", "000852.SS"))
    domestic_parts = [
        trend_score(csi300), trend_score(sse), trend_score(chinext), trend_score(star), trend_score(csi1000),
        relative_score(csi1000, csi300), relative_score(star, csi300),
    ]
    domestic = neutral_average(domestic_parts)
    participation_parts = [
        volume_score(data.get("510300.SS")), relative_score(csi1000, csi300), relative_score(chinext, csi300),
    ]
    participation = neutral_average(participation_parts)

    cnh = data.get("CNH=X")
    cnh20 = pct_change(cnh.values, 20) if cnh else None
    cnh_score = None if cnh20 is None else clamp(55 - cnh20 * 18)
    cnh_trend = trend_score(cnh)
    cnh_trend = None if cnh_trend is None else 100 - cnh_trend
    bond_score = trend_score(data.get("511260.SS"))
    rates_fx_parts = [cnh_score, cnh_trend, bond_score]
    rates_fx = neutral_average(rates_fx_parts)

    hxc, kweb, fxi, mchi = (data.get(k) for k in ("^HXC", "KWEB", "FXI", "MCHI"))
    yinn, yang = data.get("YINN"), data.get("YANG")
    offshore_parts = [
        trend_score(hxc), trend_score(kweb), trend_score(fxi), trend_score(mchi), relative_score(yinn, yang),
    ]
    offshore = neutral_average(offshore_parts)

    vix, spy, uup = data.get("^VIX"), data.get("SPY"), data.get("UUP")
    dollar = trend_score(uup)
    dollar = None if dollar is None else 100 - dollar
    global_parts = [vix_score(vix.last if vix else None), trend_score(spy), dollar]
    global_risk = neutral_average(global_parts)

    modules = {
        "趋势与内部结构": {"weight": 30, "score": domestic},
        "参与度与流动性": {"weight": 15, "score": participation},
        "人民币与利率": {"weight": 15, "score": rates_fx},
        "离岸中国信号": {"weight": 20, "score": offshore},
        "全球风险环境": {"weight": 10, "score": global_risk},
        "政策与事件": {"weight": 10, "score": 50.0},
    }
    present_weight = sum(x["weight"] for x in modules.values() if x["score"] is not None)
    base = sum(x["weight"] * x["score"] for x in modules.values() if x["score"] is not None) / present_weight
    covered_weight = (
        30 * sum(x is not None for x in domestic_parts) / len(domestic_parts)
        + 15 * sum(x is not None for x in participation_parts) / len(participation_parts)
        + 15 * sum(x is not None for x in rates_fx_parts) / len(rates_fx_parts)
        + 20 * sum(x is not None for x in offshore_parts) / len(offshore_parts)
        + 10 * sum(x is not None for x in global_parts) / len(global_parts)
    )
    coverage = covered_weight / 90 * 100

    vetoes = []
    csi20 = pct_change(csi300.values, 20) if csi300 else None
    csi200 = mean_tail(csi300.values, 200) if csi300 else None
    below200 = bool(csi300 and csi300.last is not None and csi200 is not None and csi300.last < csi200)
    if below200 and csi20 is not None and csi20 <= -10:
        vetoes.append("沪深300 跌破 200 日线且 20 日跌幅 ≤ -10%")
    if below200 and cnh20 is not None and cnh20 >= 2.5:
        vetoes.append("USD/CNH 20 日升幅 ≥ 2.5% 且沪深300低于200日线")
    hxc5 = pct_change(hxc.values, 5) if hxc else None
    if vix and vix.last is not None and vix.last >= 35 and hxc5 is not None and hxc5 <= -8:
        vetoes.append("VIX ≥ 35 且 HXC 5 日跌幅 ≤ -8%")
    yinn5 = pct_change(yinn.values, 5) if yinn else None
    yang5 = pct_change(yang.values, 5) if yang else None
    if yinn5 is not None and yang5 is not None and yinn5 <= -15 and yang5 >= 15:
        vetoes.append("YINN/YANG 共同确认离岸压力")
    return {
        "base_score": round(base, 1), "coverage_pct": round(coverage, 1),
        "regime": classify(base, coverage, len(vetoes)), "modules": modules, "vetoes": vetoes,
        "changes": {"csi300_20d_pct": csi20, "cnh_20d_pct": cnh20, "hxc_5d_pct": hxc5,
                    "yinn_5d_pct": yinn5, "yang_5d_pct": yang5},
    }


def classify(score: float, coverage: float, veto_count: int) -> str:
    if coverage < 70:
        return "数据不足 / 以防守为主"
    label = "进攻" if score >= 70 else "偏进攻" if score >= 58 else "中性" if score >= 43 else "偏防守" if score >= 30 else "防守"
    if veto_count >= 2:
        return "防守"
    if veto_count == 1 and label in ("进攻", "偏进攻", "中性"):
        return "偏防守"
    return label


def fmt(value: float | None, suffix: str = "", digits: int = 2) -> str:
    return "UNAVAILABLE" if value is None else f"{value:.{digits}f}{suffix}"


def stale_days(last_date: str | None, today: date) -> int | None:
    if not last_date:
        return None
    try:
        return (today - date.fromisoformat(last_date)).days
    except ValueError:
        return None


def portfolio_section() -> str:
    try:
        payload = json.loads((ROOT / "portfolio.json").read_text(encoding="utf-8"))
    except Exception:
        return "未配置；请补充 `portfolio.json`。"
    holdings = payload.get("holdings") or []
    if not holdings:
        return "未配置个人持仓。本报告只给出市场风险预算，不给出个股/ETF买卖动作。"
    rows = ["| 标的 | 权重/数量 | 持有逻辑 | 宏观敏感项 |", "|---|---:|---|---|"]
    for item in holdings:
        size = item.get("weight_pct", item.get("quantity", "未填"))
        rows.append(f"| {item.get('code', item.get('ticker', '未填'))} | {size} | {item.get('thesis', '未填')} | 待结合本期模块判断 |")
    return "\n".join(rows)


def render(data: dict[str, Series], result: dict, errors: list[str], now: datetime) -> str:
    module_rows = ["| 模块 | 权重 | 得分 | 解释 |", "|---|---:|---:|---|"]
    for name, item in result["modules"].items():
        score = item["score"]
        note = "待核验今日政策事件" if name == "政策与事件" else ("缺失" if score is None else "越高越支持承担风险")
        module_rows.append(f"| {name} | {item['weight']}% | {fmt(score, digits=1)} | {note} |")
    domestic_keys = ["000001.SS", "000300.SS", "399006.SZ", "000688.SS", "000852.SS", "510300.SS", "CNH=X"]
    offshore_keys = ["^HXC", "KWEB", "FXI", "MCHI", "YINN", "YANG", "^VIX", "SPY", "UUP"]
    def table(keys: list[str]) -> str:
        rows = ["| 指标 | 最新值 | 1日 | 5日 | 20日 | 观测日 |", "|---|---:|---:|---:|---:|---|"]
        for key in keys:
            s = data.get(key)
            if not s:
                rows.append(f"| {SYMBOLS[key]} | UNAVAILABLE | — | — | — | — |")
            else:
                rows.append(f"| {s.label} | {fmt(s.last)} | {fmt(pct_change(s.values, 1), '%')} | {fmt(pct_change(s.values, 5), '%')} | {fmt(pct_change(s.values, 20), '%')} | {s.last_date} |")
        return "\n".join(rows)
    veto = "；".join(result["vetoes"]) if result["vetoes"] else "无"
    action = {
        "进攻": "可按既定计划参与，开盘后仍需确认广度和量能。",
        "偏进攻": "可以参与，但不追高，主题仓位保持分散。",
        "中性": "先看开盘后30–60分钟的广度、量能与人民币，不急于下结论。",
        "偏防守": "降低高贝塔、拥挤主题和杠杆暴露，优先保护本金。",
        "防守": "暂停主动增加风险，等待人民币、离岸中国资产和内部趋势修复。",
        "数据不足 / 以防守为主": "关键数据覆盖不足，不用猜测替代；暂以防守为主。",
    }[result["regime"]]
    freshness = [f"- {s.label}: {s.last_date}（滞后 {stale_days(s.last_date, now.date())} 天）｜{s.source}" for s in data.values()]
    errors_text = "\n".join(f"- {x}" for x in errors) if errors else "- 无抓取错误。"
    return f"""# A股宏观交易环境｜{now.date().isoformat()}

> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} Asia/Shanghai｜口径：上一完整A股收盘 + 最近完整美股时段｜非投资建议

## 今日结论

**{result['regime']}｜量化底分 {result['base_score']}/100｜有效覆盖 {result['coverage_pct']}%**

硬否决：{veto}。结论是风险预算，不是对开盘涨跌的保证。

## 开盘前怎么做

{action}

## 六模块温度表

{chr(10).join(module_rows)}

## A股内部结构

{table(domestic_keys)}

## 离岸中国风险温度

{table(offshore_keys)}

- HXC：美国上市、主要业务在中国的公司指数，不等于A股全市场。
- YINN/YANG：只用于单日/短期压力确认；每日重置，不能按多日“三倍收益”理解。

## 流动性、人民币与政策事件

**待自动化代理核验 PBOC 公开市场操作、DR007、人民币中间价、国家统计局/财政部/证监会/交易所公告，并给出 -10 至 +10 的透明覆盖分。**

北向数据只使用可获得的官方历史成交/持仓口径，不声称实时净流入。

## 个人持仓联动

{portfolio_section()}

## 反证与升级/降级条件

- 升级：人民币稳定、A股内部广度改善、离岸中国资产同向确认、政策传导可量化。
- 降级：触发任一硬否决，或政策/信用事件显著抬升风险溢价。
- 当前硬否决：{veto}。

## 数据质量与来源

{chr(10).join(freshness)}

抓取异常：
{errors_text}
"""


def write_outputs(report: str, data: dict[str, Series], result: dict, errors: list[str], now: datetime) -> Path:
    report_dir, data_dir = ROOT / "reports", ROOT / "data"
    report_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"a-share-macro-regime-{now.date().isoformat()}.md"
    report_path.write_text(report, encoding="utf-8")
    snapshot = {
        "generated_at": now.isoformat(), "result": result, "errors": errors,
        "series": {k: {"label": s.label, "date": s.last_date, "value": s.last, "source": s.source} for k, s in data.items()},
    }
    (data_dir / "latest_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    with (data_dir / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return report_path


def fixture_series(key: str, value: float, count: int = 260, slope: float = 0.2) -> Series:
    values = [value - slope * (count - i - 1) for i in range(count)]
    dates = [f"2026-01-{(i % 28) + 1:02d}" for i in range(count)]
    return Series(key, key, dates, values, [1_000_000 + i * 1000 for i in range(count)], "fixture")


def self_test() -> None:
    data = {key: fixture_series(key, 500) for key in SYMBOLS}
    data["CNH=X"] = fixture_series("CNH=X", 7.0, slope=-0.001)
    data["^VIX"] = fixture_series("^VIX", 15, slope=-0.01)
    data["YANG"] = fixture_series("YANG", 30, slope=-0.02)
    result = compute(data)
    assert result["coverage_pct"] >= 99
    assert result["regime"] in {"进攻", "偏进攻", "中性"}
    data["^VIX"].values[-1] = 40
    data["^HXC"].values[-6:] = [500, 490, 480, 470, 460, 450]
    stressed = compute(data)
    assert stressed["vetoes"]
    assert stressed["regime"] in {"偏防守", "防守"}
    print("self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    now = datetime.now(TZ)
    data, errors = collect()
    if not data:
        print("No data sources succeeded", file=sys.stderr)
        return 2
    result = compute(data)
    report = render(data, result, errors, now)
    path = write_outputs(report, data, result, errors, now)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
