"""Check packaged ownership and actual Foundation merges without installing.

Set CODEX_BASE_FOUNDATION_SOURCE to a reviewed foundation.ps1 to run the
PowerShell regression. It loads function definitions only and writes exclusively
to a temporary fixture home; it never invokes the install/apply entry point.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
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


MERGE_FIXTURE_SCRIPT = r'''
param([string]$FoundationSource, [string]$RequiredConfig,
      [string]$ManifestPath, [string]$FixtureHome)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$ParseErrors = $null
$Tokens = $null
$Parsed = [Management.Automation.Language.Parser]::ParseFile(
    $FoundationSource, [ref]$Tokens, [ref]$ParseErrors)
if ($ParseErrors.Count -gt 0) { throw 'Foundation source failed to parse' }
# Do not dot-source the CLI: that would dispatch a command. Load definitions only.
foreach ($Statement in $Parsed.EndBlock.Statements) {
    if ($Statement -is [Management.Automation.Language.FunctionDefinitionAst]) {
        Invoke-Expression $Statement.Extent.Text
    }
}
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$null = Assert-DesiredStateContract $Manifest.desired_state
$script:ActiveDesiredState = $Manifest.desired_state
$script:ActiveMergeTomlRelativePath = '.codex/config.toml'
$script:ActiveLocalTomlExceptions = @()
$UnknownBefore = @(Get-TomlUnknownEntries $Manifest $FixtureHome)
$Destination = Join-Path $FixtureHome '.codex/config.toml'
Merge-TomlFileAtomic $RequiredConfig $Destination $FixtureHome
$UnknownAfter = @(Get-TomlUnknownEntries $Manifest $FixtureHome)
[pscustomobject]@{
    unknown_before = $UnknownBefore
    unknown_after = $UnknownAfter
    merged = [IO.File]::ReadAllText($Destination)
} | ConvertTo-Json -Depth 10 -Compress
'''

USER_CONFIG = '''# Existing employee choices: no live credentials.
model = "employee-model"
model_reasoning_effort = "employee-effort"
project_doc_max_bytes = 8192

[mcp_servers.k7-revit-bridge]
command = "employee-revit.exe"
enabled = false

[mcp_servers.k7-autocad-bridge]
command = "employee-autocad.exe"
enabled = false

[mcp_servers.local_tool]
command = "employee-tool.exe"
args = ["--fixture"]
enabled = true

[mcp_servers.node_repl]
command = "host-owned.exe"
enabled = false

[plugins."documents@openai-primary-runtime"]
enabled = false

[plugins."pdf@openai-primary-runtime"]
enabled = false

[plugins."presentations@openai-primary-runtime"]
enabled = false

[plugins."spreadsheets@openai-primary-runtime"]
enabled = false

[plugins."template-creator@openai-primary-runtime"]
enabled = false

[plugins."employee-tool@local"]
enabled = true

[plugin_marketplaces.employee]
path = "C:/fixture/employee-marketplace"

[profiles.employee]
model = "employee-profile-model"
'''


class HostOwnedConnectionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="codex-host-connections-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.temporary = Path(cls.temp.name)
        foundation = cls.temporary / "inert-foundation"
        foundation.mkdir()
        script = b"# Inert packaging fixture; never executed.\n"
        (foundation / "foundation.ps1").write_bytes(script)
        dist = cls.temporary / "dist"
        dist.mkdir()
        identity = {
            "repository": "https://github.com/K7-LS/codex-base",
            "commit": "0" * 40,
            "tree": "0" * 40,
            "transformation": "codex-native-independent-v2",
        }
        built = _build_release_from_export(
            source_root=ROOT, dist_root=dist, version="0.1.0",
            foundation_root=foundation, foundation_version="0.1.0",
            foundation_manifest_sha256=hashlib.sha256(script).hexdigest(),
            component_lock=build_component_lock(ROOT, "0.1.0", identity),
            identity=identity,
            session_tools=build_session_tools_bundle(ROOT, dist, "0.1.0"),
        )
        with zipfile.ZipFile(built.zip_path) as archive:
            cls.payload = {name: archive.read(name) for name in archive.namelist()}
        cls.manifest = json.loads(cls.payload["package-manifest.json"])
        cls.config = tomllib.loads(cls.payload[".codex/config.toml"].decode("utf-8"))

    def test_package_does_not_register_or_enable_connections(self) -> None:
        self.assertEqual(
            self.payload[".codex/config.toml"],
            (ROOT / "runtime/config.toml").read_bytes(),
        )
        for key in ("mcp_servers", "plugins", "plugin_marketplaces"):
            self.assertNotIn(key, self.config)
        self.assertEqual(
            self.manifest["managed_surface"]["merge_toml_files"],
            [".codex/config.toml"],
        )

    def test_package_does_not_own_or_retire_user_connections(self) -> None:
        self.assertEqual(self.manifest["desired_state"]["toml_reconcile"], [])
        self.assertEqual(
            self.manifest["desired_state"]["inventory_roots"],
            [".agents/skills", ".codex/agents"],
        )
        desired = json.loads(self.payload[".codex/base/desired-state.json"])
        for key in ("mcp", "plugins", "marketplaces", "retired_ids", "migrations"):
            self.assertEqual(desired[key], [], key)

    def test_foundation_merge_preserves_choices_and_does_not_quarantine_them(self) -> None:
        source_value = os.environ.get("CODEX_BASE_FOUNDATION_SOURCE")
        if not source_value:
            self.skipTest("CODEX_BASE_FOUNDATION_SOURCE is required for real merge regression")
        source = Path(source_value).resolve(strict=True)
        executables = list(dict.fromkeys(
            value for name in ("pwsh", "powershell.exe")
            if (value := shutil.which(name))
        ))
        if not executables:
            self.skipTest("PowerShell is required for the Foundation merge regression")
        script_path = self.temporary / "merge-fixture.ps1"
        script_path.write_text(MERGE_FIXTURE_SCRIPT, encoding="utf-8")
        manifest_path = self.temporary / "package-manifest.json"
        manifest_path.write_bytes(self.payload["package-manifest.json"])
        required_path = self.temporary / "required.toml"
        required_path.write_bytes(self.payload[".codex/config.toml"])
        for index, executable in enumerate(executables):
            for kind, existing in (("fresh", ""), ("employee", USER_CONFIG)):
                with self.subTest(shell=executable, profile=kind):
                    fixture_home = self.temporary / f"home-{index}-{kind}"
                    (fixture_home / ".codex").mkdir(parents=True)
                    if existing:
                        (fixture_home / ".codex/config.toml").write_bytes(
                            existing.replace("\n", "\r\n").encode("utf-8")
                        )
                    completed = subprocess.run(
                        [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                         "Bypass", "-File", str(script_path), str(source),
                         str(required_path), str(manifest_path), str(fixture_home)],
                        capture_output=True, text=True, encoding="utf-8", timeout=60,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    result = json.loads(completed.stdout)
                    self.assertEqual(result["unknown_before"], [])
                    self.assertEqual(result["unknown_after"], [])
                    merged = tomllib.loads(result["merged"])
                    if existing:
                        before = tomllib.loads(existing)
                        for key in ("model", "model_reasoning_effort", "mcp_servers",
                                    "plugins", "plugin_marketplaces", "profiles"):
                            self.assertEqual(merged[key], before[key], key)
                    else:
                        self.assertEqual(merged, self.config)
                    self.assertEqual(
                        merged["project_doc_max_bytes"], self.config["project_doc_max_bytes"]
                    )
                    self.assertIs(merged["features"]["hooks"], True)


if __name__ == "__main__":
    unittest.main()
