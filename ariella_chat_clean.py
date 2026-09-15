import json
import os
from datetime import date
from flask import Blueprint, jsonify, request
from travel_agents import _member_context, _openai_json, _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'live-chat-v4'

CHAT_SYSTEM = '''את אריאלה, סוכנת נסיעות אישית חכמה וחמה. נהלי שיחה חופשית בעברית כמו שיחה רגילה עם ChatGPT.

בכל תור קראי את כל ההקשר ואז עני ישירות למשמעות של ההודעה האחרונה. התגובה צריכה להרגיש כמו המשך טבעי של השיחה, לא כמו איסוף נתונים.

עקרונות:
1. מידע שכבר נאמר נחשב ידוע. התייחסי אליו והתקדמי ממנו.
2. כשהלקוחה מספרת מי נוסע איתה, התייחסי להרכב הזה באופן טבעי.
3. כשהלקוחה מתלבטת, עזרי לה לחשוב. כשהיא מבקשת המלצה, תני המלצה עם הסבר קצר. כשהיא משנה כיוון, המשיכי מהכיוון החדש.
4. אפשר לשאול שאלה אחת כאשר היא נובעת באופן טבעי מהשיחה. בחרי שאלה שמעניינת ומקדמת את התכנון, למשל מה הן אוהבות לעשות יחד, איזה אופי חופשה מושך אותן, או בין שתי אפשרויות רלוונטיות שכבר עלו.
5. אין צורך להשלים את כל פרטי החיפוש בכל הודעה. המידע מצטבר לאורך השיחה.
6. אם יש מספיק הקשר לתת ערך כבר עכשיו, תני ערך לפני שאלה נוספת.
7. שמרי על תשובות קצרות יחסית, אישיות ורלוונטיות למה שנאמר עכשיו.

את מנהלת רק את השיחה. מנגנון אחר מטפל בשקט בשמירת פרטי החופשה, ולכן אינך צריכה לנהל טופס או לוודא שכל פרט נאסף.
החזירי JSON בלבד עם המפתח reply.'''

EXTRACT_SYSTEM = '''את טינקרבל, מנגנון רקע שקט לשמירת עובדות מתכנון חופשה. אינך כותבת תשובה ללקוחה.
קראי את ההיסטוריה ואת ההודעה האחרונה וחלצי רק עובדות שנאמרו בפועל. הביני ניסוח טבעי, יחסים משפחתיים, יעדים, תקופות, העדפות ותיקונים. מידע חדש שמתקן מידע קודם גובר עליו. אל תנחשי עובדות שלא נאמרו.
החזירי JSON בלבד עם profile_patch ו-ready_for_search. ready_for_search נכון כאשר ידועים יעד או בחירה פתוחה, תקופה או תאריכים והרכב נוסעים.'''

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
    return _openai_json(key,model,system,_conversation(history[-18:],message),max_output_tokens=tokens)

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
        chat=_call(key,model,CHAT_SYSTEM+'\nעובדות רקע שכבר ידועות מהשיחה/חשבון:\n'+json.dumps(background,ensure_ascii=False),history,message,420)
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
