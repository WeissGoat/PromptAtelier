# Windows 任务便捷工具设计

## 1. 背景

refactor 的批量生图任务会在输出目录中归档 `prompt_bundle.json`、`render_request.json`、`generation_result.json` 等文件。归档中已经包含本次任务使用的 Action、Artist、Character 等节点引用和实际路径。

当前常见工作流是从类似下面的任务目录返回对应设计节点：

```text
G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f
```

第一阶段需要提供两个高频操作：

- 打开对应 Action 节点目录。
- 打开对应 Artist 节点目录。

旧系统主要通过 Windows SendTo 中的多个 `.bat` 文件实现。新工具仍保留 SendTo 的低侵入优势，但必须避免把归档解析、操作逻辑和菜单入口耦合在脚本中。后续新增打开文件、复制路径、参数检查、重新执行等操作时，不应重复实现任务解析逻辑。

## 2. 目标

- 支持对任务目录、任务内 PNG、任务内 JSON 使用 Windows SendTo。
- 默认提供“打开 Action 目录”和“打开 Artist 目录”两个高频快捷项。
- 提供一个“Refactor 工具...”统一窗口，用于承载后续增加的操作。
- 每个操作可配置显示在高频快捷项、统一窗口或两者中。
- 统一解析任务归档，操作 Handler 不直接读取归档 JSON。
- 支持多选任务，并对重复目标路径去重。
- 安装后重启 Windows 仍可使用，通常不需要重启 Explorer。
- 安装、同步和卸载时不修改用户现有的 `ct.*` SendTo 项。
- 错误可见、可定位，不通过闪退的终端窗口报告。

## 3. 非目标

- 第一阶段不注册 Windows Explorer 原生注册表菜单。
- 第一阶段不允许 YAML 配置任意 Python 模块、PowerShell 或可执行文件。
- 第一阶段不支持从任务目录名猜测节点。
- 第一阶段不扫描整个 `design` 目录寻找同名节点。
- 第一阶段不实现重新跑图、修改节点或删除节点等有副作用操作。
- 第一阶段不将工具打包为独立 EXE；先复用 refactor 的 Python 环境。

## 4. 用户交互

### 4.1 高频快捷项

安装后 SendTo 默认增加：

```text
Refactor - 打开 Action 目录
Refactor - 打开 Artist 目录
Refactor 工具...
```

选择一个或多个任务目录、PNG 或 JSON 后，通过“右键 -> 发送到”执行。

高频快捷项直接执行操作。成功时只打开资源管理器，不弹出额外窗口；失败时显示 Windows 消息框。

### 4.2 统一工具窗口

“Refactor 工具...”接收同样的输入路径，先展示解析结果，再展示当前可用操作。

窗口至少展示：

- 输入任务数量。
- Action 名称及路径状态。
- Artist 名称及路径状态。
- 可执行操作。
- 不可执行操作及禁用原因。

操作列表来自 OperationRegistry 和有效配置，不在窗口代码中写死。

## 5. 总体架构

```text
SendTo 快捷项 / Refactor 工具窗口
                |
                v
          CommandRouter
                |
                v
       TaskContextResolver
                |
                v
          TaskContextSet
                |
                v
       OperationRegistry
                |
                v
       OperationHandler
```

### 5.1 Shell 入口层

职责：

- 接收 Explorer 传入的一个或多个路径。
- 区分快捷操作和统一窗口模式。
- 将参数交给 Python 工具入口。

该层不解析归档，不包含节点路径规则。

### 5.2 CommandRouter

统一命令模型：

```text
task-tools run <operation_id> <input...>
task-tools launcher <input...>
task-tools install-sendto
task-tools sync-sendto
task-tools uninstall-sendto
```

职责：

- 加载有效配置。
- 调用 TaskContextResolver。
- 从 OperationRegistry 获取操作。
- 校验操作是否支持当前输入。
- 调用 Handler，并统一处理错误和日志。

### 5.3 TaskContextResolver

职责：

- 将目录、PNG、JSON 输入定位到最近的任务归档目录。
- 读取归档文件并生成统一 TaskContext。
- 合并节点引用、Artist 路径和归档文件状态。
- 不执行打开目录、复制路径等操作。

### 5.4 OperationRegistry

职责：

