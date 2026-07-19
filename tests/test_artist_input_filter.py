from __future__ import annotations

from pathlib import Path

from tags_machine_core.config import AppConfig
from tags_machine_core.batch.models import BatchSpec
from tags_machine_core.batch.planner import BatchPlanner
from tags_machine_core.nodes.artist_input_filter import ArtistInputFilter
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.novelai_artist import NovelAIArtist


def test_default_config_enables_nsfw_filter() -> None:
    config = AppConfig.model_validate(
        {
            "legacy": {
                "tags_machine_root": ".",
                "design_root": ".",
            }
        }
    )

    negative_filter = config.artist_input_filter.negative_prompt
    assert negative_filter.enabled is True
    assert negative_filter.blocked_tokens == ["nsfw"]
    assert negative_filter.fields == ["negative_prompt", "after_negative_prompt"]


def test_filter_removes_exact_weighted_tokens_from_legacy_artist() -> None:
    artist = NovelAIArtist(
        artist_ref="20260412",
        path=Path("artists/20260412"),
        negative_prompt="nsfw,lowres,{{NSFW}},1.5::nsfw::,nsfw_only",
        after_negative_prompt="NSFW, bad anatomy",
    )

    filtered = ArtistInputFilter().apply(artist)

    assert filtered.negative_prompt == "lowres,nsfw_only"
    assert filtered.after_negative_prompt == "bad anatomy"
    assert artist.negative_prompt.startswith("nsfw,")


def test_filter_updates_structured_artist_and_records_trace() -> None:
    artist = NodeDocument(
        kind="artist",
        id="structured",
        negative_prompt=["nsfw, lowres"],
        prompt={"negative": [{"text": "{{nsfw}}, bad anatomy"}]},
        renderers={
            "novelai": {
                "negative_prompt": ["1.5::nsfw::, worst quality"],
                "after_negative_prompt": "NSFW, extra fingers",
            }
        },
    )

    filtered = ArtistInputFilter().apply(artist)

    assert filtered.negative_prompt == ["lowres"]
    assert [fragment.text for fragment in filtered.prompt.negative] == ["bad anatomy"]
    assert filtered.renderers["novelai"]["negative_prompt"] == ["worst quality"]
    assert filtered.renderers["novelai"]["after_negative_prompt"] == "extra fingers"
    trace = filtered.composition["input_filter"]["negative_prompt"]
    assert trace["removed_tokens"] == ["nsfw"]
    assert set(trace["affected_fields"]) == {
        "negative_prompt",
        "prompt.negative",
        "renderers.novelai.negative_prompt",
        "renderers.novelai.after_negative_prompt",
    }
    assert artist.negative_prompt == ["nsfw, lowres"]


def test_filter_can_be_disabled() -> None:
    artist = NovelAIArtist(
        artist_ref="20260412",
        path=Path("artists/20260412"),
        negative_prompt="nsfw,lowres",
    )

    filtered = ArtistInputFilter(
        {"negative_prompt": {"enabled": False}}
    ).apply(artist)

    assert filtered is artist
    assert filtered.negative_prompt == "nsfw,lowres"


def test_blocked_tokens_replace_default_list() -> None:
    artist = NovelAIArtist(
        artist_ref="20260412",
        path=Path("artists/20260412"),
        negative_prompt="nsfw,censored,lowres",
    )

    filtered = ArtistInputFilter(
        {
            "negative_prompt": {
                "blocked_tokens": ["censored"],
                "fields": ["negative_prompt"],
            }
        }
    ).apply(artist)

    assert filtered.negative_prompt == "nsfw,lowres"


def test_batch_false_disables_inherited_character_prompts() -> None:
    spec = BatchSpec.model_validate(
        {
            "name": "character-prompts-disabled",
            "defaults": {
                "composer": "full",
                "character_prompts": False,
            },
            "expand": {"mode": "manual"},
            "tasks": [{"prompt": "akemi_homura"}],
        }
    )

    assert spec.defaults.character_prompts is False
    tasks = BatchPlanner(base_dir=Path(".")).plan(
        spec,
        run_dir=Path("examples/batches/.tmp/filter-plan"),
        output_dir=Path("outputs/filter-plan"),
        run_id="filterplan",
    )

    assert tasks
    assert "character_prompts" not in tasks[0].render.params
