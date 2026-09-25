# tags_machine_core 优化审查报告（2026-07-26）

审查范围：`src/tags_machine_core/` 全部核心模块（cli、execution、services、batch、renderers、verification、policies）。
关键结论已人工抽查源码确认。按优先级排列。

---

## P0 — 建议尽快处理

### 1. `config` 命令明文打印 NovelAI access_token（安全）
- 位置：`cli.py` cmd_config（约 342-345 行）、`config.py`（46-47 行）、`json_tools.py` sanitize
- 现状：`cmd_config` 直接 `print_json(config)`，`sanitize_json_for_display` 只截断长字符串不遮蔽敏感键。短 token 会完整进入终端历史 / CI 日志。
- 建议：`access_token` 改用 pydantic `SecretStr`，或在 sanitize 中加敏感键遮蔽列表（`access_token`、`token` 等）。改动极小。

### 2. batch/manifest.py：每次 append 全量重读+重写，整个 run 是 O(n²) IO
- 位置：`batch/manifest.py` `append_manifest_entry`（36-42 行）
- 现状：每追加一条 entry 就调用 `write_index(root, latest_manifest_entries(root))`，后者读取整个 manifest.jsonl 并逐行 `model_validate`。每个任务至少写 2 次（running + 终态），N 个任务 O(N²) 次解析。
- 建议：runner 在内存维护 latest dict，append 只追加 jsonl，index.json 定期或结束时写一次。

### 3. batch/runner.py：注入的 archive 被无条件覆盖，DI 失效
- 位置：`runner.py` 64 行 `self.archive = archive or BatchArchive()` vs 80 行 `self.archive = BatchArchive(archive_config)`
- 现状：构造函数注入的实例在 `run_tasks` 里被丢弃，测试替身失效；运行期状态写在 `self` 上使 runner 非可重入。
- 建议：`run_tasks` 内用局部变量，仅当未注入时才按 archive_config 新建。

### 4. 重试判定靠错误消息子串匹配，过宽且易误判
- 位置：`runner.py` 229-236、465-467 行 `_retryable`；`models.py` 40-43 行
- 现状：`except Exception` 捕获一切，再用 `"429"/"500"/"timeout"` 子串在异常文本里匹配。异常消息恰好含 "500"（路径、seed、尺寸数字）会被误判为可重试；编程错误（TypeError 等）被吞成 failed 条目，traceback 丢失。
- 建议：定义 `RetryableBackendError`（带 status_code），客户端按 HTTP 状态抛类型化异常，按类型判定重试；非预期异常不重试并保留 traceback。

---

## P1 — 结构性重构（收益最大）

### 5. cli.py 2838 行巨石文件，三种职责混杂
- 现状：约 45 个 `cmd_*`（98-1048 行）+ `_batch_*` 业务辅助（1051-1431 行）+ 850 行的 `build_parser`（1817-2667 行）。
- 建议：拆为 `cli/` 包按域分组（compose / render / batch / acceptance / api / parser_common）。项目内已有先例：`tools/action_resolver/cli.py`、`tools/task_tools/cli.py` 的 `add_*_subparser(subparsers, ...)` 挂载模式可直接推广。
- 注意：建议先做 #6、#7 去重再物理拆分，拆分体量会小很多。

### 6. 批处理编排逻辑在 CLI 层重复 6 份
- 位置：`cli.py` `cmd_api_plan/run/resume_batch`（683-857 行）与 `cmd_plan/run/resume_batch`（882-1030 行）
- 现状：六个函数各自手写同一流程（解析 spec → run_dir → planner → run_id → plan → 归档 spec → run_tasks → 组装结果），API 版与 CLI 版逐行对应。`fresh=False` 的 model_copy 等关键业务规则写在 CLI 里（775、959 行），修一处 bug 要改六处。
- 建议：在 batch 包内新增 `BatchOrchestrator` 或 `plan_batch()/run_batch()/resume_batch()` 纯函数 + `BatchRunOptions` dataclass；CLI/API 只做参数翻译。

### 7. 10 个 `cmd_api_*` 是逐字复制样板，可注册表化
- 位置：`cli.py` 582-654 行（实现）+ 2045-2117 行（parser 注册）
- 现状：全部是 `GenerationJsonApi().X(load(request)) → 可选写 output → print_json` 模板；已有 `_emit_api_result`（1233 行）却没被使用。
- 建议：`API_SIMPLE_COMMANDS` 注册表 + 工厂闭包生成 handler，parser 用循环注册。约 130 行缩到 20 行。

### 8. verification/acceptance.py 1977 行，至少混了 5 个职责
- 现状：record 构建/比较、归档复制、GenerationResult 证据校验、PromptBundle 契约校验、suite 验证、路径相对化全在一个文件。最长函数 `archive_acceptance_case` 约 124 行、`verify_acceptance_suite` 约 121 行。另有 4 个 case_check 包装函数复制粘贴（1557-1621、1656-1712 行），可收敛为一个 `_case_check(name, records, error_fn)`。
- 建议：拆成 `acceptance/record.py`、`archive.py`、`generation_evidence.py`、`bundle_contract.py`、`suite.py`。

### 9. batch/planner.py 三个 plan 函数约 300 行近乎复制
- 位置：`_plan_character_action_group`（333-433）、`_plan_blackboard_rounds`（435-582）、`_plan_blackboard_auto_rounds`（584-688）
- 现状：内层逻辑完全相同，20 键的 source dict 字面量重复 3 份，加一个字段要改三处。
- 建议：抽取 `_expand_round_tasks(round_ctx)`；source 元数据改为 `TaskSource` 模型（当前 `models.py:249` 是 `dict[str, Any]`）。

