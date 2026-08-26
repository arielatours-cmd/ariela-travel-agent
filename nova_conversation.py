"""NOVA N2 — inbound WhatsApp conversation router."""
from __future__ import annotations
import hashlib, re
from database import connection, utc_now_iso
from nova_whatsapp import NovaHandoffError, consume_member_handoff

TOKEN_RE = re.compile(r"קוד\s*חיבור\s*:\s*([^\s]+)", re.I)

def _digits(value):
    return re.sub(r"\D", "", value or "")

def _phone_hash(phone):
    return hashlib.sha256(_digits(phone).encode("utf-8")).hexdigest()

def linked_member_for_phone(phone):
    h=_phone_hash(phone)
    if not h: return None
    with connection() as conn:
        row=conn.execute("SELECT member_id FROM whatsapp_member_links WHERE wa_phone_hash=? AND status='active'",(h,)).fetchone()
    return int(row['member_id']) if row else None

def _member(member_id):
    with connection() as conn:
        row=conn.execute("SELECT id,full_name FROM members WHERE id=? AND status='active'",(member_id,)).fetchone()
    return dict(row) if row else {"id":member_id,"full_name":""}

def _vacations(member_id, limit=5):
    with connection() as conn:
        rows=conn.execute("SELECT id,request_name,status,answers_json FROM trip_requests WHERE member_id=? ORDER BY id DESC LIMIT ?",(member_id,limit)).fetchall()
    return [dict(r) for r in rows]

def _set_state(member_id, intent, trip_id=None):
    now=utc_now_iso()
    with connection() as conn:
        conn.execute('''INSERT INTO whatsapp_conversation_state(member_id,active_trip_id,current_intent,last_message_at,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(member_id) DO UPDATE SET active_trip_id=excluded.active_trip_id,current_intent=excluded.current_intent,last_message_at=excluded.last_message_at,updated_at=excluded.updated_at''',(member_id,trip_id,intent,now,now))
        conn.commit()

def welcome(member_id):
    name=(_member(member_id).get('full_name') or '').strip().split(' ')[0]
    hello=f"היי {name} 🌷" if name else "היי 🌷"
    return hello+" החיבור לאריאלה הושלם בהצלחה.\nמה תרצי לעשות?\n1. החופשות שלי\n2. חופשה חדשה\n3. להמשיך חופשה קיימת\n4. הדילים האחרונים\n\nאפשר גם פשוט לכתוב לי במילים חופשיות."

def _vacation_text(member_id):
    trips=_vacations(member_id)
    if not trips: return "עדיין אין לך חופשות שמורות. כתבי ‘חופשה חדשה’ כדי להתחיל."
    lines=["החופשות שלך:"]
    for i,t in enumerate(trips,1):
        title=(t.get('request_name') or f"חופשה {t['id']}").strip()
        status="פעילה" if t.get('status')=='active' else "הסתיימה"
        lines.append(f"{i}. {title} — {status}")
    lines.append("\nכתבי את מספר החופשה כדי להמשיך אותה, או ‘חופשה חדשה’.")
    return "\n".join(lines)

def route_inbound(phone, text):
    text=(text or '').strip()
    match=TOKEN_RE.search(text)
    if match:
        try:
            member_id=consume_member_handoff(match.group(1), phone)
        except NovaHandoffError as exc:
            return f"לא הצלחתי להשלים את החיבור: {exc}"
        _set_state(member_id,'menu')
        return welcome(member_id)

    member_id=linked_member_for_phone(phone)
    if not member_id:
        return "היי, אני נובה מאריאלה 🌷 כדי שאזהה את החופשות שלך, התחברי פעם אחת דרך הכפתור ‘אריאלה בנייד’ באזור האישי באתר."

    normalized=text.lower()
    if normalized in {'היי','הי','שלום','hello','hi','תפריט','menu'}:
        _set_state(member_id,'menu'); return welcome(member_id)
    if normalized in {'1','החופשות שלי','חופשות','החופשות'}:
        _set_state(member_id,'my_vacations'); return _vacation_text(member_id)
    if normalized in {'2','חופשה חדשה','חדשה','תכנון חופשה'}:
        _set_state(member_id,'new_vacation')
        return "מעולה. נתחיל חופשה חדשה ✈️\nאיזה סוג חופשה?\n1. חופשה רגילה\n2. חופשת סקי\n3. נסיעת עסקים"
    if normalized in {'3','להמשיך חופשה קיימת','המשך חופשה','להמשיך'}:
        _set_state(member_id,'continue_vacation'); return _vacation_text(member_id)
    if normalized in {'4','הדילים האחרונים','דילים','דילים אחרונים'}:
        _set_state(member_id,'latest_deals')
        return "אני מחוברת לחשבון שלך. בשלב הבא אציג כאן את הדילים המדורגים של החופשה שבחרת — מאותו מנגנון של האתר, בלי סריקה כפולה. כרגע אפשר לבחור ‘החופשות שלי’ ולהמשיך משם."
    if normalized in {'עזרה','help','?'}:
        return "אפשר לכתוב: החופשות שלי, חופשה חדשה, להמשיך חופשה קיימת, הדילים האחרונים או תפריט."
    return "הבנתי אותך. כרגע אפשר לבחור: 1 החופשות שלי · 2 חופשה חדשה · 3 המשך חופשה · 4 הדילים האחרונים."
