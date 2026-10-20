"""QA for Shlomo's relay of Shaked's live stage-1 run-1 finding (20.10.2026,
b71506d, 1/5 - report: qa/reports/2026-10-20-stage1-live-run1.md on the
shaked branch, 2063f40), priority fix #1 of the four he named as blocking
stage-1 before the link/confirmation work continues:

פנייה בלשון נקבה ללקוח שרשום כזכר - r90→s1a1 (ליובליאנה) ו-s1a3 (סלוניקי),
שבהם profile.gender=male ו-user_gender=male. המקור: משפטים קבועים
ב-ariella_chat_clean.py שורות 12556/12560 ("תרצי שאעזור גם עם X?") ו-12533/
12332 ("בואי נוודא..."). הם לא תלויים במגדר.

These fixed sentences bypass Tinkerbell's own model call entirely (several
are short-circuit replies returned before any model call that turn), so the
general "address per registration" prompt instruction never had a chance to
apply to them - and a grep found well over a dozen more of the same two
feminine-only forms ("תרצי"/"בואי") scattered across this file's many other
fixed/deterministic reply strings, not just the two Shaked named.

Fixed with one deterministic post-processing safety net (mirrors the
existing _fix_child_gender_wording's own philosophy exactly), wired into
_reply() - "the single exit point for every successful turn" per its own
docstring - so no individual call site (fixed string or Tinkerbell-composed)
can forget it. Deliberately narrow: only a REGISTERED male customer is ever
rewritten. Feminine phrasing is this file's existing default everywhere
else (plenty of other tests assume it) - a female or unknown/unregistered
gender is left completely untouched, so this fixes only the one actual
reported mismatch without changing anything else's behavior.

Run: python3 tools/qa_customer_address_gender_fix.py
"""
import os
import sys
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import app as app_module
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# Direct unit tests of the correction function itself.
# =====================================================================
check("male: 'בואי' -> 'בוא'",
      chat._fix_customer_address_gender_wording("בואי נוודא שגם פרטי הטיסה שלמים.", "male")
      == "בוא נוודא שגם פרטי הטיסה שלמים.")
check("male: 'תרצי' -> 'תרצה'",
      chat._fix_customer_address_gender_wording("תרצי שאעזור גם עם לינה?", "male")
      == "תרצה שאעזור גם עם לינה?")
check("female: left untouched (already correct)",
      chat._fix_customer_address_gender_wording("תרצי שאעזור גם עם לינה?", "female")
      == "תרצי שאעזור גם עם לינה?")
check("unknown/unregistered gender: left completely untouched - this file's "
      "existing default everywhere else, unchanged by this fix",
      chat._fix_customer_address_gender_wording("תרצי שאעזור גם עם לינה?", None)
      == "תרצי שאעזור גם עם לינה?")
check("a plain reply with neither gendered form at all is left completely untouched",
      chat._fix_customer_address_gender_wording("מעולה, קלטתי את כל הפרטים.", "male")
      == "מעולה, קלטתי את כל הפרטים.")
check("does not touch 'תרצה' when it's already masculine-correct (idempotent)",
      chat._fix_customer_address_gender_wording("תרצה שאעזור גם עם לינה?", "male")
      == "תרצה שאעזור גם עם לינה?")
check("never raises on empty/None input",
      chat._fix_customer_address_gender_wording(None, "male") == ""
      and chat._fix_customer_address_gender_wording("", "male") == "")
check("does not false-positive inside an unrelated longer word containing the substring",
      chat._fix_customer_address_gender_wording("התרציה", "male") == "התרציה")
check("a vav-prefixed conjunction form ('ותרצי', no space - standard Hebrew "
      "attachment) is still corrected, not skipped as if it were a "
      "different word",
      chat._fix_customer_address_gender_wording("בואי נוודא, ותרצי שאעזור?", "male")
      == "בוא נוודא, ותרצה שאעזור?")

# =====================================================================
# Shaked's two exact live finding lines.
# =====================================================================
check("Shaked's exact s1a1/s1a3 line 1 ('עוד דבר אחד לפני שסוגרים - בואי "
      "נוודא...') correctly addresses a male-registered customer",
      chat._fix_customer_address_gender_wording(
          "עוד דבר אחד לפני שסוגרים - בואי נוודא שגם פרטי הטיסה שלמים.", "male"
      ) == "עוד דבר אחד לפני שסוגרים - בוא נוודא שגם פרטי הטיסה שלמים.")
check("Shaked's exact s1a1/s1a3 line 2 ('תרצי שאעזור גם עם X?') correctly "
      "addresses a male-registered customer",
      chat._fix_customer_address_gender_wording(
          "עוד דבר אחד לפני שסוגרים - תרצי שאעזור גם עם לינה?", "male"
      ) == "עוד דבר אחד לפני שסוגרים - תרצה שאעזור גם עם לינה?")

# =====================================================================
# End-to-end through the real endpoint: confirms the WIRING itself - that
# _reply() (the file's own single shared exit point for every successful
# turn) really does apply the correction to whatever `reply` text a turn
# ends up producing, for a registered male customer, regardless of which
# code path built that text. The individual fixed strings themselves are
# already covered directly above, against Shaked's own two exact lines.
# =====================================================================
def _make_member(email, gender):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Gender Address", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", gender),
        )
        return cur.lastrowid


member_male = _make_member("qa-gender-address-male@example.com", "male")
with client.session_transaction() as sess:
    sess["member_id"] = member_male


def _quiet_post_claude_feminine_reply(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        # Stands in for ANY turn's final reply text, whichever code path
        # produced it (a Tinkerbell-composed sentence here, or one of this
        # file's own fixed strings elsewhere) - the point is that _reply()
        # must correct it regardless of its origin.
        return "בואי נוודא שגם פרטי הטיסה שלמים, ותרצי שאעזור גם עם לינה?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_quiet_post_claude_feminine_reply):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "שלום",
        "history": [],
        "trip_state": {"user_gender": "male"},
    })
data = r.get_json() or {}
reply = str(data.get("reply") or "")
check("end-to-end: _reply() corrects a feminine-only reply for a "
      "male-registered customer regardless of which code path produced it",
      "בוא נוודא" in reply and "תרצה שאעזור" in reply)
check("end-to-end: the forbidden feminine-only 'בואי'/'תרצי' forms never "
      "leak through to a male-registered customer's final response",
      "בואי" not in reply and "תרצי" not in reply)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL CUSTOMER-ADDRESS-GENDER-FIX TESTS PASSED")
