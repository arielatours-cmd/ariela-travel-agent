"""QA for dry-run 1 (22.10, Shaked via Bezalel; report qa/reports/2026-10-22-dryrun1.md
on the shaked branch, raw logs on qa-dryrun) on oholiav-run11-mixed-baggage:

1. B (Valencia): "לי ולאשתי מזוודה, לתינוק מספיק תיק קטן" - the general extractor
   already resolved it to ONE type (['checked_bag']), so the safety net ("2+ types")
   never ran. Now any baggage written outside the guided extraction gets the model
   check (guided_extract decides mixed_per_passenger).
2. C/E: the accessibility clarification went out alone, without the question.
3. E (Rovinj -> Pula): the chosen nearby airport wasn't saved and the summary had
   no landing line.
4. C: "נוסעות: 2 ..." + an appended second "נוסעים: 2 מבוגרים" line. Per Shaked/Shlomo:
   found only by the fixed label "נוסעים:", replaced by the canonical line from
   state (now with children + infants); no label -> added.
5. E: "התקציב כבר ידוע לי" right after the budget was given for the first time.

Hints / state only - no regex on the output. Offline. Run:
python3 tools/qa_dryrun1_fixes.py
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

import database  # noqa: E402
database.init_db()

import ariella_chat_clean as chat  # noqa: E402
import whatsapp_bridge  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def member(email):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        return conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA", email, generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        ).lastrowid


BASE = {
    "destination": {"places": ["ולנסיה"], "mode": "specific", "status": "known"},
    "travelers": {"adults": 2, "infants": 1},
    "dates": {"departure": "2027-06-12", "return": "2027-06-17", "needs_confirmation": False},
    "departure_airport": "TLV",
    "requested_services": ["flights"], "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]},
}


def turn(email, state, history, message, extractor_update, guided_results, extra=None):
    seen = {}
    m = member(email)
    database.save_ariella_conversation(m, history, json.loads(json.dumps(state)))

    def fake(key, model, ss, sd, hist, msg, mt, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps(dict({"restart_request": False, "trip_update": extractor_update}, **(extra or {})), ensure_ascii=False)
        if source == "tinkerbell_reply":
            seen.setdefault("dyn", []).append(sd)
            return "תשובה."
        return "{}"

    def fake_guided(key, model, field, message, history, s, guided_steps=None):
        return guided_results.get(field, {"status": "other_topic", "confidence": "low", "also_mentioned": {}, "correction": None})

    with patch.object(chat, "_post_claude", side_effect=fake), \
            patch.object(chat, "_guided_extract_answer", side_effect=fake_guided), \
            patch.object(chat, "_guided_redirect_field", return_value=None):
        whatsapp_bridge.ariella_turn(m, message)
    return (database.load_ariella_conversation(m) or {}).get("trip_state") or {}, "\n".join(seen.get("dyn") or [])


MIXED = {"status": "answered", "mixed_per_passenger": True, "confidence": "high", "also_mentioned": {}, "correction": None}
SINGLE = {"status": "answered", "mixed_per_passenger": False, "items": [{"type": "checked_bag", "count": None}],
          "confidence": "high", "also_mentioned": {}, "correction": None}
HIST_BAG = [{"role": "user", "content": "עד 1500 שקל לאדם"},
            {"role": "assistant", "content": "לגבי הכבודה - איזו כבודה תצטרכו לקחת?"}]

# --- 1. B: the extractor resolved the mixed message to ONE type ----------------------------------
st, dyn = turn("qa-dr1-b@example.com", BASE, HIST_BAG, "לי ולאשתי מזוודה, לתינוק מספיק תיק קטן",
               {"flight": {"baggage": ["checked_bag"]}}, {"baggage": MIXED})
g = st.get("guided") or {}
check("B: the single type the extractor wrote is NOT saved", not (st.get("flight") or {}).get("baggage"))
check("B: pending + baggage is the live question", g.get("mixed_baggage_pending") is True and g.get("current_question") == "baggage")
check("B: this turn's reply gets the payment-page explanation + yes/no", "בעמוד התשלום" in dyn)
st, dyn = turn("qa-dr1-b-plain@example.com", BASE, HIST_BAG, "מזוודה לכולנו",
               {"flight": {"baggage": ["checked_bag"]}}, {"baggage": SINGLE})
check("a plain uniform answer written by the extractor is kept (model: not mixed)",
      (st.get("flight") or {}).get("baggage") == ["checked_bag"] and "בעמוד התשלום" not in dyn)

# --- 2. accessibility clarification never on its own ----------------------------------------------
acc = chat._accessibility_ask_hint(False, 0)
check("accessibility hint: the clarification is part of the question, never a separate sentence",
      "לעולם לא משפט נפרד" in acc and "אל תכתבי את ההבהרה בכלל" in acc)

# --- 3. Rovinj -> Pula --------------------------------------------------------------------------------
check("EXTRACTOR_SYSTEM: a nearby airport the customer accepted is written to destination_airports",
      "הציעה ללקוח שדה תעופה קרוב מסוים" in chat.EXTRACTOR_SYSTEM)
ROV = dict(BASE, destination={"places": ["רוביני"], "mode": "specific", "status": "known"})
st, _ = turn("qa-dr1-e-puy@example.com", ROV,
             [{"role": "assistant", "content": "לרוביני אין שדה תעופה משלה, השדה הקרוב ביותר הוא פולה. נוח לך לטוס דרכו?"}],
             "פולה מתאים לנו", {"destination_airports": ["PUY"]}, {}, extra={"destination_evidence": "פולה מתאים לנו"})
check("E: the chosen nearby airport (PUY, not in our list) stays in state", st.get("destination_airports") == ["PUY"])
gw = chat._destination_gateway_summary({"destination": {"places": ["רוביני"]}, "destination_airports": ["PUY"]})
check("E: the reply is told the chosen code for the 'נחיתה:' line", "PUY" in gw and "נחיתה:" in gw)
fb = chat._final_summary_fallback_text(dict(ROV, destination_airports=["PUY"]))
check("E: the fallback summary carries a landing line", "נחיתה: PUY" in fb)
fb2 = chat._final_summary_fallback_text(dict(BASE, destination_airports=["VLC"]))
check("fallback landing line uses the catalog's verified name when there is one", "נחיתה: ולנסיה (VLC), ספרד" in fb2)

# --- 4. travelers line ---------------------------------------------------------------------------------
summary_state = {"travelers": {"adults": 2}, "flight": {"baggage": ["personal_item"], "connection_preference": "אין העדפה"},
                 "budget_per_person": {"amount": 1300, "currency": "ILS"},
                 "dates": {"departure": "2027-04-20", "return": "2027-04-25"}}
reply = ("הנה הסיכום:\nתאריכים: 20.04.2027 – 25.04.2027\nנוסעות: 2 (את ואמא שלך)\n"
         "כבודה: תיק יד לכל נוסע (בהתאם לתנאי חברת התעופה)\nהעדפת טיסה: אין העדפה לטיסה ישירה\n"
         "תקציב: עד 1,300 ש\"ח לאדם\nאם כל הפרטים נכונים, כתבי מאשרת.")
out = chat._ensure_flight_summary_completeness(reply, summary_state)
check("C: an unlabelled 'נוסעות: 2 ...' is never chosen for replacement (no word list on the model's text)",
      "נוסעות: 2 (את ואמא שלך)" in out)
labelled = reply.replace("נוסעות: 2 (את ואמא שלך)", "נוסעים: 2 (את ואמא שלך)")
out = chat._ensure_flight_summary_completeness(labelled, summary_state)
check("C: the 'נוסעים:' line is found by its label and rebuilt from state - exactly once",
      out.count("נוסעים:") == 1 and "נוסעים: 2 מבוגרים\n" in out and "את ואמא שלך" not in out)
b_state = dict(summary_state, travelers={"adults": 2, "infants": 1})
out = chat._ensure_flight_summary_completeness(labelled.replace("נוסעים: 2 (את ואמא שלך)", "נוסעים: 3 (2 מבוגרים ותינוק בן שנה)"), b_state)
check("B: the canonical line keeps the infant ('2 מבוגרים ותינוק' doesn't disappear)",
      "נוסעים: 2 מבוגרים ותינוק" in out and out.count("נוסעים:") == 1)
out = chat._ensure_flight_summary_completeness(reply.replace("נוסעות: 2 (את ואמא שלך)\n", ""), summary_state)
check("no 'נוסעים:' label -> the canonical line is added", "נוסעים: 2 מבוגרים" in out)
check("_flight_travelers_line: children and infants", chat._flight_travelers_line({"adults": 2, "children": 2, "infants": 1})
      == "נוסעים: 2 מבוגרים, 2 ילדים ותינוק" and chat._flight_travelers_line({"adults": 2, "children": 2}) == "נוסעים: 2 מבוגרים ו-2 ילדים")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ariella_chat_clean.py"), encoding="utf-8").read()
check("the 'נוסעות' word check is gone", '"נוסעות" not in text' not in src)
check("TINKERBELL_SYSTEM: the travelers line has the fixed 'נוסעים:' label", 'בתווית הקבועה "נוסעים:"' in chat.TINKERBELL_SYSTEM)

# --- 5. budget given for the first time ---------------------------------------------------------------
B5 = dict(BASE, guided={"current_question": None, "attempts": 0, "answered": ["dates", "travelers", "accessibility", "baggage"]},
          accessibility={"needed": False}, flight={"baggage": ["carry_on_only"]})
st, dyn = turn("qa-dr1-budget@example.com", B5,
               [{"role": "assistant", "content": "מה התקציב שלכם לאדם לטיסה?"}],
               "עד 1100 שקל לאחת", {"budget_per_person": {"amount": 1100, "currency": "ILS", "status": "known"}}, {})
check("E: budget given now for the first time -> 'never as if already known' hint", "כבר ידוע לי" in dyn and "לראשונה" in dyn)
check("...the one-turn key isn't kept on a later turn's prompt",
      "לראשונה" not in turn("qa-dr1-budget2@example.com", dict(B5, budget_per_person={"amount": 1100, "currency": "ILS", "status": "known"}),
                            [{"role": "assistant", "content": "חשוב לכם שהטיסה תהיה ישירה?"}], "לא חובה", {}, {})[1])

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
