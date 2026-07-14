#!/usr/bin/env python3
"""Check a newly disclosed Hi5 campaign and emit only new entry alerts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_daily_report.py"
FUTU_SNAPSHOT = Path.home() / ".codex/skills/futuapi/scripts/quote/get_snapshot.py"
NEW_YORK = ZoneInfo("America/New_York")

SPEC = importlib.util.spec_from_file_location("hi5_generator", GENERATOR)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def target_fraction(discount_pct: float) -> int:
    if discount_pct >= 2.0:
        return 100
    if discount_pct >= 1.0:
        return 50
    if discount_pct >= 0.5:
        return 25
    return 0


def market_open_now(now: datetime | None = None) -> bool:
    current = (now or datetime.now(NEW_YORK)).astimezone(NEW_YORK)
    minutes = current.hour * 60 + current.minute
    return current.weekday() < 5 and 9 * 60 + 30 <= minutes < 16 * 60


def parse_futu_json(output: str) -> dict[str, dict]:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload.get("data"), list):
            return {row["code"].split(".")[-1]: row for row in payload["data"]}
    raise ValueError("Futu snapshot JSON not found")


def futu_quotes(symbols: list[str]) -> dict[str, dict]:
    if not FUTU_SNAPSHOT.exists():
        raise FileNotFoundError(FUTU_SNAPSHOT)
    command = [sys.executable, str(FUTU_SNAPSHOT), *[f"US.{symbol}" for symbol in symbols], "--json"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=25, check=True)
    return parse_futu_json(result.stdout)


def yahoo_quotes(symbols: list[str]) -> dict[str, dict]:
    quotes: dict[str, dict] = {}
    for symbol in symbols:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=5m"
        payload = json.loads(MODULE.fetch_text(url))["chart"]["result"][0]
        meta = payload.get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            closes = payload.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            price = next((value for value in reversed(closes) if value is not None), None)
        if price is None:
            raise ValueError(f"{symbol}: no live price")
        quotes[symbol] = {"last_price": float(price), "low": meta.get("regularMarketDayLow"), "source": "Yahoo"}
    return quotes


def completed_sessions(campaign_day: str) -> int:
    bars = MODULE.fetch_bars("RSP", offline=False)
    return sum(bar.day > campaign_day for bar in bars)


def render_alert(campaign_day: str, d_stage: int, alerts: list[dict], source: str) -> str:
    lines = [f"# Hi5 到价提醒｜{campaign_day} D+{d_stage}", "", "## 现在可以做什么", ""]
    for alert in alerts:
        lines.append(
            f"- **{alert['symbol']}** 当前 ${alert['price']:.2f}，比作者 ${alert['author_price']:.2f} "
            f"便宜 {alert['discount_pct']:.2f}%；按规则累计买到计划金额的 **{alert['target_fraction']}%**。"
        )
    lines += ["", "这是到价提醒，不会自动下单。同一档位只提醒一次；若继续跌到下一档，会再次通知。", "", f"行情来源：{source}。"]
    return "\n".join(lines) + "\n"


def run(allow_backfill: bool = False) -> dict:
    now = datetime.now(MODULE.TZ).isoformat(timespec="seconds")
    trades = MODULE.parse_trades(MODULE.load_source("trades"))
    campaign_day, campaign = MODULE.latest_campaign(trades)
    ledger_path = ROOT / "data" / "signal_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {"episodes": {}}
    episodes = ledger.setdefault("episodes", {})
    is_first_import = not episodes
    episode = episodes.setdefault(campaign_day, {
        "first_seen_at": now,
        "historical_backfill": is_first_import,
        "campaign_type": MODULE.campaign_type(campaign_day),
    })
    d_stage = completed_sessions(campaign_day)
    episode["state"] = "CLOSED" if d_stage > 3 else f"WATCH_D{d_stage}"
    episode["last_alert_check_at"] = now
    if (episode.get("historical_backfill") and not allow_backfill) or d_stage > 3:
        MODULE.atomic_text(ledger_path, json.dumps(ledger, ensure_ascii=False, indent=2))
        return {"status": "SKIP", "campaign_date": campaign_day, "d_stage": d_stage,
                "reason": "historical_backfill" if episode.get("historical_backfill") else "window_closed", "alerts": []}
    if not market_open_now():
        MODULE.atomic_text(ledger_path, json.dumps(ledger, ensure_ascii=False, indent=2))
        return {"status": "SKIP", "campaign_date": campaign_day, "d_stage": d_stage,
                "reason": "us_market_closed", "alerts": []}

    symbols = [trade.symbol for trade in campaign]
    try:
        quotes = futu_quotes(symbols)
        source = "Futu OpenD"
    except Exception:
        quotes = yahoo_quotes(symbols)
        source = "Yahoo fallback"

    prior_alerts = episode.setdefault("alerts", {})
    alerts: list[dict] = []
    for trade in campaign:
        quote = quotes[trade.symbol]
        price = float(quote["last_price"])
        discount = (trade.price / price - 1) * 100
        target = target_fraction(discount)
        if not target:
            continue
        reached = [level for level, fraction in ((0.5, 25), (1.0, 50), (2.0, 100)) if target >= fraction]
        new_levels = [level for level in reached if f"{trade.symbol}:{level:.1f}" not in prior_alerts]
        if not new_levels:
            continue
        for level in new_levels:
            prior_alerts[f"{trade.symbol}:{level:.1f}"] = {"triggered_at": now, "price": price, "source": source}
        alerts.append({"symbol": trade.symbol, "author_price": trade.price, "price": price,
                       "discount_pct": round(discount, 3), "target_fraction": target,
                       "new_levels": new_levels})

    MODULE.atomic_text(ledger_path, json.dumps(ledger, ensure_ascii=False, indent=2))
    if not alerts:
        return {"status": "NO_ALERT", "campaign_date": campaign_day, "d_stage": d_stage,
                "source": source, "alerts": []}
    text = render_alert(campaign_day, d_stage, alerts, source)
    report_path = ROOT / "reports" / "alerts" / f"hi5-alert-{datetime.now(MODULE.TZ).strftime('%Y-%m-%d-%H%M')}.md"
    MODULE.atomic_text(report_path, text)
    return {"status": "ALERT", "campaign_date": campaign_day, "d_stage": d_stage,
            "source": source, "alerts": alerts, "report": str(report_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-backfill", action="store_true", help="test historical episodes; never use for live notifications")
    args = parser.parse_args()
    print(json.dumps(run(args.allow_backfill), ensure_ascii=False))


if __name__ == "__main__":
    main()
