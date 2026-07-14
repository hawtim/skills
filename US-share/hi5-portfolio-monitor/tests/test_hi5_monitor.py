import importlib.util
import sys
import unittest
from datetime import date, datetime
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_report.py"
SPEC = importlib.util.spec_from_file_location("hi5_monitor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

ALERT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_entry_alerts.py"
ALERT_SPEC = importlib.util.spec_from_file_location("hi5_alerts", ALERT_PATH)
ALERT_MODULE = importlib.util.module_from_spec(ALERT_SPEC)
assert ALERT_SPEC and ALERT_SPEC.loader
sys.modules[ALERT_SPEC.name] = ALERT_MODULE
ALERT_SPEC.loader.exec_module(ALERT_MODULE)


class Hi5Tests(unittest.TestCase):
    def test_parse_sheet_with_preamble(self):
        text = ("mobile note\nTransaction Date,Settlement Date,Activity Description,Description,Symbol,Quantity,Price,Price Currency,Total Amount,Total Currency\n"
                "2026-01-02,2026-01-05,Buy,x,RSP,10,100,USD,-1005,USD\n")
        rows = MODULE.parse_trades(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].symbol, "RSP")
        self.assertEqual(rows[0].source_row, 3)

    def test_campaign_labels(self):
        self.assertEqual(MODULE.campaign_type("2023-08-03"), "initial")
        self.assertEqual(MODULE.campaign_type("2025-08-01"), "rebalance")
        self.assertEqual(MODULE.campaign_type("2026-07-08"), "recurring")

    def test_third_friday(self):
        self.assertEqual(MODULE.third_friday(2026, 7), date(2026, 7, 17))

    def test_event_window_uses_future_three_sessions(self):
        bars = [MODULE.Bar(f"2026-01-0{i}", 100, 101, low, 100, 100) for i, low in enumerate([99, 98, 97, 96, 95], 1)]
        trade = MODULE.Trade("2026-01-01", "2026-01-02", "Buy", "RSP", 1, 100, -100, 3)
        event = MODULE.event_study([trade], {"RSP": bars})[0]
        self.assertEqual(event["future_3d_low"], 96)
        self.assertAlmostEqual(event["gap_to_future_low_pct"], 4.1667, places=4)

    def test_xirr(self):
        value = MODULE.xirr([(date(2024, 1, 1), -100), (date(2025, 1, 1), 110)])
        self.assertAlmostEqual(value, 0.1, places=3)

    def test_entry_alert_bands(self):
        self.assertEqual(ALERT_MODULE.target_fraction(0.49), 0)
        self.assertEqual(ALERT_MODULE.target_fraction(0.5), 25)
        self.assertEqual(ALERT_MODULE.target_fraction(1.2), 50)
        self.assertEqual(ALERT_MODULE.target_fraction(2.0), 100)

    def test_parse_futu_snapshot_amid_logs(self):
        output = 'log line\n{"data":[{"code":"US.VNQ","last_price":96.9}]}\nmore log'
        self.assertEqual(ALERT_MODULE.parse_futu_json(output)["VNQ"]["last_price"], 96.9)

    def test_market_hours_gate(self):
        self.assertTrue(ALERT_MODULE.market_open_now(datetime(2026, 7, 13, 10, 0, tzinfo=ALERT_MODULE.NEW_YORK)))
        self.assertFalse(ALERT_MODULE.market_open_now(datetime(2026, 7, 13, 8, 0, tzinfo=ALERT_MODULE.NEW_YORK)))
        self.assertFalse(ALERT_MODULE.market_open_now(datetime(2026, 7, 12, 10, 0, tzinfo=ALERT_MODULE.NEW_YORK)))


if __name__ == "__main__":
    unittest.main()
