# משימת פיתוח 002א — הרדאר האישי, שלב 1: "הרדאר מוכן" (בלי שליחה)

תוכנית: [002 — רדאר אישי](../plans/002-personal-radar.md) — **אושר: שלב 1 בלבד**
נוצרה: 2026-10-08
מצב: לכתוב את הקוד יחד עם שאר המשימות בפקודה אחת (לפי בעלת העסק). **אין שליחה ללקוחות** — רק החלטה, נוסח, הצגה בכרטיס החופשה ותצוגה מקדימה במסך המנהל.
תלות: משתמשת בטבלת התור `whatsapp_outbound_queue` ובמתג `WHATSAPP_DEALS_BUTTONS_ENABLED` — אם 003א עוד לא נבנתה, ליצור כאן את הטבלה באותה הגדרה (ראו סעיף 1).

## המטרה
כל יום, אחרי שהמעקב בתשלום (19 ₪ / 39 ₪) מוצא ומצמיד את הטיסות הטובות לחופשה, אריאלה מחליטה **אם יש סיבה טובה להתריע**, מנסחת הודעה קצרה, שומרת אותה, ומציגה אותה:
- בכרטיס החופשה באזור האישי ("🎯 עדכון אחרון מהרדאר"),
- ובמסך המנהל כתצוגה מקדימה של הודעת הוואטסאפ.

## מה קיים היום
- מעקב בתשלום: `run_paid_personal_search_batch` (צהריים, 39 ₪) ו-`run_personal_vacation_evening_refresh` (ערב, 19 ₪ + 39 ₪) — public_site.py:4185–4290. שתיהן קוראות ל-`_pin_offer_ids_to_trip(trip_id, answers, matches)` (public_site.py:3975) שממיין לפי מחיר ושומר עד 5 מזהים ב-`answers["_matched_offer_ids"]`.
- מחיר בכרטיס: `offer.price_ils` = מחיר לאדם (templates/_deal_card.html:40). כבודה: `offer.baggage.checked_bag_23kg.included`.
- היסטוריה: טבלת `offers` (route, outbound_date, return_date, price_ils, observed_at) עם אינדקס `idx_offers_route_dates`.
- דגל התראות לחופשה: `trip_requests.mobile_notifications` (מתג קיים, public_site.py:3799–3801).
- תשלום מדומה: `dev_bypass_payment` (public_site.py:4916) → `_confirm_paid_search` (4885).

## שינויים

### 1. מסד נתונים (database.py — בבלוק המיגרציות של `trip_requests`)
```python
for col, ddl in [
    ("alert_baseline_price_ils", "REAL"),
    ("alert_last_price_ils", "REAL"),
    ("alert_last_at", "TEXT"),
]:
    if col not in trip_columns:
        conn.execute(f"ALTER TABLE trip_requests ADD COLUMN {col} {ddl}")
```
```sql
CREATE TABLE IF NOT EXISTS trip_alerts_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,          -- 'price_drop' | 'lowest_seen'
    price_ils REAL NOT NULL,
    previous_price_ils REAL,
    offer_id INTEGER,
    message_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'preview',   -- 'preview' | 'queued' | 'sent' | 'failed'
    FOREIGN KEY(trip_id) REFERENCES trip_requests(id)
);
CREATE INDEX IF NOT EXISTS idx_trip_alerts_trip ON trip_alerts_log(trip_id, id DESC);

-- משותפת עם 003א (ליצור רק אם לא קיימת):
CREATE TABLE IF NOT EXISTS whatsapp_outbound_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    kind TEXT NOT NULL,            -- 'welcome' | 'hot_deals' | 'radar'
    body TEXT NOT NULL,
    buttons_json TEXT NOT NULL DEFAULT '[]',
    image_url TEXT,
    ref_id INTEGER,                -- trip_id לרדאר
    status TEXT NOT NULL DEFAULT 'preview',
    created_at TEXT NOT NULL,
    sent_at TEXT,
    error TEXT
);
```
(מחיר הבסיס נקבע בפעם הראשונה שהרדאר רץ על החופשה אחרי תחילת המעקב בתשלום.)

### 2. מודול חדש: `radar_alerts.py`
`evaluate_trip_alert(trip_id: int) -> dict | None`
1. טוען את החופשה. ממשיך רק אם `subscription_status='active'` ו-`subscription_plan IN ('scan','update')`.
2. לוקח את ההצעה הזולה מבין `_matched_offer_ids` (דרך `recent_offers(offer_ids=...)`).
3. אם `alert_baseline_price_ils` ריק → שומר אותו = המחיר הנוכחי, **בלי התראה**, ויוצא.
4. מחיר השוואה = `alert_last_price_ils` אם קיים, אחרת ה-baseline.
5. **סיבה להתריע** (אחת מספיקה):
   - `price_drop`: ירידה של **5% לפחות וגם 50 ₪ לפחות לאדם** ממחיר ההשוואה.
   - `lowest_seen`: המחיר הזול ביותר שנראה ב-30 הימים האחרונים בטבלת `offers` לאותו `route` ולאותם `outbound_date`/`return_date` — **וגם** נמוך ממחיר ההשוואה (כדי לא להתריע על אותו מחיר שוב).
