# Style Lab API

两阶段流程首先读 [workflow-api.md](workflow-api.md)。下列单图接口仅在用户明确选定测试范围之后使用；准备阶段不能调用 regenerate/generate。配方变体用 test-plans 快照，无需临时覆盖保存配方。

路径相对于 `/api/style-lab`；`w/i/r/u` 是工作区、图片、配方、run 的真实 id。用 `client.py api` 和 UTF-8 JSON 文件，避免 PowerShell 多层引号。

## 创建与读取

| 方法 | 路径 | 请求体或说明 |
|---|---|---|
| GET | `/workspaces` | 响应 `workspaces` |
| POST | `/workspaces` | `{"root":"F:/图库/作者","name":"作者画风"}` 或 `{"files":["F:/图库/a.png","F:/图库/b.png"],"name":"参考组"}`；响应 `workspace, images, analysis_job_id` |
| GET | `/workspaces/w` | `images` 含 `has_metadata, seed, model, gen_width, gen_height, flags, vibe` |
| POST | `/workspaces/w/scan` | `{}`，增量重扫 |
| GET | `/workspaces/w/analysis` | `categories, groups, job_id`；只读缓存 |
| GET | `/workspaces/w/images/i` | `image, raw_parameters, png_text_keys` |
| GET | `/shelf` | 全局选择 `materials`：每项 `role, ref, name, excluded` |
| GET | `/library/node?role=character&ref=...` | `ref, role, name, sections:[{name,tags}]`；动作 role 为 `action`，查询值 URL 编码 |
| GET | `/library/search?role=action&q=...&limit=30&offset=0` | 查准确 ref；素材架为空不要自行选陌生素材 |
| GET | `/workspaces/w/recipes` | 配方摘要 `recipes` |
| POST | `/workspaces/w/recipes` | `{"image_id":"i","name":"清晰线稿","group_id":null}`；响应 `recipe`。`draft:true` 不保存 |
| GET | `/workspaces/w/recipes/r` | `recipe, history` |

多个文件夹合并图片组时，先枚举指定目录内图片，再一次 POST `files`；有 `origin/` 优先枚举它。手动枚举排除 `.stylelab/` 等生成目录，不能把输出当源图。跨盘散图若后台报 commonpath 错误则按盘拆组，不移动源图。

## 配方编辑与保存

必须编辑 API 返回的**完整 recipe 对象**，保留 id、版本、时间、源图、参数等。主要区域为：

- `prefix/subject/suffix/dropped/negative`：token 数组，token 形如 `{"id":"唯一短串","text":"一整块提示词","sep":"","origins":["source"]}`。原样移动沿用 id/来源；新增块用 UUID 短串，sep 为同区块间分隔。组合顺序 `prefix + subject + suffix`。
- `character`：`enabled, captions, use_coords, add_male_caption`；每个 caption 含 `tokens, negative`（也是 token 数组）、`center`（如 `{"x":0.5,"y":0.5}` 或 null）。保留全部条目。
- `materials`：所用卡片的 `role/ref/name/excluded`；与全局 shelf 是不同数据。
- `model/params/use_source_vibe/flags`：从源图继承；不往 params 填种子、宽高、张数。
- 画风签名包含前后缀/负面文本、模型、参数、vibe 开关和 flags。改变签名增加版本；只改主体/captions/materials/name/notes 原地保存，不加版本，仍更新 `updated_at`。
- 预览 `POST /workspaces/w/recipes/preview`：`{"recipe": 完整对象}`；返回 `preview.prompt, negative_prompt, char_captions, negative_char_captions, model, size, params, vibe_count`。不出图，内部 seed=0 不代表测试种子。
- 保存 `PUT /workspaces/w/recipes/r`：`{"recipe": 完整对象, "base_version": 刚读取的版本}`。recipe 本身携带刚读取的 `updated_at`，两者都用于冲突检查。
- 分词用 `tags_machine_core.style_lab.tokens.tokenize`；块转文本用 `recipe.tokens_text`；不能普通 `split(',')` 拆权重。

本地生成请求示例：

```python
import json
from pathlib import Path

data = json.loads(Path('runtime/stylelab/agent/task/base.json').read_text(encoding='utf-8-sig'))
recipe = data['recipe']
# 完成画风划分或生成一个内容变体，保留并发字段。
Path('runtime/stylelab/agent/task/preview.json').write_text(
    json.dumps({'recipe': recipe}, ensure_ascii=False, indent=2), encoding='utf-8')
Path('runtime/stylelab/agent/task/save.json').write_text(
    json.dumps({'recipe': recipe, 'base_version': recipe['version']}, ensure_ascii=False, indent=2),
    encoding='utf-8')
```

```powershell
uv run python $sl api POST /workspaces/w/recipes/preview --body-file runtime/stylelab/agent/task/preview.json
uv run python $sl api PUT /workspaces/w/recipes/r --body-file runtime/stylelab/agent/task/save.json --output runtime/stylelab/agent/task/saved.json
```

## 出图与查询

原参重生 POST `/workspaces/w/regenerate`：

```json
{"image_id":"i","settings":{"count":1,"seed_mode":"source","size_mode":"source","overrides":{}}}
```

配方测试 POST `/workspaces/w/recipes/r/generate`：

```json
{"settings":{"count":1,"seed_mode":"source","size_mode":"source","overrides":{}}}
```

配方测试取**已保存内容**，草稿不会生效。两者返回 `{"run":{...}}`。不使用 `artist-test` 代替配方测试：它依赖已导出的 artist，这里不需要额外导出。

- GET `/workspaces/w/runs/u`：`run.id, kind, status, job_id, source, settings, recipe, warnings, items`。
- GET `/workspaces/w/runs?recipe_id=r` 或 `?image_id=i`：`runs`，用于恢复和查重。
- item 成功字段 `image_path, seed, compare`；失败字段 `error, error_detail`。compare 有 `verdict, similarity, dhash_distance, param_diff_count, param_diff_no_resolution_count, diffs`，diff 可有 `expected/note`。
- GET `/workspaces/w/file?image_id=i` 或 `?path=返回的结果绝对路径`，可加 `size=320` 取缩略图。只允许该工作区来源及 runs 内文件。远程结果需通过此接口读到本地才能使用本地看图工具。
- 取消用 Web `/api/jobs/{job_id}/cancel`；此 helper 只封装 Style Lab，不提供取消命令，不删除 run 文件。

HTTP 错误形如 `{"error":{"code":"...","message":"...","details":{...}}}`。`duplicate_request` 的 details 有 `run_id/status/created_at`；`recipe_conflict` 要重新读取处理，不加 force。

## 实现定位

- `src/tags_machine_core/web/routes/style_lab.py`：API 请求体。
- `src/tags_machine_core/style_lab/recipe.py`：字段、画风签名、保存冲突、captions。
- `src/tags_machine_core/style_lab/regenerate.py`：原参恢复、种子递增、尺寸。
- `src/tags_machine_core/style_lab/service.py`：拼接、出图、查重、run 状态。
- `src/tags_machine_core/style_lab/shelf.py`、`web/src/styleLab/materialShelf.ts`：全局选择。
- `web/src/styleLab/recipeModel.ts`：划分/素材块/来源/位置；按来源移除素材不能自动清掉原图中的旧角色或旧动作。
