#!/usr/bin/env python3
"""Rebuild the Jiashi dual-fund portfolio and evaluate deterministic rules."""

import argparse
import csv
import json
from pathlib import Path


TARGETS = {
    "000043": {
        "name": "嘉实美国成长股票（QDII）",
        "share_class": "A",
        "initial": 150000.0,
        "cap": 200000.0,
    },
    "017730": {
        "name": "嘉实全球产业升级股票发起式（QDII）A",
        "share_class": "A",
        "initial": 50000.0,
        "cap": 100000.0,
    },
}

REQUIRED_COLUMNS = (
    "record_id",
    "reported_at",
    "trade_date",
    "confirmation_date",
    "account_label",
    "action_type",
    "trigger_type",
    "fund_code",
    "fund_name",
    "share_class",
    "side",
    "confirmed_amount",
    "confirmed_shares",
    "confirmed_nav",
    "fee",
    "currency",
    "total_invested_after_trade",
    "position_cost_after_trade",
    "position_shares_after_trade",
    "notes",
    "source",
)


def _number(value, field, allow_zero=False):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("invalid {}: {}".format(field, value))
    if number < 0 or (number == 0 and not allow_zero):
        raise ValueError("{} must be {}".format(field, "non-negative" if allow_zero else "positive"))
    return number


def load_operations(path):
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("missing columns: {}".format(", ".join(missing)))
        rows = list(reader)
    validate_operations(rows)
    return rows


def validate_operations(rows):
    seen = set()
    for row in rows:
        record_id = str(row.get("record_id", "")).strip()
        if not record_id:
            raise ValueError("record_id is required")
        if record_id in seen:
            raise ValueError("duplicate record_id: {}".format(record_id))
        seen.add(record_id)

        code = str(row.get("fund_code", "")).strip()
        if code not in TARGETS:
            raise ValueError("unsupported fund_code: {}".format(code))
        if str(row.get("share_class", "")).strip().upper() != TARGETS[code]["share_class"]:
            raise ValueError("unsupported share_class for {}".format(code))
        if str(row.get("side", "")).strip().lower() not in {"buy", "sell", "cash_dividend", "reinvest"}:
            raise ValueError("unsupported side: {}".format(row.get("side")))
        _number(row.get("confirmed_amount", 0), "confirmed_amount", allow_zero=True)
        _number(row.get("confirmed_shares", 0), "confirmed_shares", allow_zero=True)
        _number(row.get("confirmed_nav", 0), "confirmed_nav", allow_zero=True)
        _number(row.get("fee", 0), "fee", allow_zero=True)


def _empty_fund(code):
    target = TARGETS[code]
    return {
        "code": code,
        "name": target["name"],
        "shares": 0.0,
        "net_invested": 0.0,
        "average_cost": 0.0,
        "market_value": 0.0,
        "unrealized_pnl": 0.0,
        "realized_proceeds": 0.0,
        "realized_pnl": 0.0,
        "current_weight": 0.0,
        "remaining_cap": target["cap"],
        "cost_drawdown": None,
        "nav": None,
        "nav_date": None,
        "nav_stale": None,
    }


def build_portfolio(operations, navs):
    validate_operations(operations)
    funds = {code: _empty_fund(code) for code in TARGETS}

    for row in operations:
        code = str(row["fund_code"]).strip()
        fund = funds[code]
        side = str(row["side"]).strip().lower()
        amount = _number(row.get("confirmed_amount", 0), "confirmed_amount", allow_zero=True)
        shares = _number(row.get("confirmed_shares", 0), "confirmed_shares", allow_zero=True)
        fee = _number(row.get("fee", 0), "fee", allow_zero=True)

        if side in {"buy", "reinvest"}:
            if shares <= 0:
                raise ValueError("buy/reinvest confirmed_shares must be positive")
            fund["shares"] += shares
            fund["net_invested"] += amount + fee
        elif side == "sell":
            if shares <= 0 or shares > fund["shares"]:
                raise ValueError("sell shares exceed position for {}".format(code))
            average_cost = fund["net_invested"] / fund["shares"] if fund["shares"] else 0.0
            cost_released = average_cost * shares
            proceeds = amount - fee
            fund["shares"] -= shares
            fund["net_invested"] -= cost_released
            fund["realized_proceeds"] += proceeds
            fund["realized_pnl"] += proceeds - cost_released
        elif side == "cash_dividend":
            fund["realized_proceeds"] += amount
            fund["realized_pnl"] += amount

    missing_inputs = []
    for code, fund in funds.items():
        nav_record = navs.get(code)
        if nav_record is None:
            missing_inputs.append("{}_nav".format(code))
        else:
            fund["nav"] = _number(nav_record.get("nav"), "{}_nav".format(code))
            fund["nav_date"] = nav_record.get("date")
            fund["nav_stale"] = bool(nav_record.get("stale", False))
            if fund["nav_stale"]:
                missing_inputs.append("{}_nav_stale".format(code))
        fund["average_cost"] = fund["net_invested"] / fund["shares"] if fund["shares"] else 0.0
        fund["market_value"] = fund["shares"] * fund["nav"] if fund["nav"] is not None else 0.0
        fund["unrealized_pnl"] = fund["market_value"] - fund["net_invested"]
        fund["remaining_cap"] = max(0.0, TARGETS[code]["cap"] - fund["net_invested"])
        if fund["average_cost"] and fund["nav"] is not None:
            fund["cost_drawdown"] = fund["nav"] / fund["average_cost"] - 1.0

    total_value = sum(fund["market_value"] for fund in funds.values())
    for fund in funds.values():
        fund["current_weight"] = fund["market_value"] / total_value if total_value else 0.0

    totals = {
        "shares": sum(fund["shares"] for fund in funds.values()),
        "net_invested": sum(fund["net_invested"] for fund in funds.values()),
        "market_value": total_value,
        "unrealized_pnl": sum(fund["unrealized_pnl"] for fund in funds.values()),
        "realized_proceeds": sum(fund["realized_proceeds"] for fund in funds.values()),
        "realized_pnl": sum(fund["realized_pnl"] for fund in funds.values()),
        "remaining_cap": sum(fund["remaining_cap"] for fund in funds.values()),
    }
    return {"funds": funds, "totals": totals, "missing_inputs": missing_inputs}


