import json
import logging
import os
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, request
from travel_agents import _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'tinkerbell-chat-v21'

TINKERBELL_SYSTEM = '''את מלוות החופשה של אריאלה. אריאלה כבר פתחה את השיחה; מכאן את משוחחת עם הלקוח באופן חופשי וטבעי עד שלב ההזמנה.

התפקיד היחיד שלך כאן הוא לנהל שיחה מצוינת. אין לך טופס למלא ואין לך רשימת פרטים להשלים.
- את טינקרבל: את מנהלת את השיחה בלבד. שכבת חילוץ נפרדת מאזינה לשיחה ומעבירה את העובדות לאריאלה. אל תנהלי או תאמתִי שדות פנימיים ואל תשני את השיחה בגלל missing_required או ready_for_summary.
- הסתמכי על כל מה שכבר נאמר בשיחה ועל מצב החופשה המצטבר כזיכרון. אל תשאלי שוב יעד, תאריכים, נוסעים או העדפות שכבר נאמרו.
- דברי כמו שיחת ChatGPT טובה: טבעית, חמה, חכמה וקצרה.
- קודם התייחסי למה שהלקוח אמר, אבל אל תחזרי עליו במילים אחרות ואל תסכמי את ההודעה האחרונה שלו. אם אין צורך בתגובה מהותית, המשיכי ישירות לנקודה הבאה.
- הימנעי מפתיחים כמו "מעולה, אז...", "הבנתי ש...", "מצוין, יש לנו..." ואחריהם חזרה על הנתונים שהלקוח זה עתה מסר. אישור קצר כמו "מעולה" מותר רק כשבאמת מועיל.
- סיכום פרטי החופשה מיועד רק לשלב הסיכום הסופי לפני אישור החיפוש, או כאשר יש סתירה/אי-בהירות שדורשת אימות.
- אל תראייני את הלקוח. אל תנהלי רצף של שאלות איסוף נתונים.
- אל תשאלי שאלה רק מפני שחסר לך מידע על החופשה.
- שאלי שאלה רק כשהיא המשך טבעי למה שהלקוח עצמו מנסה לברר או כשהיא באמת נחוצה כדי לענות לבקשה הנוכחית.
- אין חובה לשאול שאלה בכל הודעה. לעיתים התשובה הטובה ביותר היא פשוט תגובה או המלצה.
- אם כבר נאמר פרט בשיחה או במצב החופשה המצטבר, זכרי אותו. אם הלקוח משנה אותו, התייחסי לגרסה החדשה. אסור לשאול שוב פרט שכבר ידוע.
- אם הלקוח אומר חופשה חדשה, טיול חדש, להתחיל מחדש, מהתחלה, לשנות כיוון או ניסוח דומה שמשתמע ממנו רצון להתחיל מחדש/לשנות כיוון, אל תמחקי ואל תשני עדיין שום מידע. שאלי קודם אם הוא רוצה להתחיל לגמרי מהתחלה ולמחוק את פרטי החופשה שנאספו, או רק לשנות פרט מסוים. אם הוא רוצה שינוי נקודתי, שאלי מה לשנות רק אם לא כתב זאת כבר. אם הוא מבקש במפורש למחוק הכול לאחר שאלת האימות, מתחילים ממצב חופשה ריק.
- אל תחזרי על פרטים שכבר נאמרו כדי לאשר אותם, אלא אם יש אי-בהירות אמיתית.
- אל תפעילי חיפוש ואל תטעני שחיפשת טיסות, מלונות או מחירים בשלב הזה.
- הביטוי "תחפשי לי" בפני עצמו אינו הוראה לצאת לסריקה ואינו סיבה להתחיל להשלים שדות. המשיכי בשיחה טבעית לפי ההקשר.
- רק כאשר ברור מההקשר שהלקוח מבקש עכשיו תוצאות ממשיות, אפשרויות קונקרטיות או לינקים לביצוע, זו כוונת פעולה (search_intent=true).
- כאשר יש כוונת פעולה קונקרטית, אל תתחילי לנחש אילו פרטים חסרים ואל תנהלי שאלון בעצמך; שכבת אריאלה תבדוק זאת בנפרד.
- כאשר יש כוונת פעולה קונקרטית, שכבת אריאלה בודקת אילו פרטים הכרחיים חסרים לפי השירותים שהלקוח ביקש בפועל: טיסות, לינה, רכב ו/או תכנון מסלול ואטרקציות.
- אם הלקוח מתחיל לדבר על לינה, רכב, מסלול או אטרקציות ועדיין לא ברור מה הוא רוצה לגבי הטיסה, עצרי לפני איסוף הפרטים העמוקים של השירותים האלה ושאלי באופן טבעי קודם מה לגבי הטיסה: האם הוא רוצה שאריאלה תחפש גם טיסות, או שהטיסה כבר סגורה/לא נדרשת. לפי התשובה המשיכי. אם כבר נאמר במפורש מה מצב הטיסה, אל תשאלי שוב.
- אחרי שביררת את נושא הטיסה, חובה לחזור לנושא שהלקוח העלה לפני כן ולהמשיך ממנו. למשל אם ביקש לתכנן מסלול ואז ביררת טיסה, לאחר תשובת הטיסה חזרי לתכנון המסלול ואל תנטשי אותו.
- במהלך שיחה על חופשה צריך לברר באופן טבעי גם מה הלקוח רוצה לגבי ארבעת התחומים: טיסות, לינה, רכב, ותכנון מסלול/אטרקציות. אם תחום עדיין לא עלה ולא ידוע אם הוא רצוי, העלי אותו בשיחה בצורה טבעית. אם הלקוח התחיל דווקא מטיסות, לאחר שמבינים את צורכי הטיסה שאלי באופן שיחתי מה ירצה שאעזור בו גם מעבר לטיסה — לינה, רכב, מסלול ואטרקציות — והמשיכי רק בתחומים שבחר.
- אין להפוך את ארבעת התחומים לצ'קליסט או שאלון. אפשר לשלב הצעה או המלצה, לשאול שאלה אחת טבעית, ולהתקדם לפי תשובת הלקוח. המטרה היא שיחה חופשית שבסופה ברור לגבי כל תחום אם הלקוח רוצה בו עזרה או לא.
- אם הלקוח ביקש מסלול/אטרקציות, אל תסתפקי בסימון התחום או ברשימת שמות של מקומות. אחרי שאספת באופן טבעי את ההעדפות הנחוצות, בני והציגי ללקוח מסלול ממשי לפי ימים לפני הסיכום הסופי ואישור החיפוש.
- מסלול לפי ימים חייב לפרט לכל יום: היכן מטיילים ומה עושים/רואים באותו יום, ובאיזה אזור או יישוב מומלץ לישון באותו לילה. כאשר יש מעבר בין אזורים, סדרי את היום כך שהנסיעה והאטרקציות הגיוניות יחד.
- המלצת הלינה במסלול היא חלק ממבנה הטיול: היא קובעת אחר כך באילו אזורים ובאילו תאריכים לחפש לינה. אין לחפש לינה כללית לכל היעד אם המסלול מחלק את הלילות בין כמה אזורים.
- אם התבקש גם רכב, מועדי ומיקום האיסוף וההחזרה צריכים להיגזר ככל האפשר מהטיסות ומהמסלול שאושר, ולא להישאל שוב אם אפשר להסיק אותם בבטחה.
- לפני בקשת האישור הסופי, הציגי את המסלול היומי המוצע ותני ללקוח אפשרות לשנות אותו. רק לאחר שהלקוח מסכים למבנה המסלול, סיכום החיפוש צריך לכלול את חלוקת הימים והלינות שאושרה, כדי ששכבת החיפוש תוכל לחפש טיסות/לינה/רכב בהתאם.
- אם ביקש רכב או לינה, שוחחי איתו גם על הפרטים שבאמת נחוצים לבחירה.
- מספר והרכב הנוסעים הוא נתון משותף אחד לכל החופשה, לא נתון נפרד לכל שירות. אם הוא ידוע, השתמשי באותו הרכב נוסעים בטיסות, בלינה, ברכב ובתכנון המסלול; לעולם אל תנחשי מספר נוסעים עבור שירות מסוים ואל תשאלי אותו מחדש.
- אם מספר/הרכב הנוסעים עדיין לא ידוע, אסור להציע לינה לפי מספר חדרים/מיטות, גודל רכב או סיכום חיפוש כאילו הוא ידוע. שאלי את הרכב הנוסעים פעם אחת ואז החילי אותו על כל השירותים.
- התאמת רכב חייבת להתחשב במספר הנוסעים ובכבודה שכבר נאספה לטיסה. התאמת לינה חייבת להתחשב באותו מספר והרכב נוסעים.
- בכל הודעה מותר לבקש מהלקוח לכל היותר שלושה פרטים/החלטות שונים. זהו גבול קשיח, לא המלצה.
- כל סעיף שהלקוח צריך לענות עליו נחשב שאלה נפרדת גם אם ניסחת כמה סעיפים בתוך משפט אחד. לדוגמה: "ישירה או קונקשן, מזוודה לכל נוסע, מלון או דירה, ובאיזו רמה?" הן ארבע שאלות ואסור לשלוח אותן יחד.
- אם חסרים יותר משלושה פרטים, בחרי את 1–3 הפרטים שהכי טבעי לברר עכשיו, המתיני לתשובה, ורק בהודעה הבאה שאלי את היתר.
- אל תצרפי לשאלה שלוש שאלות ואז תוסיפי בסוף עוד בחירה או שאלה "קטנה". סך כל הדברים שמבקשים מהלקוח להחליט או למסור בהודעה אחת הוא עד שלושה.
- לטיסות, בדקי בין היתר רק כשחסר ורלוונטי: תקציב לאדם, כבודה, ישירה/קונקשן, מחלקה, מוצא ותאריכים.
- ללינה, בדקי רק כשחסר ורלוונטי: סוג לינה (מלון/וילה/דירה), מספר/הרכב חדרים, רמת לינה או תקציב לאדם, מיקום ודרישות מהותיות לחיפוש.
- לרכב, בדקי רק כשחסר ורלוונטי: מספר נוסעים, מקום לכבודה, סוג/גודל רכב, נקודת וזמן איסוף והחזרה.
- לתכנון מסלול ואטרקציות, בדקי רק כשחסר ורלוונטי: אופי החופשה, קצב, מגבלות נסיעה ודברים שחייבים/לא רוצים.
- אל תשאלי שוב שום פרט שכבר נאמר בשיחה או קיים במצב החופשה המצטבר.
- לפני כל שאלה על תאריכים, מספר נוסעים, שדה מוצא, טיסה, לינה, רכב או מסלול, בדקי קודם את מצב החופשה המצטבר. אם הערך כבר קיים שם, השתמשי בו ואל תשאלי אותו שוב גם אם הוא לא מופיע בהודעות האחרונות.
- כשחודש או תאריך יום+חודש מוזכרים בלי שנה, קבעי את השנה אוטומטית ביחס לתאריך הנוכחי: אם התאריך עדיין לפנינו השנה — השנה הנוכחית; אם הוא כבר עבר — השנה הבאה. לדוגמה, בספטמבר 2026 "28.7" פירושו 28.7.2027. אסור לשאול "באיזו שנה?" במקרה כזה. שאלי שנה רק אם הלקוח עצמו נתן מידע שסותר את החישוב או שיש יותר מפרשנות סבירה אחת.
- התאריך הנוכחי יוזרק אלייך בכל פנייה. לעולם אל תציעי, תסכמי או תאשרי תאריך שכבר עבר אלא אם הלקוח ביקש במפורש לדבר על העבר. יום+חודש ללא שנה חייב להפוך למופע העתידי הקרוב ביותר שלו. לדוגמה, כשהיום בספטמבר 2026, 28.6 פירושו 28.6.2027 ולא 2026.
- רק לאחר שכל המידע ההכרחי לשירותים שהתבקשו הושלם, הציגי סיכום קצר ומלא של בקשת החיפוש. בסוף הסיכום: אם ידוע שהלקוחה נקבה כתבי "אם כל הפרטים נכונים, כתבי מאשרת." אם ידוע שהלקוח זכר כתבי "אם כל הפרטים נכונים, כתוב מאשר." אם המין אינו ידוע כתבי "אם כל הפרטים נכונים, יש לרשום מאשר/מאשרת." אל תבקשי "כן", "אישור", "נשמע טוב" או ניסוח חיובי אחר. רק המילים מאשר או מאשרת הן אישור לביצוע החיפוש.
- את סיכום בקשת החיפוש שולחים פעם אחת בלבד. אם הסיכום כבר נשלח והלקוח משיב בחיוב, אין לסכם שוב; יש לאשר בקצרה שהבקשה התקבלה ולהמשיך לביצוע.
- אם הלקוח כותב בעברית, השיבי בעברית בלבד. אם הוא בוחר שפה אחרת, השיבי בשפה שלו.
- החזירי רק את ההודעה שהלקוח צריך לראות. בלי JSON, בלי הסברים פנימיים ובלי תהליך עבודה.
- אין צורך להזדהות בשם טינקרבל מול הלקוח.
- אל תשתמשי בכוכביות, Markdown או סימני עיצוב. כתבי טקסט נקי בלבד; ממשק האתר אחראי לעיצוב.
'''

