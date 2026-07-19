from pathlib import Path

import pytest

from tags_machine_core.task_tools.config import (
    OperationPlacement,
    load_task_tools_config,
)
from tags_machine_core.task_tools.models import RelatedResource, TaskContext, TaskContextSet
from tags_machine_core.task_tools.registry import build_default_registry


def test_default_registry_contains_only_first_phase_operations():
    registry = build_default_registry()

    assert registry.ids() == ["open_action_directory", "open_artist_directory"]
    assert registry.get("open_action_directory").target_role == "action"
    assert registry.get("open_artist_directory").target_role == "artist"


def test_config_can_place_operations_independently(tmp_path: Path):
    path = tmp_path / "task_tools.yaml"
    path.write_text(
        """
schema: prompt-atelier.task-tools/v1
operations:
  open_action_directory:
    enabled: true
    placement: quick
    order: 25
  open_artist_directory:
    enabled: true
    placement: launcher
""".strip(),
        encoding="utf-8",
    )

    config = load_task_tools_config(path, registry=build_default_registry())

    assert config.operations["open_action_directory"].placement is OperationPlacement.QUICK
    assert config.operations["open_action_directory"].order == 25
    assert config.operations["open_artist_directory"].placement is OperationPlacement.LAUNCHER


def test_unknown_operation_id_is_rejected(tmp_path: Path):
    path = tmp_path / "task_tools.yaml"
    path.write_text(
        "schema: prompt-atelier.task-tools/v1\noperations:\n  misspelled_action:\n    enabled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        load_task_tools_config(path, registry=build_default_registry())

    assert exc_info.value.args[0] == "\u672a\u77e5\u7684\u4efb\u52a1\u5de5\u5177\u64cd\u4f5c\uff1amisspelled_action"


def test_invalid_config_mapping_error_is_chinese(tmp_path: Path):
    path = tmp_path / "task_tools.yaml"
    path.write_text("- open_action_directory\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_task_tools_config(path, registry=build_default_registry())

    assert exc_info.value.args[0] == f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e\u5fc5\u987b\u662f\u6620\u5c04\uff1a{path}"


@pytest.mark.parametrize("yaml_text", ["false\n", "[]\n"])
def test_falsey_non_mapping_config_roots_are_rejected(tmp_path: Path, yaml_text: str):
    path = tmp_path / "task_tools.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_task_tools_config(path, registry=build_default_registry())

    assert exc_info.value.args[0] == f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e\u5fc5\u987b\u662f\u6620\u5c04\uff1a{path}"


def test_malformed_yaml_error_is_wrapped_in_chinese(tmp_path: Path):
    path = tmp_path / "task_tools.yaml"
    path.write_text("operations:\n  open_action_directory: [\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_task_tools_config(path, registry=build_default_registry())

    message = exc_info.value.args[0]
    assert message.startswith(
        f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e YAML \u89e3\u6790\u5931\u8d25\uff1a{path}\uff08"
    )
    assert "\u884c\uff0c\u7b2c " in message
    assert "expected the node content" not in message
    assert "<stream end>" not in message
    assert exc_info.value.__cause__ is not None


def test_pydantic_validation_error_is_wrapped_in_chinese(tmp_path: Path):
    path = tmp_path / "task_tools.yaml"
    path.write_text(
        """
schema: prompt-atelier.task-tools/v1
operations:
  open_action_directory:
    placement: sidebar
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        load_task_tools_config(path, registry=build_default_registry())

    message = exc_info.value.args[0]
    assert message.startswith(
        f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e\u6821\u9a8c\u5931\u8d25\uff1a{path}\uff08"
    )
    assert "\u64cd\u4f5c\u914d\u7f6e\uff1a\u64cd\u4f5c open_action_directory\uff1a\u64cd\u4f5c\u4f4d\u7f6e" in message
    assert "Input should be" not in message
    assert exc_info.value.__cause__ is not None


def test_missing_config_path_error_is_wrapped_in_chinese(tmp_path: Path):
    path = tmp_path / "missing.yaml"

    with pytest.raises(ValueError) as exc_info:
        load_task_tools_config(path, registry=build_default_registry())

    assert exc_info.value.args[0] == f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e\u8bfb\u53d6\u5931\u8d25\uff1a{path}"
    assert "No such file or directory" not in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


def test_invalid_utf8_config_error_is_wrapped_in_chinese(tmp_path: Path):
    path = tmp_path / "invalid.yaml"
    path.write_bytes(b"schema: \xff\n")

    with pytest.raises(ValueError) as exc_info:
        load_task_tools_config(path, registry=build_default_registry())

    assert exc_info.value.args[0] == f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e\u8bfb\u53d6\u5931\u8d25\uff1a{path}"
    assert "UnicodeDecodeError" not in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


def test_registry_duplicate_and_unknown_errors_are_chinese():
    registry = build_default_registry()
    existing = registry.get("open_action_directory")

    with pytest.raises(ValueError) as duplicate_exc:
        registry.register(existing)

    assert duplicate_exc.value.args[0] == (
        "\u91cd\u590d\u7684\u4efb\u52a1\u5de5\u5177\u64cd\u4f5c\uff1aopen_action_directory"
    )

    with pytest.raises(KeyError) as unknown_exc:
        registry.get("missing_operation")

    assert unknown_exc.value.args[0] == "\u672a\u77e5\u7684\u4efb\u52a1\u5de5\u5177\u64cd\u4f5c\uff1amissing_operation"


def test_context_set_deduplicates_paths_without_losing_order(tmp_path: Path):
    shared = tmp_path / "artist"
    shared.mkdir()
    first = TaskContext(
        input_path=tmp_path / "a.png",
        task_dir=tmp_path / "task-a",
        resources=[RelatedResource(role="artist", id="a", ref=str(shared), path=shared)],
    )
    second = TaskContext(
        input_path=tmp_path / "b.png",
        task_dir=tmp_path / "task-b",
        resources=[RelatedResource(role="artist", id="a", ref=str(shared), path=shared)],
    )

    contexts = TaskContextSet(tasks=[first, second])

    assert contexts.existing_paths("artist") == [shared]
