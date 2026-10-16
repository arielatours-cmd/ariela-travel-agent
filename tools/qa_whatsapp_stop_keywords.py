"""QA for the free-text WhatsApp stop words (Din WA-2, anti-spam law),
replacing the 8.10 "button only" decision.

  - a member active for hot deals who writes הסר / עצור / הסירו אותי /
    stop / unsubscribe -> stopped exactly like the STOP_HOT_DEALS button
    (same _handle_stop, same reply), no "stop what?" question
  - a member NOT active for deals who writes the same word -> not
    intercepted at all, the normal conversation continues, no stop message
  - an active member writing anything else (incl. a stop word inside a
    sentence) -> untouched
  - the button keeps working as before

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


def make_member(email, phone, opt_in):
    with connection() as conn:
        mid = int(conn.execute(
            "INSERT INTO members (full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES('QA',?,?,'x',datetime('now'),'active',0,'[]')", (email, phone)).lastrowid)
    if opt_in:
        database.set_whatsapp_deals_opt(mid, True, "payment")
    nc.ensure_whatsapp_link(mid, phone)
    return mid


def opt_in(mid):
    with connection() as conn:
        return bool(conn.execute("SELECT whatsapp_opt_in FROM members WHERE id=?", (mid,)).fetchone()[0])


def last_event(mid):
    with connection() as conn:
        row = conn.execute("SELECT event, source FROM whatsapp_opt_events WHERE member_id=? ORDER BY id DESC LIMIT 1", (mid,)).fetchone()
    return dict(row) if row else {}


ACTIVE_PHONE = "+972501110001"
active = make_member("qa-active@example.com", ACTIVE_PHONE, True)
check("setup: active member is opted in and linked", opt_in(active) and nc.linked_member_for_phone(ACTIVE_PHONE) == active)

# The button's reply, as the reference for "exactly like the button".
button_reply = nc.route_inbound(ACTIVE_PHONE, "", button_payload="STOP_HOT_DEALS")
check("button still stops (unchanged)", not opt_in(active) and "הפסקנו לשלוח לכם את הדילים החמים" in button_reply)
check("button event source stays whatsapp_button", last_event(active) == {"event": "opt_out", "source": "whatsapp_button"})

# --- 1. Active member + each required stop word -> stopped like the button ---------
REQUIRED = ["הסר", "עצור", "הסירו אותי", "stop", "unsubscribe"]
VARIANTS = ["STOP", " Stop ", "עצור!", "הסר.", "Unsubscribe", "הסר אותי", "הסירו", "עצרו"]
for word in REQUIRED + VARIANTS:
    database.set_whatsapp_deals_opt(active, True, "payment")
    before = len(routed_texts)
    reply = nc.route_inbound(ACTIVE_PHONE, word)
    check(f"active + {word!r} -> stopped", not opt_in(active))
    check(f"active + {word!r} -> same reply as the button", reply == button_reply)
    check(f"active + {word!r} -> not passed to the conversation", len(routed_texts) == before)
    check(f"active + {word!r} -> opt-out recorded (source whatsapp_keyword)",
          last_event(active) == {"event": "opt_out", "source": "whatsapp_keyword"})

# --- 2. Active member writing something else -> untouched ---------------------------
database.set_whatsapp_deals_opt(active, True, "payment")
for text in ("אל תעצור את החיפוש", "מה עם הטיסה לאתונה?", "stop over באתונה זה אפשרי?", "הסר את המזוודה מהחיפוש", "שלום"):
    before = len(routed_texts)
    reply = nc.route_inbound(ACTIVE_PHONE, text)
    check(f"active + {text!r} -> normal conversation", reply == ROUTED and routed_texts[before:] == [text])
    check(f"active + {text!r} -> still opted in", opt_in(active))

# --- 3. Member NOT active for deals -> the word is ordinary conversation ------------
INACTIVE_PHONE = "+972501110002"
inactive = make_member("qa-inactive@example.com", INACTIVE_PHONE, False)
for word in REQUIRED:
    before = len(routed_texts)
    reply = nc.route_inbound(INACTIVE_PHONE, word)
    check(f"not active + {word!r} -> normal conversation continues", reply == ROUTED and routed_texts[before:] == [word])
    check(f"not active + {word!r} -> no stop message at all",
          "הדילים החמים כבר לא נשלחים" not in reply and "הפסקנו לשלוח" not in reply)
check("not active: no opt events written", last_event(inactive) == {})

# previously active, already stopped -> the word is not intercepted either
database.set_whatsapp_deals_opt(active, False, "whatsapp_button")
before = len(routed_texts)
reply = nc.route_inbound(ACTIVE_PHONE, "עצור")
check("already stopped + 'עצור' -> normal conversation, no 'already stopped' message",
      reply == ROUTED and routed_texts[before:] == ["עצור"])

# --- 4. Unknown phone (no member) -> not intercepted, onboarding as before ----------
reply = nc.route_inbound("+972501119999", "stop")
check("unknown phone + 'stop' -> no stop message (onboarding as before)",
      "לא מצאנו שירות דילים פעיל" not in reply and "הפסקנו לשלוח" not in reply)

# --- 5. Keyword matcher itself --------------------------------------------------------
check("matcher: whole message only", nc._is_stop_keyword("עצור") and not nc._is_stop_keyword("עצור את זה"))
check("matcher: empty -> no", not nc._is_stop_keyword("") and not nc._is_stop_keyword(None))
check("required words are all in the list", all(nc._is_stop_keyword(w) for w in REQUIRED))

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
