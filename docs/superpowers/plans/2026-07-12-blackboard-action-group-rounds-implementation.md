# Blackboard Action Group Rounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `blackboard_action_new_manga_monochrome.yaml` 按旧 `blackboard.py:run_tags_machine` 的业务节奏运行：保留动作分类目录边界、按最少使用次数选择组、每组随机抽 3 个动作并按原顺序执行、随后切换角色。

**Architecture:** `action_groups.py` 负责把 action collection 解析成保留目录边界的 `ResolvedActionGroup`，并提供纯函数式组内抽样；`BatchPlanner` 只读取动作组状态快照并在内存中投影后续选择，不写磁盘；`BatchRunner` 通过 run directory 下的状态存储器幂等记录实际开始和完成的 round。Composer、Policy、Renderer 和 NovelAI client 不感知调度变化。

**Tech Stack:** Python 3.11+、Pydantic v2、PyYAML、现有 `unittest` 测试体系、NovelAI batch mock client、JSON 原子状态文件。

## Global Constraints

- 只修改 `refactor` 子模块，不修改旧 `tags_machine` 业务代码。
- 代码注释使用中文；仅在复杂状态或算法处添加必要注释。
- 不写 `ACTION_NEW`、`pn_*`、artist 名称等业务硬编码。
- 普通 `select.actions` collection 的扁平展开行为必须保持不变。
- AgentComposer、ScriptComposer、PromptPolicyPipeline、Renderer、NovelAI client 不改变职责。
- `plan-batch` 不得修改持久化动作组状态。
- `resume-batch` 不得重复累计同一个 `round_id`。
- `--fresh` 删除 run directory，并从空动作组状态重新规划。
- 业务验收优先：完成后必须执行 300 task 的 mock 全链路验证，并运行小规模真实 NovelAI 出图。

---

## File Map

- Modify: `src/tags_machine_core/batch/models.py`：新增组内动作选择配置类型与校验。
- Modify: `src/tags_machine_core/batch/selectors.py`：暴露可复用的目录匹配与节点发现函数。
- Modify: `src/tags_machine_core/batch/action_groups.py`：保留 collection 目录边界、组内动作抽样、状态模型基础操作。
- Create: `src/tags_machine_core/batch/action_group_state.py`：run directory 动作组状态的加载、原子保存、round 幂等更新和状态汇总。
- Modify: `src/tags_machine_core/batch/planner.py`：按 round 选择动作组和动作子集，只进行内存状态投影。
- Modify: `src/tags_machine_core/batch/runner.py`：在真实执行边界更新 round 状态，并在执行后协调 completed/failed。
- Modify: `src/tags_machine_core/batch/report.py`：输出 round 和动作组摘要。
- Modify: `src/tags_machine_core/batch/__init__.py`：导出新增公共类型。
- Modify: `tests/test_batch_generation.py`：覆盖解析、抽样、Planner、状态和 Runner 行为。
- Modify: `examples/batches/blackboard_action_new_manga_monochrome.yaml`：切换到 `balanced_random + max_tasks + 每组抽 3 个`。
- Modify: `docs/batch_generation_readme.md`：正式记录 collection/group、`auto_num` 和状态目录语义。
- Create: `docs/blackboard_action_group_rounds_business_test_20260712.md`：记录 mock 与真实出图验收结果。

---

### Task 1: 组内动作选择配置与纯函数

**Files:**
- Modify: `src/tags_machine_core/batch/models.py`
- Modify: `src/tags_machine_core/batch/action_groups.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Produces: `ActionSelectionName = Literal["all", "random_preserve_order"]`
- Produces: `ExpandConfig.actions_per_group: int | None`
- Produces: `ExpandConfig.action_selection: ActionSelectionName`
- Produces: `select_group_actions(group, *, strategy, limit, rng) -> list[str]`

- [ ] **Step 1: Add focused failing model and selection tests**

在 `tests/test_batch_generation.py` 增加：

```python
def test_expand_config_rejects_non_positive_actions_per_group(self):
    with self.assertRaisesRegex(ValueError, "actions_per_group must be >= 1"):
        ExpandConfig(actions_per_group=0)

