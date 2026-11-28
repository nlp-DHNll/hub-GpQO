"""月报工具的行为测试。"""

import unittest

from report_tools import get_month_range, validate_reference_map


class ReportToolsTests(unittest.TestCase):
    def test_month_range_handles_february_and_leap_year(self):
        self.assertEqual(
            get_month_range("2026-02"),
            ("2026-02-01", "2026-02-28"),
        )
        self.assertEqual(
            get_month_range("2024-02"),
            ("2024-02-01", "2024-02-29"),
        )

    def test_month_range_rejects_invalid_month(self):
        with self.assertRaises(ValueError):
            get_month_range("2026-13")

    def test_reference_map_accepts_used_source_ids(self):
        report = "结论引用 [S01]。\n\n## 六、来源清单\n- **[S01]** 来源标题"
        self.assertEqual(validate_reference_map(report), [])

    def test_reference_map_reports_missing_and_unused_source_ids(self):
        report = "结论引用 [S01]。\n\n## 来源清单\n- **[S02]** 来源标题"
        errors = validate_reference_map(report)
        self.assertTrue(any("S01" in error and "来源清单" in error for error in errors))
        self.assertTrue(any("S02" in error and "未被引用" in error for error in errors))

    def test_reference_map_reports_duplicate_source_ids(self):
        report = "结论引用 [S01]。\n\n## 来源清单\n- **[S01]** 甲\n- **[S01]** 乙"
        self.assertTrue(any("S01" in error and "重复" in error for error in validate_reference_map(report)))


if __name__ == "__main__":
    unittest.main()
