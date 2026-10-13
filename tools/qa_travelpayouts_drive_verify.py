"""QA for task 012a - Travelpayouts Drive verification script (home page only).

Per product/dev-tasks/012a-travelpayouts-drive-verify.md (ofek branch),
approved by the business owner directly: a verification script, gated by
TRAVELPAYOUTS_DRIVE_SRC, is injected into templates/home.html's <head> only
when the env var is set, and must never appear on any other page
(about/account/admin, payment, chat). The var is removed again from Render
right after Travelpayouts confirms the connection - this only has to be
correct while it's temporarily present.

Renders real pages through the Flask test client, with and without the env
var set.

Run: python3 tools/qa_travelpayouts_drive_verify.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- Case 1: var unset -> home page unchanged, no script anywhere ---
os.environ.pop("TRAVELPAYOUTS_DRIVE_SRC", None)

import app as app_module

client = app_module.app.test_client()
r = client.get("/?lang=he")
check("home page renders (no env var)", r.status_code == 200)
check("no emrld.ltd / travelpayouts script without the env var", b"emrld.ltd" not in r.data and b"data-cmp-ab" not in r.data)

r_about = client.get("/about?lang=he")
check("about page renders", r_about.status_code == 200)
check("no script on /about even if it were somehow set elsewhere", b"data-cmp-ab" not in r_about.data)

# --- Case 2: var set -> script appears on home only, exact src, nowhere else ---
TEST_SRC = "https://emrld.ltd/NTg0ODgw.js?t=584880"
os.environ["TRAVELPAYOUTS_DRIVE_SRC"] = TEST_SRC

r2 = client.get("/?lang=he")
check("home page renders (env var set)", r2.status_code == 200)
check("script tag present on home page", b"data-cmp-ab=\"2\"" in r2.data)
check("exact configured src is used, not a guessed/hardcoded one", TEST_SRC.encode() in r2.data)

r3_about = client.get("/about?lang=he")
check("about page still renders", r3_about.status_code == 200)
check("script does NOT leak onto /about", b"data-cmp-ab" not in r3_about.data and b"emrld.ltd" not in r3_about.data)

r3_account = client.get("/account", follow_redirects=False)
check("account route responds (redirect to login is fine, no crash)", r3_account.status_code in (200, 302, 401, 403))
check("script does NOT leak onto /account", b"data-cmp-ab" not in r3_account.data and b"emrld.ltd" not in r3_account.data)

r3_admin = client.get("/admin", follow_redirects=False)
check("admin route responds (redirect/login-gate is fine, no crash)", r3_admin.status_code in (200, 302, 401, 403))
check("script does NOT leak onto /admin", b"data-cmp-ab" not in r3_admin.data and b"emrld.ltd" not in r3_admin.data)

os.environ.pop("TRAVELPAYOUTS_DRIVE_SRC", None)

# --- Case 3: blank-but-set env var still counts as "not configured" ---
os.environ["TRAVELPAYOUTS_DRIVE_SRC"] = "   "
r4 = client.get("/?lang=he")
check("whitespace-only env var treated as unset -> no script", b"data-cmp-ab" not in r4.data)
os.environ.pop("TRAVELPAYOUTS_DRIVE_SRC", None)

# --- Case 4: cookie policy and privacy policy mention Travelpayouts, both languages ---
r5_he = client.get("/cookies?lang=he")
check("cookies page (he) renders", r5_he.status_code == 200)
check("cookies page (he) mentions Travelpayouts", "Travelpayouts".encode() in r5_he.data)

r5_en = client.get("/cookies?lang=en")
check("cookies page (en) renders", r5_en.status_code == 200)
check("cookies page (en) mentions Travelpayouts", "Travelpayouts".encode() in r5_en.data)

r6_he = client.get("/privacy?lang=he")
check("privacy page (he) renders", r6_he.status_code == 200)
check("privacy page (he) lists Travelpayouts under service providers", "Travelpayouts".encode() in r6_he.data)

r6_en = client.get("/privacy?lang=en")
check("privacy page (en) renders", r6_en.status_code == 200)
check("privacy page (en) lists Travelpayouts under service providers", "Travelpayouts".encode() in r6_en.data)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL TRAVELPAYOUTS DRIVE-VERIFY TESTS PASSED")
