---
name: style-lab
description: >-
  通过 PromptAtelier Web API 将指定图片或文件夹整理为工作区、自定义画风分组与配方；
  先准备，只有用户指定哪些现有组或配方要测试后，才按原图种子和尺寸做原参重生、配方原图与角色动作测试。
  在要求操作 style-lab、分析图库、批量建配方或测试指定画风配方时使用。
---

# Style Lab：准备与测试

在 PromptAtelier 仓库根目录执行，使用当前 Web 后台。**默认只做第一步，第一步不会生成任何图片，原参重生也留到第二步。** 分析/划分/角色动作的语义取舍由 Agent 做；Web 保存结果、校验、拼接和出图。

## 入口与模式

```powershell
$sl = '.agents/skills/style-lab/scripts/client.py'
uv run python $sl api GET /workspaces
```

- 「整理/处理这些图片、建工作区、分析、分组、提取配方」→ **准备**。完成后给出组/配方清单并停止，不将建配方视为允许测试。
- 「测试工作区 w 的组 g1/g2 或配方 r1/r2」→ **测试**，只展开明确指定的对象。用户明确指定全部已准备配方时可以全选；仅有路径而没有选定已建对象，先完成准备并列清单。
- 用户在第二步已指定范围后，直接预览并执行该范围，无需逐张再确认。仅预览请求不开始计划。

后台按 `--server`、`PROMPTATELIER_URL`、`runtime/dev_web.json`、`http://127.0.0.1:53211` 定位；`--server` 在子命令前。连接正确后台，不另起不同配置的服务；远程路径必须能由后台读取。

首次准备读 [references/analysis-rules.md](references/analysis-rules.md) 和 [references/workflow-api.md](references/workflow-api.md)。旧单图 API、字段与编辑方式按需读 [references/api.md](references/api.md)。不要以旧文档的单图生图入口代替新的阶段边界。

## 第一步：工作区、自定义分组、配方

1. 校验指定路径，沿用用户分组方式；默认每文件夹一个工作区、散图合成图片组。先查 `/workspaces`，按路径/记录复用；图片组 POST 每次新建，恢复时不要重复提交。
2. `POST /workspaces` 后，分页读 `/workspaces/{w}/analysis-context?offset=0&limit=20`。结合原图完整元数据、现有自动分组和必要的图片检查分析。不要一次把大图库所有提示词塞入上下文；有 `next_offset` 就继续取。无 LLM 也能继续分析，tag 分类任务不是生图。
3. 按分析规则建立稳定家族及子组，记录名字、成员、代表图、证据强度与理由。自定义组与自动组独立；自动 `g1` 等 id 会漂移，不能作为自定义组身份。保留人工锁定的组与成员，重新分析时提出建议，不解除锁定或覆盖。
4. 从代表图 `POST /recipes` 带 `draft:true` 取完整配方草稿。把画师栈、风格、质量/媒介分入 prefix/suffix，内容留在 subject/对应 captions。保留权重、负面、全部角色与位置、模型、参数、vibe 和 flags（包括 `not_quailty_prompts`）。画风区为空的初始草稿不能算完成提取。
5. 组装完整配方，设 `source_group:{kind:custom,id:cg_...}`、`stage:edit, locked:true`、`preparation:{status:ready}`。缺参考图/底图、元数据不全、划分未完成等改为 `needs_review`，写原因，不能谎称可正常复现。宽高、种子、张数不写进画风 params。
6. 用 `/recipes/preview` 检查实际主提示词与全部 captions。不要按普通逗号拆权重组；按块移动并保留原 id/来源，重写块标 manual。不自行加质量词、男角色 caption 或换模型。
7. 保存请求到 `runtime/stylelab/agent/<任务名>/prepare.json`，包含稳定任务 id、当前 revision 的 custom_groups、完整 recipes 与分析总结，调用 `client.py prepare`。后端只校验、建组/配方，不出图；记录逐项结果。partial 时用相同请求恢复，只补未完成配方，不盲建新 id。
8. 交付每工作区的组/配方名称、id、代表图、分析理由、待处理项。告诉用户这些配方尚未测试，等其指定对象后进入第二步。**此处结束；不调用 regenerate、generate 或 test-plan start。**

