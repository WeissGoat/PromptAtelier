from pathlib import Path
import pytest

from tools.legacy_migration.extract_action_clothes import (
    clean_and_route_tags,
    classify_tag_to_section,
    discover_clothing_candidate_dirs,
    export_clothing_nodes,
    is_clothing_action,
    is_drop_tag,
    is_nudity_or_absence,
    normalize_tag,
)


def test_normalize_tag():
    assert normalize_tag('{white_shirt}') == 'white shirt'
    assert normalize_tag('{{long hair}}') == 'long hair'
    assert normalize_tag('1.2::black_skirt::') == 'black skirt'
    assert normalize_tag('   [pleated_skirt]   ') == 'pleated skirt'


def test_drop_general_tags():
    assert is_drop_tag('1girl') is True
    assert is_drop_tag('solo') is True
    assert is_drop_tag('blush') is True
    assert is_drop_tag('looking at viewer') is True
    assert is_drop_tag('lying') is True
    assert is_drop_tag('spread legs') is True
    assert is_drop_tag('hetero') is True
    assert is_drop_tag('cum in pussy') is True


def test_drop_clothing_actions():
    assert is_clothing_action('clothes lift') is True
    assert is_clothing_action('skirt lift') is True
    assert is_clothing_action('clothes pull') is True
    assert is_clothing_action('open clothes') is True
    assert is_clothing_action('bra lift') is True
    assert is_clothing_action('panties aside') is True
    assert is_clothing_action('shibari over clothes') is True
    assert is_clothing_action('unworn shoes') is True
    assert is_clothing_action('clothed female nude male') is True


def test_clothing_action_base_garment_recovery():
    res = clean_and_route_tags(["skirt lift", "open shirt", "black thighhighs", "loafers"])
    assert "skirt" in res["sections"]["lower_clothes"]
    assert "shirt" in res["sections"]["upper_clothes"]
    assert "black thighhighs" in res["sections"]["legwear"]
    assert "loafers" in res["sections"]["shoes"]
    assert "skirt lift" in res["dropped"]
    assert "open shirt" in res["dropped"]


def test_drop_nudity_and_absence():
    assert is_nudity_or_absence('nude') is True
    assert is_nudity_or_absence('naked') is True
    assert is_nudity_or_absence('completely nude') is True
    assert is_nudity_or_absence('bottomless') is True
    assert is_nudity_or_absence('topless') is True
    assert is_nudity_or_absence('no panties') is True
    assert is_nudity_or_absence('no bra') is True


def test_partial_nudity_routing():
    # 局部裸露/鞋履状态：赤脚
    assert classify_tag_to_section('barefoot') == 'shoes'
    assert classify_tag_to_section('bare soles') == 'shoes'
    # 局部裸露/腿部造型：光腿/露腿/绝对领域
    assert classify_tag_to_section('bare legs') == 'legwear'
    assert classify_tag_to_section('zettai ryouiki') == 'legwear'
    # 局部裸露/剪裁造型：露肩/露背/露胸/露臂/深V
    assert classify_tag_to_section('bare shoulders') == 'upper_clothes'
    assert classify_tag_to_section('bare back') == 'upper_clothes'
    assert classify_tag_to_section('cleavage') == 'upper_clothes'
    assert classify_tag_to_section('underboob') == 'upper_clothes'
    assert classify_tag_to_section('backless') == 'upper_clothes'


