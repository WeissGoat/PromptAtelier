"""把配方导出成项目能直接用的 artist（design/画风/<author>_<EnglishStyleName>/tags.txt）。

- tags.txt 沿用旧格式：第 1 行前缀、第 2 行 `,`、第 3 行后缀，`type` 行写标记，`=` 之后是 origin_uc 和 gen_json；
- gen_json 只放画风参数（含模型和 vibe），不放宽高、种子；
- 导出前先在临时目录写一遍再用正式的读取器读回来，和配方逐项比对，读回不一致就拒绝导出；
- 目标目录已存在时不覆盖，改用并列版本 `<name>_v2`、`_v3`……
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from tags_machine_core.nodes.novelai_artist import NovelAIArtistRepository

from .metadata import ImageRecord, read_source_parameters
from .recipe import VIBE_IMAGE_KEY, Recipe, artist_node, tokens_text
from .tokens import tokenize
from .workspace import WorkspaceInfo


EXPORT_SCHEMA = "tags-machine-core.style-lab.export/v1"
MARKER_FILE = "stylelab_export.json"
_NAME_RE = re.compile(r"^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*$")
_AUTHOR_RE = re.compile(r"^[A-Za-z0-9-]+$")
_VERSION_SUFFIX_RE = re.compile(r"_v(\d+)$")
# 读回比对的字段：渲染器只用这些。
_ROUNDTRIP_FIELDS = (
    ("prompt_prefix", "前缀"),
    ("prompt_suffix", "后缀"),
    ("negative_prompt", "负面"),
    ("params", "参数"),
    ("flags", "标记"),
)
# 宽高、种子是出图时的运行设置，旧画风里即使写了也会在读取时去掉。
_DIFF_SKIP_PARAMS = {VIBE_IMAGE_KEY, "width", "height", "seed", "n_samples"}


class ExportRequest(BaseModel):
    name: str
    author: str | None = None
    compare_ref: str | None = None
    include_source: bool = True


class ExportError(ValueError):
    pass


class ExportConflictError(RuntimeError):
    pass


def suggest_author(info: WorkspaceInfo) -> str | None:
    """标准语料目录 artist_parse/<日期>/<作者 id>：作者 id 就是工作区根目录名。"""
    name = Path(info.root).name
    return name if _AUTHOR_RE.match(name) else None


def folder_name(author: str | None, name: str) -> str:
    name = name.strip()
    if not _NAME_RE.match(name):
        raise ExportError("画风名只能用英文字母、数字和下划线，例如 Crisp_Manga_Ink。")
    author = (author or "").strip()
    if author and not _AUTHOR_RE.match(author):
        raise ExportError("作者 id 只能用英文字母、数字和连字符。")
    return f"{author}_{name}" if author else name


def free_folder(artist_root: Path, folder: str) -> str:
    """同名目录已存在时返回下一个空着的并列版本名。"""
    if not (artist_root / folder).exists():
        return folder
    match = _VERSION_SUFFIX_RE.search(folder)
    base, number = (folder[: match.start()], int(match.group(1))) if match else (folder, 1)
    while True:
        number += 1
        candidate = f"{base}_v{number}"
        if not (artist_root / candidate).exists():
            return candidate


def artist_values(recipe: Recipe, source_path: str | None) -> dict[str, Any]:
    """配方对应的 artist 字段，和预览、测试出图用的是同一份。"""
    return dict(artist_node(recipe, source_path=source_path)["renderers"]["novelai"])


def render_tags_txt(values: dict[str, Any]) -> str:
    prefix = _single(values.get("prompt_prefix"))
    suffix = _single(values.get("prompt_suffix"))
    negative = _single(values.get("negative_prompt"))
    flags = sorted(values.get("flags") or [])
    params = values.get("params") or {}
    # 前缀为空时第 1 行也写 `,`：读取器会丢掉空行，否则后缀会被当成前缀。
    lines = [prefix or ",", ","]
    if suffix:
        lines.append(suffix)
    if flags:
        lines.append("type, " + ", ".join(flags))
    extensions = []
    if negative:
        extensions.append(f"origin_uc, {negative}")
    if params:
        extensions.append("gen_json, " + json.dumps(params, ensure_ascii=False, separators=(",", ":")))
    if extensions:
        lines.extend(["=", *extensions])
    return "\n".join(lines) + "\n"


def roundtrip_problems(tags_txt: str, values: dict[str, Any]) -> list[str]:
    """用正式读取器读回 tags.txt，列出和配方不一致的字段。"""
    with tempfile.TemporaryDirectory(prefix="stylelab_export_") as tmp:
        folder = Path(tmp) / "artist"
        folder.mkdir()
        (folder / "tags.txt").write_text(tags_txt, encoding="utf-8")
        try:
            loaded = NovelAIArtistRepository(tmp).load(str(folder)).artist_payload()
        except ValueError as exc:
            return [f"读回失败：{exc}"]
    expected = {
        "prompt_prefix": [line for line in values.get("prompt_prefix") or [] if line],
        "prompt_suffix": [line for line in values.get("prompt_suffix") or [] if line],
        "negative_prompt": _single(values.get("negative_prompt")),
        "params": values.get("params") or {},
        "flags": sorted(values.get("flags") or []),
    }
    problems = []
    for key, label in _ROUNDTRIP_FIELDS:
        if loaded[key] != expected[key]:
            problems.append(f"{label}读回后和配方不一致")
    return problems


def _single(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return ", ".join(str(item) for item in value if str(item).strip())


# ---- diff ----


def _norm(text: str) -> str:
    return " ".join(text.replace("_", " ").lower().split())


def _token_texts(value: Any) -> list[str]:
    return [token.text for token in tokenize(_single(value)).tokens]


def _diff_tokens(before: list[str], after: list[str]) -> dict[str, Any]:
    before_norms = {_norm(text) for text in before}
    after_norms = {_norm(text) for text in after}
    return {
        "added": [text for text in after if _norm(text) not in before_norms],
        "removed": [text for text in before if _norm(text) not in after_norms],
        "same": [_norm(text) for text in before] == [_norm(text) for text in after],
    }


def diff_artists(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """两个 artist（artist_payload 格式）的差异：提示词按 token 增删，参数逐项列出；vibe 只比数量。"""
    sections = {}
    for key, label in (("prompt_prefix", "prefix"), ("prompt_suffix", "suffix"), ("negative_prompt", "negative")):
        sections[label] = _diff_tokens(_token_texts(before.get(key)), _token_texts(after.get(key)))
    # 旧画风常把整段画风都写在前缀；只看前后缀合起来的 token 是否一致，方便判断“只是换了位置”。
    style_before = _token_texts(before.get("prompt_prefix")) + _token_texts(before.get("prompt_suffix"))
    style_after = _token_texts(after.get("prompt_prefix")) + _token_texts(after.get("prompt_suffix"))
    sections["style"] = _diff_tokens(style_before, style_after)
    before_params = before.get("params") or {}
    after_params = after.get("params") or {}
    params = []
    for key in sorted(set(before_params) | set(after_params)):
        if key in _DIFF_SKIP_PARAMS:
            continue
        left, right = before_params.get(key), after_params.get(key)
        # 没写和写成空列表是一回事。
        if left != right and not (_is_empty(left) and _is_empty(right)):
            params.append({"key": key, "before": left, "after": right})
    vibe_before = list(before_params.get(VIBE_IMAGE_KEY) or [])
    vibe_after = list(after_params.get(VIBE_IMAGE_KEY) or [])
    if vibe_before != vibe_after:
        params.append({"key": "vibe", "before": len(vibe_before), "after": len(vibe_after)})
    flags_before = sorted(before.get("flags") or [])
    flags_after = sorted(after.get("flags") or [])
    return {
        **sections,
        "params": params,
        "flags": None if flags_before == flags_after else {"before": flags_before, "after": flags_after},
    }


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or value == {} or value == ""


def _style_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    left = {_norm(text) for text in _token_texts(a.get("prompt_prefix")) + _token_texts(a.get("prompt_suffix"))}
    right = {_norm(text) for text in _token_texts(b.get("prompt_prefix")) + _token_texts(b.get("prompt_suffix"))}
    union = left | right
    return len(left & right) / len(union) if union else 0.0


# ---- 导出 ----


class ArtistExporter:
    def __init__(self, artist_root: Path):
        self.artist_root = Path(artist_root)
        self.repository = NovelAIArtistRepository(self.artist_root.parent)
        self._lock = threading.Lock()

    def load(self, ref: str) -> dict[str, Any]:
        return self.repository.load(ref).artist_payload()

    def candidates(self, author: str | None, exports: list[dict[str, Any]]) -> list[str]:
        """可选的对比对象：这个配方以前的导出，加上同一作者的已有画风。"""
        refs = [item["folder"] for item in exports if (self.artist_root / item["folder"] / "tags.txt").is_file()]
        if author and self.artist_root.is_dir():
            for path in sorted(self.artist_root.glob(f"{author}_*")):
                if path.is_dir() and (path / "tags.txt").is_file() and path.name not in refs:
                    refs.append(path.name)
        return refs

    def preview(
        self,
        recipe: Recipe,
        request: ExportRequest,
        *,
        record: ImageRecord | None,
        exports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        wanted = folder_name(request.author, request.name)
        folder = free_folder(self.artist_root, wanted)
        values = artist_values(recipe, record.path if record else None)
        tags_txt = render_tags_txt(values)
        problems = roundtrip_problems(tags_txt, values)
        candidates = self.candidates(request.author, exports)
        compare_ref = request.compare_ref if request.compare_ref in candidates else None
        compare = None
        if compare_ref is None and candidates:
            # 默认对比：上一次导出；没导出过就挑同作者里画风 token 最接近的。
            if exports and exports[-1]["folder"] in candidates:
                compare_ref = exports[-1]["folder"]
            else:
                scored = []
                for ref in candidates:
                    try:
                        scored.append((_style_similarity(self.load(ref), values), ref))
                    except (OSError, ValueError):
                        continue
                compare_ref = max(scored)[1] if scored else None
        if compare_ref:
            try:
                compare = {"ref": compare_ref, "diff": diff_artists(self.load(compare_ref), values)}
            except (OSError, ValueError) as exc:
                compare = {"ref": compare_ref, "error": str(exc)}
        warnings = []
        if recipe.stage != "edit" or not recipe.locked:
            warnings.append("配方还没锁定画风，导出的前后缀可能不是你想要的。")
        if not values.get("prompt_prefix") and not values.get("prompt_suffix"):
            warnings.append("前缀和后缀都是空的。")
        vibe_count = len((values.get("params") or {}).get(VIBE_IMAGE_KEY) or [])
        if recipe.use_source_vibe and not vibe_count:
            warnings.append("配方设为使用原图 vibe，但原图里没有可用的 vibe 参考，导出的 artist 不带 vibe。")
        return {
            "folder": folder,
            "requested_folder": wanted,
            "exists": folder != wanted,
            "artist_root": str(self.artist_root),
            "tags_txt": tags_txt,
            "files": self._file_names(record, include_source=request.include_source),
            "vibe_count": vibe_count,
            "roundtrip_ok": not problems,
            "problems": problems,
            "warnings": warnings,
            "candidates": candidates,
            "compare": compare,
        }

    def export(
        self,
        recipe: Recipe,
        request: ExportRequest,
        *,
        record: ImageRecord | None,
        info: WorkspaceInfo,
        expected_folder: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            wanted = folder_name(request.author, request.name)
            folder = free_folder(self.artist_root, wanted)
            if expected_folder and folder != expected_folder:
                raise ExportConflictError(f"目标目录变了（现在是 {folder}），请重新预览后再导出。")
            values = artist_values(recipe, record.path if record else None)
            tags_txt = render_tags_txt(values)
            problems = roundtrip_problems(tags_txt, values)
            if problems:
                raise ExportError("；".join(problems))
            self.artist_root.mkdir(parents=True, exist_ok=True)
            temp = self.artist_root / f".{folder}.stylelab-{uuid.uuid4().hex[:6]}"
            temp.mkdir()
            try:
                files = self._write_files(temp, recipe, values, tags_txt, record, info, request, folder)
                # 先在临时目录写完再改名：失败不会留下半个画风，改名时目标已存在也会失败而不是覆盖。
                temp.rename(self.artist_root / folder)
            except Exception:
                shutil.rmtree(temp, ignore_errors=True)
                raise
        return {
            "folder": folder,
            "path": str(self.artist_root / folder),
            "recipe_id": recipe.id,
            "recipe_version": recipe.version,
            "recipe_name": recipe.name,
            "exported_at": time.time(),
            "files": files,
        }

    def _file_names(self, record: ImageRecord | None, *, include_source: bool) -> list[str]:
        names = ["tags.txt", "notes.md", MARKER_FILE]
        if record and include_source:
            stem = Path(record.path).stem
            names += [
                f"source_{stem}{Path(record.path).suffix}",
                f"source_prompt_{stem}.txt",
                f"source_uc_{stem}.txt",
                f"source_action_{stem}.txt",
                f"source_params_{stem}.json",
            ]
        return names

    def _write_files(
        self,
        folder_path: Path,
        recipe: Recipe,
        values: dict[str, Any],
        tags_txt: str,
        record: ImageRecord | None,
        info: WorkspaceInfo,
        request: ExportRequest,
        folder: str,
    ) -> list[str]:
        subject = tokens_text(recipe.subject).strip(" ,")
        (folder_path / "tags.txt").write_text(tags_txt, encoding="utf-8")
        (folder_path / "notes.md").write_text(
            build_notes(folder, recipe, values, record, info, subject), encoding="utf-8"
        )
        marker = {
            "schema": EXPORT_SCHEMA,
            "recipe": {"id": recipe.id, "version": recipe.version, "name": recipe.name},
            "workspace": {"id": info.id, "root": info.root},
            "source": {"image_id": record.id, "rel_path": record.rel_path} if record else None,
            "exported_at": time.time(),
        }
        (folder_path / MARKER_FILE).write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
        if record and request.include_source:
            source = Path(record.path)
            stem = source.stem
            shutil.copy2(source, folder_path / f"source_{stem}{source.suffix}")
            (folder_path / f"source_prompt_{stem}.txt").write_text(record.prompt, encoding="utf-8")
            (folder_path / f"source_uc_{stem}.txt").write_text(record.negative_prompt, encoding="utf-8")
            (folder_path / f"source_action_{stem}.txt").write_text(subject, encoding="utf-8")
            params, _ = read_source_parameters(source)
            (folder_path / f"source_params_{stem}.json").write_text(
                json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return sorted(path.name for path in folder_path.iterdir())


def build_notes(
    folder: str,
    recipe: Recipe,
    values: dict[str, Any],
    record: ImageRecord | None,
    info: WorkspaceInfo,
    subject: str,
) -> str:
    params = values.get("params") or {}
    vibe_count = len(params.get(VIBE_IMAGE_KEY) or [])
    lines = [
        f"# {folder}",
        "",
        "由画风工坊（Style Lab）从配方导出。",
        "",
        "来源：",
        "",
        f"- 工作区：`{info.root}`",
        f"- 配方：{recipe.name}（`{recipe.id}` v{recipe.version}）",
    ]
    if record:
        lines.append(f"- 原图：`{record.rel_path}`")
        if record.post:
            lines.append(f"- 投稿：`{record.post.post_id}` {record.post.date or ''} {record.post.title or ''}".rstrip())
        lines.append(f"- 原图种子：`{record.seed}`，尺寸 {record.width} × {record.height}")
    lines += [
        "",
        "参数：",
        "",
        f"- model：`{params.get('model')}`",
    ]
    for key in ("sampler", "steps", "scale", "cfg_rescale", "noise_schedule"):
        if key in params:
            lines.append(f"- {key}：`{params[key]}`")
    if vibe_count:
        strengths = params.get("reference_strength_multiple") or []
        lines.append(f"- vibe：{vibe_count} 张，强度 {strengths}")
    else:
        lines.append("- vibe：无")
    lines += [
        "",
        "提示词结构：`前缀（第 1 行） + 角色 + 动作 + 后缀（第 3 行）`。宽高不属于画风，由出图时决定。",
        "",
        "测试用主体（原图去掉画风后的内容）：",
        "",
        "```text",
        subject or "（空）",
        "```",
    ]
    if recipe.notes.strip():
        lines += ["", "配方备注：", "", recipe.notes.strip()]
    return "\n".join(lines) + "\n"


class ExportLog:
    """工作区里记录每次导出（.stylelab/exports.json），配方页据此显示“已导出”和是否有新改动。"""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "exports.json"
        self._lock = threading.Lock()

    def all(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def for_recipe(self, recipe_id: str) -> list[dict[str, Any]]:
        return [item for item in self.all() if item.get("recipe_id") == recipe_id]

    def add(self, entry: dict[str, Any]) -> None:
        with self._lock:
            items = [*self.all(), entry]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)


__all__ = [
    "ArtistExporter",
    "ExportConflictError",
    "ExportError",
    "ExportLog",
    "ExportRequest",
    "MARKER_FILE",
    "diff_artists",
    "folder_name",
    "free_folder",
    "render_tags_txt",
    "roundtrip_problems",
    "suggest_author",
]

