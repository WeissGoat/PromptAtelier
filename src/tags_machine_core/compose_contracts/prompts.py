"""给外部 Agent 的「要求 prompt」（§6）：工具版（在仓库里直接改契约文件）和自包含版（纯对话）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .profiles import FormatProfile


FRAME_FORMAT_GUIDE = """\
每帧一个二级标题小节，帧 id 用 f01、f02…，新增帧可用 f02b 这样插在中间：

## f01 帧标题（简短中文）
source: <动作组成员 ref>          # 自定义帧写 source: custom
inspired_by: <参考动作 ref>        # 可选，仅自定义帧；多个用逗号分隔
characters: c1                     # 本帧出现的角色
size: portrait                     # 可选：portrait / landscape / square

```positive
完整正向提示词，可以随意换行分组
```

```negative
本帧额外的负面提示词（可选）
```

代码块之外的文字都算本帧备注。"""


def writing_guide() -> str:
    """与 compose-contract-author Skill 共用一份编写与复核规范。"""
    return Path(__file__).with_name("writing_guide.md").read_text(encoding="utf-8").strip()


def existing_plan(detail: dict[str, Any]) -> list[str]:
    preamble = str(detail.get("preamble") or "").strip()
    return ["## 已有计划区（修改时一并参考）", preamble, ""] if preamble else []


MULTI_CHARACTER_GUIDE = """\
本契约有多个角色（c1、c2…）。画面里有两个及以上角色的帧，用分角色代码块写：

- ```positive：画面共用的部分——人数 tag（2girls 等）、互动、构图镜头、背景环境。不写某一个角色专属的词。
- ```positive c1 / ```positive c2：这个角色自己的全部内容——性别词（girl / boy）、身份词（角色名、发色瞳色）、服装，以及动作里属于这个人的那部分（姿势、表情、谁对谁做什么）。
- ```negative c1 / ```negative c2：可选，只对这个角色生效的负面词。
- 帧的 characters: 列出本帧出现的角色，每个都要有自己的 ```positive cN。
- 动作素材里的行内写法 `::character A: … ::`、`::character B: … ::`：把 A、B 里的词挪进对应的 cN 块，主提示词里删掉这一段，不要两种写法混用。
  默认 A→c1、B→c2…；定制要求说明了谁做什么时，按要求对应。块里原来的角色名、发色等换成该角色自己的身份词。
- 只有一个角色出现的帧（如单人特写），可以只写 ```positive，不用分块。

示例：

```positive
2girls, yuri, sitting on lap, night, classroom, window
```

```positive c1
girl, akemi_homura, black_hair, long_hair, purple_eyes, sitting behind, hands on another's waist, smile
```

```positive c2
girl, kaname_madoka, pink_hair, twintails, pink_eyes, sitting on lap, open mouth, blush
```"""


def multi_character_guide(detail: dict[str, Any], profile: FormatProfile | None) -> list[str]:
    """契约有多个角色、且格式支持分角色提示词时，给出「多角色」一节。"""
    characters = (detail.get("request") or {}).get("nodes", {}).get("characters") or {}
    if len(characters) < 2 or profile is None or not profile.multi_character.supported:
        return []
    return ["## 多角色", MULTI_CHARACTER_GUIDE, ""]


def _format_notes(profile: FormatProfile | None, target_format: str) -> str:
    if profile is None:
        return f"- 目标格式：{target_format}（没有找到对应的格式 profile）"
    weights = {
        "brace": "{tag} 加强 / [tag] 减弱",
        "numeric": "1.2::tag:: 数值权重（可包住多个 tag）",
        "paren": "(tag:1.2) / (tag)",
    }
    lines = [
        f"- 目标格式：{profile.label or profile.id}（{profile.id}）",
        f"- 分隔符：「{profile.separator}」；换行{'视为分隔符' if profile.newline == 'separator' else '原样保留'}",
        "- 权重写法：" + "；".join(weights[s] for s in profile.weight.syntaxes if s in weights)
        + (f"，优先 {weights.get(profile.weight.preferred, profile.weight.preferred)}" if profile.weight.preferred else ""),
        f"- 中文：{'可以' if profile.language.allow_cjk else '不要在提示词里写中文'}",
    ]
    if profile.length.max_tokens:
        scope = "主提示词加各角色提示词合计" if profile.length.shared_with_characters else "每帧正向"
        lines.append(
            f"- 长度：{scope}不超过 {profile.length.max_tokens} token（{profile.length.tokenizer} 分词，和官网计数一致）；"
            "画风和质量词出图时还会再加，最好留出余量。contract check 的 tokens 字段给出每帧的实际数"
        )
    if profile.multi_character.supported:
        lines.append(
            f"- 分角色提示词：支持，最多 {profile.multi_character.max} 个；每个角色一个 ```positive cN（c1、c2…），主提示词只写画面共用的部分"
        )
    else:
        lines.append("- 分角色提示词：不支持，所有角色写在同一个 positive 里")
    return "\n".join(lines)


