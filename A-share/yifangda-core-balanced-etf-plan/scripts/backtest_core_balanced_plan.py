#!/usr/bin/env python3
"""Fetch ETF daily data and backtest the 易方达核心均衡 ETF plan.

Assumptions:
- Daily close execution.
- Fractional shares are allowed for clean allocation math.
- Fees, slippage, taxes, and dividends are ignored unless reflected in prices.
- Subjective build language is converted into deterministic drawdown/time triggers.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ETFS = [
    {"code": "159259", "name": "成长ETF易方达", "yahoo": "159259.SZ", "weight": 0.30, "lower": 0.24, "upper": 0.36},
    {"code": "159222", "name": "自由现金流ETF易方达", "yahoo": "159222.SZ", "weight": 0.40, "lower": 0.32, "upper": 0.48},
    {"code": "515180", "name": "红利ETF易方达", "yahoo": "515180.SS", "weight": 0.30, "lower": 0.24, "upper": 0.36},
]


@dataclass
class Portfolio:
    cash: float
    shares: dict[str, float]
    invested: float = 0.0
    high_watermark: float = 0.0


def fetch_yahoo_chart(symbol: str, begin: str, end: str) -> list[dict[str, str | float]]:
    start = datetime.strptime(begin, "%Y%m%d").replace(tzinfo=timezone.utc)
    finish = datetime.strptime(end, "%Y%m%d").replace(tzinfo=timezone.utc)
    period1 = int(start.timestamp())
    period2 = int(finish.timestamp()) + 24 * 60 * 60
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?"
        f"period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"No Yahoo data returned for {symbol}")
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    rows = []
    for i, ts in enumerate(timestamps):
        close = quote.get("close", [None])[i]
        if close is None:
            continue
        open_price = quote.get("open", [None])[i]
        high = quote.get("high", [None])[i]
        low = quote.get("low", [None])[i]
        volume = quote.get("volume", [None])[i]
        rows.append(
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": float(open_price) if open_price is not None else "",
                "close": float(close),
                "high": float(high) if high is not None else "",
                "low": float(low) if low is not None else "",
                "volume": float(volume) if volume is not None else "",
                "adj_close": float(adj[i]) if i < len(adj) and adj[i] is not None else "",
            }
        )
    return adjust_yahoo_price_discontinuities(rows)


def adjust_yahoo_price_discontinuities(rows: list[dict[str, str | float]]) -> list[dict[str, str | float]]:
    adjusted: list[dict[str, str | float]] = []
    factor = 1.0
    previous_adjusted_close: float | None = None
    for row in rows:
        raw_close = float(row["close"])
        tentative_close = raw_close * factor
        if previous_adjusted_close and tentative_close > 0:
            ratio = tentative_close / previous_adjusted_close
            if ratio > 1.45 or ratio < 1 / 1.45:
                factor *= previous_adjusted_close / tentative_close
                tentative_close = raw_close * factor
        new_row = dict(row)
        for field in ("open", "close", "high", "low", "adj_close"):
            value = row.get(field)
            if value != "":
                new_row[f"raw_{field}"] = value
                new_row[field] = float(value) * factor
        adjusted.append(new_row)
        previous_adjusted_close = tentative_close
    return adjusted


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def month_end_dates(dates: list[str]) -> set[str]:
    last_by_month: dict[str, str] = {}
    for day in dates:
        last_by_month[day[:7]] = day
    return set(last_by_month.values())


def first_trading_dates_by_month(dates: list[str]) -> list[str]:
    first_by_month: dict[str, str] = {}
    for day in dates:
        first_by_month.setdefault(day[:7], day)
    return [first_by_month[m] for m in sorted(first_by_month)]


def prices_on(all_prices: dict[str, dict[str, dict]], day: str) -> dict[str, float]:
    return {code: all_prices[code][day]["close"] for code in all_prices}


def market_value(portfolio: Portfolio, prices: dict[str, float]) -> float:
    return sum(portfolio.shares.get(code, 0.0) * price for code, price in prices.items())


def total_value(portfolio: Portfolio, prices: dict[str, float]) -> float:
    return portfolio.cash + market_value(portfolio, prices)


def weights(portfolio: Portfolio, prices: dict[str, float]) -> dict[str, float]:
    mv = market_value(portfolio, prices)
    if mv <= 0:
        return {etf["code"]: 0.0 for etf in ETFS}
    return {code: portfolio.shares.get(code, 0.0) * prices[code] / mv for code in prices}


def buy_target_notional(
    portfolio: Portfolio,
    prices: dict[str, float],
    notional: float,
    trigger: str,
    day: str,
    logs: list[dict],
    principal_cap: float,
    strategy: str,
) -> None:
    for etf in ETFS:
        amount = notional * etf["weight"]
        if amount <= 0:
            continue
        code = etf["code"]
        price = prices[code]
        portfolio.shares[code] = portfolio.shares.get(code, 0.0) + amount / price
        portfolio.cash -= amount
        portfolio.invested += amount
        logs.append(
            {
                "strategy": strategy,
                "trade_date": day,
                "action_type": "buy",
                "trigger_type": trigger,
                "etf_code": code,
                "etf_name": etf["name"],
                "price": round(price, 4),
                "amount": round(amount, 2),
                "principal_cap": round(principal_cap, 2),
                "total_principal_invested_after_trade": round(portfolio.invested, 2),
                "notes": "按目标权重买入",
            }
        )


def rebalance_month_end(
    portfolio: Portfolio,
    prices: dict[str, float],
    day: str,
    logs: list[dict],
    principal_cap: float,
    strategy: str,
) -> None:
    current_weights = weights(portfolio, prices)
    mv = market_value(portfolio, prices)
    if mv <= 0:
        return

    for etf in ETFS:
        code = etf["code"]
        current_weight = current_weights[code]
        target_weight = etf["weight"]
        if current_weight <= etf["upper"] + 0.03:
            continue
        target_value = mv * target_weight
        current_value = portfolio.shares[code] * prices[code]
        sell_amount = max(0.0, current_value - target_value)
        if sell_amount <= 0:
            continue
        portfolio.shares[code] -= sell_amount / prices[code]
        portfolio.cash += sell_amount
        logs.append(
            {
                "strategy": strategy,
                "trade_date": day,
                "action_type": "sell",
                "trigger_type": "month_end_rebalance_over_upper_plus_3pct",
                "etf_code": code,
                "etf_name": etf["name"],
                "price": round(prices[code], 4),
                "amount": round(sell_amount, 2),
                "principal_cap": round(principal_cap, 2),
                "total_principal_invested_after_trade": round(portfolio.invested, 2),
                "notes": "超上限3个百分点以上，卖回目标权重",
            }
        )

    current_weights = weights(portfolio, prices)
    mv = market_value(portfolio, prices)
    for etf in ETFS:
        code = etf["code"]
        principal_capacity = max(0.0, principal_cap - portfolio.invested)
        investable_cash = min(portfolio.cash, principal_capacity)
        if investable_cash <= 1:
            break
        if current_weights[code] >= etf["lower"]:
            continue
        target_value = mv * etf["weight"]
        current_value = portfolio.shares.get(code, 0.0) * prices[code]
        buy_amount = min(investable_cash, max(0.0, target_value - current_value))
        if buy_amount <= 0:
            continue
        portfolio.shares[code] = portfolio.shares.get(code, 0.0) + buy_amount / prices[code]
        portfolio.cash -= buy_amount
        portfolio.invested += buy_amount
        logs.append(
            {
                "strategy": strategy,
                "trade_date": day,
                "action_type": "buy",
                "trigger_type": "month_end_rebalance_below_lower",
                "etf_code": code,
                "etf_name": etf["name"],
                "price": round(prices[code], 4),
                "amount": round(buy_amount, 2),
                "principal_cap": round(principal_cap, 2),
                "total_principal_invested_after_trade": round(portfolio.invested, 2),
                "notes": "低于下限，用现金补回目标权重",
            }
        )


def run_strategy(
    name: str,
    dates: list[str],
    all_prices: dict[str, dict[str, dict]],
    principal_cap: float,
) -> tuple[list[dict], list[dict], dict]:
    portfolio = Portfolio(cash=principal_cap, shares={etf["code"]: 0.0 for etf in ETFS})
    nav_rows: list[dict] = []
    logs: list[dict] = []
    month_ends = month_end_dates(dates)
    first_by_month = first_trading_dates_by_month(dates)
    principal_tranches = [
        {"drawdown": 0.03, "fallback_day": 5, "pct": 0.20, "drawdown_trigger": "drawdown_3pct_principal_add", "time_trigger": "time_5_trading_days_principal_add"},
        {"drawdown": 0.06, "fallback_day": 20, "pct": 0.20, "drawdown_trigger": "drawdown_6pct_principal_add", "time_trigger": "time_20_trading_days_principal_add"},
        {"drawdown": 0.10, "fallback_day": 40, "pct": 0.20, "drawdown_trigger": "drawdown_10pct_principal_add", "time_trigger": "time_40_trading_days_principal_add"},
    ]
    trigger_index = 0

    for i, day in enumerate(dates):
        prices = prices_on(all_prices, day)

        if i == 0:
            buy_target_notional(portfolio, prices, principal_cap * 0.40, "initial_40pct_build", day, logs, principal_cap, name)

        tv = total_value(portfolio, prices)
        portfolio.high_watermark = max(portfolio.high_watermark, tv)
        drawdown = 0.0 if portfolio.high_watermark <= 0 else tv / portfolio.high_watermark - 1

        if name == "triggered_plan" and i > 0 and trigger_index < len(principal_tranches):
            tranche = principal_tranches[trigger_index]
            trigger_name = None
            if -drawdown >= tranche["drawdown"]:
                trigger_name = tranche["drawdown_trigger"]
            elif i >= tranche["fallback_day"]:
                trigger_name = tranche["time_trigger"]

            if trigger_name and portfolio.invested < principal_cap - 1:
                buy_amount = min(principal_cap * tranche["pct"], principal_cap - portfolio.invested)
                buy_target_notional(portfolio, prices, buy_amount, trigger_name, day, logs, principal_cap, name)
                trigger_index += 1

        if name == "monthly_dca" and day in first_by_month[1:] and portfolio.invested < principal_cap - 1:
            buy_amount = min(principal_cap * 0.20, principal_cap - portfolio.invested)
            buy_target_notional(portfolio, prices, buy_amount, "monthly_first_trading_day_dca", day, logs, principal_cap, name)

        if name == "one_shot_full" and i == 0 and portfolio.invested < principal_cap - 1:
            buy_amount = principal_cap - portfolio.invested
            buy_target_notional(portfolio, prices, buy_amount, "one_shot_remaining_60pct_benchmark", day, logs, principal_cap, name)

        if day in month_ends and name != "one_shot_full" and portfolio.invested >= principal_cap - 1:
            rebalance_month_end(portfolio, prices, day, logs, principal_cap, name)

        tv = total_value(portfolio, prices)
        mv = market_value(portfolio, prices)
        portfolio.high_watermark = max(portfolio.high_watermark, tv)
        drawdown = 0.0 if portfolio.high_watermark <= 0 else tv / portfolio.high_watermark - 1
        row = {
            "strategy": name,
            "date": day,
            "total_value": round(tv, 2),
            "cash": round(portfolio.cash, 2),
            "market_value": round(mv, 2),
            "principal_invested": round(portfolio.invested, 2),
            "return_on_principal_cap": round(tv / principal_cap - 1, 6),
            "drawdown_from_strategy_high": round(drawdown, 6),
        }
        current_weights = weights(portfolio, prices)
        for etf in ETFS:
            row[f"weight_{etf['code']}"] = round(current_weights[etf["code"]], 6)
        nav_rows.append(row)

    end_value = nav_rows[-1]["total_value"]
    invested = nav_rows[-1]["principal_invested"]
    summary = {
        "strategy": name,
        "start_date": dates[0],
        "end_date": dates[-1],
        "principal_cap": round(principal_cap, 2),
        "ending_total_value": round(end_value, 2),
        "ending_market_value": round(nav_rows[-1]["market_value"], 2),
        "ending_cash": round(nav_rows[-1]["cash"], 2),
        "ending_principal_invested": round(invested, 2),
        "return_on_principal_cap": round(end_value / principal_cap - 1, 6),
        "return_on_invested_principal": round((end_value - (principal_cap - invested)) / invested - 1, 6) if invested else 0,
        "max_drawdown": round(min(row["drawdown_from_strategy_high"] for row in nav_rows), 6),
        "trade_count": len(logs),
    }
    return nav_rows, logs, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--begin", default="20260101")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--principal", type=float, default=400000)
    parser.add_argument("--out-dir", default="A-share/yifangda-core-balanced-etf-plan/backtests/h1-2026")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    all_prices: dict[str, dict[str, dict]] = {}
    price_rows: list[dict] = []

    for etf in ETFS:
        rows = fetch_yahoo_chart(etf["yahoo"], args.begin, args.end)
        if not rows:
            raise RuntimeError(f"No data returned for {etf['code']}")
        all_prices[etf["code"]] = {str(row["date"]): row for row in rows}
        for row in rows:
            price_rows.append({"code": etf["code"], "name": etf["name"], **row})

    common_dates = sorted(set.intersection(*(set(rows.keys()) for rows in all_prices.values())))
    if not common_dates:
        raise RuntimeError("No common trading dates across ETFs")

    strategies = ["triggered_plan", "monthly_dca", "one_shot_full"]
    all_nav: list[dict] = []
    all_logs: list[dict] = []
    summaries: list[dict] = []
    for strategy in strategies:
        nav, logs, summary = run_strategy(strategy, common_dates, all_prices, args.principal)
        all_nav.extend(nav)
        all_logs.extend(logs)
        summaries.append(summary)

    write_csv(
        out_dir / "prices_h1_2026.csv",
        price_rows,
        ["code", "name", "date", "open", "close", "high", "low", "volume", "adj_close", "raw_open", "raw_close", "raw_high", "raw_low", "raw_adj_close"],
    )
    write_csv(out_dir / "nav_h1_2026.csv", all_nav, list(all_nav[0].keys()))
    write_csv(out_dir / "operation_log_backtest_h1_2026.csv", all_logs, list(all_logs[0].keys()))
    write_csv(out_dir / "summary_h1_2026.csv", summaries, list(summaries[0].keys()))

    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
