from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase
from unittest.mock import patch


def _load_fetch_models():
    path = Path(__file__).resolve().parents[1] / "deploy" / "comfyui" / "fetch_models.py"
    spec = importlib.util.spec_from_file_location("tm_fetch_models", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_models = _load_fetch_models()
CONTENT = b"model-bytes"
MODEL = {
    "path": "loras/画风调整/add contrast.safetensors",
    "size": len(CONTENT),
    "sha256": hashlib.sha256(CONTENT).hexdigest(),
    "source": "civitai",
}


class FakeRclone:
    """按子命令应答的假 rclone：lsjson 返回给定的文件列表，copyto 写入固定内容。"""

    def __init__(self, files: list[dict], *, fail_list: bool = False):
        self.files = files
        self.fail_list = fail_list
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[1] == "lsjson":
            if self.fail_list:
                return subprocess.CompletedProcess(command, 1, "", "didn't find section in config file\n")
            return subprocess.CompletedProcess(command, 0, json.dumps(self.files), "")
        if command[1] == "copyto":
            Path(command[3]).write_bytes(CONTENT)
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected rclone command: {command}")


def _sync(dest: Path, rclone: FakeRclone, *, which: str | None = "rclone") -> str:
    output = io.StringIO()
    with (
        patch.object(fetch_models.shutil, "which", return_value=which),
        patch.object(fetch_models.subprocess, "run", side_effect=rclone),
        patch.object(fetch_models, "resolve_download", return_value=("https://example.test/model", {})) as resolve,
        patch.object(fetch_models, "download", side_effect=lambda url, headers, partial: partial.write_bytes(CONTENT)),
        contextlib.redirect_stdout(output),
    ):
        fetch_models.sync_model(
            MODEL,
            dest,
            [],
            mirrors=[fetch_models.Mirror("tmgdrive:tm-models/")],
            verify=False,
            dry_run=False,
        )
    return output.getvalue() + ("source used" if resolve.called else "")


class FetchModelsMirrorTest(TestCase):
    def test_pulls_from_the_model_store_before_the_source(self):
        rclone = FakeRclone([{"Path": MODEL["path"], "Size": MODEL["size"]}])
        with tempfile.TemporaryDirectory() as tmp:
            log = _sync(Path(tmp), rclone)
            saved = (Path(tmp) / MODEL["path"]).read_bytes()

        self.assertEqual(saved, CONTENT)
        self.assertIn("pull    tmgdrive:tm-models/" + MODEL["path"], log)
        self.assertNotIn("source used", log)
        self.assertEqual(rclone.calls[-1][2], "tmgdrive:tm-models/" + MODEL["path"])

    def test_falls_back_to_the_source_when_the_store_lacks_the_file(self):
        rclone = FakeRclone([{"Path": MODEL["path"], "Size": MODEL["size"] + 1}])
        with tempfile.TemporaryDirectory() as tmp:
            log = _sync(Path(tmp), rclone)

        self.assertIn("source used", log)
        self.assertEqual([call[1] for call in rclone.calls], ["lsjson"])

    def test_skips_stores_it_cannot_reach(self):
        for which, rclone in (
            (None, FakeRclone([])),
            ("rclone", FakeRclone([], fail_list=True)),
        ):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as tmp:
                log = _sync(Path(tmp), rclone, which=which)

                self.assertIn("skip    mirror tmgdrive:tm-models", log)
                self.assertIn("source used", log)

    def test_check_reports_missing_and_mismatched_files(self):
        models = [
            MODEL,
            {**MODEL, "path": "checkpoints/missing.safetensors"},
            {**MODEL, "path": "sams/wrong-size.pth"},
            {**MODEL, "path": "ultralytics/wrong-hash.pt"},
        ]
        rclone = FakeRclone(
            [
                {"Path": MODEL["path"], "Size": MODEL["size"], "Hashes": {"sha256": MODEL["sha256"].upper()}},
                {"Path": "sams/wrong-size.pth", "Size": 1},
                {"Path": "ultralytics/wrong-hash.pt", "Size": MODEL["size"], "Hashes": {"sha256": "0" * 64}},
            ]
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(fetch_models.shutil, "which", return_value="rclone"),
            patch.object(fetch_models.subprocess, "run", side_effect=rclone),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = fetch_models.check_mirrors(models, [fetch_models.Mirror("tmgdrive:tm-models")])

        self.assertEqual(code, 1)
        self.assertIn("--hash", rclone.calls[0])
        self.assertEqual(stdout.getvalue().strip(), f"ok      tmgdrive:tm-models/{MODEL['path']}")
        problems = stderr.getvalue()
        self.assertIn("checkpoints/missing.safetensors: missing", problems)
        self.assertIn("sams/wrong-size.pth: size 1 != manifest", problems)
        self.assertIn("ultralytics/wrong-hash.pt: sha256", problems)

    def test_reads_model_stores_from_the_model_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_file = Path(tmp) / "models.yaml"
            models_file.write_text(
                "mirrors:\n  - rclone: tmgdrive:tm-models\n  - note: ignored\nmodels: []\n",
                encoding="utf-8",
            )

            self.assertEqual(fetch_models.load_mirrors(models_file), ["tmgdrive:tm-models"])
