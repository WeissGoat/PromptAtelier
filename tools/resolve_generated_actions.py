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
INPUT_STRING = r"g:\GoogleDrive\NovelAI_Images\20261022\00228_akuma_homura_00_start_20260505_俯趴露足忍者_3star_d9405f32 g:\GoogleDrive\NovelAI_Images\20261016\9e6d4957_17_6_2_0c91f657 g:\ai_auto\drive-download-20261020T171041Z-1-001\00091_1adanbooru_akemi_homura_暁美_魔法少女_-_快捷方式_03_cum_20260523_黄夹克后入_4c25af09 g:\GoogleDrive\NovelAI_Images\20261017\00113_danbooru_illyasviel_von_einzbern_見_魔法少女_-_快捷方式_02_core_20260_4dfb2ecd g:\GoogleDrive\NovelAI_Images\20261017\00123_1adanbooru_akemi_homura_暁美_魔法少女_-_快捷方式_01_pre_20260604_狐娘催眠掰_42477ea9 g:\GoogleDrive\NovelAI_Images\20261023\00127_1adanbooru_kaname_madoka_鹿目_魔法少女_-_快捷方式_02_core_龙娘群交轮奸_4edb460e g:\GoogleDrive\NovelAI_Images\20261023\00150_ultimate_madoka_02_core_2026-07-14_147173188_04_床上侧卧深肤男交合_f48ae1af g:\GoogleDrive\NovelAI_Images\20261023\00151_ultimate_madoka_02_core_2026-07-14_147173188_12_床上裸体异种族侧卧交合指_3998788c g:\GoogleDrive\NovelAI_Images\20261023\00159_ultimate_madoka_02_core_黑皮深插_4star_1f27e100 g:\GoogleDrive\NovelAI_Images\20261025\00172_1adanbooru_akemi_homura_暁美_魔法少女_-_快捷方式_02_core_抓胸后入_615ab539 g:\GoogleDrive\NovelAI_Images\20261022\00236_akuma_homura_02_core_20260524_沙发束缚口交强奸_ee45eec9 g:\GoogleDrive\NovelAI_Images\20261017\00299_danbooru_illyasviel_von_einzbern_見_魔法少女_-_快捷方式_00_start_2026_5d5d00c7 g:\GoogleDrive\NovelAI_Images\20261025\00306_akuma_homura_03_cum_20260630_0042_口交_77105d15 g:\GoogleDrive\NovelAI_Images\20261025\00357_akuma_homura_02_core_20260504_双女指交掰穴_1star_30802e47 g:\GoogleDrive\NovelAI_Images\20261025\00446_ultimate_madoka_01_pre_2026-10-11_150701062_Momo_Ai_06_双女一男床_fddab563 g:\GoogleDrive\NovelAI_Images\20261017\00467_danbooru_1213_konjiki_no_yami_金色_闇_01_pre_20260531_红手套肥男舌吻_959e4cc1 g:\GoogleDrive\NovelAI_Images\20261017\00484_1adanbooru_kaname_madoka_鹿目_魔法少女_-_快捷方式_00_start_20260718_01_3b9e52fa g:\GoogleDrive\NovelAI_Images\20261017\00498_akuma_homura_02_core_图书馆站立捉奸_5star_62e20554 g:\GoogleDrive\NovelAI_Images\20261017\00523_4danbooru_0_krul_tepes_克鲁鲁_-_快捷方式_04_post_自慰后交合_79ef7c42 g:\GoogleDrive\NovelAI_Images\20261017\00531_akuma_homura_03_cum_20260526_kimono_cowgirl_after_5362e589 g:\GoogleDrive\NovelAI_Images\20261017\00557_4danbooru_0_krul_tepes_克鲁鲁_-_快捷方式_02_core_20260902_2153_校服胶带_dd6fa303 g:\GoogleDrive\NovelAI_Images\20261019\00575_1adanbooru_kaname_madoka_鹿目_魔法少女_-_快捷方式_02_core_FFM站立双飞_b9e1a112 g:\GoogleDrive\NovelAI_Images\20261017\00584_2danbooru_fate_testarossa_-_快捷方式_01_pre_20260504_森林强暴MMF反抗_4_478b64f9 g:\GoogleDrive\NovelAI_Images\20261017\00724_4八神疾风_-_快捷方式_-_副本_01_pre_20260523_萝莉女上研磨敞衣_4star_4ca0e21e g:\GoogleDrive\NovelAI_Images\20261017\00726_4八神疾风_-_快捷方式_-_副本_02_core_抓胸后入_a366d73c g:\GoogleDrive\NovelAI_Images\20261017\00763_danbooru_illyasviel_von_einzbern_見_魔法少女_-_快捷方式_03_cum_202606_19e64e67 g:\ai_auto\20260906\blackboard_tags_machine_1788673739_3_1788675710 g:\ai_auto\20260906\blackboard_tags_machine_1788673739_3_1788676192 g:\GoogleDrive\NovelAI_Images\20260907\blackboard_tags_machine_1788746445_3_1788746531 g:\GoogleDrive\NovelAI_Images\20260921\blackboard_tags_machine_1789956032_3_1789961023 g:\GoogleDrive\NovelAI_Images\20260921\blackboard_tags_machine_1789956032_3_1789963507 g:\GoogleDrive\NovelAI_Images\20260921\blackboard_tags_machine_1789956032_3_1789973340 g:\GoogleDrive\NovelAI_Images\20260921\blackboard_tags_machine_1789984828_3_1789993261 g:\ai_auto\20260926\blackboard_tags_machine_1790402576_3_1790407650 g:\GoogleDrive\NovelAI_Images\20260927\blackboard_tags_machine_1790474439_3_1790478023 g:\GoogleDrive\NovelAI_Images\20260927\blackboard_tags_machine_1790474439_3_1790478130 g:\GoogleDrive\NovelAI_Images\20261007\blackboard_tags_machine_1791307078_3_1791321249 g:\GoogleDrive\NovelAI_Images\20261011\blackboard_tags_machine_1791655266_3_1791674157"
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
