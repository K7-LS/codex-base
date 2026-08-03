from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_assets_are_attested_on_publish_and_manual_repair():
    workflow = (
        ROOT / ".github" / "workflows" / "attest-release-assets.yml"
    ).read_text(encoding="utf-8")

    assert "release:" in workflow
    assert "types: [published]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "tag:" in workflow
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "contents: read" in workflow
    assert "gh release download" in workflow
    assert "actions/attest@v4" in workflow
    assert "subject-path: release-assets/*" in workflow
