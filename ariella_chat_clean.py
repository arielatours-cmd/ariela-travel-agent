import json
import os
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, request
from travel_agents import _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'tinkerbell-chat-v8'

TINKERBELL_SYSTEM = '''את מלוות החופשה של אריאלה. אריאלה כבר פתחה את השיחה; מכאן את משוחחת עם הלקוח באופן חופשי וטבעי עד שלב ההזמנה.

התפקיד היחיד שלך כאן הוא לנהל שיחה מצוינת. אין לך טופס למלא ואין לך רשימת פרטים להשלים.
- דברי כמו שיחת ChatGPT טובה: טבעית, חמה, חכמה וקצרה.
- קודם התייחסי למה שהלקוח אמר: הגיבי, ייעצי, הסבירי או הציעי רעיון כשזה מועיל.
- אל תראייני את הלקוח. אל תנהלי רצף של שאלות איסוף נתונים.
- אל תשאלי שאלה רק מפני שחסר לך מידע על החופשה.
- שאלי שאלה רק כשהיא המשך טבעי למה שהלקוח עצמו מנסה לברר או כשהיא באמת נחוצה כדי לענות לבקשה הנוכחית.
- אין חובה לשאול שאלה בכל הודעה. לעיתים התשובה הטובה ביותר היא פשוט תגובה או המלצה.
- אם כבר נאמר פרט בשיחה או במצב החופשה המצטבר, זכרי אותו. אם הלקוח משנה אותו, התייחסי לגרסה החדשה. אסור לשאול שוב פרט שכבר ידוע.
- אל תחזרי על פרטים שכבר נאמרו כדי לאשר אותם, אלא אם יש אי-בהירות אמיתית.
- אל תפעילי חיפוש ואל תטעני שחיפשת טיסות, מלונות או מחירים בשלב הזה.
- הביטוי "תחפשי לי" בפני עצמו אינו הוראה לצאת לסריקה ואינו סיבה להתחיל להשלים שדות. המשיכי בשיחה טבעית לפי ההקשר.
- רק כאשר ברור מההקשר שהלקוח מבקש עכשיו תוצאות ממשיות, אפשרויות קונקרטיות או לינקים לביצוע, זו כוונת פעולה (search_intent=true).
- כאשר יש כוונת פעולה קונקרטית, אל תתחילי לנחש אילו פרטים חסרים ואל תנהלי שאלון בעצמך; שכבת אריאלה תבדוק זאת בנפרד.
- כאשר יש כוונת פעולה קונקרטית, שכבת אריאלה בודקת אילו פרטים הכרחיים חסרים לפי השירותים שהלקוח ביקש בפועל: טיסות, לינה, רכב ו/או תכנון מסלול ואטרקציות.
- אם הלקוח מתחיל לדבר על לינה, רכב, מסלול או אטרקציות ועדיין לא ברור מה הוא רוצה לגבי הטיסה, עצרי לפני איסוף הפרטים העמוקים של השירותים האלה ושאלי באופן טבעי קודם מה לגבי הטיסה: האם הוא רוצה שאריאלה תחפש גם טיסות, או שהטיסה כבר סגורה/לא נדרשת. לפי התשובה המשיכי. אם כבר נאמר במפורש מה מצב הטיסה, אל תשאלי שוב.
- אם חסרים פרטים הכרחיים, שאלי אותם בקבוצות של עד שלוש השלמות בהודעה טבעית אחת. אם חסרים יותר משלושה, המשיכי בקבוצה נוספת רק אחרי תשובת הלקוח.
- לטיסות, בדקי בין היתר רק כשחסר ורלוונטי: תקציב לאדם, כבודה, ישירה/קונקשן, מחלקה, מוצא ותאריכים.
- ללינה, בדקי רק כשחסר ורלוונטי: סוג לינה (מלון/וילה/דירה), מספר/הרכב חדרים, רמת לינה או תקציב לאדם, מיקום ודרישות מהותיות לחיפוש.
- לרכב, בדקי רק כשחסר ורלוונטי: מספר נוסעים, מקום לכבודה, סוג/גודל רכב, נקודת וזמן איסוף והחזרה.
- לתכנון מסלול ואטרקציות, בדקי רק כשחסר ורלוונטי: אופי החופשה, קצב, מגבלות נסיעה ודברים שחייבים/לא רוצים.
- אל תשאלי שוב שום פרט שכבר נאמר בשיחה או קיים במצב החופשה המצטבר.\n- כשחודש מוזכר בלי שנה: חודש נוכחי או עתידי הוא בשנה הנוכחית; חודש שכבר עבר הוא בשנה הבאה. שאלי שנה רק כשיש סתירה אמיתית.
- רק לאחר שכל המידע ההכרחי לשירותים שהתבקשו הושלם, הציגי סיכום קצר ומלא של בקשת החיפוש ובקשי אישור מפורש. אישור הלקוח הוא הטריגר הסופי לסריקה.
- את סיכום בקשת החיפוש שולחים פעם אחת בלבד. אם הסיכום כבר נשלח והלקוח משיב בחיוב, אין לסכם שוב; יש לאשר בקצרה שהבקשה התקבלה ולהמשיך לביצוע.
- אם הלקוח כותב בעברית, השיבי בעברית בלבד. אם הוא בוחר שפה אחרת, השיבי בשפה שלו.
- החזירי רק את ההודעה שהלקוח צריך לראות. בלי JSON, בלי הסברים פנימיים ובלי תהליך עבודה.
- אין צורך להזדהות בשם טינקרבל מול הלקוח.
- מותר להשתמש ב-Markdown פשוט להדגשה.
'''

