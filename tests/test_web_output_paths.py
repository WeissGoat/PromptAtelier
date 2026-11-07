from pathlib import Path
from unittest import TestCase

from tags_machine_core.web.services.output_paths import resolve_output_dir


class ResolveOutputDirTest(TestCase):
    def test_relative_dirs_join_the_output_root(self):
        root = Path("G:/ai_auto/output")
        self.assertEqual(resolve_output_dir(root, "compares/studio_1"), str(root.resolve() / "compares" / "studio_1"))
        self.assertEqual(resolve_output_dir(root, r"outputs\compares\studio_1"), str(root.resolve() / "compares" / "studio_1"))

    def test_absolute_and_missing_dirs_pass_through(self):
        self.assertIsNone(resolve_output_dir("G:/ai_auto/output", None))
        self.assertIsNone(resolve_output_dir("G:/ai_auto/output", "  "))
        absolute = str(Path.cwd() / "elsewhere")
        self.assertEqual(resolve_output_dir("G:/ai_auto/output", absolute), absolute)

    def test_rejects_dirs_that_leave_the_root(self):
        with self.assertRaises(ValueError):
            resolve_output_dir("G:/ai_auto/output", "compares/../../x")
