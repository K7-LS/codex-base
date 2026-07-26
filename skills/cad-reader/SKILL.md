---
name: cad-reader
description: Use when нужно прочитать геометрию, слои или блоки DWG/DXF.
---

# CAD Reader Skill (<организация>)

## ⚠ Предусловия

Перед использованием убедись что установлен **ODA File Converter** (бесплатный, для конвертации `.dwg` → `.dxf`). См. `INSTALL.md` в этой же папке. Без ODA работает **только** чтение `.dxf` напрямую (через `ezdxf`).

Python-зависимости: `ezdxf` (`pip install ezdxf` если не стоит).

## Когда применять

- Заказчик прислал чертёж .dwg/.dxf — нужно понять состав систем
- Спецификация оборудования по чертежу (через блоки)
- Извлечь штамп — название проекта, номер листа, масштаб
- Подсчёт помещений по слою (для слаботочных проектов = площадь = объём кабеля)

**Не работает с:** Revit (.rvt), IFC, Compass-3D — для них отдельные подходы.

## Quick Start

### Список слоёв в DXF

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".agents/skills/cad-reader/scripts"))
from extract_dxf import list_layers

print(list_layers("plan.dxf"))
# ['0', 'walls', 'doors', 'SKS', 'SKUD', 'CCTV', 'stamp', 'dimensions']
```

### Поиск текста по слою

```python
from extract_dxf import extract_text_entities

labels = extract_text_entities("plan.dxf", layer="SKS")
for t in labels:
    print(f"({t['x']:.1f}, {t['y']:.1f}) {t['text']}")
```

### Штамп

```python
from extract_dxf import find_stamp

stamp = find_stamp("plan.dxf", stamp_layer="stamp")
# {'project': '<проект>', 'drawing_no': '5', 'scale': '1:50', 'stage': 'РД', ...}
```

### Конвертация DWG -> DXF

```python
from dwg_to_dxf import dwg_to_dxf

dxf_path = dwg_to_dxf("incoming.dwg", output_dir="artifacts/")
```

### Список блоков

```python
from extract_dxf import list_blocks

blocks = list_blocks("plan.dxf")
```

## Установка ODA File Converter
См. `INSTALL.md`.

## Стандартные слои в проектах <организация>

- `SKS` или `СКС` — структурированная кабельная система
- `SKUD` или `СКУД` — контроль доступа
- `CCTV` или `Видеонаблюдение`
- `OPS` или `ОПС` — пожарная сигнализация
- `LVS` или `ЛВС` — локальная сеть

## Tools (слой 3)

Папка `scripts/` — это 3-й слой стандарта скиллов (Description + Instructions + **Tools**): детерминированные Python-скрипты, к которым обращаются примеры выше.

- `extract_dxf.py` — чтение DXF через `ezdxf`: `list_layers`, `extract_text_entities`, `find_stamp`, `list_blocks`.
- `dwg_to_dxf.py` — конвертация `.dwg` → `.dxf` через ODA File Converter (`dwg_to_dxf`, `find_oda_executable`).
- `test_extract_dxf.py` — тесты для `extract_dxf`.

Скрипты остаются в `scripts/` (не переименовывать в `tools/`).
