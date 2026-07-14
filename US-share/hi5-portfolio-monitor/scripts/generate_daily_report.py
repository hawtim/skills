#!/usr/bin/env python3
"""Audit the public Hi5 log and generate a reproducible Chinese daily monitor."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
import calendar
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SHEET_ID = "1G1E0qtLzt1WulfUk2uSxXrm_HNKejTMwwI-4KF3OG9w"
SHEET_GIDS = {"trades": "0", "data": "827729252"}
SYMBOLS = ("IWY", "RSP", "MOAT", "SPMO", "VNQ", "PFF")
CURRENT = ("IWY", "RSP", "SPMO", "VNQ", "PFF")
TZ = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 hi5-portfolio-monitor/1.0"
RULE_VERSION = "2.0.0"


@dataclass(frozen=True)
class Trade:
    transaction_date: str
    settlement_date: str
    activity: str
    symbol: str
    quantity: float
    price: float
    total_amount: float
    source_row: int


@dataclass
class Bar:
    day: str
    open: float
    high: float
    low: float
    close: float
    adjclose: float


def number(value: object) -> float:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def day_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text[:10]


def fetch_text(url: str) -> str:
    last: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=25) as response:
                return response.read().decode("utf-8-sig")
        except Exception as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    assert last is not None
    raise last


def sheet_url(gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def load_source(name: str, offline: bool = False, explicit: Path | None = None) -> str:
    target = DATA / "source" / f"{name}-current.csv"
    if explicit:
        text = explicit.read_text(encoding="utf-8-sig")
    elif offline:
        text = target.read_text(encoding="utf-8-sig")
    else:
        try:
            text = fetch_text(sheet_url(SHEET_GIDS[name]))
        except Exception:
            if not target.exists():
                raise
            text = target.read_text(encoding="utf-8-sig")
    atomic_text(target, text)
    return text


def parse_trades(text: str) -> list[Trade]:
    rows = list(csv.reader(io.StringIO(text)))
    header_idx = next(i for i, row in enumerate(rows) if row and row[0].strip() == "Transaction Date")
    header = rows[header_idx]
    idx = {name: header.index(name) for name in (
        "Transaction Date", "Settlement Date", "Activity Description", "Symbol",
        "Quantity", "Price", "Total Amount",
    )}
    result: list[Trade] = []
    allowed = {"Buy", "Sell", "Dividend", "Non resident tax"}
    for source_row, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        if len(row) <= max(idx.values()) or row[idx["Activity Description"]].strip() not in allowed:
            continue
        result.append(Trade(
            day_text(row[idx["Transaction Date"]]), day_text(row[idx["Settlement Date"]]),
            row[idx["Activity Description"]].strip(), row[idx["Symbol"]].strip(),
            number(row[idx["Quantity"]]), number(row[idx["Price"]]),
            number(row[idx["Total Amount"]]), source_row,
        ))
    if not result:
        raise ValueError("no Hi5 transactions parsed")
    return sorted(result, key=lambda item: (item.transaction_date, item.source_row))


def parse_author_stats(text: str) -> dict[str, float]:
    rows = list(csv.reader(io.StringIO(text)))
    result: dict[str, float] = {}
    in_current_section = False
    for row in rows[:20]:
        if len(row) < 22:
            continue
        label = row[20].strip()
        if "2026" in label and ("關鍵" in label or "关键" in label):
            in_current_section = True
            continue
        if in_current_section and "2025" in label and ("關鍵" in label or "关键" in label):
            break
        if not in_current_section:
            continue
        if label:
            result[label] = number(row[21])
    aliases = {
        "prior_year_end_mv": ("2025期末市值",), "current_mv": ("2026當前市值", "2026当前市值"),
        "market_value_growth": ("市值增長", "市值增长"), "year_net_input": ("淨投入", "净投入"),
        "year_net_dividends": ("淨股息", "净股息"), "year_net_income": ("淨收益", "净收益"),
    }
    normalized: dict[str, float] = {}
    for key, choices in aliases.items():
        for choice in choices:
            if choice in result:
                normalized[key] = result[choice]
                break
    return normalized


def parse_sheet_latest(text: str) -> dict:
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        return {}
    row = next((r for r in rows[2:] if r and day_text(r[0])), [])
    if len(row) < 26:
        return {}
    result = {"date": day_text(row[0]), "total_mv": number(row[25])}
    for symbol, start in (("IWY", 1), ("RSP", 5), ("SPMO", 9), ("VNQ", 13), ("PFF", 17), ("MOAT", 21)):
        result[symbol] = {"close": number(row[start]), "shares": number(row[start + 2]), "mv": number(row[start + 3])}
    return result


def fetch_bars(symbol: str, offline: bool = False) -> list[Bar]:
    cache = DATA / "price-cache" / f"{symbol}.json"
    payload: dict
    if offline:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        start = int(datetime(2023, 7, 1, tzinfo=timezone.utc).timestamp())
        end = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp())
        encoded = urllib.parse.quote(symbol, safe="")
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
               f"?period1={start}&period2={end}&interval=1d&events=div%2Csplits&includeAdjustedClose=true")
        try:
            payload = json.loads(fetch_text(url))
            atomic_text(cache, json.dumps(payload, ensure_ascii=False))
        except Exception:
            if not cache.exists():
                raise
            payload = json.loads(cache.read_text(encoding="utf-8"))
    result = payload["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    adjusted = result.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
    bars: list[Bar] = []
    for i, stamp in enumerate(stamps):
        values = [quote.get(key, [None] * len(stamps))[i] for key in ("open", "high", "low", "close")]
        if any(v is None for v in values):
            continue
        close = float(values[3])
        adj = float(adjusted[i]) if i < len(adjusted) and adjusted[i] is not None else close
        bars.append(Bar(datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(),
                        float(values[0]), float(values[1]), float(values[2]), close, adj))
    if len(bars) < 100:
        raise RuntimeError(f"{symbol}: insufficient history ({len(bars)})")
    return bars


def trade_hash(trades: list[Trade]) -> str:
    raw = json.dumps([asdict(item) for item in trades], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def campaign_type(day: str) -> str:
    if day == "2023-08-03":
        return "initial"
    if day in {"2024-08-01", "2025-08-01"}:
        return "rebalance"
    return "recurring"


def third_friday(year: int, month: int) -> date:
    cal = calendar.monthcalendar(year, month)
    fridays = [week[calendar.FRIDAY] for week in cal if week[calendar.FRIDAY]]
    return date(year, month, fridays[2])


def rsp_rule_audit(trades: list[Trade], bars: list[Bar]) -> list[dict]:
    campaigns = sorted({t.transaction_date for t in trades if t.activity == "Buy" and
                        campaign_type(t.transaction_date) == "recurring" and t.transaction_date >= "2025-01-01"})
    by_month: defaultdict[str, list[str]] = defaultdict(list)
    for day in campaigns:
        by_month[day[:7]].append(day)
    positions = {bar.day: i for i, bar in enumerate(bars)}
    rows: list[dict] = []
    for month, days in sorted(by_month.items()):
        year, mon = map(int, month.split("-"))
        month_bars = [bar for bar in bars if bar.day.startswith(month)]
        if not month_bars:
            continue
        first_i = positions[month_bars[0].day]
        prior_close = bars[first_i - 1].close if first_i else month_bars[0].open
        for ordinal, day in enumerate(days, 1):
            if day not in positions:
                continue
            i = positions[day]
            daily = bars[i].low / bars[i - 1].close - 1 if i else 0
            mtd = bars[i].low / prior_close - 1
            if ordinal == 1:
                if daily <= -0.0095:
                    result = "MATCH_RSP_MINUS_1"
                elif date.fromisoformat(day) == third_friday(year, mon):
                    result = "MATCH_THIRD_FRIDAY"
                else:
                    result = "UNMATCHED_FIRST_ADD"
                mechanical = True
            elif ordinal == 2:
                result = "MATCH_RSP_MTD_MINUS_5" if mtd <= -0.0495 else "UNMATCHED_SECOND_ADD"
                mechanical = True
            else:
                result = "DISCRETIONARY_THIRD_ADD"
                mechanical = False
            rows.append({"date": day, "month": month, "ordinal": ordinal, "intraday_change_pct": round(daily * 100, 4),
                         "intraday_month_change_pct": round(mtd * 100, 4), "result": result, "mechanical": mechanical,
                         "matched": result.startswith("MATCH_")})
    return rows


def current_rsp_state(trades: list[Trade], bars: list[Bar]) -> dict:
    latest = bars[-1]
    current = date.fromisoformat(latest.day)
    month = latest.day[:7]
    month_bars = [bar for bar in bars if bar.day.startswith(month)]
    first_i = bars.index(month_bars[0])
    prior_close = bars[first_i - 1].close if first_i else month_bars[0].open
    minus1 = None
    minus5 = None
    for bar in month_bars:
        i = bars.index(bar)
        daily = bar.low / bars[i - 1].close - 1 if i else 0
        if minus1 is None and daily <= -0.01:
            minus1 = bar.day
        if minus5 is None and bar.low / prior_close - 1 <= -0.05:
            minus5 = bar.day
    friday = third_friday(current.year, current.month)
    sessions_to_friday = sum(1 for n in range(1, max(0, (friday - current).days) + 1)
                             if (current + timedelta(days=n)).weekday() < 5)
    campaign_days = sorted({t.transaction_date for t in trades if t.activity == "Buy" and
                            campaign_type(t.transaction_date) == "recurring" and t.transaction_date.startswith(month)})
    return {"as_of": latest.day, "month_change_pct": (latest.close / prior_close - 1) * 100,
            "minus1_trigger_date": minus1, "minus5_trigger_date": minus5,
            "third_friday": friday.isoformat(), "estimated_sessions_to_third_friday": sessions_to_friday,
            "logged_campaigns_this_month": campaign_days}


def atr_at(bars: list[Bar], index: int, window: int = 14) -> float:
    ranges: list[float] = []
    for i in range(max(0, index - window + 1), index + 1):
        previous = bars[i - 1].close if i else bars[i].close
        ranges.append(max(bars[i].high - bars[i].low, abs(bars[i].high - previous), abs(bars[i].low - previous)))
    return statistics.fmean(ranges) if ranges else 0.0


def event_study(trades: list[Trade], prices: dict[str, list[Bar]]) -> list[dict]:
    events: list[dict] = []
    for trade in trades:
        if trade.activity != "Buy" or trade.symbol not in prices:
            continue
        bars = prices[trade.symbol]
        positions = {bar.day: i for i, bar in enumerate(bars)}
        if trade.transaction_date not in positions:
            continue
        i = positions[trade.transaction_date]
        if i + 3 >= len(bars):
            continue
        d0 = bars[i]
        future = bars[i + 1 : i + 4]
        episode = bars[i : i + 4]
        future_low = min(bar.low for bar in future)
        episode_low = min(bar.low for bar in episode)
        episode_high = max(bar.high for bar in episode)
        gap = trade.price / future_low - 1
        percentile = (trade.price - episode_low) / (episode_high - episode_low) if episode_high > episode_low else 0.5
        atr = atr_at(bars, i)
        d1_open = bars[i + 1].open
        d4_open = bars[i + 4].open if i + 4 < len(bars) else None
        limit05 = trade.price - 0.5 * atr
        limit10 = trade.price - atr
        fill05 = any(bar.low <= limit05 for bar in future)
        fill10 = any(bar.low <= limit10 for bar in future)
        staged = None if d4_open is None else 0.25 * d1_open + 0.25 * (limit05 if fill05 else d4_open) + 0.25 * (limit10 if fill10 else d4_open) + 0.25 * d4_open
        prior20 = bars[max(0, i - 19) : i + 1]
        future20 = bars[i + 1 : i + 21] if i + 20 < len(bars) else []
        prior20_high = max(bar.high for bar in prior20)
        future20_low = min((bar.low for bar in future20), default=None)
        future20_drawdown = None if future20_low is None else trade.price / future20_low - 1
        stage_high20 = None if future20_drawdown is None else trade.price >= prior20_high * 0.98 and future20_drawdown >= 0.05
        events.append({
            "transaction_date": trade.transaction_date, "campaign_type": campaign_type(trade.transaction_date),
            "symbol": trade.symbol, "author_price": round(trade.price, 6), "amount": round(abs(trade.total_amount), 2),
            "daily_low": round(d0.low, 6), "daily_high": round(d0.high, 6),
            "range_valid": d0.low * 0.9975 <= trade.price <= d0.high * 1.0025,
            "future_3d_low": round(future_low, 6), "gap_to_future_low_pct": round(gap * 100, 4),
            "near_low_0_5": gap <= 0.005, "near_low_1": gap <= 0.01, "near_low_2": gap <= 0.02,
            "episode_range_percentile": round(percentile, 4),
            "stage_high_proxy": percentile >= 0.67 and gap > 0.01,
            "prior_20d_high": round(prior20_high, 6),
            "future_20d_low": None if future20_low is None else round(future20_low, 6),
            "future_20d_drawdown_pct": None if future20_drawdown is None else round(future20_drawdown * 100, 4),
            "stage_high_20d_proxy": stage_high20,
            "d1_open": round(d1_open, 6), "d1_vs_author_pct": round((d1_open / trade.price - 1) * 100, 4),
            "d4_open": None if d4_open is None else round(d4_open, 6),
            "d4_vs_author_pct": None if d4_open is None else round((d4_open / trade.price - 1) * 100, 4),
            "atr14": round(atr, 6), "limit_0_5atr_filled": fill05, "limit_1atr_filled": fill10,
            "staged_price": None if staged is None else round(staged, 6),
            "staged_vs_author_pct": None if staged is None else round((staged / trade.price - 1) * 100, 4),
        })
    return events


def validate_executions(trades: list[Trade], prices: dict[str, list[Bar]]) -> tuple[int, int]:
    checked = passed = 0
    for trade in trades:
        if trade.activity != "Buy" or trade.symbol not in prices:
            continue
        bar = next((item for item in prices[trade.symbol] if item.day == trade.transaction_date), None)
        if bar is None:
            continue
        checked += 1
        passed += bar.low * 0.9975 <= trade.price <= bar.high * 1.0025
    return checked, passed


def mean(rows: Iterable[dict], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return statistics.fmean(values) if values else None


def pct(rows: list[dict], key: str) -> float | None:
    return 100 * sum(bool(row.get(key)) for row in rows) / len(rows) if rows else None


def pct_below_zero(rows: list[dict], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return 100 * sum(value < 0 for value in values) / len(values) if values else None


def pct_at_least(rows: list[dict], key: str, threshold: float) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return 100 * sum(value >= threshold for value in values) / len(values) if values else None


def pct_available(rows: list[dict], key: str) -> tuple[int, float | None]:
    values = [bool(row[key]) for row in rows if row.get(key) is not None]
    return len(values), (100 * sum(values) / len(values) if values else None)


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    if not cashflows or not any(v < 0 for _, v in cashflows) or not any(v > 0 for _, v in cashflows):
        return None
    origin = min(day for day, _ in cashflows)
    def npv(rate: float) -> float:
        return sum(value / ((1 + rate) ** ((day - origin).days / 365.25)) for day, value in cashflows)
    low, high = -0.999, 1.0
    while npv(low) * npv(high) > 0 and high < 1024:
        high *= 2
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        if npv(low) * npv(mid) <= 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def rebuild(trades: list[Trade], prices: dict[str, list[Bar]], sheet_latest: dict, author_stats: dict) -> dict:
    holdings: defaultdict[str, float] = defaultdict(float)
    buys = sells = gross_div = tax = 0.0
    cashflows: list[tuple[date, float]] = []
    for trade in trades:
        if trade.activity in {"Buy", "Sell"}:
            holdings[trade.symbol] += trade.quantity
        if trade.activity == "Buy":
            buys += -trade.total_amount
        elif trade.activity == "Sell":
            sells += trade.total_amount
        elif trade.activity == "Dividend":
            gross_div += trade.total_amount
        elif trade.activity == "Non resident tax":
            tax += trade.total_amount
        cashflows.append((date.fromisoformat(trade.transaction_date), trade.total_amount))
    independent_mv = sum(holdings[s] * prices[s][-1].close for s in CURRENT)
    asof = min(prices[s][-1].day for s in CURRENT)
    sheet_date = sheet_latest.get("date", asof)
    independent_sheet_mv = 0.0
    for symbol in CURRENT:
        bar = next((item for item in prices[symbol] if item.day == sheet_date), None)
        if bar:
            independent_sheet_mv += holdings[symbol] * bar.close
    cashflows.append((date.fromisoformat(asof), independent_mv))
    net_investment = buys - sells
    author_total = float(sheet_latest.get("total_mv") or independent_mv) + gross_div
    days = max(1, (date.fromisoformat(asof) - min(d for d, _ in cashflows)).days)
    author_cagr = (author_total / net_investment) ** (365.25 / days) - 1 if net_investment > 0 else None
    return {
        "as_of": asof, "holdings": {s: holdings[s] for s in SYMBOLS},
        "buy_cost": buys, "sell_proceeds": sells, "net_investment": net_investment,
        "gross_dividends": gross_div, "withholding_tax": tax, "net_dividends": gross_div + tax,
        "sheet_date": sheet_date, "sheet_market_value": sheet_latest.get("total_mv"),
        "independent_sheet_date_market_value": independent_sheet_mv, "independent_market_value": independent_mv,
        "author_total_value_formula": author_total, "author_formula_cagr": author_cagr,
        "estimated_xirr": xirr(cashflows), "author_year_stats": author_stats,
    }


def summarize(events: list[dict], portfolio: dict, sheet_latest: dict, prices: dict[str, list[Bar]], validation: tuple[int, int], rule_audit: list[dict], rsp_state: dict) -> dict:
    recurring = [row for row in events if row["campaign_type"] == "recurring"]
    campaign_days = sorted({row["transaction_date"] for row in recurring})
    checked, passed = validation
    close_diffs = []
    for symbol in CURRENT:
        node = sheet_latest.get(symbol, {})
        if node and number(node.get("close")):
            independent = next((b.close for b in prices[symbol] if b.day == sheet_latest.get("date")), None)
            if independent:
                close_diffs.append(abs(independent / number(node["close"]) - 1) * 100)
    by_symbol = {}
    stage20_n, stage20_pct = pct_available(recurring, "stage_high_20d_proxy")
    for symbol in CURRENT + ("MOAT",):
        rows = [row for row in recurring if row["symbol"] == symbol]
        if rows:
            by_symbol[symbol] = {"n": len(rows), "near_low_1_pct": pct(rows, "near_low_1"),
                                 "cheaper_0_5_pct": pct_at_least(rows, "gap_to_future_low_pct", 0.5),
                                 "cheaper_1_pct": pct_at_least(rows, "gap_to_future_low_pct", 1.0),
                                 "stage_high_proxy_pct": pct(rows, "stage_high_proxy"),
                                 "avg_gap_to_low_pct": mean(rows, "gap_to_future_low_pct"),
                                 "avg_d4_vs_author_pct": mean(rows, "d4_vs_author_pct")}
    return {
        "rule_version": RULE_VERSION, "portfolio": portfolio,
        "transactions": checked, "validated_transactions": passed,
        "validation_rate_pct": 100 * passed / checked if checked else None,
        "sheet_close_max_abs_diff_pct": max(close_diffs) if close_diffs else None,
        "recurring_campaigns": len(campaign_days), "recurring_trades": len(recurring),
        "near_low_0_5_pct": pct(recurring, "near_low_0_5"), "near_low_1_pct": pct(recurring, "near_low_1"),
        "near_low_2_pct": pct(recurring, "near_low_2"), "stage_high_proxy_pct": pct(recurring, "stage_high_proxy"),
        "stage_high_20d_n": stage20_n, "stage_high_20d_proxy_pct": stage20_pct,
        "avg_gap_to_future_low_pct": mean(recurring, "gap_to_future_low_pct"),
        "median_gap_to_future_low_pct": statistics.median(float(row["gap_to_future_low_pct"]) for row in recurring) if recurring else None,
        "future_lower_price_seen_pct": 100 * sum(float(row["gap_to_future_low_pct"]) > 0 for row in recurring) / len(recurring) if recurring else None,
        "future_0_5_cheaper_pct": pct_at_least(recurring, "gap_to_future_low_pct", 0.5),
        "future_1_cheaper_pct": pct_at_least(recurring, "gap_to_future_low_pct", 1.0),
        "avg_d1_vs_author_pct": mean(recurring, "d1_vs_author_pct"),
        "avg_d4_vs_author_pct": mean(recurring, "d4_vs_author_pct"),
        "d4_cheaper_pct": pct_below_zero(recurring, "d4_vs_author_pct"),
        "avg_staged_vs_author_pct": mean(recurring, "staged_vs_author_pct"),
        "staged_cheaper_pct": pct_below_zero(recurring, "staged_vs_author_pct"),
        "rsp_rule_audit": {"campaigns": len(rule_audit),
                           "mechanical_campaigns": sum(bool(row["mechanical"]) for row in rule_audit),
                           "matched_mechanical": sum(bool(row["mechanical"] and row["matched"]) for row in rule_audit),
                           "match_rate_pct": (100 * sum(bool(row["mechanical"] and row["matched"]) for row in rule_audit) /
                                              sum(bool(row["mechanical"]) for row in rule_audit)) if any(row["mechanical"] for row in rule_audit) else None},
        "current_rsp_state": rsp_state,
        "by_symbol": by_symbol,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(path, stream.getvalue())


def latest_campaign(trades: list[Trade]) -> tuple[str, list[Trade]]:
    buys = [t for t in trades if t.activity == "Buy" and campaign_type(t.transaction_date) == "recurring"]
    day = max(t.transaction_date for t in buys)
    return day, [t for t in buys if t.transaction_date == day]


def daily_rows(campaign_day: str, campaign: list[Trade], prices: dict[str, list[Bar]]) -> tuple[int, list[dict]]:
    result = []
    rsp_days = [bar.day for bar in prices["RSP"]]
    d_index = rsp_days.index(campaign_day)
    completed = len([day for day in rsp_days[d_index + 1 :] if day <= prices["RSP"][-1].day])
    for trade in campaign:
        bars = prices[trade.symbol]
        positions = {bar.day: i for i, bar in enumerate(bars)}
        i = positions[trade.transaction_date]
        current = bars[-1]
        atr = atr_at(bars, i)
        gain = current.close / trade.price - 1
        seen = bars[i + 1 : min(i + 4, len(bars))]
        best = min((bar.low for bar in seen), default=current.low)
        improvement = (trade.price / best - 1) * 100
        better = improvement >= 0.5
        if improvement >= 2:
            triggered = "是：达到 -2%，目标仓位100%"
        elif improvement >= 1:
            triggered = "是：达到 -1%，目标仓位50%"
        elif improvement >= 0.5:
            triggered = "是：达到 -0.5%，目标仓位25%"
        else:
            triggered = "否"
        if completed <= 3:
            action = "继续等到价提醒" if not better else "已出现买入提醒"
        else:
            action = "窗口结束，不追价"
        result.append({"symbol": trade.symbol, "author_price": trade.price, "current": current.close,
                       "vs_author_pct": gain * 100, "better_seen": better, "best_3d": best,
                       "improvement_pct": improvement, "triggered": triggered, "atr": atr,
                       "action": action})
    return completed, result


def update_ledger(trades: list[Trade], campaign_day: str, completed: int, run_at: str) -> dict:
    path = DATA / "signal_ledger.json"
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"episodes": {}}
    episodes = ledger.setdefault("episodes", {})
    first_run = not episodes
    for day in sorted({t.transaction_date for t in trades if t.activity == "Buy"}):
        episodes.setdefault(day, {"first_seen_at": run_at, "historical_backfill": first_run, "campaign_type": campaign_type(day)})
    episodes[campaign_day]["state"] = "CLOSED" if completed > 3 else f"WATCH_D{completed}"
    episodes[campaign_day]["last_updated_at"] = run_at
    atomic_text(path, json.dumps(ledger, ensure_ascii=False, indent=2))
    return ledger


def fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def render_daily(summary: dict, campaign_day: str, completed: int, rows: list[dict], stale: bool, late_backfill: bool) -> str:
    p = summary["portfolio"]
    if stale:
        permission = "DATA_INSUFFICIENT / 不新增风险"
    elif late_backfill:
        permission = "历史回填 / 不追单"
    elif completed < 3:
        permission = "三日观察窗口"
    elif completed == 3:
        permission = "D+4 缩量预案"
    else:
        permission = "等待下一次新披露"
    signal_count = sum(row["better_seen"] for row in rows)
    if late_backfill:
        direct_action = f"这是历史补录，不能现在追单。复盘结果：5只中有 {signal_count} 只曾出现至少便宜0.5%的买点。"
    elif completed <= 3 and signal_count:
        direct_action = f"有 {signal_count} 只 ETF 已达到更便宜的买入线，请看下表的分档仓位。"
    elif completed <= 3:
        direct_action = "尚未出现比作者便宜0.5%的价格，继续等提醒。"
    else:
        direct_action = "三日观察窗口已结束；没有新提醒就不追价，等待作者下一笔操作。"
    lines = [f"# Hi5 跟单执行卡｜{p['as_of']}", "", "## 今天直接看这里", "",
             f"**{direct_action}**", "",
             f"作者最近买入：{campaign_day}｜进度：D+{completed}｜状态：{permission}", "",
             "## 这次作者买入后，是否出现了更好的价格？", "",
             "“更好价格”统一定义为：比作者成交价至少便宜 **0.5%**。触发后才通知，不把几分钱波动当机会。", "",
             "| ETF | 作者价 | 历史上3日内便宜≥0.5%的概率 | 本次3日最低价 | 比作者便宜 | 是否触发买入提醒 |", "|---|---:|---:|---:|---:|---|"]
    for row in rows:
        probability = summary["by_symbol"].get(row["symbol"], {}).get("cheaper_0_5_pct")
        trigger = row["triggered"] + ("（历史复盘）" if late_backfill and row["better_seen"] else "")
        lines.append(f"| {row['symbol']} | ${row['author_price']:.2f} | {fmt_pct(probability)} | ${row['best_3d']:.2f} | {row['improvement_pct']:+.2f}% | {trigger} |")
    lines += ["", "## 收到提醒后怎么做", "", "- 首次到 **-0.5%**：买入计划金额的 **25%**。", "- 继续到 **-1.0%**：累计买到 **50%**。", "- 继续到 **-2.0%**：累计买到 **100%**。", "- D+3 结束仍未触发：不机械追涨，等待下一次作者操作；日报只提示机会成本，不会自动下单。", "",
              "## 历史依据（翻成一句话）", "",
              f"作者过去常规买入后，未来3个交易日出现至少便宜0.5%的概率是 **{fmt_pct(summary['future_0_5_cheaper_pct'])}**，至少便宜1%的概率是 **{fmt_pct(summary['future_1_cheaper_pct'])}**。但机械等到D+4并不划算：只有 {fmt_pct(summary['d4_cheaper_pct'])} 的样本更便宜。", "",
              "## 数据核验（附录，可跳过）", ""]
    stats = p.get("author_year_stats", {})
    bridge = stats.get("current_mv", 0) - stats.get("prior_year_end_mv", 0) - stats.get("year_net_input", 0) + stats.get("year_net_dividends", 0)
    lines += [f"- 独立行情验价：{summary['validated_transactions']}/{summary['transactions']} 笔通过（{fmt_pct(summary['validation_rate_pct'])}）；Sheet 收盘价最大偏差 {fmt_pct(summary['sheet_close_max_abs_diff_pct'])}。",
              f"- Sheet ETF 市值（{p['sheet_date']}）：${p['sheet_market_value']:,.2f}；同日独立收盘重估：${p['independent_sheet_date_market_value']:,.2f}。最新独立估值（{p['as_of']}）：${p['independent_market_value']:,.2f}。",
              f"- 累计净买入：${p['net_investment']:,.2f}；毛股息：${p['gross_dividends']:,.2f}；预扣税：${p['withholding_tax']:,.2f}。",
              f"- 作者公式总值（ETF市值+毛股息）：${p['author_total_value_formula']:,.2f}；该数不是可核验的券商现金总资产。",
              f"- 2026 年净收益桥接复算：${bridge:,.2f}；Sheet 声称：${stats.get('year_net_income', 0):,.2f}。",
              f"- 作者式 CAGR：{fmt_pct(None if p['author_formula_cagr'] is None else p['author_formula_cagr']*100)}；假设逐笔外部现金流的 XIRR：{fmt_pct(None if p['estimated_xirr'] is None else p['estimated_xirr']*100)}。TWR 因缺少完整出入金/现金余额不可计算。"]
    rsp = summary["current_rsp_state"]
    audit = summary["rsp_rule_audit"]
    lines += [f"- RSP 本月涨跌：{rsp['month_change_pct']:+.2f}%；-1% 首次日跌触发：{rsp['minus1_trigger_date'] or '未触发'}；-5% 月跌触发：{rsp['minus5_trigger_date'] or '未触发'}。",
              f"- 本月第三个周五：{rsp['third_friday']}，估算还剩 {rsp['estimated_sessions_to_third_friday']} 个交易日；已记录买入：{', '.join(rsp['logged_campaigns_this_month']) or '无'}。",
              f"- 2025 年起可机械核验 {audit['mechanical_campaigns']} 次，规则匹配 {audit['matched_mechanical']} 次（{fmt_pct(audit['match_rate_pct'])}）；第三笔主观买入不计入匹配率。",
              "- 新交易首次发现若已经晚于 D+3，只做历史记录；数据覆盖低于95%时不发买入提醒。", ""]
    return "\n".join(lines)


def render_research(summary: dict) -> str:
    p = summary["portfolio"]
    lines = ["# Hi5 组合真实性与三日择时核验", "", f"数据截至 {p['as_of']}。结论：交易日志可重建且成交价大体可由独立行情验证；作者的总资产和 CAGR 是自定义表格口径，不是经审计的账户收益率。", "",
             "## 可验证性", "", f"- 独立日内区间验价：{summary['validated_transactions']}/{summary['transactions']} 笔通过（{fmt_pct(summary['validation_rate_pct'])}）。",
             f"- Sheet ETF 市值（{p['sheet_date']}）${p['sheet_market_value']:,.2f}，同日独立收盘重估 ${p['independent_sheet_date_market_value']:,.2f}；最新独立估值（{p['as_of']}）${p['independent_market_value']:,.2f}。",
             f"- `Total Value` 可复算为 ETF 市值 + 累计毛股息 = ${p['author_total_value_formula']:,.2f}；但预扣税 ${abs(p['withholding_tax']):,.2f} 未从该总值扣除，也没有完整现金余额/出入金记录。",
             "- 因此，证券持仓与交易存在的可信度为中高；账户总资产、TWR、CAGR 的可信度为中低，不能称独立审计。", "",
             "## 三日择时结果", "", f"主样本排除了首仓和年度再平衡，共 {summary['recurring_campaigns']} 个常规批次、{summary['recurring_trades']} 笔 ETF 买入。",
             f"买价落在未来 D+1–D+3 最低点 1% 内的比例是 {fmt_pct(summary['near_low_1_pct'])}；落在 2% 内是 {fmt_pct(summary['near_low_2_pct'])}。三日高位代理比例是 {fmt_pct(summary['stage_high_proxy_pct'])}；20日阶段高点代理为 {fmt_pct(summary['stage_high_20d_proxy_pct'])}（{summary['stage_high_20d_n']} 笔有效样本）。",
             f"平均而言，未来三日最低价比作者买价低 {fmt_pct(summary['avg_gap_to_future_low_pct'])}（中位 {fmt_pct(summary['median_gap_to_future_low_pct'])}）；但直接等到 D+4 开盘平均反而贵 {fmt_pct(summary['avg_d4_vs_author_pct'])}，且只有 {fmt_pct(summary['d4_cheaper_pct'])} 的样本更便宜。", "",
             "| ETF | 样本 | 1%近低点 | 三日高位代理 | 平均后3日低点空间 | D+4价差 |", "|---|---:|---:|---:|---:|---:|"]
    for symbol, row in summary["by_symbol"].items():
        lines.append(f"| {symbol} | {row['n']} | {fmt_pct(row['near_low_1_pct'])} | {fmt_pct(row['stage_high_proxy_pct'])} | {fmt_pct(row['avg_gap_to_low_pct'])} | {fmt_pct(row['avg_d4_vs_author_pct'])} |")
    lines += ["", "## 可行性判断", "", "- 作为长期、规则化投入框架：可行。它分散了成长、动量、等权、REIT 和优先证券，但仍然全部属于风险资产，并非低风险现金替代。",
              f"- 2025 年起公开机械规则的可核验匹配率为 {fmt_pct(summary['rsp_rule_audit']['match_rate_pct'])}（{summary['rsp_rule_audit']['matched_mechanical']}/{summary['rsp_rule_audit']['mechanical_campaigns']}）；这支持规则大体被执行，但不验证第三笔主观条件。",
              "- 作为可精确复制的机械策略：不完全可行。历史规则变更，2023 年有人工干预，第三笔“人性之极”没有完整机械定义，披露时间也不总能历史还原。",
              "- 作为跟单择时信号：可行，但必须以首次发现时间为锚。建议执行固定的25%起始仓 + 三日限价观察 + D+4按上涨/ATR缩量，而不是假设作者总能抄底。", ""]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict:
    run_at = datetime.now(TZ).isoformat(timespec="seconds")
    trades_text = load_source("trades", args.offline, args.trades_csv)
    data_text = load_source("data", args.offline, args.data_csv)
    trades = parse_trades(trades_text)
    author_stats = parse_author_stats(trades_text)
    sheet_latest = parse_sheet_latest(data_text)
    prices = {symbol: fetch_bars(symbol, args.offline) for symbol in SYMBOLS}
    events = event_study(trades, prices)
    portfolio = rebuild(trades, prices, sheet_latest, author_stats)
    rule_audit = rsp_rule_audit(trades, prices["RSP"])
    summary = summarize(events, portfolio, sheet_latest, prices, validate_executions(trades, prices), rule_audit, current_rsp_state(trades, prices["RSP"]))
    campaign_day, campaign = latest_campaign(trades)
    completed, daily = daily_rows(campaign_day, campaign, prices)
    stale = (date.fromisoformat(portfolio["as_of"]) - date.fromisoformat(sheet_latest.get("date", portfolio["as_of"]))).days > 3 or (summary["validation_rate_pct"] or 0) < 95
    ledger = update_ledger(trades, campaign_day, completed, run_at)
    late_backfill = bool(ledger["episodes"][campaign_day].get("historical_backfill"))
    canonical = [asdict(t) | {"record_id": hashlib.sha256(f"{t.source_row}|{t.transaction_date}|{t.activity}|{t.symbol}|{t.quantity}|{t.total_amount}".encode()).hexdigest()[:16],
                               "source_hash": trade_hash(trades)} for t in trades]
    write_csv(DATA / "trade-log.csv", canonical)
    write_csv(DATA / "backtests" / "latest" / "event-study.csv", events)
    write_csv(DATA / "backtests" / "latest" / "rule-audit.csv", rule_audit)
    atomic_text(DATA / "backtests" / "latest" / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
    snapshot = {"generated_at": run_at, "source_hash": trade_hash(trades), "sheet_latest": sheet_latest,
                "summary": summary, "latest_campaign": {"date": campaign_day, "d_completed": completed, "rows": daily}}
    atomic_text(DATA / "latest_snapshot.json", json.dumps(snapshot, ensure_ascii=False, indent=2))
    history = DATA / "history.jsonl"
    previous = history.read_text(encoding="utf-8") if history.exists() else ""
    line = json.dumps({"generated_at": run_at, "as_of": portfolio["as_of"], "source_hash": trade_hash(trades),
                       "sheet_mv": portfolio["sheet_market_value"], "independent_mv": portfolio["independent_market_value"]}, ensure_ascii=False)
    last = None
    if previous.strip():
        try:
            last = json.loads(previous.strip().splitlines()[-1])
        except json.JSONDecodeError:
            last = None
    same_observation = bool(last and last.get("as_of") == portfolio["as_of"] and
                            last.get("source_hash") == trade_hash(trades) and
                            abs(float(last.get("independent_mv", 0)) - portfolio["independent_market_value"]) < 0.01)
    if not same_observation:
        atomic_text(history, previous + line + "\n")
    daily_text = render_daily(summary, campaign_day, completed, daily, stale, late_backfill)
    report_day = datetime.now(TZ).date().isoformat()
    atomic_text(ROOT / "reports" / "daily" / f"hi5-daily-{report_day}.md", daily_text)
    atomic_text(ROOT / "reports" / "research" / "hi5-validation-latest.md", render_research(summary))
    return snapshot


def self_test() -> None:
    sample = "note\nTransaction Date,Settlement Date,Activity Description,Description,Symbol,Quantity,Price,Price Currency,Total Amount,Total Currency\n2026-01-02,2026-01-05,Buy,x,RSP,10,100,USD,-1005,USD\n"
    parsed = parse_trades(sample)
    assert len(parsed) == 1 and parsed[0].symbol == "RSP" and parsed[0].total_amount == -1005
    flows = [(date(2024, 1, 1), -100), (date(2025, 1, 1), 110)]
    assert abs((xirr(flows) or 0) - 0.10) < 0.001
    print("self-test: OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--trades-csv", type=Path)
    parser.add_argument("--data-csv", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    snapshot = run(args)
    print(json.dumps({"as_of": snapshot["summary"]["portfolio"]["as_of"],
                      "report": str(ROOT / "reports" / "daily" / f"hi5-daily-{datetime.now(TZ).date().isoformat()}.md")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
