from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.cli import main
from tags_machine_core.compose_contracts import ContractConflictError, ContractService, parse_contract
from tags_machine_core.compose_contracts.parser import (
    extract_import_frames,
    replace_frame_prompts,
    set_front_matter_fields,
)
from tags_machine_core.compose_contracts.profiles import load_format_profiles
from tags_machine_core.compose_contracts.service import prompt_hash
from tags_machine_core.compose_contracts.tokens import tokenize_prompt
from tags_machine_core.execution import write_png_text_chunks


CONTRACT = """---
schema: tags-machine.compose-contract/v1
id: demo
title: ""
status: pending
target_format: nai-v4.5
nodes:
  characters:
    c1: { ref: "series/char_a", content_hash: "x" }
  action_group: { ref: stn_20260101_0001 }
requirements: |
  夜晚教室
options: { keep_order: true, allow_new_frames: true, max_new_frames: 1 }
---

前言

## f01 站立
source: new/20260101_0001_01_站立
characters: c1
size: portrait

```positive
char_a, black_hair,
1girl, solo, standing
```

```negative
red_glasses
```

备注一行

## f01b 回头
source: custom
inspired_by: new/20260101_0001_02_坐下

```positive
1girl, looking back
```
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_design_root(base: Path) -> Path:
    design = base / "design"
    actions = design / "动作改2"
    _write(
        actions / "new" / "20260101_0001_01_站立" / "meta.yaml",
        yaml.safe_dump(
            {
                "kind": "action",
                "id": "20260101_0001_01_站立",
                "tags": {"action": ["1girl", "solo", "standing", "white background"]},
                "negative_prompt": ["bad hands"],
                "character_scope": "full_body",
                "clothing": {"state": "clothed"},
            },
            allow_unicode=True,
        ),
    )
    _write(actions / "new" / "20260101_0001_01_站立" / "classify.yaml", "phase: start\ncast: solo\npose: [standing]\n")
    _write(
        actions / "new" / "20260101_0001_02_坐下" / "meta.yaml",
        yaml.safe_dump({"kind": "action", "id": "20260101_0001_02_坐下", "tags": {"action": ["1girl", "sitting"]}}, allow_unicode=True),
    )
    group = actions / "stn_20260101_0001"
    group.mkdir(parents=True)
    os.symlink("../new/20260101_0001_01_站立", group / "01_站立")
    os.symlink("../new/20260101_0001_02_坐下", group / "02_坐下")
    _write(actions / "st_demo" / "2_second" / "tags.txt", "2girls, kiss\n=uc, bad\n")
    _write(actions / "st_demo" / "10_tenth" / "tags.txt", "1girl\n")
    _write(
        design / "角色" / "series" / "char_a" / "meta.yaml",
        yaml.safe_dump(
            {
                "kind": "character",
                "id": "char_a",
                "tags": {"character": ["char_a"], "hair": ["black_hair"]},
            }
        ),
    )
    return design


class ContractParserTest(unittest.TestCase):
    def test_parses_front_matter_frames_blocks_and_notes(self):
        contract = parse_contract(CONTRACT)
        self.assertEqual(contract.request.requirements, "夜晚教室")
        self.assertEqual(contract.request.options.max_new_frames, 1)
        self.assertEqual(contract.preamble, "前言")
        self.assertEqual([frame.id for frame in contract.frames], ["f01", "f01b"])
        first = contract.frames[0]
        self.assertEqual(first.title, "站立")
        self.assertEqual(first.size, "portrait")
        self.assertEqual(first.characters, ["c1"])
        self.assertEqual(first.positive, "char_a, black_hair,\n1girl, solo, standing")
        self.assertEqual(first.negative, "red_glasses")
        self.assertEqual(first.notes, "备注一行")
        self.assertTrue(contract.frames[1].is_custom)
        self.assertEqual(contract.frames[1].inspired_by, ["new/20260101_0001_02_坐下"])

    def test_headers_inside_code_blocks_do_not_start_frames(self):
        text = CONTRACT.replace("1girl, looking back", "## not a frame\n1girl")
        contract = parse_contract(text)
        self.assertEqual(len(contract.frames), 2)
        self.assertIn("## not a frame", contract.frames[1].positive)

    def test_replace_frame_prompts_only_touches_target_blocks(self):
        updated = replace_frame_prompts(
            CONTRACT,
            "f01",
            {"positive": "1girl,\nsitting", "negative": "", "positive c2": "1boy"},
        )
        contract = parse_contract(updated)
        frame = contract.frame("f01")
        self.assertEqual(frame.positive, "1girl,\nsitting")
        self.assertIsNone(frame.block("negative"))
        self.assertEqual(frame.block("positive", "c2").text, "1boy")
        self.assertEqual(frame.notes, "备注一行")
        self.assertEqual(contract.frame("f01b").positive, "1girl, looking back")
        self.assertIn("前言", updated)

    def test_replace_adds_blocks_to_frame_without_code(self):
        text = CONTRACT.replace("```positive\n1girl, looking back\n```\n", "")
        updated = replace_frame_prompts(text, "f01b", {"positive": "1girl"})
        frame = parse_contract(updated).frame("f01b")
        self.assertEqual(frame.positive, "1girl")
        self.assertEqual(frame.source, "custom")

    def test_set_front_matter_fields_keeps_other_lines(self):
        updated = set_front_matter_fields(CONTRACT, {"status": "done", "author": "agent x"})
        contract = parse_contract(updated)
        self.assertEqual(contract.request.status, "done")
        self.assertEqual(contract.request.author, "agent x")
        self.assertIn("requirements: |\n  夜晚教室", updated)

    def test_extract_import_frames_handles_wrappers(self):
        raw = "```markdown\n---\ntitle: 夜晚\n---\n说明\n## f01 a\nsource: x\n\n```positive\n1girl\n```\n```"
        body, extra = extract_import_frames(raw)
        self.assertTrue(body.startswith("## f01 a"))
        self.assertEqual(extra, {"title": "夜晚"})


class TokenizeTest(unittest.TestCase):
    def test_weights_span_multiple_tags(self):
        tags = tokenize_prompt("1.2::leaning forward, bent over::, {smile, blush}, [sad], (night:1.3), plain")
        by_key = {tag.key: tag for tag in tags}
        self.assertEqual(by_key["leaning_forward"].weight, 1.2)
        self.assertEqual(by_key["bent_over"].weight, 1.2)
        self.assertAlmostEqual(by_key["smile"].weight, 1.05)
        self.assertAlmostEqual(by_key["blush"].weight, 1.05)
        self.assertAlmostEqual(by_key["sad"].weight, round(1 / 1.05, 4))
        self.assertEqual(by_key["night"].weight, 1.3)
        self.assertEqual(by_key["plain"].weight, 1.0)
        self.assertIn("paren", by_key["night"].syntaxes)

    def test_newlines_split_and_positions_point_into_text(self):
        text = "a b,\nc-d"
        tags = tokenize_prompt(text)
        self.assertEqual([tag.key for tag in tags], ["a_b", "c_d"])
        self.assertEqual(text[tags[1].start:tags[1].end], "c-d")
        self.assertEqual(tags[1].line, 1)


class ContractServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.design = make_design_root(base)
        self.output = base / "outputs"
        self.service = ContractService(
            root=self.design / "动作改2" / "contracts",
            design_root=self.design,
            output_dir=self.output,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _create(self, **extra):
        payload = {
            "action_group": "stn_20260101_0001",
            "characters": [str(self.design / "角色" / "series" / "char_a")],
            "requirements": "夜晚教室\n第二行",
            **extra,
        }
        return self.service.create(payload)

    def test_builtin_profiles_load(self):
        profiles = load_format_profiles()
        self.assertTrue({"nai-v4.5", "nai-v4", "sdxl-danbooru"} <= set(profiles))
        self.assertEqual(profiles["nai-v4.5"].prompt_for_submit("a,\n\nb ,c"), "a, b, c")

    def test_action_group_members_follow_node_reader(self):
        group = self.service.action_group("stn_20260101_0001")
        first = group["members"][0]
        self.assertEqual(first["ref"], "new/20260101_0001_01_站立")
        self.assertEqual(first["positive"], "1girl, solo, standing, white background")
        self.assertEqual(first["negative"], "bad hands")
        self.assertEqual(first["source_file"], "meta.yaml")
        self.assertEqual(first["classify"]["cast"], "solo")
        st_group = self.service.action_group("st_demo")
        self.assertEqual([m["name"] for m in st_group["members"]], ["2_second", "10_tenth"])
        self.assertEqual(st_group["members"][0]["positive"], "2girls, kiss")
        self.assertEqual(st_group["members"][0]["negative"], "")
        self.assertEqual(st_group["members"][0]["source_file"], "tags.txt")
        refs = [group["ref"] for group in self.service.action_groups()]
        self.assertEqual(sorted(refs), ["st_demo", "stn_20260101_0001"])

    def test_create_writes_pending_contract_with_relative_refs(self):
        detail = self._create()
        self.assertEqual(detail["request"]["status"], "pending")
        self.assertEqual(detail["request"]["nodes"]["characters"]["c1"]["ref"], "series/char_a")
        self.assertEqual(detail["request"]["requirements"], "夜晚教室\n第二行")
        self.assertEqual(detail["frames"], [])
        self.assertEqual(detail["stale"], [])
        self.assertTrue(detail["id"].endswith("_stn_20260101_0001"))
        again = self._create()
        self.assertNotEqual(again["id"], detail["id"])

    def test_import_marks_done_and_reports_issues(self):
        detail = self._create()
        body = """## f01 站立
