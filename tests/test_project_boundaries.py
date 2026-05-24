import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_SOURCE_ROOTS = [
    PROJECT_ROOT / "src" / "tags_machine_core",
    PROJECT_ROOT / "tests",
]
DISALLOWED_LEGACY_IMPORT_ROOTS = {
    "act",
    "blackboard",
    "blackboard_proxy",
    "formula",
    "machine_input",
    "nai",
    "nai_const",
    "prompt_preset_service",
    "prompt_run_service",
    "tags_machine",
}


class ProjectBoundaryTest(unittest.TestCase):
    def test_core_and_tests_do_not_import_legacy_runtime_modules(self):
        violations: list[str] = []
        for source_path in _iter_python_sources():
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                imported_roots = _legacy_import_roots(node)
                for root in imported_roots:
                    if root in DISALLOWED_LEGACY_IMPORT_ROOTS:
                        violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno}: {root}")

        self.assertEqual(
            violations,
            [],
            "core/tests must only read legacy artifacts as data, not import legacy runtime modules",
        )

    def test_cli_keeps_backend_clients_behind_execution_module(self):
        cli_path = PROJECT_ROOT / "src" / "tags_machine_core" / "cli.py"
        tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
        violations: list[str] = []
        disallowed_clients = {"NovelAIClient", "ComfyUIClient", "SDClient"}

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in {
                    "tags_machine_core.clients",
                    "tags_machine_core.clients.novelai",
                    "tags_machine_core.clients.comfyui",
                    "tags_machine_core.clients.sd",
                }:
                    for alias in node.names:
                        if alias.name in disallowed_clients:
                            violations.append(
                                f"{cli_path.relative_to(PROJECT_ROOT)}:{node.lineno}: {module}.{alias.name}"
                            )
            elif isinstance(node, ast.Name) and node.id in disallowed_clients:
                violations.append(
                    f"{cli_path.relative_to(PROJECT_ROOT)}:{node.lineno}: direct {node.id} reference"
                )

        self.assertEqual(
            violations,
            [],
            "CLI must use tags_machine_core.execution for backend execution",
        )


def _iter_python_sources():
    for root in PYTHON_SOURCE_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _legacy_import_roots(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".", maxsplit=1)[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module.split(".", maxsplit=1)[0]]
    return []


if __name__ == "__main__":
    unittest.main()