def test_random_preserve_order_samples_then_restores_source_order(self):
    group = ResolvedActionGroup(name="g1", actions=["a1", "a2", "a3", "a4"])
    selected = select_group_actions(
        group,
        strategy="random_preserve_order",
        limit=2,
        rng=random.Random(7),
    )
    self.assertEqual(len(selected), 2)
    self.assertEqual(selected, sorted(selected, key=group.actions.index))

def test_all_selection_respects_limit_without_shuffle(self):
    group = ResolvedActionGroup(name="g1", actions=["a1", "a2", "a3"])
    self.assertEqual(
        select_group_actions(group, strategy="all", limit=2, rng=random.Random(1)),
        ["a1", "a2"],
    )
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "actions_per_group or preserve_order or all_selection" -q
```

Expected: FAIL because the new fields and `select_group_actions` do not exist.

- [ ] **Step 3: Add the model fields and validation**

在 `models.py` 增加：

```python
ActionSelectionName = Literal["all", "random_preserve_order"]

class ExpandConfig(BaseModel):
    # existing fields...
    actions_per_group: int | None = None
    action_selection: ActionSelectionName = "all"

    @field_validator("actions_per_group")
    @classmethod
    def _actions_per_group_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("actions_per_group must be >= 1")
        return value
```

- [ ] **Step 4: Implement pure group action selection**

在 `action_groups.py` 增加：

```python
def select_group_actions(
    group: ResolvedActionGroup,
    *,
    strategy: ActionSelectionName,
    limit: int | None,
    rng: random.Random,
) -> list[str]:
    actions = list(group.actions)
    if limit is None or limit >= len(actions):
        return actions
    if strategy == "all":
        return actions[:limit]
    if strategy == "random_preserve_order":
        indices = sorted(rng.sample(range(len(actions)), k=limit))
        return [actions[index] for index in indices]
    raise ValueError(f"Unsupported action selection strategy: {strategy}")
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "actions_per_group or preserve_order or all_selection" -q
```

Expected: PASS.

- [ ] **Step 6: Commit the isolated behavior**

```powershell
git add src/tags_machine_core/batch/models.py src/tags_machine_core/batch/action_groups.py tests/test_batch_generation.py
git commit -m "feat: add batch action group sampling"
```

---

### Task 2: Preserve folder boundaries when collections become action groups

**Files:**
- Modify: `src/tags_machine_core/batch/selectors.py`
- Modify: `src/tags_machine_core/batch/action_groups.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Produces: `matching_directories(root: Path, spec: SelectorSpec) -> list[Path]`
- Produces: `discover_nodes(root: Path, spec: SelectorSpec) -> list[str]`
- Changes: `resolve_action_groups()` expands folder selectors inside collections into one group per matched direct directory.

- [ ] **Step 1: Add failing collection-boundary tests**

创建临时目录：

```text
actions/
  pn_a/01/meta.yaml
  pn_a/02/meta.yaml
  pn_b/01/meta.yaml
```

测试：

```python
def test_action_group_collection_preserves_matched_folder_boundaries(self):
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "actions"
        _write_node(root / "pn_a" / "01")
        _write_node(root / "pn_a" / "02")
        _write_node(root / "pn_b" / "01")
        context = SelectorContext(
            base_dir=Path(tmp),
            collections={
                "actions": {
                    "action_new": [{
                        "selector": "folder",
                        "root": str(root),
                        "include": {"names": ["pn_*"]},
                    }]
                }
            },
        )
        groups = resolve_action_groups(
            [SelectorSpec(selector="collection", name="action_new")],
            context=context,
        )
        self.assertEqual([group.name for group in groups], ["pn_a", "pn_b"])
        self.assertEqual([len(group.actions) for group in groups], [2, 1])
```

同时增加回归测试，证明同一个 collection 通过普通 `expand_selector(role="action")` 时仍得到 3 个扁平 action ref。

