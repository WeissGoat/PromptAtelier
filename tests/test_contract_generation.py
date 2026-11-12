from __future__ import annotations

import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from tags_machine_core.cli import main
from tags_machine_core.compose_contracts.generation import build_generation_batch
from tags_machine_core.compose_contracts.generation_client import GenerationClient
from tags_machine_core.contracts import GenerationResult
from tags_machine_core.execution import save_generated_images
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.services.generation_reuse import GenerationReuse
from tags_machine_core.web import create_app
from tests.test_compose_contracts import make_design_root


@pytest.fixture
def setup(tmp_path):
    design = make_design_root(tmp_path)
    config = tmp_path / "config.yaml"
    output = tmp_path / "outputs"
    config.write_text(
        yaml.safe_dump(
            {
                "legacy": {"tags_machine_root": str(tmp_path), "design_root": str(design)},
                "runtime": {"output_dir": str(output), "cache_dir": str(tmp_path / "cache")},
            }
        ),
        encoding="utf-8",
    )
    generated = []

    def executor(request, options):
        generated.append(request)
        data = io.BytesIO()
        Image.new("RGB", (16, 16), "white").save(data, format="PNG")
        images = save_generated_images(
            [
                SimpleNamespace(filename="test.png", content=data.getvalue())
                for _ in range(request.params.get("n_samples", 1))
            ],
            output_dir=Path(options["output_dir"]),
            request=request,
            default_format="png",
        )
        return GenerationResult(backend=request.backend, images=images)

    app = create_app(
        config_path=config, generation_executor=executor, style_lab_dir=tmp_path / "stylelab"
    )
    artist = NodeDocument(
        kind="artist",
        id="test-style",
        name="Test Style",
        path=tmp_path / "artist",
        renderers={
            "novelai": {"model": "nai-diffusion-4-5-full", "params": {"steps": 10}},
        },
    )
    app.state.node_workspace.read_artist_node = lambda ref: artist
    app.state.generation_api.artist_loader = lambda ref: artist
    service = app.state.contract_service
    detail = service.create({"action_group": "stn_20260101_0001", "characters": ["series/char_a"]})
    detail = service.import_frames(
        detail["id"],
        """## f01 Standing
source: #1
characters: c1
size: portrait

```positive
char_a, black_hair, 1girl, standing
```

## f02 Sitting
source: #2
characters: c1

```positive
char_a, black_hair, 1girl, sitting
```
""",
    )
    return SimpleNamespace(
        app=app,
        client=TestClient(app),
        service=service,
        detail=detail,
        artist=artist,
        generated=generated,
        output=output,
    )


def submit(setup, contract_id=None, **payload):
    response = setup.client.post(
        f"/api/contracts/{contract_id or setup.detail['id']}/generate",
        json={
            "artist": "test-style",
            "frames": "f01",
            "seed": 42,
            **payload,
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    setup.app.state.job_manager.wait(job_id, timeout=5)
    job = setup.app.state.job_manager.get(job_id)
    assert job.status == "succeeded", job.error
    return job.result["items"][0]


def test_requires_artist_and_preflight_does_not_generate(setup):
    url = f"/api/contracts/{setup.detail['id']}/generate"
    assert setup.client.post(url, json={}).status_code == 400
    preview = setup.client.post(
        url, json={"artist": "test-style", "frames": "f01", "dry_run": True}
    ).json()
    assert preview["total"] == 1
    assert preview["frames"][0]["render_request"]["params"]["steps"] == 10
    assert preview["frames"][0]["token_usage"]["limit"] == 512
    assert setup.generated == []
    assert setup.app.state.job_manager.list(name="generate-batch") == []


def test_cross_contract_reuse_is_visible_in_results_and_keeps_original_png(setup):
    first = submit(setup)
    clone = setup.service.clone(setup.detail["id"], with_frames=True)
    second = submit(setup, clone["id"])
    assert len(setup.generated) == 1
    assert second["cache_hit"] is True
    assert second["images"] == first["images"]
    results = setup.service.results(clone["id"])["frames"]["f01"]
    assert results[0]["current"] and results[0]["reused"]
    assert results[0]["path"] == first["images"][0]["path"]
    assert setup.service._png_contract_info(Path(results[0]["path"]))["id"] == setup.detail["id"]
    report = setup.client.get(f"/api/contracts/{clone['id']}/results")
    assert report.status_code == 200
    assert report.json()["frames"]["f01"][0]["current"]


def test_cache_survives_restart_and_force_generates_again(setup):
    submit(setup)
    setup.app.state.generation_reuse = GenerationReuse(setup.output)
    assert submit(setup)["cache_hit"]
    assert not submit(setup, skip_duplicates=False)["cache_hit"]
    assert len(setup.generated) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"seed": 43},
        {"negative": "lowres"},
        {"nt": 2},
        {"size": "square"},
        {"character_prompts": "off"},
    ],
)
def test_effective_parameter_changes_must_generate(setup, change):
    submit(setup)
    assert not submit(setup, **change)["cache_hit"]
    assert len(setup.generated) == 2


def test_style_parameter_change_invalidates_cache(setup):
    submit(setup)
    setup.artist.renderers["novelai"]["params"]["steps"] = 12
    assert not submit(setup)["cache_hit"]
    assert len(setup.generated) == 2


def test_failed_or_incomplete_generation_never_becomes_a_cache_hit(setup):
    executor = setup.app.state.generation_api.generation_executor
    for failing in (True, False):

        def bad(request, options, failing=failing):
            if failing:
                raise RuntimeError("temporary backend failure")
            return GenerationResult(backend=request.backend)

        setup.app.state.generation_api.generation_executor = bad
        response = setup.client.post(
            f"/api/contracts/{setup.detail['id']}/generate",
            json={
                "artist": "test-style",
                "frames": "f01",
                "seed": 42,
            },
        )
        setup.app.state.job_manager.wait(response.json()["id"], timeout=5)
        assert not list((setup.output / ".web" / "generation_cache").glob("*.json"))
    setup.app.state.generation_api.generation_executor = executor
    assert not submit(setup)["cache_hit"]
    assert submit(setup)["cache_hit"]