def test_route_sections():
    assert classify_tag_to_section('white pleated skirt') == 'lower_clothes'
    assert classify_tag_to_section('microskirt') == 'lower_clothes'
    assert classify_tag_to_section('pantsu') == 'lower_clothes'
    assert classify_tag_to_section('black panties') == 'lower_clothes'
    assert classify_tag_to_section('underwear') == 'lower_clothes'
    assert classify_tag_to_section('black thighhighs') == 'legwear'
    assert classify_tag_to_section('single stocking') == 'legwear'
    assert classify_tag_to_section('thighlet') == 'legwear'
    assert classify_tag_to_section('white socks') == 'legwear'
    assert classify_tag_to_section('high heels') == 'shoes'
    assert classify_tag_to_section('loafers') == 'shoes'
    assert classify_tag_to_section('flip-flops') == 'shoes'
    assert classify_tag_to_section('uwabaki') == 'shoes'
    assert classify_tag_to_section('single shoe') == 'shoes'
    assert classify_tag_to_section('school uniform') == 'full_body_clothes'
    assert classify_tag_to_section('sleeveless dress') == 'full_body_clothes'
    assert classify_tag_to_section('micro bikini') == 'full_body_clothes'
    assert classify_tag_to_section('reverse bunnysuit') == 'full_body_clothes'
    assert classify_tag_to_section('sleepwear') == 'full_body_clothes'
    assert classify_tag_to_section('bodystocking') == 'full_body_clothes'
    assert classify_tag_to_section('nun') == 'full_body_clothes'
    assert classify_tag_to_section('white shirt') == 'upper_clothes'
    assert classify_tag_to_section('off shoulder') == 'upper_clothes'
    assert classify_tag_to_section('sailor collar') == 'upper_clothes'
    assert classify_tag_to_section('labcoat') == 'upper_clothes'
    assert classify_tag_to_section('cloak') == 'upper_clothes'
    assert classify_tag_to_section('bustier') == 'upper_clothes'
    assert classify_tag_to_section('hair ribbon') == 'headwear'
    assert classify_tag_to_section('maid headdress') == 'headwear'
    assert classify_tag_to_section('halo') == 'headwear'
    assert classify_tag_to_section('hairclip') == 'headwear'
    assert classify_tag_to_section('goggles') == 'headwear'
    assert classify_tag_to_section('head wreath') == 'headwear'
    assert classify_tag_to_section('red collar') == 'accessories'
    assert classify_tag_to_section('elbow gloves') == 'accessories'
    assert classify_tag_to_section('randoseru') == 'accessories'
    assert classify_tag_to_section('cowbell') == 'accessories'
    assert classify_tag_to_section('bandages') == 'accessories'
    assert classify_tag_to_section('maebari') == 'accessories'
    assert classify_tag_to_section('headphones') == 'accessories'
    assert classify_tag_to_section('see-through') == 'clothes'
    assert classify_tag_to_section('animal print') == 'clothes'
    assert classify_tag_to_section('gold trim') == 'clothes'
    assert classify_tag_to_section('cat cutout') == 'clothes'
    assert classify_tag_to_section('frilled') == 'clothes'
    assert classify_tag_to_section('lolita fashion') == 'clothes'


def test_route_hair_and_props():
    # 发型发式
    assert classify_tag_to_section('twintails') == 'hair'
    assert classify_tag_to_section('side ponytail') == 'hair'
    assert classify_tag_to_section('twin braids') == 'hair'
    assert classify_tag_to_section('hair bun') == 'hair'
    assert classify_tag_to_section('short hair') == 'hair'
    assert classify_tag_to_section('blunt bangs') == 'hair'
    assert classify_tag_to_section('ahoge') == 'hair'
    assert classify_tag_to_section('two side up') == 'hair'
    # 道具与手持物
    assert classify_tag_to_section('umbrella') == 'props'
    assert classify_tag_to_section('paper fan') == 'props'
    assert classify_tag_to_section('holding fan') == 'props'
    assert classify_tag_to_section('katana') == 'props'
    assert classify_tag_to_section('magic wand') == 'props'
    assert classify_tag_to_section('holding phone') == 'props'
    assert classify_tag_to_section('controller') == 'props'
    assert classify_tag_to_section('teddy bear') == 'props'
    assert classify_tag_to_section('writing brush') == 'props'


def test_holding_action_vs_props():
    # 对衣物动作应识别为 drop
    assert is_clothing_action('holding skirt') is True
    assert is_clothing_action('holding panties') is True
    assert is_clothing_action('holding hem') is True
    # 手持道具不应被误杀为服装动作
    assert is_clothing_action('holding fan') is False
    assert is_clothing_action('holding umbrella') is False
    assert is_clothing_action('holding phone') is False
    assert is_clothing_action('holding weapon') is False


def test_clean_and_route_tags_full():
    raw_tags = [
        '1girl', 'solo', 'blush', 'skirt lift', 'nude', 'bare back',
        'white shirt, black pleated skirt',
        'black thighhighs', 'loafers', 'red ribbon', 'upskirt', 'blue nails',
        'covered nipples', 'twintails', 'paper umbrella', 'holding fan'
    ]
    res = clean_and_route_tags(raw_tags)
    assert '1girl' in res['dropped']
    assert 'solo' in res['dropped']
    assert 'blush' in res['dropped']
    assert 'skirt lift' in res['dropped']
    assert 'nude' in res['dropped']
    assert 'covered nipples' in res['dropped']
    assert 'upskirt' in res['dropped']
    assert 'blue nails' in res['dropped']

    sections = res['sections']
    assert 'white shirt' in sections['upper_clothes']
    assert 'bare back' in sections['upper_clothes']
    assert 'black pleated skirt' in sections['lower_clothes']
    assert 'black thighhighs' in sections['legwear']
    assert 'loafers' in sections['shoes']
    assert 'red ribbon' in sections['accessories']
    assert 'twintails' in sections['hair']
    assert 'paper umbrella' in sections['props']
    assert 'holding fan' in sections['props']


