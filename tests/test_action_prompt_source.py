from pathlib import Path

import pytest
import yaml

from tags_machine_core.compose_contracts.sources import action_prompt
from tags_machine_core.composers.script import ScriptComposer
from tags_machine_core.nodes import NodeReader, validate_node_tree
from tags_machine_core.web.node_editing.action_sources import ActionSourcesAdapter
from tools.legacy_migration.sync_action_meta import sync_action_meta


def make_action(root: Path) -> Path:
    root.mkdir(exist_ok=True)
    (root / "meta.yaml").write_text(yaml.safe_dump({
        "schema": "tags-machine.action/v1", "kind": "action", "id": root.name,
        "tags": {"action": ["stale positive"], "extra": ["stale extra"]},
        "prompt": {"positive": ["stale prompt"], "negative": ["stale fragment"]},
        "negative_prompt": ["stale negative"], "character_scope": "hand_detail",
        "clothing": {"state": "clothed"}, "agent": {"summary": "keep me"},
    }), encoding="utf-8")
    (root / "tags.txt").write_text("standing, {smile, blush}\ntype,dress\n=\nuc, bad hands\n", encoding="utf-8")
    (root / "tags.compiled.txt").write_text("stale compiled\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("entry", ["", "meta.yaml", "tags.txt"])
def test_action_reads_latest_text_and_preserves_metadata(tmp_path, entry):
    root = make_action(tmp_path)
    reader = NodeReader()
    before = (root / "meta.yaml").read_bytes()
    node = reader.read(root / entry)
    assert node.tags == {"action": ["standing", "{smile, blush}"]}
    assert node.character_scope == "hand_detail"
    assert node.clothing == {"state": "clothed"}
    assert node.agent == {"summary": "keep me"}
    bundle = ScriptComposer().compose_nodes(action=node)
    assert bundle.prompt.positive == "standing, {smile, blush}"
    assert bundle.prompt.negative == "bad hands"
    assert action_prompt(node, root) == ("standing, {smile, blush}", "bad hands", "tags.txt")
    (root / "tags.txt").write_text("sitting\n", encoding="utf-8")
    updated = reader.read(root / entry)
    assert updated.positive_texts() == ["sitting"]
    assert updated.negative_prompt == []
    assert updated.negative_texts() == []
    assert (root / "meta.yaml").read_bytes() == before
    (root / "tags.txt").write_text("# deliberately empty\n", encoding="utf-8")
    empty = ScriptComposer().compose_nodes(action=reader.read(root / entry))
    assert empty.prompt.positive == ""
    assert empty.prompt.negative == ""


def test_yaml_only_and_non_action_nodes_keep_yaml_prompts(tmp_path):
    root = make_action(tmp_path)
    (root / "tags.txt").unlink()
    assert NodeReader().read(root).negative_prompt == ["stale negative"]
    (root / "tags.txt").write_text("different\n=uc, different negative\n", encoding="utf-8")
    data = yaml.safe_load((root / "meta.yaml").read_text())
    data["kind"] = "character"
    (root / "meta.yaml").write_text(yaml.safe_dump(data))
    assert NodeReader().read(root).negative_prompt == ["stale negative"]


def test_sync_creates_metadata_without_prompt_copies(tmp_path):
    (tmp_path / "tags.txt").write_text("standing\n=uc, bad hands\n", encoding="utf-8")
    sync_action_meta(tmp_path, write=True)
    meta = yaml.safe_load((tmp_path / "meta.yaml").read_text(encoding="utf-8"))
    assert "tags" not in meta and "negative_prompt" not in meta and "prompt" not in meta
    assert set(meta["legacy"]) == {"source_file"}
    assert validate_node_tree(tmp_path)["valid"]
    before = (tmp_path / "meta.yaml").read_bytes()
    (tmp_path / "tags.txt").write_text("sitting\n=uc, new negative\n", encoding="utf-8")
    sync_action_meta(tmp_path, write=True)
    assert (tmp_path / "meta.yaml").read_bytes() == before
    node = NodeReader().read(tmp_path)
    assert node.positive_texts() == ["sitting"]
    assert node.negative_prompt == ["new negative"]


def test_web_negative_edits_round_trip_through_tags_text(tmp_path):
    root = make_action(tmp_path)
    (root / "tags.txt").write_text("standing\ntype,dress\n=uc, old\nafter_uc, older\ngen_param, keep\n", encoding="utf-8")
    adapter = ActionSourcesAdapter()
    values = adapter.read_editor(root).values
    values["prompt_lines"] = ["sitting"]
    values["negative"] = ["new negative"]
    for mutation in adapter.preview_mutations(root, values):
        mutation.path.write_text(mutation.after_text, encoding="utf-8")
    assert adapter.read_editor(root).values["negative"] == ["new negative"]
    saved = (root / "tags.txt").read_text()
    assert "type,dress" in saved and "gen_param, keep" in saved
    assert "old" not in saved
    assert "new negative" not in (root / "meta.yaml").read_text()
    values["negative"] = []
    for mutation in adapter.preview_mutations(root, values):
        mutation.path.write_text(mutation.after_text, encoding="utf-8")
    assert NodeReader().read(root).negative_prompt == []


def test_raw_text_preserves_character_blocks_and_negative_directives(tmp_path):
    text = "1girl, ::character A: 2::smile, blush:: ::\nuc, bad hands\nafter_uc, blurry\n"
    (tmp_path / "tags.txt").write_text(text, encoding="utf-8")
    node = NodeReader().read(tmp_path)
    assert node.positive_texts() == [text.splitlines()[0]]
    assert node.negative_prompt == ["bad hands", "blurry"]


@pytest.mark.parametrize("key", ["uc", "after_uc", "origin_uc", "negative_prompt", "after_negative_prompt"])
@pytest.mark.parametrize("separator", ["\n=\n", "\n= ", "\n=, ", "\n"])
def test_negative_directive_aliases_and_separator_forms(tmp_path, key, separator):
    root = make_action(tmp_path)
    (root / "tags.txt").write_text(
        f"standing{separator}{key}, {{bad hands, extra fingers}}, blurry\n",
        encoding="utf-8",
    )
    node = NodeReader().read(root)
    assert node.positive_texts() == ["standing"]
    assert node.negative_prompt == ["{bad hands, extra fingers}, blurry"]
    assert node.negative_texts() == []


@pytest.mark.parametrize("negative", ["latest_negative", ""])
def test_web_preview_and_generation_submit_current_file_prompts(tmp_path, negative):
    from fastapi.testclient import TestClient
    from tags_machine_core.contracts import GenerationResult
    from tags_machine_core.web import create_app
    from tags_machine_core.web.services.job_manager import JobManager

    root = make_action(tmp_path)
    captured = []

    def executor(request, options):
        captured.append(request)
        return GenerationResult(backend="novelai")

    manager = JobManager()
    app = create_app(job_manager=manager, generation_executor=executor)
    client = TestClient(app)
    request = {
        "compose": {"nodes": [{"role": "action", "ref": str(root)}]},
        "render": {"backend": "novelai", "width": 832, "height": 1216},
    }
    preview = client.post("/api/compose-preview", json=request)
    assert preview.status_code == 200, preview.text
    assert "standing" in preview.json()["render_request"]["prompt"]
    # The ordinary Web batch carries refs, so even an edit after preview is read.
    (root / "tags.txt").write_text(f"sitting\n=\nuc, {negative}\n", encoding="utf-8")
    response = client.post("/api/generate/batch", json={
        "items": [{"compose_request": request, "generate": {}}],
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    manager.wait(job_id, timeout=5)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded", job
    assert len(captured) == 1
    assert captured[0].prompt == "1girl, sitting"  # renderer's default subject policy
    assert captured[0].negative_prompt == negative


def test_script_executor_submits_current_file_prompts(tmp_path, monkeypatch):
    from tags_machine_core.batch.executor import BatchExecutor
    from tags_machine_core.batch.models import BatchTask
    from tags_machine_core.config import AppConfig, LegacyConfig
    from tags_machine_core.contracts import GenerationResult

    root = make_action(tmp_path / "action")
    task = BatchTask(
        id="current-source", index=0, composer="script",
        nodes=[{"role": "action", "ref": str(root)}],
        render={"backend": "novelai", "width": 832, "height": 1216},
        output={"task_dir": str(tmp_path / "output")},
    )
    captured = []

    def generate(config, request, **options):
        captured.append(request)
        return GenerationResult(backend="novelai")

    monkeypatch.setattr("tags_machine_core.batch.executor.execute_render_request", generate)
    config = AppConfig(legacy=LegacyConfig(tags_machine_root=tmp_path, design_root=tmp_path))
    executor = BatchExecutor()
    for positive, negative in [("sitting", "latest_negative"), ("standing", "")]:
        (root / "tags.txt").write_text(f"{positive}\n=uc, {negative}\n", encoding="utf-8")
        result = executor.execute(task, config=config)
        assert result.status == "succeeded"
        assert captured[-1].prompt == f"1girl, {positive}"
        assert captured[-1].negative_prompt == negative


@pytest.mark.parametrize("with_meta", [True, False])
@pytest.mark.parametrize("negative", [["new_negative"], []])
def test_save_diff_and_commit_only_write_prompt_source(tmp_path, with_meta, negative):
    from fastapi.testclient import TestClient
    from tags_machine_core.web import create_app
    from tags_machine_core.web.services.node_workspace import NodeWorkspace

    root = make_action(tmp_path / "action")
    if not with_meta:
        (root / "meta.yaml").unlink()
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    client = TestClient(create_app(node_workspace=NodeWorkspace(design_root=tmp_path)))
    loaded = client.get("/api/nodes/read", params={"ref": str(root), "role": "action"}).json()
    values = loaded["editor"]["values"]
    values.update(prompt_lines=["sitting"], negative=negative)
    response = client.post("/api/nodes/save-preview", json={"ref": str(root), "role": "action", "values": values})
    assert response.status_code == 200, response.text
    preview = response.json()
    changed = [item for item in preview["files"] if item["changed"]]
    assert [item["relative"] for item in changed] == ["tags.txt"]
    assert "+sitting" in changed[0]["diff"]
    assert "-uc, bad hands" in changed[0]["diff"]
    if negative:
        assert "+uc, new_negative" in changed[0]["diff"]
    else:
        assert "uc," not in changed[0]["after_text"]
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before
    response = client.put("/api/nodes/save-commit", json={"preview_id": preview["preview_id"]})
    assert response.status_code == 200, response.text
    assert (root / "tags.txt").read_text(encoding="utf-8") == changed[0]["after_text"]
    assert response.json()["editor"]["values"]["negative"] == negative
    assert response.json()["node"]["negative_prompt"] == negative
    assert [part["text"] for part in response.json()["node"]["prompt"]["positive"]] == ["sitting"]
    if with_meta:
        assert (root / "meta.yaml").read_bytes() == before["meta.yaml"]
    else:
        assert not (root / "meta.yaml").exists()
    assert client.put("/api/nodes/save-commit", json={"preview_id": preview["preview_id"]}).status_code == 409


@pytest.mark.parametrize("external_file", ["tags.txt", "meta.yaml"])
def test_action_save_rejects_concurrent_edit_before_writing_any_file(tmp_path, external_file):
    from fastapi.testclient import TestClient
    from tags_machine_core.web import create_app
    from tags_machine_core.web.services.node_workspace import NodeWorkspace

    root = make_action(tmp_path / "action")
    client = TestClient(create_app(node_workspace=NodeWorkspace(design_root=tmp_path)))
    values = client.get("/api/nodes/read", params={"ref": str(root), "role": "action"}).json()["editor"]["values"]
    values.update(prompt_lines=["sitting"], negative=["new_negative"], name="new name")
    response = client.post("/api/nodes/save-preview", json={"ref": str(root), "role": "action", "values": values})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert {f["relative"] for f in preview["files"] if f["changed"]} == {"tags.txt", "meta.yaml"}
    external = root / external_file
    external.write_bytes(external.read_bytes() + b"\n# external edit\n")
    before_commit = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    committed = client.put("/api/nodes/save-commit", json={"preview_id": preview["preview_id"]})
    assert committed.status_code == 409
    assert committed.json()["error"]["code"] == "source_changed"
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before_commit