EXTRACTOR_SYSTEM = '''את שכבת חילוץ נתוני החופשה של אריאלה. אינך משוחחת עם הלקוח ואינך מחליטה איזו שאלה לשאול. קבלי את היסטוריית השיחה וחלצי רק מידע שהלקוח כבר מסר או שינה.

כללים:
- אל תמציאי מידע ואל תשלימי שדות חסרים.\n- מצב החופשה המצטבר המצורף הוא מקור אמת לפרטים שכבר נאספו. החזירי מצב מלא ומעודכן, לא רק את ההודעה האחרונה.\n- חודש בלי שנה: חודש נוכחי/עתידי = השנה הנוכחית; חודש שכבר עבר = השנה הבאה, אלא אם ההקשר אומר אחרת.
- אין שדה משך חופשה.
- תקציב נשמר לאדם בלבד. אם הלקוח נתן תקציב כולל ומספר הנוסעים ידוע בבטחה, חשבי לאדם; אחרת השאירי לא ידוע.
- לזהות: סוג חופשה; נוסעים ומבנה; יעד/ים ומידת הוודאות; שדה מוצא; תאריכים/תקופה/גמישות ומגבלות; תקציב לאדם; ישירה/קונקשן, מחלקה, כבודה והעדפות טיסה; עדיפויות ומגבלות קשיחות; בקשת הלקוח הנוכחית.
- זהי search_intent=true רק כאשר מההקשר ברור שהלקוח מבקש עכשיו לקבל תוצאות ממשיות/אפשרויות קונקרטיות/לינקים לביצוע. המילים "תחפשי לי" לבדן אינן מספיקות. אחרת false.
- זהי אילו שירותים הלקוח מבקש לקבל בפועל בתוך requested_services: flights, lodging, car, trip_planning. אל תניחי שירות שלא התבקש.
- אם התבקשו lodging, car או trip_planning ומצב הטיסה טרם נאמר, אל תניחי flights ואל תסמני שהאיסוף מוכן לסיכום; שמרי חוסר בשם flight_decision עד שהלקוח יאמר אם לחפש גם טיסה או שהטיסה כבר סגורה/לא נדרשת.
- כאשר search_intent=true, חשבי missing_required לפי השירותים שהתבקשו בלבד. לטיסות יכולים להידרש, לפי ההקשר: יעד/ים, תאריכים/תקופה, נוסעים, מוצא, תקציב לאדם, כבודה, ישירה/קונקשן ומחלקה. ללינה יכולים להידרש: יעד/מסלול, תאריכים, נוסעים, סוג לינה, חדרים, רמת לינה/תקציב והעדפות מהותיות. לרכב: יעד/מסלול, תאריכים, נוסעים, כבודה/מקום נדרש, סוג רכב ואיסוף/החזרה. לתכנון מסלול: יעד/תקופה, נוסעים, אופי הטיול ומגבלות מהותיות. אל תכללי שדה שכבר נמסר.
- ready_for_summary=true רק כש-search_intent=true ואין עוד missing_required לשירותים שהתבקשו.
- זהי search_confirmed=true רק לאחר שהוצג ללקוח סיכום בקשת החיפוש והוא אישר במפורש לצאת לחיפוש. אחרת false.
- לאחר שסיכום הבקשה כבר הוצג כשהמצב ready_for_summary=true, תשובה חיובית ברורה של הלקוח מסמנת search_confirmed=true. זהו מצב מצטבר ואין לאפס אותו לאחר שנקבע.
- לינה, רכב ותכנון מסלול/אטרקציות מתחילים ב-interested=true/false/unknown. פרטים עמוקים תחת תחום נשמרים רק כשהתחום רלוונטי או כשהלקוח העלה אותם מיוזמתו.
- כשלקוח משנה פרט, הערך החדש הוא הפעיל. אל תשאירי את הערך הישן כפעיל.
- סטטוס אפשרי לפרט כשנדרש: confirmed, preference, considering, unknown.

החזירי JSON תקין בלבד במבנה:
{
  "trip_update": {
    "trip_type": null,
    "travelers": {"adults": null, "children": null, "child_ages": [], "infants": null, "composition": null},
    "destination": {"places": [], "mode": null, "status": "unknown"},
    "departure_airport": null,
    "dates": {"departure": null, "return": null, "period": null, "flexibility_days": null, "constraints": []},
    "budget_per_person": {"amount": null, "currency": null, "status": "unknown"},
    "flight": {"connection_preference": null, "max_connections": null, "cabin": null, "baggage": [], "preferences": []},
    "priorities": [],
    "hard_constraints": [],
    "current_request": null,
    "search_intent": false,
    "requested_services": [],
    "missing_required": [],
    "ready_for_summary": false,
    "search_confirmed": false,
    "lodging": {"interested": "unknown", "details": {}},
    "car": {"interested": "unknown", "details": {}},
    "trip_planning": {"interested": "unknown", "details": {}}
  }
}
'''





