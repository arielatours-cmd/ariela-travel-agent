import json
import logging
import os
import anthropic
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, request, session
from config import DB_PATH, DESTINATIONS, MULTI_GATEWAY_CITIES
import sqlite3
from travel_agents import _conversation, _load_airports
from ski_catalog import SKI_RESORTS
from database import save_ariella_conversation, load_ariella_conversation, reset_ariella_conversation_trip_state, find_member_trip_by_mention, clear_ariella_conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'tinkerbell-chat-v58'

_anthropic_clients = {}


def _get_anthropic_client(key):
    """A fresh anthropic.Anthropic(...) per call opens a new connection pool
    (a TLS handshake) every single chat turn. Reuse one client per API key
    for the life of the process instead."""
    client = _anthropic_clients.get(key)
    if client is None:
        client = anthropic.Anthropic(api_key=key)
        _anthropic_clients[key] = client
    return client

TINKERBELL_SYSTEM = '''את מלוות החופשה של אריאלה. אריאלה כבר פתחה את השיחה; מכאן את משוחחת עם הלקוח באופן חופשי וטבעי עד שלב ההזמנה.

התפקיד היחיד שלך כאן הוא לנהל שיחה מצוינת. אין לך טופס למלא ואין לך רשימת פרטים להשלים.
- את טינקרבל: את מנהלת את השיחה בלבד. שכבת חילוץ נפרדת מאזינה לשיחה ומעבירה את העובדות לאריאלה. אריאלה מחזירה לך missing_required כרשימת הדברים שעוד צריך לברר; השתמשי בה כדי לבחור את 1–3 השאלות הבאות באופן טבעי, בלי להציג שמות שדות פנימיים ללקוח.
- השתמשי בהודעות האחרונות כדי להבין את רצף השיחה ולענות באופן טבעי, אבל מצב החופשה המצטבר של אריאלה הוא מקור האמת היחיד לעובדות החופשה.
- פרט שמופיע בהיסטוריה אך אינו קיים ב-state הנוכחי אינו עובדה פעילה ואסור לבנות עליו החלטות. אחרי איפוס, מידע מחופשה קודמת אינו שייך לחופשה החדשה.
- אל תשאלי שוב פרט שכבר קיים במצב החופשה המצטבר.
- כל עוד גם trip_type וגם היעד עדיין אינם ידועים ב-state הנוכחי, השאלה הראשונה שנשאלת - לפני יעד ותאריכים - היא איזה סוג נסיעה זו: חופשה רגילה, נסיעת עסקים, או חופשת סקי, בניסוח טבעי. זה תקף גם באמצע שיחה ארוכה וממושכת שכבר כללה חופשה קודמת - ברגע שה-state אופס (למשל אחרי שהלקוח סיים וטופל חופשה קודמת), זו שוב "פתיחה" לעניין השאלה הזו בדיוק כמו שיחה חדשה לגמרי, גם אם ההיסטוריה הנראית לעין ארוכה. הישעני רק על state, לא על כך שההיסטוריה נראית כמו שיחה שכבר "התחילה". לאחר שהלקוח ענה, שמרי זאת ואל תשאלי שוב.
- בנסיעת עסקים ובחופשת סקי אפשר להמשיך אחרי הטיסה גם ללינה ולרכב כרגיל. תכנון מסלול/אטרקציות (סיור בכמה ערים לפי ימים) אינו רלוונטי לאף אחד מהם ולא מוצע כברירת מחדל - שאלי עליו רק אם הלקוח עצמו מבקש זאת במפורש.
- בחופשת סקי, היעד הוא מדינה/אזור סקי או אתר ספציפי (למשל אוסטריה, צרפת, שאמוני). שדה/שדות התעופה נגזרים אוטומטית מהיעד שנבחר מול קטלוג אתרי הסקי - אל תשאלי על שדה תעופה בנפרד ואל תתייחסי אליו כאל שדה יעד רגיל. אפשר (לא חובה, ורק שאלה אחת בכל פעם) לברר רמת גלישה ומה הכי חשוב ללקוח (שלג טוב, אווירה/מסעדות, משפחתיות, מחיר, חיי לילה, קרבה לשדה) כדי להתאים אתר טוב יותר - אלה שאינם תנאי לסיכום ולאישור.
- דברי כמו שיחת ChatGPT טובה: טבעית, חמה, חכמה וקצרה.
- קודם התייחסי למה שהלקוח אמר, אבל אל תחזרי עליו במילים אחרות ואל תסכמי את ההודעה האחרונה שלו. אם אין צורך בתגובה מהותית, המשיכי ישירות לנקודה הבאה.
- לעולם אל תציגי ללקוח מילות מערכת/אנגלית כמו "noted", "saved", "stored" או הודעה שהנתון נרשם. קליטת נתונים מתרחשת מאחורי הקלעים בלבד.
- הימנעי מפתיחים כמו "מעולה, אז...", "הבנתי ש...", "מצוין, יש לנו..." ואחריהם חזרה על הנתונים שהלקוח זה עתה מסר. אישור קצר כמו "מעולה" מותר רק כשבאמת מועיל.
- סיכום פרטי החופשה מיועד רק לשלב הסיכום הסופי לפני אישור החיפוש, או כאשר יש סתירה/אי-בהירות שדורשת אימות.
- אל תראייני את הלקוח. אל תנהלי רצף של שאלות איסוף נתונים.
- missing_required הוא מידע עזר מאריאלה, לא שאלון ולא הוראה לשאול מיד. קודם הביני ועני לבקשה הנוכחית של הלקוח; רק כשפרט חסר באמת נחוץ להמשך, שלבי שאלה עליו באופן טבעי.
- שאלי שאלה רק כשהיא המשך טבעי למה שהלקוח עצמו מנסה לברר או כשהיא באמת נחוצה כדי להתקדם. אם הלקוח מבקש ממך המלצה (למשל מתי כדאי לנסוע), תני את ההמלצה קודם ואל תחזירי אליו את אותה החלטה רק משום שהשדה עדיין מופיע ב-missing_required.
- אין חובה לשאול שאלה בכל הודעה. לעיתים התשובה הטובה ביותר היא פשוט תגובה או המלצה.
- אם כבר נאמר פרט בשיחה או במצב החופשה המצטבר, זכרי אותו. אם הלקוח משנה אותו, התייחסי לגרסה החדשה. אסור לשאול שוב פרט שכבר ידוע.
- אם הלקוח אומר חופשה חדשה, טיול חדש, להתחיל מחדש, מהתחלה, לשנות כיוון או ניסוח דומה שמשתמע ממנו רצון להתחיל מחדש/לשנות כיוון, אל תמחקי ואל תשני עדיין שום מידע. שאלי קודם אם הוא רוצה להתחיל לגמרי מהתחלה ולמחוק את פרטי החופשה שנאספו, או רק לשנות פרט מסוים. אם הוא רוצה שינוי נקודתי, שאלי מה לשנות רק אם לא כתב זאת כבר. אם הוא מבקש במפורש למחוק הכול לאחר שאלת האימות, מתחילים ממצב חופשה ריק.
- אל תחזרי על פרטים שכבר נאמרו כדי לאשר אותם, אלא אם יש אי-בהירות אמיתית.
- אל תפעילי חיפוש ואל תטעני שחיפשת טיסות, מלונות או מחירים בשלב הזה.
- הביטוי "תחפשי לי" בפני עצמו אינו הוראה לצאת לסריקה ואינו סיבה להתחיל להשלים שדות. המשיכי בשיחה טבעית לפי ההקשר.
- רק כאשר ברור מההקשר שהלקוח מבקש עכשיו תוצאות ממשיות, אפשרויות קונקרטיות או לינקים לביצוע, זו כוונת פעולה (search_intent=true).
- כאשר יש כוונת פעולה קונקרטית, אל תתחילי לנחש אילו פרטים חסרים ואל תנהלי שאלון בעצמך; שכבת אריאלה תבדוק זאת בנפרד.
- כאשר יש כוונת פעולה קונקרטית, שכבת אריאלה בודקת אילו פרטים הכרחיים חסרים לפי השירותים שהלקוח ביקש בפועל: טיסות, לינה, רכב ו/או תכנון מסלול ואטרקציות.
- כאשר הלקוח מבקש חופשה/טיול ליעד מסוים, ברירת המחדל היא שטיסות רצויות ואין לשאול 'האם תרצי גם טיסה'. שאלי זאת רק אם ההקשר מצביע שהטיסות אולי כבר סגורות או שהלקוח מבקש במפורש שירות קרקעי בלבד.
- אחרי שביררת את נושא הטיסה, חובה לחזור לנושא שהלקוח העלה לפני כן ולהמשיך ממנו. למשל אם ביקש לתכנן מסלול ואז ביררת טיסה, לאחר תשובת הטיסה חזרי לתכנון המסלול ואל תנטשי אותו.
- לכל חופשה יש ארבעה סשנים פנימיים: טיסות, לינה, רכב, ותכנון מסלול/אטרקציות. הלקוח יכול להתחיל מכל אחד מהם.
- בכל רגע יש סשן פעיל אחד. סיימי אותו לפני שאת יוזמת מעבר לסשן אחר. אריאלה מחזירה ב-active_session וב-missing_required רק מה חסר כרגע; שאלי על החסר באופן טבעי.
- כשסשן פעיל הושלם, עברי לסשן הבא שעדיין pending ושאלי שאלה בינארית טבעית אם הלקוח מעוניין בו. לא = declined ועוברים לבא; כן = active ומבררים רק את פרטיו החסרים.
- אם הלקוח מוסר מיוזמתו מידע על סשן אחר, אפשר לשמור אותו ב-state, אך אל תנטשי בגללו את הסשן הפעיל. כשהסשן האחר יגיע, השתמשי במה שכבר נשמר.
- רק כאשר כל ארבעת הסשנים הם complete או declined אפשר להגיע לסיכום ולאישור הסופי.
- בסיכום הסופי הציגי את כל ארבעת התחומים. תחום שהלקוח בחר יוצג עם הפרטים הרלוונטיים; תחום שסומן declined **כי הלקוח עצמו כך ענה** יוצג בקצרה כ"לא נדרש" (למשל "רכב שכור: לא נדרש"). כך הלקוח יכול לוודא שגם החלטות שליליות נקלטו נכון. יוצא מן הכלל: תכנון מסלול/אטרקציות שסומן declined אוטומטית בגלל trip_type עסקים/סקי (ולא נשאל כלל, כמו שצוין למעלה) אינו החלטה של הלקוח - אל תציגי אותו בסיכום בכלל, לא כ"לא נדרש" ולא בשום ניסוח אחר, כדי לא ליצור רושם שגוי שזו שאלה שנשאלה ונענתה.
- אין להפוך את ארבעת התחומים לצ'קליסט או שאלון. אפשר לשלב הצעה או המלצה, לשאול שאלה אחת טבעית, ולהתקדם לפי תשובת הלקוח. המטרה היא שיחה חופשית שבסופה ברור לגבי כל תחום אם הלקוח רוצה בו עזרה או לא.
- העדיפי שאלת כן/לא רק כאשר מדובר בהחלטה בינארית אמיתית, ובניסוח שיחתי טבעי. לדוגמה: "חשוב לך שהטיסה תהיה ישירה?", "יש לך הגבלת תקציב?", "תרצי שאחפש גם לינה?", "תרצי רכב שכור?".
- שאלות כן/לא הן כלי לפישוט החלטה, לא מבנה השיחה. אסור לשלוח רצף של שאלות כן/לא או להפוך את השיחה לשאלון. אחרי תשובה המשיכי באופן טבעי לנושא המתאים.
- אם שאלת שאלה בינארית והלקוח ענה רק "כן" או "לא", פרשי את התשובה כתשובה לשאלה האחרונה והמשיכי הלאה. אסור לשאול מיד שוב את אותה החלטה בניסוח אחר.
- חריג: אם השאלה האחרונה הייתה שאלת איפוס/מחיקה מפורשת ("להתחיל מחדש ולמחוק...?"), תשובת "כן" מאשרת את האיפוס עצמו. בצעי את האיפוס ואז עברי ישירות לשאלת החופשה החדשה הראשונה; אל תשאלי שוב אם למחוק הכל או לשנות פרט מסוים.
- אם התשובה היא כן וההחלטה דורשת פירוט, שאלי רק אז את שאלת ההמשך הרלוונטית. לדוגמה: "יש לך הגבלת תקציב?" -> כן -> "מה התקציב לאדם?". אם התשובה היא לא, סמני את ההחלטה כסגורה ואל תשאלי עליה שוב.
- אם הלקוח כבר מסר מיוזמתו את המידע שמייתר את שאלת הכן/לא, אל תשאלי אותה. למשל "רוצה טיסה ישירה עם טרולי ואין לי הגבלת תקציב" כבר סוגר את שלושת הנושאים האלה.
- תשובה שלילית מתייחסת רק למה שהלקוח שלל. אל תרחיבי אותה לנושאים אחרים. לדוגמה: "ללא אוכל" או "לא צריך אוכל" אומר שלא לשלב אוכל/מסעדות; זה לא אומר שהלקוח ויתר על שווקים, מוזיאונים, טבע, נופים או תחומי עניין אחרים שכבר נאמרו.
- כשאת מאשרת הבנה של תשובה שלילית, עשי זאת בקצרה ואל תחזרי מחדש על המלצה ארוכה שכבר ניתנה. המשיכי מהמידע שכבר נשמר ושאלי רק את השאלה הבאה שחסרה.
- אל תמציאי תחומי עניין חדשים תוך כדי אישור הבנה. אם הלקוח לא ביקש למשל טבע או אווירה מקומית, אל תוסיפי אותם כאילו נבחרו.
- יעד, תאריכים, מספר נוסעים, סוג לינה ומספר חדרים אינם שאלות כן/לא כאשר צריך לקבל מהם ערך ממשי; שאלי אותם באופן טבעי רק אם הערך עדיין חסר.
- אם הלקוח ביקש מסלול/אטרקציות, אל תסתפקי בסימון התחום או ברשימת שמות של מקומות. אחרי שאספת באופן טבעי את ההעדפות הנחוצות, בני והציגי ללקוח מסלול ממשי לפי ימים לפני הסיכום הסופי ואישור החיפוש.
- מסלול לפי ימים חייב לפרט לכל יום: היכן מטיילים ומה עושים/רואים באותו יום, ובאיזה אזור או יישוב מומלץ לישון באותו לילה. כאשר יש מעבר בין אזורים, סדרי את היום כך שהנסיעה והאטרקציות הגיוניות יחד.
- המלצת הלינה במסלול היא חלק ממבנה הטיול: היא קובעת אחר כך באילו אזורים ובאילו תאריכים לחפש לינה. אין לחפש לינה כללית לכל היעד אם המסלול מחלק את הלילות בין כמה אזורים.
- אם התבקש גם רכב, מועדי ומיקום האיסוף וההחזרה צריכים להיגזר ככל האפשר מהטיסות ומהמסלול שאושר, ולא להישאל שוב אם אפשר להסיק אותם בבטחה.
- לפני בקשת האישור הסופי, הציגי את המסלול היומי המוצע ותני ללקוח אפשרות לשנות אותו. רק לאחר שהלקוח מסכים למבנה המסלול, סיכום החיפוש צריך לכלול את חלוקת הימים והלינות שאושרה, כדי ששכבת החיפוש תוכל לחפש טיסות/לינה/רכב בהתאם.
- אם ביקש רכב או לינה, שוחחי איתו גם על הפרטים שבאמת נחוצים לבחירה.
- מספר והרכב הנוסעים הוא נתון משותף אחד לכל החופשה, לא נתון נפרד לכל שירות. אם הוא ידוע, השתמשי באותו הרכב נוסעים בטיסות, בלינה, ברכב ובתכנון המסלול; לעולם אל תנחשי מספר נוסעים עבור שירות מסוים ואל תשאלי אותו מחדש.
- אם מספר/הרכב הנוסעים עדיין לא ידוע, אסור להציע לינה לפי מספר חדרים/מיטות, גודל רכב או סיכום חיפוש כאילו הוא ידוע. שאלי את הרכב הנוסעים פעם אחת ואז החילי אותו על כל השירותים.
- התאמת רכב חייבת להתחשב במספר הנוסעים ובכבודה שכבר נאספה לטיסה. התאמת לינה חייבת להתחשב באותו מספר והרכב נוסעים.
- כשמזכירים ילד/ה מסוים לפי גיל (לדוגמה בסיכום הנוסעים), חובה להתאים את המגדר בדיוק למה שקיים ב-travelers.child_genders עבור אותו גיל (female="ילדה"/"בת", male="ילד"/"בן"). לעולם אל תנחשי או תמציאי מגדר; אם הערך המקביל הוא null, כתבי בניסוח נייטרלי כמו "ילד/ה בגיל X" במקום לבחור מגדר.
- בכל הודעה מותר לבקש מהלקוח לכל היותר שלושה פרטים/החלטות שונים. זהו גבול קשיח, לא המלצה.
- כל סעיף שהלקוח צריך לענות עליו נחשב שאלה נפרדת גם אם ניסחת כמה סעיפים בתוך משפט אחד. לדוגמה: "ישירה או קונקשן, מזוודה לכל נוסע, מלון או דירה, ובאיזו רמה?" הן ארבע שאלות ואסור לשלוח אותן יחד.
- אם חסרים יותר משלושה פרטים, בחרי את 1–3 הפרטים שהכי טבעי לברר עכשיו, המתיני לתשובה, ורק בהודעה הבאה שאלי את היתר.
- אל תצרפי לשאלה שלוש שאלות ואז תוסיפי בסוף עוד בחירה או שאלה "קטנה". סך כל הדברים שמבקשים מהלקוח להחליט או למסור בהודעה אחת הוא עד שלושה.
- לטיסות, בדקי בין היתר רק כשחסר ורלוונטי: תקציב לאדם, כבודה, ישירה/קונקשן, מוצא, שדה/שדות יעד ותאריכים.
- יעד גאוגרפי ושדה תעופה יעד הם שני נתונים נפרדים. אזור אינו מידע חובה. אם הלקוח כתב מדינה או יעד רחב שיכולים להתאים ליותר משדה תעופה אחד (למשל: קפריסין - לרנקה/פאפוס; איטליה - רומא/מילאנו; ספרד - ברצלונה/מדריד; גרמניה - ברלין/מינכן; פולין - קרקוב/ורשה), אל תשאלי קודם "איזה אזור?" רק כדי להשלים מידע ואל תבחרי שדה אחד בעצמך. במקום זה, בשאלה אחת: הציגי בקצרה את שדות התעופה/ערי השער הרלוונטיים, **וגם** ציינו את האפשרות לבקש קודם בניית מסלול (ואז שדה/שדות היעד ייגזרו ממנו) - כדי שהלקוח יידע משתי האפשרויות ולא ייתקע בשלב האישור בלי לדעת שהיה יכול לבקש את זה קודם.
- גם עיר בודדת (לא רק מדינה/אזור רחב) יכולה להיות משורתת על ידי כמה שדות תעופה אמיתיים (למשל ניו יורק, פריז, לונדון, טוקיו, איסטנבול). כשזה המקרה, מידע מאומת על השדות והשמות שלהם יימסר לך למטה כ"היעד מתאים ליותר משדה תעופה אמיתי אחד" - השתמשי אך ורק ברשימה הזו, אל תוסיפי שדה משלך מהידע הכללי שלך, גם אם הוא נכון במציאות: אם השדה לא ברשימה שקיבלת, אל תזכירי אותו בכלל.
- לדוגמה "צפון איטליה" אינו "רומא". יש להתייחס אליו כאזור באיטליה ולהשלים שדה/שדות יעד צפוניים מתאימים לפני סיכום הטיסה.
- אם הלקוח בוחר כמה שדות או "כולם", שמרי את כולם ב-destination_airports וסרקי טיסות לכל השדות שנבחרו יחד, כדי שהלקוח יוכל להשוות מחירים/שעות אמיתיים בעצמו. אם הוא מבקש קודם מסלול, אל תאשרי חיפוש טיסה עד שהמסלול קבע gateway מתאים.
- לפני שמציעים שדה תעופה כאופציה ליעד מסוים, ודאי שהוא באמת באותה מדינה שהלקוח ביקש. אם ההצעה היחידה הסבירה היא שדה במדינה שכנה (למשל זאגרב בקרואטיה עבור יעד בסלובניה), חובה לציין זאת במפורש ולתת ללקוח לבחור מדעת, ולא להציג אותו כאילו הוא בתוך היעד המבוקש.
- כשמזכירים או מסכמים שדה/שדות תעופה יעד (למשל בסיכום לפני שאלת ישירה/קונקשן), ציינו אך ורק את מה שכבר קיים בפועל ב-destination_airports או שהלקוח עצמו ציין. לעולם אל תוסיפי משדה תעופה נוסף שמוכר לך מידע כללי על העולם (למשל "גם לגוארדיה" ליד JFK עבור ניו יורק) אם הוא לא חלק מה-state או מדברי הלקוח - זו עובדה לא מאומתת שעלולה להטעות.
- אם יש ילדים בהרכב ולא ידועים הגילאים של כולם, חובה לשאול את גיל כל ילד/ה לפני סיום סשן הטיסה, כדי לסווג נכון את הנוסעים לחיפוש. אם הלקוח אמר שאין תקציב/אין הגבלת תקציב, זו תשובה מלאה לשאלת התקציב ואסור לשאול שוב תקציב לטיסה.
- ללינה, בדקי רק כשחסר ורלוונטי: סוג לינה (מלון/וילה/דירה), מספר/הרכב חדרים, רמת לינה או תקציב לאדם, מיקום ודרישות מהותיות לחיפוש.
- לרכב, בדקי רק כשחסר ורלוונטי: מספר נוסעים, מקום לכבודה, סוג/גודל רכב, נקודת וזמן איסוף והחזרה.
- לתכנון מסלול ואטרקציות, בדקי רק כשחסר ורלוונטי: אופי החופשה, קצב, מגבלות נסיעה ודברים שחייבים/לא רוצים.
- אל תשאלי שוב שום פרט שכבר נאמר בשיחה או קיים במצב החופשה המצטבר. בפרט, ניסוח כמו 'ראשון עד חמישי' כבר קובע את אורך החופשה (4 לילות/5 ימים); אסור לשאול אחר כך 'כמה ימים'.
- חשבון תאריכים הוא דטרמיניסטי: שבוע=7 ימים ושבועיים=14 ימים. אם הלקוח אמר יציאה 20.12 ושבועיים, החזרה היא 3.1; אל תמציאי 7.1 ואל תציעי תאריך חלופי אחרי שהמשך אושר.
- כשמשך החופשה הוא בקשה בקירוב ובמקביל יש אילוצי ימי שבוע (למשל יציאה בראשון וחזרה בחמישי), דרגי את טווחי התאריכים לפי המרחק המוחלט מהמשך המבוקש. האפשרות הקרובה ביותר למשך המבוקש מוצגת/מומלצת ראשונה. לדוגמה מול יעד של 14 ימים: 11 ימים עדיפים על 18 ימים כי הסטייה היא 3 לעומת 4. אל תעדיפי אוטומטית חופשה ארוכה יותר. אם נאמר גם חודש/טווח כמו 'באפריל אחרי ה-15', חשבי את התאריכים האפשריים מתוך המגבלה במקום לבקש שוב משך.
- היי סלחנית לשגיאות כתיב ברורות לפי ההקשר. אם שאלת על תקציב ונכתב למשל "ללא תקציר", אפשר להבין "ללא תקציב"; אם יש יותר מפירוש סביר אחד, שאלי הבהרה קצרה.
- בביטוי יחסי כמו "סוף יוני" יחד עם ימי שבוע/משך, אל תבחרי תאריך אחד בשם הלקוח. אם יש שתי אפשרויות סבירות סמוכות, הציגי את שתיהן ושאלי איזו עדיפה. רק אחרי בחירת הלקוח יש תאריכי יציאה וחזרה סופיים.
- כשdates.candidate_ranges במצב החופשה המצטבר כבר מכיל תאריכים (מחושבים דטרמיניסטית, לא על ידך), חובה להציג ללקוח בדיוק את התאריכים האלה, מילה במילה, ולעולם לא לחשב או לנחש תאריכים אחרים בעצמך - גם אם הם נראים לך "מתאימים יותר". אל תמציאי טווח שאינו ברשימת candidate_ranges.
- אסור להגיע לסיכום או לבקש מאשר/מאשרת כאשר dates עדיין דורש בחירה/אישור.
- לפני כל שאלה על תאריכים, מספר נוסעים, שדה מוצא, טיסה, לינה, רכב או מסלול, בדקי קודם את מצב החופשה המצטבר. אם הערך כבר קיים שם, השתמשי בו ואל תשאלי אותו שוב גם אם הוא לא מופיע בהודעות האחרונות.
- תאריכי יציאה וחזרה מדויקים שכבר קיימים ב-state הם סגורים. אסור לפתוח אותם מחדש, להציע שוב חלופות או לשאול איזו אפשרות עדיפה בעקבות תשובה על מסלול/אטרקציות/רכב/לינה או תגובה כללית כמו "נשמע אחלה". פתחי תאריכים מחדש רק אם הלקוח עצמו מבקש לשנות תאריך או מוסר תאריך/טווח חדש.
- כשחודש או תאריך יום+חודש מוזכרים בלי שנה, קבעי את השנה אוטומטית ביחס לתאריך הנוכחי: אם התאריך עדיין לפנינו השנה — השנה הנוכחית; אם הוא כבר עבר — השנה הבאה. לדוגמה, בספטמבר 2026 "28.7" פירושו 28.7.2027. אסור לשאול "באיזו שנה?" במקרה כזה. שאלי שנה רק אם הלקוח עצמו נתן מידע שסותר את החישוב או שיש יותר מפרשנות סבירה אחת.
- התאריך הנוכחי יוזרק אלייך בכל פנייה. לעולם אל תציעי, תסכמי או תאשרי תאריך שכבר עבר אלא אם הלקוח ביקש במפורש לדבר על העבר. יום+חודש ללא שנה חייב להפוך למופע העתידי הקרוב ביותר שלו. לדוגמה, כשהיום בספטמבר 2026, 28.6 פירושו 28.6.2027 ולא 2026.
- אם profile.gender הוא female/נקבה, פני ללקוחה בלשון נקבה יחידה לאורך כל השיחה. אם male/זכר, פנה בלשון זכר יחיד. אל תשתמשי בלשון רבים רק כדי להימנע מבחירת מגדר.
- אם יש profile.first_name, זהו שם הלקוח האמיתי מהרשמתו לאתר. אפשר (לא חובה) לפנות אליו בשמו הפרטי בהודעת הפתיחה של השיחה או במקום טבעי אחר, כדי שהשיחה תרגיש אישית - אבל אל תשלבי אותו בכל הודעה כאילו זו תבנית קבועה.
- זרימת הסשנים החדשה: סשן 1 הוא טיסות בלבד. השלימי את כל פרטי הטיסה, הציגי סיכום טיסה ובקשי מאשר/מאשרת בלי לשאול לפני כן על לינה, רכב או אטרקציות.
- אחרי אישור סיכום הטיסה החיפוש יוצא לסריקה. אל תמשיכי באותה נקודה לשאלות לינה/רכב/אטרקציות לפני ההפניה לסריקה.
- לאחר סריקת הטיסות, אם הלקוח חוזר לשיחה, פרטי החופשה שכבר נאספו נשמרים. שאלי תחילה האם ממשיכים עם אותה חופשה או שמדובר בחופשה חדשה.
- אם זו אותה חופשה, אל תשאלי שוב יעד, תאריכים, נוסעים או פרטי טיסה שכבר ידועים. שאלי במה ירצה/תרצה להמשיך: לינה, השכרת רכב או תכנון מסלול ואטרקציות, ואז פתחי רק את הסשן שנבחר.
- אם זו חופשה חדשה, רק אז מתחילים מחדש מסשן הטיסות ואוספים state חדש.
- סיכום הטיסה כולל רק את פרטי הטיסה והבקשה לכתוב מאשר/מאשרת. אין להוסיף בסיכום הסבר על מה יקרה לאחר האישור או על שירותים נוספים.
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
- ה-state שקיבלת הוא הזיכרון היחיד. אסור לשחזר עובדות מהודעות קודמות שאינן נמצאות בו.
- יש state מרכזי אחד לחופשה. destination, destination_airports, return_departure_airports, departure_airport, dates, travelers, budget_per_person והעדפות טיסה הם מידע משותף בין כל הסשנים. מעבר בין flights/lodging/car/trip_planning לעולם אינו מאפס אותם ולעולם אינו מצדיק לשאול אותם שוב.
- תוצר של trip_planning הוא גם מידע משותף: שמרי ב-trip_planning.details את המסלול היומי, נקודת/שדה הכניסה והיציאה שנגזרו ממנו וכל החלטה שאושרה. אם המסלול קובע שדה תעופה, עדכני גם destination_airports כדי שסשן flights יקרא אותו ישירות.
- כאשר הלקוח מבקש לעבור לשירות אחר, שאלי רק על missing_required של אותו שירות אחרי קריאת כל המידע המשותף. אל תפתחי שאלון מחדש.
- session_status כולל תמיד flights/lodging/car/trip_planning, וכל אחד הוא pending/active/complete/declined. אל תסמני complete רק כי הלקוח הזכיר את התחום; אריאלה מחשבת השלמה לפי שדות החובה.
- active_session הוא הסשן היחיד שטינקרבל משלימה כעת.
- אם הלקוח משנה פרט, החליפי רק את אותו פרט. לדוגמה: "במקום מונטנגרו יוון" מחליף destination בלבד; שינוי תאריכים מחליף dates בלבד.
- אל תמציאי ואל תנחשי. ערך חסר נשאר חסר.
- תקני סמנטית שגיאת כתיב ברורה רק כשההקשר חד-משמעי. למשל תשובה "ללא תקציר" לשאלת תקציב = budget_per_person.status="unlimited".
- budget_per_person.status חייב להישאר "unknown" עד שהלקוח מסר סכום/מגבלה או אמר במפורש שאין מגבלת תקציב. אסור להסיק unlimited משתיקה, מהיעדר סכום, או כברירת מחדל.
- כנ"ל לגבי car.details.vehicle_type: השדה נשאר ריק עד שהלקוח עצמו ציין סוג/גודל רכב (קטן, משפחתי, ג'יפ, אוטומט וכו') או אמר במפורש שכל רכב מתאים לו/שאין העדפה. לעולם אל תמלאי אותו לבד ממספר הנוסעים, מהכבודה או מברירת מחדל - זה בדיוק כמו לנחש תקציב, ומונע מהלקוח לענות על שאלה שמעולם לא נשאלה.
- trip_type מזהה את סוג הנסיעה: חופשה רגילה ("standard"), נסיעת עסקים ("business"), או חופשת סקי ("ski"), לפי מה שהלקוח אמר במפורש. השאירי null עד שהלקוח ציין זאת. אל תנחשי מ-destination/dates/travelers.
- אין לאסוף או לשמור מחלקת טיסה (תיירים/פרימיום/עסקים) גם בנסיעת עסקים. החיפוש מציג את כל אפשרויות הכרטיס הרלוונטיות והלקוח יבחר בהמשך.
- כאשר trip_type הוא ski, שמרי בשדה ski את פרטי הסקי הידועים: ski.skill_level (אחד מ-first_time/beginner/intermediate/advanced/mixed, אם נאמר), ski.priorities (רשימה מתוך snow/family/large/value/atmosphere/nightlife/spa/proximity, לפי מה שהלקוח ציין כחשוב לו), ski.transfer_choice ("90"/"180"/"any" - מרחק מקסימלי בדקות מהשדה לאתר, אם נאמר). כל שלושת השדות האלה אופציונליים ואינם תנאי לסיכום. destination_airports באתר סקי נגזר אוטומטית מהיעד ולא נשאל כשדה נפרד.
- travelers הוא מקור אמת אחד לכל החופשה. "זוג"=2 מבוגרים. "זוג עם ילדה בת 17"=2 מבוגרים, ילד/ה 1, child_ages=[17], child_genders=["female"].
- child_genders היא רשימה מקבילה ל-child_ages, לפי אותו סדר: "female" כאשר הלקוח אמר "ילדה"/"בת", "male" כאשר אמר "ילד"/"בן", ו-null כשלא צוין מגדר לאותו ילד. לעולם אל תמחקי או תנחשי ערך שכבר קיים ברשימה הזו.
- יום+חודש בלי שנה מקבל את המופע העתידי הקרוב ביותר ביחס לתאריך הנוכחי.
- requested_services ו-service_decisions נשמרים מצטבר ומשתנים רק לפי דברי הלקוח.
- הביני סמנטית אילו מארבעת השירותים הלקוח מבקש: flights/lodging/car/trip_planning. אין להסתמך על מילות קסם או ניסוח קבוע.
- הפרידי בין היעד לבין שדה התעופה של היעד. destination מתאר את היעד שהלקוח נתן; destination_airports הוא רשימת קודי IATA לנחיתה בהלוך. return_departure_airports הוא רשימת קודי IATA ליציאה בחזור. כברירת מחדל אל תשאלי על שדה החזור: אם הלקוח לא ביקש אחרת, שדה/שדות החזור זהים ל-destination_airports. אם הלקוח אומר במפורש שחוזרים משדה אחר, שמרי אותו ב-return_departure_airports.
- flight.connection_preference: כאשר הלקוח מבקש שהטיסה תהיה ישירה/ללא עצירות בלבד (בכל ניסוח - "ישירה", "רק ישירות", "ללא עצירות", "direct", "nonstop" וכו'), שמרי בשדה הזה בדיוק את המילה "direct" (אנגלית, אותיות קטנות) - לא ניסוח אחר ולא תרגום. כשאין העדפה כזו השאירי null.
- flight.baggage היא רשימה מתוך הערכים האלה בדיוק, לפי מה שהלקוח ציין: "carry_on_only" (טרולי/כבודת עלייה למטוס בלבד, ללא מזוודה למחסן - "רק טרולי" ו"טרולי בלבד" הן דוגמאות למשמעות הזו, לא ל"ללא כבודה"), "checked_bag" (יש גם מזוודה למחסן), "personal_item" (תיק קטן בלבד, אפילו לא טרולי). "none"/"no_baggage" שמורים אך ורק למקרה שהלקוח אמר במפורש שאין לו שום כבודה, כולל לא תיק - לא לניסוח כמו "טרולי בלבד" שאומר בדיוק את ההפך: יש כבודה, רק לא מזוודה.
- region הוא מידע אופציונלי בלבד. לעולם אל תוסיפי region ל-missing_required ואל תשאלי את הלקוח על אזור רק כדי להשלים state. שמרי region רק אם הלקוח עצמו ציין אזור או אם הוא נובע ממסלול שאושר.
- אם נאמרה מדינה או יעד רחב עם כמה שערי כניסה סבירים, אל תמציאי שדה יעד ואל תסמני את בחירת היעד לטיסה כמושלמת. destination_airports נשאר ריק עד שהלקוח בוחר אחד/כמה/כולם, או עד שמסלול שאושר קובע את שער הכניסה.
- כאשר הלקוח מבהיר שהוא רוצה שירות מסוים בלבד, או ששאר השירותים כבר סגורים/לא נחוצים, החזירי service_decisions מפורש לכל ארבעת התחומים: המבוקש wanted=true וכל התחומים שנשללו במשמעות המשפט wanted=false. requested_services יכיל רק את השירותים המבוקשים.
- הכלל סימטרי: "רק טיסות", "המלון והרכב כבר סגורים, צריכה טיסה", "רק מקום לינה", "הטיסות כבר הוזמנו, תמצאי מלון", "צריך רק רכב", "רק תבני לי מסלול ואטרקציות" הם דוגמאות למשמעות ולא רשימת ביטויים.
- אל תסיקי ששירותים אחרים נדחו רק מעצם אזכור שירות אחד. "אני רוצה טיסה לסופיה" לבדו מבקש flights אך אינו בהכרח שולל לינה/רכב/מסלול. שלילה של האחרים דורשת משמעות ברורה מההקשר.
- תשובה קצרה לשאלה האחרונה חייבת להתפרש לפי ההקשר שלה. אם נשאל "תרצי גם לינה?" ונענה "לא", סמני lodging wanted=false בלבד.
- search_confirmed נקבע רק על ידי מנגנון האישור בקוד, לא על ידך.
- לאחר עדכון הנתונים חשבי missing_required מה-state המלא והרלוונטי בלבד. הוא רשימת השדות שאריאלה מחזירה לטינקרבל כדי לדעת מה עדיין צריך לברר.
- אל תסמני כשדה חסר שירות שהלקוח אמר שאינו רוצה.
- ready_for_summary=true רק כאשר יש כוונת חיפוש וכל שדות החובה לשירותים המבוקשים מלאים.

החזירי JSON תקין בלבד:
{
 "trip_update":{
  "trip_type":null,
  "travelers":{"adults":null,"children":null,"child_ages":[],"child_genders":[],"infants":null,"composition":null},
  "destination":{"places":[],"mode":null,"status":"unknown"},
  "departure_airport":null,
  "dates":{"departure":null,"return":null,"period":null,"flexibility_days":null,"duration_days":null,"constraints":[]},
  "budget_per_person":{"amount":null,"currency":null,"status":"unknown"},
  "flight":{"connection_preference":null,"max_connections":null,"baggage":[],"preferences":[]},
  "priorities":[],"hard_constraints":[],"current_request":null,
  "search_intent":false,"requested_services":[],"service_decisions":{},
  "session_status":{"flights":"pending","lodging":"pending","car":"pending","trip_planning":"pending"},
  "active_session":null,
  "missing_required":[],"ready_for_summary":false,"search_confirmed":false,
  "lodging":{"interested":"unknown","details":{}},
  "car":{"interested":"unknown","details":{}},
  "trip_planning":{"interested":"unknown","details":{}},
  "ski":{"skill_level":null,"priorities":[],"transfer_choice":null}
 }
}
'''



