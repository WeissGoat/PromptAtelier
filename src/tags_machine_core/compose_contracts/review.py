"""出图复核（给 Agent 用的 `contract results` / `contract review`）。

- results：每帧的出图状态（有图 / 缺图 / 只有旧提示词的图 / 最近一次失败 / 排队中）、最新一轮的图、各轮次；
  失败原因来自 Web 出图任务记录（`<output_dir>/.web/jobs`）。
- review：在 results 之上挑每帧代表图、检查 PNG 元数据（画幅、负面词冲突、参数是否一致）、
  汇总提示词校验里的连续性问题，可选生成联系表（总览 + 每帧全部候选）。
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tags_machine_core.verification.image_params import read_image_parameters

from .selection import select_frames
from .tokens import tag_keys

if TYPE_CHECKING:
    from .service import ContractService


JOBS_DIR = Path(".web") / "jobs"
REVIEW_DIR = ".contract_review"
PROMPT_REVIEW_VALIDATORS = ("identity_anchor", "frame_novelty", "character_count", "tag_conflict")
# 契约里出现这些词时按成人内容处理：负面词里的 nsfw 会和它打架。
ADULT_HINTS = frozenset({
    "nsfw", "explicit", "sex", "nude", "completely_nude", "nipples", "pussy", "penis", "vaginal", "anal",
    "cum", "fellatio", "paizuri", "masturbation", "sex_from_behind", "missionary", "cowgirl_position",
})
STATUS_ORDER = ("failed", "missing", "stale", "pending", "ok")
STATUS_LABELS = {"ok": "有图", "missing": "缺图", "stale": "只有旧提示词的图", "failed": "最近一次失败", "pending": "排队 / 进行中"}


# ---------------------------------------------------------------------------
# 出图任务记录
# ---------------------------------------------------------------------------


def generation_attempts(output_dir: Path | None, contract_id: str) -> list[dict[str, Any]]:
    """Web 出图任务里属于这份契约的每一项：帧、画风、状态、错误、时间。"""
    if output_dir is None:
        return []
    jobs = Path(output_dir) / JOBS_DIR
    if not jobs.is_dir():
        return []
    attempts: list[dict[str, Any]] = []
    for request_path in jobs.glob("*.request.json"):
        job_path = request_path.with_name(request_path.name.replace(".request.json", ".json"))
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
            job = json.loads(job_path.read_text(encoding="utf-8")) if job_path.is_file() else {}
        except (OSError, ValueError):
            continue
        if not isinstance(request, dict):
            continue
        requested = request.get("items") or []
        if not any(_item_contract(item).get("id") == contract_id for item in requested):
            continue
        results = (job.get("result") or {}).get("items") or []
        by_index = {item.get("index"): item for item in results if isinstance(item, dict)}
        job_status = job.get("status") or "queued"
        run = Path(str(request.get("output_dir") or "")).name
        for index, item in enumerate(requested):
            trace = _item_contract(item)
            if trace.get("id") != contract_id:
                continue
            result = by_index.get(index) or {}
            status = result.get("status") or ("queued" if job_status in {"queued", "running"} else "cancelled")
            if status in {"queued", "running"} and job_status not in {"queued", "running"}:
                status = "cancelled"
            attempts.append({
                "job": job.get("id") or request_path.name.split(".")[0],
                "run": run,
                "frame_id": str(trace.get("frame_id") or ""),
                "artist": trace.get("artist"),
                "prompt_hash": trace.get("prompt_hash"),
                "status": status,
                "error": short_error(result.get("error")),
                "at": float(result.get("finished_at") or result.get("started_at") or job.get("updated_at") or 0),
            })
    return attempts


def _item_contract(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    compose = (item.get("compose_request") or {}).get("compose") or {}
    trace = compose.get("contract")
    return trace if isinstance(trace, dict) else {}


def short_error(error: Any) -> str | None:
    if not error:
        return None
    text = str(error)
    if "Just a moment" in text:
        text = re.sub(r"<!DOCTYPE.*", "Cloudflare 拦截页（稍后重试）", text, flags=re.S | re.I)
    text = re.sub(r"<!DOCTYPE.*|<html.*", "（HTML 页面）", text, flags=re.S | re.I)
    text = " ".join(text.split())
    return text[:200] + ("…" if len(text) > 200 else "")


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


def results_report(
    service: "ContractService",
    contract_id: str,
    *,
    frames: str | None = None,
    artist: str | None = None,
    current_only: bool = False,
    all_images: bool = False,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail = detail or service.detail(contract_id)
    if "parse_error" in detail:
        raise ValueError(detail["parse_error"])
    results = service.results(contract_id, detail)
    attempts = [item for item in generation_attempts(service.output_dir, contract_id) if not artist or item["artist"] == artist]
    by_frame_attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        by_frame_attempts[attempt["frame_id"]].append(attempt)
    phases = _member_phases(detail)

    items: list[dict[str, Any]] = []
    for frame in select_frames(detail["frames"], frames):
        # 状态按这个画风的全部图算；current_only 只影响列出哪些图（否则只有旧图的帧会被当成缺图）。
        everything = [image for image in results["frames"].get(frame["id"], []) if not artist or image.get("artist") == artist]
        images = [image for image in everything if not current_only or image["current"]]
        rounds = _rounds(images)
        entry: dict[str, Any] = {"id": frame["id"], "title": frame["title"]}
        if phases.get(frame["id"]):
            entry["phase"] = phases[frame["id"]]
        status, failure, pending = _frame_status(everything, by_frame_attempts.get(frame["id"], []))
        entry.update(
            status=status,
            images=len(images),
            current=sum(1 for image in images if image["current"]),
            picked=sum(1 for image in images if image["picked"]),
            rounds=len(rounds),
        )
        if failure:
            entry["failure"] = failure
        if pending:
            entry["pending"] = pending
        shown = images if all_images else (rounds[0]["images"] if rounds else [])
        entry["latest_round" if not all_images else "all_images"] = [_compact_image(image) for image in shown]
        items.append(entry)

    counts = Counter(item["status"] for item in items)
    return {
        "id": contract_id,
        "title": detail["request"].get("title") or "",
        "frame_count": len(detail["frames"]),
        "frames_shown": len(items),
        "filters": {"artist": artist, "current_only": current_only},
        "counts": {status: counts.get(status, 0) for status in STATUS_ORDER},
        "status_labels": STATUS_LABELS,
        "images": sum(item["images"] for item in items),
        "runs": _runs(results, attempts, artist=artist),
        "frames": items,
    }


def _member_phases(detail: dict[str, Any]) -> dict[str, str]:
    group = (detail.get("sources") or {}).get("action_group") or {}
    by_index = {member["index"]: (member.get("classify") or {}).get("phase") for member in group.get("members") or []}
    return {frame["id"]: by_index.get(frame.get("member_index")) or "" for frame in detail["frames"] if by_index.get(frame.get("member_index"))}


def _rounds(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按「结果目录 + 画风」分轮，最新的一轮在前（和 Web 故事板一致）。"""
    rounds: dict[str, dict[str, Any]] = {}
    for image in images:
        key = f"{image['run']}|{image.get('artist') or ''}"
        rounds.setdefault(key, {"run": image["run"], "artist": image.get("artist"), "images": []})["images"].append(image)
    return sorted(rounds.values(), key=lambda item: max(image["created_at"] for image in item["images"]), reverse=True)