def _request_lines(detail: dict[str, Any]) -> list[str]:
    request = detail["request"]
    nodes = request["nodes"]
    sources = detail["sources"]
    group = sources.get("action_group") or {}
    lines = [f"- 动作组：{nodes['action_group']['ref'] if nodes.get('action_group') else '（未选）'}（{group.get('member_count', 0)} 个成员）"]
    for key, entry in (nodes.get("characters") or {}).items():
        name = (sources.get("characters") or {}).get(key, {}).get("name") or ""
        lines.append(f"- 角色 {key}：{entry['ref']}" + (f"（{name}）" if name else ""))
    for role, label in (("clothing", "服装"), ("background", "背景")):
        if nodes.get(role):
            lines.append(f"- {label}：{nodes[role]['ref']}")
    options = request.get("options") or {}
    lines.append(
        "- 选项：保持动作组顺序 {keep}；允许新增帧 {allow}（最多 {max} 帧）".format(
            keep="是" if options.get("keep_order", True) else "否",
            allow="是" if options.get("allow_new_frames", True) else "否",
            max=options.get("max_new_frames", 2),
        )
    )
    requirements = (request.get("requirements") or "").strip()
    lines.append("- 定制要求：" + ("\n" + _quote(requirements) if requirements else "无（按动作组原样逐帧拼接角色）"))
    return lines


def _quote(text: str) -> str:
    return "\n".join(f"  > {line}" if line.strip() else "  >" for line in text.splitlines())


def render_tools_prompt(
    detail: dict[str, Any],
    profile: FormatProfile | None,
    *,
    contract_path: str,
    cli: str,
    config_arg: str,
    skill_path: str,
    project_root: str,
) -> str:
    request = detail["request"]
    contract_id = request["id"]
    return "\n".join(
        [
            "你是这份「Agent 拼接契约」的主 Agent：先读要求和素材，与用户讨论方案，经用户确认后再写正式计划与每帧完整提示词；会话中已有明确确认的方案直接沿用。",
            "",
            f"契约文件：{contract_path}",
            f"契约 id：{contract_id}",
            "",
            "## 请求",
            *_request_lines(detail),
            "",
            "## 步骤",
            f"命令都在 PromptAtelier 仓库目录（{project_root}）下执行。",
            f"1. 先读 Skill：{skill_path}",
            f"2. `{cli} contract show {contract_id}{config_arg}` 看请求和已写的帧；`{cli} contract context {contract_id} --summary{config_arg}` 先看全组结构（每个成员的分类），"
            f"再用 `--members 1-20` 分段取提示词（输出很长，不要一次取全部）。已写的帧多时 `contract show --summary` / `--frames f01-f30` 分段看。",
            f"3. 先提出创作方案，与用户讨论并等待确认。需要新增帧时，用 `{cli} kb search` / `{cli} kb show` 找参考动作（用法见 Skill）。",
            "4. 确认后落实计划区；写提示词前，按下方规范读完目标格式对应的已有提示词 Skill 及其要求的参考资料，再按帧书写。提示词全部由你拼接。",
            f"5. `{cli} contract check {contract_id}{config_arg}` 修到没有 error；有状态变化规划时，填写下方「提示词复核派单模板」，交子 Agent 逐帧核实最终提示词、纵向回看整组。主 Agent 退回空泛赞美的报告补查，逐项裁决后再将 `status: pending` 改为 `status: done`。可填 `title` 和 `author`。"
            " warn 里的 identity_anchor（帧里没有角色身份词）和 frame_novelty（和上一帧几乎相同）要逐条处理。",
            "6. 需要测试契约或沟通需求时，先询问用户指定画风（用户已指定则沿用），不要自行挑选。",
            f"   用 `{cli} contract artists --query <搜索词>` 查画风 ref；选少量代表帧先 `{cli} contract generate {contract_id} --artist <用户指定的ref> --frames f01 --dry-run`，",
            f"   正式改词后，通常按下方修订流程先复核当前版本，再去掉 --dry-run 按授权提交。异步任务用 `{cli} contract job <任务id> --wait` 查结果；讨论例图可用草稿。",
            "   生图命令连接正在运行的 PromptAtelier 后台（默认 runtime/dev_web.json，也可 --server 或 PROMPTATELIER_URL），使用该后台的配置和契约目录。默认复用相同参数；要新候选时加 --force。",
            f"7. 出图后用 `{cli} contract review {contract_id} --sheets{config_arg}` 准备材料，填写「图片复核派单模板」，把本轮联系表和原图交给图片复核子 Agent。主 Agent 默认只读报告。有待修问题就据证据改词，重新审词、修补、复核最终版，按授权重出后再交图片复核子 Agent 查验。",
            "",
            *existing_plan(detail),
            writing_guide(),
            "",
            "## 帧格式",
            FRAME_FORMAT_GUIDE,
            "",
            *multi_character_guide(detail, profile),
            "## 目标格式要点",
            _format_notes(profile, request["target_format"]),
            "",
        ]
    )