def _current_trip_history(history, state=None):
    """Return only messages belonging to the current trip conversation boundary."""
    history = history if isinstance(history, list) else []
    state = state if isinstance(state, dict) else {}
    # After a confirmed reset the client receives a reset marker in state. If it
    # survives there, everything before the most recent restart request is stale.
    restart_phrases = ("חופשה חדשה","טיול חדש","חיפוש חדש","להתחיל מחדש","נתחיל מחדש",
                       "מהתחלה","להתחיל מהתחלה","נתחיל מהתחלה","בואי נתחיל מהתחלה","לשנות כיוון")
    boundary = -1
    for i, item in enumerate(history):
        if not isinstance(item, dict):
            continue
        txt = str(item.get("content") or "").strip().lower()
        if any(p in txt for p in restart_phrases):
            boundary = i
    if boundary >= 0:
        return history[boundary:]
    return history


def _weekday_date_conflict(message):
    """Validate every explicit Hebrew weekday/date pairing deterministically."""
    import re
    text = str(message or "")
    weekdays = {"ראשון":6,"שני":0,"שלישי":1,"רביעי":2,"חמישי":3,"שישי":4,"שבת":5}
    day_re = r"(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)"
    date_re = r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?"
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


def _post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True):
    """system_static is the large, unchanging instruction block (thousands of
    tokens, identical on every call) - marked cacheable so Claude does not
    reprocess it from scratch on every chat turn. system_dynamic is the small
    per-turn suffix (current date, accumulated trip state) that must never be
    cached since it changes every call."""
    client = _get_anthropic_client(key)
    messages = _conversation(history[-16:] if include_history else [], message)
    system_blocks = [{"type": "text", "text": system_static, "cache_control": {"type": "ephemeral"}}]
    if system_dynamic:
        system_blocks.append({"type": "text", "text": system_dynamic})
    try:
        response = client.messages.create(
            model=model, max_tokens=max_tokens, system=system_blocks, messages=messages,
            # Reply generation and state extraction are both simple, well-specified
            # tasks (natural conversation, structured JSON) - extended thinking adds
            # latency here without improving output, so keep it off for speed.
            thinking={'type': 'disabled'},
        )
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f'Claude API error {exc.status_code}') from exc
    return ''.join(block.text for block in response.content if block.type == 'text').strip()


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
        # A confirmed date choice is a replacement object, not a cumulative merge.
        # Otherwise stale candidate metadata (needs_confirmation/candidate_ranges)
        # survives beside the exact dates and makes Tinkerbell ask for dates again.
        if key == "dates" and isinstance(value, dict) and value.get("departure") and value.get("return") and value.get("needs_confirmation") is False:
            merged[key] = dict(value)
            continue
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


