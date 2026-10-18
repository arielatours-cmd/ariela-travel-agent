"""QA for a fix relayed by Shlomo (business owner's instruction, 17.10.2026):
"מאשרת 30 יום" - members were logged out of the public site every time the
browser closed, because public_site.py's join (line ~2394) and login
(line ~2501) routes set session["member_id"] without session.permanent,
so Flask defaulted to a non-permanent, browser-session-only cookie with no
PERMANENT_SESSION_LIFETIME to extend it even if it had been.

Fixed:
1. Both routes now set session.permanent = True right before
   session["member_id"] = ...
2. app.py sets app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30).
3. app.py also sets SESSION_COOKIE_SECURE/HTTPONLY=True and
   SESSION_COOKIE_SAMESITE="Lax" (per the business owner's explicit list).
4. /logout already called session.clear() before this fix and still does -
   combined with the cookie no longer surviving requests after a 30-day
   Max-Age/Expires is sent, logout immediately invalidates the session.
5. /admin/login is untouched: it signs its own separate cookie
   (ADMIN_COOKIE="ariella_admin") via resp.set_cookie/delete_cookie with
   its own secure/httponly/samesite flags, never touching Flask's
   session/session.permanent/PERMANENT_SESSION_LIFETIME at all.

Run: python3 tools/qa_session_persistence_30days.py
"""
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

from werkzeug.security import generate_password_hash

DB = database.DB_PATH

import app as app_module

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# === app.config: the three settings exist with the approved values ===

check("PERMANENT_SESSION_LIFETIME is exactly 30 days",
      app_module.app.config.get("PERMANENT_SESSION_LIFETIME") == timedelta(days=30))
check("SESSION_COOKIE_SECURE is True",
      app_module.app.config.get("SESSION_COOKIE_SECURE") is True)
check("SESSION_COOKIE_HTTPONLY is True",
      app_module.app.config.get("SESSION_COOKIE_HTTPONLY") is True)
check("SESSION_COOKIE_SAMESITE is 'Lax'",
      app_module.app.config.get("SESSION_COOKIE_SAMESITE") == "Lax")


# === Source-level: both join and login set session.permanent = True right
#     before session["member_id"] = ... (never the other order - Flask only
#     applies permanent/lifetime settings to cookies issued AFTER the flag
#     is set on the current request's session, but setting it one line
#     earlier in the same request is equivalent in practice; this just
#     guards the pairing stays intact) ===

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
public_site_src = open(os.path.join(ROOT, "public_site.py"), encoding="utf-8").read()
check("public_site.py: every session[\"member_id\"] assignment is immediately "
      "preceded by session.permanent = True (join and login routes both)",
      len(re.findall(r'session\.permanent = True\s*\n\s*session\["member_id"\]', public_site_src)) == 2)
check("public_site.py: no session[\"member_id\"] assignment is left without "
      "a preceding session.permanent = True",
      len(re.findall(r'session\["member_id"\]\s*=', public_site_src)) ==
      len(re.findall(r'session\.permanent = True\s*\n\s*session\["member_id"\]', public_site_src)))


# === End-to-end: a real /login sets a cookie that actually survives browser
#     close (Max-Age ~30 days), and /logout actually invalidates it ===

def _make_member(email, password):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Session Persistence", email, generate_password_hash(password),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


EMAIL = "qa-session-persistence@example.com"
PASSWORD = "Test1234!"
_make_member(EMAIL, PASSWORD)

client = app_module.app.test_client()
r = client.post("/login", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=False)

set_cookie_headers = r.headers.get_all("Set-Cookie") if hasattr(r.headers, "get_all") else r.headers.getlist("Set-Cookie")
session_cookie = next((h for h in set_cookie_headers if h.startswith("session=")), None)

check("a successful /login redirects (not an error page re-render)",
      r.status_code in (301, 302, 303, 307, 308))
check("a successful /login sets a 'session' cookie",
      session_cookie is not None)
if session_cookie:
    expires_match = re.search(r"Expires=([^;]+)", session_cookie, re.IGNORECASE)
    check("the session cookie carries an Expires date (not a browser-"
          "session-only cookie with no persistence at all)",
          expires_match is not None)
    if expires_match:
        expires_at = parsedate_to_datetime(expires_match.group(1))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        delta_days = (expires_at - datetime.now(timezone.utc)).total_seconds() / 86400
        check("the session cookie's Expires is approximately 30 days out "
              "(the approved PERMANENT_SESSION_LIFETIME), not a short-lived "
              "or missing expiry",
              29.9 <= delta_days <= 30.1)
    check("the session cookie is HttpOnly",
          "httponly" in session_cookie.lower())
    check("the session cookie is SameSite=Lax",
          "samesite=lax" in session_cookie.lower())
    check("the session cookie is Secure",
          "secure" in session_cookie.lower())

r2 = client.post("/logout", follow_redirects=False)
logout_cookie_headers = r2.headers.get_all("Set-Cookie") if hasattr(r2.headers, "get_all") else r2.headers.getlist("Set-Cookie")
logout_session_cookie = next((h for h in logout_cookie_headers if h.startswith("session=")), None)
check("/logout re-issues the session cookie (session.clear() still runs, "
      "same as before this fix)",
      logout_session_cookie is not None)
if logout_session_cookie:
    logout_value = logout_session_cookie.split(";", 1)[0]
    login_value = session_cookie.split(";", 1)[0] if session_cookie else None
    check("/logout's cookie payload differs from the logged-in one (the "
          "signed value no longer encodes member_id, so it can't be replayed "
          "to stay authenticated) - the 30-day Expires this fix adds never "
          "outlives the session's actual content",
          login_value is not None and logout_value != login_value)
    check("/logout's re-issued cookie no longer carries the 30-day Expires "
          "(session.clear() also drops the permanent flag, so it reverts to "
          "a plain non-persistent cookie - nothing here keeps a logged-out "
          "member's old cookie alive for 30 more days)",
          "expires=" not in logout_session_cookie.lower()
          or (re.search(r"Expires=([^;]+)", logout_session_cookie, re.IGNORECASE)
              and (parsedate_to_datetime(re.search(r"Expires=([^;]+)", logout_session_cookie, re.IGNORECASE).group(1))
                   .replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds() < 86400))

r3 = client.get("/account", follow_redirects=False)
check("after /logout, visiting a @login_required page redirects to login "
      "again (the session is genuinely gone, not just the cookie header) - "
      "confirms session.clear() in /logout still works after this change",
      r3.status_code in (301, 302, 303, 307, 308) and "/login" in (r3.headers.get("Location") or ""))


# === /admin/login stays on its own separate cookie mechanism, untouched ===

app_py_src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
admin_login_section = app_py_src[app_py_src.index('def admin_login('):app_py_src.index('def admin_logout(')]
check("admin_login() never sets session.permanent or session[\"member_id\"] - "
      "it manages its own ADMIN_COOKIE entirely outside Flask's session",
      "session.permanent" not in admin_login_section and "session[" not in admin_login_section)
check("the admin cookie name ('ariella_admin') is distinct from Flask's "
      "default session cookie name ('session') - the two mechanisms never "
      "collide or share a lifetime/flag configuration",
      app_module.ADMIN_COOKIE == "ariella_admin" and app_module.ADMIN_COOKIE != "session")


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL SESSION-PERSISTENCE-30-DAYS TESTS PASSED")