- [ ] **Step 2: Run boundary tests and confirm current flattening failure**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "preserves_matched_folder_boundaries or ordinary_action_collection_remains_flat" -q
```

Expected: action group test FAIL，普通 action collection 回归测试 PASS。

- [ ] **Step 3: Expose reusable selector discovery helpers**

在 `selectors.py`：

```python
def matching_directories(root: Path, spec: SelectorSpec) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(f"Selector root not found: {root}")
    if not root.is_dir():
        return []
    candidates = sorted((path for path in root.iterdir() if path.is_dir()), key=_natural_sort_key)
    return [path for path in candidates if not _excluded(path, spec) and _included(path, spec)]

def discover_nodes(root: Path, spec: SelectorSpec) -> list[str]:
    return _discover_nodes(root, spec)
```

不改变 `_discover_nodes()` 的现有算法。

- [ ] **Step 4: Add collection-aware group resolution**

在 `action_groups.py` 中让 `resolve_action_groups()` 对 `selector == "collection"` 调用新的递归解析函数：

```python
def _resolve_collection_groups(
    collection_name: str,
    *,
    context: SelectorContext,
    stack: tuple[str, ...] = (),
) -> list[ResolvedActionGroup]:
    # 读取 context.collections["actions"][collection_name] 的原始 item。
    # folder item 匹配多个直接子目录时，每个目录建立一个 group。
    # collection item 递归展开并检测循环引用。
    # 其他 item 回退为 collection_name 对应的单一 group。
```

folder group 的节点发现使用：

```python
child_spec = selector.model_copy(
    update={"root": str(folder), "include": {}, "exclude": {}, "limit": None, "shuffle": False}
)
actions = discover_nodes(folder, child_spec)
```

所有 group 最后检查空组和重名，错误信息包含 collection 链。

- [ ] **Step 5: Run action group and selector regression tests**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "action_group or action_collection" -q
```

Expected: PASS，现有显式 action group 测试不回归。

- [ ] **Step 6: Commit folder-preserving resolution**

```powershell
git add src/tags_machine_core/batch/selectors.py src/tags_machine_core/batch/action_groups.py tests/test_batch_generation.py
git commit -m "feat: preserve collection action group folders"
```

---

### Task 3: Add run-directory action group state store

**Files:**
- Create: `src/tags_machine_core/batch/action_group_state.py`
- Modify: `src/tags_machine_core/batch/action_groups.py`
- Modify: `src/tags_machine_core/batch/__init__.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Produces: `ActionGroupRoundState`
- Produces: `ActionGroupStateStore.for_run_dir(run_dir) -> ActionGroupStateStore`
- Produces: `load() -> ActionGroupRecord`
- Produces: `save(record: ActionGroupRecord) -> Path`
- Produces: `mark_round_started(record, *, round_id, group_name) -> bool`
- Produces: `mark_round_finished(record, *, round_id, status) -> bool`

- [ ] **Step 1: Add failing state location and idempotency tests**

```python
def test_action_group_state_defaults_under_run_directory(self):
    with TemporaryDirectory() as tmp:
        store = ActionGroupStateStore.for_run_dir(Path(tmp) / "run")
        self.assertEqual(store.path, Path(tmp) / "run" / "state" / "action_groups.json")

def test_mark_round_started_is_idempotent(self):
    record = ActionGroupRecord()
    self.assertTrue(mark_round_started(record, round_id="r1", group_name="g1"))
    self.assertFalse(mark_round_started(record, round_id="r1", group_name="g1"))
    self.assertEqual(record.groups["g1"].selected_count, 1)

def test_state_store_round_trip_preserves_recorded_rounds(self):
    with TemporaryDirectory() as tmp:
        store = ActionGroupStateStore.for_run_dir(Path(tmp) / "run")
        record = ActionGroupRecord()
        mark_round_started(record, round_id="r1", group_name="g1")
        store.save(record)
        self.assertEqual(store.load().recorded_rounds["r1"].group, "g1")
```

- [ ] **Step 2: Run state tests and confirm failure**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "action_group_state or mark_round_started" -q
```

Expected: FAIL because the store and round state do not exist.

- [ ] **Step 3: Extend the state model**

在 `action_groups.py` 增加：

```python
class ActionGroupRoundState(BaseModel):
    group: str
    status: Literal["started", "completed", "failed"] = "started"
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str | None = None

class ActionGroupRecord(BaseModel):
    # existing fields...
    recorded_rounds: dict[str, ActionGroupRoundState] = Field(default_factory=dict)
```