def _multi_gateway_hint(state):
    """When the destination matches a city genuinely served by more than one
    real airport (New York, Paris, London, Tokyo, Istanbul - see
    config.MULTI_GATEWAY_CITIES, itself built from the verified airport
    catalog) and no gateway choice has been made yet, hand Tinkerbell the
    real code/name list so it presents verified data instead of relying on
    its own recollection - the exact thing that produced an unconfirmed,
    unprompted "LaGuardia" mention (once even with a spelled-out name
    garbled into stray Cyrillic) with nothing in destination_airports to
    back it up."""
    state = state if isinstance(state, dict) else {}
    if state.get("destination_airports"):
        return None
    destination = state.get("destination") if isinstance(state.get("destination"), dict) else {}
    places = [str(p).strip() for p in (destination.get("places") or []) if str(p).strip()]
    for place in places:
        for city, options in MULTI_GATEWAY_CITIES.items():
            if city in place or place in city:
                return {"city": city, "options": options}
    return None


def _sessionize_state(state):
    """Ariella owns the four-session lifecycle; Tinkerbell only converses around it."""
    state = state if isinstance(state, dict) else {}
    statuses = state.get("session_status") if isinstance(state.get("session_status"), dict) else {}
    statuses = {s: statuses.get(s, "pending") for s in ("flights","lodging","car","trip_planning")}
    decisions = state.get("service_decisions") if isinstance(state.get("service_decisions"), dict) else {}
    services = set(state.get("requested_services") or [])

    # Explicit decisions always win.
    for s in statuses:
        d = decisions.get(s)
        wanted = d.get("wanted") if isinstance(d, dict) else d
        if wanted is False:
            statuses[s] = "declined"
        elif wanted is True:
            services.add(s)
            if statuses[s] in ("pending", "declined"):
                statuses[s] = "active"

    # A destination/trip request implies flights unless explicitly declined.
    dest = state.get("destination") if isinstance(state.get("destination"), dict) else {}
    fd = decisions.get("flights")
    fw = fd.get("wanted") if isinstance(fd, dict) else fd
    if dest.get("places") and fw is not False:
        services.add("flights")
        if statuses["flights"] == "pending":
            statuses["flights"] = "active"

    # A business trip or a single-resort ski trip has no natural use for
    # day-by-day multi-city itinerary/attraction planning. Default
    # trip_planning to declined unless the customer explicitly asked for it
    # (an explicit decision above already won).
    _trip_type = str(state.get("trip_type") or "").lower()
    if _trip_type in ("business", "ski") and decisions.get("trip_planning") is None and statuses["trip_planning"] == "pending":
        statuses["trip_planning"] = "declined"
        decisions = dict(decisions)
        decisions["trip_planning"] = {"wanted": False, "source": f"{_trip_type}_trip_default"}

    # Keep one active session. Respect an existing unfinished active session first.
    active = state.get("active_session")
    if active not in statuses or statuses.get(active) in ("complete","declined"):
        active = None
    if not active:
        # "flights" is the domain most likely to get auto-marked active purely
        # from a destination being known (see the block above), so it must not
        # win this tie-break over a session the customer explicitly chose.
        active = next((s for s in ("trip_planning","lodging","car","flights") if statuses[s] == "active"), None)

    state["requested_services"] = list(dict.fromkeys(list(state.get("requested_services") or []) + list(services)))
    state["session_status"] = statuses
    state["service_decisions"] = decisions
    state["active_session"] = active
    return state


def _session_gaps(state, session):
    """Required facts for one session only."""
    all_gaps = _required_state_gaps(state)
    prefixes = {
        # trip_type only gates the flights session (it affects date-flex/cabin
        # behavior there). Requiring it for every session risks permanently
        # stalling lodging/car/trip_planning if the opening question was ever
        # skipped, since none of those sessions have a natural place to ask it.
        "flights": ("trip_type","destination","dates","travelers","departure_airport","flight.","budget_per_person"),
        "lodging": ("destination","dates","travelers","lodging."),
        "car": ("destination","dates","travelers","car."),
        "trip_planning": ("destination","dates","travelers","trip_planning."),
    }
    allowed = prefixes.get(session, ())
    return [g for g in all_gaps if any(g == p or g.startswith(p) for p in allowed)]


def _advance_sessions(state):
    """Complete the active session when full, then expose exactly one next session decision."""
    state = _sessionize_state(state)
    statuses = dict(state.get("session_status") or {})
    active = state.get("active_session")

    if active and not _session_gaps(state, active):
        statuses[active] = "complete"
        active = None

    # Never auto-activate a new domain merely because it is pending. The next
    # pending domain becomes a yes/no decision for Tinkerbell.
    next_pending = next((s for s in ("flights","lodging","car","trip_planning") if statuses.get(s) == "pending"), None)
    if not active:
        active = next((s for s in ("flights","lodging","car","trip_planning") if statuses.get(s) == "active"), None)

    state["session_status"] = statuses
    state["active_session"] = active
    if active:
        state["missing_required"] = _session_gaps(state, active)
        state["next_session"] = None
        state["ready_for_summary"] = False
    elif next_pending:
        state["missing_required"] = []
        state["next_session"] = next_pending
        state["ready_for_summary"] = False
    else:
        state["missing_required"] = []
        state["next_session"] = None
        state["ready_for_summary"] = all(v in ("complete","declined") for v in statuses.values())
    # Session 1 is intentionally self-contained. Once flights are complete, the
    # flight search may be summarized/approved without forcing decisions about
    # lodging, car or trip planning. Those sessions reopen after flight handoff.
    # next_session must be cleared here too: the elif branch above may have
    # already set it to the next pending domain (e.g. lodging) before this
    # flights-complete check ran, leaving both ready_for_summary=True and
    # next_session="lodging" set at once - a genuinely contradictory signal
    # that let Tinkerbell sometimes jump straight to the next domain's
    # question instead of presenting the flight summary and asking for
    # "מאשר/מאשרת" first, skipping the hard approval gate entirely.
    # This must only apply BEFORE that approval gate - once the flight was
    # actually approved and searched (post_flight_continuation=True), the gate
    # has already done its job. Without excluding that case, this block kept
    # firing forever afterward on every later turn too (flights stays
    # "complete" for the rest of the conversation), so once trip_planning also
    # completed post-approval it forced next_session back to None and
    # ready_for_summary back to True even though lodging/car were still
    # genuinely "pending" - seen live: Ariella silently treated the whole
    # vacation as finished instead of ever asking about lodging or car.
    if statuses.get("flights") == "complete" and state.get("active_session") is None and not state.get("post_flight_continuation"):
        state["missing_required"] = []
        state["ready_for_summary"] = True
        state["next_session"] = None
    return state


def _direct_route_available(state):
    """True when the requested destination has a known nonstop route from the selected Israeli origin."""
    state = state if isinstance(state, dict) else {}
    destination = state.get("destination") if isinstance(state.get("destination"), dict) else {}
    places = destination.get("places") if isinstance(destination.get("places"), list) else []
    if not places:
        return False
    origin = str(state.get("departure_airport") or "TLV").strip().upper()
    aliases = {
        "תאילנד":["BKK","HKT"], "thailand":["BKK","HKT"],
        "בנגקוק":["BKK"], "bangkok":["BKK"], "פוקט":["HKT"], "phuket":["HKT"],
    }
    codes = []
    for place in places:
        raw = str(place or "").strip()
        upper = raw.upper()
        if len(upper) == 3 and upper.isalpha():
            codes.append(upper)
        codes.extend(aliases.get(raw.lower(), aliases.get(raw, [])))
    if not codes:
        return False
    dates = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    departure = str(dates.get("departure") or "")[:10]
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        marks = ",".join("?" for _ in codes)
        sql = f"""SELECT 1 FROM direct_routes
                  WHERE origin_code=? AND destination_code IN ({marks}) AND status='active'
                    AND (valid_from IS NULL OR valid_from='' OR ?='' OR valid_from<=?)
                    AND (valid_to IS NULL OR valid_to='' OR ?='' OR valid_to>=?)
                  LIMIT 1"""
        row = conn.execute(sql, [origin, *codes, departure, departure, departure, departure]).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def _resolve_destination_airports_from_route(state):
    """Deterministic safety net: once trip planning has confirmed a day-by-day
    route, derive the flight gateway from it (or from a plain destination name)
    the same way the scanner resolves free-text places to IATA codes, instead
    of relying on the extractor to remember to copy it over every turn. Without
    this, returning to the flight session after route planning can re-ask a
    question the route itself already answered."""
    state = state if isinstance(state, dict) else {}
    if state.get("destination_airports"):
        return state
    # A ski trip's gateway airports come only from the ski resort catalog
    # (see _resolve_ski_destination_airports) - the general airport catalog
    # would happily match a country to its capital's airport, which is
    # usually the wrong gateway for skiing (e.g. Vienna for Austria, instead
    # of Innsbruck/Salzburg/Munich).
    if str(state.get("trip_type") or "").lower() == "ski":
        return state
    planning = state.get("trip_planning") if isinstance(state.get("trip_planning"), dict) else {}
    details = planning.get("details") if isinstance(planning.get("details"), dict) else {}
    route = details.get("route") if isinstance(details.get("route"), list) else []
    names = []
    for day in route:
        if isinstance(day, dict):
            base = day.get("base") or day.get("city") or day.get("region")
            if base:
                names.append(str(base))
    if not names:
        destination = state.get("destination") if isinstance(state.get("destination"), dict) else {}
        names = [str(p) for p in (destination.get("places") or []) if p]
    if not names:
        return state
    airports = _load_airports()
    codes = []
    for name in names:
        needle = str(name).strip().lower()
        if not needle:
            continue
        for airport in airports:
            hay = " ".join(str(airport.get(k) or "") for k in ("country_he", "country_en", "city_he", "city_en")).lower()
            if hay and (needle in hay or hay in needle):
                code = str(airport.get("code") or "").upper()
                if code and code not in codes:
                    codes.append(code)
    if not codes:
        return state
    state = dict(state)
    state["destination_airports"] = codes[:4]
    return state


def _resolve_ski_destination_airports(state):
    """Ski gateway airports come from the ski resort catalog, not the general
    airport catalog: matching a country/resort name against SKI_RESORTS and
    deriving destination_airports from the matched resorts' own gateway
    airports (e.g. Austria -> INN/ZRH/MUC/SZG, not Vienna). Also records
    which resorts matched, needed later so the search/scoring layer can
    match offers back to a specific resort."""
    state = state if isinstance(state, dict) else {}
    if str(state.get("trip_type") or "").lower() != "ski":
        return state
    if state.get("destination_airports"):
        return state
    destination = state.get("destination") if isinstance(state.get("destination"), dict) else {}
    places = [str(p) for p in (destination.get("places") or []) if str(p).strip()]
    if not places:
        return state
    matched_rows = []
    for place in places:
        needle = place.strip().lower()
        if not needle:
            continue
        for row in SKI_RESORTS:
            hay = " ".join(str(row.get(k) or "") for k in ("country", "country_he", "resort")).lower()
            if needle in hay or hay in needle:
                matched_rows.append(row)
    if not matched_rows:
        return state
    resort_names = []
    codes = []
    for row in matched_rows:
        name = str(row.get("resort") or "")
        if name and name not in resort_names:
            resort_names.append(name)
        for code in (row.get("gateway_airports") or []):
            code = str(code).upper()
            if code and code not in codes:
                codes.append(code)
    if not codes:
        return state
    state = dict(state)
    state["destination_airports"] = codes[:6]
    ski_state = dict(state.get("ski") or {})
    ski_state["resort_names"] = resort_names
    state["ski"] = ski_state
    return state


