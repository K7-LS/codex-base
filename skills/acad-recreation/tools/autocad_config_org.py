"""Backend detection and environment configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import structlog

log = structlog.get_logger()

# Paths
LISP_DIR = Path(__file__).resolve().parent.parent.parent / "lisp-code"
IPC_DIR = Path(os.environ.get("AUTOCAD_MCP_IPC_DIR", "C:/temp"))

# Backend selection
BACKEND_DEFAULT = "auto"  # auto | file_ipc | ezdxf

# IPC timeout (seconds), clamped to [1, 300]
IPC_TIMEOUT = max(1.0, min(300.0, float(os.environ.get("AUTOCAD_MCP_IPC_TIMEOUT", "10.0"))))

# Screenshot
ONLY_TEXT_FEEDBACK = os.environ.get("AUTOCAD_MCP_ONLY_TEXT", "").lower() in ("1", "true", "yes")

# Win32 availability
WIN32_AVAILABLE = sys.platform == "win32"

# Autostart guard: AutoCAD is launched at most once per server lifetime.
_autostart_attempted = False


def _current_backend_env() -> str:
    """Read backend selection from env with normalization."""
    return os.environ.get("AUTOCAD_MCP_BACKEND", BACKEND_DEFAULT).strip().lower()


def _is_wsl() -> bool:
    """Detect WSL Linux runtime."""
    if os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in os.uname().release.lower()
    except AttributeError:
        return False


def _write_debug_snapshot(backend_env: str):
    """Optionally write backend detection debug information.

    Set AUTOCAD_MCP_DEBUG_DETECT_FILE to enable.
    """
    debug_file = os.environ.get("AUTOCAD_MCP_DEBUG_DETECT_FILE", "").strip()
    if not debug_file:
        return

    try:
        debug_path = Path(debug_file)
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        with debug_path.open("w", encoding="utf-8") as f:
            f.write(f"sys.platform={sys.platform}\n")
            f.write(f"WIN32_AVAILABLE={WIN32_AVAILABLE}\n")
            f.write(f"BACKEND_ENV={backend_env}\n")
            f.write(f"python={sys.executable}\n")
    except Exception:
        # Best-effort only; never fail backend detection due debug writes.
        pass


def _find_acad_exe() -> str | None:
    """Locate the AutoCAD executable for autostart (newest version first).

    Honors AUTOCAD_MCP_ACAD_EXE override; otherwise scans
    Program Files[\\ (x86)]\\Autodesk for acad.exe (full) then acadlt.exe (LT).
    """
    import glob

    explicit = os.environ.get("AUTOCAD_MCP_ACAD_EXE", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit

    bases = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    full, lt = [], []
    for base in bases:
        if not base:
            continue
        full += glob.glob(str(Path(base) / "Autodesk" / "*" / "acad.exe"))
        lt += glob.glob(str(Path(base) / "Autodesk" / "*" / "acadlt.exe"))
    # Prefer full AutoCAD over LT; newest version folder first (sort desc).
    candidates = sorted(full, reverse=True) + sorted(lt, reverse=True)
    return candidates[0] if candidates else None


def _try_launch_autocad() -> int | None:
    """Launch AutoCAD and wait for its window. Returns hwnd, or None on failure.

    Wait timeout: AUTOCAD_MCP_AUTOSTART_WAIT seconds (default 90, clamped 10..300).
    """
    import subprocess
    import time as _time

    from autocad_mcp.backends.file_ipc import find_autocad_window

    # Race guard: window may have appeared between checks.
    hwnd = find_autocad_window()
    if hwnd:
        return hwnd

    exe = _find_acad_exe()
    if not exe:
        log.warning("autostart_no_acad_exe")
        return None

    wait_s = max(10.0, min(300.0, float(os.environ.get("AUTOCAD_MCP_AUTOSTART_WAIT", "90"))))
    log.info("autostart_launching", exe=exe, wait_s=wait_s)
    try:
        subprocess.Popen([exe], close_fds=True)
    except Exception as e:  # noqa: BLE001 - best-effort launch
        log.warning("autostart_launch_failed", error=str(e))
        return None

    deadline = _time.time() + wait_s
    while _time.time() < deadline:
        hwnd = find_autocad_window()
        if hwnd:
            log.info("autostart_window_ready", hwnd=hwnd)
            return hwnd
        _time.sleep(2.0)
    log.warning("autostart_window_timeout", wait_s=wait_s)
    return None


def detect_backend() -> str:
    """Return the backend name to use: 'file_ipc' or 'ezdxf'.

    Policy (ORG patch): in 'auto' mode ALWAYS prefer the live AutoCAD (file_ipc).
    The headless ezdxf backend is reachable ONLY via an explicit
    AUTOCAD_MCP_BACKEND=ezdxf — it never silently substitutes the live AutoCAD.
    When AutoCAD is closed in auto/file_ipc mode we try to launch it
    (AUTOCAD_MCP_AUTOSTART, default on) and, failing that, raise an actionable
    error instead of degrading to ezdxf.
    """
    global _autostart_attempted

    backend_env = _current_backend_env()
    _write_debug_snapshot(backend_env)

    # Explicit headless is the ONLY route to ezdxf.
    if backend_env == "ezdxf":
        log.info("using_ezdxf_backend", reason="explicit")
        return "ezdxf"

    # Off-Windows there is no live AutoCAD; ezdxf is the only option.
    if not WIN32_AVAILABLE:
        if backend_env == "file_ipc":
            raise RuntimeError(
                "AUTOCAD_MCP_BACKEND=file_ipc requires Windows. "
                "Use AUTOCAD_MCP_BACKEND=ezdxf for headless mode."
            )
        log.info("non_windows_ezdxf", platform=sys.platform, wsl=_is_wsl())
        return "ezdxf"

    # Windows, auto/file_ipc: live AutoCAD only.
    try:
        from autocad_mcp.backends.file_ipc import find_autocad_window
    except ImportError:
        raise RuntimeError(
            "autocad-mcp needs pywin32 for the live AutoCAD (file_ipc) backend. "
            "Install with: pip install pywin32. "
            "For headless DXF set AUTOCAD_MCP_BACKEND=ezdxf."
        )

    hwnd = find_autocad_window()
    if hwnd:
        log.info("autocad_window_found", hwnd=hwnd)
        return "file_ipc"

    # AutoCAD not running. Try to start it once (default on).
    autostart = os.environ.get("AUTOCAD_MCP_AUTOSTART", "auto").strip().lower()
    if autostart not in ("0", "false", "no", "off") and not _autostart_attempted:
        _autostart_attempted = True
        if _try_launch_autocad():
            return "file_ipc"

    raise RuntimeError(
        "AutoCAD is not running. autocad-mcp uses the live AutoCAD and will NOT "
        "silently fall back to headless ezdxf. Open AutoCAD with a .dwg and retry "
        "(auto-launch of acad.exe was disabled or did not finish in time). "
        "For deliberate headless DXF work set AUTOCAD_MCP_BACKEND=ezdxf."
    )
