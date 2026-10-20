"""QA for priority-5's baggage-precision findings (Shlomo, 20.10.2026,
relaying Carmit's stage-1/2 regression + her own 7-item WhatsApp feedback),
shipped after priorities 2 (English-leak, PR #90) and 4, then simplified
the same day per the business owner's own directive on PR #91.

Original scope (per_adult unit, carry_on count/unit/size) was reviewed by
Shaked and rejected: her fail-safe repros showed a whole-message regex
search cross-attributing one bag kind's unit word to the OTHER bag kind
whenever both were mentioned together - no fixed-window or distance
heuristic can reliably tell which phrase belongs to which bag from text
alone, which is exactly the class of mistake the business owner's standing
rule forbids (understanding via phrase/word matching instead of the
model).

Before that fix could even ship, Carmit (relayed by Shlomo, 20.10) made the
whole premise moot: a group booking is ALWAYS one uniform baggage choice
for every ticket (never a per-passenger split, short of two separate
bookings) - so per_adult/per_couple/per_child/per_person/total unit
tracking was never meaningful in the first place. This file now tests the
FINAL, simplified model:

1. checked_bag's "size" (קטנה/בינונית/גדולה) - GUIDED model path only, the
   real fact the business owner's priority-5 finding (s12x10) originally
   asked for; never guessed when unstated, never tracked at all by the
   fail-safe (the fail-safe isn't asked to understand which exact size
   word belongs to which bag, only whether a bag was mentioned).

2. count - the group total, tracked by BOTH the guided path and the
   fail-safe (the fail-safe already reliably parses "שתי מזוודות"/"מזוודה
   אחת" without needing to attribute anything to a specific passenger).

3. mixed_per_passenger - when the customer's own words explicitly
   differentiate what different passengers get (the MODEL decides this
   from meaning, never a phrase list), the booking still can't represent
   that split: default to checked_bag for everyone and surface the
   uniform-booking explanation via the existing low-confidence
   confirm-hint pathway, rather than silently merging a request that was
   never actually made.

4. _checked_bag_label / _carry_on_label - simplified to count+size only,
   no unit parameter anywhere; a stated size still pluralizes correctly
   once count>1 (the original PR #91 label bug, independent of the unit
   question and still valid after the simplification).

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
#    attempts size at all - it only recognizes that a bag was mentioned
#    and, separately, a stated count).
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
      "not captured here at all - size is a guided-model-only fact, never "
      "guessed from the message text - still correctly records checked_bag "
      "itself, just no size in the detail",
      "size" not in chat._deterministic_baggage_facts("מזוודה בינונית")
      ["flight"].get("baggage_detail", {}).get("checked_bag", {}))

# =====================================================================
# 2. count - the group total, tracked by both mechanisms. No per-passenger
#    unit exists anymore for either mechanism (business owner's 20.10
#    directive: a booking is always one uniform baggage choice for every
#    ticket in the group).
# =====================================================================
check("fail-safe: 'יש לנו מזוודה בבטן המטוס לכל מבוגר' records checked_bag, "
      "no unit/per-passenger detail of any kind survives",
      chat._deterministic_baggage_facts("יש לנו מזוודה בבטן המטוס לכל מבוגר")
      == {"flight": {"baggage": ["checked_bag"]}})
check("fail-safe: 'מזוודה גדולה לכל אחד' (no digit stated) also records "
      "just checked_bag, no detail invented",
      chat._deterministic_baggage_facts("מזוודה גדולה לכל אחד")
      == {"flight": {"baggage": ["checked_bag"]}})
check("fail-safe: an explicit count ('שתי מזוודות') is still recovered - "
      "this is the one real fact the fail-safe can reliably parse without "
      "attributing anything to a specific passenger",
      chat._deterministic_baggage_facts("יש לנו שתי מזוודות")
      ["flight"]["baggage_detail"] == {"checked_bag": {"count": 2}})
check("guided path: item {type:checked_bag, count:2} is preserved as-is",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "checked_bag", "count": 2}]}
      )[0]["flight"]["baggage_detail"]["checked_bag"] == {"count": 2})
check("guided path: a carry_on item with a count gets its own "
      "baggage_detail.carry_on_only, mirroring checked_bag's own structure",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "carry_on_only", "count": 2}]}
      )[0]["flight"]["baggage_detail"]["carry_on_only"] == {"count": 2})
check("guided path: a carry_on item with no count stated keeps the old "
      "flat label, no default invented",
      chat._guided_field_update_and_confirm(
          "baggage", {"items": [{"type": "carry_on_only"}]}
      ) == ({"flight": {"baggage": ["carry_on_only"]}}, chat._BAGGAGE_HE.get("carry_on_only")))
check("fail-safe: carry_on alone ('טרולי לכל מבוגר') is detected as a "
      "baggage kind, with no unit/count detail attempted for it at all",
      chat._deterministic_baggage_facts("טרולי לכל מבוגר")
      == {"flight": {"baggage": ["carry_on_only"]}})
check("fail-safe regression: carry_on_only alone, with no מזוודה word "
      "anywhere, still records no baggage_detail at all",
      "baggage_detail" not in chat._deterministic_baggage_facts("רק טרולי בלבד")["flight"])

# =====================================================================
# Shaked's exact PR #91 review repros: TWO baggage kinds in one message,
# each with its OWN unit word in the original (rejected) fix - now that
# unit tracking is removed entirely, these just confirm both bag kinds
# are still recorded, and only the reliably-parsed checked-bag count
# (never any unit) survives.
# =====================================================================
check("Shaked's repro 1: 'טרולי לכל מבוגר ומזוודה אחת' - both kinds "
      "recorded, checked_bag keeps its count (1), no unit anywhere",
      chat._deterministic_baggage_facts("טרולי לכל מבוגר ומזוודה אחת")
      == {"flight": {
          "baggage": ["carry_on_only", "checked_bag"],
          "baggage_detail": {"checked_bag": {"count": 1}},
      }})
check("Shaked's repro 2: 'לכל מבוגר מזוודה, וטרולי אחד לכולנו' - both "
      "kinds recorded, no count (no explicit digit next to מזוודה itself) "
      "and no unit for either",
      chat._deterministic_baggage_facts("לכל מבוגר מזוודה, וטרולי אחד לכולנו")
      == {"flight": {"baggage": ["carry_on_only", "checked_bag"]}})
check("Shaked's repro 3: 'שתי מזוודות גדולות ועוד טרולי לכל נוסע' - "
      "count=2 survives for the suitcase, no unit anywhere",
      chat._deterministic_baggage_facts("שתי מזוודות גדולות ועוד טרולי לכל נוסע")
      ["flight"]["baggage_detail"] == {"checked_bag": {"count": 2}})
check("regression: the original proximity-bug repro ('טרולי לכל אחד "
      "ומזוודה אחת משותפת') - both kinds recorded, suitcase count (1) "
      "survives, no unit for either",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת משותפת")
      == {"flight": {
          "baggage": ["carry_on_only", "checked_bag"],
          "baggage_detail": {"checked_bag": {"count": 1}},
      }})

# =====================================================================
# 3. mixed_per_passenger - the model's own understanding that different
#    passengers were asked for different things; the booking can't
#    represent that split, so it defaults to checked_bag for everyone.
#    UPDATED (20.10, after Shaked's live K1 Warsaw finding on #91: Ariella
#    correctly explained uniform baggage but then ASKED a confirm question
#    anyway, and separately PROMISED a per-passenger split at booking time
#    - both now forbidden per the business owner's explicit decision): the
#    resolution is now completely SILENT - the exact same flat description
#    as a direct checked_bag answer, no explanation, no confirm question.
# =====================================================================
check("guided path: mixed_per_passenger defaults the whole group to "
      "checked_bag, never silently merging distinct per-passenger requests",
      chat._guided_field_update_and_confirm(
          "baggage", {"mixed_per_passenger": True}
      )[0] == {"flight": {"baggage": ["checked_bag"]}})
check("guided path: mixed_per_passenger's description is the SAME flat "
      "label as a direct checked_bag answer - no explanation of the mixed "
      "request or the uniform-booking rule leaks into it at all",
      chat._guided_field_update_and_confirm(
          "baggage", {"mixed_per_passenger": True}
      )[1] == chat._checked_bag_label({}))
check("guided path: mixed_per_passenger takes precedence even if the model "
      "also sent items alongside it (never a silently-merged per-passenger "
      "fact)",
      chat._guided_field_update_and_confirm(
          "baggage", {"mixed_per_passenger": True,
                      "items": [{"type": "carry_on_only"}]}
      )[0] == {"flight": {"baggage": ["checked_bag"]}})

# =====================================================================
# 4. _checked_bag_label / _carry_on_label - simplified labels, count+size
#    only, no unit parameter anywhere.
# =====================================================================
check("label: size stated (קטנה), no count -> the generic per-passenger "
      "default with the real size, never the old invented 'גדולה'",
      chat._checked_bag_label({"size": "קטנה"}) == "מזוודה קטנה אחת לכל נוסע")
check("label: count=2, no size -> states the real count, no invented size",
      chat._checked_bag_label({"count": 2}) == "2 מזוודות")
check("label fix (Shlomo's PR #91 review): a stated size no longer "
      "disappears once count>1 - '2 מזוודות גדולות', not the old bare "
      "'2 מזוודות'",
      chat._checked_bag_label({"count": 2, "size": "גדולה"}) == "2 מזוודות גדולות")
check("label: no detail at all -> the plain per-passenger default",
      chat._checked_bag_label(None) == "מזוודה אחת לכל נוסע")
check("_carry_on_label: count=1 -> states the singular form",
      chat._carry_on_label({"count": 1}) == "טרולי אחד")
check("_carry_on_label: count=3 -> states the real count",
      chat._carry_on_label({"count": 3}) == "3 טרולים")
check("_carry_on_label: no detail at all -> the plain flat label, no "
      "per-traveler default invented (unlike _checked_bag_label(None))",
      chat._carry_on_label(None) == chat._BAGGAGE_HE.get("carry_on_only"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BAGGAGE-PRECISION-FIXES TESTS PASSED")
