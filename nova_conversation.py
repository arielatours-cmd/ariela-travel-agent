"""NOVA N2 — inbound WhatsApp conversation router.

Identity rule (product decision):
1. The verified WhatsApp sender number is the primary identity.
2. If it matches an active Ariella member phone, link automatically.
3. If it is already linked, use that member.
4. If no member matches, run a short onboarding conversation and create a user.
5. A website session/handoff must never override the WhatsApp number identity.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Optional

from werkzeug.security import generate_password_hash

from database import connection, utc_now_iso

TOKEN_RE = re.compile(r"קוד\s*חיבור\s*:\s*([^\s]+)", re.I)

YES = {"כן", "כן.", "מאשר", "מאשרת", "אישור", "yes", "y", "1"}
NO = {"לא", "לא.", "no", "n", "ביטול", "בטל", "cancel"}
TLV_WORDS = {"tlv", "נתבג", 'נתב"ג', "נתב״ג", "בן גוריון", "תל אביב"}
HFA_WORDS = {"hfa", "חיפה"}


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def canonical_phone(value: str) -> str:
    """Normalize Israeli/local WhatsApp numbers to a stable international form."""
    digits = _digits(value)
    if not digits:
        return ""
    # 00 international prefix
    if digits.startswith("00"):
        digits = digits[2:]
    # Israeli local mobile/landline -> 972...
    if digits.startswith("0") and len(digits) >= 9:
        digits = "972" + digits[1:]
    return digits


def _phone_hash(phone: str) -> str:
    canonical = canonical_phone(phone)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest() if canonical else ""


def _member_phone_matches(stored_phone: str, inbound_phone: str) -> bool:
    a, b = canonical_phone(stored_phone), canonical_phone(inbound_phone)
    return bool(a and b and a == b)


def linked_member_for_phone(phone: str) -> Optional[int]:
    h = _phone_hash(phone)
    if not h:
        return None
    with connection() as conn:
        row = conn.execute(
            "SELECT member_id FROM whatsapp_member_links WHERE wa_phone_hash=? AND status='active'",
            (h,),
        ).fetchone()
    return int(row["member_id"]) if row else None


def registered_member_for_phone(phone: str) -> Optional[int]:
    """Find an existing active website user by normalized phone, format-agnostic."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id,phone FROM members WHERE status='active' AND phone IS NOT NULL AND trim(phone)<>''"
        ).fetchall()
    matches = [int(r["id"]) for r in rows if _member_phone_matches(r["phone"], phone)]
    # Phone should be unique by product rule; refuse ambiguity rather than guess.
    return matches[0] if len(matches) == 1 else None


def ensure_whatsapp_link(member_id: int, phone: str) -> int:
    """Bind verified WhatsApp sender to member, never stealing a link from another member."""
    h = _phone_hash(phone)
    if not h:
        raise ValueError("invalid WhatsApp phone")
    now = utc_now_iso()
    with connection() as conn:
        existing = conn.execute(
            "SELECT member_id FROM whatsapp_member_links WHERE wa_phone_hash=? AND status='active'",
            (h,),
        ).fetchone()
        if existing and int(existing["member_id"]) != int(member_id):
            raise ValueError("WhatsApp phone already linked to another member")
        conn.execute(
            """INSERT INTO whatsapp_member_links
               (member_id,wa_phone_hash,verified_at,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(member_id) DO UPDATE SET
                 wa_phone_hash=excluded.wa_phone_hash,
                 verified_at=excluded.verified_at,
                 status='active',
                 updated_at=excluded.updated_at""",
            (int(member_id), h, now, "active", now, now),
        )
        conn.commit()
    return int(member_id)


def _member(member_id: int) -> dict:
    with connection() as conn:
        row = conn.execute(
            "SELECT id,full_name,email,phone FROM members WHERE id=? AND status='active'",
            (int(member_id),),
        ).fetchone()
    return dict(row) if row else {"id": member_id, "full_name": ""}


