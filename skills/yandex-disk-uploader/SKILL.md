---
name: yandex-disk-uploader
description: Use when готовый файл нужно загрузить на Яндекс Диск.
---

# Yandex Disk Uploader Skill (<организация>)

## ⚠ Предусловия

Перед использованием в `.env` (cwd проекта или `~/.codex/base/.env`) должны быть **credentials Я.Диска**:
```
YANDEX_DISK_USER=<email_организации>
YANDEX_DISK_PASS=<пароль_приложения_Yandex_360>
```
(альтернативные имена: `WEBDAV_USERNAME` / `WEBDAV_PASSWORD`)

**Пароль приложения** генерируется в Яндекс ID → Безопасность → Пароли приложений. **Не путать с основным паролем аккаунта** — WebDAV его не примет если включена 2FA.

Python-зависимости: `requests`.

Без `.env` `load_credentials()` упадёт с `RuntimeError`. Если кредов нет — переходи на **MCP `webdav`** (см. секцию «Альтернатива» ниже).

## Когда применять

- После генерации договора → положить в `02_Проекты/<код>/02_Договор/`
- После создания КП → `01_КП/`
- После сохранения переписки → `02_Договор/05_Переписка/`
- Любой артефакт, который должен жить на проектном Я.Диске

## Quick Start

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".agents/skills/yandex-disk-uploader/scripts"))
from upload import upload_file, resolve_target_path, FileType, load_credentials

user, password = load_credentials()

target = resolve_target_path(
    project_code="<проект>",
    file_type=FileType.CORRESPONDENCE,
    filename="2026-04-27-ответ-про-оплату.docx"
)

upload_file(
    local_path="artifacts/2026-04/2026-04-27-ответ-про-оплату.docx",
    target_path=target,
    user=user,
    password=password,
)
```

## Типы файлов

| FileType | Подпапка | Что туда |
|----------|----------|----------|
| `GENERAL` | 00_Общее | паспорт проекта, контакты |
| `KP` | 01_КП | коммерческое предложение |
| `CONTRACT` | 02_Договор | договор + ДС |
| `CORRESPONDENCE` | 02_Договор/05_Переписка | письма, претензии |
| `FINANCE` / `INVOICE` | 03_Финансы | счета, акты сверки, оплаты |
| `TZ` | 04_ТЗ | техническое задание |
| `DRAWINGS` | 05_Чертежи | DWG, PDF чертежей |
| `ACTS` | 06_Акты | акты выполненных работ |
| `REPORTS` | 07_Отчёты | управленческие отчёты |
| `ARCHIVE` | 08_Архив | завершённые материалы |

Полный реестр путей и список проектов — см. `paths_reference.md`.

## Credentials

Из `.env`:
- `YANDEX_DISK_USER` (или `WEBDAV_USERNAME`)
- `YANDEX_DISK_PASS` (или `WEBDAV_PASSWORD`) — пароль приложения Yandex 360

## Альтернатива: webdav MCP

Если подключён опциональный MCP `webdav`, можно заливать файлы через его инструменты:
- `capability `external.tool``
- `capability `external.tool``

Этот MCP не входит в стандартный набор и в конфиге может отсутствовать — проверь `Codex mcp list`. Для скриптовой автоматизации (batch-выгрузка после генерации артефактов) прямой Python из этого skill надёжнее.

## Tools (слой 3)

`scripts/` — детерминированные скрипты этого скилла, 3-й слой стандарта (Description + Instructions + **Tools**):
- `upload.py` — загрузка файла на Я.Диск по WebDAV + маршрутизация в подпапку (`upload_file`, `resolve_target_path`, `FileType`, `load_credentials`).
- `test_upload.py` — проверка загрузки.

Повторяемая логика вынесена в код; модель отвечает только за выбор `FileType` и путь.
