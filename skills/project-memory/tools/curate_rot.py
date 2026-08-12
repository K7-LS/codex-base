#!/usr/bin/env python3
"""curate_rot.py — rot-куратор памяти проекта (propose → review → apply).

propose: read-only сверка STATUS.md с журналом и реальностью файлов →
         LLM/.curate/<stamp>/{proposals.json, REPORT.md}
apply:   бэкап затрагиваемых файлов в LLM/_backup_<дата_время>/ →
         применение ТОЛЬКО явно принятых предложений (--accept id1,id2).
         Скрипт сам никогда не решает, что применять: апрув ведёт
         человек/LLM-клиент (см. SKILL.md и prompts/rot.md).

Правила: пути в выходных артефактах — относительные от корня проекта
(мультидевайс, Я.Диск); пустой evidence → предложение невалидно; куратор
не пишет вне LLM/. git log сознательно не используется: папки объектов
живут вне git (решение владельца); при необходимости — точка расширения.
"""
import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

JOURNAL_NAME = "ЖУРНАЛ СЕССИЙ.md"
STATUS_NAME = "STATUS.md"
ARCHIVE_REL = Path("LLM") / "_АРХИВ" / "из-курирования.md"

WAIT_RE = re.compile(r"(ждём|ждем|дедлайн|срок)", re.IGNORECASE)
WAIT_DO_RE = re.compile(r"\bдо\s+\d{2,4}[.\-]")
DONE_RE = re.compile(r"(готов|сдан|собран|выполнен)", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RU_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
ABS_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/]")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
MDLINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
LAST_UPD_RE = re.compile(r"Последнее обновление:\**\s*([0-9.\-]+)")
JOURNAL_HEAD_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def find_project_root(start: Path) -> Path | None:
    """Идёт вверх от start (≤12 уровней) до папки с LLM/ЖУРНАЛ СЕССИЙ.md."""
    d = Path(start).resolve()
    for _ in range(12):
        if (d / "LLM" / JOURNAL_NAME).exists():
            return d
        if d.name == "LLM" and (d / JOURNAL_NAME).exists():
            return d.parent
        if d.parent == d:
            return None
        d = d.parent
    return None


def _parse_date(token: str) -> date | None:
    m = ISO_DATE_RE.search(token)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = RU_DATE_RE.search(token)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _path_candidates(line: str) -> list[str]:
    """Упоминания путей в строке: `бэктики` и markdown-ссылки. URL и
    абсолютные пути отбрасываются (абсолютные ловит отдельный сигнал)."""
    cands = BACKTICK_RE.findall(line) + MDLINK_RE.findall(line)
    out = []
    for c in cands:
        c = c.strip()
        if not c or c.startswith(("http://", "https://", "#")):
            continue
        if ABS_PATH_RE.search(c):
            continue
        if " " in c:
            continue
        if "<" in c or ">" in c:      # плейсхолдер вида _backup_<дата>/ — не путь
            continue
        if "/" in c or "\\" in c or re.search(r"\.\w{1,6}$", c):
            out.append(c.replace("\\", "/"))
    return out


class _Collector:
    def __init__(self):
        self.items = []
        self.dropped = 0

    def add(self, target, excerpt, proposed, evidence, confidence, action,
            signal):
        if not evidence:            # пустой evidence → предложение невалидно
            self.dropped += 1
            return
        self.items.append({
            "id": f"p{len(self.items) + 1}",
            "target": target,
            "current_excerpt": excerpt,
            "proposed_excerpt": proposed,
            "evidence": evidence,
            "confidence": confidence,
            "action": action,
            "source": "script",
            "signal": signal,
        })


