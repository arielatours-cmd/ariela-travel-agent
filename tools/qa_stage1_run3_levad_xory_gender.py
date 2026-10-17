"""QA for Shaked's stage-1, run-3 live findings (17.10.2026, qa/reports/
2026-10-17-stage1-run3.md on the shaked branch, commit e238e2e): 2/5
scenarios passed on main faa4399 (#56+#57+#58).

Bug 1 (V5): _deterministic_traveler_facts's solo-traveler detector matched
the bare word "לבד" anywhere in the message. "נסתדר לבד" (we'll manage on
our own - answering the ROUTE offer, a couple with a daughter), "תבני
לבד" and "אני אסתדר לבד עם זה" (go ahead and build it yourself/I'll
handle it myself) all matched it and silently overwrote travelers.adults
down to 1, even though the real travelers count (a couple, 2 adults) was
already known. Fixed: "לבד" is now only recognized as stating a solo
traveler when it directly follows "אני" or a travel verb ("טס/ה",
"נוסע/ת") - never after an unrelated verb.

Bug 2 (V3, V4): despite TINKERBELL_SYSTEM's existing one-question/never-
"X או Y" instruction (already reinforced once for baggage in PR #58), the
free generation still produced an enumerated/binary question on an
ordinary first ask - the baggage question again ("...רק תיק קטן, או שיש
גם מזוודות?", V4) and, new this round, the trip_planning continuation
offer skipping its plain yes/no entirely in favor of route content ("יש
לך רעיון למסלול..., או שתרצי שאציע?", V3). A free-text instruction alone
isn't reliable - fixed with a deterministic post-generation check,
_enforce_one_option_question, wired into _call_tinkerbell's own reply
pipeline (so every call site gets it for free): when the model's last
question clause contains " או " in exactly one of these two narrow,
well-defined situations (the plain next-domain yes/no offer, or the
baggage question), it is replaced with the already-approved fixed
phrasing used elsewhere (_flight_gap_question's own text for the same two
cases) - any earlier statement sentence in the same reply is kept as-is.

Bug 3 (V3): a customer who wrote "אני טס" (clearly male) got addressed in
feminine mid-conversation ("טסה ללונדון לבד... איזו כבודה תצטרכי?") even
though user_gender was correctly set (the final approval line used the
correct "כתוב מאשר") - rule 188 (profile.gender -> לשון זכר/נקבה) is a
free-text instruction pointing at a key buried in the large state JSON
dump, not reliably followed on its own. Fixed by surfacing it as its own
explicit sentence (_gender_hint_text), the same pattern already used for
_direct_route_hint_text/_multi_gateway_hint.

Run: python3 tools/qa_stage1_run3_levad_xory_gender.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# === Bug 1: "לבד" solo-traveler false positives ===

check("'נסתדר לבד' (V5 live repro) is NOT read as a solo traveler",
      not chat._deterministic_traveler_facts("נסתדר לבד"))
check("'תבני לבד' is NOT read as a solo traveler",
      not chat._deterministic_traveler_facts("תבני לבד"))
check("'אני אסתדר לבד עם זה' is NOT read as a solo traveler",
      not chat._deterministic_traveler_facts("אני אסתדר לבד עם זה"))
check("'אני לבד' is still correctly read as a solo traveler (guard)",
      chat._deterministic_traveler_facts("אני לבד") == {"travelers": {"adults": 1}})
check("'אני טס לבד' is still correctly read as a solo traveler (guard)",
      chat._deterministic_traveler_facts("אני טס לבד") == {"travelers": {"adults": 1}})
check("'אני נוסעת לבד' is still correctly read as a solo traveler (guard)",
      chat._deterministic_traveler_facts("אני נוסעת לבד") == {"travelers": {"adults": 1}})
check("an existing real count ('זוג' = 2 adults) is never downgraded by a "
      "false 'לבד' match in the same conversation turn",
      chat._deterministic_traveler_facts("זוג, נסתדר לבד עם המסלול") == {"travelers": {"adults": 2}})


# === Bug 2: deterministic one-option-question enforcer ===

check("baggage X/Y question gets replaced with the fixed open question, "
      "the earlier statement sentence kept as-is",
      chat._enforce_one_option_question(
          "מעולה, נרשם. כל אחת מכן לוקחת רק תיק קטן, או שיש גם מזוודות?", {}
      ) == "מעולה, נרשם. איזו כבודה תרצו לקחת?")
check("trip_planning X/Y continuation offer gets replaced with the fixed "
      "yes/no, the earlier statement sentence kept as-is",
      chat._enforce_one_option_question(
          "מצוין, הטיסה מוכנה. בואי נדבר על המסלול ביעד - יש לך רעיון למה בא לך "
          "לעשות בלונדון, או שתרצי שאציע לך מסלול מגוון?",
          {"post_flight_offer": ["trip_planning"], "active_session": None},
      ) == "מצוין, הטיסה מוכנה. לתכנן גם מסלול ואטרקציות לחופשה הזו?")
check("the same fix generalizes to a lodging continuation offer",
      chat._enforce_one_option_question(
          "מצוין, המסלול מאושר. רוצים שאני אסדר גם לינה, או שכבר יש לכם משהו?",
          {"post_flight_offer": ["lodging"], "active_session": None},
      ) == "מצוין, המסלול מאושר. לסדר גם לינה לחופשה הזו?")
check("the fixed next-domain offer text is gender-neutral (infinitive verb "
      "form) - never guesses the customer's gender the way bug #3 did",
      not any(w in q for w in ("תרצי", "תרצה") for q in chat._OFFER_DOMAIN_QUESTIONS.values()))
check("a leading statement sentence in the same reply is preserved, only "
      "the offending question clause is replaced",
      chat._enforce_one_option_question(
          "מעולה, נרשם. איזו כבודה תרצו לקחת - טרולי, מזוודה, או תיק קטן?", {}
      ) == "מעולה, נרשם. איזו כבודה תרצו לקחת?")
check("a reply with no '?' at all is returned unchanged",
      chat._enforce_one_option_question("מעולה, נרשם.", {}) == "מעולה, נרשם.")
check("a reply whose last question has no ' או ' at all is left untouched",
      chat._enforce_one_option_question("איזו כבודה תרצו לקחת?", {}) == "איזו כבודה תרצו לקחת?")
check("regression: a legitimate multi-option lodging-type question (not "
      "a binary X-or-Y preference, and not baggage/offer) is left untouched",
      chat._enforce_one_option_question(
          "האם תרצי מלון, דירה או וילה?", {}
      ) == "האם תרצי מלון, דירה או וילה?")
check("the domain-offer fix only fires while the domain is still a plain "
      "offer (active_session empty) - once it's already active, a free "
      "X-or-Y slip there is left alone rather than risk breaking real "
      "mid-domain content",
      chat._enforce_one_option_question(
          "יש לך רעיון למה בא לך לעשות, או שתרצי שאציע לך מסלול מגוון?",
          {"post_flight_offer": ["trip_planning"], "active_session": "trip_planning"},
      ) == "יש לך רעיון למה בא לך לעשות, או שתרצי שאציע לך מסלול מגוון?")
check("two domains offered at once (len != 1, itself a separate violation "
      "of the one-domain-per-offer rule) is not papered over by this fix",
      chat._enforce_one_option_question(
          "רוצים לינה או רכב?", {"post_flight_offer": ["lodging", "car"], "active_session": None},
      ) == "רוצים לינה או רכב?")


# === Bug 3: explicit gender hint ===

check("_gender_hint_text names masculine form explicitly for a known male customer",
      "זכר" in chat._gender_hint_text({"user_gender": "male"})
      and "תצטרך" in chat._gender_hint_text({"user_gender": "male"}))
check("_gender_hint_text names feminine form explicitly for a known female customer",
      "נקבה" in chat._gender_hint_text({"user_gender": "female"})
      and "תצטרכי" in chat._gender_hint_text({"user_gender": "female"}))
check("_gender_hint_text is empty when gender is unknown - no guess injected",
      chat._gender_hint_text({}) == "" and chat._gender_hint_text({"user_gender": None}) == "")


# === End-to-end: _call_tinkerbell actually applies both fixes ===

def _captured_system_dynamic(message, state, fake_reply):
    captured = {}

    def _fake_post_claude(key, model, system_static, system_dynamic, history, msg, max_tokens, include_history=True, source="other"):
        captured["system_dynamic"] = system_dynamic
        return fake_reply

    with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
        reply = chat._call_tinkerbell("test-key", "test-model", [], message, state)
    return reply, captured.get("system_dynamic", "")


e2e_reply, _ = _captured_system_dynamic(
    "אין לי רעיון, מה את ממליצה?",
    {"post_flight_offer": ["trip_planning"], "active_session": None, "destination": {"places": ["לונדון"]}},
    "בואי נדבר על המסלול ביעד - יש לך רעיון למה בא לך לעשות בלונדון, או שתרצי שאציע לך מסלול מגוון?",
)
check("end-to-end via _call_tinkerbell: V3's exact bad reply comes back fixed, "
      "with gender-neutral phrasing",
      e2e_reply == "לתכנן גם מסלול ואטרקציות לחופשה הזו?")

e2e_baggage_reply, _ = _captured_system_dynamic(
    "היי", {"destination": {"places": ["אתונה"]}},
    "כל אחת מכן לוקחת רק תיק קטן, או שיש גם מזוודות?",
)
check("end-to-end via _call_tinkerbell: V4's exact bad baggage reply comes back fixed",
      e2e_baggage_reply == "איזו כבודה תרצו לקחת?")

_, sd_male = _captured_system_dynamic(
    "אני טס ללונדון לבד", {"user_gender": "male", "destination": {"places": ["לונדון"]}}, "תשובה לדוגמה.",
)
check("end-to-end via _call_tinkerbell: a known male customer gets the explicit "
      "masculine-form hint in system_dynamic",
      "זכר" in sd_male and "תצטרך" in sd_male)

_, sd_none = _captured_system_dynamic(
    "היי", {"destination": {"places": ["לונדון"]}}, "תשובה לדוגמה.",
)
check("end-to-end via _call_tinkerbell: no gender hint text leaks in when "
      "user_gender is unknown",
      "מגדר" not in sd_none)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE1-RUN3-LEVAD-XORY-GENDER TESTS PASSED")
