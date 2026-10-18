"""QA for Shaked's stage-3 run-4 report (qa/reports/2026-10-18-stage3-run4.md,
branch shaked @eba2489, main @320d0e3, relayed by Shlomo, 18.10.2026). 0/5
scenarios passed live. The urgent past-date bug (s3y2) was fixed and shipped
separately (PR #86, task/stage3-run4-fix1-date-rollover, per Shlomo's
explicit instruction to send it first on its own). This file covers the
remaining findings fixable without live production log data; the ones that
genuinely need it (whether the real model's restart classification/evidence
behaves as expected live, and the exact cause of the Tuscany guided-redirect
miss) now have diagnostic logging added instead of another guess, and the
ones not yet addressed (remaining X/Y and bundled-question phrasing in V1/
V3/V5, "זה כבר רשום אצלי" said about an unstated fact) are left open.

1. #85's reset-confirmation gate didn't fire live for genuine restart
   language ("בא לי בכלל לתכנן משהו אחר לגמרי", "עזבי את בודפשט, אני רוצה
   לחשוב על חופשה אחרת") even though a local test with a mocked model fired
   it correctly. Two actions, per Shlomo's explicit instruction:
   (a) broadened EXTRACTOR_SYSTEM's restart_request rule - the examples
   were all explicit "start over" phrasing; these two real messages are
   just as clear in MEANING but far more indirect, and a model given only
   explicit examples can under-classify indirect ones.
   (b) added diagnostic logging (restart_request/restart_evidence/whether
   evidence verification passed) for every turn with real vacation
   progress, WITHOUT the customer's own message text (explicitly no
   personal details, per Shlomo), so the next live finding comes with the
   data needed to diagnose it instead of another guess.

2. Tuscany: "לא קשורה לתקציב ללילה" fired again on "שתיים לפחות" answering
   a bathroom-count question - the same bug class #83's _guided_redirect_
   field fix targeted (Madrid/Milano), but it didn't catch this one.
   Without live logs the exact point of failure (never called? current_
   question already drifted past both fields? the model said no match?)
   can't be confirmed - added diagnostic logging (current_question, the
   candidate fields actually offered, and the redirect outcome; then, if a
   field matched, the re-extraction's own status/confidence/whether it
   wrote anything), again without the customer's message text.

3. General finding #6 (baggage per traveler-type): "וטרولי לכל ילד" ("a
   bag per CHILD") saved/summarized as per_person ("per every traveler,
   adults included") - a real schema gap, not a parsing bug: the baggage
   unit enum never had a "per_child" option at all, anywhere (the guided-
   extraction field's own primary schema, its regex fail-safe, or the
   label function) - per_person was the closest the model had, and it
   isn't the same fact. Added "per_child" as its own explicit unit value
   in all three places.

4. General finding #4 (Kyoto): trip_type stayed None for the whole
   conversation, looping "איזה סוג נסיעה זו?". Root cause traced to #85's
   own X/Y/Z opening-question fix: the opening question no longer NAMES
   the three categories ("חופשה רגילה, נסיעת עסקים, או חופשת סקי?"), so the
   customer's natural answer almost never echoes one of those category
   WORDS literally anymore - but EXTRACTOR_SYSTEM's trip_type rule still
   required the customer to have stated it "במפורש" (explicitly), which in
   practice meant one of those literal words. Loosened the rule to match
   TINKERBELL_SYSTEM's own standing instruction to classify trip_type from
   the customer's free-form description of the trip's purpose (leisure/
   work/skiing) - still forbidding any guess from destination/dates/
   travelers alone, just no longer requiring a magic word.

Run: python3 tools/qa_stage3_run4_root_causes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# 1. Restart-signal instruction broadened + diagnostic logging, without
#    the customer's own message text.
# =====================================================================
check("item 1: EXTRACTOR_SYSTEM's restart_request rule now covers indirect phrasing "
      "explicitly (not just explicit 'start over' wording)",
      "בא לי בכלל לתכנן משהו אחר לגמרי" in chat.EXTRACTOR_SYSTEM
      and "עזבי את" in chat.EXTRACTOR_SYSTEM)
check("item 1: the rule still requires understanding by MEANING, not matching specific sentences",
      "לפי המשמעות השלמה של המשפט" in chat.EXTRACTOR_SYSTEM)
check("item 1: the diagnostic log line exists and never includes the customer's own message text",
      'logging.info(\n                "restart_signal: request=%s evidence=%r evidence_verified=%s",'
      in open(chat.__file__, encoding="utf-8").read())


# =====================================================================
# 2. Guided-redirect diagnostic logging (Tuscany bathroom-count miss).
# =====================================================================
_source = open(chat.__file__, encoding="utf-8").read()
check("item 2: a diagnostic log line exists for the redirect outcome (current_question, "
      "candidates offered, redirected_to), without the customer's own message text",
      'logging.info(\n            "guided_redirect: current_question=%s candidates=%s redirected_to=%s",'
      in _source)
check("item 2: a second diagnostic log line exists for the redirected re-extraction's own "
      "status/confidence/whether it actually wrote anything",
      'logging.info(\n                "guided_redirect: redirected_to=%s extract_status=%s '
      'extract_confidence=%s fragment_written=%s",' in _source)


# =====================================================================
# 3. Baggage per_child unit - all three places.
# =====================================================================
r_child = chat._deterministic_baggage_facts("מזוודה אחת לכל ילד", traveler_count=4)
check("item 3: regex fail-safe recognizes 'per child' as its own unit, not per_person",
      r_child["flight"]["baggage_detail"]["checked_bag"]["unit"] == "per_child")
check("item 3: the label function distinguishes per_child from per_person",
      chat._checked_bag_label({"count": 1, "unit": "per_child"}) == "מזוודה אחת לכל ילד"
      and chat._checked_bag_label({"count": 3, "unit": "per_child"}) == "3 מזוודות לכל ילד")
fragment, desc = chat._guided_field_update_and_confirm("baggage", {
    "status": "answered", "no_baggage": False,
    "items": [{"type": "checked_bag", "count": 1, "unit": "per_child"}],
    "confidence": "high",
})
check("item 3: the guided-extraction field's own (primary) schema accepts per_child, "
      "not just the regex fail-safe",
      fragment.get("flight", {}).get("baggage_detail", {}).get("checked_bag", {}).get("unit") == "per_child")
check("item 3: EXTRACTOR_SYSTEM's guided baggage prompt documents per_child as its own, "
      "explicitly-distinct-from-per_person category",
      "per_child" in chat.EXTRACTOR_SYSTEM)

# Regressions: existing units still work exactly as before.
r_person = chat._deterministic_baggage_facts("מזוודה גדולה לכל אחד מאיתנו", traveler_count=4)
check("regression: per_person unit (no explicit digit) still recognized",
      r_person["flight"]["baggage_detail"]["checked_bag"]["unit"] == "per_person")
r_couple = chat._deterministic_baggage_facts("מזוודה אחת לכל זוג", traveler_count=4)
check("regression: per_couple unit still recognized",
      r_couple["flight"]["baggage_detail"]["checked_bag"]["unit"] == "per_couple")
r_total = chat._deterministic_baggage_facts("שתי מזוודות לכולנו", traveler_count=4)
check("regression: total/shared unit still recognized",
      r_total["flight"]["baggage_detail"]["checked_bag"]["unit"] == "total")


# =====================================================================
# 4. trip_type rule loosened to match the open-question flow (#85).
# =====================================================================
check("item 4: EXTRACTOR_SYSTEM's trip_type rule no longer requires a literal "
      "category word, and explains why (the open question never elicits one)",
      "כמעט לעולם לא ישתמש במילים" in chat.EXTRACTOR_SYSTEM)
check("item 4: the rule still forbids guessing trip_type from destination/dates/"
      "travelers alone when the customer never described the trip's purpose",
      "לנחש trip_type מ-destination/dates/travelers" in chat.EXTRACTOR_SYSTEM)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE3-RUN4-ROOT-CAUSES TESTS PASSED")
