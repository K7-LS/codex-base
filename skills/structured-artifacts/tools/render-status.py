#!/usr/bin/env python3
"""Render an explicitly prepared canonical projection; never infer acceptance."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from urllib.parse import quote

STATES = {
    "pending": "Не начато", "in_progress": "В работе",
    "awaiting_decision": "Ожидает решения", "needs_review": "Требует проверки",
    "accepted": "Принято по данным источника", "failed": "Ошибка",
    "skipped": "Пропущено",
}
MAX_INPUT = 1_048_576


def require(condition, message):
    if not condition:
        raise ValueError(message)


def plain_path(path):
    """Check lexical ancestors before resolving; reject Windows junctions too."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0) & 0x400),
                f"Ссылка или reparse point недопустимы: {part}")
    return path


def in_root(value, root):
    path = Path(value)
    path = plain_path(path if path.is_absolute() else root / path)
    require(path.is_relative_to(root), f"Путь выходит за корень: {value}")
    return path


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def text(value, name, allow_empty=False):
    require(isinstance(value, str), f"{name}: ожидается строка")
    require(allow_empty or bool(value.strip()), f"{name}: пустая строка")
    require(len(value) <= 10000 and not any(ord(c) < 32 and c not in "\n\t\r" for c in value),
            f"{name}: недопустимый текст")
    return value


def array(value, name):
    require(isinstance(value, list) and len(value) <= 1000, f"{name}: ожидается список до 1000 строк")
    return value


def object_keys(value, required, optional, name):
    require(isinstance(value, dict), f"{name}: ожидается объект")
    require(required <= value.keys() and value.keys() <= required | optional,
            f"{name}: отсутствующие или неизвестные поля")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Повторный JSON-ключ: {key}")
        result[key] = value
    return result


def validate(data, root):
    required = {"title", "as_of", "canonical_sources", "requirements", "open_questions", "findings"}
    object_keys(data, required, set(), "Проекция")
    text(data["title"], "title")
    stamp = datetime.fromisoformat(text(data["as_of"], "as_of").replace("Z", "+00:00"))
    require(stamp.utcoffset() is not None, "as_of: нужна временная зона")
    checked = {}

    def references(values, name):
        for ref in array(values, name):
            object_keys(ref, {"path", "sha256"}, {"locator"}, name)
            raw = text(ref["path"], name + ".path")
            relative = raw.replace("\\", "/")
            parts = PurePosixPath(relative).parts
            require(parts and not PurePosixPath(relative).is_absolute()
                    and not any(p in (".", "..") for p in relative.split("/"))
                    and not any(c in relative for c in ':<>"|?*\x00')
                    and not any(p.endswith((".", " ")) for p in parts),
                    f"{name}: нужен относительный путь без обхода корня")
            path = in_root(relative, root)
            require(path.is_file(), f"Отсутствует файл: {raw}")
            expected = text(ref["sha256"], name + ".sha256")
            require(re.fullmatch(r"[0-9a-fA-F]{64}", expected), f"Неверный SHA256: {raw}")
            actual = digest(path)
            require(actual == expected.lower(), f"Файл изменился (SHA256): {raw}")
            checked[path] = actual
            if "locator" in ref:
                text(ref["locator"], name + ".locator")

    references(data["canonical_sources"], "canonical_sources")
    require(data["canonical_sources"], "Нужен хотя бы один канонический источник")
    ids = set()
    for row in array(data["requirements"], "requirements"):
        object_keys(row, {"id", "text", "state"}, {"result", "sources", "evidence"}, "Требование")
        identifier = text(row["id"], "id")
        require(identifier not in ids, f"Повторный id требования: {identifier}")
        ids.add(identifier)
        text(row["text"], "Требование.text")
        require(isinstance(row["state"], str) and row["state"] in STATES, "Неизвестное состояние")
        text(row.get("result", ""), "result", allow_empty=True)
        references(row.get("sources", []), "sources")
        references(row.get("evidence", []), "evidence")
        if row["state"] == "accepted":
            require(row.get("result", "").strip() and row.get("evidence"),
                    f"{identifier}: accepted требует result и ссылки evidence")
    for field in ("open_questions", "findings"):
        for value in array(data[field], field):
            text(value, field)
    return checked


CSS = """
:root{font-family:Segoe UI,Arial,sans-serif;color:#20252b;background:#f1f3f5}
body{margin:0}main{max-width:1120px;margin:auto;padding:28px 24px 48px}
h1{font-size:28px;margin:0 0 16px}h2{font-size:20px;margin-top:28px}
p,li{line-height:1.55}header,.notice,article{background:white;border:1px solid #d6dce2;
border-radius:8px;padding:18px 20px;margin:12px 0}.notice{border-left:5px solid #a66a19}
.meta{font-size:14px;color:#4b5660}.hash{font-family:Consolas,monospace;overflow-wrap:anywhere}
.counts{display:flex;flex-wrap:wrap;gap:8px;padding:0;list-style:none}
.counts li{background:white;border:1px solid #d6dce2;padding:8px 10px;border-radius:5px}
.state{font-weight:600}.failed{border-left:5px solid #a93232}
.awaiting_decision,.needs_review{border-left:5px solid #a66a19}
.accepted{border-left:5px solid #477056}.text{white-space:pre-wrap;overflow-wrap:anywhere}
a{color:#15516c;overflow-wrap:anywhere}dt{font-weight:600;margin-top:12px}dd{margin:4px 0}
.empty{color:#5a626a}footer{font-size:13px;color:#4b5660;margin-top:30px}
@media(max-width:640px){main{padding:16px 12px}h1{font-size:23px}article{padding:14px}}
@media print{:root{background:white}main{max-width:none;padding:0}article{break-inside:avoid}}
"""


