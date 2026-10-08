# משימת פיתוח 003א — "הדילים החמים" בוואטסאפ: הודעת ברכה + כפתור "הפסקת הדילים"

תוכנית: [003 — וואטסאפ אחד בלי בלאגן](../plans/003-whatsapp-one-inbox.md) — **אושר חלקית: הודעת ברכה + כפתור הפסקה**
נוצרה: 2026-10-08 · עודכנה: 2026-10-08 (לפי בעלת העסק: **כפתור בלבד, בלי מילת "עצור"**)
מצב: לכתוב את הקוד עכשיו; **ההפעלה מול לקוחות — רק אחרי שהוואטסאפ מחובר ותבניות ההודעה אושרו ב-Meta**.

## המטרה
1. מיד אחרי אישור התשלום של 9 ₪ ל"הדילים לפני כולם" — הלקוח מקבל בוואטסאפ **הודעת ברכה** עם כפתור "הפסקת הדילים".
2. בכל הודעת דילים יומית — **כפתור "הפסקת הדילים"** בסוף ההודעה (באותה הודעה, לא בהודעה נפרדת).
3. לחיצה על הכפתור מפסיקה את השירות. אין מילת מפתח בטקסט.
4. חידוש אחרי הפסקה = **תשלום חד־פעמי חדש של 9 ₪** באתר (לא מנוי; בהודעות ללקוח לא להשתמש במילה "מנוי").

## מה קיים היום
- הצטרפות/הפסקה באתר: `whatsapp_opt_in()` (public_site.py:2267) → `members.whatsapp_opt_in`, `whatsapp_opt_in_at`; מתג בעמוד הדילים (templates/deals.html:6), מוצר `whatsapp_deals_9`.
- מקבלי דילים: `members_to_notify_on_whatsapp()` (database.py:1712) מסנן לפי `whatsapp_opt_in=1`.
- שליחה: `whatsapp.send_text_message` (whatsapp.py:80) — טקסט בלבד, בלי כפתורים ובלי תבניות.
- ניתוב נכנסות: `nova_conversation.route_inbound(phone, text, profile_name)` (nova_conversation.py:374). ה-webhook (whatsapp.py:74–77) עדיין לא קורא לו — החיבור **לא** חלק מהמשימה.
- נוסח הדילים היומי: `formatter.build_daily_message` (formatter.py:66).

## שינויים

### 1. מסד נתונים (database.py — בבלוק המיגרציות של `members`, ליד שורות 394–397)
```python
if "whatsapp_opt_out_at" not in member_columns:
    conn.execute("ALTER TABLE members ADD COLUMN whatsapp_opt_out_at TEXT")
if "whatsapp_opt_out_source" not in member_columns:
    conn.execute("ALTER TABLE members ADD COLUMN whatsapp_opt_out_source TEXT")
if "whatsapp_welcome_sent_at" not in member_columns:
    conn.execute("ALTER TABLE members ADD COLUMN whatsapp_welcome_sent_at TEXT")
```
```sql
CREATE TABLE IF NOT EXISTS whatsapp_opt_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    event TEXT NOT NULL,          -- 'opt_in' | 'opt_out'
    source TEXT NOT NULL,         -- 'site' | 'payment' | 'whatsapp_button'
    created_at TEXT NOT NULL,
    FOREIGN KEY(member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_whatsapp_opt_events_member ON whatsapp_opt_events(member_id, id DESC);
```
(התיעוד נדרש כרשומת הסכמה/ביטול לפי חוק התקשורת, סעיף 30א.)

### 2. פונקציה משותפת (database.py)
`set_whatsapp_deals_opt(member_id: int, enabled: bool, source: str) -> bool`
- מעדכנת `whatsapp_opt_in`, `whatsapp_opt_in_at`; בהפסקה גם `whatsapp_opt_out_at`, `whatsapp_opt_out_source`.
- רושמת שורה ב-`whatsapp_opt_events`. מחזירה `True` אם המצב השתנה.
- להחליף בה את ה-UPDATE הישיר ב-`whatsapp_opt_in()` (public_site.py:2274), בלי לשנות את ההתנהגות באתר.

### 3. הודעת ברכה אחרי אישור תשלום
- נקודת החיבור: הרגע שבו `whatsapp_opt_in` עובר ל-1 **אחרי אישור תשלום** של `whatsapp_deals_9` (היום — מסלול האישור המדומה/ידני הקיים; בעתיד — אישור מספק הסליקה). פונקציה אחת: `on_whatsapp_deals_paid(member_id)` שקוראת ל-`set_whatsapp_deals_opt(..., True, 'payment')` ואז ל-`queue_whatsapp_welcome(member_id)`.
- `queue_whatsapp_welcome`: אם `whatsapp_welcome_sent_at` ריק **או** קטן מ-`whatsapp_opt_in_at` (הצטרפות מחדש) → בונה הודעה ושולחת; מעדכנת `whatsapp_welcome_sent_at`.
- **נוסח** (פנייה ניטרלית, ברבים):
  > 🎉 *איזה כיף שהצטרפתם!*
  > מעכשיו, פעם ביום, אריאלה תשלח לכם לכאן את הדילים הכי שווים שמצאה — טיסות מנתב"ג במחיר אמיתי, כולל מזוודה.
  > ✈️ הדילים מגיעים בימים א'–ה' (לא בשבת).
  > 💬 ובכל רגע אפשר פשוט לכתוב לאריאלה ולתכנן חופשה.
  > רוצים להפסיק? לחיצה אחת על הכפתור למטה 👇
  > [הפסקת הדילים]
  (ימי השליחה — לפי `schedule_rules.delivery_status`; לבדוק שהנוסח תואם לכלל בפועל לפני ההגשה.)