- 注册所有受支持的 OperationSpec。
- 根据平台、配置和 TaskContext 判断操作是否可用。
- 向 SendTo 安装器和统一窗口提供相同的操作定义。

配置只能覆盖已注册操作的展示属性，不能注入任意代码。

### 5.5 OperationHandler

每个 Handler 只完成一个操作，例如打开目录。Handler 接收已经解析好的 `TaskContextSet`，不直接读取 `render_request.json`。

第一阶段只实现：

- `open_action_directory`
- `open_artist_directory`

后续可以增加：

- `open_action_meta`
- `open_artist_tags`
- `copy_action_path`
- `copy_artist_path`
- `inspect_render_params`
- `rerun_task`

## 6. 数据模型

### 6.1 RelatedResource

```text
RelatedResource
  role: str
  id: str | null
  ref: str | null
  path: Path | null
  index: int
  exists: bool
  source: str
```

字段含义：

- `role`：`action`、`artist`、`character`、`background` 等角色。
- `id`：归档中的节点标识。
- `ref`：归档中的原始引用。
- `path`：解析后的绝对路径。
- `index`：同类节点中的顺序。
- `exists`：目标路径当前是否存在。
- `source`：该信息来自哪个归档字段，便于排错。

### 6.2 TaskContext

```text
TaskContext
  input_path: Path
  task_dir: Path
  archive_files: dict[str, Path]
  resources: list[RelatedResource]
  render_request: RenderRequest | dict | null
  prompt_bundle: PromptBundle | dict | null
  generation_result: GenerationResult | dict | null
  warnings: list[str]
```

TaskContext 提供按角色获取资源的方法，但不假设每种角色只有一个节点。

### 6.3 TaskContextSet

```text
TaskContextSet
  tasks: list[TaskContext]
```

TaskContextSet 负责：

- 保留多选输入顺序。
- 去重重复任务目录。
- 按资源角色汇总并去重目标路径。

## 7. 归档解析规则

### 7.1 定位任务目录

1. 输入为目录时，从该目录开始查找。
2. 输入为文件时，从文件所在目录开始查找。
3. 向上寻找最近包含受支持归档文件的目录。
4. 到达磁盘根目录后仍未找到则失败。
5. 不递归扫描子目录，避免对大型输出目录做昂贵遍历。

### 7.2 归档优先级

优先读取 `render_request.json`：

- Action、Character、Background 等节点从 `meta.node_refs` 获取。
- Artist 实际路径优先从 `artist_payload.path` 获取。

`prompt_bundle.json` 用于补充节点引用和节点名称。

`generation_result.json` 只作为后续操作的数据来源，不作为第一阶段节点路径的主要来源。

### 7.3 路径状态

归档中存在引用但路径已移动时：

- 保留 RelatedResource。
- 设置 `exists: false`。
- 在统一窗口中显示原路径。
- 禁用要求路径存在的操作。
- 不自动按名称搜索其他目录，以免打开错误节点。

## 8. 操作定义与配置

### 8.1 OperationSpec

代码注册的操作包含：

```text
OperationSpec
  id
  default_label
  supported_platforms
  supported_targets
  supports_multiple_tasks
  supports_multiple_resources
  default_placement
  default_order
  handler
```

### 8.2 配置结构

```yaml
schema: prompt-atelier.task-tools/v1

operations:
  open_action_directory:
    enabled: true
    placement: both
    order: 10

  open_artist_directory:
    enabled: true
    placement: both
    order: 20
```

可覆盖字段：

- `enabled`：是否启用操作。
- `placement`：`quick`、`launcher` 或 `both`。
- `label`：可选显示名称覆盖。
- `order`：显示顺序。

`placement` 语义：

- `quick`：只生成独立 SendTo 快捷项。
- `launcher`：只显示在统一窗口。
- `both`：两边都显示。

未配置的操作使用代码内默认值。配置中出现未知 operation id 时启动失败并给出明确错误，避免拼写错误被静默忽略。

## 9. Windows 安装与持久化

### 9.1 安装位置

SendTo 快捷项位于：

```text
%APPDATA%\Microsoft\Windows\SendTo
```

稳定启动器和安装状态位于：

```text
%LOCALAPPDATA%\PromptAtelier\TaskTools
```

安装状态记录：

- refactor 项目根目录。
- Python 解释器路径。
- task-tools 配置路径。
- 当前由工具管理的 SendTo 快捷项。
- 安装版本。

