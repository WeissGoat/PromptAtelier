#!/usr/bin/env python3
"""批量解析旧版图片和新版任务目录对应的 Action 节点。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# 允许直接从 IDE 运行此文件，不依赖当前工作目录。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ==================== 只需要修改这一区域 ====================
INPUT_STRING = r"g:\ai_auto\20260815\blackboard_tags_machine_1786798016_3_1786798078 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785443536 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785437082 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785354471 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786879110 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786879249 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786879709 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786881654 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786882150 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786884284 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786884434 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786884978 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786857763 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786859446 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786861189 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786892513 g:\ai_auto\20260816\blackboard_tags_machine_1786845842_3_1786897746 g:\GoogleDrive\NovelAI_Images\20260816\blackboard_tags_machine_1786812620_3_1786818498 g:\GoogleDrive\NovelAI_Images\20260816\blackboard_tags_machine_1786812620_3_1786820386 g:\GoogleDrive\NovelAI_Images\20260816\blackboard_tags_machine_1786812620_3_1786820992 g:\GoogleDrive\NovelAI_Images\20260816\blackboard_tags_machine_1786812620_3_1786825225 g:\GoogleDrive\NovelAI_Images\20260822\blackboard_tags_machine_1787335236_3_1787352367 g:\GoogleDrive\NovelAI_Images\20260822\blackboard_tags_machine_1787335236_3_1787355119 g:\GoogleDrive\NovelAI_Images\20260822\blackboard_tags_machine_1787335236_3_1787355136 g:\GoogleDrive\NovelAI_Images\drive-download-20260725T161355Z-1-001\blackboard_tags_machine_1784916032_3_1784932850 g:\ai_auto\20260726\blackboard_tags_machine_1785040602_3_1785052157 g:\ai_auto\20260727\blackboard_tags_machine_1785152022_3_1785152364 g:\ai_auto\20260726\blackboard_tags_machine_1785040602_3_1785041222 g:\ai_auto\20260726\blackboard_tags_machine_1785056157_3_1785063159 g:\GoogleDrive\NovelAI_Images\20260724\blackboard_tags_machine_1784829630_3_1784829884 g:\ai_auto\20260726\blackboard_tags_machine_1785056157_3_1785061364 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785349249 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785350258 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785426988 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785424856 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785441517 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785442303 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785442841 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785449402 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785449515 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785455514 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785456128 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785456940 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785457433 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785457450 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785457501 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785457535 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785457712 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785458834 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785459144 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785459162 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785459222 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785351351 g:\ai_auto\20260730\blackboard_tags_machine_1785424387_3_1785459911 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785352323 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785352529 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785352940 g:\ai_auto\20260808\blackboard_tags_machine_1786192446_3_1786194417 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785354101 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785355064 g:\ai_auto\20260809\blackboard_tags_machine_1786246084_3_1786248103 g:\ai_auto\20260809\blackboard_tags_machine_1786246084_3_1786248136 g:\ai_auto\20260809\blackboard_tags_machine_1786246084_3_1786250099 g:\ai_auto\20260809\blackboard_tags_machine_1786246084_3_1786250977 g:\GoogleDrive\NovelAI_Images\20260730\blackboard_tags_machine_1785348028_3_1785355801"
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
