# sync-base alias

Текст `/sync-base` маршрутизируется в нативный control-skill `$sync-base`.
Отдельный custom prompt не создаётся.

Навык получает только стабильный target-bound release, проверяет provenance и
attestation, вызывает Foundation `plan`/`install`/`doctor` и при ошибке делает
`rollback`. Поток только hub → consumer; обратная отправка отсутствует.
