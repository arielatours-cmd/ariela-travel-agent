"""QA for task 010a stage 1 - cumulative member_travelers list + "My profile".

Per product/dev-tasks/010a-customer-profile.md (ofek branch), stage 1 only.
Acceptance criteria covered (on a temporary DB, offline):
  1. child 9 -> one row; 6 months later girl 16 -> two rows; a year later
     boy 10 -> the existing row is updated, no third row
  2. two ungendered children 9 and 10, then "boy 10" -> new row with
     needs_review=1, no merge
  3. a child who did not travel this time stays on the list
  4. delete from "My profile" sets deleted_at and the row never comes back;
     deleting the account deletes everything
  7. a new customer with no history sees no change on the account page
  8. another member cannot update or delete a traveller that is not theirs
Plus: one-time migration from ariella_travel_companions, extra adults,
promotion of a grown child to adult, and the privacy page.

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
check("2: 'boy of 10' matching both -> a new third row", len(kids2) == 3)
check("2: the new row has needs_review=1", kids2[-1]["needs_review"] == 1 and kids2[-1]["gender"] == "male")
check("2: the two original rows were not changed (no merge)",
      [k["age_at_record"] for k in kids2[:2]] == [9, 10] and all(k["gender"] is None for k in kids2[:2]))
labels = [t["label"] for t in mp.list_travelers(m2, "2026-03-15")]
check("2: labels are honest about unknown gender", "ילד/ה, בערך בגיל 9" in labels and "ילד, בערך בן 10" in labels)

# Twins (same gender + age): by the spec every match is ambiguous, so each
# vacation adds flagged rows instead of merging - documented spec behaviour,
# raised with Bezalel as an open question.
m2b = make_member("qa2b@example.com")
mp.sync_trip_travelers(m2b, {"adults": 2, "child_ages": [8, 8], "child_genders": ["female", "female"]}, "2026-03-01")
mp.sync_trip_travelers(m2b, {"adults": 2, "child_ages": [8, 8], "child_genders": ["female", "female"]}, "2026-04-01")
twins = rows(m2b, children_only=True)
check("twins (spec): ambiguous -> new rows flagged needs_review, originals untouched",
      len(twins) == 4 and [t["needs_review"] for t in twins] == [0, 0, 1, 1])

# --- grown child -> adult --------------------------------------------------------
m5 = make_member("qa5@example.com")
mp.sync_trip_travelers(m5, {"adults": 1, "child_ages": [17], "child_genders": ["female"]}, "2025-01-01")
listing = mp.list_travelers(m5, "2026-06-01")
check("a girl of 17 recorded 17 months ago is shown as an adult", listing and listing[0]["is_adult"])
mp.sync_trip_travelers(m5, {"adults": 1, "child_ages": []}, "2026-06-01")
check("...and her record is updated to kind='adult'", rows(m5)[0]["kind"] == "adult")

# --- 7. New customer: account page unchanged ---------------------------------------
m7 = make_member("qa7@example.com")
r = client_for(m7).get("/account")
page = r.get_data(as_text=True)
check("7: new customer: account page renders", r.status_code == 200)
check("7: new customer: no 'what Ariella remembers' section", "מה אריאלה זוכרת עליי" not in page and "my-profile" not in page)
r = client_for(m1).get("/account")
page = r.get_data(as_text=True)
check("profile section shows for a customer with travellers", "מה אריאלה זוכרת עליי" in page)
check("profile lists 'ילד, בערך בן 10'", "ילד, בערך בן 10" in page or "ילד, בערך בן 11" in page)
check("profile has update + delete forms", "/account/travelers/" in page and "/update" in page and "/delete" in page)
review_page = client_for(m2).get("/account").get_data(as_text=True)
check("needs_review row is marked gently", "ייתכן שזה אותו ילד, תקנו אם צריך" in review_page)

# --- 8. Ownership -------------------------------------------------------------------
target = rows(m1, children_only=True)[0]
other = client_for(m2)
r = other.post(f"/account/travelers/{target['id']}/update", data={"age": "3", "gender": "female"})
check("8: another member updating my traveller -> 404", r.status_code == 404)
r = other.post(f"/account/travelers/{target['id']}/delete")
check("8: another member deleting my traveller -> 404", r.status_code == 404)
after = next(x for x in rows(m1, include_deleted=True) if x["id"] == target["id"])
check("8: the row is untouched", after["age_at_record"] == target["age_at_record"] and after["deleted_at"] is None)
r = app.test_client().post(f"/account/travelers/{target['id']}/delete")
check("8: logged-out delete -> redirect to login, nothing deleted",
      r.status_code == 302 and "login" in r.headers.get("Location", "") and rows(m1, include_deleted=True)[0]["deleted_at"] is None)

# own update
owner = client_for(m1)
r = owner.post(f"/account/travelers/{target['id']}/update", data={"age": "11", "gender": "male"})
fixed = next(x for x in rows(m1) if x["id"] == target["id"])
check("own update -> redirect back to profile", r.status_code == 302 and "#my-profile" in r.headers.get("Location", ""))
check("own update -> age saved, source edited_by_customer, needs_review cleared",
      fixed["age_at_record"] == 11 and fixed["source"] == "edited_by_customer" and fixed["needs_review"] == 0)

# --- 4. Delete ---------------------------------------------------------------------
girl_id = next(x["id"] for x in rows(m1, children_only=True) if x["gender"] == "female")
r = owner.post(f"/account/travelers/{girl_id}/delete")
gone = next(x for x in rows(m1, include_deleted=True) if x["id"] == girl_id)
check("4: delete -> deleted_at set (soft delete)", r.status_code == 302 and gone["deleted_at"] is not None)
check("4: deleted row not listed", girl_id not in [t["id"] for t in mp.list_travelers(m1)])
mp.sync_trip_travelers(m1, {"adults": 2, "child_ages": [17], "child_genders": ["female"]}, "2027-07-20")
gone_again = next(x for x in rows(m1, include_deleted=True) if x["id"] == girl_id)
check("4: a later vacation never revives the deleted row", gone_again["deleted_at"] is not None and gone_again["age_at_record"] == 16)
check("4: deleting twice -> 404", owner.post(f"/account/travelers/{girl_id}/delete").status_code == 404)
check("4: profile page no longer shows the deleted row",
      f"/account/travelers/{girl_id}/delete" not in owner.get("/account").get_data(as_text=True))

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
check("migration: the old table is kept", still == 1)
mp.sync_trip_travelers(m6, {"adults": 2, "child_ages": []}, "2026-05-01")
check("migration: a named companion counts as the second adult (no unnamed duplicate)", len(rows(m6)) == 1)

# --- Hook + privacy ------------------------------------------------------------------
src = open(os.path.join(os.path.dirname(__file__), "..", "public_site.py"), encoding="utf-8").read()
check("sync is called right after the chat creates the trip",
      "member_profile.sync_trip_travelers(session[\"member_id\"], travelers)" in src)
for path in ("/privacy?lang=he", "/privacy?lang=en"):
    text = app.test_client().get(path).get_data(as_text=True)
    check(f"{path} explains the saved traveller list and the right to delete it",
          ("מה אריאלה זוכרת עליי" in text) if path.endswith("he") else ("What Ariella remembers about me" in text))

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
