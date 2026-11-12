---
name: style-lab
description: >-
  通过 PromptAtelier Web 的 Style Lab API 处理指定图片或文件夹：建立一个或多个工作区，
  划分画风配方，原参重生，再以原图种子和尺寸测试配方的原图内容及当前选中的角色、动作。
  在用户要求自动操作 style-lab、批量建工作区/配方或画风复刻测试时使用。
---

# Style Lab 画风复刻与测试

在 PromptAtelier 仓库根目录执行。使用正在运行的 Web 后台，结果直接出现在 Style Lab 的工作区、配方和出图历史中。**画风划分、角色与动作的语义取舍由 agent 完成**；存储、拼接、参数恢复、出图和对照交给现有 API。

## 入口

```powershell
$sl = '.agents/skills/style-lab/scripts/client.py'
uv run python $sl api GET /workspaces
uv run python $sl materials --output runtime/stylelab/agent/materials.json
```

后台按 `--server`、`PROMPTATELIER_URL`、`runtime/dev_web.json`、`http://127.0.0.1:53211` 的顺序定位；`--server` 放在子命令前。通过 HTTP 操作，无需浏览器、ComfyUI MCP 或其他 skill。连接失败时查看项目启动方式并连接正确后台，不要另起一个使用不同配置的后台。远程后台的来源路径必须是**后台机器能读取的路径**。

`api METHOD /path --body-file request.json --output response.json` 的路径相对于 `/api/style-lab`。JSON 使用 UTF-8，`--output` 保存完整响应；省略时直接输出。HTTP 错误保留状态码和后端错误，退出码 1，不自动重试写请求。

首次创建和出图前，读 [references/api.md](references/api.md) 获取请求体、配方保存和参数语义；实现有变化时以其中列出的源码为准。

## 范围与默认值

- 沿用用户指定的分组、配方数量、样本数和素材。未指定时，每个文件夹各开一个工作区，零散图片合成一个图片组；按稳定画师/风格组合、模型、vibe 状态挑代表图建配方，同风格不逐图复制配方。
- 文件夹有 `origin/` 时后台只扫描它，数据写入该文件夹的 `.stylelab/`。零散图片工作区位于后台 `runtime/stylelab/workspaces/`。源图只读，隐藏元数据由后端读取，无需回写原图、复制图库或建立 junction。
- 用户要求完整流程就执行出图，不必逐张确认。仅要求创建 skill、分析或预览时不出图。不自动导出 artist 或覆盖已有预设。
- 每张代表源图原参重生 **1 张**；每配方原图内容测试 **1 张**；再测当前选中素材的 **至多 3 个不同组合**，每组合 1 张。用户指定数量时按指定量执行。“一些”不扩成整个素材架的笛卡尔积。提交前简述工作区、配方和预计张数。
- 全部默认 `count=1, seed_mode=source, size_mode=source, overrides={}`。变体不换种子或尺寸。**count 多张会递增种子，不能代替同种子的多个内容测试。** 原图尺寸取元数据生成尺寸 `gen_width/gen_height`，不能用放大后的文件尺寸，也不把种子/宽高写进配方 `params`。

## 1. 读取来源与素材，建立工作区

1. 校验路径，列表中找已有工作区，再按分组 `POST /workspaces`。文件夹重开会复用；图片组每次 POST 都新建，恢复任务时复用已记录的 id。记录工作区 id、data_dir、图片 id 与路径。
2. `GET /workspaces/{w}/analysis` 辅助分组，按需取 `/images/{i}` 完整参数。`analysis_job_id` 是可选的分类/翻译任务，无 LLM 仍可继续。相同风格先选一张普通文生图跑通，再按用户要求增加样本。
3. `materials` 命令读取全局 `/shelf`，解析选中卡片并应用 `excluded`；这就是“目前选择的角色和动作”。配方的 `materials` 只记该配方用过的素材，不能代替全局选择。本次请求指定的角色/动作优先；用 `/library/node` 读准确 ref，必要时 `/library/search` 查找。
4. 缺元数据、种子、模型或生成尺寸的图，换同组完整代表图或记录跳过，不能默默随机化。`vibe_missing`、`inpaint`、`img2img`、`director_ref` 单列限制，不编造缺失参考图/底图；其余可用图继续处理。

## 2. 新建并划分配方

