"""QA for the global Flask error handler added to investigate Shaked's
concurrency-failure report (2026-10-12): a genuinely unhandled exception
anywhere in the app used to produce Flask's default HTML 500 page with no
trace anywhere queryable without Render dashboard/log access. The new
app.errorhandler(Exception) logs it and records it into ai_usage (already
exposed via /admin/ai-usage.csv), making real crash reasons (e.g. a
suspected sqlite3.OperationalError "database is locked" under concurrent
load) visible through infrastructure already in use.

Critical risk this guards against: registering for the bare Exception
class also catches every werkzeug HTTPException (404s, admin 401s, etc.)
unless explicitly excluded - those are normal routing/auth outcomes, not
bugs, and must keep their own status code/body.

Run: python3 tools/qa_global_error_handler.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("ADMIN_TOKEN", "qa-probe-admin-token")

import database
database.init_db()

import app as app_module

# Route registration must happen before the first request - Flask locks
# the app's routing table once it has served anything.
probe_path = "/__qa_force_unhandled_exception_probe"


@app_module.app.route(probe_path)
def _qa_probe_route():
    raise RuntimeError("qa-probe-deliberate-crash")


client = app_module.app.test_client()

# --- 1. A genuine 404 (unmatched route) keeps its normal status/body,
# not the generic 500 diagnostic response ---
r = client.get("/this-route-does-not-exist-qa-probe")
assert r.status_code == 404, r.status_code
body = r.get_json(silent=True)
assert body is None or body.get("status") != "error" or "שגיאה פנימית" not in str(body.get("message") or "")
print("PASS: an ordinary 404 is untouched by the global handler")

# --- 2. The admin 401 (missing/wrong token) keeps its own status/body ---
r2 = client.get("/admin/ai-usage?token=definitely-wrong-token")
assert r2.status_code == 401, r2.status_code
body2 = r2.get_json(silent=True)
assert body2 and body2.get("message") == "Unauthorized", body2
print("PASS: _require_admin's 401 is untouched by the global handler")

# --- 3. A genuine unhandled exception IS caught, logged, and recorded ---
r3 = client.get(probe_path)
assert r3.status_code == 500, r3.status_code
body3 = r3.get_json(silent=True)
assert body3 and body3.get("status") == "error", body3
assert "שגיאה פנימית" in str(body3.get("message") or ""), body3
print("PASS: a genuinely unhandled exception returns the clean 500 diagnostic response")

from ai_usage import usage_rows
rows = usage_rows(days=1, include_test=True)
matching = [r for r in rows if r.get("source") == "unhandled_exception" and "qa-probe-deliberate-crash" in str(r.get("error") or "")]
assert matching, "expected an unhandled_exception row recording the probe's RuntimeError"
print(f"PASS: the exception was recorded into ai_usage (queryable via /admin/ai-usage.csv) - {matching[0]['error']!r}")

print("\nALL GLOBAL ERROR HANDLER TESTS PASSED")
