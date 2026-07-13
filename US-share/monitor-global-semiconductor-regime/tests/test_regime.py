import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_report.py"
SPEC = importlib.util.spec_from_file_location("semiconductor_regime", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StructureTests(unittest.TestCase):
    def test_uptrend_fixture(self):
        result = MODULE.analyze(MODULE.fixture("UP", 1))
        self.assertEqual(result.high_relation, "HH")
        self.assertEqual(result.low_relation, "HL")
        self.assertIn(result.state, {"上升趋势", "阶段底部确认"})

    def test_downtrend_fixture(self):
        result = MODULE.analyze(MODULE.fixture("DOWN", -1))
        self.assertEqual(result.high_relation, "LH")
        self.assertEqual(result.low_relation, "LL")
        self.assertIn(result.state, {"下降趋势确认", "阶段顶部确认"})

    def test_full_fixture_has_coverage(self):
        data = {
            item.symbol: MODULE.fixture(item.symbol, 1 if item.region != "宏观" else 0)
            for item in MODULE.INSTRUMENTS
            if item.symbol != "^VIX"
        }
        data["^VIX"] = MODULE.fixture("^VIX", 0)
        data["^VIX"].closes = [18.0] * 260
        result = MODULE.compute(data)
        self.assertEqual(result["coverage_pct"], 100.0)
        self.assertGreaterEqual(result["readiness"], 0)
        self.assertLessEqual(result["readiness"], 100)


if __name__ == "__main__":
    unittest.main()
