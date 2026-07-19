import json
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from tags_machine_core.cli import build_parser
from tags_machine_core.tools.action_resolver.cli import run_cli


def _write_case(tmp_path: Path) -> tuple[Path, Path]:
    design = tmp_path / "design"
    action_root = design / "动作改2"
    (action_root / "new" / "动作A").mkdir(parents=True)
    (action_root / "pn_group" / "00_start_动作A").mkdir(parents=True)
    (action_root / "category_view_manifest.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "name": "动作A",
                        "view_name": "00_start_动作A",
                        "root": "pn_group",
                        "source": "new/动作A",
                        "dest": "pn_group/00_start_动作A",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    image_path = tmp_path / "legacy.png"
    info = PngInfo()
    info.add_text("action", "00_start_动作A")
    info.add_text("topic", "pn_group")
    Image.new("RGB", (4, 4)).save(image_path, pnginfo=info)
    return design, image_path


def test_main_parser_accepts_multiple_inputs() -> None:
    args = build_parser().parse_args(["resolve-actions", "old", "new"])

    assert args.inputs == ["old", "new"]


def test_paths_output_is_relative_to_design_root(tmp_path: Path, capsys) -> None:
    design, image_path = _write_case(tmp_path)

    exit_code = run_cli(["--design-root", str(design), str(image_path)])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == str(Path("动作改2/new/动作A"))


def test_json_default_filters_missing_action_helpers(tmp_path: Path, capsys) -> None:
    design, image_path = _write_case(tmp_path)
    helper = tmp_path / "metadata.jpg"
    Image.new("RGB", (4, 4)).save(helper)

    exit_code = run_cli(
        ["--design-root", str(design), "--json", str(image_path), str(helper)]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["status"] == "resolved_new"