def healthy_checks():
    return {
        "strategy_ok": True,
        "fundamentals_ok": True,
        "overlap_ok": True,
        "manager_ok": True,
        "market_ok": True,
        "score_ok": True,
        "rebalance_review": False,
        "replacement_review": False,
    }


def evaluate_action(portfolio, checks):
    missing_inputs = list(portfolio.get("missing_inputs", []))
    amounts = {code: 0.0 for code in TARGETS}
    result = {
        "action": "无动作",
        "amounts": amounts,
        "rule_ids": [],
        "missing_inputs": missing_inputs,
        "requires_human_confirmation": True,
    }

    if missing_inputs:
        result.update(action="观察", rule_ids=["DATA-INCOMPLETE"])
        return result
    if checks.get("replacement_review"):
        result.update(action="减仓/替换复核", rule_ids=["REVIEW-REPLACEMENT"])
        return result
    if checks.get("rebalance_review"):
        result.update(action="再平衡复核", rule_ids=["REVIEW-REBALANCE"])
        return result

    gates = ("strategy_ok", "fundamentals_ok", "overlap_ok", "manager_ok", "market_ok", "score_ok")
    gates_ok = all(bool(checks.get(key, False)) for key in gates)
    if portfolio["totals"]["net_invested"] == 0:
        if not gates_ok:
            result.update(action="暂停加仓", rule_ids=["BUILD-GATE-FAILED"])
            return result
        for code, target in TARGETS.items():
            amounts[code] = min(target["initial"], portfolio["funds"][code]["remaining_cap"])
        result.update(action="加仓候选", rule_ids=["BUILD-INITIAL"])
        return result

    triggered = []
    observe = False
    for code, fund in portfolio["funds"].items():
        drawdown = fund.get("cost_drawdown")
        if drawdown is None:
            continue
        if drawdown <= -0.145:
            triggered.append((code, "ADD-SECOND", 25000.0))
        elif drawdown <= -0.08:
            triggered.append((code, "ADD-FIRST", 25000.0))
        elif drawdown <= -0.05:
            observe = True

    if triggered and not gates_ok:
        result.update(action="暂停加仓", rule_ids=["ADD-GATE-FAILED"])
        return result
    if triggered:
        for code, rule_id, tranche in triggered:
            amounts[code] = min(tranche, portfolio["funds"][code]["remaining_cap"])
            if amounts[code] > 0:
                result["rule_ids"].append(rule_id)
        if any(amounts.values()):
            result["action"] = "加仓候选"
        return result
    if observe:
        result.update(action="观察", rule_ids=["ADD-OBSERVE"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-log", required=True)
    parser.add_argument("--nav-json", required=True)
    parser.add_argument("--checks-json")
    args = parser.parse_args()

    operations = load_operations(args.operation_log)
    with Path(args.nav_json).open("r", encoding="utf-8") as handle:
        navs = json.load(handle)
    checks = healthy_checks()
    if args.checks_json:
        with Path(args.checks_json).open("r", encoding="utf-8") as handle:
            checks.update(json.load(handle))
    portfolio = build_portfolio(operations, navs)
    print(json.dumps({"portfolio": portfolio, "evaluation": evaluate_action(portfolio, checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