6. מגבלות: לא יותר מהתראה אחת ביום לחופשה (`alert_last_at` מהיום, שעון ישראל → לא מתריע). אם `mobile_notifications=0` → נרשם בלוג עם `status='preview'` אבל **לא** נכנס לתור.
7. יש סיבה → בונה נוסח (סעיף 3), כותב שורה ל-`trip_alerts_log`, מעדכן `alert_last_price_ils` ו-`alert_last_at`, ומוסיף לתור `whatsapp_outbound_queue` (kind='radar', ref_id=trip_id, status='preview').
8. לא שולח שום הודעה. גם כשהמתג `WHATSAPP_DEALS_BUTTONS_ENABLED=true` — שליחת הרדאר תיבנה בשלב 2.

### 3. נוסח ההודעה (פנייה ניטרלית, ברבים; קצר)
```
🎯 *עדכון על החופשה ל{יעד}*
המחיר ירד ל-{מחיר} ₪ לאדם{ כולל מזוודה}  (היה {מחיר קודם} ₪)
{שורת סיבה}
נבדק היום ב-{HH:MM}
```
- " כולל מזוודה" — רק אם `baggage.checked_bag_23kg.included is True`. אחרת לא לכתוב כלום על כבודה.
- שורת סיבה: `lowest_seen` → "זה המחיר הכי נמוך שראינו לתאריכים האלה בחודש האחרון." · `price_drop` → "ירידה של {N} ₪ מהעדכון הקודם."
- שם היעד: `arrival_city_he` של ההצעה, ואם אין — `request_name` של החופשה.
- כפתורים (נשמרים ב-`buttons_json`, יוצגו בשלב 2): `[לכל החופשה באתר]` (קישור ל-/account#vacation-{id}), `[החופשות שלי]`.
- תמונה: `destination_image_url` של ההצעה אם יש (נשמר ב-`image_url`).

### 4. חיבור
בסוף כל איטרציה של חופשה ב-`run_paid_personal_search_batch` וב-`run_personal_vacation_evening_refresh`, אחרי `_pin_offer_ids_to_trip`: `evaluate_trip_alert(trip_id)` בתוך try/except עם `log.exception` — כשל ברדאר לעולם לא מפיל את הסריקה.

### 5. ממשק
- **כרטיס החופשה** (templates/account.html, בתוך `vacation-result`, מעל רשימת הטיסות): אם יש שורה אחרונה ב-`trip_alerts_log` לחופשה — תיבה קטנה "🎯 עדכון אחרון מהרדאר · {תאריך}" עם טקסט ההודעה. אם אין — לא מציגים כלום. לטעון את השורה בשאילתה אחת לכל החופשות בעמוד (לא שאילתה לכל חופשה).
- **מסך המנהל**: `GET /admin/whatsapp-queue` (app.py, עם `_require_admin`) — JSON של 50 השורות האחרונות בתור: kind, member_id, ref_id, body, buttons, image_url, status, created_at. (אם 003א כבר הוסיפה את הנתיב — להשתמש בו.)

## קריטריוני קבלה
1. חופשה במעקב (תשלום מדומה), ריצה ראשונה → נשמר baseline, **אין** התראה.
2. ירידה של 8% ו-120 ₪ → התראה `price_drop`, שורה בלוג, שורה בתור (`radar`, `preview`), נוסח עם המחיר החדש והקודם.
3. ירידה של 3% או 40 ₪ בלבד → אין התראה.
4. אותו יום, ירידה נוספת → אין התראה שנייה. למחרת → יש.
5. מחיר שלא ירד אבל הוא "הכי נמוך ב-30 יום" ועדיין לא דווח → **אין** התראה (חייב להיות נמוך ממחיר ההשוואה).
6. `mobile_notifications=0` → שורה בלוג, **בלי** שורה בתור.
7. חופשה בלי מעקב בתשלום (`subscription_status != 'active'`) → לא נבדקת בכלל.
8. "כולל מזוודה" מופיע רק כשהמזוודה באמת כלולה.
9. התיבה "עדכון אחרון מהרדאר" מופיעה בכרטיס החופשה, ולא מופיעה בחופשה בלי התראות.
10. `/admin/whatsapp-queue` מחזיר את ההתראה; בלי טוקן מנהל → 401.
11. חריגה בתוך `evaluate_trip_alert` לא עוצרת את `run_paid_personal_search_batch`.
12. שום קריאה ל-Meta/וואטסאפ לא מתבצעת.

## בדיקות QA
- סקריפט ב-tools/ על DB זמני: יצירת חבר + חופשה + תשלום מדומה, הזרקת הצעות במחירים שונים לטבלת `offers`, הרצת `evaluate_trip_alert` בתרחישים 1–8.
- בדיקה ידנית: האזור האישי עם חופשה שיש לה התראה; `/admin/whatsapp-queue`.
- דוח QA_REPORT בסגנון הקיים.

## מחוץ להיקף
- שליחה בוואטסאפ (שלב 2), מחיר יעד (שלב 3), רדאר פתוח (שלב 4).
