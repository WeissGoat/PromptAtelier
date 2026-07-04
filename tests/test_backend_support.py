import io
import json
import unittest
from contextlib import redirect_stdout

from tags_machine_core.backends import (
    EXPERIMENTAL_EXECUTION_BACKENDS,
    RENDER_BACKENDS,
    backend_support_report,
    ensure_backend_can_build_render_plan,
    ensure_backend_can_execute,
)
from tags_machine_core.cli import main


class BackendSupportTest(unittest.TestCase):
    def test_backend_support_matrix_includes_comfyui_as_default_execution_backend(self):
        report = backend_support_report()

        self.assertEqual(report["schema"], "tags-machine-core.backend-support/v1")
        self.assertEqual(report["render_plan_backends"], ["novelai", "comfyui", "sd"])
        self.assertEqual(report["default_execution_backends"], ["novelai", "comfyui"])
        self.assertEqual(report["experimental_execution_backends"], ["sd"])

        items = {item["backend"]: item for item in report["items"]}
        self.assertEqual(items["novelai"]["stage"], "stable")
        self.assertTrue(items["novelai"]["executes_by_default"])
        self.assertEqual(items["comfyui"]["stage"], "stable")
        self.assertTrue(items["comfyui"]["executes_by_default"])
        self.assertFalse(items["comfyui"]["requires_experimental_execution"])
        self.assertEqual(items["sd"]["stage"], "experimental")
        self.assertTrue(items["sd"]["requires_experimental_execution"])
        self.assertEqual(tuple(report["render_plan_backends"]), RENDER_BACKENDS)
        self.assertEqual(tuple(report["experimental_execution_backends"]), EXPERIMENTAL_EXECUTION_BACKENDS)

    def test_sd_backend_needs_explicit_execution_gate(self):
        ensure_backend_can_execute("novelai")
        ensure_backend_can_execute("comfyui")
        ensure_backend_can_execute("sd", allow_experimental_backend=True)

        with self.assertRaises(ValueError) as raised:
            ensure_backend_can_execute("sd")

        self.assertIn("NovelAI, ComfyUI", str(raised.exception))
        self.assertIn("--allow-experimental-backend", str(raised.exception))

    def test_render_plan_gate_accepts_documented_backends(self):
        for backend in RENDER_BACKENDS:
            with self.subTest(backend=backend):
                ensure_backend_can_build_render_plan(backend)

        with self.assertRaises(ValueError) as raised:
            ensure_backend_can_build_render_plan("unknown")

        self.assertIn("expected one of: novelai, comfyui, sd", str(raised.exception))

    def test_api_generate_gate_mentions_execute_render_request_for_experimental_backends(self):
        with self.assertRaises(ValueError) as raised:
            ensure_backend_can_execute(
                "sd",
                entrypoint="api-generate",
                experimental_flag=None,
            )

        self.assertIn("api-generate", str(raised.exception))
        self.assertIn("NovelAI, ComfyUI", str(raised.exception))
        self.assertIn("Use execute-render-request", str(raised.exception))

    def test_cli_backend_support_outputs_machine_readable_matrix(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["backend-support"])

        data = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["schema"], "tags-machine-core.backend-support/v1")
        self.assertEqual(data["default_execution_backends"], ["novelai", "comfyui"])
        self.assertEqual(data["experimental_execution_backends"], ["sd"])

    def test_cli_api_backend_support_reads_json_request_file(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["api-backend-support", "examples/requests/backend_support.json"])

        data = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["schema"], "tags-machine-core.backend-support/v1")
        self.assertEqual(data["render_plan_backends"], ["novelai", "comfyui", "sd"])
        self.assertEqual(data["default_execution_backends"], ["novelai", "comfyui"])


if __name__ == "__main__":
    unittest.main()
