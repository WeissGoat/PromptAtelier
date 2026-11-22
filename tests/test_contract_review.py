"""契约 CLI 的分段读取、新建 / 复制、新校验器（identity_anchor、frame_novelty）和出图复核。"""

from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml
from PIL import Image

from tags_machine_core.cli import main
from tags_machine_core.compose_contracts import ContractService
from tags_machine_core.compose_contracts.review import results_report, review_contract, short_error
from tags_machine_core.compose_contracts.selection import select_frames, select_indexes
from tags_machine_core.execution import write_png_text_chunks
from tests.test_compose_contracts import make_design_root


def _frames(*ids: str) -> list[dict]:
    return [{"id": frame_id} for frame_id in ids]


class SelectionTest(unittest.TestCase):
    def test_index_ranges(self):
        self.assertEqual(select_indexes("1-3,5", 10), {1, 2, 3, 5})
        self.assertEqual(select_indexes("8-", 10), {8, 9, 10})
        self.assertEqual(select_indexes("3-1，20", 5), {1, 2, 3})
        self.assertEqual(select_indexes(None, 3), {1, 2, 3})
        with self.assertRaises(ValueError):
            select_indexes("a-b", 3)

    def test_frame_ranges_follow_contract_order(self):
        frames = _frames("f01", "f02", "f02b", "f03", "f04")
        self.assertEqual([f["id"] for f in select_frames(frames, "f02-f03")], ["f02", "f02b", "f03"])
        self.assertEqual([f["id"] for f in select_frames(frames, "f04,f01")], ["f01", "f04"])
        self.assertEqual([f["id"] for f in select_frames(frames, "f03-")], ["f03", "f04"])
        with self.assertRaisesRegex(ValueError, "f09"):
            select_frames(frames, "f01-f09")


class ContractToolingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.design = make_design_root(base)
        self.output = base / "outputs"
        self.service = ContractService(root=self.design / "动作改2" / "contracts", design_root=self.design, output_dir=self.output)
        self.config = base / "config.yaml"
        self.config.write_text(
            yaml.safe_dump({
                "legacy": {"tags_machine_root": str(base), "design_root": str(self.design)},
                "runtime": {"output_dir": str(self.output), "cache_dir": str(base / "cache")},
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def _create(self, requirements: str = "夜晚教室", body: str | None = None) -> dict:
        detail = self.service.create({
            "action_group": "stn_20260101_0001",
            "characters": ["series/char_a"],
            "requirements": requirements,
            "options": {"keep_order": False},
        })
        if body is not None:
            detail = self.service.import_frames(detail["id"], body)
        return detail

    def _cli(self, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([*argv, "--config", str(self.config)])
        return code, json.loads(out.getvalue()) if out.getvalue().strip() else {}

    # ---- 分段读取 ----

    def test_show_and_context_can_be_read_in_pieces(self):
        body = "".join(f"## f0{i} t{i}\nsource: #{1 + i % 2}\ncharacters: c1\n\n```positive\nchar_a, 1girl, pose{i}\n```\n\n" for i in range(1, 5))
        detail = self._create(body=body)
        shown = self.service.show(detail["id"], frames="f02-f03", summary=True)
        self.assertEqual(shown["frame_count"], 4)
        self.assertEqual([frame["id"] for frame in shown["frames"]], ["f02", "f03"])
        self.assertNotIn("prompts", shown["frames"][0])
        self.assertIn("tokens", shown["frames"][0])

        context = self.service.context(detail["id"], members="2-", summary=True)
        members = context["action_group"]["members"]
        self.assertEqual([m["index"] for m in members], [2])
        self.assertNotIn("positive", members[0])
        full = self.service.context(detail["id"], members="1")
        self.assertIn("positive", full["action_group"]["members"][0])
        with self.assertRaises(ValueError):
            self.service.context(detail["id"], members="9")

    # ---- 新建 / 复制 ----

    def test_cli_create_and_clone(self):
        code, created = self._cli(
            "contract", "create", "--action-group", "stn_20260101_0001", "--character", "series/char_a",
            "--requirements", "雨夜", "--no-keep-order", "--max-new-frames", "5",
        )
        self.assertEqual(code, 0, created)
        detail = self.service.detail(created["id"])
        self.assertEqual(detail["request"]["requirements"], "雨夜")
        self.assertEqual(detail["request"]["options"]["keep_order"], False)
        self.assertEqual(detail["request"]["options"]["max_new_frames"], 5)
        self.assertIn("contract prompt", created["next"])

        self.service.import_frames(created["id"], "## f01 a\nsource: #1\ncharacters: c1\n\n```positive\nchar_a, 1girl\n```\n")
        code, cloned = self._cli("contract", "clone", created["id"], "--requirements", "雪夜")
        self.assertEqual(code, 0, cloned)
        copy = self.service.detail(cloned["id"])
        self.assertNotEqual(cloned["id"], created["id"])
        self.assertEqual(copy["request"]["requirements"], "雪夜")
        self.assertEqual(copy["request"]["options"]["max_new_frames"], 5)  # 没写的选项沿用
        self.assertEqual(copy["request"]["status"], "pending")
        self.assertEqual(copy["frames"], [])

        with_frames = self.service.clone(created["id"], with_frames=True)
        self.assertEqual([frame["id"] for frame in with_frames["frames"]], ["f01"])
        self.assertEqual(with_frames["request"]["requirements"], "雨夜")

    # ---- 校验器 ----

    def test_identity_anchor_flags_frames_without_character_tags(self):
        body = (
            "## f01 全身\nsource: #1\ncharacters: c1\n\n```positive\nchar_a, 1girl, standing\n```\n\n"
            "## f02 特写\nsource: #2\ncharacters: c1\n\n```positive\n1girl, close-up, hand, sitting\n```\n\n"
            "## f03 发色\nsource: custom\ncharacters: c1\n\n```positive\nblack hair, 1girl, looking back\n```\n"
        )
        detail = self._create(body=body)
        flagged = [issue["frame_id"] for issue in detail["issues"] if issue["validator"] == "identity_anchor"]
        self.assertEqual(flagged, ["f02"])

    def test_frame_novelty_flags_near_duplicate_neighbours(self):
        def frame(frame_id: str, tags: str, source: str = "#1") -> str:
            return f"## {frame_id} x\nsource: {source}\ncharacters: c1\n\n```positive\nchar_a, 1girl, {tags}\n```\n\n"

        body = (
            frame("f01", "standing, from side, smile")
            + frame("f02", "standing, from side, smile, blush")    # 只多一个词
            + frame("f03", "sitting, from above, crying, tears")   # 真的变化
            + frame("f04", "sitting, from above, crying, tears")   # 完全相同
        )
        detail = self._create(body=body)
        novelty = {issue["frame_id"]: issue["message"] for issue in detail["issues"] if issue["validator"] == "frame_novelty"}
        self.assertEqual(sorted(novelty), ["f02", "f04"])
        self.assertIn("+blush", novelty["f02"])
        self.assertIn("完全相同", novelty["f04"])

    def test_prompts_keep_request_options_with_or_without_requirements(self):
        for requirements in ("保持戒备", ""):
            detail = self._create(requirements=requirements)
            for kind in ("tools", "standalone"):
                prompt = self.service.prompt(detail["id"], kind)["text"]
                self.assertIn("保持动作组顺序 否", prompt)
                self.assertIn(requirements or "无（按动作组原样逐帧拼接角色）", prompt)

    # ---- 出图结果与复核 ----

    def _image(self, run: str, frame: dict, contract_id: str, name: str, *, phash: str | None = None, size=(64, 96), uc: str = "") -> Path:
        path = self.output / "compares" / run / frame["id"] / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (120, 80, 60)).save(path)
        core = {"model": "nai-diffusion-4-5-full",
                "contract": {"id": contract_id, "frame_id": frame["id"], "prompt_hash": phash or frame["prompt_hash"], "artist": "style_a"}}
        comment = {"steps": 23, "scale": 5.0, "cfg_rescale": 0.0, "sampler": "k_euler_ancestral", "width": size[0], "height": size[1],
                   "seed": 7, "uc": uc}
        write_png_text_chunks(path, {"tags_machine_core": json.dumps(core), "Comment": json.dumps(comment)})
        return path

    def _job(self, job_id: str, run: str, contract_id: str, items: list[tuple[str, str, str | None]], status: str = "succeeded") -> None:
        jobs = self.output / ".web" / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        request = {"label": "x", "kind": "contract", "output_dir": str(self.output / "compares" / run), "items": [
            {"compose_request": {"compose": {"contract": {"id": contract_id, "frame_id": frame_id, "artist": "style_a"}}}}
            for frame_id, _, _ in items
        ]}
        result = {"items": [
            {"index": index, "status": item_status, "error": error, "finished_at": time.time() + 5}
            for index, (_, item_status, error) in enumerate(items)
        ]}
        (jobs / f"{job_id}.request.json").write_text(json.dumps(request), encoding="utf-8")
        (jobs / f"{job_id}.json").write_text(json.dumps({"id": job_id, "status": status, "result": result}), encoding="utf-8")

    def test_results_and_review_report_frame_status(self):
        body = (
            "## f01 a\nsource: #1\ncharacters: c1\nsize: portrait\n\n```positive\nchar_a, 1girl, standing, nsfw, blush\n```\n\n"
            "## f02 b\nsource: #2\ncharacters: c1\n\n```positive\nchar_a, 1girl, sitting\n```\n\n"
            "## f03 c\nsource: custom\ncharacters: c1\n\n```positive\nchar_a, 1girl, lying\n```\n\n"
            "## f04 d\nsource: custom\ncharacters: c1\n\n```positive\nchar_a, 1girl, kneeling\n```\n"
        )
        detail = self._create(body=body)
        cid = detail["id"]
        f01, f02, f03, f04 = detail["frames"]
        run = "contract_20260101_0001"
        self._image(run, f01, cid, "a.png", uc="nsfw, blush, lowres")
        self._image(run, f01, cid, "wide.png", size=(96, 64))
        self._image(run, f02, cid, "old.png", phash="sha256:old")
        self._job("job1", run, cid, [("f01", "succeeded", None), ("f03", "failed", "HTTP 403: <!DOCTYPE html><title>Just a moment...</title>")])
        self._job("job2", "contract_20260101_0002", cid, [("f04", "queued", None)], status="running")

        report = results_report(self.service, cid)
        status = {frame["id"]: frame["status"] for frame in report["frames"]}
        self.assertEqual(status, {"f01": "ok", "f02": "stale", "f03": "failed", "f04": "pending"})
        failed = next(frame for frame in report["frames"] if frame["id"] == "f03")
        self.assertIn("Cloudflare", failed["failure"]["error"])
        self.assertEqual(report["counts"]["failed"], 1)
        self.assertEqual(len(next(f for f in report["frames"] if f["id"] == "f01")["latest_round"]), 2)
        self.assertEqual(results_report(self.service, cid, current_only=True, frames="f02")["frames"][0]["status"], "stale")

        review = review_contract(self.service, cid, sheets=True)
        checks = {(warning["check"], warning["message"].split("：")[0]) for warning in review["audit"]["warnings"]}
        self.assertIn(("size", "画幅是 landscape，帧要求 portrait"), checks)
        self.assertTrue(any(w["check"] == "negative" and "nsfw" in w["message"] for w in review["audit"]["warnings"]))
        self.assertTrue(any(w["check"] == "negative" and "blush" in w["message"] for w in review["audit"]["warnings"]))
        self.assertTrue(review["audit"]["adult"])
        self.assertTrue(any("f03" in line for line in review["todo"]))
        self.assertTrue(review["frames"][0]["representative"].endswith(".png"))
        sheets = [Path(path) for path in review["sheets"]]
        self.assertEqual([path.name for path in sheets], ["overview_01.jpg", "frames_01.jpg"])
        self.assertTrue(all(path.is_file() for path in sheets))
        self.assertTrue((Path(review["out_dir"]) / "review.json").is_file())

        code, payload = self._cli("contract", "results", cid, "--frames", "f03")
        self.assertEqual(code, 0)
        self.assertEqual([frame["id"] for frame in payload["frames"]], ["f03"])

    def test_short_error_trims_html(self):
        self.assertEqual(short_error("ConnectError"), "ConnectError")
        self.assertIsNone(short_error(None))
        self.assertIn("HTML", short_error("HTTP 500: <html><body>" + "x" * 500))


if __name__ == "__main__":
    unittest.main()
