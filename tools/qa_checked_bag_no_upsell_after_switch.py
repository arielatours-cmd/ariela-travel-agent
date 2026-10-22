"""QA for Bezalel's task 4 (22.10): after the customer switches to a checked
suitcase (e.g. right after the summary), the reply must not add "אפשר
להוסיף גם תיק קטן... באתר חברת התעופה". Per the 20.10 decision (#107) the
checked bag is the top tier and gets no note. _baggage_followup_hint and
_ensure_baggage_followup_note_present already return nothing for it, so the
sentence was the model's own - _strip_upsell_note_for_checked_bag removes it
on the turn the baggage changed to include checked_bag, and nowhere else.

Offline. Run: python3 tools/qa_checked_bag_no_upsell_after_switch.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import ariella_chat_clean as chat  # noqa: E402

strip = chat._strip_upsell_note_for_checked_bag
CARRY = {"flight": {"baggage": ["carry_on_only"]}}
ITEM = {"flight": {"baggage": ["personal_item"]}}
CHECKED = {"flight": {"baggage": ["checked_bag"]}}

# --- The reported case: post-summary switch trolley -> suitcase --------------------------
reply = ("עדכנתי - מזוודה בבטן המטוס לכל נוסע. אפשר להוסיף גם תיק קטן באתר חברת התעופה בזמן ההזמנה.\n"
         "הנה הסיכום המעודכן:\nכבודה: מזוודה 20–23 ק\"ג לכל נוסע (בהתאם לתנאי חברת התעופה)\n"
         "אם הכל נכון, כתבי מאשרת.")
out = strip(reply, CHECKED, CARRY)
check("switch to checked bag: the upsell sentence is removed", "אפשר להוסיף גם תיק קטן" not in out)
check("...the rest of the reply stays, incl. the summary's baggage line (בהתאם לתנאי חברת התעופה)",
      out.startswith("עדכנתי - מזוודה בבטן המטוס לכל נוסע.") and "כבודה: מזוודה 20–23" in out and "כתבי מאשרת" in out)
for sentence in ("ניתן תמיד להוסיף טרולי באתר חברת התעופה.", "תמיד אפשר להוסיף גם תיק יד בזמן ההזמנה."):
    check(f"switch to checked bag: {sentence!r} removed",
          sentence not in strip(f"מעולה, עדכנתי. {sentence} מה עוד?", CHECKED, ITEM))
check("switch from personal_item -> checked bag also covered", "להוסיף" not in strip(reply, CHECKED, ITEM))
check("first-time checked bag (no prior baggage) also covered", "להוסיף" not in strip(reply, CHECKED, {}))

# --- Never touched -------------------------------------------------------------------------
question_answer = "כן, אפשר להוסיף תיק קטן באתר חברת התעופה בזמן ההזמנה."
check("checked bag unchanged this turn (customer asks about adding a bag) -> answer kept",
      strip(question_answer, CHECKED, CHECKED) == question_answer)
note = "אפשר תמיד להוסיף מזוודה בבטן המטוס באתר חברת התעופה בזמן ההזמנה. מה התקציב?"
check("carry-on chosen -> its legitimate note is kept", strip(note, CARRY, {}) == note)
check("personal_item chosen -> its legitimate note is kept", strip(note, ITEM, {}) == note)
plain = "מעולה, מזוודה לכל נוסע. מה התקציב?"
check("no upsell sentence -> reply unchanged", strip(plain, CHECKED, CARRY) == plain)

# The existing mechanisms already give nothing for a checked bag (unchanged)
check("_baggage_followup_hint(['checked_bag']) is still None", chat._baggage_followup_hint(["checked_bag"]) is None)
check("_ensure_baggage_followup_note_present adds nothing for checked bag",
      chat._ensure_baggage_followup_note_present(plain, CHECKED, {}) == plain)

src = open(os.path.join(os.path.dirname(__file__), "..", "ariella_chat_clean.py"), encoding="utf-8").read()
check("wired right after the follow-up note backup",
      "reply = _ensure_baggage_followup_note_present(reply, trip_update, trip_state)\n"
      "        reply = _strip_upsell_note_for_checked_bag(reply, trip_update, trip_state)" in src)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