def render_standalone_prompt(detail: dict[str, Any], profile: FormatProfile | None) -> str:
    request = detail["request"]
    sources = detail["sources"]
    parts = [
        "你是这份「Agent 拼接契约」的主 Agent。先根据下面的素材和要求提出创作方案，与用户讨论并等待确认，再为连续画面写正式计划与每帧完整图像提示词（danbooru tag 风格）。会话中已有明确确认的方案直接沿用。",
        "方案确认并完成写作后，交付计划区和全部帧组成的契约正文，将它单独放在一个 Markdown 代码块中；导入时只复制该块内容。复核报告与主 Agent 裁决另行交付，不拼进契约正文。",
        "",
        "## 请求",
        *_request_lines(detail),
        "",
        "## 素材",
    ]
    for key, character in (sources.get("characters") or {}).items():
        parts.append(f"### 角色 {key}：{character.get('name') or character.get('ref')}")
        for section, tags in (character.get("sections") or {}).items():
            parts.append(f"- {section}: {', '.join(tags)}")
        if character.get("negative"):
            parts.append(f"- negative: {', '.join(character['negative'])}")
        parts.append("")
    group = sources.get("action_group")
    if group:
        parts.append(f"### 动作组 {group['name']}（按顺序）")
        for member in group.get("members") or []:
            parts.append(f"#### #{member['index']} {member['title']}")
            parts.append(f"- ref: {member['ref']}")
            classify = member.get("classify") or {}
            if classify:
                parts.append("- 分类: " + "；".join(f"{k}={_flat(v)}" for k, v in classify.items()))
            if member.get("character_scope"):
                parts.append(f"- 镜头范围 character_scope: {member['character_scope']}")
            if member.get("clothing_state"):
                parts.append(f"- 着装状态 clothing_state: {member['clothing_state']}")
            parts.append("- 正向:")
            parts.append("```")
            parts.append(member.get("positive") or "")
            parts.append("```")
            if member.get("negative"):
                parts.append(f"- 负面: {member['negative']}")
            parts.append("")
    for role, label in (("clothing", "服装"), ("background", "背景")):
        node = sources.get(role)
        if node:
            parts.append(f"### {label}：{node.get('name') or node.get('ref')}")
            for section, tags in (node.get("sections") or {}).items():
                parts.append(f"- {section}: {', '.join(tags)}")
            parts.append("")
    parts.extend(
        [
            "## 帧格式",
            FRAME_FORMAT_GUIDE,
            "",
            "source 写上面动作组成员的 ref；新增帧写 source: custom（这种情况下没有工具检索参考动作，inspired_by 可省略）。",
            "",
            *existing_plan(detail),
            writing_guide(),
            "",
            *multi_character_guide(detail, profile),
            "## 目标格式要点",
            _format_notes(profile, request["target_format"]),
            "",
        ]
    )
    return "\n".join(parts)


def _flat(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value) or "-"
    if isinstance(value, dict):
        return ";".join(f"{k}:{_flat(v)}" for k, v in value.items())
    return str(value)
