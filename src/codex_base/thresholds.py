"""Пороги matched A/B — единый источник без импортов внутри пакета.

DEFAULT_MIN_MEDIAN_INPUT_REDUCTION — общая планка для любого benchmark.
Снижать её глобально нельзя: послабление действовало бы на все будущие
эксперименты. Отклонение оформляется в конкретном benchmark contract полем
threshold_override (authority, previous, reason_code) и действует только там.
"""

DEFAULT_MIN_MEDIAN_INPUT_REDUCTION = 0.25


def effective_min_reduction(benchmark: dict | None = None) -> float:
    """Порог для benchmark: override, если он объявлен в самом контракте."""
    override = (benchmark or {}).get("threshold_override") or {}
    value = override.get("median_input_reduction_min")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return DEFAULT_MIN_MEDIAN_INPUT_REDUCTION
