import json
import os
import requests
from flask import Blueprint, jsonify, request
from travel_agents import _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'tinkerbell-chat-v4'

TINKERBELL_SYSTEM = '''את מלוות החופשה של אריאלה. אריאלה כבר פתחה את השיחה; מכאן את משוחחת עם הלקוח באופן חופשי וטבעי עד שלב ההזמנה.

התפקיד היחיד שלך כאן הוא לנהל שיחה מצוינת. אין לך טופס למלא ואין לך רשימת פרטים להשלים.
- דברי כמו שיחת ChatGPT טובה: טבעית, חמה, חכמה וקצרה.
- קודם התייחסי למה שהלקוח אמר: הגיבי, ייעצי, הסבירי או הציעי רעיון כשזה מועיל.
- אל תראייני את הלקוח. אל תנהלי רצף של שאלות איסוף נתונים.
- אל תשאלי שאלה רק מפני שחסר לך מידע על החופשה.
- שאלי שאלה רק כשהיא המשך טבעי למה שהלקוח עצמו מנסה לברר או כשהיא באמת נחוצה כדי לענות לבקשה הנוכחית.
- אין חובה לשאול שאלה בכל הודעה. לעיתים התשובה הטובה ביותר היא פשוט תגובה או המלצה.
- אם כבר נאמר פרט בשיחה, זכרי אותו. אם הלקוח משנה אותו, התייחסי לגרסה החדשה.
- אל תחזרי על פרטים שכבר נאמרו כדי לאשר אותם, אלא אם יש אי-בהירות אמיתית.
- אל תפעילי חיפוש ואל תטעני שחיפשת טיסות, מלונות או מחירים בשלב הזה.
- אם הלקוח כותב בעברית, השיבי בעברית בלבד. אם הוא בוחר שפה אחרת, השיבי בשפה שלו.
- החזירי רק את ההודעה שהלקוח צריך לראות. בלי JSON, בלי הסברים פנימיים ובלי תהליך עבודה.
- אין צורך להזדהות בשם טינקרבל מול הלקוח.
- מותר להשתמש ב-Markdown פשוט להדגשה.
'''

EXTRACTOR_SYSTEM = '''את שכבת חילוץ נתוני החופשה של אריאלה. אינך משוחחת עם הלקוח ואינך מחליטה איזו שאלה לשאול. קבלי את היסטוריית השיחה וחלצי רק מידע שהלקוח כבר מסר או שינה.

כללים:
- אל תמציאי מידע ואל תשלימי שדות חסרים.
- אין שדה משך חופשה.
- תקציב נשמר לאדם בלבד. אם הלקוח נתן תקציב כולל ומספר הנוסעים ידוע בבטחה, חשבי לאדם; אחרת השאירי לא ידוע.
- לזהות: סוג חופשה; נוסעים ומבנה; יעד/ים ומידת הוודאות; שדה מוצא; תאריכים/תקופה/גמישות ומגבלות; תקציב לאדם; ישירה/קונקשן, מחלקה, כבודה והעדפות טיסה; עדיפויות ומגבלות קשיחות; בקשת הלקוח הנוכחית.
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
    "lodging": {"interested": "unknown", "details": {}},
    "car": {"interested": "unknown", "details": {}},
    "trip_planning": {"interested": "unknown", "details": {}}
  }
}
'''


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


def _call_tinkerbell(key, model, history, message):
    return _post_openai(key, model, TINKERBELL_SYSTEM, history, message, 650).strip()


def _extract_trip_update(key, model, history, message):
    try:
        raw = _post_openai(key, model, EXTRACTOR_SYSTEM, history, message, 900)
        return _parse_trip_update(raw)
    except Exception:
        # Extraction must never break the customer conversation.
        return {}


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
        reply = _call_tinkerbell(key, model, history, message)
    except Exception:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503

    trip_update = _extract_trip_update(key, model, history, message)

    return jsonify({
        'status': 'success',
        'agent': 'Tinkerbell',
        'engine_version': ENGINE_VERSION,
        'reply': reply or 'אני איתך 😊',
        'trip_update': trip_update,
    })