def _scan_status(root: Path, col: "_Collector", today: date) -> None:
    status_path = root / "LLM" / STATUS_NAME
    if not status_path.exists():
        return
    target = "LLM/" + STATUS_NAME
    text = status_path.read_text(encoding="utf-8")

    last_upd = None
    m = LAST_UPD_RE.search(text)
    if m:
        last_upd = _parse_date(m.group(1))

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # 1) абсолютные пути запрещены правилами папки
        if ABS_PATH_RE.search(stripped):
            col.add(target, line.rstrip(), "",
                    ["в строке абсолютный путь — запрещён правилами папки "
                     "(корни устройств разные), заменить на относительный"],
                    "high", "flag", "absolute-path")

        # 2) упомянутый файл не существует
        for cand in _path_candidates(stripped):
            if not (root / cand).exists():
                col.add(target, line.rstrip(), "",
                        [f"файл не найден: {cand} (проверено от корня проекта)"],
                        "high", "flag", "file-missing")

        # 3) прошедшая дата в строке ожидания
        if WAIT_RE.search(stripped) or WAIT_DO_RE.search(stripped):
            if "Последнее обновление" not in stripped:
                d = _parse_date(stripped)
                if d and d < today:
                    col.add(target, line.rstrip(), "",
                            [f"дата {d.isoformat()} прошла (сегодня "
                             f"{today.isoformat()}), а строка всё ещё в статусе"],
                            "medium", "flag", "date-passed")

        # 4) «готово/сдано», но файл менялся после последнего обновления статуса
        if last_upd and DONE_RE.search(stripped):
            for cand in _path_candidates(stripped):
                f = root / cand
                if f.exists():
                    mtime = datetime.fromtimestamp(f.stat().st_mtime).date()
                    if mtime > last_upd:
                        col.add(target, line.rstrip(), "",
                                [f"{cand} менялся {mtime.isoformat()} — после "
                                 f"последнего обновления статуса "
                                 f"({last_upd.isoformat()}); «готово» могло устареть"],
                                "low", "flag", "done-file-changed")

    # 5) STATUS отстал от журнала
    journal = root / "LLM" / JOURNAL_NAME
    if last_upd and journal.exists():
        jtext = journal.read_text(encoding="utf-8")
        jdates = [_parse_date(d) for d in JOURNAL_HEAD_RE.findall(jtext)]
        jdates = [d for d in jdates if d]
        newer = [d for d in jdates if d > last_upd]
        if newer:
            col.add(target,
                    m.group(0) if m else "Последнее обновление",
                    "",
                    [f"последнее обновление STATUS — {last_upd.isoformat()}, "
                     f"после него {len(newer)} записей журнала "
                     f"(верхняя {max(newer).isoformat()}); прогнать обновление STATUS"],
                    "high", "flag", "status-behind-journal")


def propose(start: Path) -> Path:
    """Read-only анализ. Возвращает папку LLM/.curate/<stamp>/."""
    root = find_project_root(Path(start))
    if root is None:
        raise SystemExit(
            f"память проекта не найдена (нет LLM/{JOURNAL_NAME} вверх от {start})")
    today = date.today()
    col = _Collector()
    _scan_status(root, col, today)

    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = root / "LLM" / ".curate" / stamp
    n = 2
    while out_dir.exists():
        out_dir = root / "LLM" / ".curate" / f"{stamp}-{n}"
        n += 1
    out_dir.mkdir(parents=True)

    payload = {"created": stamp, "project": root.name,
               "dropped_no_evidence": col.dropped, "proposals": col.items}
    (out_dir / "proposals.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "REPORT.md").write_text(_render_report(payload),
                                       encoding="utf-8", newline="\n")
    return out_dir


def _render_report(payload: dict) -> str:
    props = payload["proposals"]
    by_conf = {c: sum(1 for p in props if p["confidence"] == c)
               for c in ("high", "medium", "low")}
    lines = [
        f"# Rot-курирование {payload['created']}",
        "",
        f"Проект: {payload['project']} (все пути — от корня проекта)",
        f"Предложений: {len(props)} (high: {by_conf['high']}, "
        f"medium: {by_conf['medium']}, low: {by_conf['low']}); "
        f"отброшено без evidence: {payload['dropped_no_evidence']}",
        "",
        "Дальше: review по пунктам → `curate_rot.py apply <stamp> --accept id,…`",
        "(бэкап в `LLM/_backup_<дата>/` создаётся автоматически; "
        "flag-пункты правятся вручную).",
        "",
    ]
    for p in props:
        lines += [
            f"## {p['id']} · {p['action']} · {p['confidence']} · "
            f"{p['target']} · {p['signal']}",
            "",
            f"> {p['current_excerpt']}",
            "",
            "Evidence:",
        ]
        lines += [f"- {e}" for e in p["evidence"]]
        if p["proposed_excerpt"]:
            lines += ["", "Предлагаемая замена:", f"> {p['proposed_excerpt']}"]
        lines.append("")
    if not props:
        lines.append("Протухания не найдены — статус согласован с реальностью.")
    return "\n".join(lines) + "\n"


