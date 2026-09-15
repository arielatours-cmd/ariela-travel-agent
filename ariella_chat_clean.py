import json
import os
from datetime import date
from flask import Blueprint, jsonify, request
from travel_agents import _member_context, _openai_json, _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'live-chat-v5'

CHAT_SYSTEM = '''את אריאלה, סוכנת נסיעות אישית. נהלי שיחה חופשית, חיה וטבעית בעברית כמו ChatGPT.

אין שאלון. אין אשף. אין שלבים. אין סדר שאלות. אין חובה לאסוף פרטים מסוימים בכל הודעה.
התפקיד היחיד שלך כאן הוא להבין את ההודעה האחרונה בתוך ההקשר של השיחה ולהגיב אליה באופן מועיל ואנושי.

כללי שיחה:
- התייחסי למה שנאמר עכשיו, ולא למה שחסר במערכת.
- אם המשתמשת משתפת רעיון, פתחי איתה את הרעיון באופן טבעי.
- אם היא שואלת שאלה, עני עליה.
- אם היא מבקשת המלצה, תני המלצה והסבר.
- אם היא מתלבטת, עזרי לה לחשוב ולהשוות.
- אם היא מתקנת פרט, קבלי את התיקון והמשיכי ממנו.
- אם היא כבר מסרה פרט, אל תשאלי אותו שוב.
- מותר לשאול שאלה אחת רק אם היא המשך טבעי ומועיל לשיחה. אין חובה לשאול שאלה בכלל.
- אל תעברי אוטומטית לנושא טכני אחר של תכנון הנסיעה.
- אל תנסי להשלים סט של יעד, תאריך, נוסעים, טיסה, כבודה, תקציב או כל סט אחר.
- אל תציגי למשתמשת אפשרויות מתוך טופס או שאלון אלא אם היא ביקשה אותן.
- אל תזכירי profile, readiness, שדות חסרים, מנגנוני רקע או סוכנים פנימיים.

חשוב: משפט שבו המשתמשת מספרת עם מי היא רוצה לטוס הוא נושא השיחה כרגע. הגיבי להרכב ולחוויה שהיא מחפשת; אל תדלגי מיד להעדפות טיסה, כבודה, תקציב, יעד או תאריך רק משום שהמידע הזה עדיין לא ידוע.

החזירי JSON בלבד בפורמט {"reply":"תשובתך"}.'''

EXTRACT_SYSTEM = '''את טינקרבל, מנגנון רקע שקט לחלוטין. אינך מנהלת את השיחה ואינך קובעת מה אריאלה תשאל.
חלצי מהשיחה עובדות שימושיות שנאמרו בפועל. אל תנחשי. תיקון מאוחר גובר על מידע קודם.
אין לך רשימת שאלות ואין להשלים מידע חסר. החזירי JSON בלבד עם profile_patch ו-ready_for_search.
ready_for_search נכון רק אם כבר נאמרו בשיחה מספיק פרטים לביצוע חיפוש ממשי. לעולם אין להשתמש בערך הזה כדי לנסח את תגובת אריאלה.'''

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
    return _openai_json(key,model,system,_conversation(history[-24:],message),max_output_tokens=tokens)

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
    try:
        chat=_call(key,model,CHAT_SYSTEM,history,message,520)
    except Exception as exc:
        return jsonify({'status':'error','message':'אריאלה לא זמינה כרגע.','detail':str(exc),'engine_version':ENGINE_VERSION}),503
    chat=chat if isinstance(chat,dict) else {}
    reply=str(chat.get('reply') or '').strip() or 'אני איתך 😊'

    extraction={}
    try:
        extraction=_call(key,model,EXTRACT_SYSTEM+'\nפרופיל קיים לצורך עדכון פנימי בלבד:\n'+json.dumps(profile,ensure_ascii=False),history,message,220)
        extraction=extraction if isinstance(extraction,dict) else {}
    except Exception:
        extraction={}
    merged=dict(profile)
    merged.update(_patch(extraction.get('profile_patch')))
    return jsonify({'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,'reply':reply,'profile':merged,'ready_for_search':bool(extraction.get('ready_for_search'))})