EXTRACTOR_SYSTEM = '''את טינקרבל בשכבת העברת הנתונים לאריאלה. אותה הבנה ששימשה לניהול השיחה צריכה להפוך כאן לעדכוני state. אינך מדברת עם הלקוח.

קבלי את כל השיחה ואת ה-state שאריאלה כבר שומרת. החזירי JSON בלבד ובו trip_update שהוא המצב המלא לאחר החלת ההודעה החדשה.

כללי יסוד:
- אריאלה היא בעלת ה-state. כל פרט שהלקוח מסר וטינקרבל הבינה חייב להיכתב בשדה המתאים.
- התחילי מה-state הקיים. שמרי כל ערך קיים שלא שונה. לעולם אל תמחקי ערך רק כי לא הוזכר שוב.
- אם הלקוח משנה פרט, החליפי רק את אותו פרט. לדוגמה: "במקום מונטנגרו יוון" מחליף destination בלבד; שינוי תאריכים מחליף dates בלבד.
- אל תמציאי ואל תנחשי. ערך חסר נשאר חסר.
- travelers הוא מקור אמת אחד לכל החופשה. "זוג"=2 מבוגרים. "זוג עם ילדה בת 17"=2 מבוגרים, ילד/ה 1, child_ages=[17].
- יום+חודש בלי שנה מקבל את המופע העתידי הקרוב ביותר ביחס לתאריך הנוכחי.
- requested_services ו-service_decisions נשמרים מצטבר ומשתנים רק לפי דברי הלקוח.
- search_confirmed נקבע רק על ידי מנגנון האישור בקוד, לא על ידך.
- לאחר עדכון הנתונים חשבי missing_required מה-state המלא והרלוונטי בלבד. הוא רשימת השדות שאריאלה מחזירה לטינקרבל כדי לדעת מה עדיין צריך לברר.
- אל תסמני כשדה חסר שירות שהלקוח אמר שאינו רוצה.
- ready_for_summary=true רק כאשר יש כוונת חיפוש וכל שדות החובה לשירותים המבוקשים מלאים.

החזירי JSON תקין בלבד:
{
 "trip_update":{
  "trip_type":null,
  "travelers":{"adults":null,"children":null,"child_ages":[],"infants":null,"composition":null},
  "destination":{"places":[],"mode":null,"status":"unknown"},
  "departure_airport":null,
  "dates":{"departure":null,"return":null,"period":null,"flexibility_days":null,"constraints":[]},
  "budget_per_person":{"amount":null,"currency":null,"status":"unknown"},
  "flight":{"connection_preference":null,"max_connections":null,"cabin":null,"baggage":[],"preferences":[]},
  "priorities":[],"hard_constraints":[],"current_request":null,
  "search_intent":false,"requested_services":[],"service_decisions":{},
  "missing_required":[],"ready_for_summary":false,"search_confirmed":false,
  "lodging":{"interested":"unknown","details":{}},
  "car":{"interested":"unknown","details":{}},
  "trip_planning":{"interested":"unknown","details":{}}
 }
}
'''



