#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ru_fetch.py — fetch Russian gov sites/registries from any supported LLM environment,
including machines with a foreign egress (system VPN like WARP/Dubai, or forced through
a foreign corp proxy). The block on RU gov sites is GEO-only (verified 2026-06: a RU exit
returns 200, no antibot on pages), so a Russian exit-IP is enough for pages and direct PDFs.

Routing (deterministic):
  1. detect REAL egress geo (ipinfo, bypassing proxies)
  2. egress == RU            -> fetch directly (curl --noproxy)
  3. egress != RU:
       a) $RU_PROXY set (reliable paid RU proxy) -> use it
       b) else: cached good proxy (session) -> auto-source free RU-SOCKS5
          (proxifly RU + hookzof list), health-check via ipinfo (country==RU)

Page/PDF fetching works free. SPA registry JSON-APIs (e.g. FSA cert search) need a real
browser session (Spring-Security 403 on curl replay) -> use a browser through a RU proxy,
see SKILL.md (playwright --proxy-server / ScrapingAnt browser country=RU).

Usage:
  python ru_fetch.py <URL> [-o out] [-X POST] [-H 'K: V' ...] [-d '<body>']
                          [--timeout 20] [--tries 16] [--no-cache]
  RU_PROXY=socks5h://user:pass@host:port python ru_fetch.py <URL>   # reliable path

Needs: curl + python3. No pip deps.
"""
import argparse, json, os, re, subprocess, sys, tempfile

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
IPINFO = "https://ipinfo.io/json"
CACHE = os.path.join(tempfile.gettempdir(), "ru_fetch_proxy.txt")
# RU-SOCKS5 sources: proxifly is pre-filtered by country; hookzof is large, RU-heavy (health-checked)
SRC_PREFILTERED_RU = [
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/countries/RU/data.txt",
]
SRC_MIXED = [
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",  # ip:port
]


def run(args, timeout):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 28, b"", b"timeout"
    except Exception as e:  # noqa
        return 1, b"", str(e).encode()


def _country(stdout):
    if not stdout:
        return None
    m = re.search(rb'"country"\s*:\s*"([^"]+)"', stdout)
    return m.group(1).decode() if m else None


def egress_country():
    rc, out, _ = run(["curl", "--noproxy", "*", "-s", "--max-time", "12", IPINFO], 15)
    return _country(out) if rc == 0 else None


def proxy_country(proxy):
    rc, out, _ = run(["curl", "-s", "--max-time", "7", "-x", proxy, IPINFO], 9)
    return _country(out) if rc == 0 else None


def _dl(url):
    rc, out, _ = run(["curl", "--noproxy", "*", "-s", "--max-time", "25", url], 30)
    return out.decode("utf-8", "replace") if rc == 0 else ""


def candidates():
    """RU-SOCKS5 candidates: prefiltered-RU first (high hit-rate), then mixed (health-checked)."""
    out = []
    for url in SRC_PREFILTERED_RU:
        for ln in _dl(url).splitlines():
            ln = ln.strip()
            if ln.startswith("socks5://"):
                out.append(("socks5h://" + ln[len("socks5://"):], True))   # True = likely RU
            elif ln.startswith("socks4://"):
                out.append(("socks4a://" + ln[len("socks4://"):], True))
    for url in SRC_MIXED:
        for ln in _dl(url).splitlines():
            ln = ln.strip()
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}:\d+$", ln):
                out.append(("socks5h://" + ln, False))                     # needs check
    # dedupe, keep order
    seen, uniq = set(), []
    for px, ru in out:
        if px not in seen:
            seen.add(px); uniq.append((px, ru))
    return uniq


def find_live_ru(tries, want=2):
    live = []
    # 1) try cached proxy first
    if os.path.exists(CACHE):
        try:
            cpx = open(CACHE).read().strip()
            if cpx and proxy_country(cpx) == "RU":
                print(f"[cache] reuse {cpx}")
                live.append(cpx)
        except Exception:  # noqa
            pass
    if len(live) >= want:
        return live
    checked = 0
    for px, _ in candidates():
        if px in live:
            continue
        if checked >= tries and live:
            break
        checked += 1
        if proxy_country(px) == "RU":
            live.append(px)
            print(f"[proxy] live RU: {px}")
            if len(live) >= want:
                break
    if live:
        try:
            open(CACHE, "w").write(live[0])
        except Exception:  # noqa
            pass
    return live


def build_curl(url, proxy, a, direct):
    args = ["curl", "-sSL", "-A", UA, "-w", "\n__HTTP__%{http_code}",
            "--max-time", str(a.timeout)]
    if direct:
        args += ["--noproxy", "*"]
    else:
        args += ["-x", proxy]            # NB: no --noproxy here, it would cancel -x
    if a.method:
        args += ["-X", a.method]
    for h in (a.header or []):
        args += ["-H", h]
    if a.data is not None:
        args += ["-d", a.data]
    if a.out:
        args += ["-o", a.out]
    args += [url]
    return args


def http_code(stdout):
    m = re.search(rb"__HTTP__(\d{3})", stdout or b"")
    return m.group(1).decode() if m else None


def do_fetch(url, proxy, a, direct=False):
    rc, out, err = run(build_curl(url, proxy, a, direct), a.timeout + 6)
    code = http_code(out)
    if not a.out and out:
        body = re.sub(rb"\n__HTTP__\d{3}$", b"", out)
        sys.stdout.buffer.write(body)
    return code, rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("-o", "--out")
    ap.add_argument("-X", "--method")
    ap.add_argument("-H", "--header", action="append")
    ap.add_argument("-d", "--data")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--tries", type=int, default=16, help="mixed proxies to health-check")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    if a.no_cache and os.path.exists(CACHE):
        try:
            os.remove(CACHE)
        except Exception:  # noqa
            pass

    country = egress_country()
    print(f"[egress] country={country}")

    if country == "RU":
        print("[route] egress=RU -> direct (--noproxy)")
        code, rc = do_fetch(a.url, None, a, direct=True)
        print(f"[result] HTTP {code} rc={rc}")
        return 0 if code and code[0] in "23" else 2

    proxies = []
    if os.environ.get("RU_PROXY"):
        print("[route] using $RU_PROXY")
        proxies = [os.environ["RU_PROXY"]]
    else:
        print("[route] egress!=RU, no $RU_PROXY -> auto free RU-SOCKS5 (proxifly+hookzof)")
        proxies = find_live_ru(a.tries)
        print(f"[proxies] live RU: {len(proxies)} -> {proxies}")
        if not proxies:
            print("[FAIL] no live free RU proxy. Retry or set RU_PROXY=socks5h://host:port (see SKILL.md).")
            return 3

    for px in proxies:
        code, rc = do_fetch(a.url, px, a)
        print(f"[try] {px} -> HTTP {code} rc={rc}")
        if code and code[0] in "23":
            print(f"[OK] via {px}")
            return 0
        if code == "403":
            print("[hint] 403 = likely SPA/Spring API needing a browser session, "
                  "not a geo block. Use a browser via RU proxy (SKILL.md: data-layer).")
    print("[FAIL] no RU proxy returned 2xx/3xx. Retry (lists refresh each run) or set RU_PROXY.")
    return 4


if __name__ == "__main__":
    sys.exit(main())
