"""git_pull_ff_only 的行为测试：脏工作区不再一概阻断，交给 git 自己判断。

覆盖三种情况：
1. 本地有改动、远端改别的文件 → pull 成功，本地改动保留
2. 本地有改动、远端改同一个文件 → git 中止，报告带 reason + dirty
3. 工作区干净 → 正常快进
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tags_machine_core.web.category_view import git_pull_ff_only  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    import os

    env = {**os.environ, **GIT_ENV}
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, env=env
    )


class PullFFOnlyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.remote = base / "remote.git"
        self.seed = base / "seed"
        self.clone = base / "clone"

        git(base, "init", "--bare", "-q", "-b", "main", str(self.remote))
        git(base, "init", "-q", "-b", "main", str(self.seed))
        (self.seed / "a.txt").write_text("a1\n", encoding="utf-8")
        (self.seed / "b.txt").write_text("b1\n", encoding="utf-8")
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", "init")
        git(self.seed, "remote", "add", "origin", str(self.remote))
        git(self.seed, "push", "-q", "origin", "main")

        git(base, "clone", "-q", str(self.remote), str(self.clone))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _advance_remote(self, relative: str, content: str) -> None:
        (self.seed / relative).write_text(content, encoding="utf-8")
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", f"update {relative}")
        git(self.seed, "push", "-q", "origin", "main")

    def test_dirty_non_overlapping_still_pulls(self) -> None:
        (self.clone / "a.txt").write_text("local edit\n", encoding="utf-8")
        self._advance_remote("b.txt", "b2\n")

        report = git_pull_ff_only(self.clone)

        self.assertTrue(report["pulled"])
        self.assertNotIn("skipped", report)
        self.assertEqual((self.clone / "a.txt").read_text(encoding="utf-8"), "local edit\n")
        self.assertEqual((self.clone / "b.txt").read_text(encoding="utf-8"), "b2\n")

    def test_dirty_overlapping_is_refused_with_reason(self) -> None:
        (self.clone / "a.txt").write_text("local edit\n", encoding="utf-8")
        self._advance_remote("a.txt", "remote edit\n")

        report = git_pull_ff_only(self.clone)

        self.assertFalse(report["pulled"])
        self.assertEqual(report["reason"], "local changes overlap incoming commits")
        self.assertIn("a.txt", report["dirty"])
        self.assertEqual((self.clone / "a.txt").read_text(encoding="utf-8"), "local edit\n")

    def test_clean_fast_forward(self) -> None:
        self._advance_remote("b.txt", "b3\n")

        report = git_pull_ff_only(self.clone)

        self.assertTrue(report["pulled"])
        self.assertEqual((self.clone / "b.txt").read_text(encoding="utf-8"), "b3\n")


if __name__ == "__main__":
    unittest.main()
