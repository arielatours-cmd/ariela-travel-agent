import json
import os
from datetime import date
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

travel_agents = Blueprint("travel_agents", __name__)

_DATA_FILE = Path(__file__).resolve().parent / "data" / "attractions.json"

ARIELLA_SYSTEM = """את אריאלה, סוכנת הנסיעות הראשית והיחידה שמדברת עם הלקוח של ARIELA AI TRAVEL.
את מנהלת שיחה טבעית וחופשית בעברית (או בשפת הלקוח), כמו סוכנת נסיעות אנושית מצוינת.
המטרה שלך היא להבין מה הלקוח מחפש, למלא בשקט את מבנה החיפוש, ורק אז לקדם את החיפוש.
חשוב מאוד: אל תחזרי ללקוח על מידע שהוא כבר מסר, אל תסכמי אותו מחדש ואל תאשרי אותו בניסוח כמו "הבנתי ש..." או "אז אתם...". שמרי את המידע בשדות profile מאחורי הקלעים והמשיכי מיד לשאלה החסרה הבאה.
הובילי את השיחה בשאלות מנחות, שאלה אחת בכל פעם, בלי להקריא שאלון ובלי לשאול שוב מידע שכבר נאמר.
סדר טבעי לדוגמה: יעד/כיוון יעד, מתי, מי נוסע, תקציב, שדה יציאה, העדפת טיסה, כבודה ואופי החופשה/העדפות מיוחדות. אל תשאלי שדה שכבר ברור מהשיחה.
אם הלקוח מוסר כמה פרטים באותה הודעה, שמרי את כולם ב-profile ושאלי רק על הפרט החשוב הבא שחסר.
אם הלקוח נותן תאריכים בחודש בלי שנה, השתמשי בשנה שהמערכת סיפקה בפרופיל. אל תשאלי באיזו שנה כאשר ניתן להסיק אותה באופן חד-משמעי מהתאריך הנוכחי. אם החודש המבוקש עדיין לפנינו השנה, זו השנה הנוכחית; אם הוא כבר עבר, זו השנה הבאה.
אם יש אי-בהירות אמיתית, שאלי רק את שאלת ההבהרה הנדרשת. אל תנחשי ואל תחזרי על כל מה שכבר ידוע.
אל תקפצי להצעות, אטרקציות או מסלול בזמן איסוף הנתונים. רק לאחר שהמידע הדרוש נאסף אפשר לעבור לתוצאות.
כאשר יש מספיק מידע מעשי לחיפוש טיסה, סמני ready_for_flights=true. אין צורך לבקש מהלקוח אישור נוסף ואין צורך לחזור בפניו על תנאי החיפוש; מבנה החיפוש נבנה מתוך profile.
טינקרבל ו-Travel הם סוכנים פנימיים בלבד. לעולם אל תזכירי ללקוח שמות של סוכנים פנימיים, DB, מנוע פנימי, handoff או תהליך פנימי. כל מידע פנימי עובר דרכך בלבד.
לעולם אל תמציאי מחיר טיסה, זמינות או דיל.
החזירי JSON בלבד עם המפתחות reply, profile, ready_for_flights, ready_for_travel, intake_complete.
profile הוא אובייקט מצטבר. אל תמחקי מידע קודם אלא אם הלקוח תיקן אותו.
שדות אפשריים: destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, nature, urban, shopping, nightlife, casino, accessibility, baby_friendly, pace, max_drive_minutes, notes.
ready_for_flights=true רק כשיש מספיק מידע מעשי לחיפוש טיסה: יעד/כיוון יעד, תקופה ונוסעים.
ready_for_travel=true רק כשיש יעד והעדפות שמאפשרים התאמת אטרקציות.
intake_complete=true רק כשהמידע הבסיסי לחופשה מספיק כדי לעבור משלב התשאול לשלב ההצעות.
"""

