import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


review = load_module("review_module", "tools/review.py")


class ReviewTests(unittest.TestCase):
    def test_parse_date_marker_supports_expected_formats(self):
        cases = [
            ("2026年9月15日18:02:27", "2026-09-15 18:02:27"),
            ("2026年9月15日", "2026-09-15"),
            ("## 2026-09-15", "2026-09-15"),
        ]

        for text, stamp in cases:
            with self.subTest(text=text):
                parsed = review.parse_date_marker(text)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed[1], stamp)

    def test_parse_date_marker_rejects_normal_content(self):
        self.assertIsNone(review.parse_date_marker("例如：at 8:00 , at noon"))
        self.assertIsNone(review.parse_date_marker("2026年我会坚持学习"))

    def test_resolve_schedules_uses_relative_spacing_after_late_review(self):
        anchor = review.Anchor(
            path="Sentence/example.md",
            learned=date(2026, 9, 15),
            anchor="block:2026-09-15 18:00:00",
            kind="block",
            content=["line 1"],
        )

        schedules = review.resolve_schedules([anchor], {}, date(2026, 9, 16), with_content=True)
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0].round_no, 1)
        self.assertEqual(schedules[0].due, date(2026, 9, 16))
        self.assertTrue(schedules[0].is_today)

        reviewed = {anchor.key(1): "2026-09-17"}
        schedules = review.resolve_schedules([anchor], reviewed, date(2026, 9, 18), with_content=True)
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0].round_no, 2)
        self.assertEqual(schedules[0].gap, 1)
        self.assertEqual(schedules[0].due, date(2026, 9, 18))
        self.assertTrue(schedules[0].is_today)

    def test_upcoming_map_lists_next_due_and_following_due(self):
        anchor = review.Anchor(
            path="Word/example.md",
            learned=date(2026, 9, 15),
            anchor="2026-09-15",
            kind="file",
            content=["example"],
        )
        schedules = review.resolve_schedules(
            [anchor],
            {anchor.key(1): "2026-09-16", anchor.key(2): "2026-09-17"},
            date(2026, 9, 18),
            with_content=True,
        )
        upcoming = review.upcoming_map(schedules, date(2026, 9, 18), 10)
        self.assertEqual(
            upcoming,
            [
                (date(2026, 9, 19), ["Word/example.md"]),
                (date(2026, 9, 22), ["Word/example.md"]),
            ],
        )

    def test_load_manual_reviews_reads_truthy_status_from_day_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_repo = review.REPO
            try:
                review.REPO = Path(tmp)
                review.review_table_path().write_text(
                    "# 复习任务表\n\n"
                    "## 2026-09-21\n\n"
                    "当天是否已复习：是\n\n"
                    "| 文件 | 内容日期 | 位置 | 轮次 | 原计划复习日 |\n"
                    "| --- | --- | --- | --- | --- |\n"
                    "| Word/x.md | 2026-09-15 | 整篇 | 第 2 轮 | 2026-09-21 |\n",
                    encoding="utf-8",
                )
                reviewed, sections, order = review.load_manual_reviews()
                self.assertEqual(reviewed, {"2026-09-21": "2026-09-21"})
                self.assertEqual(order, ["2026-09-21"])
                self.assertEqual(sections["2026-09-21"]["done"], "是")
                self.assertEqual(len(sections["2026-09-21"]["rows"]), 1)
            finally:
                review.REPO = old_repo

    def test_build_reviewed_map_uses_checked_section_rows(self):
        anchor = review.Anchor(
            path="Word/example.md",
            learned=date(2026, 9, 15),
            anchor="2026-09-15",
            kind="file",
            content=["example"],
        )
        sections = {
            "2026-09-16": {
                "done": "是",
                "rows": [
                    {
                        "文件": "Word/example.md",
                        "内容日期": "2026-09-15",
                        "位置": "整篇",
                        "轮次": "第 1 轮",
                        "原计划复习日": "2026-09-16",
                    }
                ],
            }
        }
        reviewed = review.build_reviewed_map([anchor], sections, {"2026-09-16": "2026-09-16"})
        self.assertEqual(reviewed, {anchor.key(1): "2026-09-16"})

    def test_update_today_section_drops_stale_rows_for_unchecked_day(self):
        anchor = review.Anchor(
            path="Word/example.md",
            learned=date(2026, 9, 15),
            anchor="2026-09-15",
            kind="file",
            content=["example"],
        )
        schedule = review.resolve_schedules([anchor], {}, date(2026, 9, 16), with_content=True)[0]
        sections = {
            "2026-09-16": {
                "done": "",
                "rows": [
                    {
                        "文件": "旧任务.md",
                        "内容日期": "2026-09-10",
                        "位置": "整篇",
                        "轮次": "第 1 轮",
                        "原计划复习日": "2026-09-11",
                    }
                ],
            }
        }
        rows = review.update_today_section(date(2026, 9, 16), [schedule], sections, ["2026-09-16"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["文件"], "Word/example.md")
        self.assertEqual(rows[0]["内容日期"], "2026-09-15")

    def test_load_reviewed_from_daily_docs_uses_history_before_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_repo = review.REPO
            try:
                review.REPO = Path(tmp)
                daily_dir = review.REPO / review.DAILY_REVIEW_DIR
                daily_dir.mkdir(parents=True, exist_ok=True)
                (daily_dir / "2026-09-22.md").write_text(
                    "# 今日复习 2026-09-22 星期二\n\n"
                    "## 1. Grammar/example.md\n\n"
                    "- 位置：第 1 行\n"
                    "- 内容标识：2026-09-15 18:02:27\n"
                    "- 学习日期：2026-09-15\n"
                    "- 轮次：第 1 轮\n"
                    "- 计划复习日：2026-09-16\n"
                    "- [x] 当天是否已复习\n\n"
                    "```text\n第一段内容\n```\n",
                    encoding="utf-8",
                )
                anchor = review.Anchor(
                    path="Grammar/example.md",
                    learned=date(2026, 9, 15),
                    anchor="2026-09-15 18:02:27",
                    kind="block",
                    content=["第一段内容"],
                )
                reviewed = review.load_reviewed_from_daily_docs(date(2026, 9, 23))
                self.assertEqual(reviewed, {anchor.key(1): "2026-09-22"})
            finally:
                review.REPO = old_repo

    def test_build_daily_review_doc_copies_full_content(self):
        anchor = review.Anchor(
            path="Sentence/example.md",
            learned=date(2026, 9, 15),
            anchor="2026-09-15 18:02:27",
            kind="block",
            content=["第一行", "第二行"],
        )
        schedule = review.resolve_schedules([anchor], {}, date(2026, 9, 16), with_content=True)[0]
        doc = review.build_daily_review_doc([schedule], date(2026, 9, 16))
        self.assertIn("# 今日复习 2026-09-16", doc)
        self.assertIn("- [ ] 当天是否已复习", doc)
        self.assertIn("第一行", doc)
        self.assertIn("第二行", doc)

    def test_parse_daily_review_doc_returns_only_checked_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2026-09-16.md"
            path.write_text(
                "# 今日复习 2026-09-16 星期三\n\n"
                "## 1. Word/example.md\n\n"
                "- 位置：整篇（按 git 提交时间）\n"
                "- 内容标识：2026-09-15\n"
                "- 学习日期：2026-09-15\n"
                "- 轮次：第 1 轮\n"
                "- 计划复习日：2026-09-16\n"
                "- [x] 当天是否已复习\n\n"
                "```text\nexample\n```\n\n"
                "## 2. Word/other.md\n\n"
                "- 位置：整篇（按 git 提交时间）\n"
                "- 内容标识：2026-09-14\n"
                "- 学习日期：2026-09-14\n"
                "- 轮次：第 1 轮\n"
                "- 计划复习日：2026-09-16\n"
                "- [ ] 当天是否已复习\n\n"
                "```text\nother\n```\n",
                encoding="utf-8",
            )
            self.assertEqual(
                review.parse_daily_review_doc(path),
                [("Word/example.md", "2026-09-15", 1)],
            )


if __name__ == "__main__":
    unittest.main()
