"""QA for Shaked's admin-login hardening (16.10, after PR #34):

  a. /admin/login refuses to log in while FLASK_SECRET_KEY is the public
     default "change-this-before-production" (anyone reading the code could
     forge the signed cookie) - and a cookie is never accepted then either
  b. rate limit: after 5 wrong codes from one IP within 15 minutes the form
     answers 429 (even with the right code); other IPs are unaffected; a
     total cap of 50 wrong codes covers IP rotation; the header and ?token=
     keep working throughout; a successful login clears the IP's failures

Offline, temp DB. Run: python3 tools/qa_admin_login_hardening.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="ariella-qa-admin-hardening-")
TOKEN = "qa-admin-token-456"
REAL_KEY = "qa-secret-key-not-the-default"
os.environ.update({"DB_PATH": os.path.join(_TMP, "qa.db"), "SCHEDULER_ENABLED": "false",
                   "SCANNER_ENABLED": "false", "ADMIN_TOKEN": TOKEN, "RENDER": "true",
                   "FLASK_SECRET_KEY": REAL_KEY})
for key in ("SERPAPI_API_KEY", "ANTHROPIC_API_KEY", "WHATSAPP_ACCESS_TOKEN"):
    os.environ.pop(key, None)

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import app as app_module  # noqa: E402

app = app_module.app


def has_cookie(resp):
    return any(k.lower() == "set-cookie" and v.startswith("ariella_admin=") for k, v in resp.headers.items())


def reset_limits():
    with app_module._admin_login_lock:
        app_module._admin_login_fails.clear()


def login(client, token, ip="203.0.113.1"):
    return client.post("/admin/login", data={"token": token, "next": "/admin/feedback"},
                       headers={"X-Forwarded-For": ip})


# --- a. default secret key -> login refused --------------------------------------------
app.secret_key = "change-this-before-production"
c = app.test_client()
r = login(c, TOKEN)
check("a: default FLASK_SECRET_KEY -> correct code refused (503)", r.status_code == 503 and not has_cookie(r))
check("a: clear message naming FLASK_SECRET_KEY", "FLASK_SECRET_KEY" in r.get_data(as_text=True))
check("a: refusal does not count as a failed attempt", not app_module._admin_login_fails)
# a cookie signed with the default key (forgeable) is never accepted
from itsdangerous import URLSafeTimedSerializer  # noqa: E402
import hmac  # noqa: E402
tag = hmac.new(TOKEN.encode(), b"admin-session", "sha256").hexdigest()
forged = URLSafeTimedSerializer("change-this-before-production", salt="ariella-admin-session").dumps({"is_admin": True, "token_tag": tag})
c.set_cookie("ariella_admin", forged)
check("a: cookie signed with the public default key -> not authorized", c.get("/admin/feedback").status_code == 401)
check("a: header still works with the default key", app.test_client().get("/admin/feedback", headers={"X-Admin-Token": TOKEN}).status_code == 200)
app.secret_key = ""
check("a: empty secret key is refused too", login(app.test_client(), TOKEN).status_code == 503)

app.secret_key = REAL_KEY
reset_limits()
r = login(app.test_client(), TOKEN)
check("a: real secret key -> login works", r.status_code == 302 and has_cookie(r))

# --- b. rate limit -------------------------------------------------------------------------
reset_limits()
attacker = app.test_client()
codes = [login(attacker, f"wrong-{i}", ip="198.51.100.7").status_code for i in range(5)]
check("b: first 5 wrong codes -> 401 each", codes == [401] * 5)
r = login(attacker, "wrong-6", ip="198.51.100.7")
check("b: 6th attempt from the same IP -> 429", r.status_code == 429)
check("b: 429 has Retry-After and a clear message",
      r.headers.get("Retry-After") == str(15 * 60) and "יותר מדי ניסיונות" in r.get_data(as_text=True))
r = login(attacker, TOKEN, ip="198.51.100.7")
check("b: blocked IP -> even the right code is refused at the form, no cookie", r.status_code == 429 and not has_cookie(r))
r = login(app.test_client(), TOKEN, ip="198.51.100.99")
check("b: another IP is not blocked", r.status_code == 302 and has_cookie(r))
check("b: ?token= still works during a block", app.test_client().get(f"/admin/feedback?token={TOKEN}").status_code == 200)
check("b: X-Admin-Token header still works during a block",
      app.test_client().get("/admin/feedback", headers={"X-Admin-Token": TOKEN}).status_code == 200)

# window expiry: failures older than 15 minutes no longer count
with app_module._admin_login_lock:
    app_module._admin_login_fails["198.51.100.7"] = [t - 16 * 60 for t in app_module._admin_login_fails["198.51.100.7"]]
r = login(app.test_client(), TOKEN, ip="198.51.100.7")
check("b: after the 15-minute window the IP can log in again", r.status_code == 302 and has_cookie(r))

# a successful login clears that IP's failures
reset_limits()
for i in range(4):
    login(app.test_client(), "nope", ip="192.0.2.5")
login(app.test_client(), TOKEN, ip="192.0.2.5")
check("b: success clears the IP's failures", "192.0.2.5" not in app_module._admin_login_fails)

# X-Forwarded-For: the LAST entry (appended by Render's proxy) is the client
reset_limits()
for i in range(5):
    login(app.test_client(), "nope", ip=f"10.0.0.{i}, 198.51.100.50")
r = login(app.test_client(), "nope", ip="10.9.9.9, 198.51.100.50")
check("b: rotating a forged first X-Forwarded-For entry does not escape the block", r.status_code == 429)

# total cap across many IPs
reset_limits()
for i in range(50):
    login(app.test_client(), "nope", ip=f"203.0.113.{i}")
r = login(app.test_client(), "nope", ip="203.0.113.200")
check("b: 50 wrong codes in total (IP rotation) -> everyone gets 429 for the window", r.status_code == 429)
reset_limits()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
