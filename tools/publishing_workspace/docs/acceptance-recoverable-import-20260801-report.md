# 真实导入验收报告

## 基本信息

```text
验收日期：2026-08-01
输入：E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls
基准：10010 项，其中成功 9987 项，问题 23 项
```

本次验收使用独立工作区，没有修改、复制或移动输入播放列表引用的原始图片。

## 首次导入

```text
工作区：G:\ai_publish_acceptance\recoverable-import-20260801
run_id：8286009b83a84a6db8570ff2963ffed0
status：completed_with_errors
total_items：10010
parsed_new_items：9987
failed_items：23
unique_assets：9987
reader_counts：core=1001, legacy=8975, unknown=11
```

结果符合基准。23 个失败项进入问题队列，未影响其余图片入 Catalog。

## 重复导入

```text
工作区：G:\ai_publish_acceptance\recoverable-import-20260801
run_id：8271a73167514c1795a9ce07abbb1b83
status：completed_with_errors
total_items：10010
reused_path_items：9987
parsed_new_items：0
failed_items：0
held_problem_items：23
unique_assets：9987
```

结果符合预期：未变化图片全部命中路径缓存，原有问题没有被隐式重复解析。

## 中断恢复

```text
工作区：G:\ai_publish_acceptance\recoverable-import-20260801-interrupt-v2
run_id：179dcadc04f24fc3b478dfd06b8240b0
中断点：已提交 200 项
恢复方式：等待 90 秒租约过期后使用同一 run_id resume
status：completed_with_errors
total_items：10010
parsed_new_items：9987
failed_items：23
unique_assets：9987
reader_counts：core=1001, legacy=8975, unknown=11
```

恢复没有重新读取 NeeView 播放列表，已提交的 200 项没有重复创建 `import_items`，最终
结果与首次导入一致。

验收中曾发现 Windows 外部终止进程后 Run 会保持 `running`，原实现无法把它恢复到
`planned`。现已增加过期 `running` Run 的接管逻辑，并通过回归测试和本次真实重跑验证。

## 分类与导出

在中断恢复工作区执行全量分类和 NeeView 导出：

```text
分类视图：4626
unknown 视图：25
NeeView 写入：4626
NeeView 跳过：0
警告：0
```

分类和导出结果符合既有基准，后续输出只保存原始图片引用，没有复制或移动原始图片。

## 结论

本次真实业务验收通过：首次导入、重复导入、租约过期后的中断恢复、问题保持、分类
和 NeeView 导出均达到预期结果。