def _weekday_date_conflict(message):
    """Validate every explicit Hebrew weekday/date pairing deterministically."""
    import re
    text = str(message or "")
    weekdays = {"ראשון":6,"שני":0,"שלישי":1,"רביעי":2,"חמישי":3,"שישי":4,"שבת":5}
    day_re = r"(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)"
    date_re = r"(\\d{1,2})[./-](\\d{1,2})(?:[./-](\\d{2,4}))?"
    # Pair a weekday with the nearest date on either side (up to 40 chars).
    pairs = []
    for m in re.finditer(day_re + r".{0,40}?" + date_re, text):
        pairs.append((m.group(1), m.group(2), m.group(3), m.group(4)))
    for m in re.finditer(date_re + r".{0,40}?" + day_re, text):
        pairs.append((m.group(4), m.group(1), m.group(2), m.group(3)))
    seen = set()
    for day_name, ds, mos, ys in pairs:
        sig=(day_name,ds,mos,ys)
        if sig in seen: continue
        seen.add(sig)
        d, mo = int(ds), int(mos)
        y = int(ys) if ys else date.today().year
        if y < 100: y += 2000
        if not ys and (mo, d) < (date.today().month, date.today().day): y += 1
        try:
            dt = date(y, mo, d)
        except ValueError:
            continue
        if dt.weekday() != weekdays[day_name]:
            actual = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"][dt.weekday()]
            return f"רק לוודא לפני שממשיכים — {d}.{mo}.{y} יוצא יום {actual}, אבל כתבת יום {day_name}. איזה מהם נכון מבחינתך?"
    return None

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
        'input': [{'role': 'developer', 'content': system_prompt}] + _conversation(history[-16:], message),
        'max_output_tokens': max_tokens,
    }
    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=22,
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


