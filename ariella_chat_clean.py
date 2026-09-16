import json
import os
from flask import Blueprint, jsonify, request
from travel_agents import _member_context, _openai_json, _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'live-chat-v6'

CHAT_SYSTEM = '''את אריאלה, סוכנת נסיעות אישית שמנהלת שיחה חופשית וטבעית בעברית כמו ChatGPT.

את מנהלת שיחה — לא שאלון ולא טופס איסוף נתונים.
הגיבי קודם כל למשמעות של ההודעה האחרונה בתוך ההקשר של השיחה.
אם נשאלה שאלה — עני עליה. אם המשתמשת מתלבטת — עזרי לה. אם היא משתפת רעיון — פתחי אותו איתה. אם היא משנה את דעתה — המשיכי מהשינוי.

אין לך גישה לרשימת שדות חסרים, לשלבים, ל-readiness או לפרופיל החיפוש. אל תנסי להשלים אותם.
אין סדר קבוע של יעד, תאריכים, נוסעים, תקציב, טיסה או כבודה.
אל תשאלי פרט רק משום שהוא עדיין לא נאמר.
מותר לשאול שאלה אחת כאשר היא המשך טבעי של מה שנאמר עכשיו, ומותר גם לענות בלי שאלה.
לעולם אל תשאלי שוב מידע שכבר נאמר בשיחה.
אל תציגי אפשרויות של שאלון אלא אם המשתמשת ביקשה אפשרויות או המלצה.

דוגמאות עקרוניות:
- "בא לי לטוס עם הבת שלי" הוא פתיחת שיחה על חופשה של שתיהן. הגיבי לזה; אל תקפצי לכבודה, קונקשן, תקציב או רשימת פרטים חסרים.
- אם נאמר "צפון איטליה" ואז נשאל "מתי את ממליצה?" — עני מתי מומלץ לנסוע לצפון איטליה והסבירי את ההבדלים בין התקופות. אל תשאלי מתי המשתמשת רוצה לטוס.
- אם נאמר "בעצם אולי מונטנגרו" — הביני שזה שינוי כיוון והמשיכי לדבר עליו טבעית.
- אם נשאל "מה יותר מתאים עם ילדים, צפון איטליה או אוסטריה?" — עני על ההשוואה לפני כל ניסיון להתקדם לחיפוש.

החזירי JSON בלבד בפורמט {"reply":"תשובתך"}.'''

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


def _call(key, model, system, history, message, tokens):
    return _openai_json(key, model, system, _conversation(history[-24:], message), max_output_tokens=tokens)


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

    # Customer-facing Ariella sees only the conversation. Search/profile state is
    # deliberately not supplied to this call, so it cannot drive the next reply.
    try:
        chat = _call(key, model, CHAT_SYSTEM, history, message, 650)
    except Exception:
        return jsonify({'status': 'error', 'message': 'אריאלה לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    chat = chat if isinstance(chat, dict) else {}
    reply = str(chat.get('reply') or '').strip() or 'אני איתך 😊'

    # Tinkerbell runs independently after the reply and only updates structured
    # state for future search/persistence. Its output never feeds Ariella's reply.
    extraction = {}
    try:
        extraction = _call(
            key,
            model,
            EXTRACT_SYSTEM + '\nפרופיל קיים לצורך עדכון פנימי בלבד:\n' + json.dumps(profile, ensure_ascii=False),
            history,
            message,
            300,
        )
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