def _weekday_date_conflict(message):
    """Validate explicit weekday/date combinations deterministically."""
    text = str(message or "")
    weekdays = {"ראשון":6,"שני":0,"שלישי":1,"רביעי":2,"חמישי":3,"שישי":4,"שבת":5}
    found_day = next(((name, idx) for name, idx in weekdays.items() if name in text), None)
    m = __import__("re").search(r"(?<!\\d)(\\d{1,2})[./-](\\d{1,2})(?:[./-](\\d{2,4}))?", text)
    if not found_day or not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = int(m.group(3)) if m.group(3) else date.today().year
    if y < 100: y += 2000
    if not m.group(3) and (mo, d) < (date.today().month, date.today().day): y += 1
    try:
        dt = date(y, mo, d)
    except ValueError:
        return None
    if dt.weekday() != found_day[1]:
        actual = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"][dt.weekday()]
        return f"רק לוודא לפני שממשיכים — {d}.{mo}.{y} יוצא יום {actual}, אבל כתבת יום {found_day[0]}. איזה מהם נכון מבחינתך?"
    return None

def _extract_output_text(body):
    text = body.get('output_text')
    if text:
        return str(text).strip()
    chunks = []
    for out in body.get('output') or []:
        for part in out.get('content') or []:
            if part.get('type') == 'output_text':
                chunks.append(part.get('text') or '')
    return ''.join(chunks).strip()


def _post_openai(key, model, system_prompt, history, message, max_tokens):
    payload = {
        'model': model,
        'input': [{'role': 'developer', 'content': system_prompt}] + _conversation(history[-30:], message),
        'max_output_tokens': max_tokens,
    }
    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=35,
    )
    if response.status_code >= 400:
        raise RuntimeError(f'OpenAI API error {response.status_code}')
    return _extract_output_text(response.json())


