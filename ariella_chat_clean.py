import json
import os
import requests
from flask import Blueprint, jsonify, request
from travel_agents import _member_context, _openai_json, _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'live-chat-v7'

CHAT_SYSTEM = '''את אריאלה, סוכנת נסיעות אישית. דברי עם המשתמשת כמו שיחת ChatGPT טבעית, חכמה וגמישה בעברית.

המטרה שלך היא השיחה עצמה. אין לך שאלון, שלבים, שדות חובה, רשימת מידע חסר או סדר איסוף נתונים.
התגובה שלך נקבעת רק לפי מה שהמשתמשת אמרה ושאלה בשיחה.

כללים:
- אם המשתמשת שואלת שאלה — עני עליה קודם ובאופן ממשי.
- אם היא משתפת רעיון — הגיבי לרעיון ופתחי אותו באופן טבעי.
- אם היא מתלבטת — עזרי לה להשוות ולהחליט.
- אם היא משנה פרט — קבלי את השינוי והמשיכי ממנו.
- אל תשאלי שוב פרט שכבר נאמר.
- אל תנסי להשלים יעד, תאריך, נוסעים, תקציב, כבודה או העדפות טיסה רק משום שהם עדיין לא ידועים.
- אל תעברי אוטומטית לנושא הבא בתכנון החופשה.
- אפשר לשאול שאלת המשך אחת רק כשהיא באמת המשך טבעי ומועיל למה שנאמר עכשיו. אין חובה לסיים בשאלה.
- אל תכתבי תשובת פתיחה קבועה ואל תחזרי על אותו נוסח משיחה לשיחה.
- אל תגידי שאת מחפשת טיסות או מבצעת חיפוש אלא אם המערכת הודיעה במפורש שהחיפוש התחיל.

דוגמאות להתנהגות, לא טקסט להעתקה:
"בא לי לטוס עם הבת שלי" — התייחסי לחופשה משותפת של אמא ובת. אפשר לברר איזה אופי חופשה בא להן, אבל לא לקפוץ לכבודה/קונקשן/תקציב/רשימת שאלות.
"צפון איטליה" ואז "מתי את ממליצה?" — עני מתי מומלץ לנסוע לצפון איטליה ומה היתרונות של התקופות השונות. אל תשאלי אותה מתי היא רוצה לטוס.
"מה יותר מתאים עם ילדים, צפון איטליה או אוסטריה?" — עני על ההשוואה עצמה.

החזירי רק את הטקסט הטבעי שהלקוחה צריכה לראות. אין JSON ואין שדות פנימיים.'''

EXTRACT_SYSTEM = '''את טינקרבל, מנגנון רקע שקט. אינך מדברת עם הלקוח ואינך מנהלת את השיחה.
חלצי רק עובדות שימושיות שנאמרו בפועל בשיחה ועדכני אותן ב-profile_patch. תיקון מאוחר גובר על מידע קודם. אל תנחשי ואל תייצרי שאלות.
אפשר לחלץ בין היתר יעד, תאריכים/חודש, נוסעים וילדים, תקציב, כבודה, העדפת טיסה ישירה/קונקשן, גמישות, סגנון חופשה ושירותים שהתבקשו.
ready_for_search הוא אות פנימי בלבד: true רק כאשר כבר יש מספיק מידע לביצוע חיפוש ממשי. הוא לעולם אינו משפיע על ניסוח התשובה של אריאלה.
החזירי JSON בלבד עם profile_patch ו-ready_for_search.'''


def _patch(value):
    return {k: v for k, v in value.items() if v is not None} if isinstance(value, dict) else {}


def _seed(profile):
    if profile.get('live_member_loaded'):
        return profile
    out = dict(profile)
    try:
        member = _member_context()
    except Exception:
        member = None
    if member:
        if member.get('gender') and not out.get('customer_gender'):
            out['customer_gender'] = member.get('gender')
        out.setdefault('known_companions', member.get('companions') or [])
    out['live_member_loaded'] = True
    return out


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


def _call_ariella_text(key, model, history, message):
    payload = {
        'model': model,
        'input': [{'role': 'developer', 'content': CHAT_SYSTEM}] + _conversation(history[-24:], message),
        'max_output_tokens': 700,
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


def _call_extractor(key, model, history, message, profile):
    return _openai_json(
        key,
        model,
        EXTRACT_SYSTEM + '\nפרופיל קיים לצורך עדכון פנימי בלבד:\n' + json.dumps(profile, ensure_ascii=False),
        _conversation(history[-24:], message),
        max_output_tokens=300,
    )


@ariella_chat_clean.post('/api/ariella/chat-clean')
def chat_clean():
    body = request.get_json(silent=True) or {}
    message = str(body.get('message') or '').strip()
    if not message:
        return jsonify({'status': 'error', 'message': 'message is required', 'engine_version': ENGINE_VERSION}), 400

    history = body.get('history') if isinstance(body.get('history'), list) else []
    profile = _seed(body.get('profile') if isinstance(body.get('profile'), dict) else {})
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return jsonify({'status': 'error', 'message': 'אריאלה לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    model = os.getenv('ARIELLA_MODEL', 'gpt-5.6-luna').strip()

    # Ariella is a plain conversational model call. It receives conversation only.
    # No JSON schema, trip profile, readiness, missing fields or Tinkerbell output
    # can influence the customer-facing response.
    try:
        reply = _call_ariella_text(key, model, history, message)
    except Exception:
        return jsonify({'status': 'error', 'message': 'אריאלה לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    reply = reply or 'אני איתך 😊'

    # Tinkerbell is a completely separate structured extraction pass.
    extraction = {}
    try:
        extraction = _call_extractor(key, model, history, message, profile)
        extraction = extraction if isinstance(extraction, dict) else {}
    except Exception:
        extraction = {}

    merged = dict(profile)
    merged.update(_patch(extraction.get('profile_patch')))
    return jsonify({
        'status': 'success',
        'agent': 'Ariella',
        'engine_version': ENGINE_VERSION,
        'reply': reply,
        'profile': merged,
        'ready_for_search': bool(extraction.get('ready_for_search')),
    })
