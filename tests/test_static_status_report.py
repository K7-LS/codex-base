"""Subprocess checks for the optional, source-backed static status report.

The renderer is deliberately not imported: these tests exercise its public CLI
and inspect the final files, including failures that must preserve old output.
"""

from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import quote, urlsplit

import pytest


TOOL = Path(__file__).resolve().parents[1] / "skills/structured-artifacts/tools/render-status.py"
STATES = ("pending", "in_progress", "awaiting_decision", "needs_review", "accepted", "failed", "skipped")
OLD_REPORT = b"<!doctype html><p>Previously reviewed report.</p>\n"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ParsedHTML(HTMLParser):
    def __init__(self, content: str):
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.fragments: list[str] = []
        self.hidden_depth = 0
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))
        if tag in {"head", "style", "script"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag in {"head", "style", "script"}:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            self.fragments.append(data)

    @property
    def visible(self) -> str:
        return "".join(self.fragments)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "рабочая папка"
    root.mkdir()
    canon = root / "Канон" / "Решения #1.md"
    evidence = root / "Доказательства" / "акт & проверка.md"
    for source, content in ((canon, "Решение: проверить все строки.\n"), (evidence, "Сверены марки и объёмы.\r\n")):
        source.parent.mkdir()
        source.write_bytes(content.encode("utf-8"))

    def ref(path):
        return {"path": path.relative_to(root).as_posix(), "sha256": digest(path), "locator": "строки 1–3"}

    payload = {
        "title": "Сверка ВОР — участок 7",
        "as_of": "2026-09-10T17:20:30+03:00",
        "canonical_sources": [ref(canon)],
        "requirements": [{"id": "R-01", "text": "Сверить объёмы", "state": "pending"}],
        "open_questions": ["Кто подтверждает замену марки?"],
        "findings": ["Монтаж не подтверждён поставкой."],
    }
    (root / "отчёты").mkdir()
    return {"root": root, "canon": canon, "evidence": evidence, "ref": ref, "payload": payload,
            "input": root / "projection.json", "output": root / "отчёты" / "status.html"}


def write_projection(project, payload=None):
    project["input"].write_bytes((json.dumps(payload or project["payload"], ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def run_cli(project, *, relative=True, output=None, input_path=None):
    root = project["root"]
    input_path = input_path or project["input"]
    output = output or project["output"]
    if relative:
        input_path = os.path.relpath(input_path, root)
        output = os.path.relpath(output, root)
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root), "--input", str(input_path), "--output", str(output)],
        cwd=root.parent, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )


def keep_old_report(project):
    project["output"].parent.mkdir(parents=True, exist_ok=True)
    project["output"].write_bytes(OLD_REPORT)


def assert_rejected_preserving_report(project, **kwargs):
    keep_old_report(project)
    original_input = project["input"].read_bytes()
    sources = {project[key]: project[key].read_bytes() for key in ("canon", "evidence")}
    result = run_cli(project, **kwargs)
    assert result.returncode != 0, result.stdout
    assert (result.stderr + result.stdout).strip(), "A rejected request needs an error diagnostic"
    assert project["output"].read_bytes() == OLD_REPORT
    assert project["input"].read_bytes() == original_input
    assert all(path.read_bytes() == data for path, data in sources.items())


def displayed_counts(document):
    counts = {}
    for attrs, body in re.findall(r"<li\b([^>]*)>(.*?)</li>", document, flags=re.I | re.S):
        item = ParsedHTML(f"<li {attrs}>{body}</li>")
        state = item.elements[0][1].get("data-state")
        if state is not None:
            count = re.search(r"(\d+)\s*$", item.visible)
            assert count, f"A state counter needs a visible integer: {item.visible}"
            assert state not in counts, f"Duplicated state counter: {state}"
            counts[state] = int(count.group(1))
    return counts


@pytest.mark.parametrize("relative", [True, False], ids=["root-relative-cli", "absolute-in-root-cli"])
def test_render_static_report_with_unicode_paths_and_verified_sources(project, relative):
    payload = project["payload"]
    payload["requirements"] = [
        {"id": f"R-{index:02}", "text": f"Требование {index}", "state": state,
         **({"result": "Объём сверен", "evidence": [project["ref"](project["evidence"])]} if state == "accepted" else {})}
        for index, state in enumerate(STATES, 1)
    ]
    payload["requirements"][0]["sources"] = [project["ref"](project["evidence"])]
    write_projection(project)
    before = {project[key]: project[key].read_bytes() for key in ("input", "canon", "evidence")}
    result = run_cli(project, relative=relative)
    assert result.returncode == 0, result.stderr + result.stdout
    content = project["output"].read_text(encoding="utf-8")
    parsed = ParsedHTML(content)
    for value in (payload["title"], payload["as_of"], digest(project["input"]), *payload["open_questions"], *payload["findings"]):
        assert value in parsed.visible
    for requirement in payload["requirements"]:
        assert requirement["id"] in parsed.visible
        assert requirement["text"] in parsed.visible
    assert "Принято по данным источника" in parsed.visible
    assert "Объём сверен" in parsed.visible
    assert displayed_counts(content) == dict.fromkeys(STATES, 1)
    assert not re.search(r"\bPASS\b|\d\s*%", parsed.visible, re.I)
    assert not any(tag in {"script", "iframe", "object", "embed", "base"} for tag, _ in parsed.elements)
    for tag, attrs in parsed.elements:
        assert not any(name.lower().startswith("on") for name in attrs)
        assert not (tag == "meta" and (attrs.get("http-equiv") or "").lower() == "refresh")
        for attr in ("href", "src", "action"):
            value = attrs.get(attr, "") or ""
            assert not re.match(r"(?:https?:|//|javascript:|data:)", value, re.I)
    href_paths = {urlsplit(attrs["href"]).path for tag, attrs in parsed.elements if tag == "a" and attrs.get("href")}
    for source in (project["canon"], project["evidence"]):
        relative_source = os.path.relpath(source, project["output"].parent).replace("\\", "/")
        assert quote(relative_source, safe="/") in href_paths
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize("state", ["pending", "skipped"])
def test_unfinished_or_skipped_row_is_not_accepted(project, state):
    project["payload"]["requirements"][0]["state"] = state
    write_projection(project)
    result = run_cli(project)
    assert result.returncode == 0, result.stderr
    visible = ParsedHTML(project["output"].read_text(encoding="utf-8")).visible
    # A legend or zero counter may mention accepted; the actual row must not.
    document = project["output"].read_text(encoding="utf-8")
    assert displayed_counts(document) == {value: int(value == state) for value in STATES}
    rows = re.findall(r"<(?:tr|article)\b[^>]*>(.*?)</(?:tr|article)>", document, flags=re.I | re.S)
    matching_rows = [ParsedHTML(row).visible for row in rows if "R-01" in ParsedHTML(row).visible]
    assert matching_rows, "Requirements need an identifiable row or article"
    assert all("Принято по данным источника" not in row for row in matching_rows)
    assert not re.search(r"\bPASS\b|\d\s*%", visible, re.I)


@pytest.mark.parametrize("field", ["title", "as_of", "canonical_sources", "requirements", "open_questions", "findings"])
def test_required_top_level_field_is_not_silently_invented(project, field):
    del project["payload"][field]
    write_projection(project)
    assert_rejected_preserving_report(project)


@pytest.mark.parametrize("value", ["2026-09-10", "2026-09-10T17:20:30", "yesterday", "2026-99-10T17:20:30Z"])
def test_timestamp_requires_valid_iso_timezone(project, value):
    project["payload"]["as_of"] = value
    write_projection(project)
    assert_rejected_preserving_report(project)


@pytest.mark.parametrize("mutation", ["empty-canon", "unknown-state", "missing-result", "empty-result", "missing-evidence", "empty-evidence"])
def test_invalid_acceptance_or_contract_preserves_prior_report(project, mutation):
    row = project["payload"]["requirements"][0]
    row.update(state="accepted", result="Проверено", evidence=[project["ref"](project["evidence"])])
    if mutation == "empty-canon":
        project["payload"]["canonical_sources"] = []
    elif mutation == "unknown-state":
        row["state"] = "PASS"
    else:
        action, field = mutation.split("-")
        if action == "missing":
            del row[field]
        else:
            row[field] = "   " if field == "result" else []
    write_projection(project)
    assert_rejected_preserving_report(project)


@pytest.mark.parametrize("ref_location", ["canonical_sources", "sources", "evidence"])
def test_raw_hash_drift_at_every_reference_location_is_rejected(project, ref_location):
    if ref_location == "canonical_sources":
        source = project["canon"]
    else:
        source = project["evidence"]
        project["payload"]["requirements"][0][ref_location] = [project["ref"](source)]
    write_projection(project)
    # Byte changes count, including newline normalization that leaves meaning intact.
    source.write_bytes(source.read_bytes() + b"\r\n")
    assert_rejected_preserving_report(project)


@pytest.mark.parametrize("sha", ["a" * 63, "g" * 64, 17, None])
def test_invalid_hash_shape_is_rejected(project, sha):
    project["payload"]["canonical_sources"][0]["sha256"] = sha
    write_projection(project)
    assert_rejected_preserving_report(project)


def test_malformed_json_preserves_existing_report(project):
    project["input"].write_bytes(b'{"title": "unfinished"')
    assert_rejected_preserving_report(project)


def test_duplicate_json_key_cannot_replace_a_decision_silently(project):
    write_projection(project)
    raw = project["input"].read_text(encoding="utf-8")
    project["input"].write_text(raw.replace('"state": "pending"', '"state": "accepted", "state": "pending"'), encoding="utf-8")
    assert_rejected_preserving_report(project)


def test_all_display_fields_are_literal_not_markup(project):
    payload = project["payload"]
    injection = '</h1><script>alert("x")</script><img src=x onerror="alert(1)"> & "quoted"'
    payload["title"] = injection
    payload["requirements"][0].update(text=injection, result=injection, sources=[project["ref"](project["evidence"])])
    payload["canonical_sources"][0]["locator"] = injection
    payload["open_questions"] = [injection]
    payload["findings"] = [injection]
    write_projection(project)
    result = run_cli(project)
    assert result.returncode == 0, result.stderr
    parsed = ParsedHTML(project["output"].read_text(encoding="utf-8"))
    assert parsed.visible.count(injection) >= 5
    assert not any(tag in {"script", "img"} for tag, _ in parsed.elements)
    assert not any(name.startswith("on") for _, attrs in parsed.elements for name in attrs)


@pytest.mark.parametrize("victim", ["input", "canon", "evidence"])
def test_output_cannot_overwrite_projection_or_any_referenced_source(project, victim):
    project["payload"]["requirements"][0]["evidence"] = [project["ref"](project["evidence"])]
    write_projection(project)
    original = project[victim].read_bytes()
    result = run_cli(project, output=project[victim])
    assert result.returncode != 0, result.stdout
    assert project[victim].read_bytes() == original


@pytest.mark.parametrize("victim", ["input", "canon", "evidence"])
def test_output_hardlink_alias_of_input_or_reference_is_rejected(project, victim):
    project["payload"]["requirements"][0]["evidence"] = [project["ref"](project["evidence"])]
    write_projection(project)
    alias = project["root"] / "alias.html"
    try:
        os.link(project[victim], alias)
    except OSError:
        pytest.skip("This filesystem does not allow a local test hardlink")
    original = project[victim].read_bytes()
    result = run_cli(project, output=alias)
    assert result.returncode != 0, result.stdout
    assert alias.samefile(project[victim])
    assert alias.read_bytes() == original == project[victim].read_bytes()


@pytest.mark.parametrize("path_kind", ["parent", "absolute", "backslash-parent", "missing"])
def test_source_path_cannot_escape_root_or_be_missing(project, path_kind):
    external = project["root"].parent / "external.md"
    external.write_bytes(b"Outside the selected project root.\n")
    paths = {"parent": "../external.md", "absolute": str(external), "backslash-parent": "..\\external.md", "missing": "missing.md"}
    project["payload"]["canonical_sources"] = [{"path": paths[path_kind], "sha256": digest(external)}]
    write_projection(project)
    assert_rejected_preserving_report(project)
    assert external.read_bytes() == b"Outside the selected project root.\n"


@pytest.mark.parametrize("argument", ["input", "output"])
def test_cli_paths_outside_root_are_rejected_without_writing(project, argument):
    write_projection(project)
    external = project["root"].parent / ("external.json" if argument == "input" else "external.html")
    external.write_bytes(project["input"].read_bytes() if argument == "input" else OLD_REPORT)
    before = external.read_bytes()
    assert_rejected_preserving_report(project, **{"input_path" if argument == "input" else "output": external})
    assert external.read_bytes() == before


def directory_link(link: Path, target: Path):
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            pytest.skip("Directory symlinks are unavailable on this host")
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("Neither directory symlinks nor PowerShell junction creation is available")
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:K7_TEST_LINK -Target $env:K7_TEST_TARGET | Out-Null"],
        env={**os.environ, "K7_TEST_LINK": str(link), "K7_TEST_TARGET": str(target)},
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode:
        pytest.skip("Host does not permit a test directory symlink or junction")


@pytest.mark.parametrize("use", ["source", "input", "output", "root"])
def test_symlink_or_junction_path_is_rejected_even_if_target_is_in_project(project, use):
    write_projection(project)
    link = project["root"] / "linked"
    directory_link(link, project["canon"].parent)
    kwargs = {}
    if use == "source":
        project["payload"]["canonical_sources"][0]["path"] = f"linked/{project['canon'].name}"
        write_projection(project)
    elif use == "input":
        linked_input = project["canon"].parent / "linked-input.json"
        linked_input.write_bytes(project["input"].read_bytes())
        kwargs["input_path"] = link / linked_input.name
    elif use == "output":
        kwargs["output"] = link / "report.html"
    else:
        root_link = project["root"].parent / "linked-root"
        directory_link(root_link, project["root"])
        linked_project = copy.copy(project)
        linked_project["root"] = root_link
        linked_project["input"] = root_link / "projection.json"
        linked_project["output"] = root_link / "отчёты" / "status.html"
        assert_rejected_preserving_report(linked_project)
        return
    assert_rejected_preserving_report(project, **kwargs)
    assert not (project["canon"].parent / "report.html").exists()
