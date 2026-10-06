import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.job_manager import JobContext, JobManager


class WebJobsTest(TestCase):
    def test_job_manager_runs_worker_and_records_events(self):
        manager = JobManager()

        def worker(ctx: JobContext):
            ctx.emit("progress", {"value": 1})
            return {"done": True}

        job = manager.submit("demo", worker)
        manager.wait(job.id, timeout=5)

        record = manager.get(job.id)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.result, {"done": True})
        self.assertEqual(record.events[-1]["type"], "succeeded")
        self.assertIn({"type": "progress", "value": 1}, record.events)

    def test_job_cancel_sets_flag_for_worker(self):
        manager = JobManager()

        def worker(ctx: JobContext):
            while not ctx.cancel_requested:
                time.sleep(0.01)
            ctx.emit("stopped", {})
            return {"cancelled": True}

        job = manager.submit("cancel-demo", worker)
        manager.cancel(job.id)
        manager.wait(job.id, timeout=5)

        record = manager.get(job.id)
        self.assertEqual(record.status, "cancelled")
        self.assertEqual(record.result, {"cancelled": True})

    def test_jobs_http_status_and_cancel(self):
        manager = JobManager()

        def worker(ctx: JobContext):
            ctx.emit("ready", {})
            return {"ok": True}

        app = create_app(job_manager=manager)
        client = TestClient(app)
        job = manager.submit("http-demo", worker)
        manager.wait(job.id, timeout=5)

        response = client.get(f"/api/jobs/{job.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "succeeded")


class JobPersistenceTest(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.jobs_dir = Path(self._tmp.name) / "jobs"

    def tearDown(self):
        self._tmp.cleanup()

    def test_persisted_jobs_survive_restart_and_running_ones_become_interrupted(self):
        manager = JobManager(persist_dir=self.jobs_dir, persist_names={"batch"})
        release = threading.Event()

        def finished(ctx: JobContext):
            ctx.set_result({"items": [1]})
            return {"items": [1, 2]}

        def stuck(ctx: JobContext):
            ctx.set_result({"items": [{"status": "running"}]})
            release.wait(timeout=5)
            return {}

        done = manager.submit("batch", finished, request={"items": ["a", "b"]})
        manager.wait(done.id, timeout=5)
        running = manager.submit("batch", stuck)
        other = manager.submit("not-persisted", lambda ctx: {})
        manager.wait(other.id, timeout=5)
        for _ in range(500):
            if manager.get(running.id).status == "running":
                break
            time.sleep(0.01)

        recovered: list[str] = []
        restarted = JobManager(
            persist_dir=self.jobs_dir,
            persist_names={"batch"},
            recover=lambda job: recovered.append(job.id),
        )
        release.set()
        manager.wait(running.id, timeout=5)

        self.assertEqual({job.id for job in restarted.list()}, {done.id, running.id})
        self.assertEqual(restarted.get(done.id).status, "succeeded")
        self.assertEqual(restarted.get(done.id).result, {"items": [1, 2]})
        self.assertEqual(restarted.request_of(done.id), {"items": ["a", "b"]})
        self.assertEqual(restarted.get(running.id).status, "interrupted")
        self.assertEqual(recovered, [running.id])

    def test_resume_reruns_a_stopped_job_in_place(self):
        manager = JobManager(persist_dir=self.jobs_dir, persist_names={"batch"})

        def broken(ctx: JobContext):
            raise RuntimeError("boom")

        job = manager.submit("batch", broken)
        manager.wait(job.id, timeout=5)
        self.assertEqual(manager.get(job.id).status, "failed")

        manager.resume(job.id, lambda ctx: {"ok": True})
        manager.wait(job.id, timeout=5)

        record = manager.get(job.id)
        self.assertEqual(record.status, "succeeded")
        self.assertIsNone(record.error)

        release = threading.Event()
        manager.resume(job.id, lambda ctx: release.wait(timeout=5))
        with self.assertRaises(ValueError):
            manager.resume(job.id, lambda ctx: {})
        release.set()
        manager.wait(job.id, timeout=5)
