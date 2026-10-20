"""QA for priority-5's baggage-precision findings (Shlomo, 20.10.2026,
relaying Carmit's stage-1/2 regression + her own 7-item WhatsApp feedback),
shipped after priorities 2 (English-leak, PR #90) and 4 per his explicit
"תמשיך לפי הסדר: עדיפות 2, אחריה 4, אחריה 5" ordering.

Three real code-level bugs, all in flight.baggage_detail:

1. checked_bag's "size" was never tracked at all - the summary/label always
   invented "גדולה" (large) regardless of what the customer actually said
   ("בינונית" (medium) was silently shown back as "גדולה"). Now a real,
   optional fact: "קטנה"/"בינונית"/"גדולה"/unset, captured the same way
   count/unit already were, never guessed when unstated.

2. "מבוגר" (adult) was lumped into the SAME "per_person" unit bucket as
   "אחד/נוסע/אדם" - "טרולי לכל מבוגר" (a carry-on per ADULT, excluding
   children) was shown back as "לכל נוסע" (per every traveler, children
   included), silently erasing an explicit exclusion the customer stated.
   Split into its own unit, "per_adult", with the same precedence
   "per_child" already had over the generic per-person case.

3. carry_on (trolley-only) never tracked count/unit/detail at all, unlike
   checked_bag - "טרולי לכל מבוגר" lost the per-adult split the moment it
   reached either path (guided-extraction primary path or the regex
   fail-safe). Now mirrors checked_bag's own unit detection (minus the
   size dimension, which never applied to a carry-on), with a NEW
   _carry_on_label function and its own baggage_detail.carry_on_only
   sub-object.

Covers both paths: the guided-extraction primary path
(_guided_field_update_and_confirm) and the regex-only fail-safe
(_deterministic_baggage_facts) used when the model call isn't available or
guided extraction is off for the session.

Also regression-tests a real bug found and fixed while building this: the
regex fail-safe's new carry_on unit detection originally searched the WHOLE
message for a unit word, so a message stating two DIFFERENT units for the
two bag kinds ("טרולי לכל אחד ומזוודה אחת משותפת": a per-person trolley, a
separately shared suitcase) wrongly attributed the suitcase's own "total"
unit to the trolley too. Fixed by requiring the unit phrase to actually be
near "טרולי" (same 15-char proximity window already used to detect
carry_on_only's own presence), not just present anywhere in the message.

Run: python3 tools/qa_baggage_precision_fixes.py
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
# 1. checked_bag size - regex fail-safe path
# =====================================================================
check("fail-safe: 'מזוודה בינונית' captures size=בינונית, never the old "
      "invented 'גדולה' default",
      chat._deterministic_baggage_facts("מזוודה בינונית")
      ["flight"]["baggage_detail"]["checked_bag"].get("size") == "בינונית")
check("fail-safe: 'מזוודה קטנה' captures size=קטנה",
      chat._deterministic_baggage_facts("מזוודה קטנה")
      ["flight"]["baggage_detail"]["checked_bag"].get("size") == "קטנה")
check("fail-safe: plural 'מזוודות בינוניות' normalizes to the singular size word",
      chat._deterministic_baggage_facts("שתי מזוודות בינוניות", traveler_count=2)
      ["flight"]["baggage_detail"]["checked_bag"].get("size") == "בינונית")
check("fail-safe: no size word at all -> no baggage_detail invented at all "
      "(unlike the old hardcoded 'גדולה' default)",
      "baggage_detail" not in chat._deterministic_baggage_facts("יש לנו מזוודה בבטן המטוס")["flight"])

# =====================================================================
# 2. per_adult unit, distinct from per_person - both bag kinds, both paths
# =====================================================================
check("fail-safe: checked_bag 'מזוודה לכל מבוגר' is unit=per_adult, never the "
      "generic per_person (which would wrongly include children)",
      chat._deterministic_baggage_facts("יש לנו מזוודה בבטן המטוס לכל מבוגר")
      ["flight"]["baggage_detail"]["checked_bag"].get("unit") == "per_adult")
check("fail-safe: the plain per-person phrasing ('לכל אחד') is still "
      "unit=per_person, unaffected by the per_adult split",
      chat._deterministic_baggage_facts("מזוודה גדולה לכל אחד")
      ["flight"]["baggage_detail"]["checked_bag"].get("unit") == "per_person")
check("fail-safe: carry_on 'טרולי לכל מבוגר' is unit=per_adult on the trolley "
      "side too - Shlomo's exact repro",
      chat._deterministic_baggage_facts("טרולי לכל מבוגר")
      ["flight"]["baggage_detail"]["carry_on_only"].get("unit") == "per_adult")
check("guided path: item {type:checked_bag, unit:per_adult} is preserved "
      "as-is, not collapsed to per_person",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "checked_bag", "unit": "per_adult"}]}
      )[0]["flight"]["baggage_detail"]["checked_bag"] == {"unit": "per_adult"})
check("guided path: an unrecognized unit string is dropped (never trusted "
      "blindly from the model) rather than crashing or inventing a fallback",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "checked_bag", "unit": "per_bag"}]}
      )[0]["flight"].get("baggage_detail", {}).get("checked_bag", {}).get("unit") is None)

# =====================================================================
# 3. carry_on count/unit/detail parity with checked_bag - both paths
# =====================================================================
check("guided path: a carry_on item with count+unit gets its own "
      "baggage_detail.carry_on_only, mirroring checked_bag's own structure",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "carry_on_only", "count": 2, "unit": "per_couple"}]}
      )[0]["flight"]["baggage_detail"]["carry_on_only"] == {"count": 2, "unit": "per_couple"})
check("guided path: a carry_on item with no count/unit stated keeps the old "
      "flat label, no new default invented (same convention checked_bag "
      "never had before this fix either)",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "carry_on_only"}]}
      ) == ({"flight": {"baggage": ["carry_on_only"]}}, chat._BAGGAGE_HE.get("carry_on_only")))
check("fail-safe: 'רק טרולי לכל זוג' (no מזוודה word at all) now also records "
      "the per-couple split on the carry-on side",
      chat._deterministic_baggage_facts("רק טרולי לכל זוג", traveler_count=4)
      ["flight"]["baggage_detail"]["carry_on_only"].get("unit") == "per_couple")
check("fail-safe: proximity bug fixed - 'טרולי לכל אחד ומזוודה אחת משותפת' "
      "(two DIFFERENT units for the two bag kinds) attributes 'total' only "
      "to the suitcase, and 'per_person' only to the nearby trolley phrase, "
      "never crossing over",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת משותפת") == {
          "flight": {
              "baggage": ["carry_on_only", "checked_bag"],
              "baggage_detail": {
                  "checked_bag": {"unit": "total", "count": 1},
                  "carry_on_only": {"unit": "per_person"},
              },
          },
      })
check("fail-safe regression: carry_on_only alone, with no unit word nearby "
      "at all, still records no baggage_detail (no default invented)",
      "baggage_detail" not in chat._deterministic_baggage_facts("רק טרולי בלבד")["flight"])

# =====================================================================
# 4. _checked_bag_label / _carry_on_label - labels built from real data
# =====================================================================
check("label: size stated (קטנה) + per_adult unit -> both facts in the label",
      chat._checked_bag_label({"unit": "per_adult", "size": "קטנה"})
      == "מזוודה קטנה אחת לכל מבוגר")
check("label: per_adult, count=2, no size -> states the real count, no "
      "invented size",
      chat._checked_bag_label({"unit": "per_adult", "count": 2})
      == "2 מזוודות לכל מבוגר")
check("label: size alone (no unit/count) still appears in the generic "
      "per-passenger default, instead of the old invented 'גדולה'",
      chat._checked_bag_label({"size": "בינונית"}) == "מזוודה בינונית אחת לכל נוסע")
check("_carry_on_label: per_adult, count=1 -> states the unit, never "
      "inventing a 'per traveler' default the way checked_bag's own "
      "fallback does",
      chat._carry_on_label({"unit": "per_adult", "count": 1}) == "טרולי אחד לכל מבוגר")
check("_carry_on_label: total, count=3 -> states the real count, shared "
      "phrasing",
      chat._carry_on_label({"unit": "total", "count": 3}) == "3 טרולים משותפים לכל הנוסעים")
check("_carry_on_label: no detail at all -> the plain flat label, no "
      "per-traveler default invented (unlike _checked_bag_label(None))",
      chat._carry_on_label(None) == chat._BAGGAGE_HE.get("carry_on_only"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BAGGAGE-PRECISION-FIXES TESTS PASSED")
