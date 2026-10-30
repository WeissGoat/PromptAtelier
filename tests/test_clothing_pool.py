from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from tags_machine_core.web.clothing_pool import (
    _newest_source_mtime,
    _scan_exports,
    refresh_clothing_pool,
)

STUB_EXPORTER = textwrap.dedent(
    """
    import argparse
    import os
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--export-dir", required=True)
    parser.add_argument("--min-tags", type=int, default=4)
    args = parser.parse_args()

    marker = Path(__file__).with_name("calls.txt")
    with marker.open("a", encoding="utf-8") as handle:
        handle.write("run\\n")

    if os.environ.get("STUB_EXPORTER_FAIL") == "1":
        sys.stderr.write("boom: exporter exploded\\n")
        raise SystemExit(3)

    root = Path(args.export_dir) / "st_2girls" / "node"
    root.mkdir(parents=True, exist_ok=True)
    (root / "meta.yaml").write_text("schema: tags-machine.clothing/v1\\n", encoding="utf-8")
    print("Total Candidates Scanned  : 1")
    print("Exported Clothing Nodes   : 1")
    """
).strip()


class ClothingPoolTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "动作改2"
        (self.root / "tools").mkdir(parents=True)
        (self.root / "tools" / "extract_action_clothes.py").write_text(
            STUB_EXPORTER, encoding="utf-8"
        )
        self.node = self.root / "new" / "20260101_1_测试动作"
        self.node.mkdir(parents=True)
        (self.node / "tags.txt").write_text("blue dress, standing\n", encoding="utf-8")
        self.export = self.base / "服装"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _calls(self) -> int:
        marker = self.root / "tools" / "calls.txt"
        return len(marker.read_text(encoding="utf-8").splitlines()) if marker.exists() else 0

    def test_scans_only_clothing_sources(self) -> None:
        (self.root / "new" / "x").mkdir()
        (self.root / "new" / "x" / "image.png").write_text("not a source", encoding="utf-8")
        self.assertGreater(_newest_source_mtime(self.root), 0)
        self.assertEqual(_scan_exports(self.export), (0.0, 0))

    def test_skips_when_export_is_newer(self) -> None:
        first = refresh_clothing_pool(self.root, export_root=self.export)
        self.assertTrue(first["ok"], first)
        self.assertEqual(self._calls(), 1)
        second = refresh_clothing_pool(self.root, export_root=self.export)
        self.assertTrue(second["ok"], second)
        self.assertEqual(second.get("skipped"), "up to date")
        self.assertEqual(second["nodes"], 1)
        self.assertEqual(self._calls(), 1)

    def test_reruns_when_source_changed(self) -> None:
        refresh_clothing_pool(self.root, export_root=self.export)
        tags = self.node / "tags.txt"
        os.utime(tags, (tags.stat().st_atime, tags.stat().st_mtime + 60))
        again = refresh_clothing_pool(self.root, export_root=self.export)
        self.assertTrue(again["ok"], again)
        self.assertNotIn("skipped", again)
        self.assertEqual(self._calls(), 2)

    def test_force_ignores_timestamps(self) -> None:
        refresh_clothing_pool(self.root, export_root=self.export)
        forced = refresh_clothing_pool(self.root, export_root=self.export, force=True)
        self.assertTrue(forced["ok"], forced)
        self.assertEqual(self._calls(), 2)

    def test_exporter_failure_is_reported_not_raised(self) -> None:
        os.environ["STUB_EXPORTER_FAIL"] = "1"
        try:
            report = refresh_clothing_pool(self.root, export_root=self.export)
        finally:
            os.environ.pop("STUB_EXPORTER_FAIL", None)
        self.assertFalse(report["ok"])
        self.assertEqual(report["returncode"], 3)
        self.assertIn("boom", report["error"])

    def test_missing_exporter_is_skipped(self) -> None:
        (self.root / "tools" / "extract_action_clothes.py").unlink()
        report = refresh_clothing_pool(self.root, export_root=self.export)
        self.assertFalse(report["ok"])
        self.assertIn("exporter not found", report["skipped"])


if __name__ == "__main__":
    unittest.main()
