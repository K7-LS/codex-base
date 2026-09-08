"""An ambient pytest filter must not silently accept a partial release suite."""
import runpy
import subprocess
import sys


def test_release_test_process_cannot_inherit_filter_or_plugin_injection(repo_root, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k test_good")
    monkeypatch.setenv("PYTEST_PLUGINS", "missing_ambient_plugin")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "foreign-imports"))
    monkeypatch.setenv("PYTHONOPTIMIZE", "1")
    runner = runpy.run_path(str(repo_root / "tools/run_acceptance.py"))
    environment = runner["_test_environment"](tmp_path / "accepted-engine")
    assert all(key not in environment for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONOPTIMIZE"))
    (tmp_path / "test_fixture.py").write_text(
        "def test_good(): pass\ndef test_bad():\n    raise AssertionError('must execute')\n", encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_fixture.py"],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed, 1 passed" in result.stdout
