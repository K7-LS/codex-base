# One-way update model

База распространяется только в направлении **hub → consumer**.

## Hub

- хранит рабочий репозиторий;
- собирает target-bound package;
- публикует immutable GitHub Release после acceptance;
- не получает данные с consumer-устройств.

## Consumer

- SessionStart не чаще одного раза в 24 часа проверяет только номер последнего
  стабильного release;
- если обновления нет, не пишет ничего в контекст;
- `$sync-base` скачивает release, проверяет attestation и хэши, строит plan,
  создаёт backup, вызывает Foundation и запускает doctor;
- при ошибке установка откатывается.

Consumer **не отправляет** feedback, телеметрию, отчёты сессий, credentials,
локальные файлы или изменения базы. Автоматическая установка без явного
`$sync-base` запрещена.
