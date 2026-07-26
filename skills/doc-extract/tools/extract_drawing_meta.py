"""Извлечение текстовых блоков из PDF + поиск штампа чертежа."""
from typing import List, Dict, Tuple, Optional
import pdfplumber
import re

def extract_text_blocks(pdf_path: str, page: int = 0) -> List[Dict]:
    """Возвращает список блоков {text, bbox=(x0,y0,x1,y1)} со страницы."""
    blocks = []
    with pdfplumber.open(pdf_path) as pdf:
        if page >= len(pdf.pages):
            return []
        p = pdf.pages[page]
        for word in p.extract_words():
            blocks.append({
                "text": word["text"],
                "bbox": (word["x0"], word["top"], word["x1"], word["bottom"]),
            })
    return blocks

def find_stamp_data(blocks: List[Dict], page_size: Tuple[float, float]) -> Dict[str, Optional[str]]:
    """Ищет данные штампа в правом нижнем углу (типичное место).

    Возвращает {project, drawing_no, scale, stage} с None для ненайденного.
    """
    pw, ph = page_size
    # Штамп обычно в нижней правой четверти
    stamp_blocks = [b for b in blocks if b["bbox"][0] > pw * 0.6 and b["bbox"][1] > ph * 0.5]
    text_concat = " ".join(b["text"] for b in stamp_blocks)

    return {
        "project": _grep(text_concat, r"Проект[:\s]+([^\s,]+)"),
        "drawing_no": _grep(text_concat, r"Лист[:\s]+(\S+)"),
        "scale": _grep(text_concat, r"М\s*([0-9:]+)") or _grep(text_concat, r"1[:/]([0-9]+)"),
        "stage": _grep(text_concat, r"(Стадия|Раздел)[:\s]+(\S+)"),
        "raw_stamp_text": text_concat[:500],
    }

def _grep(text: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(1) if m else None