def test_comfyui_workflow_and_target_are_part_of_reuse_identity(setup):
    from tests.test_multi_backend_renderers import _artist_node

    setup.artist.renderers = {"comfyui": _artist_node().renderers["comfyui"]}
    first = submit(setup, seed=None)
    assert first["cache_hit"] is False
    assert submit(setup, seed=None)["cache_hit"]
    assert not submit(setup, seed=None, comfyui_target="another-server")["cache_hit"]
    setup.artist.renderers["comfyui"]["workflow_json"]["3"]["inputs"]["steps"] = 35
    assert not submit(setup, seed=None)["cache_hit"]
    assert len(setup.generated) == 3


def test_random_settings_reuse_and_missing_images_regenerate(setup):
    first = submit(setup, frames="f02", seed=None)
    second = submit(setup, frames="f02", seed=-1)
    assert second["cache_hit"]
    Path(first["images"][0]["path"]).unlink()
    assert not submit(setup, frames="f02", seed=None)["cache_hit"]
    assert len(setup.generated) == 2


def test_same_parameters_in_parallel_pay_for_one_generation(setup):
    barrier = threading.Barrier(2)

    def run():
        barrier.wait(timeout=5)
        return submit(setup)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert len(setup.generated) == 1
    assert sum(bool(r["cache_hit"]) for r in results) == 1


def test_web_batch_uses_same_cache_as_agent_and_can_force(setup):
    first = submit(setup)
    raw = build_generation_batch(
        setup.detail, setup.artist, {"artist": "test-style", "frames": "f01", "seed": 42}
    )
    response = setup.client.post("/api/generate/batch", json=raw)
    assert response.status_code == 200
    job_id = response.json()["id"]
    setup.app.state.job_manager.wait(job_id, timeout=5)
    item = setup.app.state.job_manager.get(job_id).result["items"][0]
    assert item["cache_hit"] and item["images"] == first["images"]


def test_preview_rejects_invalid_frame_or_parameters_before_queueing(setup):
    url = f"/api/contracts/{setup.detail['id']}/generate"
    for values in (
        {"frames": "f99"},
        {"nt": 0},
        {"size": "banana"},
        {"width": 65},
        {"nt": None},
        {"frames": []},
    ):
        assert setup.client.post(url, json={"artist": "test-style", **values}).status_code == 400
    assert not setup.generated


def test_final_length_gate_is_checked_before_generation(setup, monkeypatch):
    monkeypatch.setattr(
        "tags_machine_core.web.routes.contracts.render_request_token_usage",
        lambda _: {"over": True, "total": 600, "limit": 512},
    )
    url = f"/api/contracts/{setup.detail['id']}/generate"
    payload = {"artist": "test-style", "frames": "f01"}
    assert setup.client.post(url, json=payload).status_code == 400
    assert setup.client.post(url, json={**payload, "dry_run": True}).json()["frames"][0][
        "token_usage"
    ]["over"]
    assert not setup.generated
    submit(setup, allow_over_limit=True)


def test_character_blocks_merge_only_for_backends_without_character_prompts(setup):
    detail = deepcopy(setup.detail)
    frame = detail["frames"][0]
    frame["character_prompts"] = [
        {"id": "c1", "positive": "girl, char_a", "negative": "red_glasses"}
    ]
    params = {"artist": "test-style", "frames": "f01", "negative": "lowres"}
    novelai = build_generation_batch(detail, setup.artist, params)["items"][0]["compose_request"]
    assert (
        novelai["render"]["params"]["character_prompts"]["captions"][0]["positive"]
        == "girl, char_a"
    )
    comfy = setup.artist.model_copy(update={"renderers": {"comfyui": {}}})
    merged = build_generation_batch(detail, comfy, params)["items"][0]["compose_request"]
    assert merged["compose"]["agent_result"]["positive"].endswith("girl, char_a")
    assert merged["compose"]["agent_result"]["negative"] == "red_glasses, lowres"
    assert "character_prompts" not in merged["render"]["params"]


def test_cli_generates_and_returns_image_paths_without_browser(setup, monkeypatch):
    def request(client, method, path, **kwargs):
        response = setup.client.request(method, "/api" + path, **kwargs)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(GenerationClient, "request", request)
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(
            [
                "contract",
                "generate",
                setup.detail["id"],
                "--artist",
                "test-style",
                "--frames",
                "f01",
                "--wait",
            ]
        )
    result = json.loads(out.getvalue())
    assert code == 0 and result["status"] == "succeeded"
    assert Path(result["result"]["items"][0]["images"][0]["path"]).is_file()
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(["contract", "job", result["id"]])
    assert code == 0
    assert json.loads(out.getvalue())["id"] == result["id"]


def test_cli_timeout_and_partial_failure_have_nonzero_exit_codes(monkeypatch):
    monkeypatch.setattr(
        GenerationClient,
        "job",
        lambda *a, **kw: {
            "status": "succeeded",
            "result": {"counts": {"failed": 1}},
        },
    )
    with redirect_stdout(io.StringIO()):
        assert main(["contract", "job", "demo"]) == 1
    monkeypatch.setattr(
        GenerationClient, "job", lambda *a, **kw: {"status": "running", "wait_timed_out": True}
    )
    with redirect_stdout(io.StringIO()):
        assert main(["contract", "job", "demo", "--wait", "--timeout", "0"]) == 1
