#!/usr/bin/env python3
"""Collect public U.S. market data and write a reproducible macro-regime report."""

from __future__ import annotations

import argparse
import csv
import io
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
UA = "Mozilla/5.0 macro-regime-monitor/1.0"
YAHOO = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
    "RSP": "S&P 500 equal weight ETF",
    "^VIX": "VIX",
    "^VIX3M": "VIX3M",
    "UUP": "美元 ETF 代理",
    "HYG": "高收益债 ETF",
    "LQD": "投资级债 ETF",
    "ARKK": "高贝塔散户偏好代理",
}
FRED = {
    "DGS2": "2Y 美债",
    "DGS10": "10Y 美债",
    "DFII10": "10Y 实际利率",
    "BAMLH0A0HYM2": "美国高收益债 OAS",
}


@dataclass
class Series:
    key: str
    label: str
    dates: list[str]
    values: list[float]
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
    return (values[-1] / values[-periods - 1] - 1.0) * 100.0


def delta(values: list[float], periods: int) -> float | None:
    if len(values) <= periods:
        return None
    return values[-1] - values[-periods - 1]


def mean_tail(values: list[float], periods: int) -> float | None:
    if len(values) < periods:
        return None
    return statistics.fmean(values[-periods:])


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def fetch_text(url: str, timeout: int = 10) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_yahoo(symbol: str, label: str) -> Series:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1y&interval=1d&events=history"
    result = fetch_json(url)["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    adjusted = result.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose")
    closes = adjusted if adjusted and len(adjusted) == len(timestamps) else quote.get("close", [])
    dates, values = [], []
    for ts, value in zip(timestamps, closes):
        if value is None or not math.isfinite(float(value)):
            continue
        dates.append(datetime.fromtimestamp(ts, timezone.utc).date().isoformat())
        values.append(float(value))
    ny_now = datetime.now(NY_TZ)
    ny_minutes = ny_now.hour * 60 + ny_now.minute
    if dates and ny_now.weekday() < 5 and 570 <= ny_minutes < 975 and dates[-1] == ny_now.date().isoformat():
        dates.pop()
        values.pop()
    return Series(symbol, label, dates, values, f"Yahoo chart JSON ({symbol})")


def fetch_fred(series_id: str, label: str) -> Series:
    text = fetch_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
    rows = csv.DictReader(io.StringIO(text))
    dates, values = [], []
    for row in rows:
        raw = row.get(series_id, ".")
        if raw in (None, "", "."):
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        dates.append(row.get("DATE") or row.get("observation_date") or "")
        values.append(value)
    return Series(series_id, label, dates, values, f"FRED CSV ({series_id})")


def fetch_treasury_curve(real: bool = False) -> dict[str, Series]:
    year = datetime.now(timezone.utc).year
    curve_type = "daily_treasury_real_yield_curve" if real else "daily_treasury_yield_curve"
    url = (
        f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/{year}/all?type={curve_type}&field_tdr_date_value={year}&page&_format=csv"
    )
    rows = list(csv.DictReader(io.StringIO(fetch_text(url, timeout=15))))
    if not rows:
        return {}
    wanted = {"DFII10": "10YR"} if real else {"DGS2": "2YR", "DGS10": "10YR"}
    output: dict[str, Series] = {}
    for series_id, normalized_column in wanted.items():
        points = []
        for row in rows:
            date_raw = row.get("Date") or row.get("DATE")
            column = next((k for k in row if k.upper().replace(" ", "") == normalized_column), None)
            if not date_raw or not column or not row.get(column):
                continue
            try:
                obs_date = datetime.strptime(date_raw, "%m/%d/%Y").date().isoformat()
                points.append((obs_date, float(row[column])))
            except ValueError:
                continue
        points.sort()
        if points:
            output[series_id] = Series(
                series_id, FRED[series_id], [x[0] for x in points], [x[1] for x in points],
                f"U.S. Treasury CSV ({curve_type})",
            )
    return output


