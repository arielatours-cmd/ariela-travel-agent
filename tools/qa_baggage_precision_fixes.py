"""QA for priority-5's baggage-precision findings (Shlomo, 20.10.2026,
relaying Carmit's stage-1/2 regression + her own 7-item WhatsApp feedback),
shipped after priorities 2 (English-leak, PR #90) and 4 per his explicit
"תמשיך לפי הסדר: עדיפות 2, אחריה 4, אחריה 5" ordering.

Three real facts, all in flight.baggage_detail, now captured via the
GUIDED-EXTRACTION model path (_guided_field_update_and_confirm) - the real,
primary mechanism that asks the model directly, per item, {type, count,
unit, size}:

1. checked_bag's "size" was never tracked at all - the summary/label always
   invented "גדולה" (large) regardless of what the customer actually said.
   Now a real, optional fact: "קטנה"/"בינונית"/"גדולה"/unset, never guessed
   when unstated.

2. "מבוגר" (adult) was lumped into the SAME "per_person" unit bucket as
   "אחד/נוסע/אדם" - "טרולי לכל מבוגר" was shown back as "לכל נוסע" (per
   every traveler, children included), silently erasing an explicit
   exclusion the customer stated. Split into its own unit, "per_adult".

3. carry_on (trolley-only) never tracked count/unit/detail at all, unlike
   checked_bag. Now mirrors checked_bag's own structure (minus size, which
   never applied to a carry-on), with a new _carry_on_label function and
   its own baggage_detail.carry_on_only sub-object.

Per Shaked's PR #91 REVIEW (20.10, confirmed by the business owner): her
FIRST version of this fix tried to extend _deterministic_baggage_facts (the
regex-only FAIL-SAFE, used only when the guided model call itself isn't
available) with the same per_adult/size/carry-on-unit detail, using
whole-message word matching (even with a nearest-phrase-by-character-
distance refinement). That is still exactly the class of mistake the
business owner's standing rule forbids (understanding via phrase/word
matching instead of the model) - and it was still provably wrong in
practice: a message naming BOTH bag kinds, each with its OWN unit word
("טרולי לכל מבוגר ומזוודה אחת", "לכל מבוגר מזוודה וטרולי אחד לכולנו", "שתי
מזוודות גדולות ועוד טרולי לכל נוסע"), kept attributing one bag kind's unit
word to the OTHER bag kind - no fixed window or distance heuristic can
reliably tell which phrase belongs to which bag from text alone.

Final, approved fix: the fail-safe reverts to never guessing a unit at all
once a SECOND baggage kind is also mentioned in the same message (ambiguous
-> no unit, not a guess); carry_on's own unit/size tracking is removed from
the fail-safe entirely (it never attempts it, so there is nothing left to
get wrong) - the guided model path is the one real mechanism for this
detail, exactly as it already was for baggage_detail before this round.
per_adult (and count) are still correctly recognized by the fail-safe for
checked_bag in the UNAMBIGUOUS case (only one baggage kind mentioned) -
that part was never wrong, only the cross-contamination when two kinds
were mentioned together.

Also fixed (Shlomo's PR #91 review): _checked_bag_label used to drop a
stated size entirely once count>1 ("2 מזוודות" lost "גדולות") - the plural
branches built their own bare count text instead of reusing the size-aware
bag_word. Now pluralizes the size adjective too.

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
# 1. checked_bag size - GUIDED model path only (the fail-safe never
#    attempts size at all, per Shaked's review).
# =====================================================================
check("guided path: item {type:checked_bag, size:בינונית} is preserved, "
      "never the old invented 'גדולה' default",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "checked_bag", "size": "בינונית"}]}
      )[0]["flight"]["baggage_detail"]["checked_bag"] == {"size": "בינונית"})
check("guided path: an unrecognized size string is dropped, never trusted "
      "blindly from the model",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "checked_bag", "size": "ענקית"}]}
      )[0]["flight"].get("baggage_detail", {}).get("checked_bag", {}).get("size") is None)
check("fail-safe: a size word in the message ('מזוודה בינונית' alone) is "
      "NOT captured here at all (fully reverted per Shaked's review - size "
      "is a guided-model-only fact now, never guessed from the message "
      "text) - still correctly records checked_bag itself, just no detail",
      "baggage_detail" not in chat._deterministic_baggage_facts("מזוודה בינונית")["flight"])

# =====================================================================
# 2. per_adult unit, distinct from per_person
# =====================================================================
check("fail-safe: checked_bag 'מזוודה לכל מבוגר' (ONLY ONE baggage kind "
      "mentioned - unambiguous) is still unit=per_adult, never the generic "
      "per_person",
      chat._deterministic_baggage_facts("יש לנו מזוודה בבטן המטוס לכל מבוגר")
      ["flight"]["baggage_detail"]["checked_bag"].get("unit") == "per_adult")
check("fail-safe: the plain per-person phrasing ('לכל אחד') is still "
      "unit=per_person, unaffected by the per_adult split",
      chat._deterministic_baggage_facts("מזוודה גדולה לכל אחד")
      ["flight"]["baggage_detail"]["checked_bag"].get("unit") == "per_person")
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
check("fail-safe: carry_on alone ('טרולי לכל מבוגר') is detected as a "
      "baggage kind, but the fail-safe no longer attempts a unit for it at "
      "all (removed entirely per Shaked's review, not re-gated) - the "
      "guided model path is the only source for this detail now",
      chat._deterministic_baggage_facts("טרולי לכל מבוגר")
      == {"flight": {"baggage": ["carry_on_only"]}})

# =====================================================================
# 3. carry_on count/unit/size - GUIDED model path only; the fail-safe
#    never attempts any detail for carry_on (removed, not re-gated).
# =====================================================================
check("guided path: a carry_on item with count+unit gets its own "
      "baggage_detail.carry_on_only, mirroring checked_bag's own structure",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "carry_on_only", "count": 2, "unit": "per_couple"}]}
      )[0]["flight"]["baggage_detail"]["carry_on_only"] == {"count": 2, "unit": "per_couple"})
check("guided path: a carry_on item with no count/unit stated keeps the old "
      "flat label, no new default invented",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "carry_on_only"}]}
      ) == ({"flight": {"baggage": ["carry_on_only"]}}, chat._BAGGAGE_HE.get("carry_on_only")))
check("fail-safe regression: carry_on_only alone, with no מזוודה word "
      "anywhere, still records no baggage_detail at all (no default "
      "invented, and no unit guessed either)",
      "baggage_detail" not in chat._deterministic_baggage_facts("רק טרולי בלבד")["flight"])

# =====================================================================
# Shaked's exact PR #91 review repros: TWO baggage kinds in one message,
# each with its OWN unit word - the fail-safe must never cross-attribute
# one bag kind's unit to the other. No unit is saved for EITHER kind in
# this ambiguous case; only the reliably-parsed count (never a unit word)
# survives for checked_bag.
# =====================================================================
check("Shaked's repro 1: 'טרולי לכל מבוגר ומזוודה אחת' no longer saves the "
      "suitcase as per_adult too - checked_bag keeps its count (1), no unit",
      chat._deterministic_baggage_facts("טרולי לכל מבוגר ומזוודה אחת")
      ["flight"]["baggage_detail"] == {"checked_bag": {"count": 1}})
check("Shaked's repro 2: 'לכל מבוגר מזוודה, וטרולי אחד לכולנו' no longer "
      "saves the suitcase as 'total' from the trolley's own word",
      "baggage_detail" not in chat._deterministic_baggage_facts(
          "לכל מבוגר מזוודה, וטרולי אחד לכולנו"
      )["flight"])
check("Shaked's repro 3: 'שתי מזוודות גדולות ועוד טרולי לכל נוסע' no longer "
      "saves '2 מזוודות לכל נוסע' - count=2 survives, unit does not",
      chat._deterministic_baggage_facts("שתי מזוודות גדולות ועוד טרולי לכל נוסע")
      ["flight"]["baggage_detail"] == {"checked_bag": {"count": 2}})
check("regression: the original proximity-bug repro ('טרולי לכל אחד ומזוודה "
      "אחת משותפת') - now neither bag kind gets a unit (fully reverted), "
      "but the suitcase's count (1) still survives",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת משותפת")
      == {"flight": {
          "baggage": ["carry_on_only", "checked_bag"],
          "baggage_detail": {"checked_bag": {"count": 1}},
      }})

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
check("label fix (Shlomo's PR #91 review): a stated size no longer "
      "disappears once count>1 - '2 מזוודות בינוניות לכל זוג', not the "
      "old bare '2 מזוודות לכל זוג'",
      chat._checked_bag_label({"unit": "per_couple", "count": 2, "size": "בינונית"})
      == "2 מזוודות בינוניות לכל זוג")
check("label fix regression: the genuinely-unclear-split case (count>1, no "
      "unit) still pluralizes the size adjective correctly too",
      chat._checked_bag_label({"count": 3, "size": "גדולה"}) == "3 מזוודות גדולות")
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
