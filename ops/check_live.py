"""Live health check of the deployed Ariella site.

Reads /health and times the key public pages. When ARIELLA_OPS_TOKEN is set and
the site exposes /admin/ops-status (see product plan 002), it also reads the
operational summary (scans, daily batch, paid searches, errors, SerpAPI usage).

Usage: python ops/check_live.py [--base https://...] [--out ops/reports/latest.md]
Exit code: 0 ok, 1 problems found, 2 site unreachable from here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = os.getenv("ARIELLA_BASE_URL", "https://ariela-travel-agent.onrender.com")
PAGES = ["/", "/deals", "/login", "/join", "/feedback", "/forgot-password"]
SLOW_SECONDS = 8  # Render may cold-start; anything slower is worth a note


def fetch(url: str, timeout: int = 60) -> tuple[int | str, float, bytes]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Ariella-Eran/1.0"}), timeout=timeout) as r:
            return r.status, time.monotonic() - started, r.read()
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - started, b""
    except Exception as e:  # noqa: BLE001 - any network failure is a finding
        return f"{type(e).__name__}: {e}", time.monotonic() - started, b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--out")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    problems, lines = [], [f"# בדיקת אתר חי — {base}", ""]

    status, secs, body = fetch(base + "/health")
    if not isinstance(status, int):
        lines += [f"❌ האתר לא נגיש מכאן: {status}", "",
                  "אם השגיאה היא 403 של CONNECT — הדומיין לא מאושר ברשת של הסביבה (Allowed domains)."]
        text = "\n".join(lines)
        _write(args.out, text)
        print(text)
        return 2
    health = {}
    try:
        health = json.loads(body or b"{}")
    except ValueError:
        problems.append("/health לא החזיר JSON")
    lines += ["## /health", f"- סטטוס HTTP: {status} ({secs:.1f} שנ')"]
    for key, label in [("status", "מצב"), ("version", "גרסה"), ("database_ok", "מסד נתונים"),
                       ("database_persistent_path", "דיסק קבוע"), ("scheduler_enabled", "מתזמן"),
                       ("serpapi_configured", "מפתח SerpAPI"), ("admin_protected", "לוח בקרה מוגן")]:
        lines.append(f"- {label}: {health.get(key)}")
    if status != 200 or health.get("status") != "ok":
        problems.append(f"/health: HTTP {status}, status={health.get('status')}, error={health.get('database_error')}")
    for key in ("database_ok", "database_persistent_path", "scheduler_enabled", "admin_protected"):
        if health.get(key) is False:
            problems.append(f"/health: {key}=False")

    lines += ["", "## עמודים", "| עמוד | סטטוס | זמן |", "|---|---|---|"]
    for page in PAGES:
        s, t, _ = fetch(base + page)
        lines.append(f"| {page} | {s} | {t:.1f} שנ' |")
        if not isinstance(s, int) or s >= 500:
            problems.append(f"{page}: {s}")
        elif t > SLOW_SECONDS:
            problems.append(f"{page}: איטי ({t:.0f} שנ')")

    token = os.getenv("ARIELLA_OPS_TOKEN")
    lines += ["", "## סיכום תפעולי (/admin/ops-status)"]
    if not token:
        lines.append("- לא נבדק: אין ARIELLA_OPS_TOKEN בסביבה (וצריך את תוכנית 002)")
    else:
        s, _, body = fetch(f"{base}/admin/ops-status?token={token}")
        if s == 200:
            lines.append("```json\n" + json.dumps(json.loads(body), ensure_ascii=False, indent=2) + "\n```")
        else:
            lines.append(f"- לא זמין עדיין (HTTP {s})")

    head = "✅ הכל תקין" if not problems else f"❌ {len(problems)} בעיות"
    lines[0] += f" — {head}"
    if problems:
        lines += ["", "## בעיות", *[f"- {p}" for p in problems]]
    text = "\n".join(lines)
    _write(args.out, text)
    print(text)
    return 1 if problems else 0


def _write(path: str | None, text: str) -> None:
    if path:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
