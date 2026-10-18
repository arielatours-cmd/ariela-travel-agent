"""QA for task 003b - "הסר" / "עצור" in free text stop WhatsApp messages
(product/dev-tasks/003b-whatsapp-stop-keywords.md, ofek branch; Din WA-2).

Covers the spec's 7 checks for Shaked, plus the details around them:
  1. "הסר" from a member with deals + alerts -> both off, confirmation with
     both parts
  2. "STOP" / "עצור!" -> same as 1
  3. "תעצרי רגע, אני רוצה לשנות תאריך" -> not a stop, normal routing
  4. "הסר" from an unknown number -> "nothing to remove", no DB change
     (a KNOWN member with nothing active gets the flag + confirmation, Din)
  5. "הסר" in the middle of onboarding -> the stop wins over the state
  6. after "הסר", "שלום" -> Ariella answers as usual
  7. the "הפסקת הדילים" button -> stops deals only, as before

Offline, temp DB, the Claude conversation is stubbed.
Run: python3 tools/qa_whatsapp_stop_keywords.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="ariella-qa-wa-stop-")
os.environ.update({"DB_PATH": os.path.join(_TMP, "qa.db"), "SCHEDULER_ENABLED": "false",
                   "SCANNER_ENABLED": "false"})
for key in ("SERPAPI_API_KEY", "ANTHROPIC_API_KEY", "WHATSAPP_ACCESS_TOKEN"):
    os.environ.pop(key, None)

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import database  # noqa: E402
import nova_conversation as nc  # noqa: E402
from database import connection  # noqa: E402

database.init_db()
ROUTED = "__NORMAL_CONVERSATION__"
routed_texts = []


def fake_route_member(member_id, text):
    routed_texts.append(text)
    return ROUTED


nc._route_member = fake_route_member  # the Claude conversation, stubbed

HEAD = "הוסרתם בהצלחה ✅ לא נשלח לכם יותר הודעות יזומות בוואטסאפ (דילים, התראות ועדכוני חופשה). אפשר עדיין לכתוב לי כאן בכל זמן."
BOTH = HEAD + f"\nלחידוש הדילים: {nc._DEALS_URL} · להפעלת התראות לחופשה: מהאזור האישי באתר."
DEALS_ONLY = HEAD + f"\nלחידוש הדילים: {nc._DEALS_URL}"
ALERTS_ONLY = HEAD + "\nלהפעלת התראות לחופשה: מהאזור האישי באתר."
NONE_ACTIVE = HEAD
NOTHING = ("אין כרגע הודעות יזומות פעילות במספר הזה, אז אין מה להסיר 🙂 "
           f"אם נרשמתם עם מספר אחר, אפשר להפסיק מעמוד הדילים באתר: {nc._DEALS_URL}")

_seq = [0]


def make_member(deals, alerts, link=True):
    _seq[0] += 1
    phone = f"+9725022{_seq[0]:05d}"
    with connection() as conn:
        mid = int(conn.execute(
            "INSERT INTO members (full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES('QA',?,?,'x',datetime('now'),'active',0,'[]')", (f"qa{_seq[0]}@example.com", phone)).lastrowid)
        for notify in (alerts, False):  # one trip with alerts (if asked) + one without
            conn.execute(
                "INSERT INTO trip_requests (member_id,request_name,travel_window,status,answers_json,created_at,mobile_notifications) "
                "VALUES(?,?,?,?,?,datetime('now'),?)", (mid, "QA", "", "active", "{}", 1 if notify else 0))
    if deals:
        database.set_whatsapp_deals_opt(mid, True, "payment")
    if link:
        nc.ensure_whatsapp_link(mid, phone)
    return mid, phone


def state(mid):
    with connection() as conn:
        deals = bool(conn.execute("SELECT whatsapp_opt_in FROM members WHERE id=?", (mid,)).fetchone()[0])
        alerts = conn.execute("SELECT COUNT(*) FROM trip_requests WHERE member_id=? AND mobile_notifications=1", (mid,)).fetchone()[0]
        events = [dict(r) for r in conn.execute(
            "SELECT event, source, detail FROM whatsapp_opt_events WHERE member_id=? ORDER BY id", (mid,)).fetchall()]
        linked = conn.execute("SELECT COUNT(*) FROM whatsapp_member_links WHERE member_id=? AND status='active'", (mid,)).fetchone()[0]
    return deals, alerts, events, linked


def proactive_off(mid):
    with connection() as conn:
        return conn.execute("SELECT whatsapp_proactive_off FROM members WHERE id=?", (mid,)).fetchone()[0]


def db_snapshot():
    with connection() as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("members", "trip_requests", "whatsapp_opt_events", "whatsapp_member_links"))


# --- 1. "הסר" with deals + alerts -> both off, both parts in the reply ---------------
mid, phone = make_member(deals=True, alerts=True)
reply = nc.route_inbound(phone, "הסר")
deals, alerts, events, linked = state(mid)
check("1: deals off", not deals)
check("1: alerts off on every trip (mobile_notifications=0)", alerts == 0)
check("1: confirmation with both parts, exact text", reply == BOTH)
check("1: opt-out event source='keyword' with the word", {"event": "opt_out", "source": "keyword", "detail": "הסר"} in events)
check("1: alerts-off event recorded too", {"event": "alerts_off", "source": "keyword", "detail": "הסר"} in events)
check("1: the WhatsApp link is untouched", linked == 1)
check("1: not passed to the conversation", ROUTED != reply)
check("1: whatsapp_proactive_off=1", proactive_off(mid) == 1)

# --- 2. "STOP" / "עצור!" and the rest of the list ----------------------------------------
for word, expected_word in (("STOP", "stop"), ("עצור!", "עצור"), ("  הסירו אותי 🙏", "הסירו אותי"), ("Unsubscribe.", "unsubscribe"),
                            ("remove", "remove"), ("הפסיקו!!", "הפסיקו"), ("הפסק", "הפסק"), ("עצרו", "עצרו"),
                            ("הסר אותי", "הסר אותי"), ("הסירו", "הסירו"), ("🛑 stop", "stop")):
    mid, phone = make_member(deals=True, alerts=True)
    reply = nc.route_inbound(phone, word)
    deals, alerts, events, _ = state(mid)
    check(f"2: {word!r} -> deals + alerts off, same confirmation", not deals and alerts == 0 and reply == BOTH)
    check(f"2: {word!r} -> logged with the normalized word {expected_word!r}",
          {"event": "opt_out", "source": "keyword", "detail": expected_word} in events)

# only one of the two active -> the other part is dropped from the reply
mid, phone = make_member(deals=True, alerts=False)
check("deals only -> reply mentions deals only", nc.route_inbound(phone, "הסר") == DEALS_ONLY and not state(mid)[0])
mid, phone = make_member(deals=False, alerts=True)
reply = nc.route_inbound(phone, "הסר")
check("alerts only -> reply mentions alerts only, alerts off", reply == ALERTS_ONLY and state(mid)[1] == 0)
check("alerts only -> no deals opt-out event", all(e["event"] != "opt_out" for e in state(mid)[2]))

# --- 3. A stop word inside a sentence -> not a stop ---------------------------------------
mid, phone = make_member(deals=True, alerts=True)
for text in ("תעצרי רגע, אני רוצה לשנות תאריך", "אל תעצור את החיפוש", "הסר את המזוודה מהחיפוש", "stop over באתונה?"):
    before = len(routed_texts)
    reply = nc.route_inbound(phone, text)
    check(f"3: {text!r} -> normal routing", reply == ROUTED and routed_texts[before:] == [text])
deals, alerts, events, _ = state(mid)
check("3: nothing stopped", deals and alerts == 1 and all(e["source"] != "keyword" for e in events))

# --- 4. Unknown number -> "nothing to remove", no DB change ---------------------------------
snap = db_snapshot()
reply = nc.route_inbound("+972509999999", "הסר")
check("4: unknown number -> 'nothing to remove' message", reply == NOTHING)
check("4: unknown number -> no DB change", db_snapshot() == snap)
# Din 16.10: a KNOWN member with nothing active still gets the stop flag and
# the confirmation - "nothing to remove" is only for an unknown number.
mid, phone = make_member(deals=False, alerts=False)
reply = nc.route_inbound(phone, "stop")
check("Din: known member with nothing active -> confirmation, not 'nothing to remove'", reply == NONE_ACTIVE)
check("Din: ...and whatsapp_proactive_off=1", proactive_off(mid) == 1)
check("Din: ...recorded as proactive_off/keyword with the word",
      {"event": "proactive_off", "source": "keyword", "detail": "stop"} in state(mid)[2])

# --- 5. "הסר" in the middle of onboarding -> the stop wins ---------------------------------
onboarding_phone = "+972508888888"
first = nc.route_inbound(onboarding_phone, "שלום")
check("5: setup - onboarding started", bool(nc._onboarding_get(onboarding_phone)))
reply = nc.route_inbound(onboarding_phone, "הסר")
check("5: stop word during onboarding -> stop reply, not the next onboarding step", reply == NOTHING and reply != first)
# a linked member in the middle of a conversation state
mid, phone = make_member(deals=True, alerts=True)
nc._set_state(mid, "awaiting_feedback_comment:1:2099-01-01T00:00:00+00:00")
check("5: stop word overrides a member's conversation state", nc.route_inbound(phone, "הסר") == BOTH)

# --- 6. After "הסר", "שלום" -> Ariella answers as usual -------------------------------------
before = len(routed_texts)
reply = nc.route_inbound(phone, "שלום")
check("6: after the stop, 'שלום' reaches Ariella as usual", reply == ROUTED and routed_texts[before:] == ["שלום"])
check("6: the link is still active after the stop", state(mid)[3] == 1)

# --- 7. The button stops deals only, as before ----------------------------------------------
mid, phone = make_member(deals=True, alerts=True)
reply = nc.route_inbound(phone, "", button_payload="STOP_HOT_DEALS")
deals, alerts, events, _ = state(mid)
check("7: button -> deals off", not deals and "הפסקנו לשלוח לכם את הדילים החמים" in reply)
check("7: button -> alerts untouched", alerts == 1)
check("7: button -> source whatsapp_button, no detail",
      events[-1] == {"event": "opt_out", "source": "whatsapp_button", "detail": None})

# --- Din 16.10 (s.30A(d)): after "הסר" no proactive message of ANY kind is queued --------
import trip_lifecycle_messages as tlm  # noqa: E402
import whatsapp_deals_messages as wdm  # noqa: E402
from datetime import date, timedelta  # noqa: E402


def queued(mid):
    with connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM whatsapp_outbound_queue WHERE member_id=?", (mid,)).fetchone()[0]


def booked_trip(mid, return_days_ago):
    ret = (date.today() - timedelta(days=return_days_ago)).isoformat()
    dep = (date.today() - timedelta(days=return_days_ago + 5)).isoformat()
    with connection() as conn:
        return int(conn.execute(
            "INSERT INTO trip_requests (member_id,request_name,travel_window,status,answers_json,created_at,mobile_notifications,booked_confirmed_at) "
            "VALUES(?,?,?,?,?,datetime('now'),0,datetime('now'))",
            (mid, "אתונה", "", "active", '{"departure_date": "%s", "return_date": "%s"}' % (dep, ret))).lastrowid)


mid, phone = make_member(deals=True, alerts=True)
congrats_trip, how_trip = booked_trip(mid, -10), booked_trip(mid, 5)
nc.route_inbound(phone, "הסר")
before = queued(mid)
check("Din: after 'הסר', queue_booking_congrats queues nothing", tlm.queue_booking_congrats(congrats_trip) is None and queued(mid) == before)
tlm.queue_how_was_it_messages()
check("Din: after 'הסר', queue_how_was_it_messages queues nothing for this member", queued(mid) == before)
# Din: a message already queued (preview) before the "הסר" is cancelled, not deleted
mid_q, phone_q = make_member(deals=True, alerts=True)
pre_trip = booked_trip(mid_q, -10)
pre_id = tlm.queue_booking_congrats(pre_trip)
other_id = database.queue_whatsapp_message(make_member(True, True)[0], "radar", "other member")
nc.route_inbound(phone_q, "הסר")
with connection() as conn:
    pre_status = conn.execute("SELECT status FROM whatsapp_outbound_queue WHERE id=?", (pre_id,)).fetchone()
    other_status = conn.execute("SELECT status FROM whatsapp_outbound_queue WHERE id=?", (other_id,)).fetchone()[0]
    left_preview = conn.execute("SELECT COUNT(*) FROM whatsapp_outbound_queue WHERE member_id=? AND status='preview'", (mid_q,)).fetchone()[0]
check("Din: queued booking_congrats (preview) -> status 'cancelled' after 'הסר', row kept",
      pre_id is not None and pre_status is not None and pre_status[0] == "cancelled")
check("Din: no 'preview' rows left for that member", left_preview == 0)
check("Din: another member's queued message stays 'preview'", other_status == "preview")
src = open(os.path.join(os.path.dirname(__file__), "..", "database.py"), encoding="utf-8").read()
check("Din WA-6 comment sits right above queue_whatsapp_message",
      "# Din WA-6: any real sender MUST re-check members.whatsapp_proactive_off / opt-in immediately before each send.\ndef queue_whatsapp_message(" in src)

control, _ = make_member(deals=True, alerts=True)
c_congrats, c_how = booked_trip(control, -10), booked_trip(control, 5)
c_before = queued(control)
check("control (no stop): queue_booking_congrats does queue", tlm.queue_booking_congrats(c_congrats) is not None)
tlm.queue_how_was_it_messages()
check("control (no stop): how-was-it queued too", queued(control) == c_before + 2)
check("Din: direct queue_whatsapp_message returns None (radar/deals/any future sender)",
      database.queue_whatsapp_message(mid, "radar", "x") is None and queued(mid) == before)
check("Din: a different member is not affected", database.queue_whatsapp_message(make_member(True, True)[0], "radar", "x") is not None)

# Lifted ONLY by an explicit customer action
import app as app_module  # noqa: E402
client = app_module.app.test_client()
with client.session_transaction() as sess:
    sess["member_id"] = mid
with connection() as conn:
    trip_off = conn.execute("SELECT id FROM trip_requests WHERE member_id=? AND mobile_notifications=0 AND booked_confirmed_at IS NULL LIMIT 1", (mid,)).fetchone()[0]
nc.route_inbound(phone, "שלום")
check("still off after an ordinary message", proactive_off(mid) == 1)
client.post(f"/trip/{trip_off}/toggle-notifications")
check("turning a trip's alerts ON in the account lifts the stop", proactive_off(mid) == 0)
check("...and messages queue again", database.queue_whatsapp_message(mid, "radar", "x") is not None)
nc.route_inbound(phone, "הסר")
client.post(f"/trip/{trip_off}/toggle-notifications")  # already 0 after the stop -> turns ON again
check("toggle alerts on again -> lifted", proactive_off(mid) == 0)
nc.route_inbound(phone, "הסר")
check("turning alerts OFF never lifts it", proactive_off(mid) == 1)
wdm.on_whatsapp_deals_paid(mid)
check("re-joining the deals (payment) lifts the stop and queues the welcome",
      proactive_off(mid) == 0 and queued(mid) > before)
nc.route_inbound(phone, "הסר")
database.set_whatsapp_deals_opt(mid, False, "site")
check("an opt-OUT never lifts it", proactive_off(mid) == 1)

# --- The word list and normalizer ---------------------------------------------------------------
REQUIRED = ["הסר", "הסירו", "הסירו אותי", "הסר אותי", "עצור", "עצרו", "הפסק", "הפסיקו", "stop", "unsubscribe", "remove"]
check("all 11 spec words are in STOP_KEYWORDS", set(REQUIRED) == set(nc.STOP_KEYWORDS))
check("normalizer: inner spaces collapsed", nc._stop_keyword("הסירו   אותי") == "הסירו אותי")
check("normalizer: empty / None -> no stop", nc._stop_keyword("") is None and nc._stop_keyword(None) is None)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
