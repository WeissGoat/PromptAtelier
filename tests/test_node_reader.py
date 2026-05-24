import tempfile
import unittest
from pathlib import Path

import yaml

from tags_machine_core.nodes import (
    NodeReader,
    apply_legacy_tags_migration,
    audit_legacy_tags,
    migrate_legacy_action_tags,
    migrate_legacy_background_tags,
    migrate_legacy_character_tags,
    migrate_legacy_style_tags,
    plan_legacy_tags_migration,
    validate_node_tree,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class NodeReaderTest(unittest.TestCase):
    def test_read_tags_txt_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "sample_node"
            node_dir.mkdir()
            (node_dir / "tags.txt").write_text("tag one\n# comment\ntag two\n", encoding="utf-8")

            node = NodeReader().read(node_dir)
            self.assertEqual(node.id, "sample_node")
            self.assertEqual(node.tags["legacy"], ["tag one", "tag two"])
            self.assertEqual(node.positive_texts(), ["tag one", "tag two"])

    def test_read_node_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "style_node"
            node_dir.mkdir()
            (node_dir / "node.yaml").write_text(
                """
schema: tags-machine.node/v1
kind: artist
id: style_node
tags:
  semantic:
    - watercolor
renderers:
  novelai:
    params:
      sampler: k_euler_ancestral
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            self.assertEqual(node.kind, "artist")
            self.assertEqual(node.tags["semantic"], ["watercolor"])
            self.assertIn("novelai", node.renderers)

    def test_read_style_node_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "anime_comfy"
            node_dir.mkdir()
            (node_dir / "node.yaml").write_text(
                """
schema: tags-machine.style/v1
kind: style
id: anime_comfy
tags:
  style:
    - anime style
  quality:
    - "{best quality}"
negative_prompt:
  - lowres
renderers:
  novelai:
    prompt_prefix:
      - "{best quality}"
    params:
      sampler: k_euler_ancestral
  comfyui:
    workflow: portrait_workflow
  sd:
    checkpoint: anime_sd.safetensors
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            self.assertEqual(node.kind, "style")
            self.assertEqual(node.tags["style"], ["anime style"])
            self.assertEqual(node.negative_prompt, ["lowres"])
            self.assertEqual(node.renderers["comfyui"]["workflow"], "portrait_workflow")

    def test_read_background_node_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "simple_room"
            node_dir.mkdir()
            (node_dir / "meta.yaml").write_text(
                """
schema: tags-machine.background/v1
kind: background
id: simple_room
tags:
  background:
    - simple room
  lighting:
    - soft window light
negative_prompt:
  - crowded background
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            self.assertEqual(node.kind, "background")
            self.assertEqual(node.tags["background"], ["simple room"])
            self.assertEqual(node.tags["lighting"], ["soft window light"])
            self.assertEqual(node.negative_prompt, ["crowded background"])

    def test_migrate_legacy_style_tags_txt_to_style_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            style_dir = Path(tmp) / "old_style"
            style_dir.mkdir()
            (style_dir / "tags.txt").write_text(
                """
style prefix,
style suffix, best quality
=
origin_uc, lowres, bad anatomy
after_uc, extra fingers
gen_json, {"sampler": "k_euler_ancestral", "steps": 28, "reference_image_multiple": ["abc"], "reference_strength_multiple": [0.2]}
not_quality_prompts
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_style_tags(style_dir, node_id="migrated_style")

            self.assertEqual(node["schema"], "tags-machine.style/v1")
            self.assertEqual(node["kind"], "style")
            self.assertEqual(node["id"], "migrated_style")
            self.assertEqual(node["tags"]["style"], ["style prefix", "style suffix, best quality"])
            novelai = node["renderers"]["novelai"]
            self.assertFalse(novelai["include_common_tags"])
            self.assertEqual(novelai["prompt_prefix"], ["style prefix"])
            self.assertEqual(novelai["prompt_suffix"], ["style suffix, best quality"])
            self.assertEqual(novelai["negative_prompt"], ["lowres, bad anatomy"])
            self.assertEqual(novelai["after_negative_prompt"], ["extra fingers"])
            self.assertEqual(novelai["params"]["reference_image_multiple"], ["abc"])
            self.assertEqual(novelai["params"]["reference_strength_multiple"], [0.2])
            self.assertEqual(novelai["flags"], ["not_quality_prompts"])

    def test_migrate_legacy_background_tags_txt_to_background_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            background_dir = Path(tmp) / "old_background"
            background_dir.mkdir()
            (background_dir / "tags.txt").write_text(
                """
simple room,
wooden floor
=
origin_uc, crowded background
after_uc, messy room
gen_json, {"sampler": "ignored_for_background"}
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_background_tags(
                background_dir,
                node_id="migrated_background",
            )

            self.assertEqual(node["schema"], "tags-machine.background/v1")
            self.assertEqual(node["kind"], "background")
            self.assertEqual(node["id"], "migrated_background")
            self.assertEqual(node["tags"]["background"], ["simple room", "wooden floor"])
            self.assertEqual(node["negative_prompt"], ["crowded background", "messy room"])
            self.assertNotIn("renderers", node)

    def test_migrate_legacy_action_tags_txt_to_action_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            action_dir = Path(tmp) / "old_action"
            action_dir.mkdir()
            (action_dir / "tags.txt").write_text(
                """
(soles detailed:1.2,toenails), presenting toes, toes focus, close up
type,need_before
=
origin_uc, bad feet, extra toes
node_background, flower field
gen_json, {"sampler": "ignored_for_action"}
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_action_tags(action_dir, node_id="migrated_action")

            self.assertEqual(node["schema"], "tags-machine.action/v1")
            self.assertEqual(node["kind"], "action")
            self.assertEqual(node["id"], "migrated_action")
            self.assertEqual(
                node["tags"]["action"],
                [
                    "(soles detailed:1.2,toenails)",
                    "presenting toes",
                    "toes focus",
                    "close up",
                ],
            )
            self.assertEqual(node["negative_prompt"], ["bad feet, extra toes"])
            self.assertEqual(node["character_scope"], "foot_detail")
            self.assertNotIn("renderers", node)
            self.assertIn("node_background, flower field", node["legacy"]["raw_sections"]["extension"])

    def test_migrate_legacy_character_tags_txt_to_character_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            character_dir = Path(tmp) / "old_character"
            character_dir.mkdir()
            (character_dir / "tags.txt").write_text(
                """
tachibana_kanade,angel_beats!
yellow_eyes,grey_hair,hairband
blazer,pleated_skirt,thighhighs
shirasaya
=
leg_wear, stirrup legwear|toeless legwear
shoes, shoes|boots|loafers
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_character_tags(
                character_dir,
                node_id="migrated_character",
                variant="school_uniform",
            )

            self.assertEqual(node["schema"], "tags-machine.character/v1")
            self.assertEqual(node["kind"], "character")
            self.assertEqual(node["id"], "migrated_character")
            self.assertEqual(node["character_id"], "tachibana_kanade")
            self.assertEqual(node["variant"], "school_uniform")
            self.assertEqual(node["tags"]["character"], ["tachibana_kanade"])
            self.assertEqual(node["tags"]["copyright"], ["angel_beats!"])
            self.assertEqual(node["tags"]["eyes"], ["yellow_eyes"])
            self.assertEqual(node["tags"]["hair"], ["grey_hair"])
            self.assertEqual(node["tags"]["head_accessories"], ["hairband"])
            self.assertEqual(node["tags"]["upper_clothes"], ["blazer"])
            self.assertEqual(node["tags"]["lower_clothes"], ["pleated_skirt"])
            self.assertEqual(node["tags"]["legwear"], ["thighhighs"])
            self.assertEqual(node["tags"]["weapons"], ["shirasaya"])
            self.assertNotIn("rules", node)
            self.assertNotIn("profiles", node)
            self.assertIn("leg_wear, stirrup legwear|toeless legwear", node["legacy"]["raw_sections"]["extension"])

    def test_audit_legacy_character_tags_reports_review_risks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed = root / "needs_review"
            reviewed.mkdir()
            (reviewed / "tags.txt").write_text(
                """
sample_character,sample_copyright
blue_eyes,signature_motif
=
leg_wear, stirrup legwear|toeless legwear
""".strip(),
                encoding="utf-8",
            )
            clean = root / "clean"
            clean.mkdir()
            (clean / "tags.txt").write_text(
                """
clean_character,clean_copyright
blue_eyes,short_hair,jacket
""".strip(),
                encoding="utf-8",
            )

            report = audit_legacy_tags(root, kind="character")

            self.assertEqual(report["schema"], "tags-machine-core.legacy-tags-audit/v1")
            self.assertEqual(report["kind"], "character")
            self.assertEqual(report["summary"]["total"], 2)
            self.assertEqual(report["summary"]["ok"], 1)
            self.assertEqual(report["summary"]["needs_review"], 1)
            self.assertEqual(report["summary"]["errors"], 0)
            self.assertEqual(report["summary"]["issue_counts"]["character_unclassified_tags"], 1)
            self.assertEqual(report["summary"]["issue_counts"]["character_legacy_extension_archived"], 1)
            items_by_id = {item["node_id"]: item for item in report["items"]}
            self.assertEqual(items_by_id["clean"]["status"], "ok")
            self.assertEqual(items_by_id["needs_review"]["status"], "needs_review")
            issue_codes = {
                issue["code"]
                for issue in items_by_id["needs_review"]["issues"]
            }
            self.assertEqual(
                issue_codes,
                {"character_unclassified_tags", "character_legacy_extension_archived"},
            )
            self.assertEqual(items_by_id["needs_review"]["character_id"], "sample_character")

    def test_plan_legacy_tags_migration_reports_targets_and_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "migrated"

            ready_action = root / "ready_action"
            ready_action.mkdir()
            (ready_action / "tags.txt").write_text("foot focus, toes focus", encoding="utf-8")

            existing_target = output_root / "nodes" / "actions" / "ready_action" / "meta.yaml"
            existing_target.parent.mkdir(parents=True)
            existing_target.write_text("already exists", encoding="utf-8")

            nested_a = root / "group_a" / "same"
            nested_a.mkdir(parents=True)
            (nested_a / "tags.txt").write_text("hand focus, grabbing", encoding="utf-8")
            nested_b = root / "group_b" / "same"
            nested_b.mkdir(parents=True)
            (nested_b / "tags.txt").write_text("face focus, looking at viewer", encoding="utf-8")

            plan = plan_legacy_tags_migration(root, kind="action", output_root=output_root)

            self.assertEqual(
                plan["schema"],
                "tags-machine-core.legacy-tags-migration-plan/v1",
            )
            self.assertEqual(plan["kind"], "action")
            self.assertEqual(plan["summary"]["total"], 3)
            self.assertEqual(plan["summary"]["target_exists"], 1)
            self.assertEqual(plan["summary"]["blocked"], 2)
            self.assertEqual(plan["summary"]["issue_counts"]["target_file_exists"], 1)
            self.assertEqual(plan["summary"]["issue_counts"]["target_path_collision"], 2)
            items_by_source = {
                Path(item["source_dir"]).relative_to(root).as_posix(): item
                for item in plan["items"]
            }
            ready_item = items_by_source["ready_action"]
            self.assertEqual(ready_item["target_file"], str(existing_target))
            self.assertTrue(ready_item["target_exists"])
            self.assertEqual(ready_item["migration_status"], "target_exists")
            self.assertEqual(ready_item["safe_node_dir"], "ready_action")
            self.assertEqual(items_by_source["group_a/same"]["migration_status"], "blocked")
            self.assertEqual(items_by_source["group_b/same"]["migration_status"], "blocked")
            collision_target = items_by_source["group_a/same"]["target_file"]
            self.assertEqual(collision_target, items_by_source["group_b/same"]["target_file"])
            self.assertFalse((ready_action / "meta.yaml").exists())
            self.assertFalse((nested_a / "meta.yaml").exists())
            self.assertFalse((nested_b / "meta.yaml").exists())

    def test_apply_legacy_tags_migration_writes_only_ready_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "migrated"

            ready_action = root / "ready_action"
            ready_action.mkdir()
            (ready_action / "tags.txt").write_text("foot focus, toes focus", encoding="utf-8")

            review_action = root / "needs_review_action"
            review_action.mkdir()
            (review_action / "tags.txt").write_text(
                "standing, looking at viewer, blue eyes",
                encoding="utf-8",
            )

            existing_action = root / "existing_action"
            existing_action.mkdir()
            (existing_action / "tags.txt").write_text("hand focus, grabbing", encoding="utf-8")
            existing_target = output_root / "nodes" / "actions" / "existing_action" / "meta.yaml"
            existing_target.parent.mkdir(parents=True)
            existing_target.write_text("already exists", encoding="utf-8")

            result = apply_legacy_tags_migration(root, kind="action", output_root=output_root)

            self.assertEqual(result["schema"], "tags-machine-core.legacy-tags-migration-apply/v1")
            self.assertEqual(result["summary"]["written"], 1)
            self.assertEqual(result["summary"]["skipped"], 2)
            self.assertEqual(
                result["summary"]["skip_reasons"],
                {
                    "migration_status:needs_review": 1,
                    "migration_status:target_exists": 1,
                },
            )
            items_by_source = {
                Path(item["source_dir"]).relative_to(root).as_posix(): item
                for item in result["items"]
            }
            self.assertEqual(items_by_source["ready_action"]["result"], "written")
            self.assertEqual(items_by_source["needs_review_action"]["result"], "skipped")
            self.assertEqual(items_by_source["existing_action"]["result"], "skipped")

            ready_output = output_root / "nodes" / "actions" / "ready_action" / "meta.yaml"
            self.assertTrue(ready_output.exists())
            migrated_node = NodeReader().read(ready_output)
            self.assertEqual(migrated_node.kind, "action")
            self.assertEqual(migrated_node.tags["action"], ["foot focus", "toes focus"])
            self.assertEqual(migrated_node.character_scope, "foot_detail")
            self.assertEqual(existing_target.read_text(encoding="utf-8"), "already exists")
            self.assertFalse((ready_action / "meta.yaml").exists())
            self.assertFalse((review_action / "meta.yaml").exists())
            self.assertFalse((existing_action / "meta.yaml").exists())

    def test_read_migrated_character_meta_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            character_dir = Path(tmp) / "old_character"
            character_dir.mkdir()
            (character_dir / "tags.txt").write_text(
                """
amiya_(arknights),arknights
brown_hair,long_hair,blue_eyes,hair_between_eyes
rabbit_ears,jacket,long_sleeves
""".strip(),
                encoding="utf-8",
            )
            output = character_dir / "meta.yaml"
            output.write_text(
                yaml.safe_dump(
                    migrate_legacy_character_tags(character_dir),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            node = NodeReader().read(character_dir)

            self.assertEqual(node.kind, "character")
            self.assertEqual(node.id, "old_character")
            self.assertEqual(node.character_id, "amiya_(arknights)")
            self.assertEqual(node.tags["character"], ["amiya_(arknights)"])
            self.assertEqual(node.tags["copyright"], ["arknights"])
            self.assertEqual(node.tags["hair"], ["brown_hair", "long_hair", "hair_between_eyes"])
            self.assertEqual(node.tags["eyes"], ["blue_eyes"])
            self.assertEqual(node.tags["ears"], ["rabbit_ears"])
            self.assertEqual(node.tags["upper_clothes"], ["jacket", "long_sleeves"])
            self.assertEqual(node.renderers, {})

    def test_migrate_legacy_action_tags_allows_character_scope_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            action_dir = Path(tmp) / "old_action"
            action_dir.mkdir()
            (action_dir / "tags.txt").write_text(
                """
upper body, looking at viewer
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_action_tags(action_dir, character_scope="portrait")

            self.assertEqual(node["character_scope"], "portrait")
            self.assertIn("character_scope_override", node["agent"]["labels"])

    def test_read_migrated_action_meta_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            action_dir = Path(tmp) / "old_action"
            action_dir.mkdir()
            (action_dir / "tags.txt").write_text(
                """
pov hands, grabbing
=
uc, bad hands
""".strip(),
                encoding="utf-8",
            )
            output = action_dir / "meta.yaml"
            output.write_text(
                yaml.safe_dump(
                    migrate_legacy_action_tags(action_dir),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            node = NodeReader().read(action_dir)

            self.assertEqual(node.kind, "action")
            self.assertEqual(node.id, "old_action")
            self.assertEqual(node.tags["action"], ["pov hands", "grabbing"])
            self.assertEqual(node.negative_prompt, ["bad hands"])
            self.assertEqual(node.character_scope, "hand_detail")
            self.assertEqual(node.renderers, {})

    def test_read_migrated_background_meta_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            background_dir = Path(tmp) / "old_background"
            background_dir.mkdir()
            (background_dir / "tags.txt").write_text(
                """
simple room,
=
uc, crowded background
""".strip(),
                encoding="utf-8",
            )
            output = background_dir / "meta.yaml"
            output.write_text(
                yaml.safe_dump(
                    migrate_legacy_background_tags(background_dir),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            node = NodeReader().read(background_dir)

            self.assertEqual(node.kind, "background")
            self.assertEqual(node.id, "old_background")
            self.assertEqual(node.tags["background"], ["simple room"])
            self.assertEqual(node.negative_prompt, ["crowded background"])
            self.assertEqual(node.renderers, {})

    def test_read_migrated_style_node_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            style_dir = Path(tmp) / "old_style"
            style_dir.mkdir()
            (style_dir / "tags.txt").write_text(
                """
style prefix,
=
origin_uc, lowres
gen_json, {"sampler": "k_euler"}
""".strip(),
                encoding="utf-8",
            )
            output = style_dir / "node.yaml"
            output.write_text(
                yaml.safe_dump(
                    migrate_legacy_style_tags(style_dir),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            node = NodeReader().read(style_dir)

            self.assertEqual(node.kind, "style")
            self.assertEqual(node.id, "old_style")
            self.assertEqual(node.tags["style"], ["style prefix"])
            self.assertEqual(node.renderers["novelai"]["negative_prompt"], ["lowres"])
            self.assertEqual(node.renderers["novelai"]["params"]["sampler"], "k_euler")

    def test_read_scoped_prompt_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "character_node"
            node_dir.mkdir()
            (node_dir / "node.yaml").write_text(
                """
schema: tags-machine-core.node/v1
kind: character
id: character_node
prompt:
  positive:
    - text: akemi homura
      role: identity
      include_scopes: ["*"]
    - text: purple eyes
      role: eyes
      exclude_scopes: [foot_detail]
    - text: bare soles
      role: feet
      include_scopes: [foot_detail]
  negative:
    - text: extra toes
      role: anatomy
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            self.assertEqual(node.positive_texts("foot_detail"), ["akemi homura", "bare soles"])
            self.assertEqual(
                node.positive_texts("face_detail"),
                ["akemi homura", "purple eyes"],
            )
            self.assertEqual(node.negative_texts("foot_detail"), ["extra toes"])

    def test_node_yaml_ignores_non_v1_shot_and_constraints_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "action_node"
            node_dir.mkdir()
            (node_dir / "meta.yaml").write_text(
                """
schema: tags-machine.action/v1
kind: action
id: action_node
tags:
  action:
    - foot focus
shot:
  body_scope: foot_detail
constraints:
  forbidden_parts:
    - eyes
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            payload = node.model_dump(mode="json", by_alias=True)

            self.assertEqual(node.kind, "action")
            self.assertEqual(node.character_scope, None)
            self.assertNotIn("shot", payload)
            self.assertNotIn("constraints", payload)

    def test_validate_node_tree_reports_v1_contract_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_character = root / "characters" / "homura"
            valid_character.mkdir(parents=True)
            (valid_character / "meta.yaml").write_text(
                """
schema: tags-machine.character/v1
kind: character
id: homura
tags:
  character:
    - akemi homura
""".strip(),
                encoding="utf-8",
            )
            invalid_action = root / "actions" / "foot_closeup"
            invalid_action.mkdir(parents=True)
            (invalid_action / "node.yaml").write_text(
                """
schema: tags-machine.action/v1
kind: action
id: foot_closeup
tags:
  action:
    - foot focus
shot:
  body_scope: foot_detail
""".strip(),
                encoding="utf-8",
            )
            invalid_style = root / "styles" / "simple"
            invalid_style.mkdir(parents=True)
            (invalid_style / "node.yaml").write_text(
                """
schema: tags-machine.style/v1
kind: style
id: simple
tags:
  style:
    - soft anime style
""".strip(),
                encoding="utf-8",
            )

            result = validate_node_tree(root)

            self.assertFalse(result["valid"])
            self.assertEqual(result["result"], "fail")
            self.assertEqual(result["summary"]["total_files"], 3)
            self.assertEqual(result["summary"]["pass_count"], 1)
            self.assertEqual(result["summary"]["fail_count"], 2)
            self.assertEqual(result["summary"]["issue_counts"]["node_file_name_mismatch"], 1)
            self.assertEqual(result["summary"]["issue_counts"]["action_missing_character_scope"], 1)
            self.assertEqual(result["summary"]["issue_counts"]["forbidden_v1_field"], 1)
            self.assertEqual(result["summary"]["issue_counts"]["style_missing_renderers_novelai"], 1)
            items_by_id = {item["node_id"]: item for item in result["items"]}
            self.assertEqual(items_by_id["homura"]["status"], "pass")
            action_codes = {issue["code"] for issue in items_by_id["foot_closeup"]["issues"]}
            self.assertEqual(
                action_codes,
                {
                    "node_file_name_mismatch",
                    "action_missing_character_scope",
                    "forbidden_v1_field",
                },
            )

    def test_validate_node_tree_reports_schema_kind_and_required_tag_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid_character = root / "characters" / "homura"
            invalid_character.mkdir(parents=True)
            (invalid_character / "meta.yaml").write_text(
                """
schema: tags-machine.action/v1
kind: character
id: homura
tags:
  hair:
    - black hair
""".strip(),
                encoding="utf-8",
            )
            unsupported = root / "styles" / "legacy_artist"
            unsupported.mkdir(parents=True)
            (unsupported / "node.yaml").write_text(
                """
schema: tags-machine.style/v1
kind: artist
id: legacy_artist
tags:
  style:
    - soft anime style
renderers:
  novelai: {}
""".strip(),
                encoding="utf-8",
            )
            invalid_action = root / "actions" / "flat_tags"
            invalid_action.mkdir(parents=True)
            (invalid_action / "meta.yaml").write_text(
                """
schema: tags-machine.action/v1
kind: action
id: flat_tags
tags:
  - foot focus
character_scope: foot_detail
""".strip(),
                encoding="utf-8",
            )

            result = validate_node_tree(root)

            self.assertFalse(result["valid"])
            self.assertEqual(result["summary"]["fail_count"], 3)
            self.assertEqual(result["summary"]["issue_counts"]["node_schema_mismatch"], 1)
            self.assertEqual(
                result["summary"]["issue_counts"]["missing_required_tag_section"],
                1,
            )
            self.assertEqual(result["summary"]["issue_counts"]["unsupported_v1_kind"], 1)
            self.assertEqual(result["summary"]["issue_counts"]["invalid_tags_mapping"], 1)
            items_by_id = {item["node_id"]: item for item in result["items"]}
            character_codes = {issue["code"] for issue in items_by_id["homura"]["issues"]}
            self.assertEqual(
                character_codes,
                {"node_schema_mismatch", "missing_required_tag_section"},
            )
            artist_codes = {
                issue["code"] for issue in items_by_id["legacy_artist"]["issues"]
            }
            self.assertEqual(artist_codes, {"unsupported_v1_kind"})
            action_codes = {issue["code"] for issue in items_by_id["flat_tags"]["issues"]}
            self.assertEqual(action_codes, {"invalid_tags_mapping"})

    def test_example_nodes_follow_v1_yaml_scope_contract(self):
        examples_root = PROJECT_ROOT / "examples" / "nodes"
        forbidden_keys_by_kind = {
            "character": {
                "rules",
                "profiles",
                "include_scopes",
                "exclude_scopes",
                "shot",
                "constraints",
            },
            "action": {
                "rules",
                "profiles",
                "include_scopes",
                "exclude_scopes",
                "shot",
                "constraints",
                "pose",
                "camera",
                "focus",
            },
            "background": {
                "rules",
                "profiles",
                "include_scopes",
                "exclude_scopes",
                "shot",
                "constraints",
                "renderers",
            },
            "style": {
                "rules",
                "profiles",
                "include_scopes",
                "exclude_scopes",
                "shot",
                "constraints",
            },
        }
        expected_file_by_kind = {
            "character": "meta.yaml",
            "action": "meta.yaml",
            "background": "meta.yaml",
            "style": "node.yaml",
        }
        violations: list[str] = []
        yaml_paths = sorted(examples_root.rglob("*.yaml"))

        for path in yaml_paths:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: expected YAML mapping")
                continue

            kind = str(data.get("kind") or "").strip()
            relative = path.relative_to(PROJECT_ROOT)
            expected_file = expected_file_by_kind.get(kind)
            if expected_file and path.name != expected_file:
                violations.append(f"{relative}: {kind} node should use {expected_file}")

            forbidden_keys = forbidden_keys_by_kind.get(kind, set())
            for key_path in _forbidden_yaml_key_paths(data, forbidden_keys):
                violations.append(f"{relative}: forbidden v1 field {key_path}")

            if kind == "action" and not str(data.get("character_scope") or "").strip():
                violations.append(f"{relative}: action node missing character_scope")
            if kind == "style":
                renderers = data.get("renderers")
                if not isinstance(renderers, dict) or not isinstance(renderers.get("novelai"), dict):
                    violations.append(f"{relative}: style node missing renderers.novelai")

        self.assertEqual(violations, [])
        self.assertTrue(validate_node_tree(examples_root)["valid"])


def _forbidden_yaml_key_paths(value, forbidden_keys: set[str], prefix: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            key_path = f"{prefix}.{key_text}"
            if key_text in forbidden_keys:
                paths.append(key_path)
            paths.extend(_forbidden_yaml_key_paths(item, forbidden_keys, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_forbidden_yaml_key_paths(item, forbidden_keys, f"{prefix}[{index}]"))
    return paths


if __name__ == "__main__":
    unittest.main()
