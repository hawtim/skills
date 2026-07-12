import csv
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def read(self, relative_path):
        return (SKILL_DIR / relative_path).read_text(encoding="utf-8")

    def test_skill_is_explicit_and_uses_fixed_target_codes(self):
        skill = self.read("SKILL.md")
        agent = self.read("agents/openai.yaml")
        self.assertIn('$jiashi-dual-fund-monitor', skill)
        self.assertIn("000043", skill)
        self.assertIn("017730", skill)
        self.assertIn("allow_implicit_invocation: false", agent)

    def test_operation_log_uses_public_investment_field_allowlist(self):
        allowed = {
            "record_id", "reported_at", "trade_date", "confirmation_date",
            "account_label", "action_type", "trigger_type", "fund_code",
            "fund_name", "share_class", "side", "confirmed_amount",
            "confirmed_shares", "confirmed_nav", "fee", "currency",
            "total_invested_after_trade", "position_cost_after_trade",
            "position_shares_after_trade", "notes", "source",
        }
        with (SKILL_DIR / "data/operation-log.csv").open(encoding="utf-8") as handle:
            fields = set(next(csv.reader(handle)))
        self.assertEqual(fields, allowed)

    def test_report_templates_have_required_contract(self):
        for template in ("daily-report.md", "weekly-report.md", "quarterly-report.md"):
            text = self.read("templates/{}".format(template))
            self.assertIn("需人工确认：是", text)
            self.assertIn("数据", text)
        self.assertIn("下一触发点", self.read("templates/daily-report.md"))
        self.assertIn("下周观察清单", self.read("templates/weekly-report.md"))
        self.assertIn("产品评分", self.read("templates/quarterly-report.md"))

    def test_scheduled_prompts_have_confirmed_times_and_github_contract(self):
        prompts = self.read("references/scheduled-prompts.md")
        self.assertIn("08:30 Asia/Shanghai", prompts)
        self.assertIn("每周六 10:00 Asia/Shanghai", prompts)
        self.assertIn("每周检查一次", prompts)
        self.assertEqual(prompts.count("GitHub Connect"), 4)
        self.assertIn("不运行 git push", prompts)
        self.assertIn("reports/daily", prompts)
        self.assertIn("reports/weekly", prompts)
        self.assertIn("reports/quarterly", prompts)

    def test_no_automatic_trade_action(self):
        combined = "\n".join(
            self.read(path)
            for path in (
                "SKILL.md",
                "references/monitoring-rules.md",
                "references/scheduled-prompts.md",
            )
        )
        self.assertIn("不执行交易", combined)
        self.assertNotIn("自动申购", combined)
        self.assertNotIn("自动赎回", combined)


if __name__ == "__main__":
    unittest.main()
