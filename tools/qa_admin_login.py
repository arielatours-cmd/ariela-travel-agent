"""QA for the admin login (Bezalel's task, 16.10): /admin/login sets a signed
admin cookie so the token no longer has to be pasted into ?token= URLs
(which end up in Render's request logs).

Checks: correct / wrong token, the login persists across requests, logout
clears it, the cookie flags (HttpOnly, Secure on Render, SameSite=Strict),
and regression - the X-Admin-Token header and ?token= keep working exactly
as before, and API callers still get the 401 JSON.

Offline, temp DB. Run: python3 tools/qa_admin_login.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="ariella-qa-admin-login-")
TOKEN = "qa-admin-token-123"
os.environ.update({"DB_PATH": os.path.join(_TMP, "qa.db"), "SCHEDULER_ENABLED": "false",
                   "SCANNER_ENABLED": "false", "ADMIN_TOKEN": TOKEN, "RENDER": "true"})
for key in ("SERPAPI_API_KEY", "ANTHROPIC_API_KEY", "WHATSAPP_ACCESS_TOKEN"):
    os.environ.pop(key, None)

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import app as app_module  # noqa: E402

app = app_module.app
HTML = {"Accept": "text/html,application/xhtml+xml"}


def set_cookie_header(resp):
    return next((v for k, v in resp.headers.items() if k.lower() == "set-cookie" and v.startswith("ariella_admin=")), "")


# --- Not logged in ---------------------------------------------------------------
c = app.test_client()
r = c.get("/admin/feedback")
check("no auth, API-style request -> 401 JSON as before", r.status_code == 401 and (r.get_json() or {}).get("message") == "Unauthorized")
r = c.get("/admin/feedback", headers=HTML)
check("no auth, browser -> redirect to /admin/login?next=...",
      r.status_code == 302 and r.headers["Location"].startswith("/admin/login?next=/admin/feedback"))
r = c.get("/admin/login")
check("login form renders", r.status_code == 200 and 'name="token"' in r.get_data(as_text=True))
check("login form: password field, POST, no-store", 'type="password"' in r.get_data(as_text=True)
      and 'method="post"' in r.get_data(as_text=True) and r.headers.get("Cache-Control") == "no-store")
check("POST /scan without auth -> 401 (unchanged)", c.post("/scan").status_code == 401)

# --- Wrong token -------------------------------------------------------------------
r = c.post("/admin/login", data={"token": "wrong", "next": "/admin/feedback"})
check("wrong token -> 401 page, no cookie", r.status_code == 401 and not set_cookie_header(r))
check("wrong token -> error shown", "קוד שגוי" in r.get_data(as_text=True))
check("wrong token -> still not authorized", c.get("/admin/feedback").status_code == 401)
r = c.post("/admin/login", data={"token": "", "next": "/admin"})
check("empty token -> 401", r.status_code == 401)

# --- Correct token -----------------------------------------------------------------
r = c.post("/admin/login", data={"token": TOKEN, "next": "/admin/feedback"})
cookie = set_cookie_header(r)
check("correct token -> redirect to next", r.status_code == 302 and r.headers["Location"].endswith("/admin/feedback"))
check("cookie is HttpOnly", "HttpOnly" in cookie)
check("cookie is Secure (on Render)", "Secure" in cookie)
check("cookie is SameSite=Strict", "SameSite=Strict" in cookie)
check("cookie never contains the token itself", TOKEN not in cookie)
check("logged in: /admin/feedback works with no token", c.get("/admin/feedback").status_code == 200)
check("logged in: persists across requests (/admin/analytics, /admin)",
      c.get("/admin/analytics").status_code == 200 and c.get("/admin").status_code == 200)
check("logged in: dashboard API outside /admin works too (/scan-history)", c.get("/scan-history").status_code == 200)
r = c.get("/admin/login")
check("logged in: /admin/login goes straight to the dashboard", r.status_code == 302)

# --- Open redirect guard -------------------------------------------------------------
for bad in ("https://evil.example", "//evil.example", "/admin//evil.example", "/account"):
    c2 = app.test_client()
    r = c2.post("/admin/login", data={"token": TOKEN, "next": bad})
    check(f"next={bad!r} -> stays on /admin", r.status_code == 302 and r.headers["Location"].endswith("/admin"))

# --- Tampered / foreign cookie -------------------------------------------------------
c3 = app.test_client()
c3.set_cookie("ariella_admin", "garbage")
check("garbage cookie -> not authorized", c3.get("/admin/feedback").status_code == 401)
from itsdangerous import URLSafeTimedSerializer  # noqa: E402
forged = URLSafeTimedSerializer("not-the-secret", salt="ariella-admin-session").dumps({"is_admin": True})
c3.set_cookie("ariella_admin", forged)
check("cookie signed with another key -> not authorized", c3.get("/admin/feedback").status_code == 401)
valid_no_tag = URLSafeTimedSerializer(app.secret_key, salt="ariella-admin-session").dumps({"is_admin": True, "token_tag": "x"})
c3.set_cookie("ariella_admin", valid_no_tag)
check("cookie from an old ADMIN_TOKEN (wrong tag) -> not authorized", c3.get("/admin/feedback").status_code == 401)
c4 = app.test_client()
with c4.session_transaction() as s:
    s["is_admin"] = True
check("site session flag alone (is_admin in Flask session) does not grant admin",
      c4.get("/admin/feedback").status_code == 401)

# --- Logout ----------------------------------------------------------------------------
r = c.post("/admin/logout")
check("logout -> redirect to login", r.status_code == 302 and r.headers["Location"].endswith("/admin/login"))
check("logout clears the cookie", "ariella_admin=;" in set_cookie_header(r) or "Max-Age=0" in set_cookie_header(r))
check("after logout -> not authorized", c.get("/admin/feedback").status_code == 401)
c.post("/admin/login", data={"token": TOKEN})
r = c.get("/admin/logout")
check("GET /admin/logout works too", r.status_code == 302 and c.get("/admin/feedback").status_code == 401)

# --- Regression: header and ?token= unchanged -------------------------------------------
fresh = app.test_client()
check("X-Admin-Token header still works", fresh.get("/admin/feedback", headers={"X-Admin-Token": TOKEN}).status_code == 200)
check("?token= still works", fresh.get(f"/admin/feedback?token={TOKEN}").status_code == 200)
check("wrong header -> 401", fresh.get("/admin/feedback", headers={"X-Admin-Token": "nope"}).status_code == 401)
check("wrong ?token= -> 401", fresh.get("/admin/feedback?token=nope").status_code == 401)
check("?token= on an API route still works (/scan-history)", fresh.get(f"/scan-history?token={TOKEN}").status_code == 200)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
