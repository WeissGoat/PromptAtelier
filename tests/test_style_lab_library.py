import tempfile
from pathlib import Path
from unittest import TestCase

from tags_machine_core.style_lab.library import LibraryIndex, display_name, parse_facet_params


def write_node(path: Path, *, node_id: str, tags: str, classify: str | None = None, extra: str = "") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "meta.yaml").write_text(
        f"schema: tags-machine.character/v1\nkind: character\nid: {node_id}\n{extra}tags:\n  hair:\n    - {tags}\n",
        encoding="utf-8",
    )
    (path / "tags.txt").write_text(tags, encoding="utf-8")
    if classify is not None:
        (path / "classify.yaml").write_text(classify, encoding="utf-8")
    return path


class LibraryIndexTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "角色"
        self.cache = Path(self.temp_dir.name) / "cache.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def index(self) -> LibraryIndex:
        return LibraryIndex(lambda role: [self.root], lambda path: False, cache_path=self.cache)

    def test_copies_with_same_content_merge_into_the_original(self):
        write_node(self.root / "vocaloid" / "miku", node_id="miku", tags="aqua_hair")
        # 副本：目录名带"快捷方式"，id 跟着变、多了空行和来源记录，内容相同。
        write_node(
            self.root / "特殊" / "miku - 快捷方式",
            node_id="miku - 快捷方式",
            tags="aqua_hair",
            extra="\nlegacy:\n  source_file: /old/miku/tags.txt\n",
        )
        # 同名但内容不同的不合并。
        write_node(self.root / "特殊_old" / "miku - 快捷方式", node_id="miku", tags="pink_hair")

        result = self.index().search("character", "miku")
        self.assertEqual(result["total"], 2)
        first = result["nodes"][0]
        self.assertEqual(first["name"], "miku")
        self.assertEqual(first["relative"], "vocaloid/miku")
        self.assertEqual(first["copies"], 1)
        self.assertEqual(first["copy_paths"], ["特殊/miku - 快捷方式"])
        self.assertEqual(result["nodes"][1]["relative"], "特殊_old/miku - 快捷方式")

    def test_action_facets_filter_and_count(self):
        write_node(self.root / "a", node_id="a", tags="x", classify="cast: solo\npose: [lying]\nsubtype:\n  body: [display]\n")
        write_node(self.root / "b", node_id="b", tags="y", classify="cast: 1boy1girl\npose: [lying, sitting]\n")
        write_node(self.root / "c", node_id="c", tags="z", classify="cast: solo\npose: [standing]\n")

        index = self.index()
        result = index.search("action", "", {"cast": ["solo"]})
        self.assertEqual([node["name"] for node in result["nodes"]], ["a", "c"])
        self.assertEqual(result["nodes"][0]["facets"]["subtype"], ["display"])
        # 选了 cast 以后，cast 自己的计数不变，其他分面按选择缩小。
        cast = {item["value"]: item["count"] for item in result["facet_options"]["cast"]}
        pose = {item["value"]: item["count"] for item in result["facet_options"]["pose"]}
        self.assertEqual(cast, {"solo": 2, "1boy1girl": 1})
        self.assertEqual(pose, {"lying": 1, "standing": 1})
        self.assertEqual(index.search("action", "", {"cast": ["solo"], "pose": ["lying", "standing"]})["total"], 2)

    def test_cache_survives_restart_and_picks_up_changes(self):
        node = write_node(self.root / "a", node_id="a", tags="x")
        write_node(self.root / "b", node_id="b", tags="x")
        self.assertEqual(self.index().search("character")["total"], 1)
        self.assertTrue(self.cache.is_file())

        (node / "tags.txt").write_text("changed", encoding="utf-8")
        self.assertEqual(self.index().search("character")["total"], 2)

    def test_names_and_facet_params(self):
        self.assertEqual(display_name("kasumi - 快捷方式0"), "kasumi")
        self.assertEqual(display_name("b - 副本 (2)"), "b")
        self.assertEqual(
            parse_facet_params(["cast:Solo", "pose:lying", "bogus:x", "pose:"]),
            {"cast": ["solo"], "pose": ["lying"]},
        )
