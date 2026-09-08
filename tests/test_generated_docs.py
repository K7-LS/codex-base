"""A docs refresh must not reset independently established release history."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("generate_docs", ROOT / "tools/generate_docs.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class GeneratedDocsTest(unittest.TestCase):
    def test_refresh_preserves_release_checkpoint_and_tracks_current_sources(self):
        with tempfile.TemporaryDirectory(prefix="codex-docs-test-") as temporary:
            root = Path(temporary)
            for name in ("catalog", "baselines", "agents"):
                shutil.copytree(ROOT / name, root / name)
            shutil.copy2(ROOT / "AGENTS.md", root / "AGENTS.md")
            for folder in ("skills", "control-skills"):
                for path in (ROOT / folder).glob("*/SKILL.md"):
                    target = root / path.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
            (root / "docs").mkdir()
            checkpoint = root / "docs/RELEASE-STATUS.md"
            evidence_note = b"# Reviewed checkpoint\nPreserve the real release evidence.\n"
            checkpoint.write_bytes(evidence_note)
            original_root = generator.ROOT
            try:
                generator.ROOT = root
                self.assertEqual(generator.main(), 0)
                first = json.loads((root / "reports/static-token-audit.json").read_text())
                operations = (root / "docs/INSTALL-AND-NETWORK.md").read_text(encoding="utf-8")
                self.assertIn(f"-ClientVersion {generator.SUPPORTED_CODEX_CLIENT} -Json", operations)
                with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                    stream.write("\nA changed source instruction.\n")
                self.assertEqual(generator.main(), 0)
                second = json.loads((root / "reports/static-token-audit.json").read_text())
            finally:
                generator.ROOT = original_root
            self.assertEqual(checkpoint.read_bytes(), evidence_note)
            self.assertNotEqual(first["candidate"], second["candidate"])
            self.assertEqual(second, generator.audit_static_context(root))
            self.assertEqual(second["results"]["MATCHED_AB"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
