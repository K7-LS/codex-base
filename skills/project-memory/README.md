# project-memory — единое ядро Claude/Codex

Навык хранит переносимую память проекта в одном каталоге. Существующее валидное
`Claude/` или `Codex/` всегда переиспользуется; параллельное второе ядро не
создаётся. При первом развороте из Codex используется `Codex/`, а в корне
создаются оба указателя: `AGENTS.md` и `CLAUDE.md`.

```powershell
python "$HOME\.agents\skills\project-memory\tools\bootstrap.py" `
  "Имя проекта" --target "<корень проекта>"
```

Повторный запуск ничего не затирает. Если обнаружены два несогласованных ядра,
команда возвращает `CORE_CONFLICT` до записи файлов.

Курирование также автоматически использует выбранное ядро:

```powershell
python "$HOME\.agents\skills\project-memory\tools\curate_rot.py" `
  propose --project "<корень проекта>"
python "$HOME\.agents\skills\project-memory\tools\curate_rot.py" `
  apply <stamp> --accept p1 --project "<корень проекта>"
```

Глобальные project hooks этот навык не устанавливает.
