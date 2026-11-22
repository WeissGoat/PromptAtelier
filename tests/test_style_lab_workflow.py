"""No paid generation: verify preparation isolation, group persistence and snapshot tests."""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tags_machine_core.contracts import GeneratedImage, GenerationResult
from tags_machine_core.style_lab.recipe import RecipeStore, block_from_text, tokens_from_text
from tags_machine_core.web import create_app
from tests.test_style_lab import write_nai_png


@pytest.fixture
def lab(tmp_path):
    design = tmp_path / "design"
    design.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(
        json.dumps(
            {
                "legacy": {"tags_machine_root": str(tmp_path), "design_root": str(design)},
                "runtime": {
                    "output_dir": str(tmp_path / "outputs"),
                    "cache_dir": str(tmp_path / "cache"),
                },
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def executor(request, options):
        calls.append(request.model_dump(mode="json"))
        output = Path(options["output_dir"]) / f"generated_{len(calls)}.png"
        # NovelAI's returned PNG omits this request-only count, as in the existing API fixture.
        params = {key: value for key, value in request.params.items() if key != "n_samples"}
        write_nai_png(output, size=(request.size.width, request.size.height), **params)
        return GenerationResult(
            backend="novelai", images=[GeneratedImage(path=output, filename=output.name)]
        )

    app = create_app(
        config_path=config, generation_executor=executor, style_lab_dir=tmp_path / "stylelab"
    )
    corpus = tmp_path / "corpus"
    write_nai_png(corpus / "origin/2026-01-01_1_one/a.png", size=(128, 192), width=64, height=96)
    write_nai_png(corpus / "origin/2026-01-01_1_one/b.png", seed=5678)
    write_nai_png(corpus / "origin/2026-01-02_2_two/c.png", seed=910)
    with TestClient(app) as client:
        opened = client.post("/api/style-lab/workspaces", json={"root": str(corpus)}).json()
        yield {
            "client": client,
            "app": app,
            "calls": calls,
            "root": corpus,
            "opened": opened,
            "base": f"/api/style-lab/workspaces/{opened['workspace']['id']}",
        }


def groups(lab):
    images = lab["opened"]["images"]
    return {
        "revision": 0,
        "groups": [
            {"id": "cg_family", "name": "清晰漫画"},
            {
                "id": "cg_main",
                "parent_id": "cg_family",
                "name": "主流",
                "reason": "跨投稿画师栈稳定",
            },
            {"id": "cg_other", "parent_id": "cg_family", "name": "变体"},
        ],
        "membership": {
            image["id"]: "cg_main" if index < 2 else "cg_other"
            for index, image in enumerate(images)
        },
    }


def prepare(lab, count=2, identifier="prepare_one"):
    client, base = lab["client"], lab["base"]
    doc = groups(lab)
    recipes = []
    for index, image in enumerate(lab["opened"]["images"][:count]):
        recipe = client.post(
            base + "/recipes", json={"image_id": image["id"], "draft": True}
        ).json()["recipe"]
        parts = [token.model_dump() for token in tokens_from_text(recipe["subject"][0]["text"])]
        recipe.update(
            id=f"recipe_{index}",
            name=f"配方{index}",
            prefix=parts[:1],
            subject=parts[1:],
            stage="edit",
            locked=True,
            source_group={"kind": "custom", "id": doc["membership"][image["id"]]},
            preparation={"status": "ready"},
        )
        recipes.append(recipe)
    payload = {
        "id": identifier,
        "custom_groups": doc,
        "recipes": recipes,
        "summary": "投稿级分析与画风划分",
    }
    response = client.post(base + "/preparations", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()


def wait(lab, plan):
    lab["app"].state.style_lab_service.job_manager.wait(plan["job_id"], 10)
    result = lab["client"].get(lab["base"] + f"/test-plans/{plan['id']}").json()
    assert result["status"] not in {"queued", "running"}, result
    return result


def test_custom_groups_stable_stats_conflicts_locks_and_rescan(lab):
    client, base = lab["client"], lab["base"]
    response = client.put(base + "/custom-groups", json=groups(lab))
    assert response.status_code == 200, response.text
    saved = response.json()
    by_id = {group["id"]: group for group in saved["groups"]}
    assert by_id["cg_family"]["post_count"] == 2
    assert by_id["cg_main"]["post_count"] == 1
    assert by_id["cg_main"]["image_count"] == 2
    assert client.put(base + "/custom-groups", json=groups(lab)).status_code == 409
    by_id["cg_main"]["name"] = "人工命名"
    by_id["cg_main"]["locked"] = True
    saved = client.put(base + "/custom-groups", json=saved).json()
    agent = copy.deepcopy(saved)
    next(group for group in agent["groups"] if group["id"] == "cg_main")["name"] = "覆盖人工"
    assert client.put(base + "/custom-groups", json={**agent, "actor": "agent"}).status_code == 409
    moved = copy.deepcopy(saved)
    moved["membership"][lab["opened"]["images"][0]["id"]] = "cg_other"
    assert client.put(base + "/custom-groups", json={**moved, "actor": "agent"}).status_code == 409
    write_nai_png(lab["root"] / "origin/new.png")
    client.post(base + "/scan", json={})
    after = client.get(base + "/custom-groups").json()
    assert after["membership"] == saved["membership"]
    assert len(after["ungrouped_image_ids"]) == 1
    assert (
        next(group for group in after["groups"] if group["id"] == "cg_main")["name"] == "人工命名"
    )
    assert lab["calls"] == []


def test_invalid_group_tree_members_and_representative_are_rejected(lab):
    client, base = lab["client"], lab["base"]
    doc = groups(lab)
    doc["groups"][0]["parent_id"] = "cg_main"
    assert client.put(base + "/custom-groups", json=doc).status_code == 400
    doc = groups(lab)
    doc["membership"]["not_in_workspace"] = "cg_main"
    assert client.put(base + "/custom-groups", json=doc).status_code == 400
    doc = groups(lab)
    doc["groups"][1]["representative_image_id"] = lab["opened"]["images"][-1]["id"]
    assert client.put(base + "/custom-groups", json=doc).status_code == 400


def test_prepare_never_generates_and_is_idempotent_and_paginated(lab):
    payload, result = prepare(lab)
    assert result["status"] == "succeeded"
    assert lab["calls"] == []
    client, base = lab["client"], lab["base"]
    again = client.post(base + "/preparations", json=payload)
    assert again.json() == result
    assert len(client.get(base + "/recipes").json()["recipes"]) == 2
    assert client.get(base + "/custom-groups").json()["revision"] == 1
    context = client.get(base + "/analysis-context?limit=1").json()
    assert context["total_posts"] == 2
    assert context["next_offset"] == 1
    summaries = client.get(base + "/recipes").json()["recipes"]
    assert all(recipe["preparation"]["status"] == "ready" for recipe in summaries)
    assert all(recipe["source_group"]["kind"] == "custom" for recipe in summaries)
    saved = client.get(base + "/recipes/recipe_0").json()["recipe"]
    service = lab["app"].state.style_lab_service
    from tags_machine_core.style_lab.recipe import Recipe

    assert (
        len(
            service._group_image_ids(
                Recipe.model_validate(saved),
                service.store.load_index(
                    lab["app"].state.style_lab_store.get(lab["opened"]["workspace"]["id"])
                ).images,
                lab["app"].state.style_lab_store.get(lab["opened"]["workspace"]["id"]),
            )
        )
        == 2
    )


def test_prepare_resumes_without_duplicating_groups_or_overwriting_recipes(lab, monkeypatch):
    original = RecipeStore.create
    failure = {"first": True}

    def interrupted(store, recipe):
        if recipe.id == "recipe_1" and failure["first"]:
            failure["first"] = False
            raise OSError("simulated interrupted write")
        return original(store, recipe)

    monkeypatch.setattr(RecipeStore, "create", interrupted)
    payload, record = prepare(lab)
    assert record["status"] == "partial"
    response = lab["client"].post(lab["base"] + "/preparations", json=payload)
    assert response.json()["status"] == "succeeded"
    assert lab["client"].get(lab["base"] + "/custom-groups").json()["revision"] == 1
    assert len(lab["client"].get(lab["base"] + "/recipes").json()["recipes"]) == 2
    assert lab["calls"] == []


def test_snapshot_plan_only_tests_selected_recipe_and_preserves_saved_content(lab):
    prepare(lab)
    client, base = lab["client"], lab["base"]
    original = client.get(base + "/recipes/recipe_0").json()["recipe"]
    variant = copy.deepcopy(original)
    variant["subject"] = [
        token.model_dump() for token in block_from_text("1girl, solo, standing", "manual")
    ]
    variant["character"]["captions"][0]["tokens"] = [
        token.model_dump() for token in block_from_text("girl, black hair", "manual")
    ]
    payload = {
        "recipe_ids": ["recipe_0"],
        "variants": [{"recipe_id": "recipe_0", "recipe": variant, "label": "站姿黑发"}],
    }
    response = client.post(base + "/test-plans", json=payload)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert lab["calls"] == []
    assert plan["estimated_count"] == 3
    result = wait(lab, client.post(base + f"/test-plans/{plan['id']}/start").json())
    assert result["status"] == "succeeded", result
    assert len(lab["calls"]) == 3
    assert client.get(base + "/recipes/recipe_0").json()["recipe"] == original
    assert all(item["recipe_id"] == "recipe_0" for item in result["items"])
    for request in lab["calls"]:
        assert request["seed"] == 1234
        assert request["size"] == {"width": 64, "height": 96}
    assert "standing" in lab["calls"][-1]["prompt"]
    assert "sitting" not in lab["calls"][-1]["prompt"]
    client.post(base + f"/test-plans/{plan['id']}/start")
    assert len(lab["calls"]) == 3
    second = client.post(base + "/test-plans", json=payload).json()
    assert second["reuse_count"] == 3
    assert (
        wait(lab, client.post(base + f"/test-plans/{second['id']}/start").json())["status"]
        == "succeeded"
    )
    assert len(lab["calls"]) == 3


def test_group_selection_expands_and_shared_source_regenerates_once(lab):
    prepare(lab)
    client, base = lab["client"], lab["base"]
    recipe = client.get(base + "/recipes/recipe_0").json()["recipe"]
    recipe.update(id="recipe_same_source", name="同源另一配方")
    assert client.post(base + "/recipes", json={"recipe": recipe}).status_code == 200
    plan = client.post(
        base + "/test-plans",
        json={
            "group_ids": ["cg_main"],
            "recipe_ids": ["recipe_0"],
            "include_materials": False,
            "continue_on_drift": True,
        },
    ).json()
    assert len(plan["recipe_ids"]) == 3
    assert sum(item["kind"] == "regenerate" for item in plan["items"]) == 2
    assert plan["estimated_count"] == 5


def test_content_change_without_version_increment_invalidates_plan(lab):
    prepare(lab, count=1)
    client, base = lab["client"], lab["base"]
    plan = client.post(
        base + "/test-plans", json={"recipe_ids": ["recipe_0"], "include_materials": False}
    ).json()
    recipe = client.get(base + "/recipes/recipe_0").json()["recipe"]
    version = recipe["version"]
    recipe["subject"] = [
        token.model_dump() for token in block_from_text("1girl, standing", "manual")
    ]
    saved = client.put(
        base + "/recipes/recipe_0", json={"recipe": recipe, "base_version": version}
    ).json()["recipe"]
    assert saved["version"] == version
    assert client.post(base + f"/test-plans/{plan['id']}/start").status_code == 409
    assert lab["calls"] == []


def test_shelf_requires_prepared_variants_and_keeps_exclusions_snapshot(lab):
    prepare(lab, count=1)
    client, base = lab["client"], lab["base"]
    shelf = {
        "materials": [
            {"role": "character", "ref": "characters/test", "name": "测试角色", "excluded": ["hat"]}
        ]
    }
    client.put("/api/style-lab/shelf", json=shelf)
    plan = client.post(base + "/test-plans", json={"recipe_ids": ["recipe_0"]}).json()
    assert plan["status"] == "awaiting_content"
    assert plan["shelf"]["materials"][0]["excluded"] == ["hat"]
    assert client.post(base + f"/test-plans/{plan['id']}/start").status_code == 400
    client.put("/api/style-lab/shelf", json={"materials": []})
    assert client.get(base + f"/test-plans/{plan['id']}").json()["shelf"] == plan["shelf"]
    assert lab["calls"] == []


def test_snapshot_cannot_relabel_version_or_change_group_and_bad_requests_are_400(lab):
    prepare(lab, count=1)
    client, base = lab["client"], lab["base"]
    recipe = client.get(base + "/recipes/recipe_0").json()["recipe"]
    recipe["version"] += 1
    response = client.post(
        base + "/test-plans",
        json={
            "recipe_ids": ["recipe_0"],
            "variants": [{"recipe_id": "recipe_0", "recipe": recipe}],
        },
    )
    assert response.status_code == 400
    assert (
        client.post(base + "/test-plans", json={"variants": {"wrong": "shape"}}).status_code == 400
    )
    assert lab["calls"] == []


def test_drift_blocks_following_tests_and_new_source_marks_recipe_stale(lab, monkeypatch):
    prepare(lab, count=1)
    client, base = lab["client"], lab["base"]
    import tags_machine_core.style_lab.service as service_module

    monkeypatch.setattr(
        service_module, "compare_with_source", lambda *args, **kwargs: {"verdict": "drift"}
    )
    plan = client.post(
        base + "/test-plans", json={"recipe_ids": ["recipe_0"], "include_materials": False}
    ).json()
    result = wait(lab, client.post(base + f"/test-plans/{plan['id']}/start").json())
    assert result["status"] == "partial"
    assert len(lab["calls"]) == 1
    assert result["items"][1]["status"] == "skipped"
    source = Path(lab["opened"]["images"][0]["path"])
    write_nai_png(source, seed=1)
    summary = client.get(base + "/recipes").json()["recipes"][0]
    assert summary["preparation"]["status"] == "stale"
