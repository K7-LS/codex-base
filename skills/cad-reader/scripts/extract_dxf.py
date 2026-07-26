"""Извлечение данных из DXF через ezdxf: слои, текст, штамп."""
import re
from typing import List, Dict, Optional
import ezdxf


def list_layers(dxf_path: str) -> List[str]:
    """Список всех слоёв в DXF (из таблицы слоёв + из сущностей)."""
    doc = ezdxf.readfile(dxf_path)
    layers = {layer.dxf.name for layer in doc.layers}
    # Некоторые DXF-файлы содержат сущности на слоях, не внесённых в таблицу
    for entity in doc.modelspace():
        try:
            layers.add(entity.dxf.layer)
        except Exception:
            pass
    return sorted(layers)


def extract_text_entities(dxf_path: str, layer: Optional[str] = None) -> List[Dict]:
    """Возвращает все TEXT/MTEXT сущности с их координатами и слоями."""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    out = []
    for entity in msp.query("TEXT MTEXT"):
        ent_layer = entity.dxf.layer
        if layer and ent_layer != layer:
            continue
        if entity.dxftype() == "MTEXT":
            text = entity.text
        else:
            text = entity.dxf.text
        x, y = entity.dxf.insert[0], entity.dxf.insert[1]
        out.append({"text": text, "layer": ent_layer, "x": x, "y": y})
    return out


def find_stamp(dxf_path: str, stamp_layer: str = "stamp") -> Dict[str, Optional[str]]:
    """Извлекает данные штампа: проект, номер листа, масштаб, стадия."""
    texts = extract_text_entities(dxf_path, layer=stamp_layer)
    text_concat = " ".join(t["text"] for t in texts)

    return {
        "project": _grep(text_concat, r"Проект[:\s]+([^\s,]+)"),
        "drawing_no": _grep(text_concat, r"Лист[:\s]+(\S+)"),
        "scale": _grep(text_concat, r"М\s*([0-9:]+)") or _grep(text_concat, r"1[:/]([0-9]+)"),
        "stage": _grep(text_concat, r"(?:Стадия|Раздел)[:\s]+(\S+)"),
        "raw_stamp_text": text_concat[:500],
    }


def _grep(text: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def list_blocks(dxf_path: str) -> List[Dict]:
    """Список вставок блоков (часто = оборудование/мебель в спецификациях)."""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    blocks = []
    for ins in msp.query("INSERT"):
        blocks.append({
            "name": ins.dxf.name,
            "layer": ins.dxf.layer,
            "x": ins.dxf.insert[0],
            "y": ins.dxf.insert[1],
        })
    return blocks
