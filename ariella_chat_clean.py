import json
import os
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, request
from travel_agents import _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'tinkerbell-chat-v10'

TINKERBELL_SYSTEM = '''את מלוות החופשה של אריאלה. אריאלה כבר פתחה את השיחה; מכאן את משוחחת עם הלקוח באופן חופשי וטבעי עד שלב ההזמנה.

התפקיד היחיד שלך כאן הוא לנהל שיחה מצוינת. אין לך טופס למלא ואין לך רשימת פרטים להשלים.
- דברי כמו שיחת ChatGPT טובה: טבעית, חמה, חכמה וקצרה.
- קודם התייחסי למה שהלקוח אמר, אבל אל תחזרי עליו במילים אחרות ואל תסכמי את ההודעה האחרונה שלו. אם אין צורך בתגובה מהותית, המשיכי ישירות לנקודה הבאה.
- הימנעי מפתיחים כמו "מעולה, אז...", "הבנתי ש...", "מצוין, יש לנו..." ואחריהם חזרה על הנתונים שהלקוח זה עתה מסר. אישור קצר כמו "מעולה" מותר רק כשבאמת מועיל.
- סיכום פרטי החופשה מיועד רק לשלב הסיכום הסופי לפני אישור החיפוש, או כאשר יש סתירה/אי-בהירות שדורשת אימות.
- אל תראייני את הלקוח. אל תנהלי רצף של שאלות איסוף נתונים.
- אל תשאלי שאלה רק מפני שחסר לך מידע על החופשה.
- שאלי שאלה רק כשהיא המשך טבעי למה שהלקוח עצמו מנסה לברר או כשהיא באמת נחוצה כדי לענות לבקשה הנוכחית.
- אין חובה לשאול שאלה בכל הודעה. לעיתים התשובה הטובה ביותר היא פשוט תגובה או המלצה.
- אם כבר נאמר פרט בשיחה או במצב החופשה המצטבר, זכרי אותו. אם הלקוח משנה אותו, התייחסי לגרסה החדשה. אסור לשאול שוב פרט שכבר ידוע.
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
- בכל הודעה מותר לבקש מהלקוח לכל היותר שלושה פרטים/החלטות שונים. זהו גבול קשיח, לא המלצה.
- כל סעיף שהלקוח צריך לענות עליו נחשב שאלה נפרדת גם אם ניסחת כמה סעיפים בתוך משפט אחד. לדוגמה: "ישירה או קונקשן, מזוודה לכל נוסע, מלון או דירה, ובאיזו רמה?" הן ארבע שאלות ואסור לשלוח אותן יחד.
- אם חסרים יותר משלושה פרטים, בחרי את 1–3 הפרטים שהכי טבעי לברר עכשיו, המתיני לתשובה, ורק בהודעה הבאה שאלי את היתר.
- אל תצרפי לשאלה שלוש שאלות ואז תוסיפי בסוף עוד בחירה או שאלה "קטנה". סך כל הדברים שמבקשים מהלקוח להחליט או למסור בהודעה אחת הוא עד שלושה.
- לטיסות, בדקי בין היתר רק כשחסר ורלוונטי: תקציב לאדם, כבודה, ישירה/קונקשן, מחלקה, מוצא ותאריכים.
- ללינה, בדקי רק כשחסר ורלוונטי: סוג לינה (מלון/וילה/דירה), מספר/הרכב חדרים, רמת לינה או תקציב לאדם, מיקום ודרישות מהותיות לחיפוש.
- לרכב, בדקי רק כשחסר ורלוונטי: מספר נוסעים, מקום לכבודה, סוג/גודל רכב, נקודת וזמן איסוף והחזרה.
- לתכנון מסלול ואטרקציות, בדקי רק כשחסר ורלוונטי: אופי החופשה, קצב, מגבלות נסיעה ודברים שחייבים/לא רוצים.
- אל תשאלי שוב שום פרט שכבר נאמר בשיחה או קיים במצב החופשה המצטבר.
- לפני כל שאלה על תאריכים, מספר נוסעים, שדה מוצא, טיסה, לינה, רכב או מסלול, בדקי קודם את מצב החופשה המצטבר. אם הערך כבר קיים שם, השתמשי בו ואל תשאלי אותו שוב גם אם הוא לא מופיע בהודעות האחרונות.\n- כשחודש או תאריך יום+חודש מוזכרים בלי שנה, קבעי את השנה אוטומטית ביחס לתאריך הנוכחי: אם התאריך עדיין לפנינו השנה — השנה הנוכחית; אם הוא כבר עבר — השנה הבאה. לדוגמה, בספטמבר 2026 "28.7" פירושו 28.7.2027. אסור לשאול "באיזו שנה?" במקרה כזה. שאלי שנה רק אם הלקוח עצמו נתן מידע שסותר את החישוב או שיש יותר מפרשנות סבירה אחת.
- התאריך הנוכחי יוזרק אלייך בכל פנייה. לעולם אל תציעי, תסכמי או תאשרי תאריך שכבר עבר אלא אם הלקוח ביקש במפורש לדבר על העבר. יום+חודש ללא שנה חייב להפוך למופע העתידי הקרוב ביותר שלו. לדוגמה, כשהיום בספטמבר 2026, 28.6 פירושו 28.6.2027 ולא 2026.
- רק לאחר שכל המידע ההכרחי לשירותים שהתבקשו הושלם, הציגי סיכום קצר ומלא של בקשת החיפוש ובקשי אישור מפורש. אישור הלקוח הוא הטריגר הסופי לסריקה.
- את סיכום בקשת החיפוש שולחים פעם אחת בלבד. אם הסיכום כבר נשלח והלקוח משיב בחיוב, אין לסכם שוב; יש לאשר בקצרה שהבקשה התקבלה ולהמשיך לביצוע.
- אם הלקוח כותב בעברית, השיבי בעברית בלבד. אם הוא בוחר שפה אחרת, השיבי בשפה שלו.
- החזירי רק את ההודעה שהלקוח צריך לראות. בלי JSON, בלי הסברים פנימיים ובלי תהליך עבודה.
- אין צורך להזדהות בשם טינקרבל מול הלקוח.
- אל תשתמשי בכוכביות, Markdown או סימני עיצוב. כתבי טקסט נקי בלבד; ממשק האתר אחראי לעיצוב.
'''