def test_export_clothing_nodes(tmp_path: Path):
    from tags_machine_core.nodes.validation import _validate_node_yaml
    import yaml

    action_root = tmp_path / "action_root"
    action_root.mkdir()

    # 1. 有效服装节点 (st_clothes)
    st_dir = action_root / "st_clothes" / "101_sailor_suit"
    st_dir.mkdir(parents=True)
    (st_dir / "tags.txt").write_text("white shirt, sailor collar, blue pleated skirt, loafers\n", encoding="utf-8")
    (st_dir / "preview.png").write_bytes(b"dummy image")

    # 2. 有效服装节点 (action_outfit with type,dress)
    act_dir = action_root / "actions" / "act_maid_dress"
    act_dir.mkdir(parents=True)
    (act_dir / "tags.txt").write_text("type,dress\n", encoding="utf-8")
    (act_dir / "meta.yaml").write_text(
        yaml.safe_dump({
            "name": "女仆装动作",
            "tags": {"default": ["maid dress", "white apron", "maid headdress", "kneehighs"]},
            "negative_prompt": ["barefoot"],
        }, allow_unicode=True),
        encoding="utf-8",
    )

    # 3. 空服装节点 (无服饰标签，仅姿势动作，低于阈值 4 tags)
    empty_dir = action_root / "actions" / "act_pure_pose"
    empty_dir.mkdir(parents=True)
    (empty_dir / "tags.txt").write_text("type,dress\n", encoding="utf-8")
    (empty_dir / "meta.yaml").write_text(
        yaml.safe_dump({
            "tags": {"default": ["1girl", "lying", "spread legs"]},
        }),
        encoding="utf-8",
    )

    export_root = tmp_path / "clothing_export"
    res = export_clothing_nodes(action_root, export_root)
    sm = res["summary"]

    assert sm["total_candidates"] == 3
    assert sm["exported_count"] == 2
    assert sm["skipped_empty_count"] == 1
    assert sm["skipped_existing_count"] == 0

    # 验证 st_clothes 导出的节点（维持 st_clothes/101_sailor_suit 相对路径）
    st_target = export_root / "st_clothes" / "101_sailor_suit"
    assert st_target.exists()
    assert (st_target / "preview.png").exists()
    st_meta = yaml.safe_load((st_target / "meta.yaml").read_text(encoding="utf-8"))
    assert st_meta["schema"] == "tags-machine.clothing/v1"
    assert st_meta["kind"] == "clothing"
    assert st_meta["id"] == "101_sailor_suit"
    assert st_meta["tags"]["role"] == ["{{alternative_clothing}}"]
    assert "white shirt" in st_meta["tags"]["upper_clothes"]
    assert "blue pleated skirt" in st_meta["tags"]["lower_clothes"]
    assert "loafers" in st_meta["tags"]["shoes"]

    # 验证 action_outfit 导出的节点（维持 actions/act_maid_dress 相对路径）
    act_target = export_root / "actions" / "act_maid_dress"
    assert act_target.exists()
    act_meta = yaml.safe_load((act_target / "meta.yaml").read_text(encoding="utf-8"))
    assert act_meta["schema"] == "tags-machine.clothing/v1"
    assert act_meta["kind"] == "clothing"
    assert act_meta["id"] == "act_maid_dress"
    assert act_meta["name"] == "女仆装动作"
    assert act_meta["tags"]["role"] == ["{{alternative_clothing}}"]
    assert act_meta["negative_prompt"] == ["barefoot"]

    # 验证导出的 YAML 符合官方 validation.py 校验
    val_st = _validate_node_yaml(st_target / "meta.yaml", export_root)
    assert val_st["status"] == "pass"

    val_act = _validate_node_yaml(act_target / "meta.yaml", export_root)
    assert val_act["status"] == "pass"

    # 再次导出，未指定 force 时跳过已存在的
    res2 = export_clothing_nodes(action_root, export_root, force=False)
    assert res2["summary"]["exported_count"] == 0
    assert res2["summary"]["skipped_existing_count"] == 2


