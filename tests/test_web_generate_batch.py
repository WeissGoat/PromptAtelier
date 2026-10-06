import tempfile
import threading
from unittest import TestCase

from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.generate_batch import (
    recover_interrupted_batch,
    run_generate_batch,
    validate_generate_batch,
)
from tags_machine_core.web.services.job_manager import JobManager, JobRecord


class FakeApi:
    """compose 按 seed 产出 render_request；seed 为 13 的项出图失败。"""

    def __init__(self, gate: threading.Event | None = None):
        self.generated: list[dict] = []
        self.gate = gate

    def resolve_compose_render_plan(self, request):
        if request.get("needs_agent"):
            return {"status": "requires_agent", "agent_task": {}}
        return {"status": "ready", "render_request": {"backend": "novelai", "seed": request["render"]["seed"]}}

    def generate(self, request):
        if self.gate is not None:
            self.gate.wait(timeout=5)
        seed = request["render_request"]["seed"]
        request["on_progress"]("comfyui_queued", {"prompt_id": f"p{seed}"})
        if seed == 13:
            raise RuntimeError("backend exploded")
        self.generated.append({key: value for key, value in request.items() if key != "on_progress"})
        return {"images": [{"path": f"out/{seed}.png", "meta": {"seed": seed}}], "request_body": {"huge": True}}


def _item(seed: int, **extra) -> dict:
    return {"label": f"seed {seed}", "seed": seed, "compose_request": {"render": {"seed": seed}}, **extra}


def _run(manager: JobManager, api: FakeApi, payload: dict):
    batch = validate_generate_batch(payload)
    job = manager.submit("generate-batch", lambda ctx: run_generate_batch(api, batch, ctx))
    manager.wait(job.id, timeout=5)
    return manager.get(job.id)


def _wait_until_running(manager: JobManager, job_id: str) -> dict:
    for _ in range(500):
        result = manager.get(job_id).result
        if result and result["counts"]["running"]:
            return result
        threading.Event().wait(0.01)
    raise AssertionError("batch item never started")


