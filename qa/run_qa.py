"""Ariella offline QA suite — runs without SerpAPI, Anthropic or WhatsApp keys.

Checks:
  1. compile    every .py file compiles
  2. names      pyflakes: undefined names (the class of bug behind QA v9.7.132)
  3. routes     every GET page answers < 500, as a visitor and as a logged-in member
  4. cases      deterministic Hebrew parsers match qa/cases.json

Usage: python qa/run_qa.py [--out qa/reports/latest.md]
Exit code is non-zero when any check fails.
"""
from __future__ import annotations

import argparse
import compileall
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolated, offline runtime: temp DB, no scheduler, no scanner, no external keys.
_TMP = tempfile.mkdtemp(prefix="ariella-qa-")
os.environ.update({"DB_PATH": str(Path(_TMP) / "qa.db"), "SCHEDULER_ENABLED": "false",
                   "SCANNER_ENABLED": "false", "ADMIN_TOKEN": "qa-token"})
for key in ("SERPAPI_API_KEY", "ANTHROPIC_API_KEY", "WHATSAPP_ACCESS_TOKEN"):
    os.environ.pop(key, None)

PLACEHOLDERS = {"int": "1", "string": "abc", "path": "abc", "default": "abc"}


def check_compile() -> list[str]:
    ok = compileall.compile_dir(str(ROOT), quiet=1, maxlevels=0)
    return [] if ok else ["compile: at least one top-level .py file failed to compile"]


def check_names() -> list[str]:
    files = sorted(str(p) for p in ROOT.glob("*.py"))
    out = subprocess.run([sys.executable, "-m", "pyflakes", *files], capture_output=True, text=True).stdout
    return [line.replace(str(ROOT) + "/", "") for line in out.splitlines() if "undefined name" in line]


def _route_urls(app) -> list[str]:
    urls = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint == "static":
            continue
        url = rule.rule
        for arg in rule.arguments:
            conv = type(rule._converters[arg]).__name__.replace("Converter", "").lower()
            value = PLACEHOLDERS.get("int" if "integer" in conv else conv, "abc")
            url = url.replace(f"<{arg}>", value)
            for prefix in ("int:", "string:", "path:", "float:"):
                url = url.replace(f"<{prefix}{arg}>", value)
        urls.append(url)
    return sorted(set(urls))


def _make_member(app) -> int:
    import sqlite3
    from werkzeug.security import generate_password_hash
    with app.test_client() as c:
        c.get("/")  # ensure schema exists
    conn = sqlite3.connect(os.environ["DB_PATH"])
    cur = conn.execute("INSERT INTO members (full_name,email,phone,password_hash,created_at,status) VALUES(?,?,?,?,datetime('now'),'active')",
                       ("QA Tester", "qa@example.com", "0500000000", generate_password_hash("qa-pass")))
    conn.commit()
    return int(cur.lastrowid)


def check_routes() -> tuple[list[str], int]:
    import app as app_module
    app = app_module.app
    app.config["TESTING"] = False  # surface real 500s instead of raising
    logging.disable(logging.CRITICAL)  # 500 tracebacks are summarised in the report
    urls = _route_urls(app)
    member_id = _make_member(app)
    failures = []
    for as_member in (False, True):
        with app.test_client() as c:
            if as_member:
                with c.session_transaction() as s:
                    s["member_id"] = member_id
            for url in urls:
                sep = "&" if "?" in url else "?"
                try:
                    status = c.get(f"{url}{sep}token=qa-token").status_code
                except Exception as exc:  # noqa: BLE001 - any crash is a finding
                    status = f"exception {type(exc).__name__}: {exc}"
                if not isinstance(status, int) or status >= 500:
                    failures.append(f"{'member' if as_member else 'visitor'} GET {url} -> {status}")
    return failures, len(urls)


def check_password_reset() -> list[str]:
    """End-to-end forgot/reset flow (GET-only route checks miss POST paths and missing tables)."""
    import re
    import sqlite3
    from werkzeug.security import check_password_hash
    import app as app_module
    app = app_module.app
    failures = []
    old_debug = app.config.get("DEBUG")
    app.config["DEBUG"] = True  # the reset link is only rendered in DEBUG (no email provider yet)
    try:
        with app.test_client() as c:
            r = c.post("/forgot-password", data={"email": "QA@example.com"})
            if r.status_code != 200:
                return [f"POST /forgot-password (existing member) -> {r.status_code}"]
            m = re.search(r"(/reset-password/[A-Za-z0-9_-]+)", r.get_data(as_text=True))
            if not m:
                return ["POST /forgot-password: no reset link generated for an existing member"]
            url = m.group(1)
            status = c.get(url).status_code
            if status != 200:
                failures.append(f"GET /reset-password with a valid token -> {status}")
            r = c.post(url, data={"password": "qa-new-pass", "confirm_password": "qa-new-pass"})
            if r.status_code != 302:
                failures.append(f"POST reset-password with a valid token -> {r.status_code}, expected redirect")
            conn = sqlite3.connect(os.environ["DB_PATH"])
            pw_hash = conn.execute("SELECT password_hash FROM members WHERE email='qa@example.com'").fetchone()[0]
            if not check_password_hash(pw_hash, "qa-new-pass"):
                failures.append("reset-password: the new password was not saved")
            c.post(url, data={"password": "qa-other-pass", "confirm_password": "qa-other-pass"})
            pw_hash = conn.execute("SELECT password_hash FROM members WHERE email='qa@example.com'").fetchone()[0]
            if not check_password_hash(pw_hash, "qa-new-pass"):
                failures.append("reset-password: a used token changed the password again")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"crashed - {type(exc).__name__}: {exc}")
    finally:
        app.config["DEBUG"] = old_debug
    return failures


def _contains(actual, expected) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _contains(actual[k], v) for k, v in expected.items())
    return actual == expected


def check_cases() -> tuple[list[str], int]:
    import ariella_chat_clean as chat
    data = json.loads((ROOT / "qa" / "cases.json").read_text(encoding="utf-8"))
    failures = []
    for case in data["cases"]:
        try:
            result = getattr(chat, case["fn"])(*case["args"])
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{case['id']}: crashed - {type(exc).__name__}: {exc}")
            continue
        if case.get("expect_truthy") and not result:
            failures.append(f"{case['id']}: expected a match, got {result!r}")
        elif case.get("expect_falsy") and result:
            failures.append(f"{case['id']}: expected no match, got {result!r}")
        elif "expect" in case and not _contains(result, case["expect"]):
            failures.append(f"{case['id']}: expected {case['expect']}, got {result!r}")
    return failures, len(data["cases"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    sections = []
    total_fail = 0

    def add(title, failures, detail=""):
        nonlocal total_fail
        total_fail += len(failures)
        mark = "✅" if not failures else "❌"
        sections.append(f"## {mark} {title}{detail}\n" + "".join(f"- {f}\n" for f in failures))

    add("קומפילציה", check_compile())
    add("שמות לא מוגדרים (קריסות פוטנציאליות)", check_names())
    route_fail, n_routes = check_routes()
    add("עמודי האתר", route_fail, f" — {n_routes} עמודים × מבקר/מחובר")
    add("איפוס סיסמה (תהליך מלא)", check_password_reset())
    case_fail, n_cases = check_cases()
    add("הבנת שיחה (מפענחים דטרמיניסטיים)", case_fail, f" — {n_cases} מקרים")

    head = "✅ הכל עבר" if not total_fail else f"❌ {total_fail} כשלים"
    text = f"# דוח QA לא מקוון — {head}\n\n" + "\n".join(sections)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
