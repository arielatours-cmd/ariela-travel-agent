"""Member profile, task 010a stage 1: the cumulative list of the people a
member travels with (member_travelers, created in database.init_db).

Only facts the customer actually said are stored: how many adults, each
child's age and, when given, gender. Nothing is guessed. Children are matched
across vacations by gender + estimated current age; when the match is
ambiguous a new row is added with needs_review=1 instead of merging. The list
only grows - a child who did not travel this time stays on it - and the
customer can correct an age or delete a row from "My Vacations".
"""
from __future__ import annotations

from datetime import date, datetime

from database import connection, utc_now_iso

ADULT_AGE = 18
_GENDERS = {"male", "female"}


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return datetime.utcnow().date()


def _full_years_between(start: date, end: date) -> int:
    years = end.year - start.year - ((end.month, end.day) < (start.month, start.day))
    return max(0, years)


def estimated_age(row, today=None) -> int | None:
    """age_at_record plus the full years since age_recorded_at."""
    age = row["age_at_record"]
    if age is None:
        return None
    if not row["age_recorded_at"]:
        return int(age)
    return int(age) + _full_years_between(_as_date(row["age_recorded_at"]), _as_date(today))


def _int_or_none(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number < 120 else None


def _gender_or_none(value):
    value = str(value or "").strip().lower()
    return value if value in _GENDERS else None


def _child_kind(age: int) -> str:
    if age >= ADULT_AGE:
        return "adult"
    return "infant" if age < 2 else "child"


def _promote_grown_children(conn, member_id: int, today: date) -> None:
    """A child whose estimated age is now 18+ is recorded as an adult."""
    rows = conn.execute(
        "SELECT * FROM member_travelers WHERE member_id=? AND deleted_at IS NULL AND kind != 'adult'",
        (member_id,),
    ).fetchall()
    for row in rows:
        age = estimated_age(row, today)
        if age is not None and age >= ADULT_AGE:
            conn.execute("UPDATE member_travelers SET kind='adult' WHERE id=?", (row["id"],))


def sync_trip_travelers(member_id: int, travelers: dict, trip_date=None) -> None:
    """Fold one vacation's travellers into the member's cumulative list.

    travelers is trip_state["travelers"]: adults, child_ages, child_genders.
    trip_date is the day the vacation is recorded (default: today); ages
    given in the chat are taken as the children's ages on that day.
    """
    if not member_id or not isinstance(travelers, dict):
        return
    today = _as_date(trip_date)
    today_iso = today.isoformat()
    now = utc_now_iso()
    ages = travelers.get("child_ages") if isinstance(travelers.get("child_ages"), list) else []
    genders = travelers.get("child_genders") if isinstance(travelers.get("child_genders"), list) else []

    with connection() as conn:
        _promote_grown_children(conn, member_id, today)
        existing = [dict(r) for r in conn.execute(
            "SELECT * FROM member_travelers WHERE member_id=? AND deleted_at IS NULL AND kind != 'adult' ORDER BY id",
            (member_id,),
        ).fetchall()]
        used: set[int] = set()

        for index, raw_age in enumerate(ages):
            age = _int_or_none(raw_age)
            if age is None:
                continue
            gender = _gender_or_none(genders[index] if index < len(genders) else None)
            matches = [
                row for row in existing
                if row["id"] not in used
                and (row["gender"] is None or gender is None or row["gender"] == gender)
                and (est := estimated_age(row, today)) is not None
                and abs(est - age) <= 1
            ]
            if len(matches) == 1:
                row = matches[0]
                used.add(row["id"])
                conn.execute(
                    """UPDATE member_travelers SET age_at_record=?, age_recorded_at=?, last_travelled_at=?,
                           kind=?, gender=COALESCE(gender, ?) WHERE id=?""",
                    (age, today_iso, today_iso, _child_kind(age), gender, row["id"]),
                )
                continue
            cur = conn.execute(
                """INSERT INTO member_travelers(member_id, kind, gender, age_at_record, age_recorded_at,
                       source, needs_review, last_travelled_at, created_at)
                   VALUES(?, ?, ?, ?, ?, 'said_in_chat', ?, ?, ?)""",
                (member_id, _child_kind(age), gender, age, today_iso,
                 1 if len(matches) > 1 else 0, today_iso, now),
            )
            used.add(int(cur.lastrowid))

        adults = _int_or_none(travelers.get("adults")) or 0
        known_adults = 1 + conn.execute(  # 1 = the account holder
            "SELECT COUNT(*) FROM member_travelers WHERE member_id=? AND deleted_at IS NULL AND kind='adult'",
            (member_id,),
        ).fetchone()[0]
        for _ in range(max(0, adults - known_adults)):
            conn.execute(
                """INSERT INTO member_travelers(member_id, kind, source, last_travelled_at, created_at)
                   VALUES(?, 'adult', 'said_in_chat', ?, ?)""",
                (member_id, today_iso, now),
            )


def list_travelers(member_id: int, today=None) -> list[dict]:
    """Active (not deleted) travellers, with an estimated current age and a
    Hebrew display label. A child estimated at 18+ is shown as an adult."""
    today = _as_date(today)
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM member_travelers WHERE member_id=? AND deleted_at IS NULL ORDER BY id",
            (member_id,),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        age = estimated_age(row, today)
        item["estimated_age"] = age
        item["is_adult"] = row["kind"] == "adult" or (age is not None and age >= ADULT_AGE)
        item["label"] = _label(item)
        out.append(item)
    return out


def _label(item: dict) -> str:
    if item["is_adult"]:
        if item.get("first_name"):
            return item["first_name"]
        if item.get("relationship") == "partner":
            return "בן/בת זוג"
        return "מבוגר/ת נוסף/ת"
    age, gender = item.get("estimated_age"), item.get("gender")
    if item.get("kind") == "infant":
        noun = {"male": "תינוק", "female": "תינוקת"}.get(gender, "תינוק/ת")
    else:
        noun = {"male": "ילד", "female": "ילדה"}.get(gender, "ילד/ה")
    if age is None:
        return noun
    if gender == "male":
        return f"{noun}, בערך בן {age}"
    if gender == "female":
        return f"{noun}, בערך בת {age}"
    return f"{noun}, בערך בגיל {age}"


def update_traveler(member_id: int, traveler_id: int, age=None, gender=None) -> bool:
    """The customer's own correction. False when the row is not theirs."""
    age_value = _int_or_none(age)
    gender_value = _gender_or_none(gender)
    today_iso = datetime.utcnow().date().isoformat()
    with connection() as conn:
        row = conn.execute(
            "SELECT id, kind FROM member_travelers WHERE id=? AND member_id=? AND deleted_at IS NULL",
            (traveler_id, member_id),
        ).fetchone()
        if not row:
            return False
        kind = _child_kind(age_value) if age_value is not None else row["kind"]
        conn.execute(
            """UPDATE member_travelers SET age_at_record=COALESCE(?, age_at_record),
                   age_recorded_at=CASE WHEN ? IS NULL THEN age_recorded_at ELSE ? END,
                   gender=?, kind=?, needs_review=0, source='edited_by_customer' WHERE id=?""",
            (age_value, age_value, today_iso, gender_value, kind, traveler_id),
        )
    return True


def delete_traveler(member_id: int, traveler_id: int) -> bool:
    """Soft delete: deleted_at is set, so the row never comes back in the
    list or in matching. False when the row is not theirs."""
    with connection() as conn:
        cur = conn.execute(
            "UPDATE member_travelers SET deleted_at=? WHERE id=? AND member_id=? AND deleted_at IS NULL",
            (utc_now_iso(), traveler_id, member_id),
        )
        return cur.rowcount > 0