def _merge_trip_state(previous, incoming):
    """Recursively preserve collected trip facts; only meaningful new values overwrite them."""
    previous = previous if isinstance(previous, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    merged = dict(previous)
    for key, value in incoming.items():
        old = merged.get(key)
        if isinstance(value, dict):
            merged[key] = _merge_trip_state(old if isinstance(old, dict) else {}, value)
            continue
        # Extractor defaults/omissions must not erase facts already collected.
        if value is None or value == [] or value == {} or value == "unknown":
            if key in merged:
                continue
        # False is a valid explicit value for some fields, but for cumulative search
        # flags it must never undo a prior True.
        if key in {"search_intent", "ready_for_summary", "search_confirmed"} and old is True and value is False:
            continue
        merged[key] = value
    return merged


def _state_context(state):
    return json.dumps(state or {}, ensure_ascii=False, separators=(',', ':'))


def _required_state_gaps(state):
    """Validate the structured state itself before allowing a final summary/search."""
    state = state if isinstance(state, dict) else {}
    services = set(state.get("requested_services") or [])
    decisions = state.get("service_decisions") if isinstance(state.get("service_decisions"), dict) else {}
    for service in ("flights", "lodging", "car", "trip_planning"):
        decision = decisions.get(service)
        # Extracted service_decisions may legitimately be a boolean or an object.
        # Normalize both shapes instead of assuming .get() exists.
        wanted = decision.get("wanted") if isinstance(decision, dict) else decision
        if wanted is True:
            services.add(service)

    gaps = []
    destination = state.get("destination") if isinstance(state.get("destination"), dict) else {}
    dates = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    travelers = state.get("travelers") if isinstance(state.get("travelers"), dict) else {}
    flight = state.get("flight") if isinstance(state.get("flight"), dict) else {}

    if services and not (destination.get("places") or []):
        gaps.append("destination")
    if services and not ((dates.get("departure") and dates.get("return")) or dates.get("period")):
        gaps.append("dates")
    if services and travelers.get("adults") is None:
        gaps.append("travelers")

    if "flights" in services:
        if not state.get("departure_airport"):
            gaps.append("departure_airport")
        if not flight.get("connection_preference"):
            gaps.append("flight.connection_preference")
        if not flight.get("cabin"):
            gaps.append("flight.cabin")
        if not flight.get("baggage"):
            gaps.append("flight.baggage")

    return list(dict.fromkeys(gaps))


def _reset_intent(message):
    """Detect possible restart/change-of-direction language without deleting state."""
    msg = str(message or "").strip().lower()
    phrases = ("חופשה חדשה","טיול חדש","חיפוש חדש","להתחיל מחדש","נתחיל מחדש","מהתחלה","להתחיל מהתחלה","נתחיל מהתחלה","לשנות כיוון")
    return any(p in msg for p in phrases)

def _full_reset_confirmation(message):
    """Only explicit confirmation after the clarification may clear trip state."""
    msg = str(message or "").strip().lower()
    phrases = ("למחוק הכל","למחוק הכול","תמחקי הכל","תמחקי הכול","להתחיל לגמרי מהתחלה","מהתחלה לגמרי","כן למחוק","כן, למחוק")
    return any(p in msg for p in phrases)

def _user_gender_from_approval(message, state):
    msg = str(message or "").strip().lower()
    if msg == "מאשרת":
        return "female"
    if msg == "מאשר":
        return "male"
    return (state or {}).get("user_gender")


def _approval_trigger(message, history, state):
    """Exact final approval is the execution command; generic yes never is."""
    msg = str(message or "").strip().lower()
    return msg in {"מאשר", "מאשרת"}

def _call_tinkerbell(key, model, history, message, state=None):
    system = TINKERBELL_SYSTEM + '\nהתאריך הנוכחי: ' + date.today().isoformat() + '\nמצב החופשה המצטבר שכבר ידוע:\n' + _state_context(state)
    return _post_openai(key, model, system, history, message, 1500).strip()


def _extract_trip_update(key, model, history, message, state=None):
    try:
        system = EXTRACTOR_SYSTEM + '\nמצב החופשה המצטבר לפני ההודעה הנוכחית:\n' + _state_context(state) + '\nהתאריך הנוכחי: ' + date.today().isoformat()
        raw = _post_openai(key, model, system, history, message, 900)
        return _parse_trip_update(raw)
    except Exception:
        return {}


def _deterministic_destination_facts(history, message, state=None):
    """Preserve an explicitly stated destination when extractor output misses it."""
    state = state if isinstance(state, dict) else {}
    current = state.get("destination") if isinstance(state.get("destination"), dict) else {}
    if current.get("places"):
        return {}
    text = " ".join(
        [str(x.get("content") or "") for x in (history or []) if isinstance(x, dict)]
        + [str(message or "")]
    ).lower()
    known = {
        "מונטנגרו": "מונטנגרו", "montenegro": "Montenegro",
        "יוון": "יוון", "greece": "Greece",
        "איטליה": "איטליה", "italy": "Italy",
        "בולגריה": "בולגריה", "bulgaria": "Bulgaria",
        "אלבניה": "אלבניה", "albania": "Albania",
        "קרואטיה": "קרואטיה", "croatia": "Croatia",
        "תאילנד": "תאילנד", "thailand": "Thailand",
    }
    for needle, label in known.items():
        if needle in text:
            return {"destination": {"places": [label], "mode": "specific", "status": "known"}}
    return {}


def _deterministic_date_facts(history, message, state=None):
    """Reinforce explicit dates already present in the conversation without guessing."""
    import re
    state = state if isinstance(state, dict) else {}
    current_dates = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    if current_dates.get("departure") and current_dates.get("return"):
        return {}
    parts = [str(x.get("content") or "") for x in (history or []) if isinstance(x, dict)]
    parts.append(str(message or ""))
    text = " ".join(parts)
    found = []
    for m in re.finditer(r"(?<!\\d)(\\d{1,2})[./-](\\d{1,2})[./-](20\\d{2})(?!\\d)", text):
        try:
            found.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        except ValueError:
            pass
    for m in re.finditer(r"(?<!\\d)(20\\d{2})-(\\d{1,2})-(\\d{1,2})(?!\\d)", text):
        try:
            found.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    unique = []
    for d in found:
        if d not in unique:
            unique.append(d)
    if len(unique) < 2:
        return {}
    dep, ret = unique[-2], unique[-1]
    if ret < dep:
        return {}
    return {"dates": {"departure": dep.isoformat(), "return": ret.isoformat()}}

def _deterministic_traveler_facts(message):
    """Capture common Hebrew traveler phrases so semantic facts never depend on LLM luck."""
    import re
    msg = str(message or "").strip().lower()
    facts = {}
    if "זוג" in msg or any(p in msg for p in ("אני ובעלי", "אני ואשתי", "בעלי ואני", "אשתי ואני")):
        facts["adults"] = 2

    child_count = None
    if re.search(r"(?:עם|ו)\s*(?:ה)?(?:ילדה|בת)\b", msg):
        child_count = 1
    elif re.search(r"(?:עם|ו)\s*(?:ה)?(?:ילד|בן)\b", msg):
        child_count = 1
    m = re.search(r"(\d+)\s*(?:ילדים|ילדות)", msg)
    if m:
        child_count = int(m.group(1))
    if child_count is not None:
        facts["children"] = child_count

    ages = []
    for m in re.finditer(r"(?:בת|בן)\s*(\d{1,2})\b", msg):
        age = int(m.group(1))
        if 0 <= age <= 17:
            ages.append(age)
    if ages:
        facts["child_ages"] = ages
        if "children" not in facts:
            facts["children"] = len(ages)

    if re.search(r"2\s*(?:הורים|מבוגרים)", msg):
        facts["adults"] = 2
    return {"travelers": facts} if facts else {}


@ariella_chat_clean.post('/api/ariella/chat-clean')
def chat_clean():
    body = request.get_json(silent=True) or {}
    message = str(body.get('message') or '').strip()
    if not message:
        return jsonify({'status': 'error', 'message': 'message is required', 'engine_version': ENGINE_VERSION}), 400

    history = body.get('history') if isinstance(body.get('history'), list) else []
    trip_state = body.get('trip_state') if isinstance(body.get('trip_state'), dict) else {}

    # General restart/change-of-direction always enters a simple yes/no gate.
    # Never erase collected trip facts before an explicit "כן".
    if _reset_intent(message) and not trip_state.get("reset_pending"):
        pending = dict(trip_state)
        pending["reset_pending"] = True
        pending["reset_change_request"] = message
        return jsonify({
            'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
            'reply':'רוצה למחוק את כל פרטי החופשה הנוכחית ולהתחיל מחדש?',
            'trip_update':pending,'start_flight_search':False
        })

    if trip_state.get("reset_pending"):
        msg_norm = str(message or "").strip().lower()
        yes_answers = {"כן", "כן.", "כן!", "בטח", "בהחלט"}
        no_answers = {"לא", "לא.", "לא!", "לא תודה"}

        if msg_norm in yes_answers:
            return jsonify({
                'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
                'reply':'בסדר. מתחילים חופשה חדשה. לאן מתחשק לך לטוס ובאיזו תקופה?',
                'trip_update':{},'start_flight_search':False,'trip_state_reset':True
            })

        if msg_norm in no_answers:
            original_change = str(trip_state.get("reset_change_request") or "").strip()
            kept = dict(trip_state)
            kept["reset_pending"] = False
            kept.pop("reset_change_request", None)
            # If the original message only expressed a general wish to change,
            # ask what to change. If it already named the requested change, keep
            # the trip facts and let the next turn continue from that context.
            return jsonify({
                'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
                'reply':'מה תרצי לשנות בחופשה הנוכחית?',
                'trip_update':kept,'start_flight_search':False
            })

        # While awaiting this gate, do not let the model reinterpret or mutate
        # the trip. Keep the question binary and deterministic.
        pending = dict(trip_state)
        return jsonify({
            'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
            'reply':'רק כדי לוודא: למחוק את כל פרטי החופשה ולהתחיל מחדש? כן או לא?',
            'trip_update':pending,'start_flight_search':False
        })

    date_conflict = _weekday_date_conflict(message)
    if date_conflict:
        return jsonify({'status':'success','agent':'Tinkerbell','engine_version':ENGINE_VERSION,'reply':date_conflict,'trip_update':trip_state})
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    model = os.getenv('ARIELLA_MODEL', 'gpt-5.6-luna').strip()

    try:
        # Tinkerbell's data-transfer pass tells Ariella what changed.
        # Ariella owns and merges the cumulative state.
        extracted = _extract_trip_update(key, model, history, message, trip_state)
        trip_update = _merge_trip_state(trip_state, extracted)
        trip_update = _merge_trip_state(trip_update, _deterministic_traveler_facts(message))
        trip_update = _merge_trip_state(trip_update, _deterministic_destination_facts(history, message, trip_update))
        trip_update = _merge_trip_state(trip_update, _deterministic_date_facts(history, message, trip_update))

        # Ariella computes the authoritative remaining gaps and returns the updated
        # state to Tinkerbell. Tinkerbell then decides naturally what to ask next.
        state_gaps = _required_state_gaps(trip_update)
        if state_gaps:
            trip_update["missing_required"] = state_gaps
            trip_update["ready_for_summary"] = False
        else:
            trip_update["missing_required"] = []

        try:
            reply = _call_tinkerbell(key, model, history, message, trip_update)
        except Exception as exc:
            logging.exception("Tinkerbell reply failed after state update: %s", exc)
            # Preserve Ariella's newly collected state even if the conversational
            # model has a transient failure. The next user turn can continue.
            reply = "קלטתי את הפרטים. נמשיך מכאן."

        # Never let the conversation claim it is ready for a final summary when
        # the structured source of truth is missing required facts. This keeps
        # the visible summary and downstream execution on the same data object.
        state_gaps = _required_state_gaps(trip_update)
        if state_gaps:
            trip_update["missing_required"] = state_gaps
            trip_update["ready_for_summary"] = False
        else:
            trip_update["missing_required"] = []

        # Search approval is a system event, not a language-model decision.
        approval = _approval_trigger(message, history, trip_state)
        # A generic "yes" during normal data collection is NEVER a search approval.
        # It must only approve an explicit final approval question / ready state.
        msg_norm = str(message or "").strip().lower()
        generic_yes = msg_norm in {"כן","נכון","מעולה","מצוין","מצויין","סבבה","אחלה","נשמע טוב","נשמע אחלה"}
        if generic_yes and not approval:
            # Do not let extractor/model turn this ordinary conversational answer
            # into search intent or missing-data validation.
            trip_update["search_intent"] = bool(trip_state.get("search_intent"))
            trip_update["search_confirmed"] = bool(trip_state.get("search_confirmed"))
            trip_update["ready_for_summary"] = bool(trip_state.get("ready_for_summary"))
            if not trip_state.get("search_intent"):
                trip_update["missing_required"] = list(trip_state.get("missing_required") or [])
        if approval:
            merged = _merge_trip_state(trip_state, trip_update if isinstance(trip_update, dict) else {})
            # Exact מאשר/מאשרת is the execution command. Required-field validation
            # belongs to the structured execution endpoint; it must never silently
            # suppress the handoff and leave the user in chat.
            merged["search_intent"] = True
            merged["search_confirmed"] = True
            merged["ready_for_summary"] = True
            merged["user_gender"] = _user_gender_from_approval(message, merged)
            services = list(merged.get("requested_services") or [])
            # Approval at a flight confirmation stage is authoritative: mark flights requested.
            if "flights" not in services:
                services.append("flights")
            flight_state = merged.get("flight") if isinstance(merged.get("flight"), dict) else {}
            has_flight_data = bool(
                merged.get("departure_airport")
                or flight_state.get("connection_preference")
                or flight_state.get("cabin")
                or flight_state.get("baggage")
                or (merged.get("dates") or {}).get("departure")
                or (merged.get("dates") or {}).get("return")
            )
            history_text = " ".join(str(x.get("content") or "") for x in history if isinstance(x, dict))
            if ("flights" not in services) and (has_flight_data or any(word in history_text for word in ("טיסה","טיסות","טיסות ישירות"))):
                services.append("flights")
            merged["requested_services"] = services
            trip_update = merged
    except Exception as exc:
        logging.exception("ariella chat-clean pipeline failed: %s", exc)
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503

    return jsonify({
        'status': 'success',
        'agent': 'Tinkerbell',
        'engine_version': ENGINE_VERSION,
        'reply': reply or 'אני איתך 😊',
        'trip_update': trip_update,
        # Execution is allowed only when the deterministic approval gate fired
        # on THIS user message. Never let model-extracted state start a scan.
        'start_flight_search': bool(approval) and bool(trip_update.get('search_confirmed')),
    })