TINKERBELL_SYSTEM = """את טינקרבל, סוכנת פנימית של ARIELA AI TRAVEL. אינך מדברת עם הלקוח.
התפקיד שלך הוא לפרש ניסוחים חופשיים, שגיאות כתיב וביטויים עמומים של הלקוח ולהמיר רק מידע שנאמר בפועל לשדות מובנים עבור אריאלה.
שמרי כל פרט שאפשר למפות ל-profile כדי שאריאלה לא תצטרך לשאול עליו שוב. אל תנסחי תשובה ללקוח ואל תחזרי על המידע שנאסף.
אם הלקוח אומר שאין תקציב/אין הגבלת תקציב/לא מוגבל בתקציב/המחיר לא משנה, מפִי זאת ל-budget_mode=unlimited ואל תסמני את התקציב כלא ברור.
כאשר נמסרים יום וחודש ללא שנה, השתמשי ב-inferred_travel_year שהמערכת סיפקה בפרופיל וצרי departure_date/return_date מלאים. אין לבקש מהלקוח שנה אם ניתן להסיק אותה.
אל תנחשי פרטים שלא נאמרו. אל תציעי אטרקציות, דילים או יעדים. אם משהו לא ברור, כתבי אותו ב-unclear כדי שאריאלה תוכל לשאול רק שאלת הבהרה ממוקדת.
החזירי JSON בלבד: profile_patch כאובייקט, interpretation כמחרוזת קצרה לשימוש פנימי, unclear כמערך מחרוזות.
"""


def _openai_json(key, model, developer_text, conversation, max_output_tokens=1200):
    payload = {"model": model, "input": [{"role": "developer", "content": developer_text}] + conversation, "text": {"format": {"type": "json_object"}}, "max_output_tokens": max_output_tokens}
    response = requests.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload, timeout=35)
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
    body = response.json(); text = body.get("output_text")
    if not text:
        chunks=[]
        for out in body.get("output") or []:
            for part in out.get("content") or []:
                if part.get("type")=="output_text": chunks.append(part.get("text") or "")
        text="".join(chunks)
    return json.loads(text or "{}")


def _conversation(history, message):
    items=[]
    for item in (history or [])[-12:]:
        role="assistant" if item.get("role")=="assistant" else "user"
        items.append({"role":role,"content":str(item.get("content") or "")[:2500]})
    items.append({"role":"user","content":message}); return items


def _inferred_year():
    today=date.today()
    return today.year


def _call_tinkerbell(message, history, profile):
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key: raise RuntimeError("OPENAI_API_KEY is not configured")
    model=os.getenv("ARIELLA_MODEL","gpt-5.6-luna").strip()
    p=dict(profile or {}); p["current_date"]=date.today().isoformat(); p["inferred_travel_year"]=_inferred_year()
    developer=TINKERBELL_SYSTEM+"\nפרופיל קיים:\n"+json.dumps(p,ensure_ascii=False)
    result=_openai_json(key,model,developer,_conversation(history,message),max_output_tokens=650)
    if not isinstance(result.get("profile_patch"),dict): result["profile_patch"]={}
    if not isinstance(result.get("unclear"),list): result["unclear"]=[]
    return result


def _call_ariella(message, history, profile, tinkerbell):
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key: raise RuntimeError("OPENAI_API_KEY is not configured")
    model=os.getenv("ARIELLA_MODEL","gpt-5.6-luna").strip()
    internal={"profile":profile or {},"current_date":date.today().isoformat(),"inferred_travel_year":_inferred_year(),"tinkerbell_interpretation":tinkerbell.get("interpretation") or "","tinkerbell_unclear":tinkerbell.get("unclear") or []}
    developer=ARIELLA_SYSTEM+"\nמידע פנימי שאסור לחשוף ללקוח:\n"+json.dumps(internal,ensure_ascii=False)
    result=_openai_json(key,model,developer,_conversation(history,message),max_output_tokens=1200)
    if not isinstance(result.get("profile"),dict): result["profile"]=dict(profile or {})
    return result


def _truthy(value): return str(value or "").strip().lower() in {"כן","yes","true","1","חלקית"}

def _load_attractions():
    try:
        data=json.loads(_DATA_FILE.read_text(encoding="utf-8")); return data.get("attractions",data if isinstance(data,list) else [])
    except Exception: return []

