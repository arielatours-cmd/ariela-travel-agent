"""QA for run-10 #2 (Montpellier, 22.10): "לי מזוודה, לאמא מספיק טרולי" was
not recognised as mixed_per_passenger - personal_item was saved, and "איזו
כבודה" was asked 3 times.

Cause (prompt): the guided baggage prompt opened with "the booking is
uniform, so no per-passenger detail is needed - just the uniform type",
which steers the model to COLLAPSE a per-passenger split into one type; the
mixed rule came only later, and its examples didn't cover the "ל<X> <type>,
ל<Y> <type>" shape. Fix - instructions only, before the model answers (no
after-the-fact text filtering): check mixed FIRST, never pick one type out
of a mixed request, and the Montpellier shape as an example, in both the
guided baggage prompt and EXTRACTOR_SYSTEM.

Offline: checks what the model is given. The model's real behaviour on
this phrasing needs the next live run.
Run: python3 tools/qa_mixed_baggage_side_by_side.py
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import ariella_chat_clean as chat  # noqa: E402

captured = {}


def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    captured[source] = (system_static or "") + "\n" + (system_dynamic or "")
    return json.dumps({"status": "answered", "no_baggage": False, "mixed_per_passenger": True, "items": None,
                       "confidence": "high", "also_mentioned": {}, "correction": None})


state = {"travelers": {"adults": 2}, "flight": {"baggage": []}, "destination": {"places": ["מונפלייה"]}}
with patch.object(chat, "_post_claude", side_effect=fake):
    chat._guided_extract_answer("k", "m", "baggage", "לי מזוודה, לאמא מספיק טרולי", [], state)
prompt = captured.get("guided_extract", "")

check("guided baggage prompt captured", bool(prompt))
check("guided prompt: the Montpellier shape is an explicit mixed example", "לי מזוודה, לאמא מספיק טרולי" in prompt)
check("guided prompt: mixed is checked FIRST, before the uniform-type instruction",
      "בדקי קודם כול" in prompt and prompt.index("בדקי קודם כול") < prompt.index("רק כשהבקשה אחידה לכולם"))
check("guided prompt: never pick one type out of a mixed request", "אסור לבחור במקומו סוג אחד מתוכה" in prompt)
check("guided prompt: 'מספיק' for one passenger is still an assignment (mixed)", "\"מספיק\"" in prompt)
check("guided prompt: the old 'no per-passenger detail needed' line no longer opens unconditionally",
      "לכן אין צורך בפירוט לפי נוסע (מי בדיוק מקבל מה)" not in prompt)
check("guided prompt: whole-group trolley+suitcase is still NOT mixed", "לעולם לא true רק בגלל שיש גם טרולי" in prompt)
check("EXTRACTOR_SYSTEM carries the same example", "לי מזוודה, לאמא מספיק טרולי" in chat.EXTRACTOR_SYSTEM)

# The rest of the mixed flow (#128) is unchanged: a mixed result is handled, nothing saved
r = None
with patch.object(chat, "_post_claude", side_effect=fake):
    trip_state = {"guided": {"current_question": "baggage", "attempts": 0, "answered": []}, **state,
                  "requested_services": ["flights"]}
    r = chat._handle_guided_extraction_turn("k", "m", "לי מזוודה, לאמא מספיק טרולי", [], trip_state,
                                            json.loads(json.dumps(trip_state)), {"baggage"})
check("mixed result -> no baggage type saved (handled by the #128 flow)",
      not ((r or {}).get("trip_update", {}).get("flight") or {}).get("baggage"))

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