并增加幂等纯函数；完成状态只允许从 `started` 转为一次 `completed` 或 `failed`。

- [ ] **Step 4: Implement atomic state persistence**

`action_group_state.py`：

```python
class ActionGroupStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @classmethod
    def for_run_dir(cls, run_dir: str | Path) -> "ActionGroupStateStore":
        return cls(Path(run_dir) / "state" / "action_groups.json")

    def load(self) -> ActionGroupRecord:
        if not self.path.exists():
            return ActionGroupRecord()
        return ActionGroupRecord.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, record: ActionGroupRecord) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(record.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return self.path
```

JSON 损坏时保留 Pydantic/JSON 错误并附加状态路径上下文，不静默重置。

- [ ] **Step 5: Run state tests**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "action_group_state or mark_round_started" -q
```

Expected: PASS.

- [ ] **Step 6: Commit state store**

```powershell
git add src/tags_machine_core/batch/action_group_state.py src/tags_machine_core/batch/action_groups.py src/tags_machine_core/batch/__init__.py tests/test_batch_generation.py
git commit -m "feat: persist batch action group round state"
```

---

### Task 4: Make BatchPlanner produce sampled rounds without state side effects

**Files:**
- Modify: `src/tags_machine_core/batch/planner.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Consumes: `ActionGroupStateStore.load()`
- Consumes: `select_group_actions()`
- Produces: stable task `source.round_id` and sampled-action metadata.
- Guarantee: Planner never calls `ActionGroupStateStore.save()`.

- [ ] **Step 1: Add failing planner behavior tests**

覆盖以下行为：

```python
def test_blackboard_rounds_samples_three_actions_then_switches_character(self): ...
def test_blackboard_auto_num_runs_one_sampled_round_per_character(self): ...
def test_blackboard_plan_uses_state_snapshot_without_writing_it(self): ...
def test_blackboard_fresh_ignores_existing_state_snapshot(self): ...
```

第一个测试建立两个角色、两个各有 5 个动作的 group，设置：

```python
ExpandConfig(
    mode="blackboard_rounds",
    max_tasks=6,
    action_group_strategy="ordered",
    actions_per_group=3,
    action_selection="random_preserve_order",
    seed=7,
)
```

断言前 3 个 task 使用角色 A 和同一个 group，后 3 个 task 使用角色 B 和下一个 group。

- [ ] **Step 2: Run planner tests and confirm failure**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "sampled_round or state_snapshot or fresh_ignores" -q
```

Expected: FAIL because Planner still emits all group actions and writes configured records.

- [ ] **Step 3: Load state snapshot from run directory**

在两个 action-group planner 入口中统一：

```python
store = ActionGroupStateStore.for_run_dir(run_dir)
persisted = ActionGroupRecord() if spec.run.fresh else store.load()
planning_record = persisted.model_copy(deep=True)
```

删除 Planner 内所有 `record.save(...)` 调用。`action_group_record` 不再进入新 task source。

- [ ] **Step 4: Extract one round planner helper**

在 `BatchPlanner` 增加私有方法：

```python
def _select_round(
    self,
    spec: BatchSpec,
    *,
    character: str,
    round_index: int,
    groups: list[ResolvedActionGroup],
    record: ActionGroupRecord,
    rng: random.Random,
) -> tuple[str, ResolvedActionGroup, list[str], int | None]:
    group, selected_count = choose_action_group(...)
    actions = select_group_actions(
        group,
        strategy=spec.expand.action_selection,
        limit=spec.expand.actions_per_group,
        rng=rng,
    )
    round_id = _round_id(character, group.name, round_index, actions)
    return round_id, group, actions, selected_count
