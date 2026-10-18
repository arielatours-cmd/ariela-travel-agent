"""QA for the business owner's 18.10.2026 directive (relayed via Shlomo,
after the evidence-based/English-word-rule fixes already shipped in this
same PR): any field with a canonical/closed-vocabulary list of values
(lodging.details.type being the one place in the codebase that actually
enforced one in code) must never REJECT a value the customer genuinely
stated just because it isn't one of the listed words - it must keep the
customer's own wording (normalizing it when it's an obvious synonym of a
canonical value), never silently drop it and force a re-ask of a question
already answered.

Before this fix, _guided_field_update_and_confirm's lodging_type branch
checked `value not in _LODGING_TYPE_CANON_VALUES` and returned {} (nothing
written, field stays unanswered) for anything outside the 6-word list -
so a customer who said "בקתת עץ" (a wooden cabin) or "בית הארחה" (a guest
house) would be asked the exact same question again, as if they'd said
nothing at all.

Fixed: the reject-on-unknown check is removed entirely. The two known
synonyms (אפרטמנט->דירה, אכסניה->הוסטל) still normalize; every other
non-empty value is kept exactly as returned. The guided-extraction prompt
(_lodging_guided_prompt, field="lodging_type") is updated to match: the
model is now instructed to keep the customer's own Hebrew wording for an
unlisted type rather than invent a category or return null for it - null
means only that no lodging type was mentioned at all. _LODGING_TYPE_
CANON_VALUES (now unused) is removed.

Run: python3 tools/qa_canonical_value_keeps_customer_wording.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# 1. A genuinely novel, unlisted lodging type is KEPT verbatim, never
#    dropped - the live bug this fix addresses.
# =====================================================================
for novel_value in ("בקתת עץ", "בית הארחה", "קמפינג", "אכסניית נוער משפחתית"):
    fragment, desc = chat._guided_field_update_and_confirm(
        "lodging_type", {"status": "answered", "value": novel_value, "confidence": "high"},
    )
    check(f"unlisted lodging type '{novel_value}' is kept in the customer's own wording, never dropped",
          fragment.get("lodging", {}).get("details", {}).get("type") == novel_value)
    check(f"'{novel_value}': a usable description is still produced for Tinkerbell's hint",
          bool(desc) and novel_value in desc)

# =====================================================================
# 2. The two known synonyms still normalize to their canonical spelling
#    (this behavior must survive the fix, not just the reject removal).
# =====================================================================
fragment_apt, _ = chat._guided_field_update_and_confirm(
    "lodging_type", {"status": "answered", "value": "אפרטמנט", "confidence": "high"},
)
check("'אפרטמנט' still normalizes to 'דירה'",
      fragment_apt.get("lodging", {}).get("details", {}).get("type") == "דירה")

fragment_hostel, _ = chat._guided_field_update_and_confirm(
    "lodging_type", {"status": "answered", "value": "אכסניה", "confidence": "high"},
)
check("'אכסניה' still normalizes to 'הוסטל'",
      fragment_hostel.get("lodging", {}).get("details", {}).get("type") == "הוסטל")

# =====================================================================
# 3. One of the 6 original canonical words still passes through
#    unchanged (regression: the fix must not alter already-correct values).
# =====================================================================
for canon_value in ("מלון", "דירה", "וילה", "צימר", "הוסטל", "אין העדפה"):
    fragment, _ = chat._guided_field_update_and_confirm(
        "lodging_type", {"status": "answered", "value": canon_value, "confidence": "high"},
    )
    check(f"regression: canonical value '{canon_value}' is unaffected",
          fragment.get("lodging", {}).get("details", {}).get("type") == canon_value)

# =====================================================================
# 4. A genuinely empty/null value (nothing was actually said) still
#    produces no fragment at all - the fix must not start inventing
#    values when the model correctly reports nothing.
# =====================================================================
fragment_none, desc_none = chat._guided_field_update_and_confirm(
    "lodging_type", {"status": "answered", "value": None, "confidence": "low"},
)
check("a null value still produces no fragment (nothing was actually said)",
      fragment_none == {} and desc_none is None)
fragment_blank, _ = chat._guided_field_update_and_confirm(
    "lodging_type", {"status": "answered", "value": "   ", "confidence": "low"},
)
check("a blank/whitespace-only value is treated the same as null",
      fragment_blank == {})

# =====================================================================
# 5. The now-dead _LODGING_TYPE_CANON_VALUES constant is actually gone,
#    not just unused - confirms the reject mechanism itself was removed,
#    not merely bypassed.
# =====================================================================
check("_LODGING_TYPE_CANON_VALUES no longer exists on the module (the reject-on-unknown mechanism is fully removed)",
      not hasattr(chat, "_LODGING_TYPE_CANON_VALUES"))

# =====================================================================
# 6. The guided-extraction prompt itself instructs the model to keep an
#    unlisted type in the customer's own wording, not just leave the
#    code-side door open for it.
# =====================================================================
prompt = chat._lodging_guided_prompt("lodging_type", {}, "")
check("the prompt explicitly tells the model to keep an unlisted type in the customer's own wording",
      "שמרי את הניסוח שלו בעברית" in prompt)
check("the prompt explicitly forbids rejecting/nulling a value just for not being in the closed list",
      "לעולם אל תדחי ערך רק כי הוא לא ברשימה הסגורה" in prompt)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL CANONICAL-VALUE-KEEPS-CUSTOMER-WORDING TESTS PASSED")
