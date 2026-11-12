"""Check the skill's HTTP helper and source-parameter workflow without paid generation."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

from tags_machine_core.contracts import GeneratedImage, GenerationResult
from tags_machine_core.style_lab.recipe import block_from_text, tokens_from_text
from tags_machine_core.web import create_app
from tests.test_style_lab import write_nai_png


SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/style-lab/scripts/client.py"
spec = importlib.util.spec_from_file_location("style_lab_skill_client", SCRIPT)
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)


def test_server_discovery_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROMPTATELIER_URL", raising=False)
    assert skill.server_url(None) == "http://127.0.0.1:53211/api/style-lab"
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/dev_web.json").write_text('{"backend_port": 45678}', encoding="utf-8")
    assert skill.server_url(None) == "http://127.0.0.1:45678/api/style-lab"
    monkeypatch.setenv("PROMPTATELIER_URL", "http://localhost:45679/api/")
    assert skill.server_url(None) == "http://localhost:45679/api/style-lab"
    assert skill.server_url("http://localhost:45680/api/style-lab/") == (
        "http://localhost:45680/api/style-lab"
    )


def test_writes_are_not_retried_and_conflicts_keep_details():
    client = skill.Client("http://localhost:12345")
    payload = {"error": {"code": "duplicate_request", "details": {"run_id": "previous"}}}
    response = Mock(ok=False, status_code=409)
    response.json.return_value = payload
    client.session.request = Mock(return_value=response)
    with pytest.raises(skill.ApiError) as caught:
        client.request("POST", "/workspaces/w/regenerate", body={"image_id": "i"})
    assert caught.value.status == 409
    assert caught.value.payload == payload
    assert client.session.request.call_count == 1
    client.session.request.reset_mock(side_effect=True)
    client.session.request.side_effect = requests.Timeout()
    with pytest.raises(ValueError, match="read existing runs"):
        client.request("POST", "/workspaces/w/regenerate", body={"image_id": "i"})
    assert client.session.request.call_count == 1
    client.session.close()


def test_wait_timeout_preserves_existing_run_without_submission(monkeypatch):
    client = skill.Client("http://localhost:12345")
    run = {"run": {"id": "run", "status": "running", "job_id": "job"}}
    client.request = Mock(return_value=run)
    times = iter([0, 0, 0, 1])
    monkeypatch.setattr(skill.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(skill.time, "sleep", lambda _: None)
    assert client.wait("workspace", "run", 1) == {**run, "wait_timed_out": True}
    assert client.request.call_args.args == ("GET", "/workspaces/workspace/runs/run")
    assert client.request.call_count == 1
    client.session.close()


def test_materials_resolve_current_selection_and_exact_exclusions():
    client = skill.Client("http://localhost:12345")
    card = {"role": "character", "ref": "角色/a & b", "name": "角色", "excluded": ["hat"]}
    shelf = {"materials": [card], "facets": {}}
    client.request = Mock(side_effect=[
        shelf,
        {"sections": [{"name": "appearance", "tags": ["black hair", "hat", "black hair"]}]},
    ])
    result = client.materials()
    assert result["shelf"] == shelf
    assert result["materials"][0]["tags"] == ["black hair"]
    assert result["materials"][0]["excluded"] == ["hat"]
    assert "ref=%E8%A7%92%E8%89%B2%2Fa+%26+b" in client.request.call_args.args[1]
    assert all(call.args[0] == "GET" for call in client.request.call_args_list)
    client.request = Mock(return_value={"materials": []})
    assert client.materials()["materials"] == []
    assert client.request.call_count == 1
    client.session.close()


def test_cli_reads_bom_json_and_saves_full_response(tmp_path, monkeypatch, capsys):
    body_file = tmp_path / "request.json"
    body_file.write_text(json.dumps({"name": "参考图组"}, ensure_ascii=False), encoding="utf-8-sig")
    output = tmp_path / "nested/response.json"
    fake = Mock()
    fake.session = Mock()
    fake.session.__enter__ = Mock()
    fake.session.__exit__ = Mock()
    fake.request.return_value = {"workspace": {"id": "w", "name": "参考图组"}}
    monkeypatch.setattr(skill, "Client", lambda server: fake)
    assert skill.main([
        "api", "POST", "/workspaces", "--body-file", str(body_file), "--output", str(output)
    ]) == 0
    fake.request.assert_called_once_with("POST", "/workspaces", body={"name": "参考图组"})
    assert json.loads(output.read_text(encoding="utf-8")) == fake.request.return_value
    assert json.loads(capsys.readouterr().out)["output"] == str(output.resolve())


def test_full_workflow_keeps_source_seed_generation_size_and_restores_baseline(tmp_path):
    design = tmp_path / "design"
    design.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(json.dumps({
        "legacy": {"tags_machine_root": str(tmp_path), "design_root": str(design)},
        "runtime": {"output_dir": str(tmp_path / "outputs"), "cache_dir": str(tmp_path / "cache")},
    }), encoding="utf-8")
    captured = []

    def executor(request, options):
        captured.append(request.model_dump(mode="json"))
        output = Path(options["output_dir"]) / f"gen_{len(captured)}.png"
        write_nai_png(output, size=(request.size.width, request.size.height), **request.params)
        return GenerationResult(backend="novelai", images=[GeneratedImage(path=output, filename=output.name)])

    app = create_app(
        config_path=config, generation_executor=executor, style_lab_dir=tmp_path / "stylelab"
    )
    source = write_nai_png(tmp_path / "corpus/origin/source.png", size=(128, 192), width=64, height=96)
    original_bytes = source.read_bytes()
    client = skill.Client("http://testserver")
    client.session.close()
    with TestClient(app) as session:
        class SessionAdapter:
            def request(self, method, url, *, timeout, **kwargs):
                # TestClient returns httpx responses; the helper uses requests.
                response = session.request(method, url, **kwargs)
                result = requests.Response()
                result.status_code = response.status_code
                result._content = response.content
                return result

        client.session = SessionAdapter()
        opened = client.request("POST", "/workspaces", body={"root": str(source.parent.parent)})
        workspace = opened["workspace"]["id"]
        image = opened["images"][0]
        assert (image["width"], image["height"]) == (128, 192)
        assert (image["gen_width"], image["gen_height"]) == (64, 96)
        base = f"/workspaces/{workspace}"
        # A second files workspace can coexist; no source copy is needed.
        other = client.request("POST", "/workspaces", body={"files": [str(source)], "name": "散图"})
        assert other["workspace"]["id"] != workspace
        recipe = client.request("POST", base + "/recipes", body={"image_id": image["id"]})["recipe"]
        parts = [token.model_dump() for token in tokens_from_text(recipe["subject"][0]["text"])]
        recipe.update(prefix=parts[:1], subject=parts[1:], stage="edit", locked=True)
        recipe_path = base + f"/recipes/{recipe['id']}"

        def save(value):
            return client.request("PUT", recipe_path, body={
                "recipe": value, "base_version": value["version"]
            })["recipe"]

        baseline = save(recipe)
        preview = client.request("POST", base + "/recipes/preview", body={"recipe": baseline})["preview"]
        assert preview["char_captions"] == ["girl, silver hair"]
        settings = {"count": 1, "seed_mode": "source", "size_mode": "source", "overrides": {}}

        def generate(path, body):
            run = client.request("POST", path, body=body)["run"]
            result = client.wait(workspace, run["id"], 10)["run"]
            assert result["status"] == "succeeded", result
            assert Path(result["items"][0]["image_path"]).is_file()
            return result

        generate(base + "/regenerate", {"image_id": image["id"], "settings": settings})
        generate(recipe_path + "/generate", {"settings": settings})
        with pytest.raises(skill.ApiError) as duplicate:
            client.request("POST", recipe_path + "/generate", body={"settings": settings})
        assert duplicate.value.payload["error"]["code"] == "duplicate_request"

        variant = copy.deepcopy(baseline)
        variant["name"] += " · 测试角色和动作"
        variant["subject"] = [t.model_dump() for t in block_from_text("1girl, solo, standing", "manual")]
        variant["character"]["captions"][0]["tokens"] = [
            t.model_dump() for t in block_from_text("girl, black hair", "character:test")
        ]
        saved_variant = save(variant)
        assert saved_variant["version"] == baseline["version"]
        generate(recipe_path + "/generate", {"settings": settings})
        # Same version still requires the new updated_at, protecting user edits.
        with pytest.raises(skill.ApiError) as stale:
            save(baseline)
        assert stale.value.payload["error"]["code"] == "recipe_conflict"
        restored = copy.deepcopy(baseline)
        restored["updated_at"] = saved_variant["updated_at"]
        final = save(restored)
        assert final["version"] == baseline["version"]
        assert final["subject"] == baseline["subject"]
        assert final["character"] == baseline["character"]
        assert final["name"] == baseline["name"]
        assert len(captured) == 3
        for request in captured:
            assert request["seed"] == image["seed"]
            assert request["size"] == {"width": 64, "height": 96}
        assert "standing" in captured[-1]["prompt"]
        assert "sitting" not in captured[-1]["prompt"]
        captions = captured[-1]["params"]["v4_prompt"]["caption"]["char_captions"]
        assert captions[0]["char_caption"] == "girl, black hair"
    assert source.read_bytes() == original_bytes
