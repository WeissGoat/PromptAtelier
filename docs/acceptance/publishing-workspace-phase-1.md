# Publishing Workspace 第一阶段业务验收

验收日期：2026-07-27

## 1. 真实 NeeView 输入

输入：

```text
E:/NeeView41.3/Profile/Playlists/post_20251210.nvpls
```

结果：

- 原列表 10 项，导入 10 项。
- 缺失 0，失败 0，唯一资产 10。
- 这组已处理投稿图没有保留新旧节点字段，10 项均明确记录为 `unknown`。
- 分类结果生成 `unknown/unknown/unknown/unknown.nvpls`，成员顺序与原列表一致。

该结果验证了真实 NeeView JSON、真实文件路径、快照和无节点降级行为。

## 2. 真实旧版图片

输入目录：

```text
C:/Users/WhiteSheep/Downloads/20260602_温泉MMF夹心
```

结果：

- 导入 5 张图片，失败 0。
- `LegacyImageNodeReader` 命中 1 张，其他 4 张下载图没有旧节点字段，记录为 `unknown`。
- 旧图分类视图为：

```text
20260406/
  1adanbooru_akemi_homura_暁美ほむら _魔法少女 - 快捷方式/
    new/
      20260528_海滩吃棒冰.nvpls
```

该结果验证了旧 `artist/character/topic/action` 到统一节点 role 的实际映射。

## 3. 当前 core PNG 写入契约

使用当前 `execute_mock_generation -> save_generated_images -> write_png_text_chunks` 链路生成 PNG，节点包含：

```text
artist=20260412
character=akemi_homura
action_group=st_sfw
action=standing
```

首次验收发现，`tags_machine_core` 文本块位于 PNG 的 IDAT 之后，Pillow 仅 `Image.open()` 时不会把它放入 `image.info`。Catalog 已改为复用现有 `read_png_text_chunks()`，完整读取 `tEXt/zTXt/iTXt`。

修复后的业务结果：

- `reader_counts.core = 1`
- 分类视图为 `20260412/akemi_homura/st_sfw/standing.nvpls`
- 首次 `.nvpls` 导出 `written = 1`
- 第二次相同导出 `skipped = 1`，文件不重写

## 4. Windows 快捷方式往返

- 对同一 core Asset 启用 `windows_shortcut`，成功生成 1 个 `.lnk`。
- 再使用 `DirectoryInputAdapter --recursive` 导入该快捷方式树。
- 快捷方式成功解析回原图，唯一资产仍为 1，`CoreImageNodeReader` 再次命中。
- PowerShell 与 Python 之间使用环境变量传递绝对路径，可处理空格和中文路径。

## 5. 当前批量任务的 action_group 反查

使用已有真实任务归档：

```text
G:/ai_auto/blackboard-style-rounds-400/949b8f34_232_0_233_cff70992/render_request.json
```

该归档的 `meta.node_refs` 只有 `artist/character/action`，没有 `action_group`。使用原 RenderRequest 通过当前 PNG 写入链路生成验收图后，Publishing 的结果为：

```text
109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable/
  danbooru_akemi_homura_暁美ほむら _魔法少女/
    pn_human_1boy1girl_sex_missionary_lying_bondage_nude/
      20260507_女仆捆绑强奸_4star.nvpls
```

`action_group` 来自 action ref 相邻的真实 `category_view_manifest.json`，不是测试中手工补入。

## 6. 自动化验证

Publishing 测试覆盖：

- 工作区重复初始化不覆盖配置。
- NeeView 顺序和缺失项 warning。
- Core 优先与损坏后 Legacy fallback。
- 内容 SHA-256 去重。
- 多角色展开多个视图。
- `.nvpls` 增量跳过。
- CLI 初始化和导入。

完整回归命令：

```powershell
uv run pytest tests -q
```
