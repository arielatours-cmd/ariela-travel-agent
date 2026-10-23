"""QA for task 010a stage 1 - cumulative member_travelers list, and its later
removal from customer view (business owner, 22.10.2026, Din's route B / PRV-14).

Per product/dev-tasks/010a-customer-profile.md (ofek branch), stage 1 only.
Acceptance criteria covered (on a temporary DB, offline):
  1. child 9 -> one row; 6 months later girl 16 -> two rows; a year later
     boy 10 -> the existing row is updated, no third row
  2. two ungendered children 9 and 10, then "boy 10" -> both candidates
     flagged needs_review=1, no merge and no new row (decision 16.10)
  3. a child who did not travel this time stays on the list
  4. delete sets deleted_at and the row never comes back; deleting the
     account deletes everything
  7. the "what Ariella remembers about me" section is gone from every
     customer-facing page (it briefly moved to /account/details, then the
     business owner reversed that and asked for it to be removed entirely)
  8. only the new admin-only path (see app.admin_delete_traveler) can
     delete a traveler now - there is no customer-facing route left at all
Plus: one-time migration from ariella_travel_companions, extra adults,
promotion of a grown child to adult, the Contact-page footer link, and the
privacy page's wording (routes a view/correction/deletion request through
staff via Contact, handled within 30 days - never names a screen).

Run: python3 tools/qa_member_travelers_010a.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="ariella-qa-010a-")
os.environ.update({"DB_PATH": os.path.join(_TMP, "qa.db"), "SCHEDULER_ENABLED": "false",
                   "SCANNER_ENABLED": "false"})
for key in ("SERPAPI_API_KEY", "ANTHROPIC_API_KEY", "WHATSAPP_ACCESS_TOKEN"):
    os.environ.pop(key, None)

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import app as app_module  # noqa: E402
import database  # noqa: E402
import member_profile as mp  # noqa: E402
from database import connection  # noqa: E402

app = app_module.app


def make_member(email):
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO members (full_name,email,phone,password_hash,created_at,status) "
            "VALUES('QA Member',?,'0500000000','x',datetime('now'),'active')", (email,))
        return int(cur.lastrowid)


def rows(member_id, include_deleted=False, children_only=False):
    sql = "SELECT * FROM member_travelers WHERE member_id=?"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    if children_only:
        sql += " AND kind != 'adult'"
    with connection() as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY id", (member_id,)).fetchall()]


def client_for(member_id):
    c = app.test_client()
    with c.session_transaction() as s:
        s["member_id"] = member_id
    return c


# --- 1. Accumulating children across vacations ------------------------------
m1 = make_member("qa1@example.com")
mp.sync_trip_travelers(m1, {"adults": 2, "children": 1, "child_ages": [9], "child_genders": ["male"]}, "2026-01-10")
kids = rows(m1, children_only=True)
check("1a: first vacation with a boy of 9 -> one child row", len(kids) == 1 and kids[0]["age_at_record"] == 9 and kids[0]["gender"] == "male")
check("1a: source is said_in_chat", kids and kids[0]["source"] == "said_in_chat")
mp.sync_trip_travelers(m1, {"adults": 2, "children": 1, "child_ages": [16], "child_genders": ["female"]}, "2026-07-10")
kids = rows(m1, children_only=True)
check("1b: 6 months later, a girl of 16 -> two child rows", len(kids) == 2)
mp.sync_trip_travelers(m1, {"adults": 2, "children": 1, "child_ages": [10], "child_genders": ["male"]}, "2027-01-12")
kids = rows(m1, children_only=True)
boy = next((k for k in kids if k["gender"] == "male"), {})
check("1c: a year later, a boy of 10 -> no third row", len(kids) == 2)
check("1c: the boy's row is updated (age 10, recorded 2027-01-12)",
      boy.get("age_at_record") == 10 and boy.get("age_recorded_at") == "2027-01-12" and boy.get("last_travelled_at") == "2027-01-12")
check("1: no row was flagged for review", not any(k["needs_review"] for k in kids))

# --- 3. A child who did not travel this time stays ---------------------------
girl = next((k for k in kids if k["gender"] == "female"), {})
check("3: the girl (not on the last vacation) is still on the list",
      girl.get("age_at_record") == 16 and girl.get("deleted_at") is None)
check("3: estimated age grows with time (16 on 2026-07-10 -> 17 on 2027-07-11)",
      mp.estimated_age(girl, "2027-07-11") == 17)

# adults: 2 adults = account holder + one more; repeated syncs add no more
adults = [r for r in rows(m1) if r["kind"] == "adult"]
check("adults: 2 travelling adults -> exactly one extra adult row after 3 vacations", len(adults) == 1)
mp.sync_trip_travelers(m1, {"adults": 3, "child_ages": []}, "2027-02-01")
check("adults: 3 adults later -> one more unnamed adult", len([r for r in rows(m1) if r["kind"] == "adult"]) == 2)

# --- 2. Ambiguous match -> needs_review, no merge -----------------------------
m2 = make_member("qa2@example.com")
mp.sync_trip_travelers(m2, {"adults": 1, "child_ages": [9, 10], "child_genders": [None, None]}, "2026-03-01")
check("2: two ungendered children -> two rows", len(rows(m2, children_only=True)) == 2)
mp.sync_trip_travelers(m2, {"adults": 1, "child_ages": [10], "child_genders": ["male"]}, "2026-03-15")
kids2 = rows(m2, children_only=True)
check("2: 'boy of 10' matching both -> NO new row (decision 16.10)", len(kids2) == 2)
check("2: both candidates flagged needs_review=1", [k["needs_review"] for k in kids2] == [1, 1])
check("2: the two rows were not changed (no merge)",
      [k["age_at_record"] for k in kids2] == [9, 10] and all(k["gender"] is None for k in kids2))
labels = [t["label"] for t in mp.list_travelers(m2, "2026-03-15")]
check("2: labels are honest about unknown gender", "ילד/ה, בערך בגיל 9" in labels and "ילד/ה, בערך בגיל 10" in labels)

# Twins (decision 16.10): indistinguishable candidates + the same number of
# matching children on the vacation -> paired one-to-one, no review.
m2b = make_member("qa2b@example.com")
for when, age in (("2026-03-01", 7), ("2026-06-01", 7), ("2027-04-01", 8)):
    mp.sync_trip_travelers(m2b, {"adults": 2, "child_ages": [age, age], "child_genders": ["female", "female"]}, when)
twins = rows(m2b, children_only=True)
check("twins of 7, three vacations -> 2 child rows, not 6", len(twins) == 2)
check("twins: none flagged needs_review", all(t["needs_review"] == 0 for t in twins))
check("twins: both updated on the last vacation (age 8)", all(t["age_at_record"] == 8 and t["last_travelled_at"] == "2027-04-01" for t in twins))
m2c = make_member("qa2c@example.com")
mp.sync_trip_travelers(m2c, {"adults": 2, "child_ages": [7, 7], "child_genders": ["male", "male"]}, "2026-03-01")
mp.sync_trip_travelers(m2c, {"adults": 2, "child_ages": [7], "child_genders": ["male"]}, "2026-05-01")
tw = rows(m2c, children_only=True)
check("twins, only one travels -> counts differ -> both flagged, no new row",
      len(tw) == 2 and [t["needs_review"] for t in tw] == [1, 1])
mp.sync_trip_travelers(m2c, {"adults": 2, "child_ages": [7, 7, 7], "child_genders": ["male", "male", "male"]}, "2026-06-01")
check("three boys of 7 vs two stored twins -> flagged, list does not grow", len(rows(m2c, children_only=True)) == 2)

# --- grown child -> adult --------------------------------------------------------
m5 = make_member("qa5@example.com")
mp.sync_trip_travelers(m5, {"adults": 1, "child_ages": [17], "child_genders": ["female"]}, "2025-01-01")
listing = mp.list_travelers(m5, "2026-06-01")
check("a girl of 17 recorded 17 months ago is shown as an adult", listing and listing[0]["is_adult"])
mp.sync_trip_travelers(m5, {"adults": 1, "child_ages": []}, "2026-06-01")
check("...and her record is updated to kind='adult'", rows(m5)[0]["kind"] == "adult")

# --- 7. Removed entirely from customer view (business owner, 22.10.2026, Din's ---
#        route B / PRV-14, replacing the earlier "moved to account details" plan):
#        the whole "what Ariella remembers about me" section is gone from every
#        customer-facing page. The data itself is unchanged - still saved and
#        used by Ariella in chat - only the customer self-service display and
#        the self-service update/delete HTTP routes are removed. A view/
#        correction/deletion request now goes through staff via the Contact
#        page (see the privacy-policy check below), and staff act on it
#        through the new admin-only path tested in section 8.
m7 = make_member("qa7@example.com")
r = client_for(m7).get("/account")
page = r.get_data(as_text=True)
check("7: new customer: account page renders", r.status_code == 200)
check("7: new customer: vacations page never shows the profile section", "מה אריאלה זוכרת עליי" not in page and "my-profile" not in page)
check("7: new customer: account details page never shows the profile section either",
      "מה אריאלה זוכרת עליי" not in client_for(m7).get("/account/details").get_data(as_text=True))
check("profile section is gone from the vacations page even for a customer with travellers",
      "מה אריאלה זוכרת עליי" not in client_for(m1).get("/account").get_data(as_text=True))
check("profile section is gone from account details too, even for a customer with travellers",
      "מה אריאלה זוכרת עליי" not in client_for(m1).get("/account/details").get_data(as_text=True))
check("the old customer-facing update/delete routes are gone entirely",
      not any(r.rule.startswith("/account/travelers/") for r in app.url_map.iter_rules()))

# --- 8. Admin-only delete path (replaces customer self-service) --------------------
target = rows(m1, children_only=True)[0]
target_label = next(t["label"] for t in mp.list_travelers(m1) if t["id"] == target["id"])
admin = app.test_client()
r = admin.get(f"/admin/delete-traveler?member_id={m2}&traveler_id={target['id']}")
check("8: a traveler id that isn't this member's -> 404, nothing deleted",
      r.status_code == 404 and rows(m1, include_deleted=True, children_only=True)[0]["id"] == target["id"]
      and rows(m1, include_deleted=True, children_only=True)[0]["deleted_at"] is None)
r = admin.get(f"/admin/delete-traveler?member_id={m1}")
check("8: missing traveler_id -> 400", r.status_code == 400)
r = admin.get(f"/admin/delete-traveler?member_id={m1}&traveler_id={target['id']}")
preview = r.get_json()
check("8: without confirm=1, only a preview is returned - nothing deleted",
      r.status_code == 200 and preview.get("would_delete") is True and preview.get("applied") is False
      and preview.get("label") == target_label
      and rows(m1, include_deleted=True, children_only=True)[0]["deleted_at"] is None)
r = admin.get(f"/admin/delete-traveler?member_id={m1}&traveler_id={target['id']}&confirm=1")
gone = next(x for x in rows(m1, include_deleted=True) if x["id"] == target["id"])
check("8: confirm=1 actually deletes (soft delete)", r.status_code == 200 and r.get_json().get("applied") is True and gone["deleted_at"] is not None)
check("8 (Din): deleted row has every personal field NULL",
      all(gone[f] is None for f in ("first_name", "relationship", "gender", "age_at_record", "age_recorded_at")))
r = admin.get(f"/admin/delete-traveler?member_id={m1}&traveler_id={target['id']}&confirm=1")
check("8: deleting an already-deleted traveler -> 404", r.status_code == 404)

# --- 4. Delete (direct, as member_profile.delete_traveler - still used internally) --
girl_id = next(x["id"] for x in rows(m1, children_only=True) if x["gender"] == "female")
check("4: delete -> deleted_at set (soft delete)", mp.delete_traveler(m1, girl_id))
gone = next(x for x in rows(m1, include_deleted=True) if x["id"] == girl_id)
check("4: deleted_at actually set", gone["deleted_at"] is not None)
check("4: deleted row not listed", girl_id not in [t["id"] for t in mp.list_travelers(m1)])
check("4 (Din): deleted row has every personal field NULL",
      all(gone[f] is None for f in ("first_name", "relationship", "gender", "age_at_record", "age_recorded_at")))
mp.sync_trip_travelers(m1, {"adults": 2, "child_ages": [17], "child_genders": ["female"]}, "2027-07-20")
gone_again = next(x for x in rows(m1, include_deleted=True) if x["id"] == girl_id)
check("4: a later vacation never revives the deleted row", gone_again["deleted_at"] is not None and gone_again["age_at_record"] is None)
check("4: deleting twice -> False", not mp.delete_traveler(m1, girl_id))

check("4: account deletion removes all member_travelers rows",
      database.delete_member_account(m1) and rows(m1, include_deleted=True) == [])
check("4: member_travelers and member_preferences are in the deletion list",
      {"member_travelers", "member_preferences"} <= set(database._MEMBER_OWNED_TABLES))

# --- Migration from ariella_travel_companions (one-time) ----------------------------
m6 = make_member("qa6@example.com")
with connection() as conn:
    conn.execute("""CREATE TABLE IF NOT EXISTS ariella_travel_companions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL, first_name TEXT NOT NULL,
        relationship TEXT, created_at TEXT NOT NULL, last_travelled_at TEXT, UNIQUE(member_id, first_name))""")
    conn.execute("INSERT INTO ariella_travel_companions(member_id,first_name,relationship,created_at) VALUES(?,?,?,datetime('now'))",
                 (m6, "Noa", "partner"))
    conn.execute("DELETE FROM settings WHERE key='member_travelers_migrated'")
database.init_db()
database.init_db()
migrated = rows(m6)
check("migration: companion copied once as an adult (init_db run twice)",
      len(migrated) == 1 and migrated[0]["kind"] == "adult" and migrated[0]["first_name"] == "Noa"
      and migrated[0]["relationship"] == "partner")
with connection() as conn:
    still = conn.execute("SELECT COUNT(*) FROM ariella_travel_companions WHERE member_id=?", (m6,)).fetchone()[0]
check("migration: the old table is kept (row still there before any delete)", still == 1)
mp.sync_trip_travelers(m6, {"adults": 2, "child_ages": []}, "2026-05-01")
check("migration: a named companion counts as the second adult (no unnamed duplicate)", len(rows(m6)) == 1)
noa = rows(m6)[0]
check("delete a named traveller", mp.delete_traveler(m6, noa["id"]))
noa_after = rows(m6, include_deleted=True)[0]
check("delete (Din): name, relationship and all personal fields are NULL",
      all(noa_after[f] is None for f in ("first_name", "relationship", "gender", "age_at_record", "age_recorded_at"))
      and noa_after["deleted_at"] is not None)
with connection() as conn:
    left = conn.execute("SELECT COUNT(*) FROM ariella_travel_companions WHERE member_id=? AND first_name='Noa'", (m6,)).fetchone()[0]
check("delete (Din): the matching ariella_travel_companions row is gone", left == 0)

# --- Hook + privacy ------------------------------------------------------------------
src = open(os.path.join(os.path.dirname(__file__), "..", "public_site.py"), encoding="utf-8").read()
check("sync is called right after the chat creates the trip",
      "member_profile.sync_trip_travelers(session[\"member_id\"], travelers)" in src)
check("the Contact link exists in the site footer (#131)",
      'url_for(\'site.contact\'' in open(os.path.join(os.path.dirname(__file__), "..", "templates", "_site_footer.html"), encoding="utf-8").read())
for path in ("/privacy?lang=he", "/privacy?lang=en"):
    text = app.test_client().get(path).get_data(as_text=True)
    # Route B (business owner, 22.10.2026, Din's condition PRV-14 - replaces
    # the earlier "moved to account details" plan): the policy must never
    # point at a screen that no longer exists - it now routes a view/
    # correction/deletion request through staff via the Contact page,
    # handled within 30 days, instead of naming any self-service screen.
    check(f"{path} routes the request through the Contact page with a 30-day SLA",
          ('דרך עמוד "יצירת קשר", והבקשה תטופל בתוך 30 ימים' in text) if path.endswith("he")
          else ('through the "Contact" page, and the request will be handled within 30 days' in text))
    check(f"{path} no longer names the removed self-service heading or the account details page",
          ("מה אריאלה זוכרת עליי" not in text and "פרטי החשבון" not in text) if path.endswith("he")
          else ("What Ariella remembers about me" not in text and "Account Details" not in text))
    check(f"{path} carries Din's exact wording",
          ("מחיקת נוסע מוחקת את פרטיו, ומחיקת החשבון מוחקת את כל הרשימה." in text) if path.endswith("he")
          else ("Deleting a traveler deletes their details, and deleting your account deletes the whole list." in text))

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
