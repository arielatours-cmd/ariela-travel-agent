"""QA for task 011a - Haifa (Air Haifa) destination list + route check.

Per product/dev-tasks/011a-hfa-airhaifa-routes.md (ofek branch). The four
spec cases, through the real pieces the chat uses (deterministic departure
parse -> hfa_route_check -> the departure fact handed to the model -> the
start-search guard), plus the data file and the admin page.

Offline - no SerpAPI / Claude / WhatsApp calls.
Run: python3 tools/qa_hfa_routes_011a.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="ariella-qa-011a-")
os.environ.update({"DB_PATH": os.path.join(_TMP, "qa.db"), "SCHEDULER_ENABLED": "false",
                   "SCANNER_ENABLED": "false", "ADMIN_TOKEN": "qa-token"})
for key in ("SERPAPI_API_KEY", "ANTHROPIC_API_KEY", "WHATSAPP_ACCESS_TOKEN"):
    os.environ.pop(key, None)

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import app as app_module  # noqa: E402
import ariella_chat_clean as chat  # noqa: E402
from hfa_routes import hfa_route_check, load_routes, matching_routes  # noqa: E402
from database import connection  # noqa: E402

# --- Data file -------------------------------------------------------------------
routes = load_routes()
codes = [r["iata"] for r in routes]
check("data/hfa_routes.json: the 9 spec destinations + SKG (added 16.10)",
      sorted(codes) == sorted(["ETM", "LCA", "ATH", "SKG", "PFO", "RHO", "HER", "JMK", "AOK", "SOF"]))
required = {"iata", "city_he", "city_en", "country_he", "carrier", "domestic", "seasonal", "status", "source", "verified_at"}
check("every route has all the spec fields", all(required <= set(r) for r in routes))
check("carrier is E2 everywhere", all(r["carrier"] == "E2" for r in routes))
check("statuses are only confirmed / to_verify / suspended / not_served",
      all(r["status"] in {"confirmed", "to_verify", "suspended", "not_served"} for r in routes))
by = {r["iata"]: r for r in routes}
check("owner-verified 16.10: ETM, LCA, ATH, SKG, PFO, RHO, HER, SOF confirmed",
      sorted(c for c, r in by.items() if r["status"] == "confirmed") == sorted(["ETM", "LCA", "ATH", "SKG", "PFO", "RHO", "HER", "SOF"]))
check("JMK and AOK are not_served", by["JMK"]["status"] == "not_served" and by["AOK"]["status"] == "not_served")
check("SKG fields as given", by["SKG"]["city_he"] == "סלוניקי" and by["SKG"]["city_en"] == "Thessaloniki"
      and by["SKG"]["country_he"] == "יוון" and by["SKG"]["carrier"] == "E2" and not by["SKG"]["domestic"] and not by["SKG"]["seasonal"])
check("seasonal: RHO, HER, JMK, AOK", sorted(c for c, r in by.items() if r["seasonal"]) == ["AOK", "HER", "JMK", "RHO"])
check("every route verified_at 2026-10-16 by the owner against airhaifa.com",
      all(r["verified_at"] == "2026-10-16" and r["source"] == 'אומת ע"י בעלת העסק מול airhaifa.com' for r in routes))
check("synonyms: כרתים -> HER", [r["iata"] for r in matching_routes("כרתים")] == ["HER"])
check("synonyms: קפריסין -> LCA + PFO", sorted(r["iata"] for r in matching_routes("קפריסין")) == ["LCA", "PFO"])
check("synonyms: יוון / greece -> exactly ATH, SKG, RHO, HER",
      sorted(r["iata"] for r in matching_routes("יוון")) == ["ATH", "HER", "RHO", "SKG"]
      and sorted(r["iata"] for r in matching_routes("greece")) == ["ATH", "HER", "RHO", "SKG"])
check("synonyms: סלוניקי / תסלוניקי -> SKG", hfa_route_check("סלוניקי") == "served" and hfa_route_check("תסלוניקי") == "served")
check("Mykonos / Karpathos -> not_served", hfa_route_check("מיקונוס") == "not_served" and hfa_route_check("קרפתוס") == "not_served")

# --- hfa_route_check --------------------------------------------------------------
check("Athens -> served", hfa_route_check("אתונה") == "served" and hfa_route_check("ATH") == "served")
check("Rome -> not_served", hfa_route_check("רומא") == "not_served" and hfa_route_check(["FCO"]) == "not_served")
check("Crete -> served (confirmed 16.10, seasonal)", hfa_route_check("כרתים") == "served" and hfa_route_check(["HER"]) == "served")
check("Hebrew prefix (לאתונה) still matches", hfa_route_check("לאתונה") == "served")
check("a list takes the best status (HER + ATH -> served)", hfa_route_check(["HER", "ATH"]) == "served")
check("'רמת גן' is not mistaken for רמון/Eilat", hfa_route_check("רמת גן") == "not_served")


def facts(message, places, airports=None):
    """Departure parsed from the customer's sentence + the fact block the
    model receives (_departure_summary)."""
    dep = chat._deterministic_departure_airport_facts(message).get("departure_airport")
    state = {"departure_airport": dep, "destination": {"places": places}}
    if airports:
        state["destination_airports"] = airports
    return dep, chat._departure_summary(state)


# --- Case 1: "טיסה מחיפה לאתונה" -> served ---------------------------------------------
dep, text = facts("טיסה מחיפה לאתונה", ["אתונה"], ["ATH"])
check("case 1: 'טיסה מחיפה לאתונה' -> departure HFA", dep == "HFA")
check("case 1: served -> continue as usual, no TLV offer", "Air Haifa" in text and 'לבדוק מנתב' not in text and "עונתי" not in text)
check("case 1: never promises a flight", "אל תבטיחי" in text)

# --- Case 2: "מחיפה לרומא" -> not_served + Ben Gurion offer ----------------------------
dep, text = facts("טיסה מחיפה לרומא", ["רומא"], ["FCO"])
check("case 2: departure HFA", dep == "HFA")
check("case 2: not_served -> 'אין טיסה ישירה' + offer נתב\"ג",
      'מחיפה אין טיסה ישירה לרומא. לבדוק מנתב"ג?' in text)
check("case 2: tells Ariella not to search from Haifa", "אל תתחילי חיפוש מחיפה" in text)

# --- Case 3: "מחיפה לכרתים" -> HER, seasonal ---------------------------------------------
# HER is confirmed since 16.10, so it is served - still seasonal, so the
# "seasonal - we'll check your dates" note stays.
dep, text = facts("טיסה מחיפה לכרתים", ["כרתים"])
check("case 3: departure HFA", dep == "HFA")
check("case 3: served + seasonal note", "Air Haifa" in text and "הקו עונתי — נבדוק זמינות בתאריכים שלכם" in text)
dep, text = facts("טיסה מחיפה לפאפוס", ["פאפוס"], ["PFO"])
check("Paphos (confirmed, not seasonal) -> no seasonal note", "Air Haifa" in text and "עונתי" not in text)

# --- 16.10: "יוון מחיפה" -> exactly ATH / SKG / RHO / HER --------------------------------
dep, text = facts("טיסה מחיפה ליוון", ["יוון"])
check("Greece from Haifa: offers exactly ATH, SKG, RHO, HER",
      "היעדים מחיפה באזור הזה הם בדיוק:" in text
      and all(f"({c})" in text for c in ("ATH", "SKG", "RHO", "HER"))
      and "JMK" not in text and "AOK" not in text and "מיקונוס" not in text)
dep, text = facts("טיסה מחיפה למיקונוס", ["מיקונוס"])
check("Mykonos from Haifa -> not_served + Ben Gurion offer", 'מחיפה אין טיסה ישירה למיקונוס. לבדוק מנתב"ג?' in text)

# --- the 'maybe' branch (no route is to_verify today) - with a temporary list ---------
import hfa_routes  # noqa: E402
_real_load = hfa_routes.load_routes
hfa_routes.load_routes = lambda: [dict(r, status="to_verify") if r["iata"] in ("HER", "PFO") else r for r in _real_load()]
dep, text = facts("טיסה מחיפה לכרתים", ["כרתים"])
check("to_verify + seasonal -> maybe, seasonal note", hfa_route_check("כרתים") == "maybe" and "הקו עונתי — נבדוק זמינות בתאריכים שלכם" in text)
dep, text = facts("טיסה מחיפה לפאפוס", ["פאפוס"])
check("to_verify, not seasonal -> 'not verified' note", "הקו עדיין לא מאומת — נבדוק זמינות בתאריכים שלכם" in text)
hfa_routes.load_routes = _real_load

# --- Case 4: "מתל אביב לרומא" -> unaffected -------------------------------------------
dep, text = facts("טיסה מנתב\"ג לרומא", ["רומא"], ["FCO"])
check("case 4: departure TLV", dep == "TLV")
check("case 4: no Haifa route note at all", "Air Haifa" not in text and "חיפה" not in text)
check("no destination yet -> no Haifa note", chat._departure_summary({"departure_airport": "HFA"}).count("Air Haifa") == 0)

# --- Start-search guard: never search HFA -> a destination it does not fly ------------
app = app_module.app
with connection() as conn:
    member_id = int(conn.execute(
        "INSERT INTO members (full_name,email,phone,password_hash,created_at,status) "
        "VALUES('QA','qa011a@example.com','050','x',datetime('now'),'active')").lastrowid)
client = app.test_client()
with client.session_transaction() as s:
    s["member_id"] = member_id
start_url = next((str(r.rule) for r in app.url_map.iter_rules() if r.endpoint.endswith("ariella_start_flight_search")), None)


def start(dep, places, airports):
    # No dates on purpose: a request the Haifa guard lets through stops right
    # after it ("missing dates"), so no real search can ever start here.
    state = {"departure_airport": dep, "destination": {"places": places}, "destination_airports": airports,
             "requested_services": ["flights"], "search_confirmed": True}
    with connection() as conn:
        before = conn.execute("SELECT COUNT(*) FROM trip_requests").fetchone()[0]
    r = client.post(start_url, json={"trip_state": state, "state": state, "confirmed": True, "history": []})
    with connection() as conn:
        after = conn.execute("SELECT COUNT(*) FROM trip_requests").fetchone()[0]
    return (r.get_json(silent=True) or {}).get("message", ""), r.status_code, after - before


check("start-search route found", bool(start_url))
msg, code, created = start("HFA", ["רומא"], ["FCO"])
check("HFA -> Rome: search refused with the Haifa message, no vacation created",
      created == 0 and code == 400 and msg.startswith("מחיפה אין טיסה ישירה"))
msg, code, created = start("HFA", ["אתונה"], ["ATH"])
check("HFA -> Athens: passes the Haifa guard (stops later on the missing dates)",
      msg and "מחיפה" not in msg and "תאריכ" in msg)
msg, code, created = start("TLV", ["רומא"], ["FCO"])
check("TLV -> Rome: passes the Haifa guard (stops later on the missing dates)",
      msg and "מחיפה" not in msg and "תאריכ" in msg)
src = open(os.path.join(os.path.dirname(__file__), "..", "public_site.py"), encoding="utf-8").read()
check("guard sits in ariella_start_flight_search (HFA + not_served -> 400)",
      'departure_airport == "HFA" and destination_codes and hfa_route_check(destination_codes) == "not_served"' in src)

# --- Admin page ---------------------------------------------------------------------
r = client.get("/admin/hfa-routes?token=qa-token")
page = r.get_data(as_text=True)
check("admin: /admin/hfa-routes renders", r.status_code == 200)
check("admin: lists all 10 destinations with verified_at column",
      all(c in page for c in codes) and "verified_at" in page)
r = app.test_client().get("/admin/hfa-routes")
check("admin: protected without the admin token", r.status_code in (302, 401, 403))
check("admin: scans page links to the Haifa list",
      "/admin/hfa-routes" in client.get("/admin/scans?token=qa-token").get_data(as_text=True))

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
