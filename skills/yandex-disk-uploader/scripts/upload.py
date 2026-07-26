"""Загрузка файлов на Я.Диск в правильную папку проекта.

Использует WebDAV напрямую (requests). Опция: можно завернуть как обёртку над MCP webdav,
но для надёжности smoke-тестов держим прямой вызов.
"""
from enum import Enum
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional

WEBDAV_URL = "https://webdav.yandex.ru/"

class FileType(Enum):
    """Тип файла → подпапка проекта."""
    GENERAL = "00_Общее"
    KP = "01_КП"  # коммерческое предложение
    CONTRACT = "02_Договор"
    FINANCE = "03_Финансы"
    INVOICE = "03_Финансы"  # alias для счетов
    TZ = "04_ТЗ"
    DRAWINGS = "05_Чертежи"
    CORRESPONDENCE = "02_Договор/05_Переписка"
    ACTS = "06_Акты"
    REPORTS = "07_Отчёты"
    ARCHIVE = "08_Архив"

def resolve_target_path(project_code: str, file_type: FileType, filename: str) -> str:
    """Возвращает relative-путь от корня Я.Диска: 02_Проекты/<код>/<подпапка>/<filename>."""
    if not project_code:
        raise ValueError("project_code is required")
    if not filename:
        raise ValueError("filename is required")
    return f"02_Проекты/{project_code}/{file_type.value}/{filename}"

def upload_file(local_path: str, target_path: str, user: str, password: str) -> str:
    """Загружает локальный файл на Я.Диск по target_path. Возвращает full URL загруженного файла."""
    p = Path(local_path)
    if not p.exists():
        raise FileNotFoundError(local_path)

    target_url = WEBDAV_URL + target_path.lstrip("/")
    # Создаём промежуточные директории (MKCOL для каждой части пути)
    parts = target_path.split("/")[:-1]
    cur = ""
    for part in parts:
        cur = cur + "/" + part if cur else part
        url_dir = WEBDAV_URL + cur
        requests.request("MKCOL", url_dir, auth=HTTPBasicAuth(user, password), timeout=10)
        # 201 = создано, 405 = уже существует — оба ОК

    with open(p, "rb") as f:
        r = requests.put(target_url, data=f, auth=HTTPBasicAuth(user, password), timeout=60)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"Upload failed: {r.status_code} {r.text}")
    return target_url

def load_credentials(env_path: str = ".env") -> tuple[str, str]:
    env = {}
    try:
        for line in Path(env_path).read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    user = env.get("YANDEX_DISK_USER") or env.get("WEBDAV_USERNAME")
    pwd = env.get("YANDEX_DISK_PASS") or env.get("WEBDAV_PASSWORD")
    if not (user and pwd):
        raise RuntimeError("YANDEX_DISK_USER/PASS or WEBDAV_USERNAME/PASSWORD not in .env")
    return user, pwd