```

`_round_id()` 使用稳定哈希，不包含运行时间；输入包括 `run_id`、`round_index`、character ref、group name 和抽中的 action refs。

- [ ] **Step 5: Update task source metadata**

每个 sampled task 写入：

```python
{
    "round_id": round_id,
    "round_index": round_index,
    "action_group": group.name,
    "action_group_selected_count": selected_count,
    "action_index_in_group": action_index,
    "action_count_in_group": len(selected_actions),
    "action_group_total_actions": len(group.actions),
    "action_selection": spec.expand.action_selection,
    "actions_per_group": spec.expand.actions_per_group,
}
```

`max_tasks` 仍按 task 数截断；如果在一个 round 中间截断，状态协调器只把实际开始的任务视为该 round 的本次执行范围，不伪造未规划 task。

- [ ] **Step 6: Run planner and existing batch generation tests**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "blackboard_rounds or character_action_group or batch_shorthand" -q
```

Expected: PASS；更新旧断言，使默认 `action_selection=all` 时行为保持原状。

- [ ] **Step 7: Commit side-effect-free round planning**

```powershell
git add src/tags_machine_core/batch/planner.py tests/test_batch_generation.py
git commit -m "feat: plan sampled blackboard rounds"
```

---

### Task 5: Update action group state only at Runner execution boundaries

**Files:**
- Modify: `src/tags_machine_core/batch/action_group_state.py`
- Modify: `src/tags_machine_core/batch/runner.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Produces: `ActionGroupRunTracker.start_task(task) -> None`
- Produces: `ActionGroupRunTracker.reconcile(tasks, entries) -> dict[str, Any]`
- Guarantee: one `round_id` increments selected count once across retry and resume.

- [ ] **Step 1: Add failing Runner state tests**

覆盖：

```python
def test_runner_records_round_once_for_three_tasks(self): ...
def test_runner_resume_does_not_increment_existing_round(self): ...
def test_runner_limit_records_only_started_round(self): ...
def test_runner_fresh_removes_previous_action_group_state(self): ...
def test_runner_marks_round_failed_when_a_task_finally_fails(self): ...
```

三个 task 使用同一个 `source.round_id="r1"`。成功执行后断言：

```python
record.groups["g1"].selected_count == 1
record.groups["g1"].completed_count == 1
record.recorded_rounds["r1"].status == "completed"
```

- [ ] **Step 2: Run Runner state tests and confirm failure**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "runner_records_round or runner_resume_does_not_increment or runner_limit_records or marks_round_failed" -q
```

Expected: FAIL because Runner does not track rounds.

- [ ] **Step 3: Implement `ActionGroupRunTracker`**

在 `action_group_state.py` 增加：

```python
class ActionGroupRunTracker:
    def __init__(self, run_dir: str | Path):
        self.store = ActionGroupStateStore.for_run_dir(run_dir)
        self.record = self.store.load()

    def start_task(self, task: BatchTask) -> None:
        round_id = str(task.source.get("round_id") or "")
        group = str(task.source.get("action_group") or "")
        if round_id and group and mark_round_started(
            self.record, round_id=round_id, group_name=group
        ):
            self.store.save(self.record)

    def reconcile(self, tasks: list[BatchTask], entries: list[dict[str, Any]]) -> dict[str, Any]:
        # 按 round_id 汇总本次选中 task 的最终状态。
        # 任一 failed -> failed；全部 succeeded/skipped -> completed；其他保持 started。
        # 每次状态转移后原子保存。
```

- [ ] **Step 4: Hook tracker into `BatchRunner.run_tasks()`**

顺序必须是：

```python
root = Path(run_dir)
if run_config.fresh and root.exists():
    shutil.rmtree(root)
root.mkdir(...)
tracker = ActionGroupRunTracker(root)
```

在 task 被 resume skip 或真正执行前调用 `tracker.start_task(task)`，确保旧 manifest 恢复时也能重建缺失状态。retry 内不重复调用。

循环结束后调用：

```python
action_group_summary = tracker.reconcile(selected, entries)
```

并把 summary 传给 report。