def _travel_matches(profile,limit=8):
    destinations=[str(x).lower() for x in (profile.get("destinations") or [])]; styles={str(x).lower() for x in (profile.get("vacation_styles") or [])}; rows=[]
    for row in _load_attractions():
        country=str(row.get("מדינה") or "").lower(); city=str(row.get("עיר/בסיס") or "").lower()
        if destinations and not any(d in country or d in city or country in d or city in d for d in destinations): continue
        score=0; reasons=[]
        checks=[(profile.get("nature") or "טבע" in styles,"טבע ונופים","טבע ונופים"),(profile.get("urban") or "עירוני" in styles,"טיול עירוני","טיול עירוני"),(profile.get("shopping") or "שופינג" in styles,"שופינג","שופינג"),(profile.get("nightlife") or "חיי לילה" in styles,"ברים/מועדונים/מסיבות","חיי לילה"),(profile.get("casino"),"קזינו","קזינו"),(profile.get("baby_friendly") or int(profile.get("infants") or 0)>0,"מתאים לתינוקות","מתאים לתינוקות"),(int(profile.get("children") or 0)>0,"מתאים לילדים","מתאים לילדים")]
        for wanted,field,label in checks:
            if wanted and _truthy(row.get(field)): score+=3; reasons.append(label)
            elif wanted and str(row.get(field) or "").strip()=="לא": score-=4
        if profile.get("accessibility") and str(row.get("נגישות") or "") in {"כן","חלקית"}: score+=4; reasons.append("נגישות")
        rows.append((score,row,reasons))
    rows.sort(key=lambda x:x[0],reverse=True); out=[]
    for score,row,reasons in rows[:limit]:
        out.append({"name":row.get("שם האטרקציה"),"country":row.get("מדינה"),"region":row.get("אזור/מחוז"),"city":row.get("עיר/בסיס"),"type":row.get("סוג ראשי"),"score":score,"reasons":reasons,"duration":row.get("משך מומלץ"),"difficulty":row.get("רמת קושי"),"accessibility":row.get("נגישות"),"price":row.get("מחיר/הערת מחיר"),"official_url":row.get("אתר רשמי"),"booking_url":row.get("קישור הזמנה/כרטיסים"),"notes":row.get("הערות")})
    return out

def _tinkerbell_handoff(profile):
    return {"destination_mode":profile.get("destination_mode") or ("specific" if profile.get("destinations") else "open"),"destinations":profile.get("destinations") or [],"departure_airports":profile.get("departure_airports") or [],"date_mode":profile.get("date_mode"),"departure_date":profile.get("departure_date"),"return_date":profile.get("return_date"),"outbound_month":profile.get("outbound_month"),"return_month":profile.get("return_month"),"date_flex_days":profile.get("date_flex_days") or 0,"adults":profile.get("adults"),"children":profile.get("children") or 0,"budget_mode":profile.get("budget_mode"),"budget_amount":profile.get("budget_amount"),"flight_preference":profile.get("flight_preference"),"baggage":profile.get("baggage")}

@travel_agents.post("/api/ariella/chat")
def ariella_chat():
    body=request.get_json(silent=True) or {}; message=str(body.get("message") or "").strip()
    if not message: return jsonify({"status":"error","message":"message is required"}),400
    profile=body.get("profile") if isinstance(body.get("profile"),dict) else {}; history=body.get("history") if isinstance(body.get("history"),list) else []
    try:
        tinkerbell=_call_tinkerbell(message,history,profile); normalized=dict(profile); normalized.update({k:v for k,v in tinkerbell.get("profile_patch",{}).items() if v not in (None,"",[])})
        result=_call_ariella(message,history,normalized,tinkerbell)
    except Exception as exc: return jsonify({"status":"error","message":"אריאלה לא זמינה כרגע.","detail":str(exc)}),503
    merged=dict(normalized); merged.update({k:v for k,v in result.get("profile",{}).items() if v not in (None,"",[])})
    intake_complete=bool(result.get("intake_complete")); travel=_travel_matches(merged) if intake_complete and result.get("ready_for_travel") else []
    return jsonify({"status":"success","agent":"Ariella","reply":result.get("reply") or "ספרו לי עוד קצת על החופשה שאתם מחפשים.","profile":merged,"ready_for_flights":bool(result.get("ready_for_flights")),"ready_for_travel":bool(result.get("ready_for_travel")),"intake_complete":intake_complete,"tinkerbell_handoff":_tinkerbell_handoff(merged),"travel_agent":{"agent":"Travel","attractions":travel}})