### 9.2 启动方式

SendTo 快捷方式指向 LocalAppData 中的稳定启动器。启动器读取安装状态，再调用 refactor `.venv\Scripts\pythonw.exe`。

这样可以保证：

- Windows 重启后快捷项仍存在。
- 正常执行时不显示控制台窗口。
- 配置和项目定位集中管理。
- 环境失效时可以弹出明确提示。

如果项目目录被移动，需要重新执行 `install-sendto` 或 `sync-sendto` 更新安装状态。

### 9.3 安装器约束

- 只创建带有 PromptAtelier 管理标识的快捷项。
- 只删除安装状态中记录的快捷项。
- 不按文件名前缀批量删除用户现有 SendTo 内容。
- `sync-sendto` 根据有效 placement 增删快捷项。
- `uninstall-sendto` 删除本工具快捷项和 LocalAppData 启动器，不删除日志以外的用户数据。

## 10. 统一工具窗口

第一阶段使用 Python 标准库 `tkinter`，由 `pythonw.exe` 启动。

窗口组成：

- 输入任务摘要。
- 关联资源列表。
- 可用操作列表。
- 禁用操作及原因。
- 执行状态和错误信息。

窗口不写死操作按钮。它按配置排序 OperationSpec，并根据 Handler 能力判断是否可用。

第一阶段不加入复杂主题、历史记录和参数表单。后续需要带参数操作时，在 OperationSpec 中增加参数描述，再由窗口生成对应控件。

## 11. 错误处理与日志

错误分类：

- 输入错误：所选路径不存在。
- 归档错误：找不到任务归档或 JSON 无法解析。
- 资源错误：节点引用存在但目录不存在。
- 环境错误：项目目录或 Python 环境失效。
- 操作错误：Explorer 启动失败等。

展示规则：

- 高频快捷项通过 Windows 消息框显示错误。
- 统一窗口在窗口内显示错误，必要时提供详情。
- 正常成功不弹消息框。

日志写入：

```text
%LOCALAPPDATA%\PromptAtelier\TaskTools\logs
```

日志不写入任务目录，不污染 refactor Git 工作区。默认记录错误；可通过配置提高到 info 或 trace。

## 12. 建议代码结构

```text
src/tags_machine_core/task_tools/
  __init__.py
  cli.py
  config.py
  models.py
  resolver.py
  registry.py
  runner.py
  operations/
    __init__.py
    open_directory.py
  windows/
    __init__.py
    launcher.py
    notifications.py
    sendto_installer.py

configs/
  task_tools.example.yaml

scripts/
  install_task_tools.ps1
```

PowerShell 脚本只提供便于人工安装的薄入口，实际安装逻辑由 Python 模块负责。

## 13. 第一阶段验收

使用真实任务目录：

```text
G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f
```

必须验证：

1. Resolver 解析出的 Action 路径与 `render_request.meta.node_refs` 一致。
2. Resolver 解析出的 Artist 路径与 `render_request.artist_payload.path` 一致。
3. “打开 Action 目录”打开实际 Action 节点目录。
4. “打开 Artist 目录”打开实际 Artist 节点目录。
5. 对任务内 PNG 执行时能定位到同一个任务目录。
6. 多选引用同一 Artist 的任务时只打开一个 Artist 目录。
7. 统一窗口显示正确的 Action、Artist 名称和路径状态。
8. `placement` 在 `quick`、`launcher`、`both` 之间切换后，`sync-sendto` 结果正确。
9. 安装、同步和卸载不修改已有 `ct.*` SendTo 文件。
10. Windows 重启后 SendTo 快捷项仍存在并可启动。
11. 缺少归档、JSON 损坏、路径移动和虚拟环境失效时均有明确错误提示。

## 14. 后续扩展

后续新增操作时遵循以下流程：

1. 实现一个独立 Handler。
2. 在 OperationRegistry 注册 OperationSpec。
3. 为默认 placement 和顺序提供合理值。
4. 增加真实任务归档验收。
5. 用户通过配置决定该操作显示在高频快捷项、统一窗口或两者中。

新增操作不应修改 TaskContextResolver，除非操作确实需要归档中尚未建模的新数据。新增关联对象时只扩展 RelatedResource 解析，不应修改已有 Handler。
