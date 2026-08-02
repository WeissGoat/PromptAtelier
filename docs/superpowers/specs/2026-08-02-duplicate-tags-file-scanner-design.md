# tags.txt 重复文件扫描器设计

## 目标

在 `tools` 下提供一个只读脚本，递归扫描指定目录内的 `tags.txt`，按照标签集合语义识别内容重复的文件，并以 warning 分组输出全部重复路径。

该工具只负责审计，不修改、移动或删除节点文件。

## 命令入口

```powershell
uv run python tools/check_duplicate_tag_files.py <目录>
```

输入必须是一个存在的目录。路径不存在或不是目录时，脚本输出 error 并返回非零退出码。

## 扫描范围

- 从输入目录递归查找文件名严格等于 `tags.txt` 的文件。
- 使用稳定的路径顺序处理文件，保证多次运行输出顺序一致。
- 不根据 action、character、artist 或 background 类型增加特殊规则。
- 不写入被扫描目录，也不生成备份文件。

## 等价判定

每个 `tags.txt` 被拆成普通标签和控制行两部分，二者共同组成文件签名。

### 普通标签

- 使用逗号和换行作为标签边界。
- 去除标签首尾空白。
- 转换为小写。
- 将连续空白统一为下划线。
- 保留下划线，并将连续下划线压缩为一个。
- 移除空标签。
- 在单文件内去重后排序，因此标签出现顺序不影响签名。
- 保留括号、花括号、方括号和权重语法；带权重与不带权重的标签不等价。

例如下面两个文件判定为重复：

```text
black hair, 1girl
```

```text
1girl,
black_hair
```

### 控制行

以 `=` 开头，或首个逗号前的字段属于 `type`、`extension` 的行，作为完整控制行参与签名。

控制行会统一大小写和空白，但不会拆成普通标签。控制行不同的两个文件不判定为重复，避免将生成参数或扩展行为不同的节点合并到同一组。

## 输出

每个重复签名输出一组 warning：

```text
WARNING duplicate tags content group=1 (files=3, folders=3):
  normalized_tags: 1girl, black_hair
  control_lines: (none)
  folder: path/to/first
  tags_file: path/to/first/tags.txt
  folder: path/to/second
  tags_file: path/to/second/tags.txt
  folder: path/to/third
  tags_file: path/to/third/tags.txt
```

最后输出汇总：

```text
scanned=1200 duplicate_groups=3 duplicate_files=7 errors=0
说明: duplicate_groups=重复内容组数量；duplicate_files=参与重复的 tags.txt 文件总数
```

`duplicate_groups` 表示不同的重复内容组数量；`duplicate_files` 表示所有重复组中涉及的 `tags.txt` 文件总数。每个组还会列出规范化标签、控制行、节点文件夹和文件路径。

没有重复时只输出汇总。

## 错误与退出码

- `0`：扫描完成。发现重复仍返回 `0`，因为重复属于 warning。
- `1`：一个或多个 `tags.txt` 读取失败；继续扫描其他文件并在汇总中记录错误。
- `2`：输入路径不存在、不是目录或命令参数无效。

文件读取使用 `utf-8-sig`，无法解码时记录该文件错误，不使用静默丢弃字符的方式继续比较。

## 代码结构

- `tools/check_duplicate_tag_files.py`
  - CLI 参数解析。
  - 递归发现 `tags.txt`。
  - 标签和控制行规范化。
  - 生成稳定签名并按签名分组。
  - warning、错误和汇总输出。
- `tests/test_check_duplicate_tag_files.py`
  - 顺序、空格和下划线差异仍判定重复。
  - 权重不同不判定重复。
  - 控制行不同不判定重复。
  - 唯一文件不输出 warning。
  - 读取错误和非法根目录返回正确退出码。

## 验收标准

1. 对临时目录中的等价标签文件能够稳定分组。
2. 对真实动作目录执行时不产生任何文件变化。
3. 每个重复组完整列出涉及路径。
4. 同一输入重复运行，warning 分组和路径顺序一致。
5. 测试覆盖核心等价规则、控制行和错误处理。
