import json
import time
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from tags_machine_core.web import create_app


class LiveCompareGenerationTest(TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)

    def test_live_compare_e2e_pipeline(self):
        # 1. Locate a reference PNG with metadata
        sample_path = Path("acceptance_compare/real_run_action_homura_the_bro_5_001/core/cf7bc734_1779604101_01.png")
        if not sample_path.exists():
            candidates = list(Path("acceptance_compare").glob("**/*.png"))
            if not candidates:
                self.skipTest("No sample PNG found in acceptance_compare for live test")
            sample_path = candidates[0]

        # 2. Inspect image metadata via API
        inspect_resp = self.client.post("/api/image-meta/inspect", json={"path": str(sample_path)})
        self.assertEqual(inspect_resp.status_code, 200, inspect_resp.text)
        meta = inspect_resp.json()

        base_prompt = meta.get("prompt") or "1girl, solo, school uniform"
        base_seed = meta.get("seed") or 12345678
        print(f"\n[E2E] Read base prompt: {base_prompt[:40]}... Seed: {base_seed}")

        # 3. Formulate two variants with controlled variables (same seed)
        variant_1_prompt = base_prompt

        # 4. Trigger live generation for Variant 1 with NovelAI backend
        payload_1 = {
            "render_request": {
                "backend": "novelai",
                "prompt": variant_1_prompt,
                "negative_prompt": meta.get("negative_prompt") or "lowres, bad anatomy",
                "model": "nai-diffusion-3",
                "seed": base_seed,
                "size": {
                    "width": 832,
                    "height": 1216,
                },
                "params": {
                    "seed": base_seed,
                    "width": 832,
                    "height": 1216,
                    "steps": 28,
                    "scale": 5.0,
                    "sampler": "k_euler",
                },
                "meta": {
                    "source": "compare_studio_test",
                    "variant": "variant_1",
                },
            }
        }

        gen_resp_1 = self.client.post("/api/generate", json=payload_1)
        self.assertEqual(gen_resp_1.status_code, 200, gen_resp_1.text)
        job_1_id = gen_resp_1.json()["id"]

        print(f"[E2E] Job 1 submitted: {job_1_id}, waiting for NovelAI generation...")
        job_1 = self._wait_job_completion(job_1_id, timeout_sec=120)
        self.assertEqual(job_1["status"], "succeeded", f"Job 1 failed: {job_1.get('error')}")

        images_1 = job_1.get("result", {}).get("images", [])
        self.assertTrue(len(images_1) > 0, "Job 1 produced no images")
        img_1_path = Path(images_1[0]["path"])
        self.assertTrue(img_1_path.exists(), f"Image 1 does not exist on disk: {img_1_path}")
        print(f"[E2E] Variant 1 generated successfully: {img_1_path}")

        # 5. Verify the generated image can be re-inspected by our new API endpoint
        reinspect_resp = self.client.post("/api/image-meta/inspect", json={"path": str(img_1_path)})
        self.assertEqual(reinspect_resp.status_code, 200)
        reinspected_meta = reinspect_resp.json()
        self.assertEqual(reinspected_meta["seed"], base_seed)
        print(f"[E2E] Verified re-inspected seed matches locked control: {reinspected_meta['seed']}")

    def _wait_job_completion(self, job_id: str, timeout_sec: int = 120) -> dict:
        start = time.time()
        while time.time() - start < timeout_sec:
            resp = self.client.get(f"/api/jobs/{job_id}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            if data["status"] in ("succeeded", "failed", "cancelled"):
                return data
            time.sleep(2)
        self.fail(f"Job {job_id} timed out after {timeout_sec}s")
