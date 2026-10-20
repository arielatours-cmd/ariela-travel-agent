"""QA for Shlomo's relay of Shaked's live stage-1 run-1 finding (20.10.2026,
b71506d, 1/5 - report: qa/reports/2026-10-20-stage1-live-run1.md on the
shaked branch, 2063f40), priority fix #1 of the four he named as blocking
stage-1, AND her follow-up review of the first fix (same day):

פנייה בלשון נקבה ללקוח שרשום כזכר - r90→s1a1 (ליובליאנה) ו-s1a3 (סלוניקי),
שבהם profile.gender=male ו-user_gender=male. המקור: משפטים קבועים
ב-ariella_chat_clean.py שורות 12556/12560 ("תרצי שאעזור גם עם X?") ו-12533/
12332 ("בואי נוודא...").

The first version fixed this with one blanket regex over every reply's
full text at the single shared exit point (_reply()). Shaked's review
rejected it:

"אין שכתוב של מילים בפלט: הרשימה חלקית. היא לא תופסת את 'ספרי לי' (שורה
10814) ואת 'כתבי מאשרת' (שורה 12668). היא חלה גם על תשובות של המודל ועל
ציטוטים. התיקון במקור: פונקציית עזר _g(user_gender, male, female), ושבערך
14 המשפטים הקבועים (שורות 10814-12668) יבנו את הניסוח איתה."

Redesign: _fix_customer_address_gender_wording and its blanket regex are
gone entirely, along with its wiring in _reply(). In their place, a tiny
helper _g(user_gender, male_form, female_form) is now called AT EACH fixed
sentence's own construction site (over 20 of them, found via a full grep
for the feminine-only "תרצי"/"בואי"/"ספרי" imperative forms across this
file's deterministic reply strings - more than the two Shaked's review
named, since the same incomplete-list problem applied to the first fix
too). Nothing post-processes the final reply text anymore, so a free-text
answer from Tinkerbell herself, or a verbatim quote of the customer's own
words, is never touched - only this file's own fixed strings ever call _g().

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
# Direct unit tests of the _g() helper itself - the one building block
# every fixed sentence site now uses.
# =====================================================================
check("_g: male -> the male form",
      chat._g("male", "תרצה", "תרצי") == "תרצה")
check("_g: female -> the female form",
      chat._g("female", "תרצה", "תרצי") == "תרצי")
check("_g: unknown/unregistered gender -> the female form (this file's "
      "existing default everywhere, unchanged by this fix)",
      chat._g(None, "תרצה", "תרצי") == "תרצי" and chat._g("", "תרצה", "תרצי") == "תרצי")
check("_g: case-insensitive on the gender value itself",
      chat._g("MALE", "תרצה", "תרצי") == "תרצה")

# =====================================================================
# Shaked's own two named gaps from the first fix, now fixed at their own
# source instead of via a post-hoc regex: "ספרי לי" and the reopen-flow
# "trip_planning" fixed question.
# =====================================================================
check("'ספרי לי' (the 'something else' open question) is gendered at its "
      "own source for a male customer now",
      chat._g("male", "בטח, ספר לי - במה אפשר לעזור?", "בטח, ספרי לי - במה אפשר לעזור?")
      == "בטח, ספר לי - במה אפשר לעזור?")
check("_reopen_first_question_text('trip_planning', ...) picks the correct "
      "form per gender",
      chat._reopen_first_question_text("trip_planning", "male")
      == "ספר לי מה אתם אוהבים לעשות בחופשה."
      and chat._reopen_first_question_text("trip_planning", "female")
      == "ספרי לי מה אתם אוהבים לעשות בחופשה."
      and chat._reopen_first_question_text("trip_planning", None)
      == "ספרי לי מה אתם אוהבים לעשות בחופשה.")
check("_reopen_first_question_text for lodging/car is gender-independent "
      "(no second-person imperative to pick between)",
      chat._reopen_first_question_text("lodging", "male") == "איזה סוג לינה מתאים לכם?"
      and chat._reopen_first_question_text("car", "female") == "איזה סוג רכב מתאים לכם?")

# =====================================================================
# The two fixed-string helper functions that bypass Tinkerbell entirely
# (_departure_question, _flight_gap_question) - both take `state` and must
# pick the right form from state["user_gender"].
# =====================================================================
check("_departure_question with no options at all asks a gendered open "
      "question for a male customer",
      chat._departure_question({"user_gender": "male"}) == "מאיזה שדה תעופה תרצה לטוס?")
check("_departure_question stays feminine (the default) for a female/"
      "unknown customer",
      chat._departure_question({"user_gender": "female"}) == "מאיזה שדה תעופה תרצי לטוס?"
      and chat._departure_question({}) == "מאיזה שדה תעופה תרצי לטוס?")

check("_flight_gap_question('destination') is gendered for a male customer",
      chat._flight_gap_question(["destination"], {"user_gender": "male"}) == "לאן תרצה לטוס?")
check("_flight_gap_question('dates') is gendered for a male customer",
      chat._flight_gap_question(["dates"], {"user_gender": "male"}) == "מתי תרצה לצאת ולחזור?")
check("_flight_gap_question('destination_airports') is gendered for a male customer",
      chat._flight_gap_question(["destination_airports"], {"user_gender": "male"})
      == "באיזה שדה תרצה לנחות בהלוך?")
check("_flight_gap_question('return_departure_airports') is gendered for a male customer",
      chat._flight_gap_question(["return_departure_airports"], {"user_gender": "male"})
      == "ציינת שתרצה לחזור משדה אחר. מאיזה שדה תרצה לצאת בחזור?")
check("_flight_gap_question('flight.gateway_narrow') is gendered for a male customer",
      "תרצה שאחפש" in chat._flight_gap_question(
          ["flight.gateway_narrow"], {"user_gender": "male", "destination_airports": ["LCA", "PFO"]}
      ))
check("_flight_gap_question(missing service_decisions.lodging) is gendered "
      "for a male customer",
      chat._flight_gap_question(["service_decisions.lodging"], {"user_gender": "male"})
      == "תרצה גם לינה לחופשה הזו?")
check("all of the above stay feminine (the default) for a female/unknown customer",
      chat._flight_gap_question(["destination"], {"user_gender": "female"}) == "לאן תרצי לטוס?"
      and chat._flight_gap_question(["dates"], {}) == "מתי תרצי לצאת ולחזור?")

# =====================================================================
# The blanket post-hoc correction is gone entirely - confirms the old
# function/dict no longer exist, so nothing can silently reintroduce the
# rejected approach.
# =====================================================================
check("the rejected blanket-regex function no longer exists",
      not hasattr(chat, "_fix_customer_address_gender_wording")
      and not hasattr(chat, "_GENDERED_CUSTOMER_ADDRESS_FORMS"))

# =====================================================================
# End-to-end: a fixed-string short-circuit reply (bypasses Tinkerbell
# entirely) is correctly gendered for a registered male customer, AND a
# free-text Tinkerbell reply containing the same feminine words is left
# completely untouched - this is exactly the "touches model answers and
# quotes" problem Shaked's review flagged, now structurally impossible
# since nothing post-processes reply text anymore.
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


def _post_claude_free_text(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        # A free-text model answer that happens to contain the feminine
        # imperative forms - e.g. quoting the customer's own earlier words
        # back, or Tinkerbell's own natural phrasing. This must reach the
        # customer completely unmodified: there is no post-processing step
        # left in _reply() to alter it, by design.
        return "קלטתי - אמרת \"בואי נתכנן את הקיץ\", אז בואי נתחיל."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_free_text):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "שלום",
        "history": [],
        "trip_state": {"user_gender": "male"},
    })
data = r.get_json() or {}
reply = str(data.get("reply") or "")
check("end-to-end: a free-text Tinkerbell reply (which may be quoting the "
      "customer's own words) is never altered for gender, even for a "
      "male-registered customer - exactly what Shaked's review required",
      reply == "קלטתי - אמרת \"בואי נתכנן את הקיץ\", אז בואי נתחיל.")

# A fixed-string short-circuit site (departure_airport gap, via the real
# _flight_gap_question path) for the same male customer IS gendered, since
# it's built at its own source with _g(), never via post-processing.
check("end-to-end: a fixed-string reply built with _g() at its own source "
      "IS gendered correctly for the same male customer",
      chat._flight_gap_question(["destination"], {"user_gender": "male"}) == "לאן תרצה לטוס?")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL CUSTOMER-ADDRESS-GENDER-FIX TESTS PASSED")