def _vacations(member_id: int, limit: int = 5) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT id,request_name,status,answers_json
               FROM trip_requests WHERE member_id=? ORDER BY id DESC LIMIT ?""",
            (int(member_id), int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def _set_state(member_id: int, intent: str, trip_id: int | None = None) -> None:
    now = utc_now_iso()
    with connection() as conn:
        conn.execute(
            """INSERT INTO whatsapp_conversation_state
               (member_id,active_trip_id,current_intent,last_message_at,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(member_id) DO UPDATE SET
                 active_trip_id=excluded.active_trip_id,
                 current_intent=excluded.current_intent,
                 last_message_at=excluded.last_message_at,
                 updated_at=excluded.updated_at""",
            (int(member_id), trip_id, intent, now, now),
        )
        conn.commit()


def _onboarding_get(phone: str) -> dict | None:
    h = _phone_hash(phone)
    with connection() as conn:
        row = conn.execute(
            "SELECT current_step,data_json FROM whatsapp_onboarding_state WHERE wa_phone_hash=?",
            (h,),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["data_json"] or "{}")
    except Exception:
        data = {}
    return {"step": row["current_step"], "data": data}


def _onboarding_set(phone: str, step: str, data: dict) -> None:
    h = _phone_hash(phone)
    now = utc_now_iso()
    with connection() as conn:
        conn.execute(
            """INSERT INTO whatsapp_onboarding_state
               (wa_phone_hash,current_step,data_json,created_at,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(wa_phone_hash) DO UPDATE SET
                 current_step=excluded.current_step,
                 data_json=excluded.data_json,
                 updated_at=excluded.updated_at""",
            (h, step, json.dumps(data, ensure_ascii=False), now, now),
        )
        conn.commit()


def _onboarding_clear(phone: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM whatsapp_onboarding_state WHERE wa_phone_hash=?", (_phone_hash(phone),))
        conn.commit()


def _valid_email(value: str) -> bool:
    value = (value or "").strip().lower()
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def _airport_codes(value: str) -> list[str]:
    raw = (value or "").strip().lower()
    codes = []
    tokens = {x.strip() for x in re.split(r"[,;/|]+", raw) if x.strip()}
    for token in tokens or {raw}:
        if token in TLV_WORDS or any(word in token for word in TLV_WORDS if len(word) > 2):
            if "TLV" not in codes:
                codes.append("TLV")
        elif token in HFA_WORDS or "חיפה" in token:
            if "HFA" not in codes:
                codes.append("HFA")
        elif re.fullmatch(r"[a-z]{3}", token):
            code = token.upper()
            if code not in codes:
                codes.append(code)
    return codes[:5]


def _create_member_from_whatsapp(phone: str, data: dict) -> int:
    """Create a normal Ariella member sourced from verified WhatsApp identity.

    A random unknown password is stored. The user can later use the normal
    Forgot Password flow on the website to choose a password.
    """
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    airports = data.get("preferred_airports") or ["TLV"]
    if not full_name or not _valid_email(email):
        raise ValueError("missing onboarding data")
    canonical = canonical_phone(phone)
    random_secret = secrets.token_urlsafe(32)
    now = utc_now_iso()
    with connection() as conn:
        # Never create a duplicate email. This path requires website verification.
        email_row = conn.execute(
            "SELECT id FROM members WHERE lower(email)=? AND status='active'", (email,)
        ).fetchone()
        if email_row:
            raise FileExistsError(str(int(email_row["id"])))
        cur = conn.execute(
            """INSERT INTO members
               (full_name,email,phone,password_hash,created_at,status,country,preferred_airports)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                full_name,
                email,
                canonical,
                generate_password_hash(random_secret),
                now,
                "active",
                "IL",
                json.dumps(airports, ensure_ascii=False),
            ),
        )
        member_id = int(cur.lastrowid)
        conn.commit()
    ensure_whatsapp_link(member_id, phone)
    return member_id


def _first_name(member_id: int) -> str:
    name = (_member(member_id).get("full_name") or "").strip()
    return name.split()[0] if name else ""


