import importlib.util
import unittest
from collections import OrderedDict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


autocommit = load_module("autocommit_module", "tools/autocommit.py")


class AutocommitTests(unittest.TestCase):
    def test_build_message_includes_total_when_entries_are_truncated(self):
        groups = OrderedDict(
            [
                ("新增", ["a%d" % i for i in range(autocommit.MAX_FILES_IN_MESSAGE + 2)]),
                ("修改", ["b1"]),
            ]
        )

        message = autocommit.build_message(groups, datetime(2026, 9, 20, 10, 30))
        self.assertIn("学习记录 2026-09-20 10:30", message)
        self.assertIn("- 新增：等共 %d 个文件" % (autocommit.MAX_FILES_IN_MESSAGE + 2), message)
        self.assertIn("共计 %d 个文件变动。" % (autocommit.MAX_FILES_IN_MESSAGE + 3), message)

    def test_build_message_omits_total_when_all_entries_are_shown(self):
        groups = OrderedDict([("修改", ["README.md", "tools/review.py"])])
        message = autocommit.build_message(groups, datetime(2026, 9, 20, 10, 30))
        self.assertNotIn("共计", message)


if __name__ == "__main__":
    unittest.main()