def apply(start: Path, stamp: str, accept: list[str]) -> dict:
    """Применяет ТОЛЬКО принятые предложения. Бэкап затрагиваемых файлов —
    до первой записи. Никакого авто-apply: список accept формирует человек
    (через native user-input UI) на review-шаге."""
    root = find_project_root(Path(start))
    if root is None:
        raise SystemExit("память проекта не найдена")
    cur_dir = root / "LLM" / ".curate" / stamp
    pfile = cur_dir / "proposals.json"
    if not pfile.exists():
        raise SystemExit(
            f"нет прогона propose: LLM/.curate/{stamp}/proposals.json")
    payload = json.loads(pfile.read_text(encoding="utf-8"))
    by_id = {p["id"]: p for p in payload.get("proposals", [])}
    unknown = [a for a in accept if a not in by_id]
    if unknown:
        raise SystemExit(f"неизвестные id: {', '.join(unknown)} "
                         f"(есть: {', '.join(by_id) or 'ни одного'})")
    if not accept:
        raise SystemExit("пустой --accept: применять нечего (сначала review)")

    res = {"applied": [], "skipped": [], "errors": [], "backup": None,
           "log": []}

    # какие файлы затрагиваются принятыми modify/archive — бэкапим их ДО записи
    touched = []
    for a in accept:
        p = by_id[a]
        if p["action"] in ("modify", "archive") and p["target"] not in touched:
            touched.append(p["target"])

    if touched:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        backup_dir = root / "LLM" / f"_backup_{ts}"
        n = 2
        while backup_dir.exists():
            backup_dir = root / "LLM" / f"_backup_{ts}-{n}"
            n += 1
        backup_dir.mkdir(parents=True)
        for t in touched:
            src = root / t
            if src.exists():
                shutil.copy2(src, backup_dir / src.name)
        res["backup"] = "LLM/" + backup_dir.name
        res["log"].append(f"бэкап: {res['backup']}/ (откат — копированием назад)")

    for a in accept:
        p = by_id[a]
        pid = p["id"]
        if not p.get("evidence"):
            res["errors"].append(f"{pid}: пустой evidence — предложение невалидно")
            continue
        target = p["target"].replace("\\", "/")
        if not target.startswith("LLM/"):
            res["errors"].append(f"{pid}: target вне LLM/ запрещён ({target})")
            continue
        if p["action"] == "flag":
            res["skipped"].append(pid)
            res["log"].append(f"{pid}: flag — правится вручную, скриптом пропущено")
            continue
        fpath = root / target
        if not fpath.exists():
            res["errors"].append(f"{pid}: файл не найден: {target}")
            continue
        text = fpath.read_text(encoding="utf-8")
        excerpt = p["current_excerpt"]
        if excerpt not in text:
            res["errors"].append(
                f"{pid}: current_excerpt не найден в {target} "
                f"(файл изменился после propose — повтори propose)")
            continue
        if p["action"] == "modify":
            if not p["proposed_excerpt"]:
                res["errors"].append(f"{pid}: modify без proposed_excerpt")
                continue
            text = text.replace(excerpt, p["proposed_excerpt"], 1)
        elif p["action"] == "archive":
            arch = root / ARCHIVE_REL
            arch.parent.mkdir(parents=True, exist_ok=True)
            entry = (f"\n## из {target} · {date.today().isoformat()} · {pid}\n"
                     f"{excerpt}\n")
            head = "# Архив курирования\n" if not arch.exists() else ""
            with arch.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(head + entry)
            lines = text.splitlines(keepends=True)
            joined = "".join(ln for ln in lines
                             if ln.rstrip("\r\n") != excerpt)
            text = joined if joined != text else text.replace(excerpt, "", 1)
        else:
            res["errors"].append(f"{pid}: неизвестный action «{p['action']}»")
            continue
        fpath.write_text(text, encoding="utf-8", newline="\n")
        res["applied"].append(pid)
        res["log"].append(f"{pid}: применено ({p['action']}) → {target}")

    (cur_dir / "applied.json").write_text(
        json.dumps({"when": datetime.now().strftime("%Y-%m-%dT%H-%M-%S"),
                    "accepted": accept, "applied": res["applied"],
                    "skipped": res["skipped"], "errors": res["errors"],
                    "backup": res["backup"]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    res["log"].append(
        f"итог: применено {len(res['applied'])}, "
        f"пропущено {len(res['skipped'])}, ошибок {len(res['errors'])}")
    return res


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Rot-куратор памяти проекта")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("propose",
                        help="read-only анализ → proposals.json + REPORT.md")
    pp.add_argument("--project", default=".", help="корень проекта или подпапка")
    ap = sub.add_parser("apply",
                        help="применить принятые предложения (после review)")
    ap.add_argument("stamp", help="метка прогона propose (папка в LLM/.curate/)")
    ap.add_argument("--accept", default="", help="id принятых через запятую: p1,p3")
    ap.add_argument("--project", default=".", help="корень проекта или подпапка")
    args = p.parse_args(argv)

    if args.cmd == "propose":
        out_dir = propose(Path(args.project))
        root = find_project_root(Path(args.project))
        rel = out_dir.relative_to(root).as_posix()
        data = json.loads((out_dir / "proposals.json").read_text(encoding="utf-8"))
        print(f"propose: {len(data['proposals'])} предложений → {rel}/")
        print(f"дальше: прочитать {rel}/REPORT.md, затем apply --accept id,…")
        return 0

    accepted = [a.strip() for a in args.accept.split(",") if a.strip()]
    res = apply(Path(args.project), args.stamp, accepted)
    for line in res["log"]:
        print(line)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
