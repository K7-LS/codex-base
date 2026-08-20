from __future__ import annotations


CANONICAL_REPOSITORY = "https://github.com/K7-LS/codex-base"
CANONICAL_TRANSFORMATION = "codex-native-independent-v2"
LEGACY_BRIDGE_REPOSITORY = (
    "https://github.com/daniileliseev1337/codex-base"
)
LEGACY_BRIDGE_TRANSFORMATION = "codex-native-v1"
LEGACY_BRIDGE_VERSION = "0.1.25"


def validated_release_repository(
    version: str,
    repository: str | None = None,
) -> str:
    candidate = (repository or CANONICAL_REPOSITORY).rstrip("/")
    if candidate == CANONICAL_REPOSITORY:
        return candidate
    if candidate == LEGACY_BRIDGE_REPOSITORY:
        if version == LEGACY_BRIDGE_VERSION:
            return candidate
        raise ValueError(
            "legacy repository identity is allowed only for the exact bridge "
            f"version {LEGACY_BRIDGE_VERSION}"
        )
    raise ValueError("release repository differs from the canonical repository")


def validated_release_transformation(
    version: str,
    repository: str | None = None,
) -> str:
    validated = validated_release_repository(version, repository)
    if validated == LEGACY_BRIDGE_REPOSITORY:
        return LEGACY_BRIDGE_TRANSFORMATION
    return CANONICAL_TRANSFORMATION
