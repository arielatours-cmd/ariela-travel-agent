"""QA for run-11 B (Valencia, 22.10, transcript from Shaked via Bezalel):
Ariella: "...סגרנו את פרטי הטיסה. רוצה שאמשיך גם לתכנון מסלול יומי לוולנסיה?"
customer: "לא" -> trip_planning declined (correct) AND lodging declined (never
asked); the next offer skipped straight to the car.

Root cause: the guard on the extractor's service_decisions only rolled back
an unproven wanted=false; a session_status "declined" written by the
extractor itself went straight through _merge_trip_state. Now a domain that
was pending becomes declined only together with a decline decision for it.

Offline, end to end (ariella_turn, model calls stubbed). Run:
python3 tools/qa_run11_status_decline_guard.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
import database; database.init_db()
import ariella_chat_clean as chat, whatsapp_bridge
from werkzeug.security import generate_password_hash
T="מבדיקה ראשונית, אין מסלול טיסה ישירה מאומת לוולנסיה. סגרנו את פרטי הטיסה. רוצה שאמשיך גם לתכנון מסלול יומי לוולנסיה?"
BASE={"destination":{"places":["ולנסיה"],"mode":"specific","status":"known"},"travelers":{"adults":2,"infants":1},
 "dates":{"departure":"2027-05-01","return":"2027-05-05","needs_confirmation":False},"departure_airport":"TLV",
 "flight":{"baggage":["checked_bag"],"connection_preference":"direct"},"budget_per_person":{"amount":1500,"currency":"ILS"},
 "requested_services":["flights"],"service_decisions":{"flights":{"wanted":True}},
 "session_status":{"car":"pending","flights":"active","lodging":"pending","trip_planning":"pending"},"active_session":"flights",
 "guided":{"current_question":None,"attempts":0,"answered":["dates","travelers","baggage","accessibility"]},
 "accessibility":{"needed":False}}
FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def run(mode):
    def fake(key, model, ss, sd, history, message, mt, include_history=True, source="other"):
        if source=="state_extractor":
            tu={}
            if mode=="decisions": tu={"service_decisions":{"trip_planning":{"wanted":False},"lodging":{"wanted":False}}}
            if mode=="status": tu={"session_status":{"trip_planning":"declined","lodging":"declined"}}
            if mode=="both": tu={"service_decisions":{"trip_planning":{"wanted":False},"lodging":{"wanted":False}},"session_status":{"trip_planning":"declined","lodging":"declined"}}
            return json.dumps({"restart_request":False,"trip_update":tu})
        if source=="guided_extract": return json.dumps({"status":"other_topic"})
        if source=="classifier": return '{"trip_planning": false}'
        return "תשובה."
    with sqlite3.connect(database.DB_PATH) as c:
        c.execute("DELETE FROM members WHERE email=?", (f"b-{mode}@x.com",))
        cur=c.execute("INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) VALUES(?,?,?,?,?,?,?)",("B",f"b-{mode}@x.com",generate_password_hash("x"),datetime.now(timezone.utc).isoformat(),"active",0,"[]"))
        m=cur.lastrowid
    database.save_ariella_conversation(m,[{"role":"user","content":"עדיף ישירה"},{"role":"assistant","content":T}],json.loads(json.dumps(BASE)))
    with patch.object(chat,"_post_claude",side_effect=fake):
        whatsapp_bridge.ariella_turn(m,"לא")
    st=(database.load_ariella_conversation(m) or {}).get("trip_state") or {}
    return st


for mode, label in (("none", "the extractor wrote nothing"), ("decisions", "the extractor wrote unproven decisions"),
                    ("status", "the extractor wrote session_status declined directly (the run-11 path)"),
                    ("both", "the extractor wrote both")):
    st = run(mode)
    ss = st.get("session_status") or {}
    check(f"{label}: the route is declined (it was the question asked)", ss.get("trip_planning") == "declined")
    check(f"{label}: lodging stays pending (never asked)", ss.get("lodging") == "pending")
    check(f"{label}: the next offer is lodging, not a jump to the car", st.get("post_flight_offer") == ["lodging"])

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
