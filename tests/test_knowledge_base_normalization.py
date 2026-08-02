from tags_machine_core.knowledge_base.normalization import (
    normalize_classification,
    normalize_meta,
)


def test_normalization_accepts_scalar_lists_and_warns_unknown_enum() -> None:
    classification, warnings = normalize_classification(
        {
            "phase": "unexpected",
            "species": "human",
            "cast": "solo",
            "domain": "foot",
            "subtype": {"sex": "penetration"},
        },
        ref="new/a",
    )

    assert classification.domain == ["foot"]
    assert classification.subtype == {"sex": ["penetration"]}
    assert {warning.code for warning in warnings} == {"invalid_enum", "subtype_domain_mismatch"}


def test_meta_preserves_weighted_terms_and_excludes_negative_from_positive() -> None:
    meta, warnings = normalize_meta(
        {
            "tags": {"action": "2.0::foot focus::, barefoot"},
            "negative_prompt": ["bad anatomy, extra toes"],
            "character_scope": "foot_detail",
        },
        ref="new/a",
    )

    assert warnings == []
    assert meta.positive_terms == ["2.0::foot focus::", "barefoot"]
    assert meta.negative_terms == ["bad anatomy", "extra toes"]
