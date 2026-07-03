#!/usr/bin/env python3
"""Fetch ETF daily data from Eastmoney and backtest the ETF theme plan.

Assumptions:
- Daily close execution.
- Fractional shares are allowed for clean allocation math.
- Fees, slippage, interest, and taxes are ignored.
- Subjective plan language is converted into deterministic drawdown triggers.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep


ETFS = [
    {"code": "159530", "name": "机器人ETF易方达", "secid": "0.159530", "yahoo": "159530.SZ", "weight": 0.30, "lower": 0.25, "upper": 0.35},
    {"code": "159994", "name": "通信ETF银华", "secid": "0.159994", "yahoo": "159994.SZ", "weight": 0.25, "lower": 0.20, "upper": 0.30},
    {"code": "515260", "name": "电子ETF华宝", "secid": "1.515260", "yahoo": "515260.SS", "weight": 0.20, "lower": 0.16, "upper": 0.25},
    {"code": "561980", "name": "半导体设备ETF招商", "secid": "1.561980", "yahoo": "561980.SS", "weight": 0.15, "lower": 0.10, "upper": 0.20},
    {"code": "159538", "name": "信创ETF富国", "secid": "0.159538", "yahoo": "159538.SZ", "weight": 0.10, "lower": 0.07, "upper": 0.13},
]


@dataclass
class Portfolio:
    cash: float
    shares: dict[str, float]
    invested: float = 0.0
    high_watermark: float = 0.0
    margin_used: float = 0.0
    margin_lots: list[dict] | None = None


def fetch_eastmoney_kline(secid: str, begin: str, end: str) -> list[dict[str, str | float]]:
    fields1 = "f1,f2,f3,f4,f5,f6"
    fields2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&fields1={fields1}&fields2={fields2}&klt=101&fqt=1&beg={begin}&end={end}"
    )
    payload = None
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.load(response)
            break
        except Exception as exc:  # noqa: BLE001 - retry network edge cases from public endpoint.
            last_error = exc
            sleep(0.8 * (attempt + 1))
    if payload is None:
        raise RuntimeError(f"Failed to fetch {secid}: {last_error}")
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "amplitude_pct": float(parts[7]),
                "pct_change": float(parts[8]),
                "change": float(parts[9]),
                "turnover_pct": float(parts[10]),
            }
        )
    return rows


def fetch_yahoo_chart(symbol: str, begin: str, end: str) -> list[dict[str, str | float]]:
    start = datetime.strptime(begin, "%Y%m%d").replace(tzinfo=timezone.utc)
    # Yahoo's period2 is exclusive-ish; use the next UTC day to include end date.
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
                "amount": "",
                "adj_close": float(adj[i]) if i < len(adj) and adj[i] is not None else "",
                "amplitude_pct": "",
                "pct_change": "",
                "change": "",
                "turnover_pct": "",
            }
        )
    return rows


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


def value_portfolio(portfolio: Portfolio, prices: dict[str, float]) -> float:
    return portfolio.cash + sum(portfolio.shares.get(code, 0.0) * price for code, price in prices.items()) - portfolio.margin_used


def market_value_only(portfolio: Portfolio, prices: dict[str, float]) -> float:
    return sum(portfolio.shares.get(code, 0.0) * price for code, price in prices.items())


def weights(portfolio: Portfolio, prices: dict[str, float]) -> dict[str, float]:
    mv = market_value_only(portfolio, prices)
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


def buy_margin_notional(
    portfolio: Portfolio,
    prices: dict[str, float],
    notional: float,
    trigger: str,
    day: str,
    day_index: int,
    logs: list[dict],
    principal_cap: float,
    strategy: str,
) -> None:
    if portfolio.margin_lots is None:
        portfolio.margin_lots = []
    for etf in ETFS:
        amount = notional * etf["weight"]
        if amount <= 0:
            continue
        code = etf["code"]
        price = prices[code]
        shares = amount / price
        portfolio.shares[code] = portfolio.shares.get(code, 0.0) + shares
        portfolio.margin_used += amount
        portfolio.margin_lots.append(
            {
                "code": code,
                "name": etf["name"],
                "shares": shares,
                "borrowed": amount,
                "cost_amount": amount,
                "entry_day_index": day_index,
            }
        )
        logs.append(
            {
                "strategy": strategy,
                "trade_date": day,
                "action_type": "margin_buy",
                "trigger_type": trigger,
                "etf_code": code,
                "etf_name": etf["name"],
                "price": round(price, 4),
                "amount": round(amount, 2),
                "principal_cap": round(principal_cap, 2),
                "total_principal_invested_after_trade": round(portfolio.invested, 2),
                "notes": "融资按目标权重抄底",
            }
        )


def margin_lot_return(portfolio: Portfolio, prices: dict[str, float]) -> float:
    lots = portfolio.margin_lots or []
    cost = sum(lot["cost_amount"] for lot in lots)
    if cost <= 0:
        return 0.0
    value = sum(lot["shares"] * prices[lot["code"]] for lot in lots)
    borrowed = sum(lot["borrowed"] for lot in lots)
    return (value - borrowed) / cost


def reduce_margin(
    portfolio: Portfolio,
    prices: dict[str, float],
    fraction: float,
    trigger: str,
    day: str,
    logs: list[dict],
    principal_cap: float,
    strategy: str,
) -> None:
    lots = portfolio.margin_lots or []
    if not lots:
        return
    fraction = max(0.0, min(1.0, fraction))
    remaining_lots = []
    for lot in lots:
        sell_shares = lot["shares"] * fraction
        repay = lot["borrowed"] * fraction
        price = prices[lot["code"]]
        proceeds = sell_shares * price
        portfolio.shares[lot["code"]] -= sell_shares
        portfolio.margin_used -= repay
        portfolio.cash += proceeds - repay
        logs.append(
            {
                "strategy": strategy,
                "trade_date": day,
                "action_type": "margin_sell_repay",
                "trigger_type": trigger,
                "etf_code": lot["code"],
                "etf_name": lot["name"],
                "price": round(price, 4),
                "amount": round(proceeds, 2),
                "principal_cap": round(principal_cap, 2),
                "total_principal_invested_after_trade": round(portfolio.invested, 2),
                "notes": f"卖出融资仓并还款，比例={fraction:.2f}",
            }
        )
        lot["shares"] -= sell_shares
        lot["borrowed"] -= repay
        lot["cost_amount"] *= 1 - fraction
        if lot["shares"] > 1e-9 and lot["borrowed"] > 1e-6:
            remaining_lots.append(lot)
    portfolio.margin_lots = remaining_lots
    if abs(portfolio.margin_used) < 1e-6:
        portfolio.margin_used = 0.0


def rebalance_month_end(
    portfolio: Portfolio,
    prices: dict[str, float],
    day: str,
    logs: list[dict],
    principal_cap: float,
    strategy: str,
) -> None:
    current_weights = weights(portfolio, prices)
    mv = market_value_only(portfolio, prices)
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
    mv = market_value_only(portfolio, prices)
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
    portfolio = Portfolio(cash=principal_cap, shares={etf["code"]: 0.0 for etf in ETFS}, margin_lots=[])
    nav_rows: list[dict] = []
    logs: list[dict] = []
    month_ends = month_end_dates(dates)
    first_by_month = first_trading_dates_by_month(dates)
    trigger_tranches = [(0.03, 0.20, "drawdown_3pct_principal_add"), (0.08, 0.20, "drawdown_8pct_principal_add"), (0.12, 0.20, "drawdown_12pct_principal_add")]
    trigger_index = 0
    margin_tranches = [(0.10, 50000 / 400000, "margin_drawdown_10pct"), (0.15, 80000 / 400000, "margin_drawdown_15pct"), (0.20, 120000 / 400000, "margin_drawdown_20pct")]
    margin_index = 0
    margin_reduced_once = False
    margin_paused = False

    for i, day in enumerate(dates):
        prices = prices_on(all_prices, day)

        if i == 0:
            buy_target_notional(portfolio, prices, principal_cap * 0.40, "initial_40pct_build", day, logs, principal_cap, name)

        total_value = value_portfolio(portfolio, prices)
        portfolio.high_watermark = max(portfolio.high_watermark, total_value)
        drawdown = 0.0 if portfolio.high_watermark <= 0 else total_value / portfolio.high_watermark - 1

        if name in {"triggered_plan", "triggered_plan_with_margin"} and i > 0 and trigger_index < len(trigger_tranches):
            threshold, tranche_pct, trigger_name = trigger_tranches[trigger_index]
            if -drawdown >= threshold and portfolio.invested < principal_cap - 1:
                if threshold >= 0.12 and -drawdown > 0.15:
                    pass
                else:
                    buy_amount = min(principal_cap * tranche_pct, principal_cap - portfolio.invested)
                    buy_target_notional(portfolio, prices, buy_amount, trigger_name, day, logs, principal_cap, name)
                    trigger_index += 1

        if name == "monthly_dca" and day in first_by_month[1:] and portfolio.invested < principal_cap - 1:
            buy_amount = min(principal_cap * 0.20, principal_cap - portfolio.invested)
            buy_target_notional(portfolio, prices, buy_amount, "monthly_first_trading_day_dca", day, logs, principal_cap, name)

        if name == "one_shot_full" and i == 0 and portfolio.invested < principal_cap - 1:
            buy_amount = principal_cap - portfolio.invested
            buy_target_notional(portfolio, prices, buy_amount, "one_shot_remaining_60pct_benchmark", day, logs, principal_cap, name)

        if name == "triggered_plan_with_margin" and portfolio.invested >= principal_cap - 1:
            active_margin_return = margin_lot_return(portfolio, prices)
            if portfolio.margin_used > 0 and active_margin_return <= -0.08:
                margin_paused = True
            if portfolio.margin_used > 0 and active_margin_return >= 0.15:
                reduce_margin(portfolio, prices, 1.0, "margin_profit_15pct_clear", day, logs, principal_cap, name)
                margin_reduced_once = True
            elif portfolio.margin_used > 0 and active_margin_return >= 0.08 and not margin_reduced_once:
                reduce_margin(portfolio, prices, 0.50, "margin_profit_8pct_sell_half", day, logs, principal_cap, name)
                margin_reduced_once = True
            elif portfolio.margin_used > 0:
                oldest = min((lot["entry_day_index"] for lot in portfolio.margin_lots or []), default=i)
                if i - oldest >= 20 and active_margin_return <= 0 and not margin_reduced_once:
                    reduce_margin(portfolio, prices, 0.50, "margin_20_trading_days_no_rebound_sell_half", day, logs, principal_cap, name)
                    margin_reduced_once = True

            if not margin_paused and margin_index < len(margin_tranches):
                threshold, tranche_ratio, trigger_name = margin_tranches[margin_index]
                if -drawdown >= threshold:
                    buy_margin_notional(portfolio, prices, principal_cap * tranche_ratio, trigger_name, day, i, logs, principal_cap, name)
                    margin_index += 1

        if day in month_ends and name != "one_shot_full":
            if name == "triggered_plan_with_margin" and portfolio.margin_used > 0:
                pass
            else:
                rebalance_month_end(portfolio, prices, day, logs, principal_cap, name)

        total_value = value_portfolio(portfolio, prices)
        market_value = market_value_only(portfolio, prices)
        portfolio.high_watermark = max(portfolio.high_watermark, total_value)
        drawdown = 0.0 if portfolio.high_watermark <= 0 else total_value / portfolio.high_watermark - 1
        row = {
            "strategy": name,
            "date": day,
            "total_value": round(total_value, 2),
            "cash": round(portfolio.cash, 2),
            "market_value": round(market_value, 2),
            "principal_invested": round(portfolio.invested, 2),
            "margin_used": round(portfolio.margin_used, 2),
            "return_on_principal_cap": round(total_value / principal_cap - 1, 6),
            "drawdown_from_strategy_high": round(drawdown, 6),
        }
        current_weights = weights(portfolio, prices)
        for etf in ETFS:
            row[f"weight_{etf['code']}"] = round(current_weights[etf["code"]], 6)
        nav_rows.append(row)

    start_value = principal_cap
    end_value = nav_rows[-1]["total_value"]
    min_drawdown = min(row["drawdown_from_strategy_high"] for row in nav_rows)
    invested = nav_rows[-1]["principal_invested"]
    market_value = nav_rows[-1]["market_value"]
    summary = {
        "strategy": name,
        "start_date": dates[0],
        "end_date": dates[-1],
        "principal_cap": round(principal_cap, 2),
        "ending_total_value": round(end_value, 2),
        "ending_market_value": round(market_value, 2),
        "ending_cash": round(nav_rows[-1]["cash"], 2),
        "ending_margin_used": round(nav_rows[-1]["margin_used"], 2),
        "ending_principal_invested": round(invested, 2),
        "return_on_principal_cap": round(end_value / start_value - 1, 6),
        "return_on_invested_principal": round((end_value - (principal_cap - invested)) / invested - 1, 6) if invested else 0,
        "max_drawdown": round(min_drawdown, 6),
        "trade_count": len(logs),
    }
    return nav_rows, logs, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--begin", default="20260101")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--principal", type=float, default=400000)
    parser.add_argument("--source", choices=["yahoo", "eastmoney"], default="yahoo")
    parser.add_argument("--out-dir", default="A-share/etf-theme-execution-plan/backtests/h1-2026")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    all_prices: dict[str, dict[str, dict]] = {}
    price_rows: list[dict] = []

    for etf in ETFS:
        if args.source == "eastmoney":
            rows = fetch_eastmoney_kline(etf["secid"], args.begin, args.end)
        else:
            rows = fetch_yahoo_chart(etf["yahoo"], args.begin, args.end)
        if not rows:
            raise RuntimeError(f"No data returned for {etf['code']}")
        all_prices[etf["code"]] = {str(row["date"]): row for row in rows}
        for row in rows:
            price_rows.append({"code": etf["code"], "name": etf["name"], **row})

    common_dates = sorted(set.intersection(*(set(rows.keys()) for rows in all_prices.values())))
    if not common_dates:
        raise RuntimeError("No common trading dates across ETFs")

    strategies = ["triggered_plan", "triggered_plan_with_margin", "monthly_dca", "one_shot_full"]
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
        ["code", "name", "date", "open", "close", "high", "low", "volume", "amount", "adj_close", "amplitude_pct", "pct_change", "change", "turnover_pct"],
    )
    write_csv(out_dir / "nav_h1_2026.csv", all_nav, list(all_nav[0].keys()))
    write_csv(out_dir / "operation_log_backtest_h1_2026.csv", all_logs, list(all_logs[0].keys()))
    write_csv(out_dir / "summary_h1_2026.csv", summaries, list(summaries[0].keys()))

    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
