import time
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
