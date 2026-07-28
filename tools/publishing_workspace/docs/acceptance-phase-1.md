# Publishing Workspace 第一阶段业务验收

验收日期：2026-07-28

验收入口：

```powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run publishing-workspace ...
```

本次全部业务验收均通过独立项目执行，没有 import 或调用 `tags_machine_core`。

## 1. 真实 NeeView 输入

输入：

```text
E:/NeeView41.3/Profile/Playlists/post_20251210.nvpls
```

结果：

- 原列表 10 项，导入 10 项。
- 缺失 0，失败 0，唯一资产 10。
- 这组已处理投稿图没有保留新旧节点字段，`reader_counts.unknown = 10`。
- 分类结果生成 `unknown/unknown/unknown/unknown.nvpls`，成员顺序与原列表一致。

该结果验证了真实 NeeView JSON、真实文件路径、导入快照和无节点降级行为。

## 2. 真实旧版与新版图片混合目录

输入目录：

```text
C:/Users/WhiteSheep/Downloads/20260602_温泉MMF夹心
```

结果：

- 扫描并导入 5 张图片，缺失 0，失败 0。
- `reader_counts.legacy = 1`。
- `reader_counts.core = 3`。
- `reader_counts.unknown = 1`。
- 旧图中的 `artist/character/topic/action` 正确映射到统一节点 role。

旧图分类视图包含：

```text
20260406/
  1adanbooru_akemi_homura_暁美ほむら _魔法少女 - 快捷方式/
    new/
      20260528_海滩吃棒冰.nvpls
```

## 3. 当前 Core PNG 与 action_group 反查

输入当前批量任务归档目录：

```text
G:/ai_auto/blackboard-style-rounds-400/949b8f34_232_0_233_cff70992
```

结果：

- 目录包含 3 张生成图和 1 张参数图。
- `reader_counts.core = 3`，参数图记录为 `unknown`。
- 原 RenderRequest 的 `meta.node_refs` 只有 `artist/character/action`，没有 `action_group`。
- `ActionGroupManifestEnricher` 从 action ref 相邻的真实 `category_view_manifest.json` 补出了动作组。

最终视图包含：

```text
109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable/
  danbooru_akemi_homura_暁美ほむら _魔法少女/
    pn_human_1boy1girl_sex_missionary_lying_bondage_nude/
      20260507_女仆捆绑强奸_4star.nvpls
```

## 4. NeeView 增量导出

在同一个示例 Catalog 中完成上述三次真实导入后：

- Catalog 共 19 个唯一资产。
- 分类计划生成 4 个视图。
- 首次 `.nvpls` 导出：`written = 4`，`skipped = 0`。
- 第二次相同导出：`written = 0`，`skipped = 4`。

第二次导出没有重写内容未变化的播放列表，验证了 Exporter 幂等状态。

## 5. Windows 快捷方式往返

真实分类路径中包含中文、日文和较长节点名称。验收发现 `WScript.Shell` 在直接创建或读取接近 260 字符的 `.lnk` 路径时会报 `Value does not fall within the expected range`。

修复后的策略：

- 导出时先在同卷的短临时目录创建 `.lnk`，再原子移动到最终分类路径。
- 导入时先把 `.lnk` 复制到系统短临时目录，再读取其中的目标路径。
- 原图和最终分类目录都不复制、不移动。

修复后结果：

- `windows_shortcut` 成功导出 4 个视图，共 19 个 `.lnk`。
- 对快捷方式树执行 `DirectoryInputAdapter --recursive` 往返导入。
- `total_items = 19`，`imported_items = 19`，`missing_items = 0`，`failed_items = 0`。
- 往返读取命中 `legacy = 1`、`core = 6`、`unknown = 12`。

## 6. 自动化回归

独立项目：

```powershell
uv run pytest -q
```

结果：`15 passed`，其中包含 Windows COM 超 260 字符快捷方式路径的实际往返测试，以及旧配置/Catalog 的迁移恢复测试。

Core 根项目：

```powershell
uv run pytest tests -q
```

结果：`574 passed, 34 subtests passed`，只有现有 Starlette/httpx 弃用 warning。

边界检查：

- `publishing_workspace/src` 没有 `tags_machine_core` import。
- 保留的 `tags_machine_core` 字符串仅用于读取外部 PNG key。
- `python -m tags_machine_core publish` 已返回未知命令。
- 示例 `workspace.yaml` 可进入 Git，`catalog.sqlite`、导入快照和导出结果均被忽略。
- 旧 `tags-machine-core.publish-workspace/v1` 配置会备份原文件，并保留未知字段后升级为新 schema。
- 旧 Catalog 的 `schema_meta(version)` 会在事务内补充 `schema_id`，已有导入记录保持不变；中断后的 `schema_id=NULL` 状态可以续跑恢复。
