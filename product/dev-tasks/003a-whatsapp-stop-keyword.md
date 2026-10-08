# משימת פיתוח 003א — סיום שירות "הדילים החמים" במילה בוואטסאפ ("עצור")

תוכנית: [003 — וואטסאפ אחד בלי בלאגן](../plans/003-whatsapp-one-inbox.md) — **אושר חלקית: רק מילת הסיום**
נוצרה: 2026-10-08
מצב: לכתוב את הקוד עכשיו; **ההפעלה מול לקוחות — רק אחרי שה-webhook של וואטסאפ מחובר** (לפי בעלת העסק).

## המטרה
לקוח שהצטרף ל"הדילים לפני כולם" (9 ₪ חד־פעמי, דיל יומי לנייד עד שמפסיקים) יכול להפסיק את השירות גם בכתיבת מילה אחת בוואטסאפ — לא רק מהמתג באתר (`/whatsapp-opt-in`, public_site.py:2267; templates/deals.html:6).

## מה קיים היום
- הפסקה באתר: `whatsapp_opt_in()` → `UPDATE members SET whatsapp_opt_in=0, whatsapp_opt_in_at=NULL`.
- מקבלי דילים: `members_to_notify_on_whatsapp()` (database.py:1712) מסנן לפי `whatsapp_opt_in=1`.
- ניתוב הודעות נכנסות: `nova_conversation.route_inbound(phone, text, profile_name)` (nova_conversation.py:374) — מחזיר טקסט תשובה.
- ה-webhook ב-whatsapp.py:74–77 עדיין לא קורא ל-`route_inbound` (זה החיבור שיגיע בהמשך — **לא חלק מהמשימה**).
- נוסח הדילים היומי: `formatter.build_daily_message` (formatter.py:66).

## שינויים

### 1. מסד נתונים (database.py, בבלוק המיגרציות של `members`, ליד שורות 394–397)
```python
if "whatsapp_opt_out_at" not in member_columns:
    conn.execute("ALTER TABLE members ADD COLUMN whatsapp_opt_out_at TEXT")
if "whatsapp_opt_out_source" not in member_columns:
    conn.execute("ALTER TABLE members ADD COLUMN whatsapp_opt_out_source TEXT")
```
וטבלת תיעוד (נדרש כרשומה להסכמה/ביטול לפי חוק התקשורת):
```sql
CREATE TABLE IF NOT EXISTS whatsapp_opt_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    event TEXT NOT NULL,          -- 'opt_in' | 'opt_out'
    source TEXT NOT NULL,         -- 'site' | 'whatsapp_keyword'
    raw_text TEXT,                -- המילה שהלקוח כתב (עד 40 תווים)
    created_at TEXT NOT NULL,
    FOREIGN KEY(member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_whatsapp_opt_events_member ON whatsapp_opt_events(member_id, id DESC);
```

### 2. פונקציה משותפת לביטול (database.py)
`set_whatsapp_deals_opt(member_id: int, enabled: bool, source: str, raw_text: str | None = None) -> bool`
- מעדכנת `whatsapp_opt_in`, `whatsapp_opt_in_at` (כמו היום), ובביטול גם `whatsapp_opt_out_at=utc_now_iso()` ו-`whatsapp_opt_out_source=source`.
- רושמת שורה ב-`whatsapp_opt_events`.
- מחזירה `True` אם המצב השתנה, `False` אם כבר היה במצב המבוקש.
- **להחליף** את ה-UPDATE הישיר ב-`whatsapp_opt_in()` (public_site.py:2274) בקריאה לפונקציה הזו עם `source='site'` — בלי לשנות את ההתנהגות באתר.

### 3. זיהוי מילת הסיום (nova_conversation.py)
`STOP_KEYWORDS = {"עצור", "הפסק", "הסר", "הסירו", "הסר אותי", "הפסק דילים", "בלי דילים", "ביטול דילים", "stop", "unsubscribe"}`

`_is_stop_command(text) -> bool`:
- נרמול: strip, lower, הסרת סימני פיסוק ואימוג'י בקצוות, איחוד רווחים.
- **התאמה להודעה כולה בלבד** — לא "מכיל". "אל תעצרי את החיפוש" או "תפסיקי לחפש לי מלון" **לא** מבטלים את השירות.