1. 每张代表图 `POST /workspaces/{w}/recipes`。在 `runtime/stylelab/agent/<本次任务名>/` 保存完整创建响应、计划和恢复记录；已有目标配方读取续做，用户要求新增才另建。
2. 读完整正负向、全部角色提示词和参数，结合组内共性识别画风。画师栈、画法、质量/媒介等划入 `prefix`/`suffix`；角色、外貌、服装、人数、动作、场景留在 `subject` 或对应 `character.captions`。**主体保留全部词、画风区为空的初始草稿不算提取完成。**
3. 尽量保留原文块、权重、相对顺序与来源；`1.2::a, b::` 等组不能按逗号硬拆。混合内容与风格需重组时检查权重/括号闭合，记录取舍。`dropped` 只放有理由舍弃的词，原图测试内容尽量不变。
4. 保留 `negative`、各角色负面与位置、`use_coords`、原模型、参数、vibe 开关和 flags，特别是 `not_quailty_prompts`（项目键名如此）。不额外加质量词、男角色 caption 或换模型。
5. `POST /recipes/preview` 检查实际主提示词与全部 captions：无重复画风、旧角色残留、人数冲突或丢失角色。完成划分设 `stage=edit, locked=true`，带当前 `base_version/updated_at` 保存；修改已锁画风时显式解锁，测试只改内容。
6. 保存完整基准配方，每个测试变体都从它产生，不在上个变体上叠加。

## 3. 原参重生，再测配方原图内容

1. 代表图 `POST /workspaces/{w}/regenerate`，用原图设置。相同代表图供多个配方时只做一次原参重生。记录 run id，等待完成，读取 item 的 `compare`。
2. `match` 支持链路正常；`drift` 需检查同参漂移原因；`param_diff` 先看具体 diffs，不归咎于配方划分。缺参考素材的限制明确记录，不反复提交同一请求试运气。
3. 已划分配方保留**原图内容**，调用 `/recipes/{r}/generate`，仍用原图种子和尺寸。这一步检查配方拼接，与原参重生是两个不同测试。
4. 打开源图及两张结果，结合提示词/参数差异检查风格和内容。配方图的 `verdict=reference` 是正常行为，不能报告为原参重生的 `match`；相似度也不能代替看图。基准明显有误先修划分并预览，再继续素材测试，不自动无限迭代。

## 4. 测试当前角色与动作

1. 在选中素材内挑少量不同组合，优先覆盖不同角色和动作；两类都有就组合，一类为空只换有的那类，两类都空就报告无选中素材并完成基准测试，不自行选陌生素材。仅有一个组合只出一张，不重复凑数。
2. 从基准复制，**只改** `name`（加测试标签）、`subject`、`character`、`materials`、`notes`；保留源图 id 和画风签名。
3. 换角色时从主体和相关 caption 移除旧身份/外貌及冲突服装，保留构图、场景、未替换人物；多角色明确对应，不能压成一条 caption。换动作时移除被替代的姿势、表情、互动冲突，不能只在旧动作后堆新词。卡片 exclusions 必须生效。
4. 新素材各成一块，来源为 `character:<ref>` / `action:<ref>`，重写原图块标 `manual`；`materials` 记录本组合卡片和 exclusions，删除已替换的卡片。不要跨来源去重或修改全局素材架。caption 保留正确负面和位置，性别词按实际角色写，不能盲补 `girl`。
5. 变体先预览、检查，再保存到**同一配方**并 `/generate`，串行等待，结果归入该配方历史。每次保存用上次成功保存响应的 `version/updated_at`，不能用基准备份旧时间戳；409 重新读并判断是否有用户改动，不强盖。
6. 本地记录每个变体的完整配方、素材 ref、run id、图片路径。完成或中途失败后恢复基准内容：以最后保存响应的 `version/updated_at` 为并发基准，只还原本次变更的内容字段，再读取确认。恢复遇冲突则保留备份并报告，不覆盖别人修改。

## 等待、恢复与交付

```powershell
uv run python $sl wait <workspace_id> <run_id> --timeout 45 --output runtime/stylelab/agent/run.json
```

- `wait_timed_out=true` 表示后台继续运行，继续查原 run，不能重新提交。记录 `queued/running/succeeded/partial/failed/cancelled/interrupted`，终态看每张 item 的状态和错误。
- `409 duplicate_request` 从错误 `details.run_id` 读取已有 run；完成且结果存在就复用，未完成就等待。丢失结果或失败时按原因处理，只有用户要求同参新候选或同意该次重出时才用 `force=true`。网络超时也先查 runs 确认是否提交成功。
- 完成授权范围内计划的样本即可；失败定位原因，不自动扩展到遍历模型/种子、消融、导出或大批重试。
- 交付工作区名/id、配方名/id/版本、代表源图、三类测试结果与绝对图片路径，说明跳过/失败及基准是否恢复。展示少量源图与结果，用户可在 Web Style Lab 查看完整历史。未实际出图就明确写未出图。