source: new/20260101_0001_01_站立
characters: c1

```positive
char_a, 1girl, solo, standing, by window, masterpiece, artist:someone, 教室, (night:1.2), barefoot, socks
```

## f02 新增
source: custom
inspired_by: new/missing

```positive
1girl, smile, smile
```
"""
        detail = self.service.import_frames(detail["id"], f"```markdown\n---\ntitle: 夜晚\n---\n{body}```")
        self.assertEqual(detail["request"]["status"], "done")
        self.assertEqual(detail["request"]["title"], "夜晚")
        found = {(issue["validator"], issue["severity"]) for issue in detail["issues"]}
        for expected in [
            ("forbidden_tags", "error"),
            ("forbidden_tags", "warn"),
            ("language", "error"),
            ("weight_syntax", "error"),
            ("tag_conflict", "warn"),
            ("duplicate_tags", "warn"),
            ("source_exists", "warn"),
            ("coverage", "warn"),
        ]:
            self.assertIn(expected, found)
        artist_issues = [i for i in detail["issues"] if i["validator"] == "forbidden_tags" and i["severity"] == "error"]
        self.assertEqual([i["tag"] for i in artist_issues], ["artist:someone"])
        self.assertEqual(detail["coverage"]["missing"][0]["ref"], "new/20260101_0001_02_坐下")
        self.assertEqual(detail["frames"][0]["member_index"], 1)
        self.assertTrue(detail["frames"][1]["is_custom"])

    def test_unknown_source_and_missing_positive_are_errors(self):
        detail = self._create()
        detail = self.service.import_frames(detail["id"], "## f01 x\nsource: new/nope\n\n")
        messages = [issue for issue in detail["issues"] if issue["severity"] == "error"]
        validators = {issue["validator"] for issue in messages}
        self.assertIn("source_exists", validators)
        self.assertIn("frame_structure", validators)

    def test_save_frame_detects_conflicts(self):
        detail = self._create()
        detail = self.service.import_frames(detail["id"], "## f01 x\nsource: #1\n\n```positive\n1girl\n```\n")
        saved = self.service.save_frame(detail["id"], "f01", {"positive": "1girl, solo"}, expected_hash=detail["file"]["hash"])
        self.assertEqual(saved["frames"][0]["prompts"]["positive"], "1girl, solo")
        with self.assertRaises(ContractConflictError):
            self.service.save_frame(detail["id"], "f01", {"positive": "x"}, expected_hash=detail["file"]["hash"])

    def test_stale_sources_are_reported(self):
        detail = self._create()
        meta = self.design / "角色" / "series" / "char_a" / "meta.yaml"
        meta.write_text(meta.read_text(encoding="utf-8") + "variant: changed\n", encoding="utf-8")
        detail = self.service.detail(detail["id"])
        self.assertEqual(detail["stale"], [{"node": "characters.c1", "ref": "series/char_a"}])

    def test_prompts_include_requirements_and_materials(self):
        detail = self._create()
        tools = self.service.prompt(detail["id"], "tools")["text"]
        self.assertIn(detail["file"]["path"], tools)
        self.assertIn("contract check", tools)
        self.assertIn("夜晚教室", tools)
        standalone = self.service.prompt(detail["id"], "standalone")["text"]
        self.assertIn("1girl, solo, standing, white background", standalone)
        self.assertIn("hair: black_hair", standalone)

    def test_results_group_images_by_frame_and_track_picks(self):
        from PIL import Image

        detail = self._create()
        detail = self.service.import_frames(detail["id"], "## f01 x\nsource: #1\n\n```positive\n1girl\n```\n")
        frame = detail["frames"][0]
        run = self.output / "compares" / "contract_20260101_abcd" / "f01"
        run.mkdir(parents=True)
        current = run / "a.png"
        old = run / "b.png"
        for path, phash in ((current, frame["prompt_hash"]), (old, "sha256:old")):
            Image.new("RGB", (4, 4)).save(path)
            core = {"contract": {"id": detail["id"], "frame_id": "f01", "prompt_hash": phash, "artist": "style_a"}}
            write_png_text_chunks(path, {"tags_machine_core": json.dumps(core)})
        results = self.service.results(detail["id"])
        images = results["frames"]["f01"]
        self.assertEqual({image["current"] for image in images}, {True, False})
        self.assertEqual(images[0]["artist"], "style_a")
        picks = self.service.update_picks(detail["id"], "f01", add=[images[0]["path"]])
        self.assertEqual(picks, {"f01": [images[0]["path"]]})
        self.assertTrue(any(image["picked"] for image in self.service.results(detail["id"])["frames"]["f01"]))
        self.assertEqual(self.service.update_picks(detail["id"], "f01", remove=[images[0]["path"]]), {})
        self.assertEqual(prompt_hash("1girl", ""), frame["prompt_hash"])


TWO_CHARACTER_FRAME = """## f01 并排
source: custom
characters: c1, c2