def collect() -> tuple[dict[str, Series], list[str]]:
    data: dict[str, Series] = {}
    errors: list[str] = []
    def one(key: str, label: str) -> Series:
        return fetch_yahoo(key, label) if key in YAHOO else fetch_fred(key, label)

    items = list({**YAHOO, **FRED}.items())
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(one, key, label): key for key, label in items}
        for future in as_completed(futures):
            key = futures[future]
            try:
                data[key] = future.result()
            except Exception as exc:  # keep partial reports honest
                errors.append(f"{key}: {type(exc).__name__}: {exc}")
    if any(key not in data for key in ("DGS2", "DGS10")):
        try:
            for key, series in fetch_treasury_curve(real=False).items():
                data.setdefault(key, series)
        except Exception as exc:
            errors.append(f"U.S. Treasury nominal fallback: {type(exc).__name__}: {exc}")
    if "DFII10" not in data:
        try:
            for key, series in fetch_treasury_curve(real=True).items():
                data.setdefault(key, series)
        except Exception as exc:
            errors.append(f"U.S. Treasury real-yield fallback: {type(exc).__name__}: {exc}")
    return data, errors


def trend_score(series: Series | None) -> float | None:
    if not series or len(series.values) < 200:
        return None
    value = series.values[-1]
    score = 50.0
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


def vix_level_score(value: float | None) -> float | None:
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
    spy, qqq, iwm, rsp = (data.get(k) for k in ("SPY", "QQQ", "IWM", "RSP"))
    vix, vix3m = data.get("^VIX"), data.get("^VIX3M")
    hyg, lqd = data.get("HYG"), data.get("LQD")
    arkk = data.get("ARKK")
    dgs2, dgs10, real10, oas = (data.get(k) for k in ("DGS2", "DGS10", "DFII10", "BAMLH0A0HYM2"))

    trend_parts = [
        trend_score(spy), trend_score(qqq), trend_score(iwm),
        relative_score(rsp, spy), relative_score(iwm, spy),
    ]
    trend = average(trend_parts)

    vix_ratio = None
    if vix and vix3m and vix.last is not None and vix3m.last:
        vix_ratio = vix.last / vix3m.last
    term_score = None if vix_ratio is None else clamp(100 - max(0, vix_ratio - 0.80) * 250)
    vix_momentum = pct_change(vix.values, 5) if vix else None
    momentum_score = None if vix_momentum is None else clamp(70 - vix_momentum * 2)
    volatility_parts = [vix_level_score(vix.last if vix else None), term_score, momentum_score]
    volatility = average(volatility_parts)

    real20 = delta(real10.values, 20) if real10 else None
    ten20 = delta(dgs10.values, 20) if dgs10 else None
    curve = None
    if dgs2 and dgs10 and dgs2.last is not None and dgs10.last is not None:
        curve = dgs10.last - dgs2.last
    real_score = None if real20 is None else clamp(55 - real20 * 80)
    ten_score = None if ten20 is None else clamp(55 - ten20 * 60)
    curve_score = None if curve is None else (35 if curve < 0 else 55 if curve < 0.5 else 65)
    usd_score = trend_score(data.get("UUP"))
    usd_score = None if usd_score is None else 100 - usd_score
    core_rate_parts = [real_score, ten_score, curve_score]
    rate_parts = core_rate_parts + [usd_score]
    rates = neutral_average(rate_parts) if sum(x is not None for x in core_rate_parts) >= 2 else None

    oas5 = delta(oas.values, 5) if oas else None
    oas_score = None
    if oas and oas.last is not None:
        oas_score = clamp(110 - oas.last * 18)
        if oas5 is not None:
            oas_score = clamp(oas_score - max(0, oas5) * 40)
    credit_parts = [oas_score, relative_score(hyg, lqd)]
    credit = neutral_average(credit_parts)

    sentiment_parts = [relative_score(arkk, spy), relative_score(iwm, spy)]
    sentiment = average(sentiment_parts)
    modules = {
        "趋势与广度": {"weight": 25, "score": trend},
        "波动与尾部": {"weight": 20, "score": volatility},
        "利率与美元": {"weight": 20, "score": rates},
        "信用与流动性": {"weight": 15, "score": credit},
        "情绪与拥挤": {"weight": 10, "score": sentiment},
        "事件风险": {"weight": 10, "score": 50.0},
    }
    present_weight = sum(x["weight"] for x in modules.values() if x["score"] is not None)
    base = sum(x["weight"] * x["score"] for x in modules.values() if x["score"] is not None) / present_weight
    covered_weight = (
        25 * sum(x is not None for x in trend_parts) / len(trend_parts)
        + 20 * sum(x is not None for x in volatility_parts) / len(volatility_parts)
        + 20 * sum(x is not None for x in rate_parts) / len(rate_parts)
        + 15 * sum(x is not None for x in credit_parts) / len(credit_parts)
        + 10 * sum(x is not None for x in sentiment_parts) / len(sentiment_parts)
    )
    coverage = covered_weight / 90 * 100

    vetoes = []
    if vix and vix.last is not None and vix.last >= 35:
        vetoes.append("VIX ≥ 35")
    if vix_ratio is not None and vix_ratio >= 1.15:
        vetoes.append("VIX/VIX3M ≥ 1.15")
    if oas5 is not None and oas5 >= 0.75:
        vetoes.append("HY OAS 5 个观测日扩大 ≥ 75bp")
    spy20 = pct_change(spy.values, 20) if spy else None
    spy200 = mean_tail(spy.values, 200) if spy else None
    if spy and spy.last is not None and spy200 is not None and spy.last < spy200 and spy20 is not None and spy20 <= -8:
        vetoes.append("SPY 跌破 200 日线且 20 日跌幅 ≤ -8%")
    regime = classify(base, coverage, len(vetoes))
    return {
        "base_score": round(base, 1), "coverage_pct": round(coverage, 1), "regime": regime,
        "modules": modules, "vetoes": vetoes, "vix_ratio": vix_ratio, "curve": curve,
        "changes": {"vix_5d_pct": vix_momentum, "real10_20d_pp": real20, "dgs10_20d_pp": ten20,
                    "hy_oas_5obs_pp": oas5, "spy_20d_pct": spy20},
    }