- ההודעה היא יזומה → נשלחת כתבנית (template) עם כפתור quick reply. עד שיש תבנית מאושרת: לשמור את ההודעה בתור/לוג ולהציג תצוגה מקדימה במסך המנהל — **לא לשלוח**.

### 4. כפתור בכל הודעת דילים יומית
- תבנית הדילים היומית תכלול בסוף כפתור quick reply: טקסט `הפסקת הדילים`, payload `STOP_HOT_DEALS`.
- `build_daily_message` נשאר לגוף ההודעה; להוסיף פונקציה `build_daily_whatsapp_payload(deals)` שמחזירה גוף + רשימת כפתורים (לשימוש בשליחה כשתחובר).
- להוסיף ל-whatsapp.py פונקציה `send_template_message(recipient, template_name, body_params, buttons)` — מוכנה, אבל לא נקראת עד החיבור.

### 5. טיפול בלחיצה על הכפתור
- להוסיף ל-`route_inbound` פרמטר `button_payload: str | None = None`, ולבדוק אותו **לפני** כל ניתוב אחר.
- `button_payload == 'STOP_HOT_DEALS'` → `_handle_stop(phone)`:
  - מזהה לקוח: `linked_member_for_phone` ואם אין — `registered_member_for_phone`. **לא** פותח onboarding ולא יוצר משתמש.
  - שירות פעיל → `set_whatsapp_deals_opt(member_id, False, 'whatsapp_button')` ותשובה:
    > ✔️ *הפסקנו לשלוח לכם את הדילים החמים.*
    > תמיד אפשר להצטרף שוב מעמוד הדילים באתר (תשלום חד־פעמי של 9 ₪): {קישור מלא ל-/deals}
    > והשיחה עם אריאלה ממשיכה כרגיל — כתבו מתי שרוצים 🌷
  - כבר לא פעיל → "הדילים החמים כבר לא נשלחים אליכם. אפשר להצטרף שוב מעמוד הדילים באתר (תשלום חד־פעמי של 9 ₪): {קישור}"
  - לא נמצא לקוח → "לא מצאנו שירות דילים פעיל במספר הזה. אם נרשמתם עם מספר אחר — אפשר להפסיק מעמוד הדילים באתר."
  - אם יש חופשה עם מעקב בתשלום פעיל (`subscription_status='active'`, `mobile_notifications=1`) — להוסיף: "עדכוני החופשה שלכם ממשיכים. להפסקה — בכרטיס החופשה באתר."
  - לא משנה את `whatsapp_conversation_state`, את קישור הוואטסאפ לחשבון, או את `mobile_notifications`.
- payload לא מוכר → מתעלמים וממשיכים לניתוב הרגיל.
- **אין** זיהוי מילים כמו "עצור" בטקסט (החלטת בעלת העסק).

### 6. מתג הפעלה
`WHATSAPP_DEALS_BUTTONS_ENABLED` ב-config.py (ברירת מחדל `false` עד אישור התבניות). כש-`false`: לא שולחים ברכה/כפתורים בפועל — רק תור ותצוגה מקדימה במסך המנהל.

## קריטריוני קבלה
1. אישור תשלום מדומה ל-`whatsapp_deals_9` → `whatsapp_opt_in=1`, שורת `opt_in/payment`, והודעת הברכה מופיעה בתצוגה המקדימה במסך המנהל (ולא נשלחת כשהמתג `false`).
2. הצטרפות מחדש אחרי הפסקה ותשלום נוסף → הודעת ברכה חדשה. אישור כפול של אותו תשלום → **לא** שולח ברכה פעמיים.
3. `build_daily_whatsapp_payload` מחזיר כפתור `הפסקת הדילים` עם payload `STOP_HOT_DEALS`.
4. `route_inbound(phone, '', button_payload='STOP_HOT_DEALS')` משירות פעיל → `whatsapp_opt_in=0`, `whatsapp_opt_out_source='whatsapp_button'`, שורה ב-`whatsapp_opt_events`, והתשובה המלאה עם קישור.
5. אחרי זה הלקוח לא מופיע ב-`members_to_notify_on_whatsapp()`.
6. לחיצה שנייה → תשובת "כבר לא נשלחים", בלי שורת opt_out נוספת.
7. מספר לא מוכר לוחץ → תשובת "לא מצאנו", בלי onboarding ובלי יצירת משתמש.
8. לקוח עם מעקב חופשה פעיל → מקבל את השורה על עדכוני החופשה; `mobile_notifications` לא משתנה.
9. הודעת טקסט "עצור" **לא** מפסיקה את השירות (ממשיכה לניתוב הרגיל).
10. המתג באתר ממשיך לעבוד, ונרשמת שורת `source='site'`.
11. מיגרציה רצה פעמיים על מסד קיים בלי שגיאה.

## בדיקות QA
- סקריפט ב-tools/ (בסגנון הקיים) על DB זמני: תשלום → ברכה; לחיצה מלקוח פעיל / לא פעיל / עם חופשה במעקב / מספר לא מוכר; הצטרפות מחדש.
- בדיקה ידנית: מתג באתר, תצוגה מקדימה במסך המנהל, שורות `whatsapp_opt_events`.
- דוח QA_REPORT בסגנון הקיים.

## מחוץ להיקף
- חיבור ה-webhook ל-`route_inbound` ושליחה בפועל; הגשת התבניות ל-Meta.
- חיבור ספק סליקה אמיתי.
- תור הודעות, מיזוג רדאר + דילים, תמונות, קיצור הדילים — שאר תוכנית 003 (טרם אושר).
