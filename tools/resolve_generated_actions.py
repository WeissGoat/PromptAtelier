#!/usr/bin/env python3
"""批量解析旧版图片和新版任务目录对应的 Action 节点。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# 允许直接从 IDE 运行此文件，不依赖当前工作目录。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# ==================== 只需要修改这一区域 ====================
INPUT_STRING = r"g:\GoogleDrive\NovelAI_Images\20261017\00220_ultimate_madoka_03_cum_20260523_黄夹克后入潮吹_4star_fd82e980 g:\GoogleDrive\NovelAI_Images\20261108\00001_1adanbooru_akemi_homura_暁美_魔法少女_-_快捷方式_01_pre_20261007_2_04_3af30156 g:\GoogleDrive\NovelAI_Images\20261113\00018_1adanbooru_akemi_homura_暁美_魔法少女_-_快捷方式_02_core_20260524_哥特萝莉_cbb012a6 g:\GoogleDrive\NovelAI_Images\20261105\00025_1adanbooru_kaname_madoka_鹿目_魔法少女_-_快捷方式_02_core_20260507_床上腿_7b2369fd g:\GoogleDrive\NovelAI_Images\20261108\00028_1adanbooru_kaname_madoka_鹿目_魔法少女_-_快捷方式_02_core_公主抱把尿_2star_1a6520e6 g:\GoogleDrive\NovelAI_Images\20261105\00098_1adanbooru_akemi_homura_暁美_魔法少女_-_快捷方式_02_core_20260524_哥特萝莉_92489f39 g:\GoogleDrive\NovelAI_Images\20261101\00125_ultimate_madoka_01_pre_20260718_1557_仰卧指入口中_57f87eff g:\GoogleDrive\NovelAI_Images\20261110\00189_akuma_homura_02_core_电车蓝发舔乳群交_41771e06 g:\GoogleDrive\NovelAI_Images\20261101\00209_ultimate_madoka_03_cum_20260523_黄夹克后入潮吹_4star_5e54410f"
INPUT_PATHS: list[str] = [
    # r"G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961",
    # r"G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe",
]
INPUT_PATHS.extend(INPUT_STRING.split())
# 可选：paths / table / json
OUTPUT_MODE = "paths"

# False：相同 Action 只输出一次；True：保留每个输入图片/任务的解析记录。
PER_INPUT = False

# True：遇到 fallback、歧义、未解析或读取错误时以退出码 1 结束。
STRICT = False

# 二选一：
# 1. 使用配置中的 legacy.design_root：CONFIG_PATH = None
# 2. 临时指定提示词库：DESIGN_ROOT = r"F:\my_project\new\tags_machine\design"
CONFIG_PATH: str | None = None
DESIGN_ROOT: str | None = None

# ==================== 配置区域结束 ====================


def main() -> int:
    from tags_machine_core.tools.action_resolver.cli import (
        STRICT_FAILURE_STATUSES,
        _print_paths,
        _print_table,
        _resolve_design_root,
    )
    from tags_machine_core.tools.action_resolver.resolver import (
        deduplicate_resolved_actions,
        resolve_generated_actions,
    )

    clean_inputs = [p for p in INPUT_PATHS if p.strip()]
    if not clean_inputs:
        print("请先在 INPUT_PATHS 中填写要解析的图片或目录。", file=sys.stderr)
        return 2
    if CONFIG_PATH and DESIGN_ROOT:
        print("CONFIG_PATH 和 DESIGN_ROOT 只能配置一个。", file=sys.stderr)
        return 2
    if OUTPUT_MODE not in {"paths", "table", "json"}:
        print(f"OUTPUT_MODE 无效：{OUTPUT_MODE!r}，可选 paths/table/json。", file=sys.stderr)
        return 2

    design_root = _resolve_design_root(
        config_path=Path(CONFIG_PATH) if CONFIG_PATH else None,
        design_root=Path(DESIGN_ROOT) if DESIGN_ROOT else None,
    )
    results = resolve_generated_actions(clean_inputs, design_root=design_root)

    # 1. 前面输出每个路径对应的 Action 节点
    for path_str in clean_inputs:
        target_path = Path(path_str).expanduser()
        if not target_path.exists():
            print(f"{path_str} -> [路径不存在]")
            continue
        try:
            resolved_target = target_path.resolve()
        except OSError:
            resolved_target = target_path

        matched = [
            r
            for r in results
            if r.evidence.input_path == resolved_target
            or resolved_target in r.evidence.input_path.parents
        ]
        valid = [r for r in matched if r.relative_path]
        actions = list(
            dict.fromkeys(
                os.path.basename(str(Path(r.relative_path)))
                for r in valid
            )
        )
        if actions:
            act_str = ", ".join(actions)
        elif matched:
            first_fail = matched[0]
            act_str = f"[{first_fail.status}] {first_fail.reason}".strip()
        else:
            act_str = "[未找到匹配内容]"
        print(f"{path_str} -> {act_str}")

    print()

    # 2. 后面接之前的打印
    display_results = (
        results
        if PER_INPUT
        else [
            item
            for item in deduplicate_resolved_actions(results)
            if item.status != "missing_action"
        ]
    )
    if OUTPUT_MODE == "json":
        import json

        print(
            json.dumps(
                [item.as_dict() for item in display_results],
                ensure_ascii=False,
                indent=2,
            )
        )
    elif OUTPUT_MODE == "table":
        _print_table(display_results)
    else:
        _print_paths(display_results)

    if STRICT and any(item.status in STRICT_FAILURE_STATUSES for item in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
