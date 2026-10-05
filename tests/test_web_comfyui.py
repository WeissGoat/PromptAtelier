from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.config import ComfyUIConfig
from tags_machine_core.contracts import RenderRequest
from tags_machine_core.web import create_app
from tags_machine_core.web.app import _default_generation_executor
from tags_machine_core.web.services.comfyui_targets import ComfyUITargetService
from tags_machine_core.web.services.node_workspace import NodeWorkspace


def _comfyui_artist(root: Path) -> Path:
    node_dir = root / "design" / "画风" / "comfyui" / "cunyfunky"
    (node_dir / "workflows").mkdir(parents=True)
    (node_dir / "workflows" / "api.json").write_text(
        json.dumps({"1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}),
        encoding="utf-8",
    )
    (node_dir / "node.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "tags-machine.artist/v1",
                "kind": "artist",
                "id": "cunyfunky",
                "tags": {"artist": ["cunyfunky"]},
                "renderers": {"comfyui": {"workflow": "cunyfunky", "workflow_path": "workflows/api.json"}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return node_dir


def _legacy_artist(root: Path) -> Path:
    node_dir = root / "design" / "画风" / "legacy_style"
    node_dir.mkdir(parents=True)
    (node_dir / "tags.txt").write_text("artist:legacy_style\n", encoding="utf-8")
    return node_dir


def _targets_config() -> ComfyUIConfig:
    return ComfyUIConfig.model_validate(
        {
            "default_target": "local",
            "targets": {
                "local": {"label": "本机 aki"},
                "modal": {
                    "label": "Modal 云端",
                    "base_url": "https://ws--tm-comfyui-api.modal.run",
                    "status_probe": {
                        "type": "modal",
                        "app": "tm-comfyui",
                        "function": "api",
                        "idle_shutdown_seconds": 180,
                    },
                },
            },
        }
    )


class WebComfyUIArtistTest(TestCase):
    def test_artist_list_reports_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _comfyui_artist(root)
            _legacy_artist(root)

            nodes, _ = NodeWorkspace(design_root=root / "design").list_nodes_page("artist")

        backends = {node["name"]: node["backends"] for node in nodes}
        self.assertEqual(backends, {"cunyfunky": ["comfyui"], "legacy_style": ["novelai"]})

    def test_read_node_serves_structured_artist_without_form_editor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comfy_dir = _comfyui_artist(root)

            response = NodeWorkspace(design_root=root / "design").read_node(str(comfy_dir), role="artist")

        self.assertIsNone(response["editor"])
        self.assertIn("comfyui", response["node"]["renderers"])
        self.assertEqual(Path(response["node"]["path"]).resolve(), comfy_dir.resolve())

    def test_artist_loader_reads_structured_node_with_its_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comfy_dir = _comfyui_artist(root)
            _legacy_artist(root)
            workspace = NodeWorkspace(design_root=root / "design")

            comfy = workspace.read_artist_node(str(comfy_dir))
            legacy = workspace.read_artist_node("legacy_style")

        self.assertIn("comfyui", comfy.renderers)
        self.assertEqual(comfy.path.resolve(), comfy_dir.resolve())
        self.assertIn("novelai", legacy.renderers)


class ComfyUITargetServiceTest(TestCase):
    def test_describes_targets_with_probe_status_and_shutdown_estimate(self):
        now = [1000.0]
        probes: list[str] = []

        def probe(target, headers=None):
            probes.append(target.name)
            return {"state": "running"} if target.name == "modal" else {"state": "offline"}

        service = ComfyUITargetService(_targets_config(), probe=probe, clock=lambda: now[0])
        with service.track("modal"):
            during = {item["name"]: item for item in service.describe()["targets"]}
        now[0] = 1060.0
        after = service.describe()

        self.assertEqual(during["modal"]["active_jobs"], 1)
        self.assertNotIn("shutdown_in_seconds", during["modal"]["status"])
        targets = {item["name"]: item for item in after["targets"]}
        self.assertEqual(after["default_target"], "local")
        self.assertEqual(targets["local"]["location"], "local")
        self.assertEqual(targets["local"]["label"], "本机 aki")
        self.assertEqual(targets["modal"]["location"], "cloud")
        self.assertEqual(targets["modal"]["status"]["shutdown_in_seconds"], 120)

    def test_status_is_cached_between_polls(self):
        calls: list[str] = []
        service = ComfyUITargetService(
            _targets_config(),
            probe=lambda target, headers=None: calls.append(target.name) or {"state": "stopped"},
            clock=lambda: 5.0,
        )

        service.describe()
        service.describe()

        self.assertEqual(sorted(calls), ["local", "modal"])

    def test_route_lists_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "local.yaml"
            config.write_text(
                yaml.safe_dump(
                    {
                        "legacy": {"tags_machine_root": str(root), "design_root": str(root / "design")},
                        "comfyui": _targets_config().model_dump(exclude_defaults=True),
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            app = create_app(config_path=config)
            app.state.comfyui_targets = ComfyUITargetService(
                app.state.config.comfyui,
                probe=lambda target, headers=None: {"state": "stopped"},
            )

            data = TestClient(app).get("/api/comfyui/targets").json()

        self.assertEqual([item["name"] for item in data["targets"]], ["local", "modal"])
        self.assertEqual(data["targets"][1]["status"], {"state": "stopped"})


class WebGenerationExecutorTest(TestCase):
    def test_executor_passes_comfyui_target_and_records_use(self):
        config = SimpleNamespace(comfyui=_targets_config(), defaults=SimpleNamespace(image_format="png"))
        service = ComfyUITargetService(config.comfyui, probe=lambda target, headers=None: {"state": "running"})
        executor = _default_generation_executor(config, service)

        with patch("tags_machine_core.web.app.execute_render_request") as execute:
            executor(RenderRequest(backend="comfyui", prompt="x"), {"comfyui_target": "modal"})
            executor(RenderRequest(backend="novelai", prompt="x"), {"comfyui_target": "modal"})

        self.assertEqual(execute.call_args_list[0].kwargs["comfyui_target"], "modal")
        self.assertIsNone(execute.call_args_list[1].kwargs["comfyui_target"])
        modal = next(item for item in service.describe()["targets"] if item["name"] == "modal")
        self.assertIsNotNone(modal["last_used_at"])


class WebComfyUIProgressTest(TestCase):
    def test_generate_job_records_comfyui_progress_events(self):
        def executor(request, options):
            options["on_progress"]("comfyui_queued", {"at": 1.0, "prompt_id": "p1"})
            return {"backend": "comfyui", "images": []}

        client = TestClient(create_app(generation_executor=executor))
        job = client.post(
            "/api/generate",
            json={"render_request": {"backend": "comfyui", "prompt": "x"}},
        ).json()
        app_jobs = client.app.state.job_manager
        app_jobs.wait(job["id"], timeout=5)
        record = client.get(f"/api/jobs/{job['id']}").json()

        self.assertEqual(record["status"], "succeeded")
        self.assertIn(
            {"type": "comfyui_queued", "at": 1.0, "prompt_id": "p1"},
            record["events"],
        )
        self.assertNotIn("on_progress", json.dumps(record["result"]))
