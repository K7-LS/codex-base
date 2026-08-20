from __future__ import annotations

import pytest

from codex_base.repository_identity import (
    CANONICAL_REPOSITORY,
    CANONICAL_TRANSFORMATION,
    LEGACY_BRIDGE_REPOSITORY,
    LEGACY_BRIDGE_TRANSFORMATION,
    LEGACY_BRIDGE_VERSION,
    validated_release_repository,
    validated_release_transformation,
)


def test_canonical_repository_is_valid_for_every_release():
    assert validated_release_repository("0.1.25") == CANONICAL_REPOSITORY
    assert (
        validated_release_repository("0.1.26", CANONICAL_REPOSITORY + "/")
        == CANONICAL_REPOSITORY
    )
    assert (
        validated_release_transformation("0.1.26")
        == CANONICAL_TRANSFORMATION
    )


def test_legacy_repository_is_valid_only_for_exact_bridge_version():
    assert (
        validated_release_repository(
            LEGACY_BRIDGE_VERSION,
            LEGACY_BRIDGE_REPOSITORY,
        )
        == LEGACY_BRIDGE_REPOSITORY
    )
    assert (
        validated_release_transformation(
            LEGACY_BRIDGE_VERSION,
            LEGACY_BRIDGE_REPOSITORY,
        )
        == LEGACY_BRIDGE_TRANSFORMATION
    )
    with pytest.raises(ValueError, match="legacy repository identity"):
        validated_release_repository("0.1.26", LEGACY_BRIDGE_REPOSITORY)


def test_unknown_repository_is_rejected():
    with pytest.raises(ValueError, match="release repository differs"):
        validated_release_repository(
            LEGACY_BRIDGE_VERSION,
            "https://github.com/example/codex-base",
        )