def _required_state_gaps(state):
    """Return the authoritative unanswered decisions Ariella needs for requested services."""
    state = state if isinstance(state, dict) else {}
    services = set(state.get("requested_services") or [])
    decisions = state.get("service_decisions") if isinstance(state.get("service_decisions"), dict) else {}
    for service in ("flights", "lodging", "car", "trip_planning"):
        decision = decisions.get(service)
        wanted = decision.get("wanted") if isinstance(decision, dict) else decision
        if wanted is True:
            services.add(service)

    gaps = []
    destination = state.get("destination") if isinstance(state.get("destination"), dict) else {}
    dates = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    travelers = state.get("travelers") if isinstance(state.get("travelers"), dict) else {}
    flight = state.get("flight") if isinstance(state.get("flight"), dict) else {}
    lodging = state.get("lodging") if isinstance(state.get("lodging"), dict) else {}
    car = state.get("car") if isinstance(state.get("car"), dict) else {}
    planning = state.get("trip_planning") if isinstance(state.get("trip_planning"), dict) else {}
    lodging_details = lodging.get("details") if isinstance(lodging.get("details"), dict) else {}
    car_details = car.get("details") if isinstance(car.get("details"), dict) else {}
    planning_details = planning.get("details") if isinstance(planning.get("details"), dict) else {}

    # Shared trip facts.
    if services and not state.get("trip_type"):
        gaps.append("trip_type")
    if services and not (destination.get("places") or []):
        gaps.append("destination")
    if services and (dates.get("needs_confirmation") or not (dates.get("departure") and dates.get("return"))):
        gaps.append("dates")
    if services and travelers.get("adults") is None:
        gaps.append("travelers")
    children_count = int(travelers.get("children") or 0)
    child_ages = travelers.get("child_ages") if isinstance(travelers.get("child_ages"), list) else []
    if services and children_count > 0 and len(child_ages) < children_count:
        gaps.append("travelers.child_ages")

    # First establish whether each of the four domains is wanted. A trip request
    # with a destination implies flights unless the user explicitly says flights
    # are already booked/not needed.
    for service in ("flights", "lodging", "car", "trip_planning"):
        decision = decisions.get(service)
        explicit = decision.get("wanted") if isinstance(decision, dict) else decision
        if service not in services and explicit is None:
            gaps.append("service_decisions." + service)

    if "flights" in services:
        if not state.get("departure_airport"):
            gaps.append("departure_airport")
        # Country/region and flight gateway are separate facts. Broad geographic
        # requests must not silently resolve to an arbitrary airport.
        destination_airports = state.get("destination_airports") if isinstance(state.get("destination_airports"), list) else []
        destination_mode = str(destination.get("mode") or "").lower()
        # A ski gateway always needs the catalog resolution regardless of
        # how specific the stated destination is (even a named resort still
        # needs its gateway airports derived from the ski catalog).
        is_ski_trip = str(state.get("trip_type") or "").lower() == "ski"
        if (is_ski_trip or destination_mode in {"country","region","area","broad"}) and not destination_airports:
            gaps.append("destination_airports")
        # Return gateway defaults to the outbound arrival gateway. It is only a
        # separate required fact when the customer explicitly asks for open-jaw.
        return_airports = state.get("return_departure_airports") if isinstance(state.get("return_departure_airports"), list) else []
        if state.get("open_jaw_requested") and not return_airports:
            gaps.append("return_departure_airports")
        # Ask direct-vs-connection only when a verified nonstop route exists
        # for this origin/destination/date. Otherwise connections are simply ranked results.
        if _direct_route_available(state) and not flight.get("connection_preference"):
            gaps.append("flight.connection_preference")
        if not flight.get("baggage"):
            gaps.append("flight.baggage")
        budget = state.get("budget_per_person") if isinstance(state.get("budget_per_person"), dict) else {}
        if budget.get("amount") is None and budget.get("status") not in ("unlimited","none","no_limit"):
            gaps.append("budget_per_person")

    if "lodging" in services:
        if not lodging_details.get("type"):
            gaps.append("lodging.details.type")
        if not (lodging_details.get("bedrooms") or lodging_details.get("rooms")):
            gaps.append("lodging.details.rooms")
        if not (lodging_details.get("areas") or lodging_details.get("locations")):
            gaps.append("lodging.details.locations")
        if not (lodging_details.get("budget") or lodging_details.get("level")):
            gaps.append("lodging.details.budget_or_level")

    if "car" in services:
        if not (car_details.get("vehicle_type") or car_details.get("size")):
            gaps.append("car.details.vehicle_type")
        if not car_details.get("pickup"):
            gaps.append("car.details.pickup")
        if not car_details.get("return"):
            gaps.append("car.details.return")
        # luggage capacity derives from the shared traveler + baggage facts; do
        # not invent suitcases that the user never requested.
        if not car_details.get("luggage_capacity_confirmed"):
            gaps.append("car.details.luggage_capacity")

    if "trip_planning" in services:
        if not (planning_details.get("style") or planning_details.get("interests")):
            gaps.append("trip_planning.details.style")
        if not planning_details.get("pace"):
            gaps.append("trip_planning.details.pace")
        if not (planning_details.get("route") or planning_details.get("daily_plan")):
            gaps.append("trip_planning.details.route")

    return list(dict.fromkeys(gaps))


def _flight_gap_question(gaps):
    """Map a _session_gaps(..., "flights") result to the one specific
    question that actually resolves it. Shared by the approval-time gap
    handling and the false-approval-claim safety net below, so both ask the
    same real, concrete question instead of a generic "something is
    missing" line the customer has no way to act on."""
    gaps = gaps or []
    if "destination_airports" in gaps:
        return "לפני שאצא לסריקה צריך להשלים את שדה היעד לנחיתה בהלוך. באיזה שדה תרצי לנחות?"
    if "return_departure_airports" in gaps:
        return "ציינת שתרצי לחזור משדה אחר. מאיזה שדה תרצי לצאת בחזור?"
    if "budget_per_person" in gaps:
        return "לפני הסריקה חסר לי התקציב לאדם. מה התקציב, או שאין מגבלת תקציב?"
    if "departure_airport" in gaps:
        return "לפני הסריקה חסר לי שדה היציאה שלכם. מאיזה שדה תרצי לטוס?"
    if "trip_type" in gaps:
        return "רק לפני שממשיכים - זו חופשה רגילה, נסיעת עסקים, או חופשת סקי?"
    if "destination" in gaps:
        return "לפני הסריקה חסר לי היעד. לאן תרצי לטוס?"
    if "dates" in gaps:
        return "לפני הסריקה חסרים לי תאריכי הטיסה המדויקים. מתי תרצי לצאת ולחזור?"
    if "travelers" in gaps:
        return "לפני הסריקה חסר לי הרכב הנוסעים. כמה נוסעים, ומי מבוגר ומי ילד?"
    if "travelers.child_ages" in gaps:
        return "חסר לי הגיל של הילד/ה בהרכב הנוסעים. מה הגיל?"
    if "flight.connection_preference" in gaps:
        return "חשוב לך שהטיסה תהיה ישירה, או שקונקשן בסדר?"
    if "flight.baggage" in gaps:
        return "לפני הסריקה חסר לי פרטי הכבודה - טרולי בלבד, גם מזוודה למחסן, או רק תיק?"
    missing_service = next((g.split(".",1)[1] for g in gaps if g.startswith("service_decisions.")), None)
    if missing_service:
        labels = {"lodging":"גם לינה","car":"גם רכב שכור","trip_planning":"גם תכנון מסלול ואטרקציות"}
        return f"רק לפני שממשיכים - תרצי {labels.get(missing_service, missing_service)} לחופשה הזו?"
    if gaps:
        return "לפני שאצא לסריקה חסר עוד פרט אחד בבקשת הטיסה. נשלים אותו ואז אציג שוב סיכום לאישור."
    return None


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


def _normalize_confirm(message):
    """Strip trailing punctuation ("מעולה!", "מצוין..") before matching a
    short confirmation against an exact-phrase set, so an ordinary exclamation
    mark doesn't make an unambiguous "yes" invisible to a deterministic gate."""
    return str(message or "").strip().rstrip("!.,?;:״\"'׳ ").strip()

def _user_gender_from_approval(message, state):
    msg = str(message or "").strip().lower()
    if msg == "מאשרת":
        return "female"
    if msg == "מאשר":
        return "male"
    return (state or {}).get("user_gender")


def _approval_trigger(message, history, state):
    """Exact approval executes after the flight summary was visibly presented.
    Do not depend on a stale ready_for_summary flag from the previous HTTP turn.
    """
    msg = str(message or "").strip().lower()
    if msg not in {"מאשר", "מאשרת"}:
        return False
    state = state if isinstance(state, dict) else {}
    if state.get("ready_for_summary"):
        return True
    # The visible assistant summary is authoritative evidence that we reached
    # the approval gate; this survives state normalization between turns.
    recent = [x for x in (history or []) if isinstance(x, dict)][-4:]
    assistant_text = " ".join(
        str(x.get("content") or "") for x in recent
        if str(x.get("role") or "").lower() == "assistant"
    )
    return ("כתבי מאשרת" in assistant_text
            or "כתוב מאשר" in assistant_text
            or "מאשר/מאשרת" in assistant_text)

def _looks_like_approval_typo(message, state=None):
    """Near-approval text may be clarified, but can never execute a search."""
    import difflib
    msg = str(message or "").strip().lower()
    if not msg or msg in {"מאשר", "מאשרת"}:
        return False
    state = state if isinstance(state, dict) else {}
    # Only interpret a near-match as an approval typo when the conversation is
    # actually at the final summary/approval stage.
    if not state.get("ready_for_summary"):
        return False
    compact = "".join(ch for ch in msg if ch.isalpha())
    if not compact or len(compact) > 8:
        return False
    return max(difflib.SequenceMatcher(None, compact, target).ratio()
               for target in ("מאשר", "מאשרת")) >= 0.72


def _interpret_pending_choice(key, model, history, message, question_kind):
    """Interpret free-form customer answers to a pending conversational choice."""
    if not key:
        return "unclear"
    prompt = """את מסווגת כוונת לקוח מתוך הקשר השיחה. הלקוח רשאי לענות בכל ניסוח טבעי וגם עם שגיאות כתיב.
החזירי מילה אחת בלבד.
כאשר question_kind=new_vacation:
NEW = הלקוח רוצה להתחיל חופשה חדשה ולוותר על פרטי החופשה הקודמת.
KEEP = הלקוח רוצה להישאר בחופשה הקיימת או רק לשנות בה פרט.
UNCLEAR = אי אפשר להבין בבטחה.
הביני משמעות והקשר; אל תדרשי מילת קסם ואל תסתמכי על התאמת מחרוזת."""
    try:
        raw = _post_claude(
            key, model, prompt, "", history if isinstance(history, list) else [],
            "question_kind=" + str(question_kind) + "\nתשובת הלקוח: " + str(message or ""),
            20, include_history=True
        ).strip().upper()
        if raw.startswith("NEW"):
            return "new"
        if raw.startswith("KEEP"):
            return "keep"
    except Exception:
        pass
    return "unclear"


def _fix_known_typos(text):
    """Deterministic safety net for a recurring model typo: dropping the
    leading נ from the נתב"ג (Ben Gurion airport) acronym, or reversing its
    two middle letters. Same philosophy as the deterministic fact-extraction
    helpers elsewhere in this file - do not trust free-form model text for
    something that has exactly one correct spelling."""
    import re
    text = str(text or "")
    text = re.sub(r'(?<!נ)תב["״]ג', 'נתב"ג', text)
    text = re.sub(r'(?<!נ)בת["״]ג', 'נתב"ג', text)
    return text


def _strip_garbled_lead_token(text):
    """Deterministic safety net for a recurring model glitch, seen live on
    the phone more than once: an occasional garbled token that mixes Hebrew
    and Latin letters within the same run of characters (e.g. "סדחFOSX")
    injected as the very first word of an otherwise normal Hebrew reply. A
    legitimate word never mixes scripts letter-by-letter like that - real
    English terms inside a Hebrew reply always appear as their own separate,
    single-script word (an airport code in parentheses, "COVID", etc.), so
    any leading token containing both scripts together is never real content
    and can be dropped outright, along with the stray comma/dash left after
    it."""
    import re
    text = str(text or "")
    m = re.match(r'^\S*[֐-׿]\S*[A-Za-z]\S*|^\S*[A-Za-z]\S*[֐-׿]\S*', text)
    if m and m.group(0):
        rest = text[m.end():].lstrip()
        rest = re.sub(r'^[,:\-–]\s*', '', rest)
        if rest:
            return rest
    return text


def _fix_child_gender_wording(text, state):
    """Deterministic safety net, same philosophy as the two helpers above: a
    prompt instruction alone did not reliably stop the model from inventing a
    child's gender when it writes them into a summary - seen live, a customer-
    stated "ילדה בת 17" turned into "ונער בן 17" in Tinkerbell's own generated
    trip summary. travelers.child_genders (set deterministically in
    _deterministic_traveler_facts from the customer's own "ילדה בת"/"ילד בן"
    wording) is the one place this fact is actually recorded, so correct any
    mismatch against it after the fact rather than trust free text to get it
    right."""
    state = state if isinstance(state, dict) else {}
    travelers = state.get("travelers") if isinstance(state.get("travelers"), dict) else {}
    ages = travelers.get("child_ages") if isinstance(travelers.get("child_ages"), list) else []
    genders = travelers.get("child_genders") if isinstance(travelers.get("child_genders"), list) else []
    if not ages or not genders:
        return text
    import re
    text = str(text or "")
    to_fem = {"ילד": "ילדה", "נער": "נערה"}
    to_masc = {"ילדה": "ילד", "נערה": "נער"}
    for age, gender in zip(ages, genders):
        if gender not in ("male", "female"):
            continue
        try:
            age_int = int(age)
        except (TypeError, ValueError):
            continue
        pattern = re.compile(r"(ילד|ילדה|נער|נערה)(\s+)(בן|בת)(\s*%d\b)" % age_int)

        def _fix(m, wants_fem=(gender == "female")):
            noun, sep, particle, tail = m.group(1), m.group(2), m.group(3), m.group(4)
            if noun.endswith("ה") == wants_fem:
                return m.group(0)
            noun = (to_fem if wants_fem else to_masc).get(noun, noun)
            particle = "בת" if wants_fem else "בן"
            return noun + sep + particle + tail

        text = pattern.sub(_fix, text)
    return text


