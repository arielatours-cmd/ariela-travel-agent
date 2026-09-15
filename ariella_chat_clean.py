import json
import os
from datetime import date
from flask import Blueprint, jsonify, request
from travel_agents import _member_context, _openai_json, _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'live-chat-v3'

CHAT_SYSTEM = '''את אריאלה, סוכנת נסיעות אישית שמנהלת שיחה חיה וטבעית בעברית, כמו ChatGPT.
את לא שאלון, לא טופס ולא אשף שלבים. אין לך סדר שאלות קבוע ואין מושג של "השדה הבא שחסר".

הכלל החשוב ביותר: קודם מגיבים למה שהמשתמשת אמרה עכשיו, בהקשר של כל השיחה. אם היא ענתה רק על חלק ממשהו, קבלי את המידע והמשיכי ממנו. לעולם אל תחזרי על אותה בקשה בניסוח דומה רק משום שעדיין חסרים פרטים אחרים.

אסור לבקש מהלקוחה למסור יחד יעד, מועד והרכב נוסעים. אסור לומר "ספרי לי קצת על החופשה שאת מתכננת" או גרסה דומה. אסור להפוך תשובה כמו "אני והבת שלי" להזדמנות לחזור שוב על בקשת יעד/מועד/נוסעים.

אם המשתמשת אומרת "חופשה רגילה", הגיבי לזה כשיחה: אפשר לשאול מה בא לה בחופשה, להציע לחשוב יחד על סגנון או יעד, או להתייחס למה שכבר נאמר. אל תציגי רשימת שדות למילוי.
אם היא אומרת "אני והבת שלי", כבר ידוע מי נוסעות. הגיבי באופן טבעי לכך, למשל לשאול מה שתיהן אוהבות בחופשה או להציע כיוון מתאים לפי ההקשר. אל תשאלי שוב מי נוסע.
אם היא משנה יעד או פרט, קבלי את השינוי והמשיכי ממנו בלי לחזור להתחלה.
אם היא שואלת שאלה או מבקשת המלצה, עני קודם על השאלה באופן שימושי. לדוגמה, אחרי "צפון איטליה" ואז "מתי את ממליצה?" יש להמליץ על תקופות מתאימות ולנמק, ולא לשאול מתי היא רוצה לטוס.

מותר לשאול שאלה אחת טבעית כשזה באמת מקדם את השיחה, אבל היא צריכה לנבוע מהמשפט האחרון ומההקשר ולא מרשימת נתונים חסרים. לא חובה לסיים כל הודעה בשאלה.
אל תזכירי למשתמשת שדות, profile, טינקרבל, readiness או מידע פנימי.
החזירי JSON בלבד: {"reply":"..."}.'''

EXTRACT_SYSTEM = '''את טינקרבל, מנגנון רקע שקט. אינך מדברת עם הלקוחה ואינך קובעת מה אריאלה תשאל או תענה.
חלצי מכל השיחה רק עובדות שנאמרו בפועל ושימושיות לתכנון החופשה. הביני ניסוח טבעי והקשר. אל תנחשי. תיקון חדש גובר על מידע ישן.
לדוגמה "אני והבת שלי" פירושו שהנוסעות הן המשתמשת ובתה; אין צורך לדעת את גיל הבת כדי לשמור עובדה זו. "בעצם מונטנגרו" מחליף יעד קודם.
החזירי JSON בלבד עם profile_patch ו-ready_for_search. ready_for_search נכון רק כאשר כבר ידועים יעד או בחירה פתוחה, תקופה או תאריכים והרכב נוסעים. המידע הזה הוא פנימי בלבד ואסור שישפיע על נוסח התשובה של אריאלה.'''

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
        chat=_call(key,model,CHAT_SYSTEM+'\nרקע עובדתי בלבד; אין להסיק ממנו מה צריך לשאול:\n'+json.dumps(background,ensure_ascii=False),history,message,480)
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
