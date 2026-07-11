# Final Fix Report

## 修改文件

- `src/tags_machine_core/web/services/node_workspace.py`
  - 纳入现有递归节点列表实现，支持嵌套目录、query、relative 和 limit。
  - 保存目标统一解析到 `design_root`，允许相对路径和根内绝对路径，拒绝 traversal 与根外路径。
- `src/tags_machine_core/web/routes/nodes.py`
  - 将保存路径校验错误映射为稳定的 `invalid_node` 400 JSON 响应。
- `tests/test_web_nodes.py`
  - 增加真实 `GET /api/nodes` 嵌套目录与 limit 覆盖。
  - 增加相对路径、根内绝对路径、traversal 和根外保存测试。
- `web/src/components/NodeSlot.tsx`
  - slot source/draft identity 变化时使 pending read 失效，旧 success/error/finally 不再覆盖外部 Apply/Save 结果。
- `web/src/components/NodeSlot.test.tsx`
  - 增加 pending read + Drawer Apply、pending read + Drawer Save 回归测试。
- `web/src/components/NodeEditorDrawer.tsx`
  - 空白临时节点显示目标 ref 输入并支持显式保存。
  - 已有节点继续默认保存到原 `sourceRef`。
  - 维护初始/已应用文本基线；关闭按钮和 backdrop 对未 Apply/Save 的 JSON 文本进行确认。
  - Apply/Save 成功更新基线并关闭；保存失败保留草稿。
- `web/src/components/NodeEditorDrawer.test.tsx`
  - 覆盖空白节点保存、失败保留、已有节点默认 ref、关闭确认及 Apply/Save 基线更新。
- `web/src/pages/CustomStudio.test.tsx`
  - 直接断言 stale 后 `/generate` 的 `body.render_request` 等于最新 `/compose-preview` 返回对象。
  - 增加 Job polling in-flight 旧响应与 unmount 后不继续更新/轮询测试。
- `tests/test_novelai_artist_dedup.py`
  - 增加 legacy NovelAI artist 同时作为 explicit artist 与 resolved artist 的 focused 业务测试。
- `.superpowers/sdd/final-fix-report.md`
  - 本报告。

## 测试结果

- `uv run python -m unittest tests.test_web_nodes tests.test_novelai_artist_dedup -v`
  - 9 tests passed。
- `npm run test -- src/components/NodeSlot.test.tsx src/components/NodeEditorDrawer.test.tsx src/pages/CustomStudio.test.tsx`
  - 3 files, 38 tests passed。
- `uv run python -m unittest tests.test_web_app tests.test_web_jobs tests.test_web_nodes tests.test_web_compose tests.test_web_results tests.test_web_batch tests.test_novelai_artist_dedup -v`
  - 23 tests passed。
  - 仅有现存 Starlette/httpx deprecation warning，无测试失败。
- `npm run test`
  - 5 files, 46 tests passed。
- `npm run build`
  - TypeScript 与 Vite production build 成功，1594 modules transformed。

## Artist 结论

Focused 业务测试通过：`ScriptComposer.compose_resolved_nodes()` 的最终 bundle prompt 不包含 Artist 内容，`NovelAIRenderAdapter` 作为唯一画风所有者写入 legacy artist prefix/suffix，最终 prompt 中每项只出现一次。因此未修改 Artist、Renderer 或相关 prompt policy 生产逻辑，也未 hardcode artist 名称。

此前旧真实服务未 reload，不能代表当前工作区代码的实际行为；本次结论来自当前工作区进程内的 focused 测试。

## 范围说明

未处理或纳入任何外部 prompt policy、batch、artist vibe、配置示例或其他任务外 dirty 文件。

## Final Artist Loading Fix

### Root Cause And Fix

`GenerationJsonApi._load_optional_artist_node()` previously called the generic `NodeReader` first. For an existing legacy `tags.txt` path, that generic representation duplicated the same artist material across common tags and prompt fields before the renderer assembled its final prompt.

The loader now follows the runtime ownership contract:

- string and `Path` artist references use the configured `artist_loader` first;
- inline `NodeDocument` and Mapping values continue through generic node validation;
- bare refs and existing absolute paths both resolve through `NovelAIArtistRepository` in Web runtime.

### Runtime Dependency Files Included

- `src/tags_machine_core/services/json_api.py`
- `src/tags_machine_core/web/app.py`
- `src/tags_machine_core/web/__main__.py`
- `src/tags_machine_core/web/routes/compose.py`
- `tests/test_json_api.py`
- `tests/test_web_app.py`
- `tests/test_web_compose.py`
- `web/package.json`

These preserve the existing Web config priority, `NovelAIArtistRepository` injection, CORS behavior, CLI host/port/config options, compose JSON error mapping, and frontend development port configuration.

### Verification

- Focused Artist loader tests: 4 passed, including bare ref, existing absolute `Path`, inline Mapping bypass, and real legacy explicit/resolved prompt deduplication.
- Clean-worktree Web suite plus `tests.test_novelai_artist_dedup`: 23 passed.
- Current-worktree frontend suite: 46 passed.
- Current-worktree TypeScript/Vite production build: passed, 1594 modules transformed.
- Full `tests.test_json_api` was run as requested. The current HEAD baseline reports 16 failures and 20 errors in pre-existing v1/v2 schema, CLI option, ComfyUI, and example-contract assertions outside this fix scope. The four Artist loading tests pass within that suite; no excluded config, batch, policy, renderer, or generation-service changes were added to mask those unrelated failures.