def menu_text(member_id: int, *, linked_now: bool = False, created_now: bool = False) -> str:
    name = _first_name(member_id)
    hello = f"היי {name} 🌷" if name else "היי 🌷"
    if created_now:
        intro = "פתחתי לך חשבון באריאלה וקישרתי אותו ל-WhatsApp."
    elif linked_now:
        intro = "זיהיתי אותך לפי מספר הטלפון וקישרתי את ה-WhatsApp לחשבון שלך."
    else:
        intro = "זיהיתי אותך."
    return (
        f"{hello} {intro}\n"
        "מה תרצי לעשות?\n"
        "1. החופשות שלי\n"
        "2. חופשה חדשה\n"
        "3. להמשיך חופשה קיימת\n"
        "4. הדילים האחרונים\n\n"
        "אפשר גם פשוט לכתוב לי במילים חופשיות."
    )


def _vacation_text(member_id: int) -> str:
    trips = _vacations(member_id)
    if not trips:
        return "עדיין אין לך חופשות שמורות. כתבי „חופשה חדשה” כדי להתחיל."
    lines = ["החופשות שלך:"]
    for i, trip in enumerate(trips, 1):
        title = (trip.get("request_name") or f"חופשה {trip['id']}").strip()
        status = "פעילה" if trip.get("status") == "active" else "הסתיימה"
        lines.append(f"{i}. {title} — {status}")
    lines.append("\nכתבי את מספר החופשה כדי להמשיך אותה, או „חופשה חדשה”.")
    return "\n".join(lines)


def _start_onboarding(phone: str, profile_name: str = "") -> str:
    data = {}
    if profile_name:
        data["profile_name"] = str(profile_name).strip()[:120]
    _onboarding_set(phone, "name", data)
    suggestion = f" אני רואה ב-WhatsApp את השם „{data['profile_name']}”." if data.get("profile_name") else ""
    return (
        "היי, אני נובה מאריאלה 🌷\n"
        "לא מצאתי עדיין משתמש באריאלה עם מספר ה-WhatsApp הזה."
        f"{suggestion}\n"
        "בואי נפתח לך משתמש קצרצר כאן.\n"
        "מה השם המלא שתרצי שיופיע בחשבון?"
    )


def _onboarding_reply(phone: str, text: str, state: dict) -> str:
    normalized = (text or "").strip()
    lower = normalized.lower()
    if lower in NO:
        _onboarding_clear(phone)
        return "ביטלתי את הרישום. כשתרצי להתחיל שוב, פשוט כתבי לי „היי”."

    step = state["step"]
    data = dict(state.get("data") or {})

    if step == "name":
        if len(normalized) < 2 or len(normalized) > 120:
            return "כתבי לי בבקשה שם מלא קצר, למשל: כרמית כהן."
        data["full_name"] = normalized
        _onboarding_set(phone, "email", data)
        return f"נעים מאוד, {normalized.split()[0]} 🌷\nמה כתובת האימייל שלך?"

    if step == "email":
        email = normalized.lower()
        if not _valid_email(email):
            return "האימייל לא נראה תקין. נסי שוב, למשל name@example.com."
        with connection() as conn:
            existing = conn.execute(
                "SELECT id FROM members WHERE lower(email)=? AND status='active'", (email,)
            ).fetchone()
        if existing:
            _onboarding_clear(phone)
            return (
                "מצאתי שכבר קיים חשבון באריאלה עם האימייל הזה, אבל הוא רשום למספר טלפון אחר.\n"
                "מטעמי אבטחה אני לא אחבר אליו מספר חדש מתוך שיחת WhatsApp. "
                "היכנסי לחשבון באתר ועדכני שם את מספר הטלפון, ואז כתבי לי שוב."
            )
        data["email"] = email
        _onboarding_set(phone, "airport", data)
        return (
            "מאיזה שדה תעופה נוח לך לצאת בדרך כלל?\n"
            "אפשר לכתוב TLV / נתב״ג, HFA / חיפה, או כמה שדות מופרדים בפסיק."
        )

    if step == "airport":
        airports = _airport_codes(normalized)
        if not airports:
            return "לא הצלחתי לזהות את שדה התעופה. נסי למשל: TLV או חיפה."
        data["preferred_airports"] = airports
        _onboarding_set(phone, "consent", data)
        return (
            "כמעט סיימנו. כדי לפתוח את החשבון צריך לאשר את תנאי השימוש ומדיניות הפרטיות של אריאלה.\n"
            "כתבי „כן” לאישור או „לא” לביטול."
        )

    if step == "consent":
        if lower not in YES:
            return "כדי להמשיך כתבי „כן” לאישור התנאים, או „לא” לביטול."
        try:
            member_id = _create_member_from_whatsapp(phone, data)
        except FileExistsError:
            _onboarding_clear(phone)
            return (
                "בינתיים נוצר/נמצא חשבון עם האימייל הזה. "
                "היכנסי לאתר ועדכני את מספר הטלפון בחשבון, ואז כתבי לי שוב."
            )
        _onboarding_clear(phone)
        _set_state(member_id, "menu")
        return (
            menu_text(member_id, created_now=True)
            + "\n\nכדי להיכנס גם לאתר, בחרי „שכחתי סיסמה” עם האימייל שנתת וקבעי סיסמה."
        )

    _onboarding_clear(phone)
    return _start_onboarding(phone)