def render(data, projection_sha, output, root):
    def links(refs):
        items = []
        for ref in refs:
            path = in_root(ref["path"].replace("\\", "/"), root)
            relative = os.path.relpath(path, output.parent).replace("\\", "/")
            label = ref["path"] + (" · " + ref["locator"] if ref.get("locator") else "")
            items.append(f'<li><a href="{escape(quote(relative, safe="/"), quote=True)}">'
                         f'{escape(label)}</a><br><span class="hash">SHA256 {ref["sha256"].lower()}</span></li>')
        return "<ul>" + "".join(items) + "</ul>" if items else '<p class="empty">Не указаны</p>'

    counts = Counter(row["state"] for row in data["requirements"])
    summary = "".join(f'<li data-state="{state}">{label}: {counts[state]}</li>' for state, label in STATES.items())
    rows = []
    for row in data["requirements"]:
        rows.append(f'<article class="{row["state"]}" data-state="{row["state"]}">'
                    f'<h2>{escape(row["id"])}</h2><p class="state">{STATES[row["state"]]}</p>'
                    f'<p class="text">{escape(row["text"])}</p><dl><dt>Результат</dt>'
                    f'<dd class="text">{escape(row.get("result") or "Не указан")}</dd>'
                    f'<dt>Основания требования</dt><dd>{links(row.get("sources", []))}</dd>'
                    f'<dt>Доказательства</dt><dd>{links(row.get("evidence", []))}</dd></dl></article>')
    sections = []
    for name, label in (("open_questions", "Открытые вопросы"), ("findings", "Замечания")):
        content = "<ul>" + "".join(f'<li class="text">{escape(v)}</li>' for v in data[name]) + "</ul>"
        sections.append(f'<section><h2>{label}</h2>{content if data[name] else "<p>Не указаны в проекции</p>"}</section>')
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{escape(data["title"])}</title><style>{CSS}</style></head><body><main>
<header><h1>{escape(data["title"])}</h1><p><strong>Данные по состоянию на {escape(data["as_of"])}</strong></p>
<p class="meta">Сформировано: {generated}</p><p class="hash">SHA256 проекции: {projection_sha}</p></header>
<aside class="notice">Статический снимок. Файлы могли измениться после формирования.
Принятие указано по данным источника; этот отчёт не выполняет инженерную проверку и не принимает результат.</aside>
<section><h2>Требования по состояниям</h2><ul class="counts">{summary}</ul></section>
{''.join(rows) if rows else '<p>Требования не указаны в проекции</p>'}
{''.join(sections)}<section><h2>Канонические источники</h2>{links(data["canonical_sources"])}</section>
<footer>Состояния показаны без автоматического перевода этапов в принятые.
При изменении источников требуется новая проверенная проекция и повторная генерация.</footer>
</main></body></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "root", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    temporary = None
    try:
        root = plain_path(args.root)
        require(root.is_dir(), "Корень проекта не существует")
        source, output = in_root(args.input, root), in_root(args.output, root)
        require(source.is_file(), "Проекция не найдена")
        require(output.suffix.lower() == ".html" and output.parent.is_dir(),
                "Выход должен быть .html в существующем каталоге проекта")
        require(not output.exists() or output.is_file(), "Выход не является файлом")
        with source.open("rb") as stream:
            raw = stream.read(MAX_INPUT + 1)
        require(len(raw) <= MAX_INPUT, "Проекция больше 1 MiB")
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_keys)
        checked = validate(data, root)
        projection_sha = hashlib.sha256(raw).hexdigest()
        checked[source] = projection_sha
        for path in checked:
            require(output != path and not (output.exists() and os.path.samefile(output, path)),
                    "Выход совпадает с проекцией или исходным файлом")
        html = render(data, projection_sha, output, root).encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".status-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(html)
            stream.flush()
            os.fsync(stream.fileno())
        for path, expected in checked.items():
            require(plain_path(path).is_file() and digest(path) == expected,
                    f"Файл изменился во время формирования: {path}")
        in_root(output, root)
        os.replace(temporary, output)
        temporary = None
        print(f"Сформирован статический снимок: {output}")
        return 0
    except (OSError, ValueError, TypeError, RecursionError) as error:
        print(f"Отчёт не обновлён; прежний файл не считать актуальным: {error}", file=sys.stderr)
        return 2
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
