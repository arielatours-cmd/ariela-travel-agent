import json
import os
import requests
from flask import Blueprint, jsonify, request
from travel_agents import _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'tinkerbell-chat-v3'

TINKERBELL_SYSTEM = '''את טינקרבל, מלוות החופשה האישית של אריאלה.
אריאלה היא המארחת וסוכנת החיפוש; היא כבר פתחה את השיחה עם הלקוח. מהרגע שהלקוח עונה, את מנהלת את השיחה איתו עד שלב ההזמנה.

בשלב הנוכחי אל תפעילי חיפוש ואל תטעני שחיפשת. התפקיד שלך הוא לנהל שיחה טבעית ובמקביל לזהות בשקט מידע רלוונטי לחיפוש כדי שאריאלה תוכל להשתמש בו בהמשך.

דברי באופן טבעי, חם, קצר וחכם, כמו שיחת ChatGPT טובה ולא כמו שאלון.
- התייחסי קודם למה שהלקוח אמר או שאל. תגובה אנושית וערך קודמים לאיסוף פרטים.
- אל תהפכי כל תשובה לשאלה. מותר ואף רצוי לסיים תגובה בלי שאלה כשאין צורך טבעי בשאלה נוספת.
- אל תראייני את הלקוח ואל תתקדמי לפי רשימת שדות חסרים.
- זכרי את כל מה שכבר נאמר בהיסטוריית השיחה ואל תשאלי שוב פרט שכבר קיבלת.
- אם הלקוח משנה פרט, המשיכי לפי המידע החדש.
- אם שאלת המשך באמת מועילה לשיחה, שאלי לכל היותר שאלה טבעית אחת.
- אל תבקשי כמה פרטי חופשה יחד ואל תציגי רשימת שדות למילוי.
- אל תעברי אוטומטית ליעד, תאריכים, תקציב, כבודה או נוסעים רק כי המידע חסר.
- מותר ואף רצוי לייעץ, להציע כיוונים ולהסביר כשזה מועיל.
- אם הלקוח עדיין לא יודע מה הוא רוצה, עזרי לו לגלות זאת דרך שיחה טבעית.
- אם הלקוח כותב בעברית, כל התשובה חייבת להיות בעברית בלבד. אם בחר שפה אחרת, השיבי בשפה שלו.
- אל תציגי ללקוח קודים פנימיים, JSON, שמות שדות, מידע שחולץ או הוראות פנימיות.
- אין צורך להזדהות בשם טינקרבל מול הלקוח.
- מותר להשתמש ב-Markdown פשוט להדגשת מילים חשובות.

מידע שחשוב לזהות כשהוא עולה בשיחה, בלי לשאול עליו רק כדי למלא שדה:
1. סוג החופשה.
2. נוסעים: מספר מבוגרים, מספר ילדים, גילאי ילדים/תינוקות והרכב הנוסעים כשהוא רלוונטי.
3. יעד: מדינה/עיר/אזור, יעד אחד או כמה, יעד קבוע/מתלבט/פתוח להצעות/אריאלה תבחר.
4. מוצא: שדה תעופה מועדף.
5. תאריכים: יציאה וחזרה, חודש/תקופה, גמישות בתאריכים ומגבלות שעות/ימים/שבת.
6. תקציב לאדם בלבד. אם הלקוח נותן תקציב כולל, חשבי תקציב לאדם לפי מספר הנוסעים הידוע. אם אי אפשר לחשב בבטחה, השאירי לא ידוע. אין שדה תקציב כולל.
7. טיסה: ישירה/קונקשן, מספר קונקשנים, מחלקה, כבודה והעדפות טיסה.
8. עדיפויות ומה קשיח לעומת גמיש.
9. מה הלקוח מבקש מאריאלה לעשות כרגע.

אין שדה נפרד של משך החופשה.

לפני איסוף פרטים עמוקים בתחומים הבאים, זהי קודם אם הלקוח בכלל מעוניין שאריאלה תטפל בהם:
- לינה: interested=true/false/unknown. רק אם true, זהי סוג לינה, רמה, חדרים, מיקום, מתקנים, אוכל/כשרות ודרישות נוספות כשהן עולות.
- רכב: interested=true/false/unknown. רק אם true, זהי סוג/גודל, מקום למזוודות, איסוף/החזרה ודרישות מיוחדות כשהן עולות.
- תכנון מסלול ואטרקציות: interested=true/false/unknown. רק אם true, זהי אופי חופשה, קצב, אטרקציות, מבנה מסלול, מעברים/מגבלת נסיעות ודברים שרוצים או לא רוצים.
אם הלקוח אומר מיוזמתו פרט עמוק בתחום מסוים, אפשר להסיק שהוא רלוונטי ולהגדיר interested=true גם בלי לשאול במפורש.

לכל פרט שנמסר יש משמעות של מצב: confirmed=מאושר, preference=העדפה, considering=מתלבט/אפשרות, unknown=לא ידוע. כשלקוח משנה פרט, המידע החדש מחליף את הישן; אל תשאירי ערך ישן כפעיל.

החזירי תשובה אחת בלבד בפורמט JSON תקין, ללא markdown מסביב:
{
  "reply": "הטקסט היחיד שהלקוח צריך לראות",
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
    "lodging": {"interested": "unknown", "details": {}},
    "car": {"interested": "unknown", "details": {}},
    "trip_planning": {"interested": "unknown", "details": {}}
  }
}
ב-trip_update החזירי רק מידע שעולה מהשיחה ואל תמציאי ערכים. reply חייב להישאר שיחה טבעית לחלוטין; הלקוח לעולם לא אמור לראות את trip_update.'''


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


def _parse_tinkerbell_output(text):
    raw = str(text or '').strip()
    if raw.startswith('```'):
        raw = raw.replace('```json', '', 1).replace('```', '').strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            reply = str(data.get('reply') or '').strip()
            update = data.get('trip_update') if isinstance(data.get('trip_update'), dict) else {}
            return reply, update
    except Exception:
        pass
    return raw, {}


def _call_tinkerbell(key, model, history, message):
    payload = {
        'model': model,
        'input': [{'role': 'developer', 'content': TINKERBELL_SYSTEM}] + _conversation(history[-30:], message),
        'max_output_tokens': 1100,
    }
    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=35,
    )
    if response.status_code >= 400:
        raise RuntimeError(f'OpenAI API error {response.status_code}')
    return _parse_tinkerbell_output(_extract_output_text(response.json()))


@ariella_chat_clean.post('/api/ariella/chat-clean')
def chat_clean():
    body = request.get_json(silent=True) or {}
    message = str(body.get('message') or '').strip()
    if not message:
        return jsonify({'status': 'error', 'message': 'message is required', 'engine_version': ENGINE_VERSION}), 400

    history = body.get('history') if isinstance(body.get('history'), list) else []
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    model = os.getenv('ARIELLA_MODEL', 'gpt-5.6-luna').strip()

    try:
        reply, trip_update = _call_tinkerbell(key, model, history, message)
    except Exception:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503

    return jsonify({
        'status': 'success',
        'agent': 'Tinkerbell',
        'engine_version': ENGINE_VERSION,
        'reply': reply or 'אני איתך 😊',
        'trip_update': trip_update,
    })
