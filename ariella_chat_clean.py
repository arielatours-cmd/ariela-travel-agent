import json
import os
from datetime import date
from flask import Blueprint, jsonify, request
from travel_agents import _member_context, _openai_json, _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'clean-chat-v1'

SYSTEM = '''את אריאלה, סוכנת נסיעות אישית. דברי כמו בשיחת ChatGPT טבעית.
אין שאלון, אין סדר שדות, אין שלבים ואין שאלה הבאה קבועה. הגיבי קודם למה שהלקוח אמר עכשיו ובהקשר של השיחה.
אם נשאלה שאלה עני עליה. אם יש התלבטות חשבי יחד. אם התבקשה המלצה המליצי. אם נמסר מידע התייחסי אליו. אם תוקן מידע המשיכי מהתיקון.
אל תשאלי שוב פרט שכבר נאמר. מותר לכל היותר לשאול שאלה אחת בסוף ורק כהמשך טבעי. אל תבקשי יחד יעד, תאריך ונוסעים ואל תגידי ספרי לי קצת על החופשה.
אם נאמר בא לי לטוס עם הבת שלי, כבר ידוע מי נוסע. אם נשאל מתי את ממליצה, עני על השאלה במקום לדרוש קודם פרט אחר.
במקביל חלצי בשקט עובדות חדשות ל-profile_patch. החילוץ אינו מנהל את השיחה. תיקון חדש גובר על ישן ואל תנחשי עובדות.
עם הבת שלי משמע בדרך כלל adults=1, children=1, travel_party_type=family. עם בעלי משמע adults=2. אין צורך לשאול גיל מיד רק משום שהוא חסר.
כאשר יש יעד או בקשה שאריאלה תבחר, תקופה או תאריכים והרכב נוסעים, אפשר לסמן ready_for_search=true. זה אות פנימי בלבד.
החזירי JSON בלבד: {"reply":"תגובה טבעית וקצרה בעברית","profile_patch":{},"ready_for_search":false}'''

def _patch(v):
    return {k:x for k,x in v.items() if x is not None} if isinstance(v,dict) else {}

def _seed(profile):
    if profile.get('clean_member_loaded'):
        return profile
    out=dict(profile)
    try:
        member=_member_context()
    except Exception:
        member=None
    if member:
        if member.get('gender') and not out.get('customer_gender'):
            out['customer_gender']=member.get('gender')
        out.setdefault('known_companions',member.get('companions') or [])
    out['clean_member_loaded']=True
    return out

@ariella_chat_clean.post('/api/ariella/chat-clean')
def chat_clean():
    body=request.get_json(silent=True) or {}
    message=str(body.get('message') or '').strip()
    if not message:
        return jsonify({'status':'error','message':'message is required','engine_version':ENGINE_VERSION}),400
    history=body.get('history') if isinstance(body.get('history'),list) else []
    profile=_seed(body.get('profile') if isinstance(body.get('profile'),dict) else {})
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:
        return jsonify({'status':'error','message':'אריאלה לא זמינה כרגע.','engine_version':ENGINE_VERSION}),503
    model=os.getenv('ARIELLA_MODEL','gpt-5.6-luna').strip()
    context={'today':date.today().isoformat(),'facts_already_known':profile}
    try:
        result=_openai_json(key,model,SYSTEM+'\nמידע רקע שכבר ידוע, לא רשימת שדות להשלמה:\n'+json.dumps(context,ensure_ascii=False),_conversation(history[-10:],message),max_output_tokens=300)
    except Exception as exc:
        return jsonify({'status':'error','message':'אריאלה לא זמינה כרגע.','detail':str(exc),'engine_version':ENGINE_VERSION}),503
    result=result if isinstance(result,dict) else {}
    merged=dict(profile); merged.update(_patch(result.get('profile_patch')))
    reply=str(result.get('reply') or '').strip() or 'אני איתך 😊 תמשיכי.'
    return jsonify({'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,'reply':reply,'profile':merged,'ready_for_search':bool(result.get('ready_for_search'))})
