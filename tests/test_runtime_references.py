"""Check instruction links against the actual installer payload, not a path map.

The public release entry point intentionally exports HEAD. These source-contract
tests call its packaging stage with the working tree so an uncommitted broken
instruction cannot pass merely because HEAD still contains an older version.
They do not publish a release or validate Foundation execution.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.release import _build_release_from_export, build_component_lock
from codex_base.session_tools import build_session_tools_bundle


def _home_links(text: str) -> set[str]:
    return set(re.findall(r"`(~/(?:\.codex|\.agents)/[^`\n]+)`", text))


class RuntimeReferencesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="codex-runtime-references-")
        cls.addClassCleanup(cls.temp.cleanup)
        temporary = Path(cls.temp.name)
        foundation = temporary / "foundation"
        foundation.mkdir()
        script = b"# Inert Foundation fixture; never executed.\n"
        (foundation / "foundation.ps1").write_bytes(script)
        dist = temporary / "dist"
        dist.mkdir()
        # Explicit fixture identity: this is a contract test, not source attestation.
        identity = {
            "repository": "https://github.com/K7-LS/codex-base",
            "commit": "0" * 40,
            "tree": "0" * 40,
            "transformation": "codex-native-independent-v2",
        }
        version = "0.1.0"
        built = _build_release_from_export(
            source_root=ROOT,
            dist_root=dist,
            version=version,
            foundation_root=foundation,
            foundation_version=version,
            foundation_manifest_sha256=hashlib.sha256(script).hexdigest(),
            component_lock=build_component_lock(ROOT, version, identity),
            identity=identity,
            session_tools=build_session_tools_bundle(ROOT, dist, version),
        )
        with zipfile.ZipFile(built.zip_path) as archive:
            cls.payload = {name: archive.read(name) for name in archive.namelist()}
        cls.agents = {
            name: tomllib.loads(payload.decode("utf-8"))["developer_instructions"]
            for name, payload in cls.payload.items()
            if name.startswith(".codex/agents/") and name.endswith(".toml")
        }

    def test_each_agent_can_read_its_shared_behavior_instructions(self) -> None:
        self.assertTrue(self.agents, "No agent entry points in release payload")
        for agent, body in self.agents.items():
            with self.subTest(agent=agent):
                roots = {link for link in _home_links(body) if link.endswith("/AGENTS.md")}
                self.assertTrue(roots, "Agent has no link to shared behavior rules")
                for link in roots:
                    destination = link.removeprefix("~/")
                    self.assertTrue(destination in self.payload, f"Uninstalled root: {link}")
                    self.assertEqual(
                        self.payload[destination],
                        (ROOT / "AGENTS.md").read_bytes(),
                        f"Agent root {link} is not the packaged base instruction",
                    )

    def test_packaged_core_fits_configured_instruction_budget(self) -> None:
        hot = self.payload[".codex/AGENTS.md"]
        self.assertEqual(hot, (ROOT / "AGENTS.md").read_bytes())
        # Count UTF-8 bytes as delivered, including any line-ending differences.
        hot.decode("utf-8")
        budget = json.loads((ROOT / "context-budget.json").read_text(encoding="utf-8"))
        config = tomllib.loads(self.payload[".codex/config.toml"].decode("utf-8"))
        self.assertLessEqual(len(hot), budget["limits"]["hot_utf8_bytes"])
        self.assertLessEqual(
            len(hot) + budget["limits"]["project_instruction_headroom_bytes"],
            config["project_doc_max_bytes"],
        )
        for key in ("model", "model_reasoning_effort", "model_provider", "model_providers"):
            self.assertNotIn(key, config)

    def test_agent_skill_and_template_links_resolve_in_payload(self) -> None:
        for agent, body in self.agents.items():
            for link in _home_links(body):
                if not (link.startswith("~/.agents/skills/") or "/templates/" in link):
                    continue
                with self.subTest(agent=agent, link=link):
                    self.assertTrue(
                        link.removeprefix("~/") in self.payload,
                        f"Agent names an unavailable installed dependency: {link}",
                    )

    def test_agent_web_reference_links_resolve_to_packaged_cold_guidance(self) -> None:
        reference_names = {
            "feedback_web_direct_access.md",
            "feedback_webfetch_reality_check.md",
        }
        referenced = set()
        for agent, body in self.agents.items():
            for link in set(re.findall(r"`([^`\n]+)`", body)):
                filename = link.rsplit("/", 1)[-1]
                if filename not in reference_names:
                    continue
                referenced.add(filename)
                with self.subTest(agent=agent, link=link):
                    # Relative memory/ paths depend on an unrelated working
                    # directory and are not installed instruction dependencies.
                    self.assertTrue(link.startswith("~/"), f"Unanchored reference: {link}")
                    destination = link.removeprefix("~/")
                    self.assertTrue(destination in self.payload, f"Uninstalled reference: {link}")
                    self.assertEqual(
                        self.payload[destination],
                        (ROOT / "cold" / "memory" / filename).read_bytes(),
                        f"Reference {link} does not deliver its canonical guidance",
                    )
        self.assertEqual(referenced, reference_names, "Web guidance has no agent entry point")

    def test_chain_discovery_directory_contains_packaged_chain_definitions(self) -> None:
        body = self.payload[".agents/skills/chains-pattern/SKILL.md"].decode("utf-8")
        directories = {link for link in _home_links(body) if link.endswith("/chains/")}
        self.assertTrue(directories, "No installed chain discovery directory")
        for directory in directories:
            prefix = directory.removeprefix("~/")
            definitions = {
                name: payload
                for name, payload in self.payload.items()
                if name.startswith(prefix) and name.endswith(".md")
            }
            with self.subTest(directory=directory):
                self.assertTrue(definitions, f"No packaged chains at {directory}")
                self.assertTrue(
                    any(re.search(r"(?m)^chain:\s*\S+", data.decode("utf-8"))
                        for data in definitions.values()),
                    "Discovery directory contains no named chain definitions",
                )


if __name__ == "__main__":
    unittest.main()