### 4. ניתוב — בראש `route_inbound`, לפני כל לוגיקה אחרת
```python
if _is_stop_command(text):
    return _handle_stop(phone, text)
```
`_handle_stop`:
- מזהה לקוח: `linked_member_for_phone(phone)` ואם אין — `registered_member_for_phone(phone)`. **לא** פותח onboarding ולא יוצר משתמש.
- אין לקוח → "לא מצאתי מנוי לדילים במספר הזה. אם נרשמתם עם מספר אחר — אפשר להפסיק מעמוד הדילים באתר."
- לקוח עם `whatsapp_opt_in=1` → `set_whatsapp_deals_opt(member_id, False, 'whatsapp_keyword', text[:40])` ותשובה:
  > הפסקנו לשלוח לכם את הדילים החמים בוואטסאפ ✔️
  > אפשר לחדש בכל רגע מעמוד הדילים באתר: {קישור מלא ל-/deals}
  > השיחה עם אריאלה ממשיכה כרגיל — אפשר לכתוב מתי שרוצים.
- לקוח שכבר לא מנוי → "השירות כבר לא פעיל אצלכם — לא יישלחו דילים חמים. אפשר להפעיל שוב מעמוד הדילים באתר: {קישור}"
- אם ללקוח יש חופשה עם מעקב בתשלום פעיל (`trip_requests.subscription_status='active'` ו-`mobile_notifications=1`), להוסיף שורה:
  > עדכוני החופשה שלכם ממשיכים. כדי להפסיק אותם — בכרטיס החופשה באתר.
  (המילה "עצור" מפסיקה **רק** את הדילים החמים.)
- לא משנה את `whatsapp_conversation_state` ולא את קישור הוואטסאפ לחשבון.
- פנייה ניטרלית ברבים (בלי "כתבי"/"תקבלי").

### 5. שורת עזרה בהודעת הדילים (formatter.py, `build_daily_message`)
להוסיף בסוף ההודעה:
`_להפסקת הדילים היומיים כתבו: עצור_`

### 6. מתג הפעלה
`WHATSAPP_STOP_KEYWORD_ENABLED` ב-config.py (ברירת מחדל `true`). כש-`false` — `route_inbound` מדלג על בדיקת המילה. (בפועל הקוד לא פעיל מול לקוחות עד שה-webhook יקרא ל-`route_inbound`.)

## קריטריוני קבלה
1. "עצור" / "STOP" / " עצור! " ממנוי פעיל → `whatsapp_opt_in=0`, `whatsapp_opt_out_source='whatsapp_keyword'`, שורה ב-`whatsapp_opt_events`, והתשובה המלאה עם קישור.
2. אחרי זה הלקוח **לא** מופיע ב-`members_to_notify_on_whatsapp()`.
3. "עצור" פעם שנייה → תשובת "השירות כבר לא פעיל", בלי שורת opt_out נוספת.
4. "אל תעצרי את החיפוש", "תפסיקי לחפש מלון", "עצור בבקשה את החיפוש לרומא" → **לא** מבטלים; ממשיכים לניתוב הרגיל.
5. מספר לא מוכר כותב "עצור" → תשובת "לא מצאתי מנוי", **בלי** פתיחת onboarding ובלי יצירת משתמש.
6. מנוי עם מעקב חופשה פעיל → מקבל גם את השורה על עדכוני החופשה, ו-`mobile_notifications` של החופשה לא משתנה.
7. המתג באתר ממשיך לעבוד כמו היום, ונרשמת שורת `source='site'` ב-`whatsapp_opt_events`.
8. `build_daily_message` כולל את שורת "להפסקת הדילים היומיים כתבו: עצור".
9. מסד קיים מתעדכן בלי שגיאה (מיגרציה רצה פעמיים בלי בעיה).

## בדיקות QA
- סקריפט בדיקה ב-tools/ (בסגנון הקיים) שקורא ל-`route_inbound` ישירות על DB זמני עם: מנוי פעיל, מנוי לא פעיל, מנוי עם חופשה במעקב, מספר לא מוכר — ומאמת את 9 הקריטריונים.
- בדיקה ידנית באתר: הפעלה/כיבוי במתג בעמוד הדילים, ושורות `whatsapp_opt_events`.
- דוח QA_REPORT בסגנון הקיים.

## מחוץ להיקף (במכוון)
- חיבור ה-webhook ל-`route_inbound` ושליחת התשובה בפועל — שלב חיבור הוואטסאפ.
- חידוש השירות מתוך וואטסאפ ("התחל") — ראו שאלה פתוחה.
- תור הודעות, מיזוג רדאר + דילים, מספור דילים — שאר תוכנית 003 (טרם אושר).

## שאלה פתוחה לבעלת העסק
לקוח שהפסיק ורוצה לחדש: האם לחדש **בלי תשלום נוסף** (כבר שילם 9 ₪ פעם אחת), או לשלם שוב? המשימה הזו לא משנה את התשלום — רק מפנה לאתר.