def classify(score: float, coverage: float, veto_count: int) -> str:
    if coverage < 70:
        return "数据不足 / 以防守为主"
    if score >= 70:
        label = "进攻"
    elif score >= 58:
        label = "偏进攻"
    elif score >= 43:
        label = "中性"
    elif score >= 30:
        label = "偏防守"
    else:
        label = "防守"
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
    path = ROOT / "portfolio.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "未配置；请补充 `portfolio.json`。"
    holdings = payload.get("holdings") or []
    if not holdings:
        return "未配置个人持仓。本报告只给出市场风险预算，不给出个股买卖动作。"
    rows = ["| 标的 | 权重/数量 | 持有逻辑 | 宏观敏感项 |", "|---|---:|---|---|"]
    for item in holdings:
        size = item.get("weight_pct", item.get("quantity", "未填"))
        rows.append(f"| {item.get('ticker', '未填')} | {size} | {item.get('thesis', '未填')} | 待结合本期模块判断 |")
    return "\n".join(rows)


def render(data: dict[str, Series], result: dict, errors: list[str], now: datetime) -> str:
    module_rows = ["| 模块 | 权重 | 得分 | 解释 |", "|---|---:|---:|---|"]
    for name, item in result["modules"].items():
        score = item["score"]
        note = "待核验今日事件" if name == "事件风险" else ("缺失" if score is None else "越高越支持承担风险")
        module_rows.append(f"| {name} | {item['weight']}% | {fmt(score, digits=1)} | {note} |")
    keys = ["SPY", "QQQ", "IWM", "RSP", "^VIX", "^VIX3M", "DGS2", "DGS10", "DFII10", "BAMLH0A0HYM2", "HYG", "LQD", "ARKK"]
    value_rows = ["| 指标 | 最新值 | 1日 | 5日 | 20日 | 观测日 |", "|---|---:|---:|---:|---:|---|"]
    for key in keys:
        series = data.get(key)
        if not series:
            value_rows.append(f"| {YAHOO.get(key, FRED.get(key, key))} | UNAVAILABLE | — | — | — | — |")
            continue
        if key in FRED:
            changes = [fmt(None if delta(series.values, n) is None else delta(series.values, n) * 100, "bp") for n in (1, 5, 20)]
        else:
            changes = [fmt(pct_change(series.values, n), "%") for n in (1, 5, 20)]
        value_rows.append(f"| {series.label} | {fmt(series.last)} | {changes[0]} | {changes[1]} | {changes[2]} | {series.last_date} |")
    veto = "；".join(result["vetoes"]) if result["vetoes"] else "无"
    action = {
        "进攻": "可按既定计划交易，避免因环境良好而追高。",
        "偏进攻": "可以参与，但降低单笔集中度，等待回撤或确认。",
        "中性": "减少频繁交易，等待趋势、信用和波动形成同向确认。",
        "偏防守": "降低高贝塔、杠杆和隔夜事件暴露，优先保护本金。",
        "防守": "暂停主动增加风险，等待硬否决信号解除。",
        "数据不足 / 以防守为主": "关键数据覆盖不足，不用猜测替代；暂以防守为主。",
    }[result["regime"]]
    errors_text = "\n".join(f"- {x}" for x in errors) if errors else "- 无抓取错误。"
    freshness = []
    for key, series in sorted(data.items()):
        age = stale_days(series.last_date, now.date())
        freshness.append(f"- {series.label}: {series.last_date}（滞后 {age} 天）｜{series.source}")
    return f"""# 美股宏观交易环境｜{now.date().isoformat()}

> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} Asia/Shanghai｜口径：最近完整美股收盘｜非投资建议

## 今日结论

**{result['regime']}｜量化底分 {result['base_score']}/100｜有效覆盖 {result['coverage_pct']}%**

硬否决：{veto}。当前结论回答的是“可承受多少风险”，不是预测指数今天必涨或必跌。

## 普通投资者怎么做

{action}

## 六模块温度表

{chr(10).join(module_rows)}

## 关键指标与变化

{chr(10).join(value_rows)}

- VIX/VIX3M：{fmt(result['vix_ratio'])}
- 10Y-2Y：{fmt(result['curve'], 'pct')}

## 散户情绪与拥挤度

- ARKK/SPY 与 IWM/SPY 只作为高贝塔/散户偏好的日频代理。
- Cboe put/call、AAII 周度情绪、FINRA 月度融资数据：**待自动化代理核验后补充**。
- 极端乐观或悲观不能单独触发交易，必须由价格、VIX 和信用确认。

## 今日事件风险

**待自动化代理从 Fed、BLS、BEA、U.S. Treasury 等一手来源核验，并给出 -10 至 +10 的透明覆盖分。**

## 个人持仓联动

{portfolio_section()}

## 反证与升级/降级条件

- 升级：趋势广度改善、VIX 期限结构恢复顺价差、实际利率与信用压力缓和。
- 降级：触发任一硬否决，或高影响事件使贴现率/盈利预期明显恶化。
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
    report_path = report_dir / f"us-market-macro-regime-{now.date().isoformat()}.md"
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
    return Series(key, key, dates, values, "fixture")


def self_test() -> None:
    data = {k: fixture_series(k, 500 if k not in ("^VIX", "^VIX3M") else 15) for k in YAHOO}
    data["^VIX"] = fixture_series("^VIX", 14, slope=-0.01)
    data["^VIX3M"] = fixture_series("^VIX3M", 18, slope=-0.005)
    data["DGS2"] = fixture_series("DGS2", 4.0, slope=0.0)
    data["DGS10"] = fixture_series("DGS10", 4.4, slope=0.0)
    data["DFII10"] = fixture_series("DFII10", 2.0, slope=0.0)
    data["BAMLH0A0HYM2"] = fixture_series("BAMLH0A0HYM2", 3.0, slope=0.0)
    result = compute(data)
    assert result["coverage_pct"] >= 99
    assert result["regime"] in {"进攻", "偏进攻", "中性"}
    data["^VIX"].values[-1] = 40
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
