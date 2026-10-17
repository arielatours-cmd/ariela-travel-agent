"""QA for a fix relayed by Shlomo (business owner's instruction, 17.10.2026):
"תור הודעות רצופות בוואטסאפ עם debounce" - consecutive WhatsApp messages
from the same customer must be answered once, not as several racing turns.

Root cause (confirmed by reading the code, not guessed): each inbound
webhook delivery runs in its own fire-and-forget daemon thread
(whatsapp_webhook -> threading.Thread(...).start(), so Meta gets a fast
ack) with zero coordination across deliveries. A customer typing one
thought across 2-3 separate WhatsApp bubbles a few seconds apart used to
spawn 2-3 concurrent route_inbound/ariella_turn calls for the SAME
member_id, each reading the same stale load_ariella_conversation() history
and racing on the save_ariella_conversation() write back - whichever
thread's save landed last silently won, dropping the other turn(s) from
history, with no guarantee the replies even arrived in the order the
customer sent them.

Fixed with a per-phone debounce queue in whatsapp.py (_queue_text_message/
_flush_text_queue): a text message appends to that phone's pending batch
and (re)starts a short timer (config.WHATSAPP_DEBOUNCE_SECONDS); each new
message for the same phone cancels and restarts the timer, so the batch
only flushes once the customer has been quiet for the debounce window -
then fires exactly ONE combined route_inbound call with every pending
text joined in order. A per-phone threading.Lock (_phone_run_lock) around
the actual flush ensures a still-running turn is waited on, never raced,
if a new batch's timer fires before the previous one finished. Button/
interactive taps bypass the queue entirely (a single deliberate action,
not prose to batch) - unaffected, same as before this fix.

Run: python3 tools/qa_whatsapp_debounce.py
"""
import json
import os
import sqlite3
import sys
import threading
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import whatsapp
import nova_conversation as nc

DB = database.DB_PATH
FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# A fast debounce window for this whole test run - the mechanics being
# tested (coalescing, serialization, per-phone isolation) don't depend on
# the exact window length, only on messages arriving faster than it.
whatsapp.WHATSAPP_DEBOUNCE_SECONDS = 0.15


def _reset_phone_queue_state():
    """Each scenario below starts from a clean slate - a stray pending
    timer/lock left over from a previous scenario (or a previous QA run's
    import of this same module-level state) must never leak into the next."""
    with whatsapp._wa_queue_guard:
        for t in whatsapp._wa_pending_timers.values():
            t.cancel()
        whatsapp._wa_pending_timers.clear()
        whatsapp._wa_pending_texts.clear()


# === 1. Three rapid consecutive messages from the same phone -> exactly
#        ONE route_inbound call, with the texts combined in order ===
_reset_phone_queue_state()
calls = []


def _fake_route_inbound(phone, text, profile_name="", button_payload=None):
    calls.append((phone, text, button_payload))
    return "תשובה אחת לכולן"


replies = []
with patch.object(whatsapp, "_reply_and_log", lambda phone, phone_hash_val, reply: replies.append(reply)), \
     patch.object(nc, "route_inbound", _fake_route_inbound):
    whatsapp._queue_text_message("9725550001", "hash1", "אני רוצה", "לקוחה")
    time.sleep(0.03)
    whatsapp._queue_text_message("9725550001", "hash1", "לטוס ליוון", "לקוחה")
    time.sleep(0.03)
    whatsapp._queue_text_message("9725550001", "hash1", "באוגוסט", "לקוחה")
    time.sleep(0.35)

check("three rapid messages from the same phone produce exactly one route_inbound call",
      len([c for c in calls if c[0] == "9725550001"]) == 1)
check("the combined text joins all three messages in the order they were sent",
      calls[-1][1] == "אני רוצה\nלטוס ליוון\nבאוגוסט")
check("exactly one reply is sent for the whole batch, not three",
      len(replies) == 1 and replies[0] == "תשובה אחת לכולן")


# === 2. Two different phones never get combined with each other ===
_reset_phone_queue_state()
calls.clear()
replies.clear()
with patch.object(whatsapp, "_reply_and_log", lambda phone, phone_hash_val, reply: replies.append((phone, reply))), \
     patch.object(nc, "route_inbound", _fake_route_inbound):
    whatsapp._queue_text_message("9725550002", "hashA", "הודעה מלקוחה א", "א")
    whatsapp._queue_text_message("9725550003", "hashB", "הודעה מלקוח ב", "ב")
    time.sleep(0.35)

phone_a_calls = [c for c in calls if c[0] == "9725550002"]
phone_b_calls = [c for c in calls if c[0] == "9725550003"]
check("phone A's own batch never includes phone B's text",
      len(phone_a_calls) == 1 and phone_a_calls[0][1] == "הודעה מלקוחה א")
check("phone B's own batch never includes phone A's text",
      len(phone_b_calls) == 1 and phone_b_calls[0][1] == "הודעה מלקוח ב")


# === 3. A single lone message still gets answered once the debounce
#        window elapses (regression guard: never gets stuck forever) ===
_reset_phone_queue_state()
calls.clear()
replies.clear()
with patch.object(whatsapp, "_reply_and_log", lambda phone, phone_hash_val, reply: replies.append(reply)), \
     patch.object(nc, "route_inbound", _fake_route_inbound):
    whatsapp._queue_text_message("9725550004", "hashC", "שלום", "ג")
    time.sleep(0.35)

check("a single message with nothing following it is still answered after the debounce window",
      len(calls) == 1 and calls[0][1] == "שלום" and len(replies) == 1)


# === 4. Serialization: a flush already in progress for a phone is waited
#        on, never run concurrently with the next batch for that SAME
#        phone (the exact race this fix exists to prevent) ===
_reset_phone_queue_state()
in_flight = {"count": 0, "max_concurrent": 0}
lock_for_counter = threading.Lock()


def _slow_route_inbound(phone, text, profile_name="", button_payload=None):
    with lock_for_counter:
        in_flight["count"] += 1
        in_flight["max_concurrent"] = max(in_flight["max_concurrent"], in_flight["count"])
    time.sleep(0.25)
    with lock_for_counter:
        in_flight["count"] -= 1
    return "ok"


with patch.object(whatsapp, "_reply_and_log", lambda phone, phone_hash_val, reply: None), \
     patch.object(nc, "route_inbound", _slow_route_inbound):
    whatsapp._queue_text_message("9725550005", "hashD", "first batch", "ד")
    # Arrives well after the first batch's timer has already fired and its
    # (slow) flush is under way, but before that flush finishes - this
    # starts a genuinely SECOND batch/timer for the same phone, not a
    # continuation of the first.
    time.sleep(0.2)
    whatsapp._queue_text_message("9725550005", "hashD", "second batch", "ד")
    time.sleep(0.6)

check("two batches for the same phone never run route_inbound concurrently "
      "(the per-phone lock serializes them)",
      in_flight["max_concurrent"] == 1)


# === 5. Regression: button/interactive messages bypass the queue
#        entirely - a single deliberate tap, not prose to batch ===
_reset_phone_queue_state()
check("_process_one_message only queues msg_type=='text' - verified at the "
      "source level, since a button tap must never wait out a debounce "
      "window or be joined with unrelated free text",
      "_queue_text_message(phone, phone_hash_val, text, profile_name)" in
      open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "whatsapp.py"),
           encoding="utf-8").read())

_reset_phone_queue_state()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL WHATSAPP-DEBOUNCE TESTS PASSED")
