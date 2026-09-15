import json
import os
from datetime import date
from flask import Blueprint, jsonify, request
from travel_agents import _member_context, _openai_json, _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'live-chat-v2'

CHAT_SYSTEM = '''את אריאלה, סוכנת נסיעות אישית. נהלי שיחה חיה, חופשית וטבעית בעברית, כמו ChatGPT.
התפקיד שלך בקריאה הזאת הוא רק לענות למשתמשת. אין טופס, אין שלבים, אין רשימת שדות חסרים ואין שאלה הבאה קבועה.
קראי את היסטוריית השיחה והגיבי להודעה האחרונה לפי הכוונה שלה. אם נשאלה שאלה עני עליה. אם התבקשה המלצה תני המלצה שימושית לפי ההקשר. אם יש התלבטות חשבי יחד. אם יש שינוי כיוון המשיכי ממנו.
אל תחזרי על שאלה שכבר נענתה ואל תדרשי מידע רק מפני שהוא חסר במערכת. מותר לשאול שאלה קצרה אחת רק כשהיא באמת מועילה, ולא חובה לסיים תשובה בשאלה.
אם כבר נאמר צפון איטליה ואז נשאל מתי את ממליצה, עני אילו תקופות מומלצות לצפון איטליה ולמה. אל תשאלי שוב מתי רוצים לנסוע.
אם נאמר בא לי לטוס עם הבת שלי, כבר ידוע שהבת נוסעת איתה ואין לשאול מי נוסע.
אל תגידי ספרי לי קצת על החופשה ואל תבקשי יחד יעד, תאריכים ונוסעים.
החזירי JSON בלבד עם מפתח reply שמכיל את התשובה הטבעית שלך.'''

EXTRACT_SYSTEM = '''את טינקרבל, מנגנון רקע שקט. אינך מדברת עם הלקוחה ואינך קובעת את תגובת אריאלה.
חלצי מהשיחה רק עובדות חדשות או תיקונים שנאמרו בפועל ושימושיים לתכנון חופשה. אל תנחשי. תיקון חדש גובר על מידע ישן.
החזירי JSON בלבד עם profile_patch ו-ready_for_search. ready_for_search נכון רק כאשר כבר ידועים יעד או בחירה פתוחה, תקופה או תאריכים והרכב נוסעים.'''

def _patch(v):
    return {k:x for k,x in v.items() if x is not None} if isinstance(v,dict) else {}

def _seed(profile):
    if profile.get('live_member_loaded'):
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
    out['live_member_loaded']=True
    return out

def _call(key,model,system,history,message,tokens):
    return _openai_json(key,model,system,_conversation(history[-14:],message),max_output_tokens=tokens)

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
    background={'today':date.today().isoformat(),'known_facts':profile}
    try:
        chat=_call(key,model,CHAT_SYSTEM+'\nרקע להבנת השיחה בלבד:\n'+json.dumps(background,ensure_ascii=False),history,message,420)
    except Exception as exc:
        return jsonify({'status':'error','message':'אריאלה לא זמינה כרגע.','detail':str(exc),'engine_version':ENGINE_VERSION}),503
    chat=chat if isinstance(chat,dict) else {}
    reply=str(chat.get('reply') or '').strip() or 'אני איתך 😊'
    extraction={}
    try:
        extraction=_call(key,model,EXTRACT_SYSTEM+'\nפרופיל קיים:\n'+json.dumps(profile,ensure_ascii=False),history,message,220)
        extraction=extraction if isinstance(extraction,dict) else {}
    except Exception:
        extraction={}
    merged=dict(profile)
    merged.update(_patch(extraction.get('profile_patch')))
    return jsonify({'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,'reply':reply,'profile':merged,'ready_for_search':bool(extraction.get('ready_for_search'))})
