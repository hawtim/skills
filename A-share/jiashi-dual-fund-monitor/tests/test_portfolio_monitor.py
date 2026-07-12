import importlib.util
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_DIR / "scripts" / "portfolio_monitor.py"
SPEC = importlib.util.spec_from_file_location("portfolio_monitor", MODULE_PATH)
portfolio_monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(portfolio_monitor)


def purchase(record_id, code, amount, shares, nav, fee=0, share_class="A"):
    return {
        "record_id": record_id,
        "reported_at": "2026-07-12",
        "trade_date": "2026-07-12",
        "confirmation_date": "2026-07-14",
        "account_label": "嘉实双基金组合",
        "action_type": "initial_build",
        "trigger_type": "user_reported_trade",
        "fund_code": code,
        "fund_name": portfolio_monitor.TARGETS.get(code, {}).get("name", "unknown"),
        "share_class": share_class,
        "side": "buy",
        "confirmed_amount": amount,
        "confirmed_shares": shares,
        "confirmed_nav": nav,
        "fee": fee,
        "currency": "CNY",
        "total_invested_after_trade": "",
        "position_cost_after_trade": "",
        "position_shares_after_trade": "",
        "notes": "",
        "source": "user_reported",
    }


def current_navs():
    return {
        "000043": {"nav": 5.5, "date": "2026-07-11", "stale": False},
        "017730": {"nav": 2.2, "date": "2026-07-11", "stale": False},
    }


class PortfolioMonitorTests(unittest.TestCase):
    def test_empty_log_builds_empty_portfolio(self):
        state = portfolio_monitor.build_portfolio([], current_navs())
        self.assertEqual(state["totals"]["shares"], 0)
        self.assertEqual(state["totals"]["market_value"], 0)
        self.assertEqual(state["totals"]["net_invested"], 0)
        self.assertEqual(state["totals"]["remaining_cap"], 300000)

    def test_single_purchase_reconstructs_cost_and_remaining_cap(self):
        rows = [purchase("trade-1", "000043", 50000, 10000, 5.0)]
        state = portfolio_monitor.build_portfolio(rows, current_navs())
        fund = state["funds"]["000043"]
        self.assertEqual(fund["shares"], 10000)
        self.assertEqual(fund["average_cost"], 5.0)
        self.assertEqual(fund["remaining_cap"], 150000)
        self.assertEqual(state["totals"]["remaining_cap"], 250000)

    def test_multiple_purchases_use_confirmed_shares_and_fees(self):
        rows = [
            purchase("trade-1", "017730", 20000, 10000, 2.0, fee=10),
            purchase("trade-2", "017730", 30000, 12000, 2.5, fee=15),
        ]
        state = portfolio_monitor.build_portfolio(rows, current_navs())
        fund = state["funds"]["017730"]
        self.assertEqual(fund["shares"], 22000)
        self.assertEqual(fund["net_invested"], 50025)
        self.assertAlmostEqual(fund["average_cost"], 50025 / 22000)

    def test_redemption_tracks_realized_value_and_remaining_shares(self):
        rows = [
            purchase("trade-1", "000043", 50000, 10000, 5.0),
            {**purchase("trade-2", "000043", 33000, 6000, 5.5, fee=20), "side": "sell"},
        ]
        state = portfolio_monitor.build_portfolio(rows, current_navs())
        fund = state["funds"]["000043"]
        self.assertEqual(fund["shares"], 4000)
        self.assertEqual(fund["realized_proceeds"], 32980)
        self.assertEqual(fund["average_cost"], 5.0)

    def test_duplicate_record_id_is_rejected(self):
        rows = [purchase("trade-1", "000043", 1000, 200, 5.0)] * 2
        with self.assertRaisesRegex(ValueError, "duplicate record_id: trade-1"):
            portfolio_monitor.validate_operations(rows)

    def test_non_target_share_class_is_rejected(self):
        with self.assertRaises(ValueError):
            portfolio_monitor.validate_operations([purchase("trade-1", "017731", 1000, 400, 2.5)])
        with self.assertRaises(ValueError):
            portfolio_monitor.validate_operations([purchase("trade-2", "017730", 1000, 400, 2.5, share_class="C")])

    def test_observe_band_does_not_trigger_add(self):
        state = portfolio_monitor.build_portfolio(
            [purchase("trade-1", "000043", 100000, 20000, 5.0)], current_navs()
        )
        state["funds"]["000043"]["cost_drawdown"] = -0.06
        result = portfolio_monitor.evaluate_action(state, portfolio_monitor.healthy_checks())
        self.assertEqual(result["action"], "观察")
        self.assertEqual(result["amounts"]["000043"], 0)

    def test_first_add_band_requires_all_non_price_checks(self):
        state = portfolio_monitor.build_portfolio(
            [purchase("trade-1", "000043", 150000, 30000, 5.0)], current_navs()
        )
        state["funds"]["000043"]["cost_drawdown"] = -0.09
        result = portfolio_monitor.evaluate_action(state, portfolio_monitor.healthy_checks())
        self.assertEqual(result["action"], "加仓候选")
        self.assertEqual(result["amounts"]["000043"], 25000)
        for key in ("strategy_ok", "fundamentals_ok", "overlap_ok", "manager_ok"):
            checks = portfolio_monitor.healthy_checks()
            checks[key] = False
            result = portfolio_monitor.evaluate_action(state, checks)
            self.assertEqual(result["action"], "暂停加仓")

    def test_second_add_band_is_capped_by_remaining_capacity(self):
        state = portfolio_monitor.build_portfolio(
            [purchase("trade-1", "017730", 90000, 45000, 2.0)], current_navs()
        )
        state["funds"]["017730"]["cost_drawdown"] = -0.15
        result = portfolio_monitor.evaluate_action(state, portfolio_monitor.healthy_checks())
        self.assertEqual(result["action"], "加仓候选")
        self.assertEqual(result["amounts"]["017730"], 10000)

    def test_missing_or_stale_nav_degrades_to_watch(self):
        state = portfolio_monitor.build_portfolio([], {"000043": current_navs()["000043"]})
        result = portfolio_monitor.evaluate_action(state, portfolio_monitor.healthy_checks())
        self.assertEqual(result["action"], "观察")
        self.assertIn("017730_nav", result["missing_inputs"])
        stale = current_navs()
        stale["017730"]["stale"] = True
        state = portfolio_monitor.build_portfolio([], stale)
        result = portfolio_monitor.evaluate_action(state, portfolio_monitor.healthy_checks())
        self.assertEqual(result["action"], "观察")
        self.assertIn("017730_nav_stale", result["missing_inputs"])


if __name__ == "__main__":
    unittest.main()