def test_export_clothing_nodes_dedup(tmp_path):
    import yaml
    action_root = tmp_path / "action_source"
    action_root.mkdir()

    act1 = action_root / "actions" / "02_core_20260502_maid"
    act1.mkdir(parents=True)
    (act1 / "tags.txt").write_text("type,dress\n", encoding="utf-8")
    (act1 / "meta.yaml").write_text(
        yaml.safe_dump({
            "name": "女仆核心动作",
            "tags": {"default": ["maid dress", "white apron", "maid headdress", "kneehighs"]},
        }, allow_unicode=True),
        encoding="utf-8",
    )

    act2 = action_root / "actions" / "20260502_maid"
    act2.mkdir(parents=True)
    (act2 / "tags.txt").write_text("type,dress\n", encoding="utf-8")
    (act2 / "meta.yaml").write_text(
        yaml.safe_dump({
            "name": "女仆主动作",
            "tags": {"default": ["maid dress", "white apron", "maid headdress", "kneehighs"]},
        }, allow_unicode=True),
        encoding="utf-8",
    )

    act3 = action_root / "actions" / "sailor_action"
    act3.mkdir(parents=True)
    (act3 / "tags.txt").write_text("type,dress\n", encoding="utf-8")
    (act3 / "meta.yaml").write_text(
        yaml.safe_dump({
            "tags": {"default": ["white shirt", "sailor collar", "blue pleated skirt", "loafers"]},
        }, allow_unicode=True),
        encoding="utf-8",
    )

    export_root = tmp_path / "clothing_export"

    # 默认 dedup=True：内容一致的2个女仆动作去重为1个最优代表
    res = export_clothing_nodes(action_root, export_root, dedup=True)
    sm = res["summary"]
    assert sm["total_candidates"] == 3
    assert sm["exported_count"] == 2
    assert sm["skipped_duplicate_count"] == 1

    # 验证导出的代表为命名更优的 20260502_maid，维持 actions/20260502_maid 相对路径
    assert (export_root / "actions" / "20260502_maid").exists()
    assert not (export_root / "actions" / "02_core_20260502_maid").exists()
    assert (export_root / "actions" / "sailor_action").exists()


def test_clean_and_route_tags_filters_halo_by_default():
    raw_tags = [
        "white shirt", "sailor collar", "blue pleated skirt", "brown loafers",
        "halo", "pink halo", "yellow halo"
    ]
    res = clean_and_route_tags(raw_tags)
    assert "halo" in res["blocked"]
    assert "pink halo" in res["blocked"]
    assert "yellow halo" in res["blocked"]
    assert "halo" in res["dropped"]

    # Headwear should not contain halo
    headwear_tags = res["sections"].get("headwear", [])
    assert "halo" not in headwear_tags
    assert "pink halo" not in headwear_tags
    assert "yellow halo" not in headwear_tags

    # Legitimate clothing tags are retained
    assert "white shirt" in res["sections"]["upper_clothes"]
    assert "blue pleated skirt" in res["sections"]["lower_clothes"]
    assert "brown loafers" in res["sections"]["shoes"]


def test_export_clothing_nodes_filters_halo_and_tracks_frequency(tmp_path: Path):
    import yaml

    action_root = tmp_path / "action_root"
    action_root.mkdir()

    # Node with halo and other clothing tags
    st_dir = action_root / "st_clothes" / "angel_dress"
    st_dir.mkdir(parents=True)
    (st_dir / "tags.txt").write_text(
        "white dress, wings, pink halo, halo, white socks, white shoes, white gloves, white ribbon\n",
        encoding="utf-8"
    )

    # Another node with yellow halo
    act_dir = action_root / "actions" / "act_demon"
    act_dir.mkdir(parents=True)
    (act_dir / "tags.txt").write_text("type,dress\n", encoding="utf-8")
    (act_dir / "meta.yaml").write_text(
        yaml.safe_dump({
            "name": "恶魔服装",
            "tags": {"default": ["black corset", "mini skirt", "yellow halo", "halo", "black boots", "black choker"]},
        }, allow_unicode=True),
        encoding="utf-8",
    )

    export_root = tmp_path / "clothing_export"
    res = export_clothing_nodes(action_root, export_root)
    sm = res["summary"]

    assert sm["exported_count"] == 2
    assert "filtered_words_frequency" in sm
    freq = sm["filtered_words_frequency"]
    assert freq.get("halo") == 2
    assert freq.get("pink halo") == 1
    assert freq.get("yellow halo") == 1
    assert sm["filtered_words_count"] == 4

    # Verify exported meta.yaml does not have halo
    angel_meta = yaml.safe_load((export_root / "st_clothes" / "angel_dress" / "meta.yaml").read_text(encoding="utf-8"))
    all_angel_tags = [t for v in angel_meta["tags"].values() for t in v]
    assert "halo" not in all_angel_tags
    assert "pink halo" not in all_angel_tags
    assert "white dress" in all_angel_tags


def test_clean_and_route_tags_custom_blocked_patterns():
    raw_tags = ["white shirt", "blue pleated skirt", "demon horns", "halo"]
    # Custom filter only targets horns, not halo
    res = clean_and_route_tags(raw_tags, blocked_patterns=["horns"])
    assert "demon horns" in res["blocked"]
    assert "halo" not in res["blocked"]
    assert "white shirt" in res["sections"]["upper_clothes"]


def test_clean_and_route_tags_disable_filter():
    raw_tags = ["white shirt", "blue pleated skirt", "halo"]
    # Explicit empty list disables blocked pattern filtering
    res = clean_and_route_tags(raw_tags, blocked_patterns=[])
    assert res["blocked"] == []
    assert "halo" in res["sections"].get("headwear", [])