def _strip_unconfirmed_airports(text, state):
    """Deterministic safety net for a second recurring model behavior: even
    after an explicit prompt instruction not to, Tinkerbell keeps
    volunteering LaGuardia (LGA) as an extra New York gateway alongside JFK
    from its own general world knowledge - nothing in destination_airports
    ever actually named it. The prompt fix alone did not reliably hold, so
    strip it here regardless of what the model produced. Seen twice now: a
    brief inline mention ("JFK או לגה"), and a full elaborated paragraph
    building on the invented second airport (explaining it exists, asking
    which one/both to search, even once with a stray Cyrillic word mixed
    into the airport's spelled-out name) - the two need different handling,
    since deleting a few words out of a paragraph built around the premise
    leaves an incoherent sentence behind, but deleting an entire paragraph
    for a brief inline mention would delete real content too."""
    state = state if isinstance(state, dict) else {}
    airports = state.get("destination_airports") if isinstance(state.get("destination_airports"), list) else []
    if any(str(a or "").strip().upper() == "LGA" for a in airports):
        return text
    # A New York destination genuinely offers LGA as a verified multi-gateway
    # option (see config.MULTI_GATEWAY_CITIES / _multi_gateway_hint) - in
    # that case Tinkerbell is meant to ask about it, using the exact
    # verified list it was handed, so this is not the unconfirmed-invention
    # case this function guards against.
    gateway_hint = _multi_gateway_hint(state)
    if gateway_hint and any(o.get("code") == "LGA" for o in gateway_hint.get("options", [])):
        return text
    import re
    text = str(text or "")
    forbidden = re.compile(r'לה\s*גוארדיה|לגה\s*גוארדיה|\bלגה\b|LaGuardia|\bLGA\b', re.IGNORECASE)
    if not forbidden.search(text):
        return text
    # Paragraph-level removal first (Tinkerbell's own structure is one topic
    # per blank-line-separated paragraph): drop any paragraph that mentions
    # it at all, as long as other paragraphs remain to keep the reply from
    # going empty.
    paragraphs = re.split(r'(\n\s*\n)', text)
    blocks = paragraphs[0::2]
    separators = paragraphs[1::2]
    kept_blocks, kept_seps = [], []
    for i, block in enumerate(blocks):
        if not forbidden.search(block):
            kept_blocks.append(block)
            if i < len(separators):
                kept_seps.append(separators[i])
    if kept_blocks and len(kept_blocks) < len(blocks):
        result = kept_blocks[0]
        for sep, block in zip(kept_seps, kept_blocks[1:]):
            result += sep + block
        return result.strip()
    # Single-paragraph (or every paragraph tainted) case: surgical phrase
    # removal instead, including the Hebrew ו- prefix glued directly onto
    # the next word ("ולה גוארדיה") and parenthesized codes ("(LGA)"),
    # followed by a cleanup pass for the connector/punctuation debris left
    # behind (a dangling "ו"/"או", empty "()", doubled spaces or commas).
    text = re.sub(r'\s*[/,]?\s*(?:ו|או)?\s*(?:לה|לגה)\s*גו?ארדיה', '', text)
    text = re.sub(r'\s*[/,]?\s*(?:ו|או)?\s*\bלגה\b', '', text)
    text = re.sub(r'\s*[/,]?\s*(?:or\s+)?LaGuardia\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*[/,]?\s*(?:or\s+)?\(?\s*\bLGA\b\s*\)?', '', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'(?:^|\s)(?:ו|או)(?=[\s.,?!]|$)', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\s+([.,?!])', r'\1', text)
    return text.strip()


def _call_tinkerbell(key, model, history, message, state=None):
    state = state if isinstance(state, dict) else {}
    statuses = state.get("session_status") if isinstance(state.get("session_status"), dict) else {}
    active_session = state.get("active_session")
    trip_planning_settled = statuses.get("trip_planning") in ("complete", "declined")
    other_session_pending = active_session and active_session != "trip_planning"
    if not other_session_pending:
        other_session_pending = any(
            statuses.get(s) not in ("complete", "declined")
            for s in ("flights", "lodging", "car")
        )

    if trip_planning_settled and other_session_pending:
        route_handoff = """
- הלקוח זה עתה אישר את המסלול/האטרקציות המוצעים, אבל יש עוד תחום/ים בחופשה (טיסות/לינה/רכב) שטרם טופלו. אל תסיימי את השיחה, אל תאמרי "מאחלת חופשה נעימה" ואל תבטיחי שליחת מידע לכרטיסייה עדיין.
- אם המסלול קבע שדה/שדות כניסה ליעד, הם כבר נשמרו ב-destination_airports; אל תשאלי עליהם שוב, רק אשרי אותם בקצרה במידת הצורך. המשיכי כעת ישירות לתחום הפתוח: אם active_session מוגדר, השלימי את missing_required שלו; אם אין active_session, זהו סשן pending הבא ושאלי עליו שאלה בינארית טבעית כרגיל.
- ברגע שהתחום הפתוח הזה מלא, נהגי לפי כללי הסיכום הרגילים שלו (למשל עבור טיסות: סיכום קצר ובקשת מאשר/מאשרת), ולא לפי נוסח הסיום של תכנון המסלול.
"""
    else:
        route_handoff = """
- כאשר הצעת מסלול/אטרקציות והלקוח מאשר אותו במפורש או אומר שהוא מתאים, ואין עוד סשן פתוח שממתין להשלמה (כלומר טיסות/לינה/רכב כבר complete או declined), אל תשאלי אם לאשר שוב ואל תציעי לעבור ללינה. סיימי בדיוק בנוסח: "מצוין. אני אשלח לך את כל האינפורמציה לכרטיסיית האטרקציות בכרטיס החופשה שלך. מאחלת לך חופשה נעימה ולכל שאלה נוספת אני תמיד כאן."
"""
    continuity = """
כללי שיחה מחייבים לאחר סריקת הטיסות:
- אם קיימת חופשה פעילה והלקוח ממשיך לדבר עליה, זו אותה חופשה כברירת מחדל. אל תשאלי שוב "אותה חופשה או חופשה חדשה" אלא אם הלקוח עצמו מבקש חופשה חדשה או שיש סתירה אמיתית.
- אם active_session הוא trip_planning, הישארי בתכנון המסלול. אל תעברי מיוזמתך ללינה, רכב או טיסות ואל תשאלי שאלות על תחום אחר.
- דברי כשיחה טבעית ולא כטופס. השתמשי בפרטים שכבר ידועים, הגיבי למה שהלקוח אמר ורק אז שאלי את השאלה הבאה הנחוצה.
""" + route_handoff
    gateway_hint = _multi_gateway_hint(state)
    gateway_hint_text = ""
    if gateway_hint:
        options_text = ", ".join(f"{o['name_he']} ({o['code']})" for o in gateway_hint["options"])
        gateway_hint_text = (
            f'\nהיעד "{gateway_hint["city"]}" מתאים ליותר משדה תעופה אמיתי אחד: {options_text}. '
            'אלה שדות מאומתים - אל תוסיפי או תמציאי שדה אחר משלך. אם destination_airports עדיין ריק, '
            'שאלי את הלקוח בשאלה אחת האם לחפש בכולם יחד, רק בשדה מסוים, או בכמה מהם - והשתמשי אך ורק ברשימה הזו.'
        )
    system_dynamic = continuity + '\nהתאריך הנוכחי: ' + date.today().isoformat() + '\nמצב החופשה המצטבר שכבר ידוע:\n' + _state_context(state) + gateway_hint_text
    reply = _post_claude(key, model, TINKERBELL_SYSTEM, system_dynamic, history, message, 1500, include_history=True).strip()
    reply = _fix_known_typos(reply)
    reply = _strip_garbled_lead_token(reply)
    return _strip_unconfirmed_airports(reply, state)


def _extract_trip_update(key, model, history, message, state=None):
    try:
        gateway_hint = _multi_gateway_hint(state)
        gateway_hint_text = ""
        if gateway_hint:
            options_text = ", ".join(f"{o['name_he']} ({o['code']})" for o in gateway_hint["options"])
            gateway_hint_text = (
                f'\nאם הלקוח כרגע עונה לגבי בחירת שדה תעופה עבור "{gateway_hint["city"]}", השדות האמיתיים היחידים '
                f'הם: {options_text}. כתבי ב-destination_airports אך ורק קודי IATA מהרשימה הזו לפי מה שהלקוח בחר '
                '(אחד, כמה, או כולם) - לעולם לא קוד אחר.'
            )
        system_dynamic = '\nמצב החופשה המצטבר לפני ההודעה הנוכחית:\n' + _state_context(state) + '\nהתאריך הנוכחי: ' + date.today().isoformat() + gateway_hint_text
        # Short replies ("כן", "נכון", "זוג") need the immediately preceding
        # question to be interpreted correctly. Keep only a tiny recent window to
        # preserve semantics without paying the latency of the entire conversation.
        recent = (history or [])[-4:]
        raw = _post_claude(key, model, EXTRACTOR_SYSTEM, system_dynamic, recent, message, 700, include_history=True)
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
        "מלטה": "מלטה", "malta": "Malta",
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
    parts = [str(x.get("content") or "") for x in (history or []) if isinstance(x, dict)]
    parts.append(str(message or ""))
    text = " ".join(parts)
    found = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)", text):
        try:
            found.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        except ValueError:
            pass
    for m in re.finditer(r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)", text):
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

def _deterministic_duration_facts(message, state=None):
    """If a departure date is known and customer gives a duration, calculate return deterministically."""
    import re
    state = state if isinstance(state, dict) else {}
    dates = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    dep_raw = str(dates.get("departure") or "")[:10]
    if not dep_raw:
        return {}
    msg = str(message or "").strip().lower()
    hebrew_durations = {
        "שבועיים": (2, "שבועות"),
        "שבוע": (1, "שבועות"),
    }
    matched = next((value for phrase, value in hebrew_durations.items() if phrase in msg), None)
    if matched:
        n, unit = matched
    else:
        m = re.search(r"(\d+)\s*(שבוע|שבועות|ימים|יום|לילות|לילה)", msg)
        if not m:
            return {}
        n = int(m.group(1))
        unit = m.group(2)
    if n <= 0:
        return {}
    try:
        dep = date.fromisoformat(dep_raw)
    except ValueError:
        return {}
    if unit in ("שבוע","שבועות"):
        # "שבועיים" is commonly written without a numeral; handled below.
        delta_days = n * 7
    elif unit in ("לילות","לילה"):
        delta_days = n
    else:
        delta_days = max(0, n - 1)
    ret = dep + timedelta(days=delta_days)
    duration_days = (ret - dep).days + 1
    return {"dates":{"departure":dep.isoformat(),"return":ret.isoformat(),
        "period":f"{dep.strftime('%d.%m.%Y')}–{ret.strftime('%d.%m.%Y')}",
        "duration_days":duration_days,
        "needs_confirmation":False,"candidate_ranges":[]}}

def _accept_assistant_single_date_proposal(history, message, state=None):
    """Commit one concrete range proposed in Ariella's immediately previous reply when customer continues without changing dates."""
    import re
    state = state if isinstance(state, dict) else {}
    current = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    if current.get("departure") and current.get("return"):
        return {}
    # Only while dates are actually the thing being discussed (the flights
    # session). Two dd.mm.yyyy-looking numbers can show up in an itinerary/
    # route reply for an unrelated reason (a local festival's dates, a
    # recommended season window, etc.) - seen live: a trip-planning
    # conversation mentioned two such dates, the customer's next reply was an
    # ordinary continuation with no rejection wording, and this function
    # silently adopted them as the confirmed flight departure/return dates
    # the customer had never actually been asked about or given.
    if str(state.get("active_session") or "") == "trip_planning":
        return {}
    msg = str(message or "").strip().lower()
    # Explicit correction/rejection/date text means let the normal parsers handle it.
    # "תשני" ("change [it]") is deliberately NOT treated as a rejection here:
    # a live transcript showed "מצוין. תשני רק את תאריך החזרה" ("great, change
    # only the return date") - the customer AGREEING with Ariella's own just-
    # proposed date and asking for a specific follow-up - get bailed out on as
    # if the date itself had been rejected, leaving a stale, never-actually-
    # confirmed date silently stuck in state. A genuinely different new date
    # still overrides this correctly via the dedicated date-fact parsers that
    # run after this one, so dropping this one keyword is safe either way.
    if any(x in msg for x in ("לא", "במקום", "אחר", "לא מתאים")) or re.search(r"\d{1,2}[./-]\d{1,2}", msg):
        return {}
    assistant_text = ""
    for item in reversed(history or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").lower()
        if role in ("assistant","ariella","tinkerbell"):
            assistant_text = str(item.get("content") or "")
            break
    if not assistant_text:
        return {}
    # Belt-and-suspenders alongside the trip_planning exclusion above: even
    # inside the flights session, two dates appearing in the text is not by
    # itself evidence they were offered AS a departure/return proposal (vs.
    # e.g. an unrelated aside). Require wording that actually frames them as
    # travel dates.
    date_proposal_cues = ("לצאת","לחזור","יציאה","חזרה","תאריך","נחיתה","טיסה","מתאים")
    if not any(cue in assistant_text for cue in date_proposal_cues):
        return {}
    found = re.findall(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)", assistant_text)
    parsed = []
    for day, month, year in found:
        try:
            d = date(int(year), int(month), int(day))
            if d not in parsed:
                parsed.append(d)
        except ValueError:
            pass
    # Exactly one pair only: if Ariella offered alternatives, customer must choose.
    if len(parsed) != 2 or parsed[1] <= parsed[0]:
        return {}
    dep, ret = parsed
    return {"dates":{
        "departure":dep.isoformat(),"return":ret.isoformat(),
        "period":f"{dep.strftime('%d.%m.%Y')}–{ret.strftime('%d.%m.%Y')}",
        "needs_confirmation":False,"candidate_ranges":[]
    }}


def _accept_single_proposed_date_range(message, state=None):
    """A single concrete date proposal becomes authoritative when the customer continues without rejecting/changing it."""
    import re
    state = state if isinstance(state, dict) else {}
    dates = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    candidates = dates.get("candidate_ranges") if isinstance(dates.get("candidate_ranges"), list) else []
    if not dates.get("needs_confirmation") or len(candidates) != 1:
        return {}
    msg = str(message or "").strip().lower()
    # "תשני" ("change [it]") deliberately excluded - see
    # _accept_assistant_single_date_proposal's docstring/comment for the
    # live-transcript false rejection this caused ("מצוין. תשני רק את תאריך
    # החזרה" read as rejecting the very date it was agreeing to).
    reject = ("לא", "במקום", "שני את", "אחר", "אחרת", "לא מתאים")
    if any(x in msg for x in reject):
        return {}
    chosen = str(candidates[0])
    found = re.findall(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})", chosen)
    if len(found) != 2:
        return {}
    try:
        dep = date(int(found[0][2]), int(found[0][1]), int(found[0][0]))
        ret = date(int(found[1][2]), int(found[1][1]), int(found[1][0]))
    except ValueError:
        return {}
    if ret <= dep:
        return {}
    return {"dates":{
        "departure":dep.isoformat(),"return":ret.isoformat(),
        "period":f"{dep.strftime('%d.%m.%Y')}–{ret.strftime('%d.%m.%Y')}",
        "needs_confirmation":False,"candidate_ranges":[]
    }}


def _deterministic_candidate_choice_facts(message, state=None):
    """Resolve a customer's selected candidate date range into exact ISO dates."""
    import re
    state = state if isinstance(state, dict) else {}
    dates = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    candidates = dates.get("candidate_ranges") if isinstance(dates.get("candidate_ranges"), list) else []
    if not dates.get("needs_confirmation") or not candidates:
        return {}
    msg = str(message or "").strip()
    # Accept an exact range repeated by the customer, or an ordinal choice such as
    # "הראשון/השני" after Ariella displayed candidate ranges.
    chosen = None
    ordinal_map = {"הראשון":0,"ראשון":0,"הראשונה":0,"השני":1,"שני":1,"השנייה":1,"השניה":1}
    for word, idx in ordinal_map.items():
        if word in msg and idx < len(candidates):
            chosen = candidates[idx]
            break
    if chosen is None:
        normalized_msg = msg.replace("–","-").replace("—","-").replace(" ","")
        for candidate in candidates:
            if str(candidate).replace("–","-").replace("—","-").replace(" ","") in normalized_msg:
                chosen = candidate
                break
    if chosen is None:
        return {}
    found = re.findall(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})", str(chosen))
    if len(found) != 2:
        return {}
    try:
        dep = date(int(found[0][2]), int(found[0][1]), int(found[0][0]))
        ret = date(int(found[1][2]), int(found[1][1]), int(found[1][0]))
    except ValueError:
        return {}
    if ret <= dep:
        return {}
    return {"dates":{
        "departure":dep.isoformat(),"return":ret.isoformat(),
        "period":f"{dep.strftime('%d.%m.%Y')}–{ret.strftime('%d.%m.%Y')}",
        "needs_confirmation":False,"candidate_ranges":[]
    }}


def _deterministic_only_flights_facts(message):
    """'Only flights' is an explicit decision for all four service domains."""
    msg = str(message or "").strip().lower()
    compact = " ".join(msg.split())
    only_flights = any(p in compact for p in (
        "רק טיסות", "טיסות בלבד", "רק טיסה", "טיסה בלבד",
        "only flights", "flights only"
    ))
    if not only_flights:
        return {}
    return {
        "search_intent": True,
        "requested_services": ["flights"],
        "service_decisions": {
            "flights": {"wanted": True, "source": "explicit_only_flights"},
            "lodging": {"wanted": False, "source": "explicit_only_flights"},
            "car": {"wanted": False, "source": "explicit_only_flights"},
            "trip_planning": {"wanted": False, "source": "explicit_only_flights"},
        },
        "session_status": {
            "flights": "active", "lodging": "declined",
            "car": "declined", "trip_planning": "declined"
        },
        "active_session": "flights",
    }


def _deterministic_budget_facts(message):
    """Treat explicit no-budget-limit language as a completed budget decision."""
    msg = str(message or "").strip().lower()
    no_limit_phrases = (
        "אין תקציב לאדם", "אין לי תקציב", "ללא תקציב", "בלי תקציב",
        "אין הגבלת תקציב", "ללא הגבלת תקציב", "לא מוגבלת בתקציב",
        "לא מוגבל בתקציב", "אין מגבלת תקציב"
    )
    if any(p in msg for p in no_limit_phrases):
        return {"budget_per_person":{"amount":None,"currency":None,"status":"unlimited"}}
    return {}


def _deterministic_baggage_facts(message):
    """Safety net for flight.baggage: a customer often answers baggage mixed
    into one longer reply that also covers origin airport, direct/connection
    preference and budget all at once. The extractor sometimes drops just the
    baggage part of a message like that, so Tinkerbell asks about baggage
    again next turn - even after it was already answered, sometimes more than
    once in a row. Matches only clear, unambiguous phrasing to avoid false
    positives; order matters, since "carry-on only" phrasing must be checked
    before a bare "no baggage" match ("רק טרולי" means a trolley, not nothing)."""
    import re
    msg = str(message or "")
    if not msg.strip():
        return {}
    if re.search(r"רק\s+טרולי|טרולי\s+בלבד|טרולי\s+לכל\s+אחד|רק\s+כבודת\s+עלי", msg):
        return {"flight": {"baggage": ["carry_on_only"]}}
    if re.search(r"מזוודה\s+למחסן|מזוודות?\s+גדול|יש\s+ל(נו|י)\s+מזוודה", msg):
        return {"flight": {"baggage": ["checked_bag"]}}
    if re.search(r"רק\s+תיק\s+יד|תיק\s+קטן\s+בלבד|רק\s+תיק(?!\s+עלי)", msg):
        return {"flight": {"baggage": ["personal_item"]}}
    if re.search(r"אין\s+לי\s+שום\s+כבודה|בלי\s+שום\s+כבודה|בלי\s+כבודה\s+בכלל", msg):
        return {"flight": {"baggage": ["no_baggage"]}}
    return {}