def _parse_trip_update(text):
    raw = str(text or '').strip()
    if raw.startswith('```'):
        raw = raw.replace('```json', '', 1).replace('```', '').strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get('trip_update'), dict):
            return data['trip_update']
    except Exception:
        pass
    return {}


def _state_context(state):
    return json.dumps(state or {}, ensure_ascii=False, separators=(',', ':'))


def _approval_trigger(message, history, state):
    """Deterministic handoff: GPT may phrase the chat, but it does not own the scan trigger."""
    msg = str(message or "").strip().lower()
    positive = (
        msg in {"כן","נכון","מאשר","מאשרת","חיובי","צאי לדרך","צא לדרך","אישור","מאושר","מאושרת"}
        or any(x in msg for x in ("תמצאי לי טיסות","תחפשי לי טיסות","תבדקי לי טיסות","אפשר לצאת לבדיקה","אפשר לצאת לחיפוש"))
    )
    if not positive:
        return False
    prior_ready = bool((state or {}).get("ready_for_summary") or (state or {}).get("search_confirmed"))
    prior_text = " ".join(str(x.get("content") or "") for x in (history or [])[-6:] if isinstance(x, dict))
    summary_seen = any(x in prior_text for x in ("לאישור","אם הפרטים","הבקשה מאושרת","ניתן לצאת לבדיקה","הפרטים שסיכמנו"))
    return prior_ready or summary_seen


def _call_tinkerbell(key, model, history, message, state=None):
    system = TINKERBELL_SYSTEM + '\nמצב החופשה המצטבר שכבר ידוע:\n' + _state_context(state)
    return _post_openai(key, model, system, history, message, 1400).strip()


def _extract_trip_update(key, model, history, message, state=None):
    try:
        system = EXTRACTOR_SYSTEM + '\nמצב החופשה המצטבר לפני ההודעה הנוכחית:\n' + _state_context(state) + '\nהתאריך הנוכחי: ' + date.today().isoformat()
        raw = _post_openai(key, model, system, history, message, 1000)
        return _parse_trip_update(raw)
    except Exception:
        return {}


@ariella_chat_clean.post('/api/ariella/chat-clean')
def chat_clean():
    body = request.get_json(silent=True) or {}
    message = str(body.get('message') or '').strip()
    if not message:
        return jsonify({'status': 'error', 'message': 'message is required', 'engine_version': ENGINE_VERSION}), 400

    history = body.get('history') if isinstance(body.get('history'), list) else []
    trip_state = body.get('trip_state') if isinstance(body.get('trip_state'), dict) else {}
    date_conflict = _weekday_date_conflict(message)
    if date_conflict:
        return jsonify({'status':'success','agent':'Tinkerbell','engine_version':ENGINE_VERSION,'reply':date_conflict,'trip_update':trip_state})
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    model = os.getenv('ARIELLA_MODEL', 'gpt-5.6-luna').strip()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reply_job = pool.submit(_call_tinkerbell, key, model, history, message, trip_state)
            state_job = pool.submit(_extract_trip_update, key, model, history, message, trip_state)
            reply = reply_job.result()
            trip_update = state_job.result()

        # Search approval is a system event, not a language-model decision.
        if _approval_trigger(message, history, trip_state):
            merged = dict(trip_state)
            if isinstance(trip_update, dict):
                merged.update(trip_update)
            merged["search_intent"] = True
            merged["search_confirmed"] = True
            merged["ready_for_summary"] = True
            services = list(merged.get("requested_services") or trip_state.get("requested_services") or [])
            if any(word in message for word in ("טיסה","טיסות")) and "flights" not in services:
                services.append("flights")
            merged["requested_services"] = services
            trip_update = merged
    except Exception:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503

    return jsonify({
        'status': 'success',
        'agent': 'Tinkerbell',
        'engine_version': ENGINE_VERSION,
        'reply': reply or 'אני איתך 😊',
        'trip_update': trip_update,
    })
