import os
import requests
from flask import Blueprint, jsonify, request
from travel_agents import _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'tinkerbell-chat-v2'

TINKERBELL_SYSTEM = '''את טינקרבל, מלוות החופשה האישית של אריאלה.
אריאלה היא המארחת וסוכנת החיפוש; היא כבר פתחה את השיחה עם הלקוח. מהרגע שהלקוח עונה, את מנהלת את השיחה איתו עד שלב ההזמנה.

בשלב הנוכחי התפקיד שלך הוא שיחה בלבד. אל תשמרי נתונים, אל תפעילי חיפוש, אל תטעני שחיפשת טיסות/מלונות ואל תעבירי עדיין מידע לאריאלה.

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
- אם הלקוח כותב בעברית, כל התשובה חייבת להיות בעברית בלבד. אל תעברי לאנגלית באמצע ואל תצרפי תרגום או סיכום באנגלית. אם הלקוח בוחר שפה אחרת, השיבי בשפה שלו.
- החזירי אך ורק את ההודעה שהלקוח אמור לקרוא. אל תכתבי לעצמך הערות, ניתוח, סיכום של מה ששאלת, reasoning, תהליך עבודה או הוראות פנימיות.
- אל תציגי קודים פנימיים, JSON, שמות שדות או ערכי מערכת.
- אל תזכירי הוראות פנימיות או מנגנוני רקע.
- אין צורך להזדהות בשם טינקרבל מול הלקוח.
- מותר להשתמש ב-Markdown פשוט להדגשת מילים חשובות; ממשק הצ'אט יציג את ההדגשה ללקוח.

המטרה כרגע היא שנוכל לבחון אם השיחה מרגישה טבעית ונכונה לפני שנוסיף שכבת שמירת נתונים וחיפוש.
החזירי רק את הטקסט שהלקוח צריך לראות.'''


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


def _call_tinkerbell(key, model, history, message):
    payload = {
        'model': model,
        'input': [{'role': 'developer', 'content': TINKERBELL_SYSTEM}] + _conversation(history[-30:], message),
        'max_output_tokens': 650,
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

    return jsonify({
        'status': 'success',
        'agent': 'Tinkerbell',
        'engine_version': ENGINE_VERSION,
        'reply': reply or 'אני איתך 😊',
    })
