"""QA for Shlomo's relay of Shaked's live stage-1 run-2 finding (Berlin):
the final approval summary's baggage sentence can be PRESENT (so
_ensure_flight_summary_completeness's own "missing" check already passes
- it does mention a baggage value word) yet still phrase it PER-PASSENGER
("לדנה מזוודה, לרון טרולי"...) even though a booking is always one
uniform choice for the whole group, never split differently per
passenger.

Per the business owner's directive: the baggage line in the final
summary must always be built deterministically from state (the uniform
state, e.g. "כבודה: כולל מזוודה בבטן המטוס" / "אחת לכל נוסע"), never
phrased per-passenger by the model.

Two earlier content-detection heuristics (bare "ל<word>" repetition, then
2+ DISTINCT baggage-type words excluding an explicit "for everyone"
marker) both still missed real live cases - Shaked's review: no content
detection at all. The final summary's baggage line always starts with
the fixed "כבודה:" label (the same wording _flight_baggage_line/
_flight_summary_text itself always uses), so _ensure_flight_summary_
completeness now unconditionally replaces whichever sentence starts with
that literal label with the canonical _flight_baggage_line text, in
place - regardless of what it says - the same "detect the labeled line,
force it to the canonical wording" pattern already used for the budget
line naming the wrong currency.

Run: python3 tools/qa_baggage_summary_uniform_wording.py
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


_STATE = {
    "flight": {"baggage": ["checked_bag"]},
    "budget_per_person": {"amount": 1200, "currency": "ILS"},
}
_CANONICAL = chat._flight_baggage_line(_STATE["flight"])

# =====================================================================
# Shaked's exact Berlin shape: a per-passenger-phrased baggage sentence,
# labeled "כבודה:", inside an otherwise-valid final summary is
# unconditionally replaced with the canonical uniform line.
# =====================================================================
berlin_reply = (
    "סיכום בקשת הטיסה: יעד ברלין. כבודה: לדנה מזוודה, לרון טרולי. תקציב 1200 ₪. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)
fixed = chat._ensure_flight_summary_completeness(berlin_reply, _STATE)
check("the per-passenger baggage sentence ('כבודה: לדנה מזוודה, לרון "
      "טרולי') is replaced with the canonical uniform line",
      "לדנה" not in fixed and "לרון" not in fixed and _CANONICAL in fixed)

# =====================================================================
# Shaked's REAL exact Berlin transcript (stage-1 run-2, s1z2): the
# customer's own message was "אני ואמא מסתדרות עם תיק קטן, לאחיין צריך
# מזוודה" - state correctly saved ['checked_bag'], but the free-text
# summary read "כבודה: תיק קטן לכל אחת מכן, מזוודה בבטן המטוס לאחיין".
# Both earlier content heuristics missed this exact live case at some
# point (first: only one bare "ל<word>"; this is now irrelevant since
# detection no longer inspects content at all - the "כבודה:" label alone
# is enough to trigger the unconditional replace).
# =====================================================================
real_berlin_reply = (
    "סיכום בקשת הטיסה: כבודה: תיק קטן לכל אחת מכן, מזוודה בבטן המטוס לאחיין. "
    "תקציב 1000 ₪. אם כל הפרטים נכונים, כתבי מאשרת."
)
real_berlin_state = {"flight": {"baggage": ["checked_bag"]}, "budget_per_person": {"amount": 1000, "currency": "ILS"}}
real_berlin_canonical = chat._flight_baggage_line(real_berlin_state["flight"])
fixed_real_berlin = chat._ensure_flight_summary_completeness(real_berlin_reply, real_berlin_state)
check("Shaked's REAL exact Berlin transcript ('כבודה: תיק קטן לכל אחת "
      "מכן, מזוודה בבטן המטוס לאחיין') is now correctly normalized",
      "לאחיין" not in fixed_real_berlin and "מכן" not in fixed_real_berlin
      and real_berlin_canonical in fixed_real_berlin)
check("the real Berlin transcript's budget line survives the fix",
      "1000" in fixed_real_berlin)
check("the rest of the summary (destination, budget, approval request) "
      "survives untouched",
      "ברלין" in fixed and "1200" in fixed and "כתבי מאשרת" in fixed)

# =====================================================================
# A second live shape (the SAME baggage-type word repeated per passenger,
# rather than two different ones - what the first distinct-word-count
# heuristic could never catch at all, by construction) is now also
# caught, since detection no longer looks at content at all.
# =====================================================================
same_word_per_passenger_reply = (
    "סיכום בקשת הטיסה: יעד תביליסי. כבודה: מזוודה לדנה, מזוודה לרון. תקציב 900 ₪. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)
same_word_state = {"flight": {"baggage": ["checked_bag"]}, "budget_per_person": {"amount": 900, "currency": "ILS"}}
same_word_canonical = chat._flight_baggage_line(same_word_state["flight"])
fixed_same_word = chat._ensure_flight_summary_completeness(same_word_per_passenger_reply, same_word_state)
check("a per-passenger split using the SAME baggage-type word twice "
      "(never catchable by a distinct-word-count heuristic) is also "
      "normalized, since detection no longer inspects content at all",
      "לדנה" not in fixed_same_word and "לרון" not in fixed_same_word
      and same_word_canonical in fixed_same_word)

# =====================================================================
# A baggage sentence that's already phrased correctly (matches the
# canonical line exactly) is left completely untouched - no needless
# rewriting of an already-compliant summary.
# =====================================================================
already_correct_reply = (
    f"סיכום בקשת הטיסה: יעד ברלין. {_CANONICAL}. תקציב 1200 ₪. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)
check("an already-canonical baggage line is left byte-for-byte untouched",
      chat._ensure_flight_summary_completeness(already_correct_reply, _STATE)
      == already_correct_reply)

# =====================================================================
# Regression: a sentence that conveys baggage WITHOUT the literal
# "כבודה:" label at all (e.g. "טיסה: טרולי לכל נוסע, תקציב 1500 ₪") is
# never touched by this replace step - it has nothing to match. It's
# still covered by the separate, pre-existing "missing" check below
# (which only checks presence, not wording), so a correct uniform
# dual-item request phrased this way also survives untouched.
# =====================================================================
uniform_dual_item_state = {"flight": {"baggage": ["carry_on_only", "checked_bag"]}, "budget_per_person": {"amount": 1200, "currency": "ILS"}}
uniform_dual_item_reply = (
    "סיכום בקשת הטיסה: טרולי וגם מזוודה לכולנו. תקציב 1200 ₪. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)
check("a correct uniform dual-item request phrased WITHOUT the 'כבודה:' "
      "label is left untouched - nothing here matches the replace trigger",
      chat._ensure_flight_summary_completeness(uniform_dual_item_reply, uniform_dual_item_state)
      == uniform_dual_item_reply)

# =====================================================================
# Regression: a reply with NO approval-request wording at all (not the
# final summary moment) is never touched by this function at all -
# matches its own existing, documented gate.
# =====================================================================
mid_conversation_reply = "כבודה: לדנה מזוודה, לרון טרולי. יש עוד משהו לגבי הטיסה?"
check("a reply that isn't the final approval summary at all (no כתבי/"
      "כתוב מאשר wording) is never touched, per-passenger phrasing and all",
      chat._ensure_flight_summary_completeness(mid_conversation_reply, _STATE)
      == mid_conversation_reply)

# =====================================================================
# Regression: when baggage isn't known in state at all, nothing is
# inserted or rewritten (matches the pre-existing "missing" check's own
# behavior - _flight_baggage_line returns None with no baggage known).
# =====================================================================
no_baggage_state = {"flight": {}, "budget_per_person": {"amount": 1200, "currency": "ILS"}}
check("with no baggage known in state at all, a baggage-looking mention "
      "is left alone (nothing to normalize against)",
      chat._flight_baggage_line(no_baggage_state["flight"]) is None)

# =====================================================================
# A different baggage tier (carry_on_only) also normalizes correctly -
# not just the checked_bag case above.
# =====================================================================
carry_on_state = {"flight": {"baggage": ["carry_on_only"]}, "budget_per_person": {"amount": 800, "currency": "ILS"}}
carry_on_canonical = chat._flight_baggage_line(carry_on_state["flight"])
mixed_reply = "סיכום בקשת הטיסה: כבודה: לדנה טרולי קטן, לרון תיק יד בלבד. תקציב 800 ₪. אם כל הפרטים נכונים, כתבי מאשרת."
fixed_carry_on = chat._ensure_flight_summary_completeness(mixed_reply, carry_on_state)
check("carry_on_only also normalizes a per-passenger-phrased sentence to "
      "its own canonical line",
      "לדנה" not in fixed_carry_on and "לרון" not in fixed_carry_on
      and carry_on_canonical in fixed_carry_on)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BAGGAGE-SUMMARY-UNIFORM-WORDING TESTS PASSED")