- [ ] **Step 5: Run Runner and retry regression tests**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "runner or retry" -q
```

Expected: PASS。

- [ ] **Step 6: Commit runtime state tracking**

```powershell
git add src/tags_machine_core/batch/action_group_state.py src/tags_machine_core/batch/runner.py tests/test_batch_generation.py
git commit -m "feat: track executed batch action rounds"
```

---

### Task 6: Add round summaries, update example config and documentation

**Files:**
- Modify: `src/tags_machine_core/batch/report.py`
- Modify: `src/tags_machine_core/batch/runner.py`
- Modify: `examples/batches/blackboard_action_new_manga_monochrome.yaml`
- Modify: `docs/batch_generation_readme.md`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Changes: `write_report(..., action_group_summary: dict[str, Any] | None = None)`
- Produces: `report.json.action_groups` and Markdown `Action Groups` section.

- [ ] **Step 1: Add failing report summary test**

```python
def test_report_includes_round_and_action_group_summary(self):
    report = write_report(
        run_dir,
        entries,
        action_group_summary={
            "rounds": 2,
            "groups": {"g1": {"selected": 1, "completed": 1, "failed": 0}},
            "characters": {"homura": 1, "madoka": 1},
        },
    )
    self.assertEqual(report["action_groups"]["rounds"], 2)
    self.assertIn("## Action Groups", (run_dir / "report.md").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Implement report output**

在 JSON 顶层增加 `action_groups`，Markdown 输出 rounds、character round count 和 group selected/completed/failed 表格。无 round source 的普通 batch 不输出该节。

- [ ] **Step 3: Update Blackboard replacement YAML**

将示例改为：

```yaml
batch:
  characters: special_next_select
  action_groups: action_new
  artist: "104994507_01_flat_color_artist_stack_vibe_86b3d31d_619_cfg07_strength04_v45_latest_stable"
  composer: script
  nt: 3

expand:
  mode: blackboard_rounds
  max_tasks: 300
  action_group_strategy: balanced_random
  actions_per_group: 3
  action_selection: random_preserve_order
```

移除 `auto_num` 和 `ordered`。不配置 `action_group_record`。

- [ ] **Step 4: Update batch README**

明确记录：

- `nai_const_action_groups.yaml` 是 action collection 来源。
- collection 作为 `select.actions` 时扁平展开。
- collection 作为 `select.action_groups` 时保留匹配目录边界。
- `auto_num` 表示每个角色一个 round。
- `action_selection` 只控制组内动作选择。
- 默认状态路径为 `<run_dir>/state/action_groups.json`。
- `plan-batch` 不改变状态，`--fresh` 重置状态。

- [ ] **Step 5: Run report and configuration tests**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -k "report or blackboard_rounds or batch_shorthand" -q
```

Expected: PASS。

- [ ] **Step 6: Commit report, config and docs**

```powershell
git add src/tags_machine_core/batch/report.py src/tags_machine_core/batch/runner.py examples/batches/blackboard_action_new_manga_monochrome.yaml docs/batch_generation_readme.md tests/test_batch_generation.py
git commit -m "feat: finalize blackboard round batch workflow"
```

---

### Task 7: Run 300-task mock business acceptance

**Files:**
- Create: `docs/blackboard_action_group_rounds_business_test_20260712.md`
- Generated but do not commit: `examples/batches/blackboard-action-new-manga-monochrome/`

**Interfaces:**
- Consumes: final example YAML and mock client.
- Produces: business acceptance evidence with task orchestration and state checks.

- [ ] **Step 1: Start with a fresh mock batch**

Run:

```powershell
uv run python -m tags_machine_core run-batch examples/batches/blackboard_action_new_manga_monochrome.yaml --mock-client --fresh --log-level info --full
```

Expected:

- `task_count` is 300.
- full Composer/Policy/Renderer/Executor/Archive chain runs with mock backend only replacing HTTP image generation.
- state file exists at `examples/batches/blackboard-action-new-manga-monochrome/state/action_groups.json`.

- [ ] **Step 2: Validate orchestration from generated task JSON files**

运行一个只读校验脚本，断言：

```python
assert len(tasks) == 300
assert all(1 <= round_task_count <= 3 for round_task_count in round_counts.values())
assert all(len({task.source["character"] for task in round_tasks}) == 1 for round_tasks in rounds)
assert all(len({task.source["action_group"] for task in round_tasks}) == 1 for round_tasks in rounds)
assert max(group_selected_counts) - min(group_selected_counts) <= 1
```

同时检查每个 round 的 action index 严格递增，证明随机抽样后恢复了原顺序。

- [ ] **Step 3: Verify preview does not mutate state**

记录状态文件 SHA256：

```powershell
Get-FileHash examples/batches/blackboard-action-new-manga-monochrome/state/action_groups.json
uv run python -m tags_machine_core plan-batch examples/batches/blackboard_action_new_manga_monochrome.yaml --full
Get-FileHash examples/batches/blackboard-action-new-manga-monochrome/state/action_groups.json
```

Expected: 两次 SHA256 相同。

- [ ] **Step 4: Verify resume idempotency**

Run:

```powershell
uv run python -m tags_machine_core resume-batch examples/batches/blackboard-action-new-manga-monochrome --full
```

Expected: succeeded task 被跳过，所有 group selected count 不增加。

- [ ] **Step 5: Record results in the business test document**

文档必须包含：

- 命令和完成时间。
- 角色数、action group 数、task 数和 round 数。
- 前 12 个 task 的 character/group/action 编排。
- 每组 selected count 的最小值和最大值。
- preview 前后状态 SHA256。
- resume 前后 selected count 汇总。
- Mock 归档文件路径。

- [ ] **Step 6: Commit business acceptance evidence**

```powershell
git add docs/blackboard_action_group_rounds_business_test_20260712.md
git commit -m "test: verify blackboard action group batch orchestration"
```

---

### Task 8: Run real NovelAI business acceptance

**Files:**
- Modify: `docs/blackboard_action_group_rounds_business_test_20260712.md`
- Generated but do not commit: configured NovelAI output directory.

**Interfaces:**
- Consumes: the same production Batch/Composer/Policy/Renderer chain.
- Produces: real image paths and PNG/render parameter evidence.

- [ ] **Step 1: Run two complete rounds with real NovelAI**

Because `nt=3` means each task generates three images, limit real execution to six tasks:

```powershell
uv run python -m tags_machine_core run-batch examples/batches/blackboard_action_new_manga_monochrome.yaml --fresh --limit 6 --log-level info --full
```

Expected:

- Six tasks form two rounds of three actions.
- The first three tasks share character/group; the next three share the next character/group.
- Every successful task archives `prompt_bundle.json`, `render_request.json`, `generation_result.json` and PNG parameters.

- [ ] **Step 2: Inspect real task artifacts**

For each of six tasks verify:

- `composer_type == "script"`.
- Prompt Policy is enabled with the expected default template.
- artist ref equals the configured artist.
- model is `nai-diffusion-4-5-full` unless the artist backend hint explicitly overrides it.
- resolution is one of the three standard sizes.
- request uses one image per NovelAI call while producing the configured `nt=3` result count.
- character captions follow the current NovelAI Renderer rules.

- [ ] **Step 3: Perform visual business review**

人工查看输出图，记录：

- artist 画风是否稳定。
- 每个 round 的角色是否正确。
- action 是否与 action node 主题一致。
- 两个 round 是否确实切换角色和动作组。
- 是否出现明显角色名称丢失、重复图或错误 character caption。

- [ ] **Step 4: Append real acceptance results**

在业务验收文档增加：

- 六个 task id。
- 实际图片绝对路径。
- 每个 task 的 model、尺寸、seed 和 artist。
- 人工视觉结论。
- 与旧 `run_tags_machine` 业务节奏的差异说明。

- [ ] **Step 5: Run the focused regression gate**

Run:

```powershell
uv run python -m pytest tests/test_batch_generation.py -q
uv run python -m tags_machine_core verify-core
```

Expected: all tests PASS and `verify-core` succeeds.

- [ ] **Step 6: Commit final acceptance evidence**

```powershell
git add docs/blackboard_action_group_rounds_business_test_20260712.md
git commit -m "test: verify real blackboard round generation"
```

---

## Completion Criteria

- `action_new` resolves to the real matched folder count instead of one flattened group.
- The production example creates 300 tasks as 3-action rounds.
- Characters switch only after the current sampled group actions finish.
- `balanced_random` uses run-directory history without YAML path configuration.
- `plan-batch` is state read-only.
- retry and resume are idempotent at round level.
- `--fresh` resets planning history.
- Mock business acceptance and real NovelAI acceptance both have archived evidence.
- Existing Composer, Policy, Renderer and non-action-group batch tests remain green.