### 10. execution.py "单请求 vs 拆分循环" 模板复制三份
- 位置：227-301（novelai）、346-428（mock）、640-765（comfyui）行
- 现状：三处同一骨架各约 50-70 行；`_request_n_samples`（510）与 `_request_n_samples_for_backend`（805）是相同实现；两个 `_offset_*_seed` 行为还不一致（novelai 溢出抛错、comfyui 负 seed 原样返回，无注释说明是否有意）。
- 建议：抽 `_run_split_requests(requests, run_one)` 通用聚合器；统一 seed 行为或加注释。

---

## P2 — 正确性/可复现性隐患

### 11. expand.seed 无法完整复现 plan 结果
- 位置：`planner.py` 122 行 `random.shuffle(tasks)`、936 行 `random.choice(...)` 用全局 random，不受 `expand.seed` 控制。
- 影响：同一 seed 两次 plan 得到不同任务顺序和分辨率，resume 快照与重新 plan 可能不一致。
- 建议：把 seeded rng 一路传入 `_task` / `_resolve_dimensions` / shuffle。

### 12. 断点续跑的薄弱点（runner.py / manifest.py）
- `task_already_succeeded` 只看 status.json，不校验 image_paths 文件仍存在，图被删后 resume 假成功跳过。
- `image_budget` 只对本次 succeeded 扣减，resume 时 skipped 任务的产出不计入，`max_images` 语义失真。
- manifest.jsonl / index.json 非原子写（对比 `action_group_state.py` 已正确用 tmp+replace，风格不一致）。
- `resume=False, fresh=False` 时覆盖旧 manifest 但保留旧产物目录，历史被截断。
- `_resume_task_snapshot` 捕获异常静默回退，task.json 损坏无日志。

### 13. 四处"读 JSON 失败静默吞掉"且无日志
- 位置：`cli.py` 1075-1078、1102-1105、1385-1388、1424-1427 行
- 建议：抽 `_read_json_mapping_or(path, default)`，内部 `logger.warning`。同类问题还有 `acceptance.py` 1153-1156、1482-1484 行的 `except Exception` 静默。

### 14. main() 无顶层错误处理
- 位置：`cli.py` 2830-2838 行
- 现状：用户输入错误（如 `ValueError("run-prompt ... requires --config")`）以完整 traceback 砸给用户，退出码语义与业务失败的 2 未区分。
- 建议：`main` 捕获 `(ValueError, FileNotFoundError, FileExistsError)` 输出 stderr + 固定错误码。

---

## P3 — 性能与代码卫生

- **重复加载 config**：`cli.py` `_load_command_config` 一条命令内可能加载/解析同一 YAML 3 次，且每次重复 `configure_logging`（副作用与名字不符）。建议入口加载一次向下传，或 lru_cache。
- **executor 无节点缓存**：`batch/executor.py` 128-161 行，planner 有 `_CachedNodeReader` 而 executor 没有；`NovelAIArtistRepository` 每任务重建。100 任务 ≈ 300 次重复 IO。
- **renderers/novelai.py**：`_build_parameters` 173 行超长；`_preserve_supported_extras` 重复实现了 `common.preserve_extra_params`（comfyui/sd 都用 common 版，仅 novelai 漂移）；`_legacy_clean_movie_style_artists` 每次调用重建 60+ 项画师黑名单并重复正则规范化，应提升为模块级预规范化 frozenset（这份名单本质是数据，建议外置配置）。
- **`_find_prompt_tag` 三重循环重复解析**：`novelai.py` 407-423、891-898 行，应先把 base_tags 预解析成 `{canonical: 原文}` 字典。
- **CLI 与 JSON API 双份标量解析已漂移**：`cli.py` 1204-1230 vs `json_api.py` 352-393 行，CLI 的 bool 解析接受 `yes/on` 而 API 侧没有，同一请求两条路径宽容度不同。收敛到共享模块。
- **json_api.py 死条件与往返转换**：65 行 `"prompt" not in data` 恒真；`resolve_agent` 等内部 模型→dict→模型→dict 两轮转换。
- **execution.py 模块级节流全局变量**（33、485-497 行）无锁，未来并行会失效；约 170 行 PNG chunk 工具与调度职责无关，宜拆出 `png_meta.py`。
- **parameter_image.py `_load_font` 无缓存**，每张参数图按 4 个字号试多个硬编码字体路径（含 Windows 绝对路径，Linux 上必失败几次），加 `lru_cache`。
- **argparse `action="append", default=[]`** 共享可变默认列表，测试中同一 parser 多次 parse 会累积，改 `default=None`。
- **仓库卫生**：refactor 根目录散落约 10 个 `*.log` / `tmp_batch_*.log`，建议清理并入 .gitignore。

---

## 建议的实施顺序

1. **一小时内可完成**：#1 token 遮蔽、#3 archive DI、#13 JSON 读取加日志、log 文件清理。
2. **第一轮重构**：#4 类型化重试异常、#2 manifest 增量写、#11 rng 可复现。
3. **第二轮重构**：#6 批处理编排下沉 + #7 api 注册表（可直接砍掉 cli.py 约 400-500 行），然后再做 #5 物理拆分。
4. **第三轮**：#8 acceptance 拆包、#9 planner 去重、#10 execution 聚合器。

config.py、generation_service.py、json_api.py、nodes/ 整体质量良好；问题集中在 cli.py、execution.py、batch/、acceptance.py 的"复制式增长"。