def _deterministic_service_decline_facts(history, message):
    """Safety net for a short decline reply ("לא"/"גם לא"/"גם לא כרגע"/"לא
    תודה" etc.) to Ariella's own immediately previous question about a
    SPECIFIC service (lodging or car). A short, context-only reply like this
    names no service itself, and a live transcript showed the extractor lose
    track of which one it answered: a lodging decline got misattributed to
    the car question being re-asked, and by the time car was declined
    lodging had silently reverted to pending and got asked again from
    scratch - an outright loop between the two. Only fires when Ariella's
    own last message unambiguously named exactly one of the two services."""
    compact = " ".join(str(message or "").strip().split())
    decline_phrases = {
        "לא", "לא.", "לא!", "לא תודה", "גם לא", "גם לא כרגע", "לא כרגע",
        "לא צריך", "לא צריכים", "בלי", "לא תודה כרגע",
    }
    if compact not in decline_phrases:
        return {}
    assistant_text = ""
    for item in reversed(history or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").lower()
        if role in ("assistant", "ariella", "tinkerbell"):
            assistant_text = str(item.get("content") or "")
            break
    if not assistant_text:
        return {}
    # Ariella's reply often acknowledges the PREVIOUS topic in one sentence
    # before asking about the new one ("understood, no lodging - now, about
    # a rental car?") - checking the whole message for either keyword would
    # see both and bail out as ambiguous. The actual question lives in the
    # final clause, so only that is checked.
    import re
    clauses = [c.strip() for c in re.split(r"[.!?]+", assistant_text) if c.strip()]
    last_clause = clauses[-1] if clauses else assistant_text
    lodging_kw = ("לינה", "מלון", "וילה", "דירה", "אכסניה")
    mentions_lodging = any(k in last_clause for k in lodging_kw)
    mentions_car = "רכב" in last_clause
    if mentions_lodging and not mentions_car:
        service = "lodging"
    elif mentions_car and not mentions_lodging:
        service = "car"
    else:
        return {}
    return {
        "service_decisions": {service: {"wanted": False, "source": "explicit_short_decline"}},
        "session_status": {service: "declined"},
    }


def _deterministic_period_facts(message):
    """Parse weekday/month windows; ambiguous end-of-month requests require customer choice."""
    import re, calendar
    msg=str(message or "").strip().lower()
    months={"ינואר":1,"פברואר":2,"מרץ":3,"אפריל":4,"מאי":5,"יוני":6,"יולי":7,"אוגוסט":8,"ספטמבר":9,"אוקטובר":10,"נובמבר":11,"דצמבר":12}
    weekdays={"ראשון":6,"שני":0,"שלישי":1,"רביעי":2,"חמישי":3,"שישי":4,"שבת":5}
    month_name=next((name for name in months if name in msg),None); month=months.get(month_name) if month_name else None
    pair=re.search(r"(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)\\s*(?:עד|[-–])\\s*(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)",msg)
    if not month or not pair:return {}
    today=date.today(); year=today.year+(1 if month<today.month else 0)
    start_wd,end_wd=weekdays[pair.group(1)],weekdays[pair.group(2)]; delta=(end_wd-start_wd)%7
    if "סוף" in msg:
        last=calendar.monthrange(year,month)[1]; candidates=[]
        for day in range(max(1,last-14),last+1):
            d=date(year,month,day)
            if d.weekday()==start_wd:candidates.append((d,d+timedelta(days=delta)))
        candidates=candidates[-2:]
        labels=[f"{x.strftime('%d.%m.%Y')}–{y.strftime('%d.%m.%Y')}" for x,y in candidates]
        return {"dates":{"departure":None,"return":None,"period":f"סוף {month_name} {year}, {pair.group(1)} עד {pair.group(2)}","constraints":[f"{pair.group(1)} עד {pair.group(2)}"],"candidate_ranges":labels,"needs_confirmation":True}}
    after=re.search(r"אחרי\\s+(?:ה[- ]?)?(\\d{1,2})",msg); min_day=int(after.group(1))+1 if after else 1
    start=None
    for day in range(min_day,32):
        try:d=date(year,month,day)
        except ValueError:break
        if d.weekday()==start_wd:start=d;break
    if not start:return {"dates":{"period":f"{pair.group(1)} עד {pair.group(2)} ב{month_name} {year}"}}
    end=start+timedelta(days=delta)
    return {"dates":{"departure":start.isoformat(),"return":end.isoformat(),"period":f"{pair.group(1)} עד {pair.group(2)}","constraints":[f"אחרי {min_day-1}.{month}.{year}"]}}

def _deterministic_departure_airport_facts(message):
    """Capture an explicitly named Israeli departure airport so it never depends
    solely on the extractor remembering to copy it over in a dense message."""
    import re
    msg = str(message or "").strip().lower()
    tlv_phrases = (
        "נתבג", 'נתב"ג', "נתב’ג", "נתב'ג", "מנתבג", 'מנתב"ג',
        "בן גוריון", "בן-גוריון", "מבן גוריון", "מבן-גוריון", "tlv",
    )
    if any(p in msg for p in tlv_phrases):
        return {"departure_airport": "TLV"}
    # "חיפה" alone is ambiguous (a home city, not necessarily the airport), so
    # only match it when the message clearly ties it to departing/the airport.
    hfa_phrases = ("משדה חיפה", "משדה תעופה חיפה", "hfa")
    if any(p in msg for p in hfa_phrases):
        return {"departure_airport": "HFA"}
    if re.search(r"(נצא|לצאת|יציאה|טסים|נטוס)[^.,!?]{0,6}מחיפה", msg):
        return {"departure_airport": "HFA"}
    return {}


def _deterministic_trip_type_facts(message):
    """Capture an explicit vacation-type choice (regular/business/ski) so the
    opening question doesn't depend solely on the LLM extractor."""
    msg = str(message or "").strip().lower()
    # Short exact replies (matched only against the whole, trimmed message -
    # never as a substring) cover directly answering the opening question
    # ("regular vacation, business trip, or ski vacation?") with just one
    # word, without risking a false match inside an unrelated longer sentence.
    business_exact = {"עסקים", "נסיעת עסקים", "עסקי", "עסקית", "business"}
    ski_exact = {"סקי", "חופשת סקי", "ski"}
    standard_exact = {"רגילה", "חופשה רגילה", "רגיל", "standard", "regular"}
    if msg in business_exact:
        return {"trip_type": "business"}
    if msg in ski_exact:
        return {"trip_type": "ski"}
    if msg in standard_exact:
        return {"trip_type": "standard"}
    business_phrases = ("נסיעת עסקים", "נסיעה עסקית", "טיסת עסקים", "טיול עסקים", "business trip")
    ski_phrases = ("חופשת סקי", "טיול סקי", "נסיעת סקי", "לגלוש בסקי", "חופשת גלישה בשלג", "ski trip", "ski vacation")
    standard_phrases = ("חופשה רגילה", "חופשת נופש", "לא, חופשה", "זו חופשה")
    if any(p in msg for p in business_phrases):
        return {"trip_type": "business"}
    if any(p in msg for p in ski_phrases):
        return {"trip_type": "ski"}
    if any(p in msg for p in standard_phrases):
        return {"trip_type": "standard"}
    return {}


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
    genders = []
    for m in re.finditer(r"(בת|בן)\s*(\d{1,2})\b", msg):
        age = int(m.group(2))
        if 0 <= age <= 17:
            ages.append(age)
            genders.append("female" if m.group(1) == "בת" else "male")
    if ages:
        facts["child_ages"] = ages
        # "בת"/"בן" preceding the age is itself the customer's own gender
        # statement ("ילדה בת 17" = a girl, age 17) - carry it through so the
        # final summary can refer to the child correctly, instead of relying
        # on the model to guess (it doesn't: seen live defaulting a stated
        # "ילדה בת 17" to "נער בן 17" in the summary, since nothing preserved
        # the gender the customer actually gave).
        facts["child_genders"] = genders
        if "children" not in facts:
            facts["children"] = len(ages)

    if re.search(r"2\s*(?:הורים|מבוגרים)", msg):
        facts["adults"] = 2
    return {"travelers": facts} if facts else {}


def _member_profile(member_id):
    """Authoritative name/gender for personalizing the conversation. Always
    read fresh from the registration data - never trust a client-supplied
    profile, which can be stale, spoofed, or (as the client widget did)
    silently defaulted to a wrong gender."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT full_name, gender FROM members WHERE id=?", (member_id,)).fetchone()
        conn.close()
    except Exception:
        return {"first_name": "", "gender": None}
    if not row:
        return {"first_name": "", "gender": None}
    full_name = str(row["full_name"] or "").strip()
    first_name = full_name.split()[0] if full_name else ""
    gender = str(row["gender"] or "").strip().lower() or None
    return {"first_name": first_name, "gender": gender}


def _remember_turn_reset_trip(member_id, history, message, reply, fresh_trip_state):
    """Used on a new-vacation boundary: this turn still joins the one
    continuous conversation history, but the structured vacation data
    starts over. The conversation itself is never erased."""
    try:
        existing = load_ariella_conversation(member_id)
        full_history = list((existing or {}).get('history') or history) + [
            {'role': 'user', 'content': message},
            {'role': 'assistant', 'content': reply},
        ]
        save_ariella_conversation(member_id, full_history[-80:], fresh_trip_state)
    except Exception:
        logging.exception("Failed to persist Ariella conversation reset for member %s", member_id)


@ariella_chat_clean.get('/api/ariella/resume')
def chat_resume():
    """Let a page load hydrate the member's own in-progress conversation from
    the server, so it's available on any device/browser they log into, not
    only the one it was saved from."""
    if not session.get('member_id'):
        return jsonify({'status': 'error', 'message': 'נדרשת התחברות כדי לשוחח עם אריאלה.'}), 401
    saved = load_ariella_conversation(session['member_id'])
    if not saved:
        return jsonify({'status': 'success', 'history': [], 'trip_state': {}})
    return jsonify({'status': 'success', 'history': saved.get('history') or [], 'trip_state': saved.get('trip_state') or {}})


@ariella_chat_clean.post('/api/ariella/reset-conversation')
def chat_reset_conversation():
    """A full, permanent reset of the member's own saved conversation - not
    the ordinary "new vacation" reset (which only clears structured trip
    facts and keeps history growing), but a genuine start-from-nothing wipe
    of the visible chat itself, on explicit customer request only."""
    if not session.get('member_id'):
        return jsonify({'status': 'error', 'message': 'נדרשת התחברות כדי לשוחח עם אריאלה.'}), 401
    clear_ariella_conversation(session['member_id'])
    return jsonify({'status': 'success'})


@ariella_chat_clean.post('/api/ariella/chat-clean')
def chat_clean():
    if not session.get('member_id'):
        return jsonify({'status': 'error', 'message': 'נדרשת התחברות כדי לשוחח עם אריאלה.', 'engine_version': ENGINE_VERSION}), 401

    body = request.get_json(silent=True) or {}
    message = str(body.get('message') or '').strip()
    if not message:
        return jsonify({'status': 'error', 'message': 'message is required', 'engine_version': ENGINE_VERSION}), 400

    history = body.get('history') if isinstance(body.get('history'), list) else []
    trip_state = body.get('trip_state') if isinstance(body.get('trip_state'), dict) else {}
    # The browser's local cache is per-device and empties on logout/switching
    # devices. When it has no progress at all, resume the member's own
    # server-saved conversation instead of starting over.
    if not trip_state:
        saved_conversation = load_ariella_conversation(session['member_id'])
        if saved_conversation and (saved_conversation.get('trip_state') or saved_conversation.get('history')):
            history = saved_conversation.get('history') or history
            trip_state = saved_conversation.get('trip_state') or trip_state
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    model = os.getenv('ARIELLA_MODEL', 'claude-sonnet-5').strip()

    # A customer question about a DIFFERENT/past vacation ("את זוכרת את
    # הטיסה לניו יורק?") must be answered from their real trip history, not
    # left for the model to (truthfully) say it has no record of, or worse,
    # guess at. This is a deterministic lookup - exactly one correct answer -
    # so it short-circuits before any LLM call, and never touches the
    # current conversation's own trip_state.
    past_trip_triggers = (
        "זוכרת את", "את זוכרת", "זוכר את", "אתה זוכר",
        "שסגרנו", "שכבר תכננו", "שכבר סגרנו", "שכבר הזמנו",
        "מהטיול ש", "מהחופשה ש", "לטיול הישן", "לחופשה הישנה",
    )
    if any(p in message for p in past_trip_triggers):
        import re as _re

        def _he_window(trip):
            # Match the day.month.year layout used everywhere else customer-
            # facing (confirmed against the flight-leg date display) - never
            # the raw ISO year-first storage format.
            return _re.sub(
                r"(\d{4})-(\d{2})-(\d{2})",
                lambda m: f"{m.group(3)}.{m.group(2)}.{m.group(1)}",
                str(trip.get('travel_window') or ''),
            )

        member_id = session.get('member_id')
        matches = find_member_trip_by_mention(member_id, message) if member_id else []
        if len(matches) == 1:
            trip = matches[0]
            reply = (
                f"כן, זוכרת! {trip['request_name']} ({_he_window(trip)}). "
                "אפשר להמשיך את החופשה הזו ישירות מהכרטיסייה שלך - שם אפשר גם לבקש למצוא לינה או רכב עבורה."
            )
            return jsonify({
                'status': 'success', 'agent': 'Ariella', 'engine_version': ENGINE_VERSION,
                'reply': reply, 'trip_update': trip_state, 'start_flight_search': False,
                'open_existing_trip_id': trip['id'],
            })
        elif len(matches) > 1:
            # Each candidate needs its own date and id shown - two same-named
            # vacations ("קפריסין, קפריסין") are otherwise indistinguishable,
            # leaving the customer no way to say which one they meant.
            listed = "; ".join(
                f"{m['request_name']} ({_he_window(m)}, מספר חופשה {m['id']})"
                for m in matches[:5]
            )
            reply = f"מצאתי כמה חופשות שיכולות להתאים: {listed}. לאיזו מהן התכוונת?"
            return jsonify({
                'status': 'success', 'agent': 'Ariella', 'engine_version': ENGINE_VERSION,
                'reply': reply, 'trip_update': trip_state, 'start_flight_search': False,
            })
        # No match: fall through to the normal model call, which already
        # knows (per its own instructions) to say honestly that it has no
        # record rather than invent one.

    # After the flight handoff, keep the same vacation as the default context.
    # When the customer asks for one of the remaining services, deterministically
    # activate that session and keep it active across follow-up answers.
    msg_lower = message.lower()
    service_request = None
    if any(x in msg_lower for x in ("מסלול", "אטרקצי", "מה לעשות", "טיול יומי", "תכנון טיול")):
        service_request = "trip_planning"
    elif any(x in msg_lower for x in ("מלון", "לינה", "וילה", "דירה")):
        service_request = "lodging"
    elif any(x in msg_lower for x in ("רכב", "השכרת רכב")):
        service_request = "car"

    existing_active = str(trip_state.get("active_session") or "")
    if service_request and trip_state.get("post_flight_continuation"):
        continued = dict(trip_state)
        statuses = dict(continued.get("session_status") or {})
        decisions = dict(continued.get("service_decisions") or {})
        services = list(continued.get("requested_services") or [])
        statuses[service_request] = "active"
        decisions[service_request] = {"wanted": True, "source": "explicit_post_flight_request"}
        if service_request not in services:
            services.append(service_request)
        continued["session_status"] = statuses
        continued["service_decisions"] = decisions
        continued["requested_services"] = services
        continued["active_session"] = service_request
        continued["next_session"] = None
        trip_state = continued
    elif existing_active in {"lodging", "car", "trip_planning"} and trip_state.get("post_flight_continuation"):
        # Ordinary answers inside a chosen post-flight session must not let the
        # extractor/sessionizer jump back to flights or another pending service.
        locked = dict(trip_state)
        statuses = dict(locked.get("session_status") or {})
        statuses[existing_active] = "active"
        locked["session_status"] = statuses
        locked["active_session"] = existing_active
        trip_state = locked

    # A request for a genuinely new vacation after a completed/approved trip is
    # a hard boundary, not a field edit. Clear the old structured trip immediately
    # and seed only facts explicitly present in the new request.
    new_vacation_language = any(x in msg_lower for x in ("חופשה חדשה","טיול חדש","חיפוש חדש לגמרי","חופשה אחרת","טיול אחר"))
    old_trip_committed = bool(trip_state.get("search_confirmed") or trip_state.get("post_flight_continuation"))
    if new_vacation_language and old_trip_committed:
        fresh = {
            'session_status':{'flights':'pending','lodging':'pending','car':'pending','trip_planning':'pending'},
            'active_session':None
        }
        seed = _deterministic_destination_facts([], message, {})
        if seed:
            fresh = _merge_trip_state(fresh, seed)
        if any(x in msg_lower for x in ("טיסה","טיסות")):
            fresh['requested_services'] = ['flights']
            fresh['active_session'] = 'flights'
            fresh['session_status']['flights'] = 'active'
            fresh['service_decisions'] = {'flights':{'wanted':True,'source':'explicit_new_vacation'}}
        places = ((fresh.get('destination') or {}).get('places') or []) if isinstance(fresh.get('destination'), dict) else []
        reply = (f"בשמחה. מתחילים חופשה חדשה ל{places[0]}. באיזו תקופה תרצי לטוס?"
                 if places else "בשמחה. מתחילים חופשה חדשה. לאן תרצי לטוס ובאיזו תקופה?")
        _remember_turn_reset_trip(session['member_id'], history, message, reply, fresh)
        return jsonify({
            'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
            'reply':reply,'trip_update':fresh,'start_flight_search':False,'trip_state_reset':True
        })

    # Returning to an already-approved flight-only vacation is a navigation
    # action, not a new conversational turn and never a reason to launch a
    # duplicate scan. The browser will reopen the existing vacation's flight tab.
    flight_only_return = (
        bool(trip_state.get("post_flight_continuation"))
        and bool(trip_state.get("search_confirmed"))
        and any(x in msg_lower for x in ("רק טיסה","רק טיסות","טיסה בלבד","טיסות בלבד"))
    )
    if flight_only_return:
        return jsonify({
            'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
            'reply':'פרטי הטיסה כבר אושרו. אני מחזירה אותך לטיסות של החופשה הזו.',
            'trip_update':trip_state,'start_flight_search':False,'open_existing_flights':True
        })

    # Interpret answers to a pending "same vacation or new vacation?" question
    # semantically. The customer can answer naturally; there are no magic phrases.
    last_assistant = ""
    for _item in reversed(history):
        if isinstance(_item, dict) and str(_item.get("role") or "").lower() == "assistant":
            last_assistant = str(_item.get("content") or "").strip().lower()
            break
    _previous_asked_new_vacation = (
        "חופשה" in last_assistant and "חדשה" in last_assistant
        and ("הקודמת" in last_assistant or "הנוכחית" in last_assistant or "אותה חופשה" in last_assistant or "למחוק" in last_assistant or "להתחיל" in last_assistant)
    )
    if _previous_asked_new_vacation:
        _intent = _interpret_pending_choice(key, model, history, message, "new_vacation")
        if _intent == "new":
            _remember_turn_reset_trip(session['member_id'], history, message, 'בשמחה 😊 לאן תרצי לטוס ובאיזו תקופה?', {'session_status':{'flights':'pending','lodging':'pending','car':'pending','trip_planning':'pending'},'active_session':None})
            return jsonify({
                'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
                'reply':'בשמחה 😊 לאן תרצי לטוס ובאיזו תקופה?',
                'trip_update':{'session_status':{'flights':'pending','lodging':'pending','car':'pending','trip_planning':'pending'},'active_session':None},
                'start_flight_search':False,'trip_state_reset':True
            })
        if _intent == "keep":
            kept = dict(trip_state)
            kept["reset_pending"] = False
            kept.pop("reset_change_request", None)
            return jsonify({
                'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
                'reply':'בשמחה. מה תרצי לשנות בחופשה הנוכחית?',
                'trip_update':kept,'start_flight_search':False
            })

    # General restart/change-of-direction always enters a simple yes/no gate.
    # Never erase collected trip facts before an explicit confirmation.
    if _reset_intent(message) and not trip_state.get("reset_pending"):
        pending = dict(trip_state)
        pending["reset_pending"] = True
        pending["reset_change_request"] = message
        # When the current interaction is flight-only, the reset gate applies only
        # to flight-search details. Shared vacation/other-service data is untouched.
        statuses_reset = trip_state.get("session_status") if isinstance(trip_state.get("session_status"), dict) else {}
        flight_only_reset = (
            str(trip_state.get("active_session") or "") == "flights"
            or (statuses_reset.get("flights") in {"active","complete"} and not any(statuses_reset.get(s) == "active" for s in ("lodging","car","trip_planning")))
        )
        pending["reset_scope"] = "flights" if flight_only_reset else "vacation"
        question = (
            "רוצה שנתחיל טיסה חדשה לגמרי ונמחק את הפרטים הקיימים, או שנשאיר הכול ונשנה רק את מה שביקשת? (כן = להתחיל מחדש, לא = להשאיר ולשנות)"
            if flight_only_reset else
            "רוצה שנתחיל חופשה חדשה לגמרי ונמחק את כל הפרטים שנאספו, או שנשאיר הכול ונשנה רק את מה שביקשת? (כן = להתחיל מחדש, לא = להשאיר ולשנות)"
        )
        return jsonify({
            'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
            'reply':question,
            'trip_update':pending,'start_flight_search':False
        })

    if trip_state.get("reset_pending"):
        msg_norm = str(message or "").strip().lower()
        yes_answers = {"כן", "כן.", "כן!", "בטח", "בהחלט"}
        no_answers = {"לא", "לא.", "לא!", "לא תודה"}

        if msg_norm in yes_answers:
            original_change = str(trip_state.get("reset_change_request") or "").strip()
            if trip_state.get("reset_scope") == "flights":
                fresh = dict(trip_state)
                for key_name in ("departure_airport","destination_airports","flight","budget_per_person","search_confirmed","ready_for_summary"):
                    fresh.pop(key_name, None)
                fresh["dates"] = {}
                statuses_fresh = dict(fresh.get("session_status") or {})
                statuses_fresh["flights"] = "active"
                fresh["session_status"] = statuses_fresh
                fresh["active_session"] = "flights"
                fresh["search_intent"] = True
                fresh["reset_pending"] = False
                fresh.pop("reset_scope", None)
                fresh.pop("reset_change_request", None)
                return jsonify({
                    'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
                    'reply':'בסדר. מחקתי את פרטי הטיסה. לאן תרצי לטוס ובאיזו תקופה?',
                    'trip_update':fresh,'start_flight_search':False
                })
            # The message that triggered the reset gate may already contain facts
            # for the NEW vacation ("I want you to plan Greece"). Preserve those
            # facts across the confirmation instead of asking for them again.
            fresh = {
                'session_status':{'flights':'pending','lodging':'pending','car':'pending','trip_planning':'pending'},
                'active_session':None
            }
            pending_destination = _deterministic_destination_facts([], original_change, {})
            if pending_destination:
                fresh = _merge_trip_state(fresh, pending_destination)
            if any(x in original_change.lower() for x in ("מסלול","לתכנן טיול","תכנון טיול","אטרקציות")):
                fresh['requested_services'] = ['trip_planning']
                fresh['active_session'] = 'trip_planning'
                fresh['session_status']['trip_planning'] = 'active'
                fresh['service_decisions'] = {'trip_planning':{'wanted':True}}
            places = ((fresh.get('destination') or {}).get('places') or []) if isinstance(fresh.get('destination'), dict) else []
            if places:
                reply = f"בשמחה. מתחילים חופשה חדשה ל{places[0]}. נמשיך מכאן בתכנון הטיול — באיזו תקופה תרצי לנסוע?"
            else:
                reply = 'בסדר. מתחילים חופשה חדשה. לאן מתחשק לך לטוס ובאיזו תקופה?'
            _remember_turn_reset_trip(session['member_id'], history, message, reply, fresh)
            return jsonify({
                'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
                'reply':reply,'trip_update':fresh,'start_flight_search':False,'trip_state_reset':True
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
                'reply':('מה תרצי לשנות בפרטי הטיסה?' if trip_state.get("reset_scope") == "flights" else 'מה תרצי לשנות בחופשה הנוכחית?'),
                'trip_update':kept,'start_flight_search':False
            })

        # While awaiting this gate, do not let the model reinterpret or mutate
        # the trip. Keep the question binary and deterministic.
        pending = dict(trip_state)
        return jsonify({
            'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
            'reply':('רק כדי לוודא: למחוק הכול ולהתחיל טיסה חדשה, או להשאיר ולשנות רק פרט אחד? (כן = למחוק ולהתחיל מחדש, לא = להשאיר ולשנות)' if trip_state.get("reset_scope") == "flights" else 'רק כדי לוודא: למחוק הכול ולהתחיל חופשה חדשה, או להשאיר ולשנות רק פרט אחד? (כן = למחוק ולהתחיל מחדש, לא = להשאיר ולשנות)'),
            'trip_update':pending,'start_flight_search':False
        })

    # Destination replacement is the only ordinary field change that requires
    # confirmation because route/lodging/car destination-dependent facts become stale.
    # A real customer's destination-change wasn't caught here because this list only
    # named 8 countries - "ספרד" (Spain) wasn't one of them, so the swap fell through
    # to plain extraction with no confirmation/rebuild step, in a conversation Tinkerbell
    # itself was already confused by. Every city already in DESTINATIONS is covered
    # automatically now, plus every country those cities sit in, so a newly-added
    # destination city doesn't reopen this same gap.
    import re
    known_destinations = (
        "יוון", "קפריסין", "הונגריה", "אוסטריה", "בולגריה", "צ'כיה", "איטליה", "צרפת",
        "הולנד", "ספרד", "פורטוגל", "בריטניה", "גרמניה", "שוויץ", "בלגיה", "רומניה",
        "פולין", "גאורגיה", "ארמניה", "סרביה", "מקדוניה", "מונטנגרו", "קרואטיה",
        "סלובניה", "תאילנד", "ארה\"ב", "אלבניה", "איחוד האמירויות", "אזרבייג'ן",
        "מולדובה", "מלטה",
    ) + tuple(d["name"] for d in DESTINATIONS)
    current_destination = trip_state.get("destination") if isinstance(trip_state.get("destination"), dict) else {}
    current_places = current_destination.get("places") or []
    destination_change = None
    for candidate in known_destinations:
        if candidate in message and current_places and candidate not in current_places:
            if any(token in message for token in ("במקום","רוצה לטוס ל","היעד","לשנות")):
                destination_change = candidate
                break

    if destination_change and not trip_state.get("destination_change_pending"):
        pending = dict(trip_state)
        pending["destination_change_pending"] = destination_change
        return jsonify({
            'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
            'reply':'שינוי היעד משנה גם את המסלול, הלינה, נקודות הרכב ופרטי הטיסה שתלויים ביעד. למחוק את הפרטים שתלויים ביעד ולבנות אותם מחדש ליעד החדש?',
            'trip_update':pending,'start_flight_search':False
        })

    if trip_state.get("destination_change_pending"):
        msg_norm = str(message or "").strip().lower()
        if msg_norm in {"כן","כן.","כן!","בטח","בהחלט"}:
            changed = dict(trip_state)
            new_destination = changed.pop("destination_change_pending")
            changed["destination"] = {"places":[new_destination],"mode":"specific","status":"known"}
            old_lodging = changed.get("lodging") if isinstance(changed.get("lodging"), dict) else {}
            old_car = changed.get("car") if isinstance(changed.get("car"), dict) else {}
            old_plan = changed.get("trip_planning") if isinstance(changed.get("trip_planning"), dict) else {}
            changed["lodging"] = {"interested":old_lodging.get("interested","unknown"),"details":{}}
            changed["car"] = {"interested":old_car.get("interested","unknown"),"details":{}}
            changed["trip_planning"] = {"interested":old_plan.get("interested","unknown"),"details":{}}
            changed["ready_for_summary"] = False
            changed["search_confirmed"] = False
            changed["missing_required"] = []
            return jsonify({
                'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
                'reply':'בסדר. היעד עודכן. את המסלול, הלינה והרכב נבנה מחדש בהתאם ליעד החדש.',
                'trip_update':changed,'start_flight_search':False
            })
        if msg_norm in {"לא","לא.","לא!","לא תודה"}:
            kept = dict(trip_state)
            kept.pop("destination_change_pending", None)
            return jsonify({
                'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
                'reply':'בסדר, נשאיר את היעד הקיים.',
                'trip_update':kept,'start_flight_search':False
            })
        return jsonify({
            'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,
            'reply':'לשנות את היעד ולבנות מחדש את הפרטים שתלויים בו? כן או לא?',
            'trip_update':trip_state,'start_flight_search':False
        })

    # A confirmed/new-trip boundary prevents old vacation facts from being
    # resurrected by the model or deterministic history scanners.
    if trip_state.get("conversation_boundary") == "current_trip":
        history = _current_trip_history(history, trip_state)

    date_conflict = _weekday_date_conflict(message)
    if date_conflict:
        return jsonify({'status':'success','agent':'Tinkerbell','engine_version':ENGINE_VERSION,'reply':date_conflict,'trip_update':trip_state})
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if not key:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    model = os.getenv('ARIELLA_MODEL', 'claude-sonnet-5').strip()

    try:
        # Tinkerbell's data-transfer pass tells Ariella what changed.
        # Ariella owns and merges the cumulative state.
        extracted = _extract_trip_update(key, model, history, message, trip_state)
        trip_update = _merge_trip_state(trip_state, extracted)
        # Service intent is semantic. When the extractor explicitly resolves a
        # domain as wanted/not-wanted, that decision is authoritative even if an
        # older requested_services list still contains the domain.
        extracted_decisions = extracted.get("service_decisions") if isinstance(extracted, dict) and isinstance(extracted.get("service_decisions"), dict) else {}
        if extracted_decisions:
            decisions = dict(trip_update.get("service_decisions") or {})
            statuses = dict(trip_update.get("session_status") or {})
            services = set(trip_update.get("requested_services") or [])
            for service in ("flights","lodging","car","trip_planning"):
                d = extracted_decisions.get(service)
                wanted = d.get("wanted") if isinstance(d, dict) else d
                if wanted is True:
                    services.add(service)
                    statuses[service] = statuses.get(service) if statuses.get(service) == "complete" else "active"
                elif wanted is False:
                    services.discard(service)
                    statuses[service] = "declined"
            trip_update["requested_services"] = list(services)
            trip_update["service_decisions"] = decisions
            trip_update["session_status"] = statuses
        # Safety net for a short decline ("לא"/"גם לא כרגע" etc.) to Ariella's
        # own previous lodging/car question. Applied the same way as the
        # extractor's own decisions above so it authoritatively overrides a
        # misattributed or dropped extraction - see the function's docstring
        # for the live-transcript loop this fixes.
        deterministic_decline = _deterministic_service_decline_facts(history, message)
        decline_decisions = deterministic_decline.get("service_decisions") if isinstance(deterministic_decline, dict) else None
        if decline_decisions:
            decisions = dict(trip_update.get("service_decisions") or {})
            statuses = dict(trip_update.get("session_status") or {})
            services = set(trip_update.get("requested_services") or [])
            for service, d in decline_decisions.items():
                decisions[service] = d
                if (d.get("wanted") if isinstance(d, dict) else d) is False:
                    services.discard(service)
                    statuses[service] = "declined"
            trip_update["requested_services"] = list(services)
            trip_update["service_decisions"] = decisions
            trip_update["session_status"] = statuses
        # Safety net for facts that must never be re-asked. This helper already
        # existed but was not wired into the live chat path. Run it before
        # missing-field/session calculation so an explicitly stated destination
        # remains authoritative even when the LLM extractor misses it.
        trip_update = _merge_trip_state(
            trip_update,
            _deterministic_destination_facts(history, message, trip_state)
        )
        trip_update = _merge_trip_state(
            trip_update,
            _deterministic_date_facts(history, message, trip_state)
        )
        # Closed exact dates are sticky. Once the customer has an authoritative
        # departure+return range, an unrelated later turn (route, attractions,
        # car, lodging, "sounds good", etc.) must never reopen date selection.
        # Dates may change only when the current message itself contains a new
        # deterministic date fact/range.
        prior_dates = trip_state.get("dates") if isinstance(trip_state.get("dates"), dict) else {}
        current_date_facts = _deterministic_date_facts([], message, {})
        current_dates = current_date_facts.get("dates") if isinstance(current_date_facts, dict) and isinstance(current_date_facts.get("dates"), dict) else {}
        # An explicit new date range in the CURRENT customer message overrides the
        # old approved range. Sticky dates protect against unrelated turns only;
        # they must never block a correction such as "change it to 23-27 May 2027".
        if current_dates:
            trip_update["dates"] = dict(current_dates)
            trip_update["dates"]["needs_confirmation"] = False
            trip_update["dates"]["candidate_ranges"] = []
            trip_update["search_confirmed"] = False
            trip_update["ready_for_summary"] = False
        elif prior_dates.get("departure") and prior_dates.get("return"):
            locked_dates = dict(prior_dates)
            # Exact dates are authoritative. Do not preserve stale proposal flags
            # from an earlier candidate-selection phase.
            locked_dates["needs_confirmation"] = False
            locked_dates.pop("candidate_ranges", None)
            locked_dates.pop("candidates", None)
            trip_update["dates"] = locked_dates
        only_flights_facts = _deterministic_only_flights_facts(message)
        trip_update = _merge_trip_state(trip_update, only_flights_facts)
        # "Only flights" is a replacement decision, not an additive merge.
        # The generic recursive merge intentionally preserves lists, so enforce
        # the exclusive service set after extraction to prevent lodging/car/plan
        # from being resurrected by prior state or the LLM.
        if only_flights_facts:
            trip_update["requested_services"] = ["flights"]
            decisions = dict(trip_update.get("service_decisions") or {})
            decisions.update(only_flights_facts["service_decisions"])
            trip_update["service_decisions"] = decisions
            statuses = dict(trip_update.get("session_status") or {})
            statuses.update(only_flights_facts["session_status"])
            trip_update["session_status"] = statuses
            trip_update["active_session"] = "flights"
            trip_update["next_session"] = None
        trip_update = _merge_trip_state(trip_update, _deterministic_budget_facts(message))
        trip_update = _merge_trip_state(trip_update, _deterministic_baggage_facts(message))
        trip_update = _merge_trip_state(trip_update, _deterministic_departure_airport_facts(message))
        trip_update = _merge_trip_state(trip_update, _deterministic_trip_type_facts(message))
        trip_update = _merge_trip_state(trip_update, _deterministic_traveler_facts(message))
        trip_update = _merge_trip_state(trip_update, _deterministic_duration_facts(message, trip_state))
        # If Ariella's immediately previous reply proposed one concrete date range
        # and the customer simply continued (e.g. supplied the airport), accept it.
        trip_update = _merge_trip_state(trip_update, _accept_assistant_single_date_proposal(history, message, trip_state))
        # A single proposed range is accepted when the customer naturally continues
        # without rejecting/changing it. Multiple alternatives still require a choice.
        trip_update = _merge_trip_state(trip_update, _accept_single_proposed_date_range(message, trip_state))
        # If Ariella offered concrete date ranges and the customer chose one,
        # convert that choice to authoritative exact dates before any summary/search.
        trip_update = _merge_trip_state(trip_update, _deterministic_candidate_choice_facts(message, trip_state))
        # Current message + Ariella state only. Never resurrect facts from old chat history.
        trip_update = _merge_trip_state(trip_update, _deterministic_period_facts(message))

        # A normal trip request to a destination implies Ariella should handle
        # flights unless the customer explicitly says flights are booked/not needed.
        dest_state = trip_update.get("destination") if isinstance(trip_update.get("destination"), dict) else {}
        decisions_state = trip_update.get("service_decisions") if isinstance(trip_update.get("service_decisions"), dict) else {}
        flight_decision = decisions_state.get("flights")
        flight_wanted = flight_decision.get("wanted") if isinstance(flight_decision, dict) else flight_decision
        if dest_state.get("places") and flight_wanted is not False:
            services_state = list(trip_update.get("requested_services") or [])
            if "flights" not in services_state:
                services_state.append("flights")
            trip_update["requested_services"] = services_state
            decisions_state = dict(decisions_state)
            if flight_decision is None:
                decisions_state["flights"] = {"wanted": True, "source": "destination_trip_intent"}
            trip_update["service_decisions"] = decisions_state

        # During a chosen post-flight service, preserve the session lock unless
        # the customer explicitly selected another service above.
        locked_post_flight_session = str(trip_state.get("active_session") or "")
        if trip_state.get("post_flight_continuation") and locked_post_flight_session in {"lodging","car","trip_planning"}:
            statuses_lock = dict(trip_update.get("session_status") or {})
            statuses_lock[locked_post_flight_session] = "active"
            trip_update["session_status"] = statuses_lock
            trip_update["active_session"] = locked_post_flight_session
        # A confirmed route settles the flight gateway even if the extractor
        # forgot to copy it into destination_airports this turn.
        trip_update = _resolve_destination_airports_from_route(trip_update)
        # A ski trip's gateway is derived from the ski resort catalog instead.
        trip_update = _resolve_ski_destination_airports(trip_update)
        # Ariella, not chat history, owns the four-session progression.
        trip_update = _advance_sessions(trip_update)
        # The customer's name/gender always come fresh from their registration
        # data, never from client-supplied state, which can be stale or wrong.
        trip_update["profile"] = _member_profile(session["member_id"])
        if trip_update["profile"].get("gender"):
            trip_update["user_gender"] = trip_update["profile"]["gender"]

        # If the customer has just declined/deferred the remaining optional
        # services and every wanted service is already complete, skip the
        # conversational acknowledgement turn. Go straight to the final summary.
        # This is service-agnostic: flights/lodging/car/trip planning behave alike.
        statuses_now = trip_update.get("session_status") if isinstance(trip_update.get("session_status"), dict) else {}
        decisions_now = trip_update.get("service_decisions") if isinstance(trip_update.get("service_decisions"), dict) else {}
        resolved_all_services = all(
            statuses_now.get(s) in ("complete","declined")
            or ((decisions_now.get(s) or {}).get("wanted") is False if isinstance(decisions_now.get(s), dict) else decisions_now.get(s) is False)
            for s in ("flights","lodging","car","trip_planning")
        )
        force_summary_now = bool(trip_update.get("ready_for_summary")) and resolved_all_services

        # A natural confirmation of an already-proposed itinerary closes only
        # the planning session. Persist the approved plan context for the vacation
        # card; enrichment (DB prices/ticket links) can consume this state without
        # reopening the conversation as a questionnaire.
        msg_confirm = _normalize_confirm(message).lower()
        planning_active = str(trip_state.get("active_session") or "") == "trip_planning"
        prior_assistant = " ".join(
            str(x.get("content") or "") for x in (history or [])[-4:]
            if isinstance(x, dict) and str(x.get("role") or "").lower() == "assistant"
        )
        planning_accept = planning_active and msg_confirm in {
            "כן","כן.","מעולה","מצוין","מצויין","אחלה","נשמע טוב","נשמע סבבה","סבבה","סבבה גמור","מתאים","מאשרת","מאשר"
        } and any(x in prior_assistant for x in ("מסלול","יום ראשון","יום שני","יום שלישי","יום רביעי","אטרק"))
        if planning_accept:
            statuses_plan = dict(trip_update.get("session_status") or {})
            statuses_plan["trip_planning"] = "complete"
            trip_update["session_status"] = statuses_plan
            trip_update["active_session"] = None
            plan = dict(trip_update.get("trip_planning") or {})
            plan["interested"] = True
            plan["approved"] = True
            plan["enrichment_pending"] = True
            trip_update["trip_planning"] = plan

        try:
            reply = _call_tinkerbell(key, model, history, message, trip_update)
        except Exception as exc:
            logging.exception("Tinkerbell reply failed after state update: %s", exc)
            # Preserve Ariella's newly collected state even if the conversational
            # model has a transient failure. The next user turn can continue.
            reply = "קלטתי את הפרטים. נמשיך מכאן."
        reply = _fix_child_gender_wording(reply, trip_update)

        if planning_accept:
            # Approval closes only the itinerary session. Name whichever of the
            # other three domains are still genuinely open - this must never
            # assume flights was already handled. trip_planning can be the
            # FIRST session a customer goes through (asking for route/
            # destination ideas before ever discussing a flight), not only
            # the usual last one after a flight search. Seen live: a customer
            # who planned Cyprus's itinerary first got told "great, itinerary
            # approved" with only lodging/car offered next - flights was
            # silently skipped entirely, because this reply used to hardcode
            # "לינה או השכרת רכב" unconditionally regardless of what was
            # actually still pending.
            statuses_after_plan = trip_update.get("session_status") if isinstance(trip_update.get("session_status"), dict) else {}
            remaining_labels = {"flights":"טיסות", "lodging":"לינה", "car":"השכרת רכב"}
            remaining = [
                remaining_labels[s] for s in ("flights","lodging","car")
                if statuses_after_plan.get(s, "pending") not in ("complete","declined")
            ]
            if remaining:
                if len(remaining) == 1:
                    extra = remaining[0]
                else:
                    extra = " או ".join([", ".join(remaining[:-1]), remaining[-1]])
                reply = f"מצוין, המסלול מאושר. תרצי שאמשיך גם עם {extra} לחופשה הזו, או שסיימנו?"
            else:
                reply = "מצוין, המסלול מאושר."

        # Never let the conversation claim it is ready for a final summary when
        # the structured source of truth is missing required facts. This keeps
        # the visible summary and downstream execution on the same data object.
        trip_update = _advance_sessions(trip_update)

        # Search approval is a system event, not a language-model decision.
        approval = _approval_trigger(message, history, trip_state)
        # A typo that resembles approval must never produce a false "search started"
        # message. Keep the hard execution gate exact, and ask for the exact word.
        if not approval and _looks_like_approval_typo(message, trip_state):
            gender = str((trip_state or {}).get("user_gender") or "").lower()
            if gender == "male":
                reply = "לא הבנתי, האם התכוונת לאשר? אם כן, כתוב מאשר."
            elif gender == "female":
                reply = "לא הבנתי, האם התכוונת לאשר? אם כן, כתבי מאשרת."
            else:
                reply = "לא הבנתי, האם התכוונת לאשר? אם כן, יש לכתוב מאשר/מאשרת."
        # Deceptive-success safety net: the prompt tells Tinkerbell that once the
        # summary was already shown and the customer answers affirmatively, it
        # should "briefly confirm the request was received and proceed to
        # execution" - free text, written on the assumption that the real
        # deterministic approval gate (_approval_trigger, above) actually fired
        # this turn. Seen live TWICE, with two different phrasings each time
        # ("הבקשה יוצאת עכשיו לחיפוש... אחזור אלייך עם התוצאות", then later
        # "אני שולחת אותה לסריקה ונחזור אלייך עם התוצאות") - free text has
        # endless equivalent phrasings, so matching a fixed list of exact
        # phrases missed the second one entirely. Detect it instead as a
        # co-occurrence of an action verb ("שולחת/יוצאת/התחלתי/נשלח/נקלט"...)
        # with a search/results noun ("לחיפוש/לסריקה/תוצאות"...) anywhere in
        # the reply - robust to whichever way the model phrases the same claim.
        elif not approval:
            action_verbs = (
                "יוצאת","יוצא","שולחת","שולח","נשלח","נשלחה","התחלתי",
                "מתחילה","מתחיל","נקלט","נקלטה","ממשיכה","ממשיך","מעבדת","מעבד",
            )
            action_targets = ("לחיפוש","לסריקה","סריקת טיסות","בסריקה","בחיפוש","תוצאות")
            claims_execution = (
                any(v in str(reply or "") for v in action_verbs)
                and any(t in str(reply or "") for t in action_targets)
            )
            if claims_execution:
                # If a real required fact is still missing, the honest and
                # useful reply is the actual pending question - not a vague
                # "just retype מאשרת", which is actively misleading here: a
                # gap means retyping מאשרת alone will not start anything, and
                # telling her to do that is exactly what produced the next
                # false claim in the same live transcript.
                gap_question = _flight_gap_question(_session_gaps(trip_update, "flights"))
                if gap_question:
                    reply = gap_question
                else:
                    gender = str((trip_state or {}).get("user_gender") or "").lower()
                    if gender == "male":
                        reply = "עדיין לא יצאתי לחיפוש בפועל - צריך לכתוב בדיוק את המילה מאשר כדי להתחיל."
                    elif gender == "female":
                        reply = "עדיין לא יצאתי לחיפוש בפועל - צריך לכתוב בדיוק את המילה מאשרת כדי להתחיל."
                    else:
                        reply = "עדיין לא יצאתי לחיפוש בפועל - צריך לכתוב בדיוק את המילה מאשר/מאשרת כדי להתחיל."
        # A generic "yes" during normal data collection is NEVER a search approval.
        # It must only approve an explicit final approval question / ready state.
        msg_norm = _normalize_confirm(message).lower()
        generic_yes = msg_norm in {"כן","נכון","מעולה","מצוין","מצויין","סבבה","אחלה","נשמע טוב","נשמע אחלה"}
        if generic_yes and not approval:
            # Do not let extractor/model turn this ordinary conversational answer
            # into search intent or missing-data validation.
            trip_update["search_intent"] = bool(trip_state.get("search_intent"))
            trip_update["search_confirmed"] = bool(trip_state.get("search_confirmed"))
            trip_update["ready_for_summary"] = bool(trip_state.get("ready_for_summary"))
        if approval:
            merged = _merge_trip_state(trip_state, trip_update if isinstance(trip_update, dict) else {})
            # Flight approval closes only session 1. Keep the shared trip facts and
            # leave lodging/car/planning available for continuation after the scan.
            statuses_after_flight = dict(merged.get("session_status") or {})
            statuses_after_flight["flights"] = "complete"
            # Flight approval must not erase prior service decisions. Pending stays
            # pending, completed stays completed, and an explicit decline stays declined.
            for optional_service in ("lodging","car","trip_planning"):
                statuses_after_flight.setdefault(optional_service, "pending")
            merged["session_status"] = statuses_after_flight
            merged["active_session"] = None
            merged["post_flight_continuation"] = True
            # Approval must execute exactly the dates the customer already approved.
            # The extractor response to the word מאשרת must never erase/replace them.
            if isinstance(trip_state.get('dates'), dict) and trip_state.get('dates', {}).get('departure') and trip_state.get('dates', {}).get('return'):
                merged['dates'] = dict(trip_state['dates'])
            # Never approve/launch a scan while a required flight fact is still
            # missing. Ask for that fact first, then summarize and request approval again.
            approval_gaps = _session_gaps(merged, "flights")
            if approval_gaps:
                merged["search_intent"] = True
                merged["search_confirmed"] = False
                merged["ready_for_summary"] = False
                merged["session_status"] = dict(merged.get("session_status") or {})
                merged["session_status"]["flights"] = "active"
                merged["active_session"] = "flights"
                trip_update = merged
                # Every gap _session_gaps can actually return for "flights" needs
                # its own specific question here. A generic fallback ("one
                # detail is missing") leaves the customer with no way to know
                # what to answer - seen live: she got exactly that generic
                # line, asked "מה עכשיו?" (what now?), and had no way forward
                # other than guessing.
                reply = _flight_gap_question(approval_gaps)
                approval = False
            else:
                # This whole branch used to end here, with everything below it
                # (search_confirmed=True, the "approved" reply, etc.) sitting
                # OUTSIDE this else at the same indent as the if/else itself -
                # so it ran unconditionally no matter which branch had just
                # executed. That silently undid the approval_gaps branch above:
                # a customer told "כתבי מאשרת" was accepted and a scan was
                # starting even when a required flight fact (destination
                # airport, budget, etc.) was still genuinely missing, which
                # then made the actual /start-flight-search call fail with an
                # unrelated-looking error instead of asking the missing
                # question in the first place. All of this must only run when
                # approval_gaps was actually empty.
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
                # The approval turn must not ask any more flight questions. It is a
                # deterministic handoff message; the browser keeps it visible for 4s
                # before opening the scan.
                remaining_labels = {
                    "lodging":"לינה", "car":"השכרת רכב", "trip_planning":"מסלול ואטרקציות"
                }
                # Reassure about a domain the customer might still want even if
                # they already said no to it earlier (declined), not only one
                # that's still pending - "you can always come back" is exactly
                # as true either way. The one exception is trip_planning when a
                # business/ski trip_type default silently declined it without
                # ever asking - that was never the customer's own decision to
                # revisit, and mentioning it here would be confusing.
                decisions_after_flight = merged.get("service_decisions") if isinstance(merged.get("service_decisions"), dict) else {}
                def _auto_declined_by_trip_type(service):
                    d = decisions_after_flight.get(service)
                    source = d.get("source") if isinstance(d, dict) else None
                    return source in ("business_trip_default", "ski_trip_default")
                remaining = [
                    remaining_labels[s] for s in ("lodging","car","trip_planning")
                    if statuses_after_flight.get(s, "pending") in ("pending", "declined")
                    and not _auto_declined_by_trip_type(s)
                ]
                if remaining:
                    if len(remaining) == 1:
                        extra = remaining[0]
                    else:
                        extra = " או ".join([", ".join(remaining[:-1]), remaining[-1]])
                    reply = (
                        "הבקשה אושרה ואני יוצאת לסריקת טיסות. "
                        f"כשתרצי, אפשר לחזור לכאן ולהמשיך עם {extra}."
                    )
                else:
                    reply = "הבקשה אושרה ואני יוצאת לסריקת טיסות. אעדכן אותך כשהתוצאות יהיו מוכנות."
    except Exception as exc:
        logging.exception("ariella chat-clean pipeline failed: %s", exc)
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503

    if not isinstance(trip_update, dict):
        trip_update = {}
    try:
        persist_trip_plan = bool(locals().get("planning_accept", False)) \
            and bool((trip_update.get("dates") or {}).get("departure")) \
            and bool((trip_update.get("dates") or {}).get("return"))
    except Exception:
        logging.exception("persist_trip_plan computation failed; defaulting to False")
        persist_trip_plan = False
    try:
        start_flight_search = bool(approval) and bool(trip_update.get('search_confirmed'))
    except Exception:
        logging.exception("start_flight_search computation failed; defaulting to False")
        start_flight_search = False
    profile_for_response = trip_update.get('profile')

    # Once all four service domains (flights/lodging/car/trip_planning) have
    # each reached a final answer - complete OR declined, either way - the
    # vacation is unambiguously done. Nothing about it should leak into
    # whatever the customer asks for next (a real bug: a couple with a
    # 17-year-old daughter carried over into a new trip as a 17-year-old son,
    # because the old structured state was never actually cleared). This is
    # deliberately silent - no "delete everything?" gate - because completion
    # is already certain once every domain answered either way; that gate
    # exists for the ambiguous case where the customer might still be
    # mid-trip, which this is not.
    # Defensive: this reset must never be allowed to crash the whole request.
    # Whatever shape trip_update happens to be in, the worst acceptable outcome
    # is skipping the reset for this turn, never a 500 that blocks the chat.
    trip_state_reset = False
    try:
        final_statuses = trip_update.get("session_status") if isinstance(trip_update.get("session_status"), dict) else {}
        final_decisions = trip_update.get("service_decisions") if isinstance(trip_update.get("service_decisions"), dict) else {}
        # flights="complete" means only that every required field is filled and
        # the summary/approval prompt is ready to show - NOT that the customer
        # has actually approved yet (that only happens inside the explicit
        # "מאשר/מאשרת" gate, which sets post_flight_continuation). Treating
        # "complete" alone as resolved here wiped the whole trip state the
        # instant flights became data-complete whenever lodging/car/
        # trip_planning already happened to be declined too (e.g. a business
        # trip, where trip_planning auto-declines) - before the customer ever
        # got to see the summary or approve, silently discarding
        # destination/dates/everything and breaking the actual search.
        flights_resolved = bool(trip_update.get("post_flight_continuation")) or final_statuses.get("flights") == "declined"
        other_domains_resolved = all(
            final_statuses.get(s) in ("complete", "declined")
            or ((final_decisions.get(s) or {}).get("wanted") is False if isinstance(final_decisions.get(s), dict) else final_decisions.get(s) is False)
            for s in ("lodging", "car", "trip_planning")
        )
        trip_fully_resolved = flights_resolved and other_domains_resolved
        if trip_fully_resolved:
            trip_state_reset = True
            fresh_after_completion = {
                'session_status': {'flights': 'pending', 'lodging': 'pending', 'car': 'pending', 'trip_planning': 'pending'},
                'active_session': None,
            }
            # Member-level facts (not trip facts) survive the reset - no need to
            # re-ask gender for the next vacation.
            if trip_update.get('profile'):
                fresh_after_completion['profile'] = trip_update['profile']
            if trip_update.get('user_gender'):
                fresh_after_completion['user_gender'] = trip_update['user_gender']
            trip_update = fresh_after_completion
    except Exception:
        logging.exception("Auto-reset-on-completion check failed; leaving trip_update untouched")
        trip_state_reset = False

    # Server-side copy of the conversation so it survives logout and follows
    # the account across devices, not just this browser's local cache.
    try:
        saved_history = list(history) + [
            {'role': 'user', 'content': message},
            {'role': 'assistant', 'content': reply or 'אני איתך 😊'},
        ]
        save_ariella_conversation(session['member_id'], saved_history[-80:], trip_update)
    except Exception:
        logging.exception("Failed to persist Ariella conversation for member %s", session.get('member_id'))

    return jsonify({
        'status': 'success',
        'agent': 'Tinkerbell',
        'engine_version': ENGINE_VERSION,
        'reply': reply or 'אני איתך 😊',
        'trip_update': trip_update,
        'profile': profile_for_response,
        # Save only an itinerary approved against the current structured state.
        'persist_trip_plan': persist_trip_plan,
        # Execution is allowed only when the deterministic approval gate fired
        # on THIS user message. Never let model-extracted state start a scan.
        'start_flight_search': start_flight_search,
        'trip_state_reset': trip_state_reset,
    })