EXTRACTOR_SYSTEM = '''את שכבת חילוץ נתוני החופשה של אריאלה. אינך משוחחת עם הלקוח ואינך מחליטה איזו שאלה לשאול. קבלי את היסטוריית השיחה וחלצי רק מידע שהלקוח כבר מסר או שינה.

כללים:
- אל תמציאי מידע ואל תשלימי שדות חסרים.\n- מצב החופשה המצטבר המצורף הוא מקור אמת לפרטים שכבר נאספו. החזירי מצב מלא ומעודכן, לא רק את ההודעה האחרונה. לעולם אל תאפסי ערך קיים ל-null, מערך ריק, unknown או false רק מפני שהוא לא הופיע שוב בהודעה הנוכחית; העתיקי את הערך הקיים ושני רק מידע שהלקוח הוסיף, תיקן או ביטל במפורש.\n- חודש או יום+חודש בלי שנה: קבעי את המופע העתידי הקרוב ביותר ביחס לתאריך הנוכחי. אם היום אחרי אותו יום+חודש בשנה הנוכחית, השנה היא הבאה. לעולם אל תחזירי תאריך עבר כברירת מחדל.
- אין שדה משך חופשה.
- תקציב נשמר לאדם בלבד. אם הלקוח נתן תקציב כולל ומספר הנוסעים ידוע בבטחה, חשבי לאדם; אחרת השאירי לא ידוע.
- לזהות: סוג חופשה; נוסעים ומבנה; יעד/ים ומידת הוודאות; שדה מוצא; תאריכים/תקופה/גמישות ומגבלות; תקציב לאדם; ישירה/קונקשן, מחלקה, כבודה והעדפות טיסה; עדיפויות ומגבלות קשיחות; בקשת הלקוח הנוכחית.
- זהי search_intent=true רק כאשר מההקשר ברור שהלקוח מבקש עכשיו לקבל תוצאות ממשיות/אפשרויות קונקרטיות/לינקים לביצוע. המילים "תחפשי לי" לבדן אינן מספיקות. אחרת false.
- זהי אילו שירותים הלקוח מבקש לקבל בפועל בתוך requested_services: flights, lodging, car, trip_planning. אל תניחי שירות שלא התבקש.
- שמרי גם service_decisions עבור flights, lodging, car, trip_planning עם wanted=true/false/unknown. תחום שלא דובר עליו נשאר unknown; אין להפוך unknown ל-false. כך שכבת השיחה יודעת אילו תחומים עוד צריך להעלות באופן טבעי.
- אם הלקוח העלה תחום ואז השיחה סטתה זמנית לבירור טיסה, התחום המקורי נשאר wanted=true ואסור לאבד אותו.
- אם התבקשו lodging, car או trip_planning ומצב הטיסה טרם נאמר, אל תניחי flights ואל תסמני שהאיסוף מוכן לסיכום; שמרי חוסר בשם flight_decision עד שהלקוח יאמר אם לחפש גם טיסה או שהטיסה כבר סגורה/לא נדרשת.
- כאשר search_intent=true, חשבי missing_required לפי השירותים שהתבקשו בלבד. לטיסות יכולים להידרש, לפי ההקשר: יעד/ים, תאריכים/תקופה, נוסעים, מוצא, תקציב לאדם, כבודה, ישירה/קונקשן ומחלקה. ללינה יכולים להידרש: יעד/מסלול, תאריכים, נוסעים, סוג לינה, חדרים, רמת לינה/תקציב והעדפות מהותיות. לרכב: יעד/מסלול, תאריכים, נוסעים, כבודה/מקום נדרש, סוג רכב ואיסוף/החזרה. לתכנון מסלול: יעד/תקופה, נוסעים, אופי הטיול ומגבלות מהותיות. אל תכללי שדה שכבר נמסר.
- ready_for_summary=true רק כש-search_intent=true ואין עוד missing_required לשירותים שהתבקשו.
- זהי search_confirmed=true רק לאחר שהוצג ללקוח סיכום בקשת החיפוש והוא אישר במפורש לצאת לחיפוש. אחרת false.
- לאחר שסיכום הבקשה כבר הוצג כשהמצב ready_for_summary=true, תשובה חיובית ברורה של הלקוח מסמנת search_confirmed=true. זהו מצב מצטבר ואין לאפס אותו לאחר שנקבע.
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
    "search_intent": false,
    "requested_services": [],
    "missing_required": [],
    "ready_for_summary": false,
    "search_confirmed": false,
    "lodging": {"interested": "unknown", "details": {}},
    "car": {"interested": "unknown", "details": {}},
    "trip_planning": {"interested": "unknown", "details": {}}
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


def _approval_trigger(message, history, state):
    """Only a dedicated final-search confirmation may start execution."""
    msg = str(message or "").strip().lower()
    explicit_search = any(x in msg for x in (
        "תמצאי לי טיסות","תחפשי לי טיסות","תבדקי לי טיסות",
        "אפשר לצאת לבדיקה","אפשר לצאת לחיפוש","צאי לחיפוש","תתחילי בחיפוש"
    ))
    if explicit_search:
        return True

    explicit_approval = msg in {
        "כן","נכון","מאשר","מאשרת","חיובי","צאי לדרך","צא לדרך","אישור","מאושר","מאושרת",
        "נשמע אחלה","נשמע טוב","מעולה","מצוין","מצויין","סבבה","אחלה"
    }
    if not explicit_approval:
        return False

    state = state if isinstance(state, dict) else {}
    # Do not infer final approval merely because the conversation contains flights.
    # The accumulated state must explicitly say the data collection reached its
    # final summary/approval gate.
    return bool(state.get("ready_for_summary")) and not bool(state.get("search_confirmed"))

def _call_tinkerbell(key, model, history, message, state=None):
    system = TINKERBELL_SYSTEM + '\nהתאריך הנוכחי: ' + date.today().isoformat() + '\nמצב החופשה המצטבר שכבר ידוע:\n' + _state_context(state)
    return _post_openai(key, model, system, history, message, 1500).strip()


def _extract_trip_update(key, model, history, message, state=None):
    try:
        system = EXTRACTOR_SYSTEM + '\nמצב החופשה המצטבר לפני ההודעה הנוכחית:\n' + _state_context(state) + '\nהתאריך הנוכחי: ' + date.today().isoformat()
        raw = _post_openai(key, model, system, history, message, 650)
        return _parse_trip_update(raw)
    except Exception:
        return {}


@ariella_chat_clean.post('/api/ariella/chat-clean')
def chat_clean():
    body = request.get_json(silent=True) or {}
    message = str(body.get('message') or '').strip()
    if not message:
        return jsonify({'status': 'error', 'message': 'message is required', 'engine_version': ENGINE_VERSION}), 400

    history = body.get('history') if isinstance(body.get('history'), list) else []
    trip_state = body.get('trip_state') if isinstance(body.get('trip_state'), dict) else {}
    date_conflict = _weekday_date_conflict(message)
    if date_conflict:
        return jsonify({'status':'success','agent':'Tinkerbell','engine_version':ENGINE_VERSION,'reply':date_conflict,'trip_update':trip_state})
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    model = os.getenv('ARIELLA_MODEL', 'gpt-5.6-luna').strip()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reply_job = pool.submit(_call_tinkerbell, key, model, history, message, trip_state)
            state_job = pool.submit(_extract_trip_update, key, model, history, message, trip_state)
            reply = reply_job.result()
            extracted = state_job.result()
            # Preserve accumulated facts deterministically. The extractor may update facts,
            # but omitted/default values must never erase information already collected.
            trip_update = _merge_trip_state(trip_state, extracted)

        # Search approval is a system event, not a language-model decision.
        approval = _approval_trigger(message, history, trip_state)
        if approval:
            merged = _merge_trip_state(trip_state, trip_update if isinstance(trip_update, dict) else {})
            merged["search_intent"] = True
            merged["search_confirmed"] = True
            merged["ready_for_summary"] = True
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
    except Exception:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503

    return jsonify({
        'status': 'success',
        'agent': 'Tinkerbell',
        'engine_version': ENGINE_VERSION,
        'reply': reply or 'אני איתך 😊',
        'trip_update': trip_update,
        # Execution is allowed only when the deterministic approval gate fired
        # on THIS user message. Never let model-extracted state start a scan.
        'start_flight_search': bool(approval) and bool(trip_update.get('search_confirmed')) and ('flights' in (trip_update.get('requested_services') or [])),
    })
