# Web 随机节点角色根目录与过滤器业务验收

**日期：** 2026-07-26
**环境：** Windows，本地 PromptAtelier Web，真实 NovelAI API

## 1. 服务

```text
Frontend: http://127.0.0.1:53173/
Backend:  http://127.0.0.1:8765/api
Config:   configs/local.yaml
```

通过 `uv run python scripts/dev_web.py` 启动，前后端均正常运行。

## 2. 角色相对路径

### Folder

```text
Role: action
Folder: new
实际根目录: F:/my_project/new/tags_machine/design/动作改2/new
原始候选: 1719
可用候选: 1719（未启用 classify.yaml 过滤）
```

候选辅助路径为 `new/<节点名>`，不再要求输入或显示 `动作改2/new` 作为来源值。

### Glob

```text
Role: action
Glob: new/*足部*
候选: 15
首个候选相对路径: new/20260507_窗边足部展示_4star
```

### 边界错误

真实 Web API 结果：

```text
绝对路径 -> HTTP 400
随机节点路径必须相对 action 根目录

../角色/* -> HTTP 400
随机节点路径必须位于 action 根目录内
```

Collection 路径语义由后端回归测试覆盖，保持现有工程配置行为。

## 3. 二次过滤交互

浏览器实际操作：

1. 点击“添加筛选”，选择 `Domain`。
2. 在复选下拉中依次选择 `foot` 和 `body`，无需 Ctrl/Shift。
3. 界面同时出现 `foot`、`body` 两个可删除标签。
4. 点击 `body` 标签的删除按钮，只取消 `body`，`foot` 保留。
5. 增加 `Subtype=sole_focus`，得到两条有效字段。
6. 点击“清空全部”，所有过滤字段消失，界面显示“未启用过滤”。

候选统计：

```text
无过滤:
  raw_total: 1719
  total: 1719
  missing_classify: 0
  classify_mismatch: 0

domain=foot AND subtype=sole_focus:
  raw_total: 1719
  total: 40
  missing_classify: 0
  classify_mismatch: 1679
  invalid_classify: 0
  invalid_node: 0
```

页面刷新后，已选择的字段和值从 Workspace 恢复；仅添加但未选值的空字段不会恢复。

## 4. NovelAI 真实出图

配置：

```text
Artist: 109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable
Character: danbooru_akemi_homura_暁美ほむら _魔法少女
Action source: Folder new
Action filter: domain=foot AND subtype=sole_focus
Resolution: 1024x1024
NT: 1
Seed: 424242
Model: nai-diffusion-4-5-full
n_samples: 1
```

输出图片：

```text
F:/my_project/new/tags_machine/refactor/outputs/random_20260726031511_b9cb4227/group_001_seed_424242/59c55f89_424242_01.png
```

实际抽中的 Action：

```text
F:/my_project/new/tags_machine/design/动作改2/new/20260510_群交倒位骑乘_4star
relative: new/20260510_群交倒位骑乘_4star
```

该节点 `classify.yaml` 实际包含：

```yaml
domain:
  - foot
subtype:
  foot:
    - sole_focus
```

图片生成成功，尺寸为 `1024x1024`。`inspect-image-params --normalized` 可读取完整 NovelAI 参数，PNG 原始 `tags_machine_core` 文本块包含：

```json
{
  "random_nodes": [
    {
      "slot_id": "primary-action",
      "role": "action",
      "source": {
        "type": "folder",
        "value": "new",
        "recursive": false
      },
      "filters": {
        "classify": {
          "domain": ["foot"],
          "subtype": ["sole_focus"]
        }
      },
      "candidate": {
        "name": "20260510_群交倒位骑乘_4star",
        "relative": "new/20260510_群交倒位骑乘_4star"
      },
      "pool_stats": {
        "raw_total": 1719,
        "total": 40,
        "classify_mismatch": 1679
      }
    }
  ]
}
```

## 5. AgentComposer 边界

本次真实 Web Generate Primary 使用现有 ScriptComposer，PNG 记录：

```text
composer_type: script
composer_version: v1
```

本次实现未修改 AgentComposer、Hash 或缓存文件。执行：

```text
uv run python -m pytest tests/test_agent_composer.py -q
```

结果：

```text
14 passed
```

随机池继续在 Composer 前解析成普通 `NodeDocument`，AgentComposer 不接收 `NodePoolSpec` 或前端过滤器状态。

## 6. 自动回归

```text
Backend focused: 24 passed
AgentComposer: 14 passed
Frontend: 19 files, 90 passed
Frontend production build: passed
```

## 7. 已知迁移边界

旧浏览器 Workspace 若保存了 `动作改2/new`，新版会按设计返回角色根目录相对路径错误。将来源改为 `new` 后即可正常扫描；未增加长期兼容分支。
