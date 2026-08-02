from __future__ import annotations

from pathlib import Path

from tools.check_duplicate_tag_files import main, scan_tag_files


def _write_tags(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_groups_equivalent_tags_without_writing_files(tmp_path: Path) -> None:
    first = tmp_path / "a" / "tags.txt"
    second = tmp_path / "b" / "tags.txt"
    _write_tags(first, "black hair, 1girl\nlooking at viewer\n")
    _write_tags(second, "1girl,\nblack_hair, looking_at_viewer\n")
    before = {path: path.read_bytes() for path in (first, second)}

    result = scan_tag_files(tmp_path)

    assert result.scanned == 2
    assert len(result.duplicate_groups) == 1
    assert result.duplicate_files == 2
    assert result.duplicate_groups[0].folder_count == 2
    assert [path.relative_to(tmp_path).as_posix() for path in result.duplicate_groups[0].paths] == [
        "a/tags.txt",
        "b/tags.txt",
    ]
    assert result.duplicate_groups[0].tags == ("1girl", "black_hair", "looking_at_viewer")
    assert {path: path.read_bytes() for path in (first, second)} == before


def test_weight_and_control_line_differences_are_not_duplicates(tmp_path: Path) -> None:
    _write_tags(tmp_path / "weight_a" / "tags.txt", "black_hair, 1girl\n")
    _write_tags(tmp_path / "weight_b" / "tags.txt", "{{black_hair}}, 1girl\n")
    _write_tags(tmp_path / "type_a" / "tags.txt", "1girl\ntype, dress\n")
    _write_tags(tmp_path / "type_b" / "tags.txt", "1girl\ntype, nude\n")
    _write_tags(tmp_path / "ext_a" / "tags.txt", "1girl\n=gen_json, {\"steps\": 28}\n")
    _write_tags(tmp_path / "ext_b" / "tags.txt", "1girl\n=gen_json, {\"steps\": 30}\n")

    result = scan_tag_files(tmp_path)

    assert result.duplicate_groups == ()
    assert result.errors == ()


def test_same_control_lines_are_normalized_and_grouped(tmp_path: Path) -> None:
    _write_tags(tmp_path / "first" / "tags.txt", "1girl\ntype, dress\n")
    _write_tags(tmp_path / "second" / "tags.txt", "1girl\ntype ,  DRESS\n")

    result = scan_tag_files(tmp_path)

    assert len(result.duplicate_groups) == 1
    assert result.duplicate_groups[0].control_lines == ("type,dress",)


def test_unique_files_have_no_duplicate_warning(capsys, tmp_path: Path) -> None:
    _write_tags(tmp_path / "only" / "tags.txt", "1girl, black_hair\n")

    exit_code = main([str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "WARNING" not in captured.err
    assert captured.out.splitlines() == [
        "scanned=1 duplicate_groups=0 duplicate_files=0 errors=0",
        "说明: duplicate_groups=重复内容组数量；duplicate_files=参与重复的 tags.txt 文件总数",
    ]


def test_cli_outputs_duplicate_warning_to_stderr(capsys, tmp_path: Path) -> None:
    _write_tags(tmp_path / "first" / "tags.txt", "1girl, black hair\n")
    _write_tags(tmp_path / "second" / "tags.txt", "black_hair, 1girl\n")

    exit_code = main([str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "WARNING duplicate tags content group=1 (files=2, folders=2):" in captured.err
    assert "normalized_tags: 1girl, black_hair" in captured.err
    assert "folder: first" in captured.err
    assert "folder: second" in captured.err
    assert "first/tags.txt" in captured.err
    assert "second/tags.txt" in captured.err
    assert captured.out.splitlines() == [
        "scanned=2 duplicate_groups=1 duplicate_files=2 errors=0",
        "说明: duplicate_groups=重复内容组数量；duplicate_files=参与重复的 tags.txt 文件总数",
    ]


def test_invalid_utf8_returns_read_error(tmp_path: Path, capsys) -> None:
    path = tmp_path / "invalid" / "tags.txt"
    path.parent.mkdir()
    path.write_bytes(b"1girl, \xff\n")

    exit_code = main([str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ERROR failed to read invalid/tags.txt" in captured.err
    assert captured.out.splitlines() == [
        "scanned=1 duplicate_groups=0 duplicate_files=0 errors=1",
        "说明: duplicate_groups=重复内容组数量；duplicate_files=参与重复的 tags.txt 文件总数",
    ]


def test_invalid_root_returns_usage_error(capsys, tmp_path: Path) -> None:
    exit_code = main([str(tmp_path / "missing")])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "ERROR root not found:" in captured.err
    assert captured.out == ""
