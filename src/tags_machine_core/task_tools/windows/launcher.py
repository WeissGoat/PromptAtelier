from __future__ import annotations

from dataclasses import dataclass

import tkinter as tk
from tkinter import messagebox, ttk

from ..config import OperationPlacement, TaskToolsConfig
from ..models import TaskContextSet
from ..registry import OperationRegistry
from ..runner import TaskToolRunner


@dataclass(frozen=True, slots=True)
class LauncherItem:
    operation_id: str
    label: str
    order: int
    enabled: bool
    disabled_reason: str = ""


@dataclass(frozen=True, slots=True)
class LauncherResource:
    name: str
    path: str
    exists: bool


@dataclass(frozen=True, slots=True)
class LauncherViewModel:
    task_count: int
    input_paths: tuple[str, ...]
    action_resources: tuple[LauncherResource, ...]
    artist_resources: tuple[LauncherResource, ...]
    items: tuple[LauncherItem, ...]


def build_launcher_items(
    *,
    contexts: TaskContextSet,
    registry: OperationRegistry,
    config: TaskToolsConfig,
    runner: TaskToolRunner,
) -> list[LauncherItem]:
    """构建 Launcher 操作模型，不解析任务，也不执行操作。"""
    items: list[LauncherItem] = []
    for spec in registry.all():
        override = config.operations.get(spec.id)
        if override is not None and not override.enabled:
            continue

        placement = (
            override.placement
            if override is not None and override.placement is not None
            else spec.default_placement
        )
        if placement not in (OperationPlacement.LAUNCHER, OperationPlacement.BOTH):
            continue

        availability = runner.availability(spec.id, contexts)
        items.append(
            LauncherItem(
                operation_id=spec.id,
                label=(
                    override.label
                    if override is not None and override.label is not None
                    else spec.default_label
                ),
                order=(
                    override.order
                    if override is not None and override.order is not None
                    else spec.default_order
                ),
                enabled=availability.enabled,
                disabled_reason=availability.reason if not availability.enabled else "",
            )
        )
    return sorted(items, key=lambda item: (item.order, item.operation_id))


def build_launcher_view_model(
    *,
    contexts: TaskContextSet,
    registry: OperationRegistry,
    config: TaskToolsConfig,
    runner: TaskToolRunner,
) -> LauncherViewModel:
    """把既有任务上下文与 Runner 状态转换为可测试的窗口模型。"""
    return LauncherViewModel(
        task_count=len(contexts.tasks),
        input_paths=tuple(str(task.input_path) for task in contexts.tasks),
        action_resources=_build_resource_items(contexts, "action"),
        artist_resources=_build_resource_items(contexts, "artist"),
        items=tuple(
            build_launcher_items(
                contexts=contexts,
                registry=registry,
                config=config,
                runner=runner,
            )
        ),
    )


def _build_resource_items(
    contexts: TaskContextSet,
    role: str,
) -> tuple[LauncherResource, ...]:
    result: list[LauncherResource] = []
    unresolved_by_name: dict[str, int] = {}
    seen_locations: set[tuple[str, str]] = set()
    for resource in contexts.resources_for(role):
        name = resource.id or resource.ref or "未提供名称"
        identity = (resource.id or resource.ref or "").casefold()
        if resource.path is None:
            if identity and (
                identity in unresolved_by_name
                or any(item.name.casefold() == identity for item in result)
            ):
                continue
            if identity:
                unresolved_by_name[identity] = len(result)
            result.append(LauncherResource(name=name, path="未提供目录路径", exists=False))
            continue

        path = str(resource.path)
        location_key = (identity, path.casefold())
        if location_key in seen_locations:
            continue
        seen_locations.add(location_key)
        item = LauncherResource(name=name, path=path, exists=resource.exists)
        if identity in unresolved_by_name:
            result[unresolved_by_name.pop(identity)] = item
        else:
            result.append(item)
    return tuple(result)


def _run_launcher_item(
    *,
    item: LauncherItem,
    contexts: TaskContextSet,
    runner: TaskToolRunner,
    parent: tk.Misc,
) -> None:
    try:
        runner.run(item.operation_id, contexts)
    except Exception as exc:
        # Runner 已经通过既有日志链路记录完整异常，这里只负责用户提示。
        messagebox.showerror(
            "任务工具错误",
            f"执行“{item.label}”失败：{exc}",
            parent=parent,
        )


def launch_task_tools_window(
    *,
    contexts: TaskContextSet,
    registry: OperationRegistry,
    config: TaskToolsConfig,
    runner: TaskToolRunner,
) -> int:
    """显示原生窗口，并把操作委托给已经初始化日志的 Runner。"""
    model = build_launcher_view_model(
        contexts=contexts,
        registry=registry,
        config=config,
        runner=runner,
    )
    window = tk.Tk()
    window.title("Refactor 任务工具")
    window.resizable(False, False)

    content = ttk.Frame(window, padding=12)
    content.grid(sticky="nsew")
    ttk.Label(content, text=f"任务数：{model.task_count}").grid(
        row=0, column=0, columnspan=2, sticky="w"
    )
    ttk.Label(content, text="输入摘要：").grid(row=1, column=0, sticky="nw", pady=(8, 0))
    ttk.Label(
        content,
        text="\n".join(model.input_paths) or "未提供输入路径",
        justify="left",
        wraplength=640,
    ).grid(row=1, column=1, sticky="w", pady=(8, 0))

    resource_frame = ttk.LabelFrame(content, text="关联资源", padding=8)
    resource_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    _add_resource_rows(resource_frame, "Action", model.action_resources, 0)
    _add_resource_rows(resource_frame, "Artist", model.artist_resources, 1)

    operation_frame = ttk.LabelFrame(content, text="可用操作", padding=8)
    operation_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    if not model.items:
        ttk.Label(operation_frame, text="没有可显示的操作").grid(sticky="w")
    for row, item in enumerate(model.items):
        button = ttk.Button(
            operation_frame,
            text=item.label,
            command=lambda current=item: _run_launcher_item(
                item=current,
                contexts=contexts,
                runner=runner,
                parent=window,
            ),
        )
        button.grid(row=row, column=0, sticky="w", pady=2)
        if not item.enabled:
            button.state(("disabled",))
            ttk.Label(operation_frame, text=item.disabled_reason).grid(
                row=row, column=1, sticky="w", padx=(8, 0)
            )

    window.mainloop()
    return 0


def _add_resource_rows(
    parent: ttk.LabelFrame,
    role_label: str,
    resources: tuple[LauncherResource, ...],
    row: int,
) -> None:
    if not resources:
        ttk.Label(parent, text=f"{role_label}：未找到关联资源").grid(
            row=row, column=0, sticky="w", pady=2
        )
        return
    lines = []
    for resource in resources:
        state = "目录存在" if resource.exists else "目录缺失"
        lines.append(f"{role_label}：{resource.name}\n路径：{resource.path}\n状态：{state}")
    ttk.Label(parent, text="\n".join(lines), justify="left", wraplength=640).grid(
        row=row, column=0, sticky="w", pady=2
    )
