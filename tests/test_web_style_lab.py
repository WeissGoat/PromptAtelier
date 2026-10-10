import json
import tempfile
import time
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from tags_machine_core.config import LLMConfig
from tags_machine_core.contracts import GeneratedImage, GenerationResult
from tags_machine_core.llm import LLMCache, LLMClient
from tags_machine_core.web import create_app

from tags_machine_core.style_lab.recipe import character_prompts_param
from tests.test_style_lab import write_nai_png


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _TranslateSession:
    def __init__(self):
        self.calls = 0

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        tags = __import__("json").loads(json["messages"][1]["content"])
        if "分类" in json["messages"][0]["content"]:
            results = {tag: "artist" if tag.startswith("foo") else "appearance" for tag in tags}
        else:
            results = {tag: f"译:{tag}" for tag in tags}
        content = __import__("json").dumps({"results": results}, ensure_ascii=False)
        return _Response({"data": {"choices": [{"message": {"content": content}}]}})


def _fake_executor(request, options):
    out_dir = Path(options["output_dir"])
    out = out_dir / f"gen_{request.seed}.png"
    write_nai_png(out, **{k: v for k, v in request.params.items() if k != "n_samples"})
    return GenerationResult(backend="novelai", images=[GeneratedImage(path=out, filename=out.name)])


class WebStyleLabTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        design = self.tmp / "design"
        design.mkdir()
        config = self.tmp / "config.yaml"
        config.write_text(
            json.dumps(
                {
                    "legacy": {"tags_machine_root": str(self.tmp), "design_root": str(design)},
                    "runtime": {"output_dir": str(self.tmp / "outputs"), "cache_dir": str(self.tmp / "cache")},
                }
            ),
            encoding="utf-8",
        )
        self.cache = LLMCache(self.tmp / "llm.sqlite")
        self.session = _TranslateSession()
        llm = LLMClient(LLMConfig(base_url="https://llm.test/v1", api_key="sk"), session=self.session, cache=self.cache)
        self.app = create_app(
            config_path=config,
            generation_executor=_fake_executor,
            llm_client=llm,
            style_lab_dir=self.tmp / "stylelab",
        )
        self.client = TestClient(self.app)
        self.corpus = self.tmp / "20260717" / "105845157"
        write_nai_png(self.corpus / "origin" / "2026-01-11_1_a" / "1_p0.png")
        write_nai_png(self.corpus / "origin" / "2026-01-12_2_b" / "2_p0.png", request_type="NativeInfillingRequest")

    def tearDown(self):
        self.cache.close()
        self.temp_dir.cleanup()

    def _open(self):
        response = self.client.post("/api/style-lab/workspaces", json={"root": str(self.corpus)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _wait_run(self, workspace_id, run_id):
        deadline = time.time() + 10
        while True:
            run = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/runs/{run_id}").json()["run"]
            if run["status"] not in {"queued", "running"} or time.time() > deadline:
                return run
            time.sleep(0.05)

    def test_open_workspace_lists_images_and_serves_files(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        self.assertEqual(data["scan"]["read"], 2)
        self.assertEqual(len(data["images"]), 2)
        image = data["images"][0]

        listed = self.client.get("/api/style-lab/workspaces").json()["workspaces"]
        self.assertEqual([item["id"] for item in listed], [workspace_id])

        detail = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/images/{image['id']}").json()
        self.assertEqual(detail["raw_parameters"]["seed"], 1234)
        self.assertIn("Comment", detail["png_text_keys"])

        file_response = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/file?image_id={image['id']}")
        self.assertEqual(file_response.status_code, 200)
        thumb = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/file?image_id={image['id']}&size=160")
        self.assertEqual(thumb.headers["content-type"], "image/webp")

        outside = write_nai_png(self.tmp / "elsewhere.png")
        forbidden = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/file", params={"path": str(outside)})
        self.assertEqual(forbidden.status_code, 403)

    def test_regenerate_creates_run_and_compares(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        image_id = data["images"][0]["id"]
        response = self.client.post(
            f"/api/style-lab/workspaces/{workspace_id}/regenerate",
            json={"image_id": image_id, "settings": {"count": 1}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        run_id = response.json()["run"]["id"]

        run = self._wait_run(workspace_id, run_id)
        self.assertEqual(run["status"], "succeeded", run)
        item = run["items"][0]
        self.assertEqual(item["compare"]["verdict"], "match")
        generated = self.client.get(
            f"/api/style-lab/workspaces/{workspace_id}/file", params={"path": item["image_path"], "size": 160}
        )
        self.assertEqual(generated.status_code, 200)

        runs = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/runs?image_id={image_id}").json()["runs"]
        self.assertEqual([r["id"] for r in runs], [run_id])

    def test_regenerate_rejects_bad_settings_and_warns_for_inpaint(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        bad = self.client.post(
            f"/api/style-lab/workspaces/{workspace_id}/regenerate",
            json={"image_id": data["images"][0]["id"], "settings": {"seed_mode": "fixed"}},
        )
        self.assertEqual(bad.status_code, 400)
        inpaint = next(img for img in data["images"] if "inpaint" in img["flags"])
        response = self.client.post(
            f"/api/style-lab/workspaces/{workspace_id}/regenerate",
            json={"image_id": inpaint["id"], "settings": {}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["run"]["warnings"])
        self._wait_run(workspace_id, response.json()["run"]["id"])

    def test_translate_and_llm_status(self):
        status = self.client.get("/api/style-lab/llm/status").json()
        self.assertTrue(status["available"])
        self.assertEqual(status["models"]["text"], "deepseek-4.1-flash")
        response = self.client.post("/api/style-lab/translate", json={"texts": ["{{thin lines}}", "solo"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["translations"], {"{{thin lines}}": "译:thin lines", "solo": "译:solo"}
        )
        bad = self.client.post("/api/style-lab/translate", json={"texts": "solo"})
        self.assertEqual(bad.status_code, 400)

    def test_open_workspace_analyzes_prompts_and_groups(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        job_id = data["analysis_job_id"]
        self.assertTrue(job_id)
        self.app.state.job_manager.wait(job_id, timeout=10)
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(job["status"], "succeeded", job)
        calls = self.session.calls
        response = self.client.post("/api/style-lab/translate", json={"texts": ["girl", "silver hair", "lowres"]})
        self.assertEqual(response.json()["translations"]["silver hair"], "译:silver hair")
        self.assertEqual(self.session.calls, calls)

        analysis = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/analysis").json()
        self.assertEqual(analysis["categories"]["foo"], "artist")
        self.assertEqual(analysis["categories"]["1girl"], "count")
        self.assertEqual(analysis["groups"][0]["name"], "foo")
        self.assertEqual(analysis["groups"][0]["post_count"], 2)
        self.assertEqual(self.session.calls, calls)

    def test_recipe_create_preview_save_and_generate(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        image_id = next(img["id"] for img in data["images"] if not img["flags"])
        base = f"/api/style-lab/workspaces/{workspace_id}/recipes"
        recipe = self.client.post(base, json={"image_id": image_id, "name": "测试配方"}).json()["recipe"]
        self.assertEqual(recipe["stage"], "split")

        # 划分：artist:foo 作前缀，最后一个 token 作后缀，开启角色提示词。
        recipe["prefix"], recipe["subject"], recipe["suffix"] = (
            recipe["subject"][:1],
            recipe["subject"][1:-1],
            recipe["subject"][-1:],
        )
        recipe["stage"], recipe["locked"] = "edit", True
        preview = self.client.post(f"{base}/preview", json={"recipe": recipe})
        self.assertEqual(preview.status_code, 200, preview.text)
        preview = preview.json()["preview"]
        self.assertTrue(preview["prompt"].startswith("artist:foo"))
        # legacy 画风的拼接格式：逗号不带空格、末尾带逗号，和导出后正式出图一致。
        self.assertEqual(preview["prompt"], "artist:foo,1girl,solo,sitting,")
        self.assertEqual(preview["char_captions"], ["girl, silver hair"])
        self.assertEqual(preview["character_prompts"]["mode"], "explicit")

        saved = self.client.put(f"{base}/{recipe['id']}", json={"recipe": recipe, "base_version": 1})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["recipe"]["version"], 2)
        conflict = self.client.put(f"{base}/{recipe['id']}", json={"recipe": recipe, "base_version": 1})
        self.assertEqual(conflict.status_code, 409)

        listed = self.client.get(base).json()["recipes"]
        self.assertEqual([item["name"] for item in listed], ["测试配方"])
        detail = self.client.get(f"{base}/{recipe['id']}").json()
        self.assertEqual([item["version"] for item in detail["history"]], [1])

        run = self.client.post(f"{base}/{recipe['id']}/generate", json={"settings": {"count": 1}})
        self.assertEqual(run.status_code, 200, run.text)
        run = self._wait_run(workspace_id, run.json()["run"]["id"])
        self.assertEqual(run["status"], "succeeded", run)
        self.assertEqual(run["kind"], "recipe")
        self.assertEqual(run["recipe"]["version"], 2)
        self.assertEqual(run["items"][0]["compare"]["verdict"], "reference")

    def test_files_workspace_upload(self):
        created = self.client.post("/api/style-lab/workspaces", json={"files": [], "name": "拖入"}).json()
        workspace_id = created["workspace"]["id"]
        png = write_nai_png(self.tmp / "upload_src.png").read_bytes()
        response = self.client.post(
            f"/api/style-lab/workspaces/{workspace_id}/upload",
            files=[("files", ("drop.png", png, "image/png")), ("files", ("notes.txt", b"x", "text/plain"))],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["uploaded"], 1)
        self.assertEqual(len(response.json()["images"]), 1)

    def _locked_recipe(self, workspace_id, image_id):
        base = f"/api/style-lab/workspaces/{workspace_id}/recipes"
        recipe = self.client.post(base, json={"image_id": image_id, "name": "导出测试"}).json()["recipe"]
        recipe["prefix"], recipe["subject"], recipe["suffix"] = (
            recipe["subject"][:1],
            recipe["subject"][1:-1],
            recipe["subject"][-1:],
        )
        recipe["stage"], recipe["locked"] = "edit", True
        recipe["character"]["enabled"] = True
        saved = self.client.put(f"{base}/{recipe['id']}", json={"recipe": recipe, "base_version": 1})
        self.assertEqual(saved.status_code, 200, saved.text)
        return base, saved.json()["recipe"]

    def test_export_artist_then_regression_and_matrix(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        image_id = next(img["id"] for img in data["images"] if not img["flags"])
        base, recipe = self._locked_recipe(workspace_id, image_id)
        url = f"{base}/{recipe['id']}"

        defaults = self.client.get(f"{url}/exports").json()
        self.assertEqual(defaults["author"], "105845157")
        self.assertEqual(defaults["exports"], [])

        bad = self.client.post(f"{url}/export/preview", json={"name": "带 空格", "author": "105845157"})
        self.assertEqual(bad.status_code, 400)
        preview = self.client.post(f"{url}/export/preview", json={"name": "Foo_Style", "author": "105845157"})
        self.assertEqual(preview.status_code, 200, preview.text)
        preview = preview.json()["preview"]
        self.assertEqual(preview["folder"], "105845157_Foo_Style")
        self.assertTrue(preview["roundtrip_ok"])
        self.assertEqual(preview["tags_txt"].splitlines()[:3], ["artist:foo", ",", "sitting"])

        exported = self.client.post(
            f"{url}/export", json={"name": "Foo_Style", "author": "105845157", "expected_folder": preview["folder"]}
        )
        self.assertEqual(exported.status_code, 200, exported.text)
        folder = exported.json()["export"]["folder"]
        self.assertTrue((self.tmp / "design" / "画风" / folder / "tags.txt").is_file())
        listed = self.client.get(f"{url}/exports").json()
        self.assertEqual([item["folder"] for item in listed["exports"]], [folder])
        self.assertTrue(listed["exports"][0]["exists"])
        stale = self.client.post(f"{url}/export", json={"name": "Foo_Style", "author": "105845157", "expected_folder": folder})
        self.assertEqual(stale.status_code, 409)

        # 导出后按名字读回的 artist，和配方本身拼出的请求完全一样。
        service = self.app.state.style_lab_service
        info = self.app.state.style_lab_store.get(workspace_id)
        recipe_obj = service.recipes(info).get(recipe["id"])
        from_recipe = service.recipe_render_request(info, recipe_obj, seed=5)
        from_disk = service._plan(
            {
                "compose": {"prompt": "1girl, solo", "negative": ""},
                "render": {
                    "backend": "novelai",
                    "artist": folder,
                    "width": from_recipe["size"]["width"],
                    "height": from_recipe["size"]["height"],
                    "seed": 5,
                    "params": {
                        "size": "custom",
                        "n_samples": 1,
                        "character_prompts": character_prompts_param(recipe_obj),
                    },
                },
            }
        )
        for key in ("prompt", "negative_prompt", "model", "size"):
            self.assertEqual(from_disk[key], from_recipe[key], key)
        self.assertEqual(from_disk["params"], from_recipe["params"])

        regression = self.client.post(
            f"{url}/artist-test", json={"settings": {"kind": "regression", "artist": folder}}
        )
        self.assertEqual(regression.status_code, 200, regression.text)
        run = self._wait_run(workspace_id, regression.json()["run"]["id"])
        self.assertEqual(run["status"], "succeeded", run)
        self.assertEqual(run["kind"], "regression")
        self.assertEqual(len(run["items"]), 1)  # 另一张是局部重绘，不参与
        item = run["items"][0]
        self.assertEqual(item["seed"], 1234)
        self.assertEqual(item["subject"], "1girl, solo")
        self.assertEqual(item["removed"], ["artist:foo", "sitting"])
        self.assertEqual(item["compare"]["verdict"], "reference")

        character = self.tmp / "design" / "角色" / "homura"
        character.mkdir(parents=True)
        (character / "meta.yaml").write_text(
            "schema: tags-machine.character/v1\nkind: character\nid: homura\ntags:\n  character:\n    - akemi homura\n",
            encoding="utf-8",
        )
        matrix = self.client.post(
            f"{url}/artist-test",
            json={"settings": {"kind": "matrix", "artist": folder, "characters": [str(character)], "seed_mode": "fixed", "seed": 9}},
        )
        self.assertEqual(matrix.status_code, 200, matrix.text)
        run = self._wait_run(workspace_id, matrix.json()["run"]["id"])
        self.assertEqual(run["status"], "succeeded", run)
        self.assertEqual(run["items"][0]["character"], str(character))
        self.assertNotIn("compare", run["items"][0])

        runs = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/runs", params={"recipe_id": recipe["id"]}).json()
        self.assertEqual(sorted(item["kind"] for item in runs["runs"]), ["matrix", "regression"])

        missing = self.client.post(f"{url}/artist-test", json={"settings": {"kind": "regression", "artist": "nope"}})
        self.assertEqual(missing.status_code, 400)
