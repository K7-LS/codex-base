"""Конвертация DWG -> DXF через ODA File Converter (бесплатный, от Open Design Alliance)."""
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Типичные пути установки ODA на Windows
DEFAULT_PATHS = [
    r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe",
    r"C:\Program Files\ODA\ODAFileConverter 25.4.0\ODAFileConverter.exe",
    r"C:\Program Files\ODA\ODAFileConverter 24.5.0\ODAFileConverter.exe",
    r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
]


def find_oda_executable() -> Optional[str]:
    """Ищет ODAFileConverter.exe в стандартных местах + PATH."""
    for p in DEFAULT_PATHS:
        if os.path.exists(p):
            return p
    found = shutil.which("ODAFileConverter")
    if found:
        return found
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    oda_dir = Path(pf) / "ODA"
    if oda_dir.exists():
        for sub in oda_dir.iterdir():
            exe = sub / "ODAFileConverter.exe"
            if exe.exists():
                return str(exe)
    return None


def dwg_to_dxf(dwg_path: str, output_dir: Optional[str] = None) -> str:
    """Конвертирует DWG в DXF. Возвращает путь к DXF."""
    exe = find_oda_executable()
    if not exe:
        raise RuntimeError(
            "ODA File Converter не найден. Установка: см. INSTALL.md в skill cad-reader."
        )

    dwg = Path(dwg_path).resolve()
    if not dwg.exists():
        raise FileNotFoundError(dwg_path)

    in_dir = dwg.parent
    out_dir = Path(output_dir) if output_dir else in_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        exe,
        str(in_dir), str(out_dir),
        "ACAD2018", "DXF",
        "0", "1",
        dwg.name,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ODA failed: {result.stderr}")

    out_dxf = out_dir / (dwg.stem + ".dxf")
    if not out_dxf.exists():
        raise RuntimeError(f"Conversion produced no output: expected {out_dxf}")
    return str(out_dxf)
