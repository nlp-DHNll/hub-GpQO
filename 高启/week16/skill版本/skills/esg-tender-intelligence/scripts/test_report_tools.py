"""投标情报工具行为测试。"""

import unittest

from report_tools import get_review_window, validate_reference_map


class TenderReportToolsTests(unittest.TestCase):
    def test_two_year_window_and_leap_day(self):
        self.assertEqual(get_review_window("2026-11-24"), ("2024-11-24", "2026-11-24"))
        self.assertEqual(get_review_window("2024-02-29"), ("2022-02-28", "2024-02-29"))

    def test_invalid_date_is_rejected(self):
        with self.assertRaises(ValueError):
            get_review_window("2026-02-30")

    def test_checker_accepts_both_source_id_styles(self):
        report = "案例 [S01]，线索 [S02]。\n## 来源清单\n- **S01** 原文\n- **[S02]** 线索"
        self.assertEqual(validate_reference_map(report), [])

    def test_checker_finds_unmatched_ids(self):
        report = "案例 [S01]。\n## 来源清单\n- **S02** 来源"
        errors = validate_reference_map(report)
        self.assertTrue(any("S01" in error for error in errors))
        self.assertTrue(any("S02" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
