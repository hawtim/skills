#!/usr/bin/env python3
"""Backtest TheMarketMemo-style TQQQ barbell strategy.

The script is intentionally deterministic and auditable. It models the stock
and ETF legs from daily closes plus cash dividends, while treating futures and
options as documented proxies or exclusions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import sleep


INSTRUMENTS = {
    "TQQQ": {"code": "US.TQQQ", "name": "ProShares UltraPro QQQ"},
    "JEPQ": {"code": "US.JEPQ", "name": "JPMorgan Nasdaq Equity Premium Income ETF"},
    "JAAA": {"code": "US.JAAA", "name": "Janus Henderson AAA CLO ETF"},
    "SGOV": {"code": "US.SGOV", "name": "iShares 0-3 Month Treasury Bond ETF"},
    "QQQ": {"code": "US.QQQ", "name": "Invesco QQQ Trust"},
}

TARGET_WEIGHTS = {"TQQQ": 0.50, "JEPQ": 0.25, "JAAA": 0.25}
DIVIDEND_ASSETS = {"JEPQ", "JAAA"}
DEFENSIVE_ASSET = "JAAA"
BTD_LEVELS = [
    {"name": "btd_qqq_drawdown_12pct", "drawdown": 0.12, "reserve_fraction": 1 / 3, "hedge_close_fraction": 0.0},
    {"name": "btd_qqq_drawdown_20pct", "drawdown": 0.20, "reserve_fraction": 1 / 2, "hedge_close_fraction": 0.0},
    {"name": "btd_qqq_drawdown_30pct", "drawdown": 0.30, "reserve_fraction": 1.00, "hedge_close_fraction": 0.0},
]


@dataclass
class Portfolio:
    cash: float
    shares: dict[str, float] = field(default_factory=lambda: {"TQQQ": 0.0, "JEPQ": 0.0, DEFENSIVE_ASSET: 0.0})
    dividend_cash: float = 0.0
    hedge_notional: float = 0.0
    hedge_entry_qqq: float = 0.0
    qqq_high: float = 0.0
    high_watermark: float = 0.0
    btd_index: int = 0


def parse_yyyymmdd(value: str) -> str:
    if "-" in value:
        return value.replace("-", "")
    return value


def iso_date(value: str) -> str:
    value = value.replace("/", "-")
    if len(value) == 8 and "-" not in value:
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        rows = []
    if fieldnames is None and rows:
        fieldnames = list(rows[0].keys())
    elif fieldnames is None:
        fieldnames = []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fetch_yahoo_chart(symbol: str, begin: str, end: str) -> list[dict]:
    start = datetime.strptime(begin, "%Y%m%d").replace(tzinfo=timezone.utc)
    finish = datetime.strptime(end, "%Y%m%d").replace(tzinfo=timezone.utc)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?"
        f"period1={int(start.timestamp())}&period2={int(finish.timestamp()) + 86400}"
        "&interval=1d&events=history&includeAdjustedClose=false"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.load(response)
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"No Yahoo chart data for {symbol}")
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    rows = []
    for i, ts in enumerate(timestamps):
        close = quote.get("close", [None])[i]
        if close is None:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": float(quote.get("open", [None])[i] or close),
                "high": float(quote.get("high", [None])[i] or close),
                "low": float(quote.get("low", [None])[i] or close),
                "close": float(close),
                "volume": float(quote.get("volume", [0])[i] or 0),
            }
        )
    return rows


def fetch_futu_history(code: str, begin: str, end: str, rehab: str) -> list[dict]:
    try:
        from futu import AuType, KLType, OpenQuoteContext, RET_OK
    except ImportError as exc:
        raise RuntimeError("futu-api is not installed. Install it or use --source yahoo.") from exc

    autype = {"none": AuType.NONE, "forward": AuType.QFQ, "backward": AuType.HFQ}[rehab]
    begin_dash = iso_date(begin)
    end_dash = iso_date(end)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    frames = []
    try:
        page_req_key = None
        while True:
            ret, data, page_req_key = ctx.request_history_kline(
                code,
                start=begin_dash,
                end=end_dash,
                ktype=KLType.K_DAY,
                autype=autype,
                max_count=1000,
                page_req_key=page_req_key,
            )
            if ret != RET_OK:
                raise RuntimeError(f"Futu returned error for {code}: {data}")
            frames.append(data)
            if page_req_key is None:
                break
    finally:
        ctx.close()

    rows = []
    for frame in frames:
        for _, row in frame.iterrows():
            rows.append(
                {
                    "date": str(row["time_key"])[:10],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0) or 0),
                }
            )
    return rows


def parse_dividend_amount(statement: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*USD", statement or "")
    if not match:
        return None
    return float(match.group(1))


def fetch_futu_dividends(codes: dict[str, str]) -> list[dict]:
    try:
        from futu import OpenQuoteContext, RET_OK
    except ImportError as exc:
        raise RuntimeError("futu-api is not installed. Dividend fetch requires Futu.") from exc

    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    rows: list[dict] = []
    try:
        for symbol, code in codes.items():
            ret, data = ctx.get_corporate_actions_dividends(code)
            if ret != RET_OK:
                raise RuntimeError(f"Futu returned dividend error for {code}: {data}")
            for item in (data or {}).get("dividend_list", []):
                amount = parse_dividend_amount(item.get("statement", ""))
                if amount is None:
                    continue
                rows.append(
                    {
                        "symbol": symbol,
                        "code": code,
                        "ex_date": iso_date(item.get("ex_date", "")),
                        "pay_date": iso_date(item.get("dividend_payable_date", "")),
                        "dividend_per_share": amount,
                        "statement": item.get("statement", ""),
                    }
                )
            sleep(0.1)
    finally:
        ctx.close()
    return rows


def load_prices(source: str, begin: str, end: str, rehab: str) -> tuple[dict[str, dict[str, dict]], list[dict]]:
    yahoo_symbols = {"TQQQ": "TQQQ", "JEPQ": "JEPQ", "JAAA": "JAAA", "SGOV": "SGOV", "QQQ": "QQQ"}
    all_prices: dict[str, dict[str, dict]] = {}
    price_rows: list[dict] = []
    for symbol, meta in INSTRUMENTS.items():
        if source == "futu":
            rows = fetch_futu_history(meta["code"], begin, end, rehab)
        else:
            rows = fetch_yahoo_chart(yahoo_symbols[symbol], begin, end)
        if not rows:
            raise RuntimeError(f"No price rows for {symbol}")
        all_prices[symbol] = {row["date"]: row for row in rows}
        for row in rows:
            price_rows.append({"symbol": symbol, "code": meta["code"], "name": meta["name"], **row})
    return all_prices, price_rows


def moving_average(values: list[float], end_index: int, window: int) -> float | None:
    if end_index + 1 < window:
        return None
    subset = values[end_index + 1 - window : end_index + 1]
    return sum(subset) / window


def next_trading_day(dates: list[str], day: str) -> str | None:
    for candidate in dates:
        if candidate >= day:
            return candidate
    return None


def month_end_dates(dates: list[str]) -> set[str]:
    out: dict[str, str] = {}
    for day in dates:
        out[day[:7]] = day
    return set(out.values())


def prices_on(all_prices: dict[str, dict[str, dict]], day: str) -> dict[str, float]:
    return {symbol: all_prices[symbol][day]["close"] for symbol in all_prices}


def hedge_unrealized(portfolio: Portfolio, qqq_price: float) -> float:
    if portfolio.hedge_notional <= 0 or portfolio.hedge_entry_qqq <= 0:
        return 0.0
    return portfolio.hedge_notional * (1 - qqq_price / portfolio.hedge_entry_qqq)


def asset_value(portfolio: Portfolio, prices: dict[str, float], symbol: str) -> float:
    return portfolio.shares.get(symbol, 0.0) * prices[symbol]


def market_value(portfolio: Portfolio, prices: dict[str, float]) -> float:
    return sum(asset_value(portfolio, prices, symbol) for symbol in TARGET_WEIGHTS)


def total_value(portfolio: Portfolio, prices: dict[str, float]) -> float:
    return portfolio.cash + market_value(portfolio, prices) + hedge_unrealized(portfolio, prices["QQQ"])


def buy(portfolio: Portfolio, symbol: str, amount: float, prices: dict[str, float]) -> float:
    amount = max(0.0, min(amount, portfolio.cash))
    if amount <= 0:
        return 0.0
    portfolio.shares[symbol] = portfolio.shares.get(symbol, 0.0) + amount / prices[symbol]
    portfolio.cash -= amount
    portfolio.dividend_cash = max(0.0, portfolio.dividend_cash - amount)
    return amount


def sell(portfolio: Portfolio, symbol: str, amount: float, prices: dict[str, float]) -> float:
    available = asset_value(portfolio, prices, symbol)
    amount = max(0.0, min(amount, available))
    if amount <= 0:
        return 0.0
    portfolio.shares[symbol] -= amount / prices[symbol]
    portfolio.cash += amount
    return amount


def buy_tqqq_from_reserve(portfolio: Portfolio, amount: float, prices: dict[str, float]) -> float:
    if amount <= 0:
        return 0.0
    if portfolio.cash < amount:
        sell_needed = amount - portfolio.cash
        sell(portfolio, DEFENSIVE_ASSET, sell_needed, prices)
    return buy(portfolio, "TQQQ", amount, prices)


def open_hedge(portfolio: Portfolio, prices: dict[str, float]) -> float:
    if portfolio.hedge_notional > 0:
        return 0.0
    notional = asset_value(portfolio, prices, "TQQQ") + asset_value(portfolio, prices, "JEPQ")
    if notional <= 0:
        return 0.0
    portfolio.hedge_notional = notional
    portfolio.hedge_entry_qqq = prices["QQQ"]
    return notional


def close_hedge(portfolio: Portfolio, prices: dict[str, float], fraction: float) -> float:
    if portfolio.hedge_notional <= 0:
        return 0.0
    fraction = max(0.0, min(1.0, fraction))
    realized = hedge_unrealized(portfolio, prices["QQQ"]) * fraction
    portfolio.cash += realized
    portfolio.hedge_notional *= 1 - fraction
    if portfolio.hedge_notional <= 1e-6:
        portfolio.hedge_notional = 0.0
        portfolio.hedge_entry_qqq = 0.0
    return realized


def initial_build(portfolio: Portfolio, prices: dict[str, float], principal: float, logs: list[dict], day: str, strategy: str) -> None:
    for symbol, weight in TARGET_WEIGHTS.items():
        spent = buy(portfolio, symbol, principal * weight, prices)
        logs.append(log_row(strategy, day, "buy", "initial_50_25_25_build", symbol, prices[symbol], spent, portfolio, prices, "初始50/25/25建仓"))


def log_row(
    strategy: str,
    day: str,
    action: str,
    trigger: str,
    symbol: str,
    price: float,
    amount: float,
    portfolio: Portfolio,
    prices: dict[str, float],
    notes: str,
) -> dict:
    return {
        "strategy": strategy,
        "date": day,
        "action": action,
        "trigger": trigger,
        "symbol": symbol,
        "price": round(price, 4) if price else "",
        "amount": round(amount, 2),
        "cash": round(portfolio.cash, 2),
        "dividend_cash": round(portfolio.dividend_cash, 2),
        "tqqq_weight": round(asset_value(portfolio, prices, "TQQQ") / total_value(portfolio, prices), 6) if total_value(portfolio, prices) > 0 else 0,
        "hedge_notional": round(portfolio.hedge_notional, 2),
        "notes": notes,
    }


def nav_row(strategy: str, day: str, portfolio: Portfolio, prices: dict[str, float], qqq_ma200: float | None, qqq_drawdown: float) -> dict:
    tv = total_value(portfolio, prices)
    row = {
        "strategy": strategy,
        "date": day,
        "total_value": round(tv, 2),
        "cash": round(portfolio.cash, 2),
        "dividend_cash": round(portfolio.dividend_cash, 2),
        "market_value": round(market_value(portfolio, prices), 2),
        "hedge_notional": round(portfolio.hedge_notional, 2),
        "hedge_unrealized": round(hedge_unrealized(portfolio, prices["QQQ"]), 2),
        "qqq_drawdown_from_high": round(qqq_drawdown, 6),
        "qqq_close": round(prices["QQQ"], 4),
        "qqq_ma200": round(qqq_ma200, 4) if qqq_ma200 else "",
    }
    for symbol in TARGET_WEIGHTS:
        row[f"shares_{symbol.lower()}"] = round(portfolio.shares[symbol], 6)
        row[f"value_{symbol.lower()}"] = round(asset_value(portfolio, prices, symbol), 2)
        row[f"weight_{symbol.lower()}"] = round(asset_value(portfolio, prices, symbol) / tv, 6) if tv > 0 else 0
    return row


def prepare_dividend_events(dividends: list[dict], dates: list[str]) -> dict[str, dict[str, list[dict]]]:
    events = {"ex": {}, "pay": {}}
    for item in dividends:
        if item["symbol"] not in DIVIDEND_ASSETS:
            continue
        ex_day = next_trading_day(dates, item["ex_date"])
        pay_day = next_trading_day(dates, item["pay_date"])
        if not ex_day or not pay_day:
            continue
        enriched = {**item, "ex_trading_day": ex_day, "pay_trading_day": pay_day}
        events["ex"].setdefault(ex_day, []).append(enriched)
    return events


def run_strategy(
    strategy: str,
    dates: list[str],
    all_prices: dict[str, dict[str, dict]],
    dividends: list[dict],
    principal: float,
    start_index: int,
    include_hedge: bool,
) -> tuple[list[dict], list[dict], dict]:
    portfolio = Portfolio(cash=principal)
    logs: list[dict] = []
    nav_rows: list[dict] = []
    pending_dividends: dict[str, list[dict]] = {}
    dividend_events = prepare_dividend_events(dividends, dates)
    qqq_closes = [all_prices["QQQ"][day]["close"] for day in dates]

    first_day = dates[start_index]
    first_prices = prices_on(all_prices, first_day)
    if strategy == "tqqq_buy_hold":
        spent = buy(portfolio, "TQQQ", principal, first_prices)
        logs.append(log_row(strategy, first_day, "buy", "initial_100pct_tqqq", "TQQQ", first_prices["TQQQ"], spent, portfolio, first_prices, "100% TQQQ参照"))
    else:
        initial_build(portfolio, first_prices, principal, logs, first_day, strategy)
    portfolio.qqq_high = first_prices["QQQ"]

    for i, day in enumerate(dates):
        if i < start_index:
            continue
        prices = prices_on(all_prices, day)
        qqq_ma200 = moving_average(qqq_closes, i, 200)
        qqq_below_hedge_line = qqq_ma200 is not None and prices["QQQ"] < qqq_ma200 * 0.97
        qqq_above_unhedge_line = qqq_ma200 is not None and prices["QQQ"] > qqq_ma200 * 1.03

        if prices["QQQ"] > portfolio.qqq_high:
            portfolio.qqq_high = prices["QQQ"]
            portfolio.btd_index = 0
        qqq_drawdown = 0.0 if portfolio.qqq_high <= 0 else prices["QQQ"] / portfolio.qqq_high - 1

        for item in dividend_events["ex"].get(day, []):
            amount = portfolio.shares.get(item["symbol"], 0.0) * item["dividend_per_share"]
            if amount <= 0:
                continue
            pending_dividends.setdefault(item["pay_trading_day"], []).append({**item, "cash_amount": amount})
            logs.append(log_row(strategy, day, "dividend_accrual", "ex_date_dividend_accrual", item["symbol"], prices[item["symbol"]], amount, portfolio, prices, item["statement"]))

        for item in pending_dividends.pop(day, []):
            amount = item["cash_amount"]
            portfolio.cash += amount
            portfolio.dividend_cash += amount
            logs.append(log_row(strategy, day, "dividend_cash_in", "dividend_payable_date", item["symbol"], prices[item["symbol"]], amount, portfolio, prices, "分红入现金"))

        if strategy == "tqqq_barbell_strategy":
            if include_hedge and qqq_below_hedge_line and portfolio.hedge_notional <= 0:
                notional = open_hedge(portfolio, prices)
                logs.append(log_row(strategy, day, "open_hedge", "qqq_below_200ma_minus_3pct", "QQQ", prices["QQQ"], notional, portfolio, prices, "QQQ空头代理NQ/MNQ对冲"))

            while portfolio.btd_index < len(BTD_LEVELS) and -qqq_drawdown >= BTD_LEVELS[portfolio.btd_index]["drawdown"]:
                level = BTD_LEVELS[portfolio.btd_index]
                if include_hedge and portfolio.hedge_notional > 0:
                    realized = close_hedge(portfolio, prices, level["hedge_close_fraction"])
                    logs.append(log_row(strategy, day, "close_hedge", f"{level['name']}_partial_hedge_close", "QQQ", prices["QQQ"], realized, portfolio, prices, "BTD触发后按档位平掉部分对冲"))
                reserve = portfolio.cash + asset_value(portfolio, prices, DEFENSIVE_ASSET)
                buy_amount = reserve * level["reserve_fraction"]
                spent = buy_tqqq_from_reserve(portfolio, buy_amount, prices)
                logs.append(log_row(strategy, day, "buy", level["name"], "TQQQ", prices["TQQQ"], spent, portfolio, prices, "动用现金储备买入TQQQ"))
                portfolio.btd_index += 1

            if include_hedge and portfolio.hedge_notional > 0 and portfolio.btd_index == 0 and qqq_above_unhedge_line:
                realized = close_hedge(portfolio, prices, 1.0)
                logs.append(log_row(strategy, day, "close_hedge", "qqq_above_200ma_plus_3pct", "QQQ", prices["QQQ"], realized, portfolio, prices, "未触发BTD，QQQ回到200MA+3%以上解除对冲"))

            tv = total_value(portfolio, prices)
            tqqq_weight = asset_value(portfolio, prices, "TQQQ") / tv if tv > 0 else 0.0
            if tqqq_weight >= 0.65:
                target_value = tv * TARGET_WEIGHTS["TQQQ"]
                sell_amount = asset_value(portfolio, prices, "TQQQ") - target_value
                sold = sell(portfolio, "TQQQ", sell_amount, prices)
                bought = buy(portfolio, DEFENSIVE_ASSET, sold, prices)
                logs.append(log_row(strategy, day, "rebalance", "tqqq_weight_65pct_rebalance_to_50_25_25", "TQQQ", prices["TQQQ"], sold, portfolio, prices, f"卖出TQQQ并买入{DEFENSIVE_ASSET} {bought:.2f}"))

        portfolio.high_watermark = max(portfolio.high_watermark, total_value(portfolio, prices))
        nav_rows.append(nav_row(strategy, day, portfolio, prices, qqq_ma200, qqq_drawdown))

    ending = nav_rows[-1]
    max_drawdown = 0.0
    peak = -math.inf
    for row in nav_rows:
        peak = max(peak, row["total_value"])
        drawdown = row["total_value"] / peak - 1 if peak > 0 else 0.0
        max_drawdown = min(max_drawdown, drawdown)
    summary = {
        "strategy": strategy,
        "start_date": nav_rows[0]["date"],
        "end_date": nav_rows[-1]["date"],
        "principal": round(principal, 2),
        "ending_total_value": ending["total_value"],
        "total_return": round(ending["total_value"] / principal - 1, 6),
        "max_drawdown": round(max_drawdown, 6),
        "ending_cash": ending["cash"],
        "ending_dividend_cash": ending["dividend_cash"],
        "ending_hedge_notional": ending["hedge_notional"],
        "ending_tqqq_weight": ending["weight_tqqq"],
        "trade_count": len([row for row in logs if row["action"] in {"buy", "rebalance", "open_hedge", "close_hedge"}]),
        "dividend_events": len([row for row in logs if row["action"] == "dividend_cash_in"]),
    }
    return nav_rows, logs, summary


def render_report(path: Path, summaries: list[dict], args: argparse.Namespace, source_note: str) -> None:
    by_strategy = {row["strategy"]: row for row in summaries}
    strategy = by_strategy["tqqq_barbell_strategy"]
    static = by_strategy["static_50_25_25"]
    tqqq = by_strategy["tqqq_buy_hold"]

    def pct(value: float) -> str:
        return f"{value * 100:.2f}%"

    lines = [
        "# TQQQ 槓鈴策略回测",
        "",
        f"回测区间：{strategy['start_date']} 至 {strategy['end_date']}；本金：{args.principal:,.2f} USD。",
        f"数据来源：{source_note}。",
        "",
        "## 结论",
        "",
        f"- 策略期末收益：{pct(strategy['total_return'])}，最大回撤：{pct(strategy['max_drawdown'])}。",
        f"- 静态 50/25/25 参照收益：{pct(static['total_return'])}，最大回撤：{pct(static['max_drawdown'])}。",
        f"- 100% TQQQ 参照收益：{pct(tqqq['total_return'])}，最大回撤：{pct(tqqq['max_drawdown'])}。",
        f"- 期末 TQQQ 权重：{pct(strategy['ending_tqqq_weight'])}；期末对冲名义本金：{strategy['ending_hedge_notional']:,.2f} USD。",
        "",
        "## 规则量化口径",
        "",
        "- 初始资产按 TQQQ/JEPQ/JAAA = 50%/25%/25% 建仓。",
        "- JEPQ 与 JAAA 分红按 Futu 派息日进入现金储备。",
        "- QQQ 从最近历史高点回撤 -12%/-20%/-30% 时，按规则动用现金和 JAAA 储备买入 TQQQ。",
        "- 默认不量化期货对冲；如显式传入 --include-hedge，则用 QQQ 空头代理 NQ/MNQ 的方向性损益。",
        "- TQQQ 权重达到 65% 时恢复到 TQQQ/JEPQ/JAAA = 50%/25%/25%。",
        "",
        "## 未量化项",
        "",
        "- VIX 接近 12 的 QQQ Put 黑天鹅保险需要 VIX 与连续期权链；本次不估算保险成本或赔付。",
        "- 凸性 QQQ Call 增持需要期权链和趋势判定；本次不估算收益。",
        "- 未计佣金、滑点、税费、融资利息、期货保证金收益和期货展期。",
        "",
        "来源：TheMarketMemo Patreon 文章《TQQQ 槓鈴策略》。非投资建议。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--begin", default="20250101", help="Data begin date for lookback, YYYYMMDD")
    parser.add_argument("--strategy-start", default="20260102", help="Strategy start date, YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--end", default="20260626", help="Backtest end date, YYYYMMDD")
    parser.add_argument("--principal", type=float, default=100000.0)
    parser.add_argument("--source", choices=["futu", "yahoo"], default="futu")
    parser.add_argument("--rehab", choices=["none", "forward", "backward"], default="none")
    parser.add_argument("--include-hedge", action="store_true", help="Include a deterministic QQQ short proxy for the optional NQ/MNQ hedge.")
    parser.add_argument("--out-dir", default="US-share/tqqq-long-term-rolling-strategy/backtests/2026-h1")
    args = parser.parse_args()

    begin = parse_yyyymmdd(args.begin)
    end = parse_yyyymmdd(args.end)
    strategy_start = iso_date(args.strategy_start)
    out_dir = Path(args.out_dir)

    all_prices, price_rows = load_prices(args.source, begin, end, args.rehab)
    dates = sorted(set.intersection(*(set(rows.keys()) for rows in all_prices.values())))
    if not dates:
        raise RuntimeError("No common trading dates across instruments")
    start_candidates = [i for i, day in enumerate(dates) if day >= strategy_start]
    if not start_candidates:
        raise RuntimeError(f"No trading date on or after strategy start {strategy_start}")
    start_index = start_candidates[0]

    if args.source == "futu":
        dividends = fetch_futu_dividends({symbol: INSTRUMENTS[symbol]["code"] for symbol in DIVIDEND_ASSETS})
        source_note = f"Futu OpenD 日线（rehab={args.rehab}）与 Futu 分红派息"
    else:
        dividends = []
        source_note = "Yahoo Finance 日线；未拉取分红派息"

    all_nav: list[dict] = []
    all_logs: list[dict] = []
    summaries: list[dict] = []
    for strategy in ["tqqq_barbell_strategy", "static_50_25_25", "tqqq_buy_hold"]:
        nav, logs, summary = run_strategy(
            strategy,
            dates,
            all_prices,
            dividends,
            args.principal,
            start_index,
            include_hedge=args.include_hedge,
        )
        all_nav.extend(nav)
        all_logs.extend(logs)
        summaries.append(summary)

    dividend_rows = sorted(dividends, key=lambda row: (row["symbol"], row["ex_date"], row["pay_date"]))
    write_csv(out_dir / "prices_daily.csv", price_rows)
    write_csv(out_dir / "dividends.csv", dividend_rows)
    write_csv(out_dir / "nav.csv", all_nav)
    write_csv(out_dir / "operation_log.csv", all_logs)
    write_csv(out_dir / "summary.csv", summaries)
    render_report(out_dir / "backtest_report.md", summaries, args, source_note)

    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
