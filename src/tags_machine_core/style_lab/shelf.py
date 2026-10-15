"""全局素材架：选过的角色/动作卡片和各自筛掉的 tag、搜索的分类筛选，换配方也一直保留。

配方里的 materials 只记这个配方用了哪几块（以及加进去时的筛选），素材架本身不跟配方走。
"""
from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel, Field

from .recipe import RecipeMaterial


SHELF_SCHEMA = "tags-machine-core.style-lab.material-shelf/v1"


class MaterialShelf(BaseModel):
    materials: list[RecipeMaterial] = Field(default_factory=list)
    # 角色 / 动作 -> 分面 -> 选中的值，和素材搜索的下拉框一一对应。
    facets: dict[str, dict[str, str]] = Field(default_factory=dict)


class ShelfStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> MaterialShelf:
        try:
            return MaterialShelf.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return MaterialShelf()
        except ValueError:
            # 文件坏了不该让配方页打不开；下次保存会覆盖。
            return MaterialShelf()

    def save(self, shelf: MaterialShelf) -> MaterialShelf:
        # 同一块素材只留一份（以后出现的为准）。
        unique: dict[tuple[str, str], RecipeMaterial] = {}
        for material in shelf.materials:
            unique.pop((material.role, material.ref), None)
            unique[(material.role, material.ref)] = material
        shelf = MaterialShelf(materials=list(unique.values()), facets=shelf.facets)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(shelf.model_dump_json(indent=2), encoding="utf-8")
            temp.replace(self.path)
        return shelf