def _frame_status(images: list[dict[str, Any]], attempts: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None, int]:
    pending = sum(1 for item in attempts if item["status"] in {"queued", "running"})
    finished = [item for item in attempts if item["status"] in {"succeeded", "failed"}]
    newest_image = max((image["created_at"] for image in images), default=0.0)
    failure = None
    if finished:
        last = max(finished, key=lambda item: item["at"])
        if last["status"] == "failed" and last["at"] >= newest_image:
            failure = {key: last[key] for key in ("run", "artist", "error")}
            failure["at"] = _time(last["at"])
    if failure:
        return "failed", failure, pending
    if pending and not images:
        return "pending", None, pending
    if not images:
        return "missing", None, pending
    if not any(image["current"] for image in images):
        return "stale", None, pending
    return "ok", None, pending


def _runs(results: dict[str, Any], attempts: list[dict[str, Any]], *, artist: str | None) -> list[dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for images in results["frames"].values():
        for image in images:
            if artist and image.get("artist") != artist:
                continue
            run = runs.setdefault(image["run"], {"run": image["run"], "images": 0, "frames": set(), "artists": set(), "started": image["created_at"], "failed": 0, "pending": 0})
            run["images"] += 1
            run["frames"].add(image["frame_id"])
            run["artists"].add(image.get("artist") or "")
            run["started"] = min(run["started"], image["created_at"])
    for attempt in attempts:
        run = runs.setdefault(attempt["run"], {"run": attempt["run"], "images": 0, "frames": set(), "artists": set(), "started": attempt["at"], "failed": 0, "pending": 0})
        if attempt["status"] == "failed":
            run["failed"] += 1
        elif attempt["status"] in {"queued", "running"}:
            run["pending"] += 1
        run["artists"].add(attempt["artist"] or "")
    ordered = sorted(runs.values(), key=lambda item: item["started"], reverse=True)
    return [
        {
            "run": item["run"],
            "started": _time(item["started"]),
            "images": item["images"],
            "frames": len(item["frames"]),
            "artists": sorted(name for name in item["artists"] if name),
            **({"failed": item["failed"]} if item["failed"] else {}),
            **({"pending": item["pending"]} if item["pending"] else {}),
        }
        for item in ordered
    ]


def _compact_image(image: dict[str, Any]) -> dict[str, Any]:
    item = {"path": image["path"], "run": image["run"], "artist": image.get("artist"), "seed": image.get("seed")}
    if not image["current"]:
        item["stale"] = True
    if image["picked"]:
        item["picked"] = True
    return item


def _time(seconds: float) -> str:
    return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M") if seconds else ""


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------


def review_contract(
    service: "ContractService",
    contract_id: str,
    *,
    frames: str | None = None,
    artist: str | None = None,
    current_only: bool = False,
    sheets: bool = False,
    out_dir: Path | None = None,
    per_frame: int = 8,
) -> dict[str, Any]:
    detail = service.detail(contract_id)
    report = results_report(
        service, contract_id, frames=frames, artist=artist, current_only=current_only, all_images=True, detail=detail,
    )
    frame_details = {frame["id"]: frame for frame in detail["frames"]}
    adult = _is_adult(detail)

    reviewed: list[dict[str, Any]] = []
    for entry in report["frames"]:
        images = entry.pop("all_images")
        candidates = _ordered_candidates(images)
        item = {key: entry[key] for key in entry}
        item["representative"] = candidates[0]["path"] if candidates else None
        item["candidates"] = [image["path"] for image in candidates[:per_frame]]
        reviewed.append({**item, "_images": candidates})

    audit = _audit(reviewed, frame_details, adult=adult)
    shown = {entry["id"] for entry in reviewed}
    prompt_issues = [
        {"frame_id": issue.get("frame_id"), "validator": issue["validator"], "message": issue["message"]}
        for issue in detail["issues"]
        if issue["validator"] in PROMPT_REVIEW_VALIDATORS and issue["severity"] != "info"
        and (issue.get("frame_id") is None or issue["frame_id"] in shown)
    ]
    review: dict[str, Any] = {
        "id": contract_id,
        "title": report["title"],
        "frame_count": report["frame_count"],
        "frames_shown": report["frames_shown"],
        "filters": report["filters"],
        "counts": report["counts"],
        "status_labels": STATUS_LABELS,
        "runs": report["runs"],
        "todo": _todo(reviewed, prompt_issues, audit),
        "prompt_issues": prompt_issues,
        "audit": audit,
        "frames": [{key: value for key, value in item.items() if key != "_images"} for item in reviewed],
    }
    if sheets:
        target = out_dir or _default_review_dir(service, contract_id)
        review["out_dir"] = str(target)
        review["sheets"] = write_contact_sheets(target, review_title(detail), reviewed, per_frame=per_frame)
        target.mkdir(parents=True, exist_ok=True)
        (target / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def review_title(detail: dict[str, Any]) -> str:
    return detail["request"].get("title") or detail["id"]


def _default_review_dir(service: "ContractService", contract_id: str) -> Path:
    if service.output_dir is None:
        raise ValueError("没有配置出图目录，请用 --out 指定联系表目录")
    service.store.path_for(contract_id)  # 校验 id
    return service.output_dir / REVIEW_DIR / contract_id


def _ordered_candidates(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """代表图在前：已采用 > 当前提示词 > 其他；同类里新的在前（images 已按时间倒序）。"""
    def rank(image: dict[str, Any]) -> int:
        if image.get("picked"):
            return 0
        return 1 if not image.get("stale") else 2

    return sorted(images, key=rank)


def _is_adult(detail: dict[str, Any]) -> bool:
    for frame in detail["frames"]:
        text = "\n".join([frame["prompts"].get("positive") or ""] + [block["positive"] for block in frame.get("character_prompts") or []])
        if ADULT_HINTS & set(tag_keys(text)):
            return True
    return False


def _audit(reviewed: list[dict[str, Any]], frames: dict[str, dict[str, Any]], *, adult: bool) -> dict[str, Any]:
    warnings: dict[tuple[str, str], dict[str, Any]] = {}
    params: dict[tuple, dict[str, Any]] = {}
    unreadable = 0

    def warn(check: str, message: str, frame_id: str, path: str) -> None:
        item = warnings.setdefault((check, message), {"check": check, "message": message, "frames": [], "images": 0, "example": path})
        item["images"] += 1
        if frame_id not in item["frames"]:
            item["frames"].append(frame_id)

    for entry in reviewed:
        frame = frames[entry["id"]]
        positive = "\n".join([frame["submit"].get("positive") or ""] + [block["positive"] for block in frame.get("character_prompts") or []])
        positive_keys = set(tag_keys(positive))
        for image in entry["_images"]:
            try:
                info = read_image_parameters(image["path"])
            except (OSError, ValueError):
                unreadable += 1
                continue
            parameters = info.get("parameters") or {}
            core = info.get("png_text", {}).get("tags_machine_core")
            model = (core.get("model") if isinstance(core, dict) else None) or parameters.get("model_name") or info.get("png_text", {}).get("Source")
            width, height = parameters.get("width"), parameters.get("height")
            key = (image.get("artist") or "", model, parameters.get("steps"), parameters.get("scale"), parameters.get("cfg_rescale"),
                   parameters.get("sampler"), parameters.get("noise_schedule"))
            combo = params.setdefault(key, {"artist": key[0], "model": model, "steps": key[2], "scale": key[3], "cfg_rescale": key[4],
                                            "sampler": key[5], "noise_schedule": key[6], "sizes": Counter(), "images": 0})
            combo["images"] += 1
            if width and height:
                combo["sizes"][f"{width}x{height}"] += 1
            path = image["path"]
            orientation = _orientation(width, height)
            if frame.get("size") and orientation and orientation != frame["size"]:
                warn("size", f"画幅是 {orientation}，帧要求 {frame['size']}", entry["id"], path)
            uc = _negative_text(parameters)
            uc_keys = set(tag_keys(uc))
            if adult and "nsfw" in uc_keys:
                warn("negative", "契约是成人内容，但出图的负面词里有 nsfw（多半来自负面预设），会压制画面内容", entry["id"], path)
            clash = sorted((positive_keys & uc_keys) - {"nsfw"})
            if clash:
                warn("negative", "这些词同时在正向和负面里：" + ", ".join(clash[:6]), entry["id"], path)
            if frame.get("character_prompts") and _is_v4(model) and not _char_captions(parameters):
                warn("characters", "帧写了分角色块，但出图没有用 Character Prompts（被并进了主提示词）", entry["id"], path)

    by_artist: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for combo in params.values():
        by_artist[combo["artist"]].append(combo)
    notes = [
        {"check": "params", "message": f"画风 {name or '（未记录）'} 的出图参数不一致（{len(combos)} 种组合）", "frames": [], "images": sum(c["images"] for c in combos)}
        for name, combos in by_artist.items() if len(combos) > 1
    ]
    return {
        "params": [
            {**{k: v for k, v in combo.items() if k != "sizes"}, "sizes": dict(combo["sizes"].most_common())}
            for combo in sorted(params.values(), key=lambda item: -item["images"])
        ],
        "warnings": list(warnings.values()) + notes,
        "unreadable": unreadable,
        "adult": adult,
    }


def _orientation(width: Any, height: Any) -> str | None:
    if not width or not height:
        return None
    if width == height:
        return "square"
    return "portrait" if height > width else "landscape"


def _negative_text(parameters: dict[str, Any]) -> str:
    uc = parameters.get("uc") or parameters.get("negative_prompt")
    if isinstance(uc, str) and uc:
        return uc
    caption = ((parameters.get("v4_negative_prompt") or {}).get("caption") or {})
    return str(caption.get("base_caption") or "")


def _char_captions(parameters: dict[str, Any]) -> list[Any]:
    caption = ((parameters.get("v4_prompt") or {}).get("caption") or {})
    return [item for item in caption.get("char_captions") or [] if (item or {}).get("char_caption")]


def _is_v4(model: Any) -> bool:
    text = str(model or "").lower()
    return any(mark in text for mark in ("diffusion-4", "diffusion v4", "diffusion-5", "diffusion v5"))


def _todo(reviewed: list[dict[str, Any]], prompt_issues: list[dict[str, Any]], audit: dict[str, Any]) -> list[str]:
    todo: list[str] = []
    by_status: dict[str, list[str]] = defaultdict(list)
    for entry in reviewed:
        by_status[entry["status"]].append(entry["id"])
    if by_status.get("failed"):
        errors = Counter((entry.get("failure") or {}).get("error") or "未知错误" for entry in reviewed if entry["status"] == "failed")
        top = "；".join(f"{error}（{count} 帧）" for error, count in errors.most_common(2))
        todo.append(f"重出最近一次失败的帧：{_ids(by_status['failed'])}。错误：{top}")
    if by_status.get("missing"):
        todo.append(f"还没出图的帧：{_ids(by_status['missing'])}")
    if by_status.get("stale"):
        todo.append(f"只有旧提示词出的图，改过提示词后还没重出：{_ids(by_status['stale'])}")
    if by_status.get("pending"):
        todo.append(f"还在排队或生成中：{_ids(by_status['pending'])}")
    for issue in prompt_issues:
        todo.append(f"{issue['frame_id'] or '契约'}：{issue['message']}")
    for warning in audit["warnings"]:
        frames = f"（{_ids(warning['frames'])}）" if warning["frames"] else ""
        todo.append(f"出图参数：{warning['message']}{frames}")
    return todo


def _ids(ids: list[str], limit: int = 20) -> str:
    return ", ".join(ids[:limit]) + (f" 等 {len(ids)} 帧" if len(ids) > limit else "")


# ---------------------------------------------------------------------------
# 联系表
# ---------------------------------------------------------------------------

OVERVIEW_COLUMNS = 6
OVERVIEW_TILE = (220, 300)
OVERVIEW_ROWS_PER_SHEET = 6
DETAIL_TILE = (170, 230)
DETAIL_LABEL_WIDTH = 260
DETAIL_ROWS_PER_SHEET = 10
STATUS_COLORS = {"ok": (60, 160, 90), "stale": (150, 150, 150), "missing": (200, 70, 60), "failed": (200, 70, 60), "pending": (70, 120, 200)}
BACKGROUND = (24, 24, 28)
TEXT = (235, 235, 235)
MUTED = (160, 160, 170)
PICKED = (235, 185, 40)


def write_contact_sheets(out_dir: Path, title: str, reviewed: list[dict[str, Any]], *, per_frame: int = 8) -> list[str]:
    """overview_NN.jpg：每帧一张代表图按顺序排；frames_NN.jpg：每帧一行全部候选（已采用、当前提示词的在前）。"""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in list(out_dir.glob("overview_*.jpg")) + list(out_dir.glob("frames_*.jpg")):
        old.unlink()
    font, small, cjk = _fonts()
    label = (lambda text: text) if cjk else (lambda text: text.encode("ascii", "ignore").decode().strip())
    cache: dict[tuple[str, tuple[int, int]], Any] = {}

    def thumb(path: str, size: tuple[int, int]):
        key = (path, size)
        if key not in cache:
            try:
                with Image.open(path) as image:
                    image = image.convert("RGB")
                    image.thumbnail(size)
                    cache[key] = image.copy()
            except OSError:
                cache[key] = None
        return cache[key]

    written: list[str] = []
    header = 44

    # 总览
    per_sheet = OVERVIEW_COLUMNS * OVERVIEW_ROWS_PER_SHEET
    tile_w, tile_h = OVERVIEW_TILE
    caption = 38
    for sheet_index, start in enumerate(range(0, len(reviewed), per_sheet), start=1):
        chunk = reviewed[start:start + per_sheet]
        rows = (len(chunk) + OVERVIEW_COLUMNS - 1) // OVERVIEW_COLUMNS
        sheet = Image.new("RGB", (OVERVIEW_COLUMNS * (tile_w + 8) + 8, header + rows * (tile_h + caption + 8) + 8), BACKGROUND)
        draw = ImageDraw.Draw(sheet)
        draw.text((10, 10), label(f"{title} · 总览 {sheet_index}") or f"overview {sheet_index}", fill=TEXT, font=font)
        for offset, entry in enumerate(chunk):
            x = 8 + (offset % OVERVIEW_COLUMNS) * (tile_w + 8)
            y = header + (offset // OVERVIEW_COLUMNS) * (tile_h + caption + 8)
            _tile(draw, sheet, x, y, (tile_w, tile_h), entry, entry["_images"][0] if entry["_images"] else None, thumb, small, label)
            text = f"{entry['id']} {entry['title']}"
            draw.text((x, y + tile_h + 2), label(text)[:22], fill=TEXT, font=small)
            meta = f"{entry['images']} 张" + (f" · {entry['phase']}" if entry.get("phase") else "")
            draw.text((x, y + tile_h + 19), label(meta) or str(entry["images"]), fill=MUTED, font=small)
        path = out_dir / f"overview_{sheet_index:02d}.jpg"
        sheet.save(path, quality=85)
        written.append(str(path))

    # 每帧候选
    tile_w, tile_h = DETAIL_TILE
    for sheet_index, start in enumerate(range(0, len(reviewed), DETAIL_ROWS_PER_SHEET), start=1):
        chunk = reviewed[start:start + DETAIL_ROWS_PER_SHEET]
        columns = max(1, min(per_frame, max(len(entry["_images"]) for entry in chunk)))
        width = DETAIL_LABEL_WIDTH + columns * (tile_w + 6) + 8
        sheet = Image.new("RGB", (width, header + len(chunk) * (tile_h + 10) + 8), BACKGROUND)
        draw = ImageDraw.Draw(sheet)
        draw.text((10, 10), label(f"{title} · 候选 {sheet_index}") or f"frames {sheet_index}", fill=TEXT, font=font)
        for row, entry in enumerate(chunk):
            y = header + row * (tile_h + 10)
            color = STATUS_COLORS.get(entry["status"], MUTED)
            draw.rectangle((8, y, 12, y + tile_h), fill=color)
            lines = [
                f"{entry['id']} {entry['title']}",
                STATUS_LABELS.get(entry["status"], entry["status"]),
                f"{entry['images']} 张 · 当前 {entry['current']} · 采用 {entry['picked']}",
                entry.get("phase") or "",
                ((entry.get("failure") or {}).get("error") or "")[:60],
            ]
            for number, line in enumerate(line for line in lines if line):
                text = label(line)
                if text:
                    draw.text((20, y + 4 + number * 20), text[:26], fill=TEXT if number == 0 else MUTED, font=small)
            for column, image in enumerate(entry["_images"][:per_frame]):
                x = DETAIL_LABEL_WIDTH + column * (tile_w + 6)
                _tile(draw, sheet, x, y, (tile_w, tile_h), entry, image, thumb, small, label)
            if not entry["_images"]:
                draw.text((DETAIL_LABEL_WIDTH, y + tile_h // 2), label("无图") or "no image", fill=MUTED, font=small)
        path = out_dir / f"frames_{sheet_index:02d}.jpg"
        sheet.save(path, quality=85)
        written.append(str(path))
    return written


def _tile(draw, sheet, x: int, y: int, size: tuple[int, int], entry: dict[str, Any], image: dict[str, Any] | None, thumb, font, label) -> None:
    width, height = size
    draw.rectangle((x, y, x + width - 1, y + height - 1), fill=(40, 40, 46))
    if image is None:
        text = label(STATUS_LABELS.get(entry["status"], "")) or entry["status"]
        draw.text((x + 10, y + height // 2 - 8), text, fill=STATUS_COLORS.get(entry["status"], MUTED), font=font)
        return
    picture = thumb(image["path"], size)
    if picture is not None:
        sheet.paste(picture, (x + (width - picture.width) // 2, y + (height - picture.height) // 2))
    if image.get("picked"):
        draw.rectangle((x, y, x + width - 1, y + height - 1), outline=PICKED, width=4)
    if image.get("stale"):
        draw.rectangle((x, y, x + 44, y + 20), fill=(90, 90, 90))
        draw.text((x + 4, y + 2), label("旧") or "OLD", fill=TEXT, font=font)
    if image.get("seed") is not None:
        draw.rectangle((x, y + height - 20, x + width - 1, y + height - 1), fill=(0, 0, 0))
        draw.text((x + 4, y + height - 19), str(image["seed"]), fill=MUTED, font=font)


def _fonts():
    from PIL import ImageFont

    candidates = [
        "msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc",
        "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, 20), ImageFont.truetype(name, 15), True
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=20), ImageFont.load_default(size=15), False
    except TypeError:  # Pillow < 10.1
        default = ImageFont.load_default()
        return default, default, False
