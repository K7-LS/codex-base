#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
local-osint-recon — диспетчер вызовов OSINT/pentest-арсенала в Kali WSL.

Зовётся с Windows-хоста, оборачивает
`wsl.exe -d <дистрибутив> [-u root] -- <tool>`.
- пассив запускается свободно;
- active/offensive требует явный флаг --authorized;
- go-инструменты вызываются от root по полному пути /root/go/bin/<t>;
- Windows-пути файлов конвертируются в /mnt/c/...;
- неизвестные инструменты fail closed;
- отсутствующие зависимости дают BLOCKED и не устанавливаются автоматически.
"""
import argparse
import os
import subprocess
import sys

DISTRO = os.environ.get("LOCAL_OSINT_WSL_DISTRO", "kali").strip() or "kali"

# category: passive | active | offensive   (гейт на active/offensive)
# runner:   user | root                     (go-инструменты — root)
# path:     None -> звать по имени; иначе полный путь
# needs_key: True -> без API-ключа пропускать
TOOLS = {
    # --- пассив ---
    "dnstwist":        dict(cat="passive", runner="user", path="/usr/local/bin/dnstwist"),
    "sublist3r":       dict(cat="passive", runner="user", path="/usr/local/bin/sublist3r"),
    "dnsrecon":        dict(cat="passive", runner="user", path="/usr/local/bin/dnsrecon"),
    "holehe":          dict(cat="passive", runner="user", path="/usr/local/bin/holehe"),
    "socialscan":      dict(cat="passive", runner="user", path="/usr/local/bin/socialscan"),
    "maigret":         dict(cat="passive", runner="user", path="/usr/local/bin/maigret"),
    "sherlock":        dict(cat="passive", runner="user", path="/usr/local/bin/sherlock"),
    "osrframework-cli":dict(cat="passive", runner="user", path="/usr/local/bin/osrframework-cli"),
    "crosslinked":     dict(cat="passive", runner="user", path="/usr/local/bin/crosslinked"),
    "snscrape":        dict(cat="passive", runner="user", path="/usr/local/bin/snscrape"),
    "h8mail":          dict(cat="passive", runner="user", path="/usr/local/bin/h8mail"),
    "exiftool":        dict(cat="passive", runner="user", path="/usr/bin/exiftool"),
    "subfinder":       dict(cat="passive", runner="root", path="/root/go/bin/subfinder"),
    "waybackurls":     dict(cat="passive", runner="root", path="/root/go/bin/waybackurls"),
    "bbot":            dict(cat="passive", runner="user", path="/usr/local/bin/bbot"),
    # --- нужен ключ (пропуск) ---
    "shodan":          dict(cat="passive", runner="user", path="/usr/local/bin/shodan",  needs_key=True),
    "censys":          dict(cat="passive", runner="user", path="/usr/local/bin/censys",  needs_key=True),
    "greynoise":       dict(cat="passive", runner="user", path="/usr/local/bin/greynoise", needs_key=True),
    "zoomeye":         dict(cat="passive", runner="user", path="/usr/local/bin/zoomeye", needs_key=True),
    # --- active (гейт) ---
    "nmap":            dict(cat="active", runner="user", path="/usr/bin/nmap"),
    "masscan":         dict(cat="active", runner="user", path="/usr/bin/masscan"),
    "httpx":           dict(cat="active", runner="user", path="/usr/local/bin/httpx"),
    "knockpy":         dict(cat="active", runner="user", path="/usr/local/bin/knockpy"),
    "whatweb":         dict(cat="active", runner="user", path="/usr/bin/whatweb"),
    "nikto":           dict(cat="active", runner="user", path="/usr/bin/nikto"),
    "spiderfoot":      dict(cat="active", runner="user", path="/usr/bin/spiderfoot"),
    "dirsearch":       dict(cat="active", runner="user", path="/usr/local/bin/dirsearch"),
    "amass":           dict(cat="active", runner="root", path="/root/go/bin/amass"),
    "naabu":           dict(cat="active", runner="root", path="/root/go/bin/naabu"),
    "gobuster":        dict(cat="active", runner="root", path="/root/go/bin/gobuster"),
    "ffuf":            dict(cat="active", runner="root", path="/root/go/bin/ffuf"),
    "nuclei":          dict(cat="active", runner="root", path="/root/go/bin/nuclei"),
    "gospider":        dict(cat="active", runner="root", path="/root/go/bin/gospider"),
    "gowitness":       dict(cat="active", runner="root", path="/root/go/bin/gowitness"),
    "onionscan":       dict(cat="active", runner="root", path="/root/go/bin/onionscan"),
    # --- offensive (гейт, усиленное предупреждение) ---
    "sqlmap":          dict(cat="offensive", runner="user", path="/usr/bin/sqlmap"),
    "hydra":           dict(cat="offensive", runner="user", path="/usr/bin/hydra"),
    "john":            dict(cat="offensive", runner="user", path="/usr/sbin/john"),
    "hashcat":         dict(cat="offensive", runner="user", path="/usr/bin/hashcat"),
    "msfconsole":      dict(cat="offensive", runner="user", path="/usr/bin/msfconsole"),
    "Modlishka":       dict(cat="offensive", runner="root", path="/root/go/bin/Modlishka"),
    "frida":           dict(cat="offensive", runner="user", path="/usr/local/bin/frida"),
    "objection":       dict(cat="offensive", runner="user", path="/usr/local/bin/objection"),
}

GATED = {"active", "offensive"}


def wsl_cmd(tool_meta, args):
    """Собрать список аргументов для subprocess -> wsl.exe."""
    base = ["wsl.exe", "-d", DISTRO]
    if tool_meta["runner"] == "root":
        base += ["-u", "root"]
    base += ["--", tool_meta["path"] or _bare_name(tool_meta)]
    return base + list(args)


def _bare_name(meta):
    return meta.get("name", "")


def win_to_wsl(p):
    """C:\\Users\\x\\f.pdf -> /mnt/c/Users/x/f.pdf"""
    p = os.path.abspath(p)
    drive, rest = os.path.splitdrive(p)
    if drive:
        letter = drive[0].lower()
        rest = rest.replace("\\", "/")
        return f"/mnt/{letter}{rest}"
    return p.replace("\\", "/")


def run_tool(name, args, authorized=False, capture=False):
    meta = TOOLS.get(name)
    if meta is None:
        print(
            f"[BLOCKED] {name}: инструмента нет в публичном allowlist; "
            "автоматический запуск запрещён."
        )
        return 3
    if meta.get("needs_key"):
        print(
            f"[i] {name}: нужны заранее настроенные пользователем credentials; "
            "база ключи не предоставляет."
        )
    if meta["cat"] in GATED and not authorized:
        warn = "OFFENSIVE" if meta["cat"] == "offensive" else "ACTIVE RECON"
        print("=" * 68)
        print(f"  WARNING — {name}: {warn}")
        print("  Запуск разрешён только для собственной или явно авторизованной цели.")
        print("  Получи текущее подтверждение и повтори с флагом --authorized.")
        print("=" * 68)
        return 2
    probe = ["wsl.exe", "-d", DISTRO]
    if meta["runner"] == "root":
        probe += ["-u", "root"]
    probe += ["--", "test", "-x", meta["path"]]
    cmd = wsl_cmd(meta, args)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        available = subprocess.run(
            probe,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if available.returncode != 0:
            print(
                f"[BLOCKED] {name}: {meta['path']} недоступен в WSL "
                f"дистрибутиве {DISTRO}; установи/настрой зависимость отдельно."
            )
            return 3
        r = subprocess.run(cmd, env=env, text=True, encoding="utf-8", errors="replace",
                           capture_output=capture)
    except FileNotFoundError:
        print("[err] wsl.exe не найден — WSL не установлен или не в PATH.")
        return 1
    if capture:
        return r
    return r.returncode


def recipe(cmds):
    """Прогнать серию (name, args) пассивных вызовов, печатая заголовки."""
    for name, args in cmds:
        print(f"\n===== {name} {' '.join(args)} =====")
        run_tool(name, args, authorized=False)


def cmd_list(_):
    for cat in ("passive", "active", "offensive"):
        names = sorted(n for n, m in TOOLS.items() if m["cat"] == cat)
        gate = "" if cat == "passive" else "  (гейт: --authorized)"
        print(f"\n[{cat}]{gate}")
        for n in names:
            key = "  *needs API key" if TOOLS[n].get("needs_key") else ""
            root = "  (root)" if TOOLS[n]["runner"] == "root" else ""
            print(f"  {n}{root}{key}")


def cmd_dd_domain(a):
    d = a.target
    recipe([
        ("dnstwist",  ["--registered", d]),
        ("sublist3r", ["-d", d]),
        ("dnsrecon",  ["-d", d]),
        ("subfinder", ["-silent", "-d", d]),
    ])


def cmd_dd_email(a):
    recipe([
        ("holehe",     [a.target]),
        ("socialscan", [a.target]),
    ])


def cmd_dd_user(a):
    recipe([("maigret", [a.target])])


def cmd_meta(a):
    run_tool("exiftool", [win_to_wsl(a.target)], authorized=False)


def cmd_run(a):
    args = list(a.args or [])
    authorized = a.authorized
    if "--authorized" in args:
        authorized = True
        args = [x for x in args if x != "--authorized"]
    if args and args[0] == "--":
        args = args[1:]
    return run_tool(a.tool, args, authorized=authorized)


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(
        prog="recon.py",
        description=f"local-osint-recon dispatcher (WSL distro: {DISTRO})",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    sp = sub.add_parser("dd-domain"); sp.add_argument("target"); sp.set_defaults(func=cmd_dd_domain)
    sp = sub.add_parser("dd-email");  sp.add_argument("target"); sp.set_defaults(func=cmd_dd_email)
    sp = sub.add_parser("dd-user");   sp.add_argument("target"); sp.set_defaults(func=cmd_dd_user)
    sp = sub.add_parser("meta");      sp.add_argument("target"); sp.set_defaults(func=cmd_meta)

    sp = sub.add_parser("run")
    sp.add_argument("tool")
    sp.add_argument("--authorized", action="store_true")
    sp.add_argument("args", nargs=argparse.REMAINDER)
    sp.set_defaults(func=cmd_run)

    a = p.parse_args()
    rc = a.func(a)
    sys.exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