class GenerateBatchTest(TestCase):
    def test_runs_items_in_order_and_keeps_going_after_a_failure(self):
        api = FakeApi()
        record = _run(
            JobManager(),
            api,
            {
                "label": "Random · 3",
                "kind": "random",
                "items": [
                    _item(1, generate={"output_dir": "outputs/a", "random_selections": [{"role": "action", "ref": "x"}]}),
                    _item(13),
                    _item(2, generate={"comfyui_target": "modal"}),
                ],
            },
        )

        self.assertEqual(record.status, "succeeded")
        result = record.result
        self.assertEqual(result["counts"]["succeeded"], 2)
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual([item["status"] for item in result["items"]], ["succeeded", "failed", "succeeded"])
        self.assertEqual(result["items"][0]["images"], [{"path": "out/1.png", "meta": {"seed": 1}}])
        self.assertEqual(result["items"][0]["label"], "seed 1")
        self.assertIn("backend exploded", result["items"][1]["error"])
        self.assertNotIn("request_body", str(result))
        first, second = api.generated
        self.assertEqual(first["output_dir"], "outputs/a")
        self.assertEqual(first["render_request"]["meta"]["random_nodes"], [{"role": "action", "ref": "x"}])
        self.assertEqual(second["comfyui_target"], "modal")
        # 进度事件带上所属项，前端只给正在跑的那一项显示阶段。
        self.assertIn({"type": "comfyui_queued", "prompt_id": "p2", "item_index": 2}, record.events)

    def test_all_failed_marks_job_failed_but_keeps_items(self):
        record = _run(JobManager(), FakeApi(), {"items": [_item(13), {"compose_request": {"needs_agent": True}}]})

        self.assertEqual(record.status, "failed")
        self.assertIn("全部 2 项都失败了", record.error)
        self.assertEqual(record.result["counts"]["failed"], 2)
        self.assertIn("外部 Agent", record.result["items"][1]["error"])

    def test_cancel_finishes_current_item_and_skips_the_rest(self):
        gate = threading.Event()
        api = FakeApi(gate)
        manager = JobManager()
        batch = validate_generate_batch({"items": [_item(1), _item(2), _item(3)]})
        job = manager.submit("generate-batch", lambda ctx: run_generate_batch(api, batch, ctx))
        _wait_until_running(manager, job.id)
        manager.cancel(job.id)
        gate.set()
        manager.wait(job.id, timeout=5)

        record = manager.get(job.id)
        self.assertEqual(record.status, "cancelled")
        self.assertEqual([item["status"] for item in record.result["items"]], ["succeeded", "cancelled", "cancelled"])
        self.assertEqual(len(api.generated), 1)

    def test_partial_result_is_visible_while_running(self):
        gate = threading.Event()
        manager = JobManager()
        batch = validate_generate_batch({"items": [_item(1), _item(2)]})
        job = manager.submit("generate-batch", lambda ctx: run_generate_batch(FakeApi(gate), batch, ctx))
        try:
            result = _wait_until_running(manager, job.id)
            self.assertEqual(result["counts"], {"queued": 1, "running": 1, "succeeded": 0, "failed": 0, "cancelled": 0})
        finally:
            gate.set()
            manager.wait(job.id, timeout=5)

    def test_validation_rejects_bad_payloads(self):
        for payload, message in (
            ({}, "non-empty items"),
            ({"items": [{"label": "x"}]}, r"items\[0\]\.compose_request"),
            ({"items": [_item(1, generate={"random_selections": "x"})]}, "random_selections"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                validate_generate_batch(payload)


class GenerateBatchHttpTest(TestCase):
    def test_submit_and_list_background_runs(self):
        manager = JobManager()
        app = create_app(job_manager=manager)
        app.state.generation_api = FakeApi()
        client = TestClient(app)

        response = client.post("/api/generate/batch", json={"label": "Compare · 1", "items": [_item(5)]})
        self.assertEqual(response.status_code, 200)
        job_id = response.json()["id"]
        manager.wait(job_id, timeout=5)
        manager.submit("generate", lambda ctx: {"images": []})

        listing = client.get("/api/jobs", params={"name": "generate-batch"}).json()["jobs"]
        self.assertEqual([job["id"] for job in listing], [job_id])
        self.assertEqual(listing[0]["result"]["label"], "Compare · 1")
        self.assertEqual(listing[0]["result"]["counts"]["succeeded"], 1)

        bad = client.post("/api/generate/batch", json={"items": []})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["error"]["code"], "invalid_generate_batch")

    def test_resume_keeps_succeeded_items_and_reruns_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(persist_dir=tmp, persist_names={"generate-batch"})
            app = create_app(job_manager=manager)
            api = FakeApi()
            app.state.generation_api = api
            client = TestClient(app)

            job_id = client.post("/api/generate/batch", json={"items": [_item(1), _item(13), _item(2)]}).json()["id"]
            manager.wait(job_id, timeout=5)
            self.assertEqual(manager.get(job_id).result["counts"]["failed"], 1)

            # 失败的那项修好后继续：已成功的 1 和 2 不重跑。
            api.generated.clear()
            api.resolve_compose_render_plan = lambda request: {"status": "ready", "render_request": {"seed": 7}}
            response = client.post(f"/api/generate/batch/{job_id}/resume")
            self.assertEqual(response.status_code, 200)
            manager.wait(job_id, timeout=5)

            record = manager.get(job_id)
            self.assertEqual(record.status, "succeeded")
            self.assertEqual([item["status"] for item in record.result["items"]], ["succeeded"] * 3)
            self.assertEqual(record.result["items"][0]["images"], [{"path": "out/1.png", "meta": {"seed": 1}}])
            self.assertEqual([item["render_request"]["seed"] for item in api.generated], [7])
            self.assertEqual(client.post(f"/api/generate/batch/{job_id}/resume").status_code, 409)
            self.assertEqual(client.post("/api/generate/batch/missing/resume").status_code, 404)

    def test_recover_interrupted_batch_requeues_the_running_item(self):
        job = JobRecord(id="x", name="generate-batch", status="interrupted", result={
            "items": [{"status": "succeeded"}, {"status": "running"}, {"status": "queued"}],
            "counts": {"succeeded": 1, "running": 1, "queued": 1},
        })
        recover_interrupted_batch(job)
        self.assertEqual([item["status"] for item in job.result["items"]], ["succeeded", "queued", "queued"])
        self.assertEqual(job.result["counts"], {"queued": 2, "running": 0, "succeeded": 1, "failed": 0, "cancelled": 0})
