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
- 每帧自己拼出完整提示词：服装、发型、配饰结合动作的裸露状态（clothing_state）、镜头范围（character_scope）、构图和要求取舍。
- 身份锚点：帧里出现的角色，至少保留角色名或发色瞳色之一；特写、局部镜头也一样，再加一个当前服装、道具或标志物。删光身份词出图会换人。
- 动作的核心（姿势、构图、表情、互动）优先保留；与要求冲突的环境词、混入的角色/画风词去掉。
- 来源冲突：动作素材里的状态词（站 / 躺、穿着 / 裸露、有没有口塞绳索等）只在和本帧状态一致时保留；定制要求和状态推进优先于素材原词。
- 尽量沿用素材里的原词写法（Web 按字面匹配标记来源）；需要调整时可以改权重或替换。
- 多角色：选了多个角色时，按下面「多角色」一节用分角色代码块写；人物怎么对应以定制要求为准。
- 连续性是一条状态链，不只是服装和场景：时间与场景、服装阶段、姿势与位置、道具与身体痕迹、出场人物与关系、镜头 / POV 都要前后衔接。
  进入新状态后不要无故回退（衣服不会自己穿回去，绑住的手不会自己松开）；状态变化要在画面里看得出原因，没有承载帧时加过渡帧。
- 相邻帧至少改变一项：机位、景别、姿势、表情、互动、服装状态、道具状态。只换 seed 的重复帧合并或删掉；有意保留时在帧备注里写明。
- 新增帧写 source: custom，参考过的动作写进 inspired_by。
- 写完后按帧顺序复查一遍：服装、姿势与位置、道具、人数与关系、POV 与镜头方向有没有跳变或回退。
- 不要写：画师名、质量前缀（masterpiece 等）、生图参数；不要改素材库的源节点；不要改 front matter 的请求部分。"""


PLANNING_GUIDE = """\
定制要求里有叙事或状态变化时，先把动作组当作素材池，而不是现成的分镜：

1. 从定制要求里提取：全局硬要求；叙事起点、终点和必须出现的转折；需要保持或按阶段变化的状态；明确不要的表现。
2. 把状态拆成独立维度：时间与场景、角色身份与外观锚点、服装阶段、姿势与空间位置、表情与情绪阶段、道具与身体痕迹、出场人物与关系、镜头 / POV。
3. 先定镜头计划再写帧：按叙事阶段给成员分组（`contract context --summary` 能看到每个成员的 phase / pose / cast 分类），
   合并重复或功能相同的成员，{order}；状态变化没有自然承载帧时新增过渡帧（受 max_new_frames 限制）。
4. 计划可以写在 front matter 之后、第一帧之前的说明文字里（不是帧，不会提交生图）。
   有意合并或舍弃的成员，contract check 的 coverage 会给 warn，在相关帧的备注里说明即可。"""


def planning_guide(detail: dict[str, Any]) -> list[str]:
    """定制要求不为空时给出「先规划」一节；没有要求时就是按动作组逐帧拼角色，不需要。"""
    request = detail.get("request") or {}
    if not (request.get("requirements") or "").strip():
        return []
    keep = (request.get("options") or {}).get("keep_order", True)
    order = "保持动作组原顺序（keep_order: true）" if keep else "按叙事需要调整顺序（keep_order: false）"
    return ["## 先规划", PLANNING_GUIDE.format(order=order), ""]


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
            f"2. `{cli} contract show {contract_id}{config_arg}` 看请求和已写的帧；`{cli} contract context {contract_id} --summary{config_arg}` 先看全组结构（每个成员的分类），"
            f"再用 `--members 1-20` 分段取提示词（输出很长，不要一次取全部）。已写的帧多时 `contract show --summary` / `--frames f01-f30` 分段看。",
            f"3. 需要新增帧时，用 `{cli} kb search` / `{cli} kb show` 找参考动作（用法见 Skill）。",
            "4. 直接编辑契约文件：在 front matter 之后按帧书写（格式见下）。提示词全部由你拼接。",
            f"5. `{cli} contract check {contract_id}{config_arg}` 没有 error 后，把 front matter 里的 `status: pending` 改成 `status: done`；可以顺便填 `title`（简短中文标题）和 `author`。"
            " warn 里的 identity_anchor（帧里没有角色身份词）和 frame_novelty（和上一帧几乎相同）要逐条处理。",
            "6. 需要测试契约或沟通需求时，先询问用户指定画风（用户已指定则沿用），不要自行挑选。",
            f"   用 `{cli} contract artists --query <搜索词>` 查画风 ref；选少量代表帧先 `{cli} contract generate {contract_id} --artist <用户指定的ref> --frames f01 --dry-run`，",
            f"   再去掉 --dry-run，按需加 --wait 提交；异步任务用 `{cli} contract job <任务id> --wait` 查结果与图片路径。无需 status: done，讨论中的草稿也能出示例。",
            "   生图命令连接正在运行的 PromptAtelier 后台（默认 runtime/dev_web.json，也可 --server 或 PROMPTATELIER_URL），使用该后台的配置和契约目录。默认复用相同参数；要新候选时加 --force。",
            f"7. 出图后复核用 `{cli} contract review {contract_id} --sheets{config_arg}`（见 compose-contract-review Skill），打开图片或联系表后再给用户结论。",
            "",
            *planning_guide(detail),
            "## 帧格式",
            FRAME_FORMAT_GUIDE,
            "",
            *multi_character_guide(detail, profile),
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
    planning = planning_guide(detail)
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
            *planning,
            *multi_character_guide(detail, profile),
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