```positive
2girls, sitting,
night
```

```positive c2
girl, char_b, pink_hair
```

```negative c2
glasses
```

```positive c1
girl, char_a,
black_hair
```
"""


class MultiCharacterContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.design = make_design_root(base)
        _write(
            self.design / "角色" / "series" / "char_b" / "meta.yaml",
            yaml.safe_dump({"kind": "character", "id": "char_b", "tags": {"character": ["char_b"], "hair": ["pink_hair"]}}),
        )
        self.service = ContractService(root=self.design / "动作改2" / "contracts", design_root=self.design, output_dir=base / "out")
        self.contract_id = self.service.create(
            {"action_group": "stn_20260101_0001", "characters": ["series/char_a", "series/char_b"], "requirements": "r"}
        )["id"]

    def tearDown(self):
        self.temp.cleanup()

    def _import(self, body: str) -> dict:
        return self.service.import_frames(self.contract_id, body)

    def _issues(self, detail: dict, validator: str = "character_blocks") -> list[tuple[str, str]]:
        return [(item["severity"], item["message"]) for item in detail["issues"] if item["validator"] == validator]

    def test_character_prompts_follow_contract_order_and_enter_prompt_hash(self):
        detail = self._import(TWO_CHARACTER_FRAME)
        frame = detail["frames"][0]
        self.assertEqual(
            frame["character_prompts"],
            [
                {"id": "c1", "positive": "girl, char_a, black_hair", "negative": ""},
                {"id": "c2", "positive": "girl, char_b, pink_hair", "negative": "glasses"},
            ],
        )
        self.assertNotEqual(frame["prompt_hash"], prompt_hash("2girls, sitting,\nnight", ""))
        self.assertEqual(self._issues(detail), [])
        changed = self._import(TWO_CHARACTER_FRAME.replace("pink_hair", "pink_hair, twintails"))
        self.assertNotEqual(changed["frames"][0]["prompt_hash"], frame["prompt_hash"])

    def test_single_block_frames_keep_previous_hash(self):
        detail = self._import("## f01 x\nsource: custom\ncharacters: c1\n\n```positive\n1girl\n```\n")
        frame = detail["frames"][0]
        self.assertEqual(frame["character_prompts"], [])
        self.assertEqual(frame["prompt_hash"], prompt_hash("1girl", ""))

    def test_inline_character_blocks_mixed_with_code_blocks_is_an_error(self):
        body = TWO_CHARACTER_FRAME.replace("night\n", "night, ::character A: girl, smile ::\n", 1)
        issues = self._issues(self._import(body))
        self.assertEqual([severity for severity, _ in issues], ["error"])
        only_inline = "## f01 x\nsource: custom\ncharacters: c1, c2\n\n```positive\n2girls, ::character A: girl, char_a ::, ::character B: girl, char_b ::\n```\n"
        self.assertEqual([severity for severity, _ in self._issues(self._import(only_inline))], ["info"])

    def test_misplaced_character_tags_and_missing_blocks_warn(self):
        body = (
            "## f01 x\nsource: custom\ncharacters: c1, c2\n\n"
            "```positive\n2girls, pink_hair\n```\n\n"
            "```positive c1\ngirl, char_a, black_hair, char_b\n```\n"
        )
        messages = [message for _, message in self._issues(self._import(body))]
        self.assertTrue(any("没有 ```positive c2" in message for message in messages), messages)
        self.assertTrue(any("「char_b」是 c2 的角色词，写在了 c1 的块里" in message for message in messages), messages)
        # pink_hair 属于 c2，但本帧没有 c2 的块，主提示词里写它不算错。
        self.assertFalse(any("pink_hair" in message for message in messages), messages)
        with_c2 = body + "\n```positive c2\ngirl, char_b\n```\n"
        messages = [message for _, message in self._issues(self._import(with_c2))]
        self.assertTrue(any("「pink_hair」是 c2 的角色词，写在了主提示词里" in message for message in messages), messages)

    def test_requirement_prompts_explain_character_blocks(self):
        for kind in ("tools", "standalone"):
            text = self.service.prompt(self.contract_id, kind)["text"]
            self.assertIn("## 多角色", text)
            self.assertIn("```positive c1", text)


class ContractCliAndRouteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.design = make_design_root(base)
        self.config = base / "config.yaml"
        self.config.write_text(
            yaml.safe_dump(
                {
                    "legacy": {"tags_machine_root": str(base), "design_root": str(self.design)},
                    "runtime": {"output_dir": str(base / "outputs"), "cache_dir": str(base / "cache")},
                }
            ),
            encoding="utf-8",
        )
        self.client = TestClient(create_app_for(self.config, base))

    def tearDown(self):
        self.temp.cleanup()

    def test_routes_and_cli_round_trip(self):
        formats = self.client.get("/api/formats").json()["formats"]
        self.assertIn("nai-v4.5", [item["id"] for item in formats])
        groups = self.client.get("/api/contracts/action-groups").json()["groups"]
        self.assertEqual(len(groups), 2)
        created = self.client.post(
            "/api/contracts",
            json={"action_group": "stn_20260101_0001", "characters": ["series/char_a"], "requirements": "r"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        contract_id = created.json()["id"]
        listing = self.client.get("/api/contracts", params={"node": str(self.design / "角色" / "series" / "char_a")}).json()
        self.assertEqual([item["id"] for item in listing["contracts"]], [contract_id])
        index = self.client.get("/api/contracts/index", params={"since": 0}).json()
        self.assertEqual(index["changed"][0]["status"], "pending")
        prompt = self.client.get(f"/api/contracts/{contract_id}/prompt", params={"kind": "standalone"})
        self.assertEqual(prompt.status_code, 200)
        imported = self.client.post(
            f"/api/contracts/{contract_id}/import",
            json={"text": "## f01 a\nsource: #1\ncharacters: c1\n\n```positive\nchar_a, 1girl, solo, standing\n```\n\n## f02 b\nsource: #2\n\n```positive\n1girl, sitting\n```\n"},
        ).json()
        self.assertEqual(imported["issue_counts"]["error"], 0, imported["issues"])
        conflict = self.client.put(
            f"/api/contracts/{contract_id}/frames/f01",
            json={"prompts": {"positive": "x"}, "hash": "sha256:stale"},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get("/api/contracts/missing").status_code, 404)

        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["contract", "check", contract_id, "--config", str(self.config)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertTrue(json.loads(out.getvalue())["ok"])
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["contract", "context", contract_id, "--member", "2", "--config", str(self.config)])
        self.assertEqual(code, 0)
        context = json.loads(out.getvalue())
        self.assertEqual([m["index"] for m in context["action_group"]["members"]], [2])


def create_app_for(config: Path, base: Path):
    from tags_machine_core.web.app import create_app

    return create_app(config_path=config, style_lab_dir=base / "stylelab")


class ContractTraceTest(unittest.TestCase):
    def test_agent_compose_carries_contract_trace_into_render_meta(self):
        from tags_machine_core.execution import build_core_png_text
        from tags_machine_core.services import GenerationJsonApi

        api = GenerationJsonApi()
        plan = api.resolve_compose_render_plan(
            {
                "compose": {
                    "composer": "agent",
                    "nodes": [{"role": "character", "ref": "c", "node": {"id": "c", "kind": "character"}}],
                    "agent_result": {"positive": "1girl", "negative": ""},
                    "contract": {"id": "demo", "frame_id": "f01", "prompt_hash": "h", "artist": "a"},
                },
                "render": {"backend": "novelai", "width": 832, "height": 1216},
            }
        )
        self.assertEqual(plan["status"], "ready")
        meta = plan["render_request"]["meta"]
        self.assertEqual(meta["contract"], {"id": "demo", "frame_id": "f01", "prompt_hash": "h", "artist": "a"})
        from tags_machine_core.contracts import RenderRequest

        png = build_core_png_text(RenderRequest.model_validate(plan["render_request"]))
        self.assertEqual(json.loads(png["tags_machine_core"])["contract"]["frame_id"], "f01")


if __name__ == "__main__":
    unittest.main()