def route_inbound(phone: str, text: str, profile_name: str = "") -> str:
    """Route one verified inbound WhatsApp text message."""
    text = (text or "").strip()

    # 1) Existing explicit WA link wins.
    member_id = linked_member_for_phone(phone)
    if member_id:
        return _route_member(member_id, text)

    # 2) Before any browser handoff semantics, identify by registered phone.
    registered_id = registered_member_for_phone(phone)
    if registered_id:
        ensure_whatsapp_link(registered_id, phone)
        _onboarding_clear(phone)
        _set_state(registered_id, "menu")
        return menu_text(registered_id, linked_now=True)

    # 3) No DB phone match -> short onboarding/new user.
    state = _onboarding_get(phone)
    if state:
        return _onboarding_reply(phone, text, state)
    return _start_onboarding(phone, profile_name)


def _route_member(member_id: int, text: str) -> str:
    normalized = (text or "").strip().lower()

    if normalized in {"היי", "הי", "שלום", "hello", "hi", "תפריט", "menu", ""}:
        _set_state(member_id, "menu")
        return menu_text(member_id)

    if normalized in {"1", "החופשות שלי", "חופשות", "החופשות"}:
        _set_state(member_id, "my_vacations")
        return _vacation_text(member_id)

    if normalized in {"2", "חופשה חדשה", "חדשה", "תכנון חופשה"}:
        _set_state(member_id, "new_vacation")
        return (
            "מעולה. נתחיל חופשה חדשה ✈️\n"
            "איזה סוג חופשה?\n"
            "1. חופשה רגילה\n"
            "2. חופשת סקי\n"
            "3. נסיעת עסקים\n\n"
            "בגרסה הזו נובה מזהה ומנהלת את החשבון ב-WhatsApp; "
            "שאלון החופשה המלא ימשיך במנגנון המשותף לאתר בשלב N3."
        )

    if normalized in {"3", "להמשיך חופשה קיימת", "המשך חופשה", "להמשיך"}:
        _set_state(member_id, "continue_vacation")
        return _vacation_text(member_id)

    if normalized in {"4", "הדילים האחרונים", "דילים", "דילים אחרונים"}:
        _set_state(member_id, "latest_deals")
        return (
            "אני מחוברת לחשבון שלך. הדילים ב-WhatsApp משתמשים באותו דירוג ובאותו DB של האתר, "
            "בלי סריקה כפולה. בחרי קודם „החופשות שלי” כדי לבחור חופשה."
        )

    if normalized in {"עזרה", "help", "?"}:
        return "אפשר לכתוב: החופשות שלי, חופשה חדשה, להמשיך חופשה קיימת, הדילים האחרונים או תפריט."

    return "לא בטוחה למה התכוונת. כתבי „תפריט” ואציג את האפשרויות."
