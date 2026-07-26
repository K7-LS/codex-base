# PDF Drawings — режим чертежей

## Когда использовать

PDF, которые на самом деле чертежи:
- Альбомные A1/A3
- Штамп в правом нижнем углу с проектом, номером листа, масштабом
- Векторные слои (СКС, СКУД, CCTV в слаботочных проектах)

## Извлечение текстовых блоков с координатами

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".agents/skills/doc-extract/tools"))
from extract_drawing_meta import extract_text_blocks

blocks = extract_text_blocks("plan_floor1.pdf", page=0)
for b in blocks:
    x0, y0, x1, y1 = b["bbox"]
    print(f"[{x0:.0f},{y0:.0f}] {b['text']}")
```

## Поиск штампа

```python
from extract_drawing_meta import find_stamp_data
import pdfplumber

with pdfplumber.open("drawing.pdf") as pdf:
    page = pdf.pages[0]
    page_size = (page.width, page.height)

blocks = extract_text_blocks("drawing.pdf", page=0)
stamp = find_stamp_data(blocks, page_size)
```

## Извлечение помещений по легенде

```python
import pdfplumber

with pdfplumber.open("plan.pdf") as pdf:
    for i, page in enumerate(pdf.pages):
        for table in page.extract_tables():
            for row in table:
                if row and "помещение" in (row[0] or "").lower():
                    print(f"Page {i}:", row)
```

## Слои в PDF

```python
from pypdf import PdfReader
r = PdfReader("plan.pdf")
oc_groups = r.trailer["/Root"].get("/OCProperties", {}).get("/OCGs", [])
for ocg in oc_groups:
    print(ocg.get_object()["/Name"])
```

## Дальше

- Если в PDF только растровое изображение чертежа — используй skill `image-text-replace`
- Если есть исходный DWG — лучше используй skill `cad-reader` (точнее)