源图只读，PNG/stealth 由现有读取器恢复到内存，不回写、复制图库或建 junction。本项目的分析规则已自包含，不修改 agent-hub 中的原 skill。

## 第二步：只测试指定的组或配方

1. 重新读取指定工作区与配方清单，明确名称对应 id；自定义父组展开其关联配方并按 id 去重。只选择本次指定对象，不扩展到其他组。needs_review/stale/source_missing 单列原因，先处理或跳过，不能默默换源图/随机化。
2. `client.py materials` 读取**当前全局素材架**及应用 exclusions 后的 tags；准备阶段不固定素材。用户本次明确指定素材优先（可先按其要求更新全局选择），不把配方曾用过的 materials 误当当前选择。为空则只测原参和配方原图，说明原因。
3. 从完整基准配方复制测试快照。每配方默认最多 3 个不同角色/动作组合，每组合 1 张；数量遵循用户要求，不扩成笛卡尔积。移除被替换的旧角色/外貌/冲突服装及旧动作冲突，保留其他人物、构图与场景；多角色明确对应，不压成一条 caption。
4. 变体只改测试内容及标签，保留配方 id、source_image_id、画风签名。新增块来源用 `character:<ref>` / `action:<ref>`；materials 记准确卡片及 exclusions，必须与该计划创建时的素材架一致。重写原图块标 manual，不能只在旧内容后堆新词。
5. `POST /test-plans` 带明确 recipe_ids/group_ids 及 variants。计划固化基准/变体、素材、源图指纹和完整内容哈希；创建不出图。检查每项 preview 的主提示词/captions、模型、种子与生成尺寸和预计数量。`awaiting_content` 表示缺变体内容，不能直接开始；补齐后新建计划。
6. 用户已要求测试时，摘要说明范围与张数，再 `/test-plans/{id}/start` 或 `client.py start-plan`。计划串行执行原参 → 配方原图内容 → 素材变体，共用原参结果可复用。所有图均用原图种子/生成尺寸；不通过 count>1 做不同内容，否则种子会递增。
7. 轮询同一计划。原参失败或 drift/param_diff 默认暂停该源图后续项，先诊断；其余源图可继续。用户理解差异并明确同意继续时，才新建 `continue_on_drift:true` 的计划。配方图 `verdict=reference` 不能当作原参 match。
8. 看原图及生成结果，结合参数/提示词差异报告三类覆盖与问题。给出计划 id、组/配方 id、run、绝对图片路径和少量代表图。远程结果用工作区 file 接口取到本地后查看。

**测试快照不 PUT 回保存配方，无需临时改名、反复保存或恢复基准。** 测试计划会检测同版本下的主体修改，409 时读取变化并重建计划，不能强盖其他人编辑。

## 恢复与限制

```powershell
uv run python $sl prepare <workspace_id> --body-file runtime/stylelab/agent/task/prepare.json
uv run python $sl start-plan <workspace_id> <plan_id>
uv run python $sl wait-plan <workspace_id> <plan_id> --timeout 45
```

- wait_timed_out 只是等待结束，后台继续运行；继续查原计划，不重新提交。网络写请求超时先查 preparation/plan/run，已有 id 继续恢复。
- 重复开始同一成功/运行中计划不会重提；恢复只补未完成结果，有效同参结果复用。不要 force 整批重出或自动遍历模型/种子/消融。
- 新图片重扫后进未分组；组改名/重排不重建配方。修改分组不隐式重写已有配方，需要重新提取时明确更新或新建。
- 不自动导出 artist、覆盖旧 preset，或修改 agent-hub 原 skill。只有明确要求这些扩展时另行处理。
