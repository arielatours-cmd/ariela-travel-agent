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
phrased per-passenger by the model. _ensure_flight_summary_completeness
now unconditionally normalizes whichever single sentence mentions a
baggage value word (טרולי/מזוודה/תיק) to the canonical
_flight_baggage_line text, in place - the same "detect wrong wording,
replace with the fixed line" pattern already used for a budget line
naming the wrong currency.

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
# Shaked's exact Berlin shape: a per-passenger-phrased baggage sentence
# inside an otherwise-valid final summary must be normalized to the
# canonical uniform line.
# =====================================================================
berlin_reply = (
    "סיכום בקשת הטיסה: יעד ברלין. לדנה מזוודה, לרון טרולי. תקציב 1200 ₪. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)
fixed = chat._ensure_flight_summary_completeness(berlin_reply, _STATE)
check("the per-passenger baggage sentence ('לדנה מזוודה, לרון טרולי') is "
      "replaced with the canonical uniform line",
      "לדנה" not in fixed and "לרון" not in fixed and _CANONICAL in fixed)
check("the rest of the summary (destination, budget, approval request) "
      "survives untouched",
      "ברלין" in fixed and "1200" in fixed and "כתבי מאשרת" in fixed)

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
# Regression: a reply with NO approval-request wording at all (not the
# final summary moment) is never touched by this function at all -
# matches its own existing, documented gate.
# =====================================================================
mid_conversation_reply = "לדנה מזוודה, לרון טרולי. יש עוד משהו לגבי הטיסה?"
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
mixed_reply = "סיכום בקשת הטיסה: לדנה טרולי קטן, לרון תיק יד בלבד. תקציב 800 ₪. אם כל הפרטים נכונים, כתבי מאשרת."
fixed_carry_on = chat._ensure_flight_summary_completeness(mixed_reply, carry_on_state)
check("carry_on_only also normalizes a per-passenger-phrased sentence to "
      "its own canonical line",
      "לדנה" not in fixed_carry_on and "לרון" not in fixed_carry_on
      and carry_on_canonical in fixed_carry_on)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BAGGAGE-SUMMARY-UNIFORM-WORDING TESTS PASSED")
