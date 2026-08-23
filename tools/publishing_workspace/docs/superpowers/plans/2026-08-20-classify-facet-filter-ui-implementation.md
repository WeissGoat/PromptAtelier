# Classify Facet Filter UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将月历素材搜索中的 `classify.yaml` 筛选改为按字段动态添加、按值多选的分组控件，并确保 `Subtype` 可直接选择。

**Architecture:** 保留现有 `AssetSearchService` 的筛选协议和语义。页面从 `/api/assets/facets` 获取当前 import 的字段和值，只渲染已添加的字段组；字段组内使用标签和下拉选择维护 `state.filters.facets`，不同字段仍由后端执行 AND，同字段多个值仍由后端执行 OR。

**Tech Stack:** 原生 HTML/CSS/JavaScript、FastAPI、pytest。

## Global Constraints

- 不改变 `classify.yaml` 解析和 `/api/assets/search` 请求格式。
- `subtype` 使用现有 facet 字段，不新增专用后端分支。
- 不选择任何字段时不启用 classify 过滤。
- 不同字段同时满足，同字段任意命中。
- 只修改 Publishing Workspace 相关文件，不覆盖其他未提交改动。

## Task 1: Replace the facet controls

**Files:**
- Modify: `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.html`
- Modify: `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.js`
- Modify: `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.css`

- [ ] Add an `添加筛选` control and keep `清空全部`.
- [ ] Render active fields as groups with a display label, raw field name, selected chips, clear button, and a select whose first option is `继续选择`.
- [ ] Exclude selected values from the select and remove an empty field group from the request state.
- [ ] Keep `state.filters.facets` as `{field: [value]}` so existing API behavior remains unchanged.
- [ ] Use the order `phase`, `species`, `cast`, `domain`, `subtype`, `pose`, `environment`, `tone`, `flags`, `clothing`, while allowing any field returned by the API.

## Task 2: Verify business behavior

**Files:**
- Modify: `tools/publishing_workspace/tests/test_schedule_api.py`
- Modify: `tools/publishing_workspace/tests/test_plan_search.py` only if a missing `subtype` assertion is found.

- [ ] Verify the page contains the new facet control text and `Subtype` display label.
- [ ] Verify an API search request with `facets={"subtype": ["kiss"]}` is accepted.
- [ ] Verify existing same-field OR and cross-field AND behavior remains covered.
- [ ] Run `uv run --with tzdata pytest tools/publishing_workspace/tests -q`.
- [ ] Run JavaScript syntax validation with Node.js.

## Task 3: Documentation

**Files:**
- Modify: `tools/publishing_workspace/README.md`
- Modify: `tools/publishing_workspace/docs/acceptance-monthly-publishing-calendar.md`

- [ ] Document dynamic facet groups, selected chips, `Subtype`, and the OR/AND semantics.
- [ ] Keep the documented API request shape unchanged.
