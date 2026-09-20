import json
import logging
import os
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, request
from travel_agents import _conversation

ariella_chat_clean = Blueprint('ariella_chat_clean', __name__)
ENGINE_VERSION = 'tinkerbell-chat-v34'

TINKERBELL_SYSTEM = '''את מלוות החופשה של אריאלה. אריאלה כבר פתחה את השיחה; מכאן את משוחחת עם הלקוח באופן חופשי וטבעי עד שלב ההזמנה.

התפקיד היחיד שלך כאן הוא לנהל שיחה מצוינת. אין לך טופס למלא ואין לך רשימת פרטים להשלים.
- את טינקרבל: את מנהלת את השיחה בלבד. שכבת חילוץ נפרדת מאזינה לשיחה ומעבירה את העובדות לאריאלה. אריאלה מחזירה לך missing_required כרשימת הדברים שעוד צריך לברר; השתמשי בה כדי לבחור את 1–3 השאלות הבאות באופן טבעי, בלי להציג שמות שדות פנימיים ללקוח.
- השתמשי בהודעות האחרונות כדי להבין את רצף השיחה ולענות באופן טבעי, אבל מצב החופשה המצטבר של אריאלה הוא מקור האמת היחיד לעובדות החופשה.
- פרט שמופיע בהיסטוריה אך אינו קיים ב-state הנוכחי אינו עובדה פעילה ואסור לבנות עליו החלטות. אחרי איפוס, מידע מחופשה קודמת אינו שייך לחופשה החדשה.
- אל תשאלי שוב פרט שכבר קיים במצב החופשה המצטבר.
- דברי כמו שיחת ChatGPT טובה: טבעית, חמה, חכמה וקצרה.
- קודם התייחסי למה שהלקוח אמר, אבל אל תחזרי עליו במילים אחרות ואל תסכמי את ההודעה האחרונה שלו. אם אין צורך בתגובה מהותית, המשיכי ישירות לנקודה הבאה.
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
- בסיכום הסופי הציגי את כל ארבעת התחומים. תחום שהלקוח בחר יוצג עם הפרטים הרלוונטיים; תחום שסומן declined יוצג בקצרה כ"לא נדרש" (למשל "רכב שכור: לא נדרש"). כך הלקוח יכול לוודא שגם החלטות שליליות נקלטו נכון.
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
- בכל הודעה מותר לבקש מהלקוח לכל היותר שלושה פרטים/החלטות שונים. זהו גבול קשיח, לא המלצה.
- כל סעיף שהלקוח צריך לענות עליו נחשב שאלה נפרדת גם אם ניסחת כמה סעיפים בתוך משפט אחד. לדוגמה: "ישירה או קונקשן, מזוודה לכל נוסע, מלון או דירה, ובאיזו רמה?" הן ארבע שאלות ואסור לשלוח אותן יחד.
- אם חסרים יותר משלושה פרטים, בחרי את 1–3 הפרטים שהכי טבעי לברר עכשיו, המתיני לתשובה, ורק בהודעה הבאה שאלי את היתר.
- אל תצרפי לשאלה שלוש שאלות ואז תוסיפי בסוף עוד בחירה או שאלה "קטנה". סך כל הדברים שמבקשים מהלקוח להחליט או למסור בהודעה אחת הוא עד שלושה.
- לטיסות, בדקי בין היתר רק כשחסר ורלוונטי: תקציב לאדם, כבודה, ישירה/קונקשן, מוצא ותאריכים. אם הלקוח אמר שאין תקציב/אין הגבלת תקציב, זו תשובה מלאה לשאלת התקציב ואסור לשאול שוב תקציב לטיסה.
- ללינה, בדקי רק כשחסר ורלוונטי: סוג לינה (מלון/וילה/דירה), מספר/הרכב חדרים, רמת לינה או תקציב לאדם, מיקום ודרישות מהותיות לחיפוש.
- לרכב, בדקי רק כשחסר ורלוונטי: מספר נוסעים, מקום לכבודה, סוג/גודל רכב, נקודת וזמן איסוף והחזרה.
- לתכנון מסלול ואטרקציות, בדקי רק כשחסר ורלוונטי: אופי החופשה, קצב, מגבלות נסיעה ודברים שחייבים/לא רוצים.
- אל תשאלי שוב שום פרט שכבר נאמר בשיחה או קיים במצב החופשה המצטבר. בפרט, ניסוח כמו 'ראשון עד חמישי' כבר קובע את אורך החופשה (4 לילות/5 ימים); אסור לשאול אחר כך 'כמה ימים'. אם נאמר גם חודש/טווח כמו 'באפריל אחרי ה-15', חשבי את התאריכים האפשריים מתוך המגבלה במקום לבקש שוב משך.
- היי סלחנית לשגיאות כתיב ברורות לפי ההקשר. אם שאלת על תקציב ונכתב למשל "ללא תקציר", אפשר להבין "ללא תקציב"; אם יש יותר מפירוש סביר אחד, שאלי הבהרה קצרה.
- בביטוי יחסי כמו "סוף יוני" יחד עם ימי שבוע/משך, אל תבחרי תאריך אחד בשם הלקוח. אם יש שתי אפשרויות סבירות סמוכות, הציגי את שתיהן ושאלי איזו עדיפה. רק אחרי בחירת הלקוח יש תאריכי יציאה וחזרה סופיים.
- אסור להגיע לסיכום או לבקש מאשר/מאשרת כאשר dates עדיין דורש בחירה/אישור.
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
- ה-state שקיבלת הוא הזיכרון היחיד. אסור לשחזר עובדות מהודעות קודמות שאינן נמצאות בו.
- session_status כולל תמיד flights/lodging/car/trip_planning, וכל אחד הוא pending/active/complete/declined. אל תסמני complete רק כי הלקוח הזכיר את התחום; אריאלה מחשבת השלמה לפי שדות החובה.
- active_session הוא הסשן היחיד שטינקרבל משלימה כעת.
- אם הלקוח משנה פרט, החליפי רק את אותו פרט. לדוגמה: "במקום מונטנגרו יוון" מחליף destination בלבד; שינוי תאריכים מחליף dates בלבד.
- אל תמציאי ואל תנחשי. ערך חסר נשאר חסר.
- תקני סמנטית שגיאת כתיב ברורה רק כשההקשר חד-משמעי. למשל תשובה "ללא תקציר" לשאלת תקציב = budget_per_person.status="unlimited".
- אין לאסוף או לשמור מחלקת טיסה (תיירים/פרימיום/עסקים). החיפוש מציג את אפשרויות הכרטיס הרלוונטיות והלקוח יבחר בהמשך.
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
  "flight":{"connection_preference":null,"max_connections":null,"baggage":[],"preferences":[]},
  "priorities":[],"hard_constraints":[],"current_request":null,
  "search_intent":false,"requested_services":[],"service_decisions":{},
  "session_status":{"flights":"pending","lodging":"pending","car":"pending","trip_planning":"pending"},
  "active_session":null,
  "missing_required":[],"ready_for_summary":false,"search_confirmed":false,
  "lodging":{"interested":"unknown","details":{}},
  "car":{"interested":"unknown","details":{}},
  "trip_planning":{"interested":"unknown","details":{}}
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


def _post_openai(key, model, system_prompt, history, message, max_tokens, include_history=True):
    payload = {
        'model': model,
        'input': [{'role': 'developer', 'content': system_prompt}] + _conversation(history[-16:] if include_history else [], message),
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
            if statuses[s] == "pending":
                statuses[s] = "active"

    # A destination/trip request implies flights unless explicitly declined.
    dest = state.get("destination") if isinstance(state.get("destination"), dict) else {}
    fd = decisions.get("flights")
    fw = fd.get("wanted") if isinstance(fd, dict) else fd
    if dest.get("places") and fw is not False:
        services.add("flights")
        if statuses["flights"] == "pending":
            statuses["flights"] = "active"

    # Keep one active session. Respect an existing unfinished active session first.
    active = state.get("active_session")
    if active not in statuses or statuses.get(active) in ("complete","declined"):
        active = None
    if not active:
        active = next((s for s in ("flights","lodging","car","trip_planning") if statuses[s] == "active"), None)

    state["requested_services"] = list(dict.fromkeys(list(state.get("requested_services") or []) + list(services)))
    state["session_status"] = statuses
    state["active_session"] = active
    return state


def _session_gaps(state, session):
    """Required facts for one session only."""
    all_gaps = _required_state_gaps(state)
    prefixes = {
        "flights": ("destination","dates","travelers","departure_airport","flight.","budget_per_person"),
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
    if services and not (destination.get("places") or []):
        gaps.append("destination")
    if services and (dates.get("needs_confirmation") or not (dates.get("departure") and dates.get("return"))):
        gaps.append("dates")
    if services and travelers.get("adults") is None:
        gaps.append("travelers")

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
        if not flight.get("connection_preference"):
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
    return _post_openai(key, model, system, history, message, 1500, include_history=True).strip()


def _extract_trip_update(key, model, history, message, state=None):
    try:
        system = EXTRACTOR_SYSTEM + '\nמצב החופשה המצטבר לפני ההודעה הנוכחית:\n' + _state_context(state) + '\nהתאריך הנוכחי: ' + date.today().isoformat()
        raw = _post_openai(key, model, system, [], message, 900, include_history=False)
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
                'trip_update':{'session_status':{'flights':'pending','lodging':'pending','car':'pending','trip_planning':'pending'},'active_session':None},'start_flight_search':False,'trip_state_reset':True
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

    # Destination replacement is the only ordinary field change that requires
    # confirmation because route/lodging/car destination-dependent facts become stale.
    import re
    known_destinations = ("יוון","מונטנגרו","איטליה","בולגריה","אלבניה","קרואטיה","תאילנד")
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
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return jsonify({'status': 'error', 'message': 'טינקרבל לא זמינה כרגע.', 'engine_version': ENGINE_VERSION}), 503
    model = os.getenv('ARIELLA_MODEL', 'gpt-5.6-luna').strip()

    try:
        # Tinkerbell's data-transfer pass tells Ariella what changed.
        # Ariella owns and merges the cumulative state.
        extracted = _extract_trip_update(key, model, history, message, trip_state)
        trip_update = _merge_trip_state(trip_state, extracted)
        trip_update = _merge_trip_state(trip_update, _deterministic_budget_facts(message))
        trip_update = _merge_trip_state(trip_update, _deterministic_traveler_facts(message))
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

        # Ariella, not chat history, owns the four-session progression.
        trip_update = _advance_sessions(trip_update)

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
        trip_update = _advance_sessions(trip_update)

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
