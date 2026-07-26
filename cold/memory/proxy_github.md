# Прокси и GitHub bypass (вынесено из AGENTS.md CORE)

Справка по сетевой настройке за корп-прокси. Загружать по триггерам: «прокси»,
«proxy», «git push падает», «Proxy CONNECT aborted», «настройка нового ПК за прокси».

## Прокси (если за корп-прокси)

Перед запуском `Codex` или открытием VS Code: убедиться что прокси выставлен в
текущей PowerShell-сессии. Codex-lite-instaler копирует хелперы в `~/.codex/base/bin/`
(per-machine, не в git) и ярлык в Пуске:

- `~/.codex/base/bin/Set-Proxy.ps1` — поставить env-vars в текущем окне (`& "$HOME\.codex/base/bin\Set-Proxy.ps1"`)
- `~/.codex/base/bin/Start-Codex.bat` — двойной клик: прокси + выбор CLI/VSCode + Codex
- `~/.codex/base/bin/Start-Codex.ahk` — глобальная горячая клавиша Ctrl+Alt+C (требует AutoHotkey v2)
- **Пуск → «Codex (with proxy)»** — одним кликом запустить (ярлык на `Start-Codex.bat`)

Хелперы persistent: если installer-папка удалена, доступ к ним сохраняется.
Урок 15 закрыт коммитом `3562631` в Codex-lite-instaler (2026-05-18).

Прокси-конфиг (host:port + login) хранится в `~/.codex-proxy.json` (без пароля).
Пароль спрашивается каждую сессию.

Без прокси: MCP-серверы не качают пакеты (✗), `Codex auth login` не работает,
`fetch` не выходит наружу.

## GitHub — обязательный bypass proxy (override Прокси-секции)

**Корп-прокси блокирует CONNECT-метод к GitHub.** Empirically на всех наших ПК
`git push`/`pull`/`fetch` к github.com через прокси падает с `Proxy CONNECT aborted`.
Решение — **bypass proxy** для GitHub-домена.

### Persistent fix (one-time на каждый ПК)

```powershell
git config --global http.https://github.com/.proxy ""
git config --global https.https://github.com/.proxy ""
```

После этого **все** git-операции к `github.com` автоматически идут напрямую, мимо
прокси. Никакие `-c` флаги не нужны. **Рекомендованный путь — применить один раз и забыть.**

Проверка:
```powershell
git config --global --get http.https://github.com/.proxy   # должно вернуть пустую строку
```

`setup-extras.ps1` авто-применяет эту настройку при первом запуске на новом ПК (Step 0).

### Правила для Codex (если persistent config не настроен)

Использовать `-c` флаги в каждой команде:
```powershell
git -c http.proxy="" -c https.proxy="" push origin main
git -c http.proxy="" -c https.proxy="" pull --rebase --autostash
git -c http.proxy="" -c https.proxy="" fetch origin main
git -c http.proxy="" -c https.proxy="" clone https://github.com/<user>/<repo>.git
# gh CLI (GitHub API) — bypass через env:
$env:HTTPS_PROXY=""; gh pr view 123
```

### Что bypass-ится (whitelist прямого подключения)
- `github.com` (git operations, web)
- `api.github.com` (`gh` CLI, REST API)
- `raw.githubusercontent.com`, `*.githubusercontent.com` (raw файлы, releases)
- `objects.githubusercontent.com` (LFS, releases binaries)

### Что нормально через прокси
- `pypi.org`, `files.pythonhosted.org` (uvx, pip install)
- `registry.npmjs.org` (npm install)
- `huggingface.co`, `cdn-lfs.huggingface.co` (модели — LaMa, EasyOCR, SD)
- Microsoft / Anthropic / другие — через прокси нормально.

### Локальные адреса — ВСЕГДА мимо прокси (NO_PROXY)
`127.0.0.1` / `localhost` / `::1` — это локальные HTTP-мосты MCP (Revit Routes `:48884`,
autocad-mcp и пр.), их НЕЛЬЗЯ гнать через корп-прокси. Если `NO_PROXY` не задан, python-`httpx`
(по умолчанию `trust_env=True`) отправляет даже запрос к `127.0.0.1` на `HTTP_PROXY` → прокси
отвечает **пустым `503`** или виснет, и локальный MCP выглядит «мёртвым» (таймаут/disconnect),
хотя сам сервис исправен. Признак: прямой `Invoke-WebRequest http://127.0.0.1:<port>/...` даёт
200 (.NET байпасит local), а MCP-команда — нет (httpx уважает прокси).
**Фикс:** задать env `NO_PROXY=127.0.0.1,localhost,::1` (системно/в Set-Proxy.ps1), а в httpx-клиентах
локальных мостов — `trust_env=False`. Кейс — Revit-Connector ([[reference_revit_mcp]]), 2026-06-18.
Кандидат в `setup-extras.ps1` Step 0 рядом с GitHub-bypass.

### Harvest и WebFetch на GitHub
- `web.fetch` tool на `https://github.com/<owner>/<repo>` — **bypass автоматический**.
- `gh api search/repositories?q=...` — **требует** `$env:HTTPS_PROXY=""` перед вызовом
  (gh не использует git config).

### Anti-pattern
Не обходить прокси-блок «костыльно» (VPN, secondary proxy). Стандарт: bypass proxy
для GitHub-домена, всё остальное — через корп-прокси.
См. также `~/.codex/base/anti-patterns.md` категории 4 (Безопасность) и 8 (PowerShell/Windows).
