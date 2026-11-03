"""给外部 Agent 的「要求 prompt」（§6）：工具版（在仓库里直接改契约文件）和自包含版（纯对话）。"""

from __future__ import annotations

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

PRINCIPLES = """\
- 先理解定制要求，区分全局改动（背景、服装、语气）和逐帧改动。
- 每帧自己拼出完整提示词：角色身份词通常保留；服装、发型、配饰结合动作的裸露状态（clothing_state）、镜头范围（character_scope）、构图和要求取舍。
- 动作的核心（姿势、构图、表情、互动）优先保留；与要求冲突的环境词、混入的角色/画风词去掉。
- 尽量沿用素材里的原词写法（Web 按字面匹配标记来源）；需要调整时可以改权重或替换。
- 多角色：只有选了多个角色、且定制要求说明了分配方式时，才替换动作中的人物；否则保留动作原词。
- 连续性：同一组里服装和场景保持一致，除非要求变化。
- 新增帧写 source: custom，参考过的动作写进 inspired_by。
- 不要写：画师名、质量前缀（masterpiece 等）、生图参数；不要改素材库的源节点；不要改 front matter 的请求部分。"""


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
        lines.append(f"- 分角色提示词：支持，最多 {profile.multi_character.max} 个；用 ```positive c2 / ```negative c2 写")
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
            "请为下面这份「Agent 拼接契约」写出每一帧的完整提示词。",
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
            f"2. `{cli} contract show {contract_id}{config_arg}` 看请求和已写的帧；`{cli} contract context {contract_id}{config_arg}` 取素材（角色分区词表、动作组各成员的提示词与分类；成员多时加 `--member N` 逐个取）。",
            f"3. 需要新增帧时，用 `{cli} kb search` / `{cli} kb show` 找参考动作（用法见 Skill）。",
            "4. 直接编辑契约文件：在 front matter 之后按帧书写（格式见下）。提示词全部由你拼接。",
            f"5. `{cli} contract check {contract_id}{config_arg}` 没有 error 后，把 front matter 里的 `status: pending` 改成 `status: done`；可以顺便填 `title`（简短中文标题）和 `author`。",
            "",
            "## 帧格式",
            FRAME_FORMAT_GUIDE,
            "",
            "## 原则",
            PRINCIPLES,
            "",
            "## 目标格式要点",
            _format_notes(profile, request["target_format"]),
            "",
        ]
    )


def render_standalone_prompt(detail: dict[str, Any], profile: FormatProfile | None) -> str:
    request = detail["request"]
    sources = detail["sources"]
    parts = [
        "请根据下面的素材和要求，为一组连续的画面写出每一帧的完整图像提示词（danbooru tag 风格）。",
        "只输出帧内容（Markdown，从第一帧的 `## f01` 开始），不要输出其他说明。",
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
            "## 原则",
            PRINCIPLES,
            "",
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
