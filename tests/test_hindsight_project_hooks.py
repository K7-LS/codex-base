"""Execute the packaged hook commands, without a real Hindsight service or model."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ASSETS = Path(__file__).parents[1] / "skills" / "llm-interop" / "assets" / "hindsight-project-hooks"
SCRIPTS = {
    "SessionStart": "codex-sessionstart-hook.js",
    "UserPromptSubmit": "codex-hook.js",
    "Stop": "codex-stop-hook.js",
}
STUB = r"""
const fs = require("fs");
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", part => input += part);
process.stdin.on("end", () => {
    const payload = JSON.parse(input);
    fs.writeFileSync(process.env.HINDSIGHT_TEST_RECEIPT, JSON.stringify(payload), "utf8");
    if (payload.prompt === "force-failure") {
        console.error("stub-failure");
        process.exitCode = 7;
        return;
    }
    console.log(JSON.stringify({
        payload,
        hookSpecificOutput: {
            hookEventName: payload.hook_event_name,
            additionalContext: "Проверенная память: " + payload.cwd
        }
    }));
});
"""


@pytest.fixture
def isolated_bridge(tmp_path):
    assert shutil.which("node"), "Node.js is required to test the Hindsight transport"
    project = tmp_path / "Проект с пробелом"
    home = tmp_path / "Профиль сотрудника"
    shutil.copytree(ASSETS, project / ".codex")
    scripts = home / ".hindsight" / "coding-agents" / "dist"
    scripts.mkdir(parents=True)
    (home / ".hindsight" / "coding-agent.json").write_text('{"optInOnly":true}', encoding="utf-8")
    for filename in SCRIPTS.values():
        (scripts / filename).write_text(STUB, encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    environment = os.environ.copy()
    environment["USERPROFILE"] = str(home)
    environment["HINDSIGHT_TEST_RECEIPT"] = str(receipt)
    hooks = json.loads((project / ".codex" / "hooks.json").read_text("utf-8"))["hooks"]
    return project, home, receipt, environment, hooks


def run_hook(fixture, shell, event, cwd, **extra):
    project, _, _, environment, hooks = fixture
    assert shutil.which(shell), f"{shell} is required for hook acceptance"
    key = "commandWindows" if shell == "powershell.exe" else "command"
    payload = {
        "cwd": str(project),
        "session_id": "isolated-transport-test",
        "hook_event_name": event,
        "prompt": "Проверить объём и память",
        "transcript_path": str(project / "Сеанс с кириллицей.jsonl"),
        **extra,
    }
    result = subprocess.run(
        hooks[event][0]["hooks"][0][key],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        cwd=cwd,
        env=environment,
        capture_output=True,
        shell=True,
        check=False,
        timeout=20,
    )
    return result, payload


@pytest.mark.parametrize("shell", ["powershell.exe", "pwsh"])
@pytest.mark.parametrize("event", list(SCRIPTS))
@pytest.mark.parametrize("nested", [False, True])
def test_packaged_commands_preserve_unicode_payload(isolated_bridge, shell, event, nested):
    project, _, receipt, _, _ = isolated_bridge
    cwd = project / "Раздел" / "Листы" if nested else project
    cwd.mkdir(parents=True, exist_ok=True)
    result, payload = run_hook(isolated_bridge, shell, event, cwd)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout, "Hook silently discarded the event"
    response = json.loads(result.stdout.decode("utf-8"))
    assert response["payload"] == payload
    assert response["hookSpecificOutput"]["hookEventName"] == event
    assert "Проверенная память" in response["hookSpecificOutput"]["additionalContext"]
    assert json.loads(receipt.read_text("utf-8")) == payload


@pytest.mark.parametrize("shell", ["powershell.exe", "pwsh"])
def test_child_failure_is_not_reported_as_success(isolated_bridge, shell):
    project, _, _, _, _ = isolated_bridge
    result, _ = run_hook(isolated_bridge, shell, "Stop", project, prompt="force-failure")
    assert result.returncode != 0
    assert b"stub-failure" in result.stderr


@pytest.mark.parametrize("shell", ["powershell.exe", "pwsh"])
def test_missing_settings_do_not_invoke_the_package(isolated_bridge, shell):
    project, home, receipt, _, _ = isolated_bridge
    (home / ".hindsight" / "coding-agent.json").unlink()
    result, _ = run_hook(isolated_bridge, shell, "SessionStart", project)
    assert result.returncode == 0
    assert not result.stdout
    assert not receipt.exists()


@pytest.mark.parametrize("shell", ["powershell.exe", "pwsh"])
def test_project_bridge_is_not_discovered_from_an_unrelated_directory(isolated_bridge, shell, tmp_path):
    _, _, receipt, _, _ = isolated_bridge
    unrelated = tmp_path / "Другой проект"
    unrelated.mkdir()
    result, _ = run_hook(isolated_bridge, shell, "UserPromptSubmit", unrelated)
    assert result.returncode == 0
    assert not result.stdout
    assert not receipt.exists()
