from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ResultIndex:
    def __init__(self, *, roots: list[str | Path]):
        self.roots = [Path(root).resolve() for root in roots]

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for root in self.roots:
            if not root.exists():
                continue
            for run in sorted(root.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
                if not run.is_dir():
                    continue
                runs.append(
                    {
                        "name": run.name,
                        "path": str(run),
                        "task_count": self._task_count(run),
                    }
                )
        return runs

    def get_task(self, task_dir: str | Path) -> dict[str, Any]:
        task = Path(task_dir)
        files = {
            "generation_result": task / "generation_result.json",
            "prompt_bundle": task / "prompt_bundle.json",
            "render_request": task / "render_request.json",
            "png_params": task / "png_params.json",
        }
        return {
            "schema": "tags-machine-core.web.result-task/v1",
            "task_dir": str(task),
            "files": {key: str(path) for key, path in files.items() if path.exists()},
            "images": [
                str(path)
                for path in sorted(task.glob("*.png"))
                if not path.name.startswith("zz_")
            ],
            "parameter_details": [
                str(path)
                for path in sorted(task.glob("zz_*_parameter_details.png"))
            ],
        }

    def read_file(self, path: str | Path) -> Any:
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(str(target))
        if target.suffix.lower() == ".json":
            return json.loads(target.read_text(encoding="utf-8-sig"))
        return {
            "path": str(target),
            "text": target.read_text(encoding="utf-8", errors="ignore"),
        }

    def resolve_image(self, path: str | Path) -> Path:
        requested = Path(path)
        candidates = [requested.resolve()]
        if not requested.is_absolute():
            for root in self.roots:
                candidates.extend(((root / requested).resolve(), (root.parent / requested).resolve()))

        for target in candidates:
            if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            if not target.is_file():
                continue
            if any(target.is_relative_to(root) for root in self.roots):
                return target
        raise FileNotFoundError(str(path))

    def _task_count(self, run: Path) -> int:
        tasks = run / "tasks"
        if tasks.exists():
            return len([item for item in tasks.iterdir() if item.is_dir()])
        return len(
            [
                item
                for item in run.iterdir()
                if item.is_dir() and (item / "generation_result.json").exists()
            ]
        )
