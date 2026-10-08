# משימת פיתוח 001א — זיהוי הזמנה לפי קרדיט מ-CJ, "תיהנו בטיול" ו"איך היה?"

תוכנית: [001 — פרופיל נוסע ומחזור חיים של חופשה](../plans/001-traveler-profile-and-trip-lifecycle.md) — **אושר: הכיוון החדש של שלב 1** (במקום שאלת "הזמנת?")
נוצרה: 2026-10-08
מצב: לכתוב את הקוד יחד עם שאר המשימות בפקודה אחת. **אין שליחה ללקוחות** עד חיבור הוואטסאפ — ההודעות נכנסות לתור ומוצגות בתצוגה מקדימה.
תלות: טבלת התור `whatsapp_outbound_queue` (משימות 002א/003א — ליצור אם לא קיימת, באותה הגדרה).

## המטרה
1. כשמגיע קרדיט (עמלה) מ-CJ על מלון או רכב שהוזמנו מתוך חופשה באריאלה → החופשה מסומנת "הוזמנה", ונוצרת הודעת "תיהנו בטיול".
2. יומיים אחרי תאריך החזרה של חופשה שהוזמנה → נוצרת הודעת "איך היה?" עם 3 כפתורי דירוג.
3. התשובה נשמרת כמשוב מקושר ללקוח ולחופשה.

## מה קיים היום
- קישורי שותפים עם קוד חופשה: `sid=trip{trip_id}` — מלון `_lodging_partner_url` (public_site.py:4650), רכב `_car_partner_url` (public_site.py:4600), עטיפת Booking `_cj_booking_wrap` (public_site.py:204).
- תאריכי החופשה: `answers["departure_date"]`, `answers["return_date"]` ב-`trip_requests.answers_json`.
- לחיצות: `booking_clicks` (database.py:323) — לחיצה בלבד, לא הזמנה.
- משוב כללי: `feedback_messages` (לא מקושר לחופשה).

## שינויים

### 1. הגדרות (config.py)
```python
CJ_API_TOKEN = os.getenv("CJ_API_TOKEN", "").strip()        # Personal Access Token מ-developers.cj.com
CJ_PUBLISHER_ID = os.getenv("CJ_PUBLISHER_ID", "").strip()  # CID של חשבון ה-Publisher
CJ_COMMISSIONS_SYNC_ENABLED = os.getenv("CJ_COMMISSIONS_SYNC_ENABLED", "false").lower() == "true"
```
ולהוסיף את שלושתם ל-env.example (בלי ערכים).

### 2. מסד נתונים (database.py)
```sql
CREATE TABLE IF NOT EXISTS partner_commissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network TEXT NOT NULL DEFAULT 'cj',
    commission_id TEXT NOT NULL,
    trip_id INTEGER,                 -- מתוך sid=trip{id}; NULL אם ה-sid לא שלנו
    advertiser_name TEXT,
    action_status TEXT,              -- כפי שמגיע מ-CJ (new/locked/closed/corrected...)
    sale_amount REAL,
    commission_amount REAL,
    currency TEXT,
    event_date TEXT,
    posting_date TEXT,
    raw_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(network, commission_id)
);
CREATE INDEX IF NOT EXISTS idx_partner_commissions_trip ON partner_commissions(trip_id);

CREATE TABLE IF NOT EXISTS trip_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    rating INTEGER NOT NULL,         -- 3 = מעולה, 2 = היה בסדר, 1 = פחות
    comment TEXT,
    source TEXT NOT NULL,            -- 'whatsapp_button' | 'site'
    created_at TEXT NOT NULL,
    UNIQUE(trip_id, member_id)
);
```
עמודות חדשות ב-`trip_requests` (ALTER TABLE בסגנון הקיים):
`booked_confirmed_at TEXT`, `booked_source TEXT` (`'cj_commission'`), `booking_cancelled_at TEXT`, `congrats_queued_at TEXT`, `how_was_it_queued_at TEXT`.

### 3. סנכרון עמלות — מודול חדש `partner_commissions.py`
`sync_cj_commissions(days_back: int = 7) -> dict`
- רץ רק אם `CJ_COMMISSIONS_SYNC_ENABLED` ושני המפתחות קיימים; אחרת מחזיר `{"status": "disabled"}`.
- קורא ל-CJ Commission Detail API (GraphQL, `https://commissions.api.cj.com/query`, כותרת `Authorization: Bearer {CJ_API_TOKEN}`), שאילתת `publisherCommissions` עם `forPublishers: [CJ_PUBLISHER_ID]` וטווח `sincePostingDate`/`beforePostingDate` (עד 31 יום לבקשה). שדות: `commissionId`, `shopperId` (= ה-sid), `actionStatus`, `advertiserName`, `eventDate`, `postingDate`, `saleAmountPubCurrency`, `pubCommissionAmountPubCurrency`, `pubCurrency`.
  **לוודא את שמות השדות מול התיעוד העדכני של CJ לפני הכתיבה** (developers.cj.com → Commission Detail API).
- `shopperId` בפורמט `trip{מספר}` → `trip_id`; אחר → `trip_id=NULL` (נשמר, לא מטופל).
- upsert לפי `commission_id`. timeout 30 שניות; כשל רשת → log ויציאה בלי חריגה.
- אחרי ה-upsert, לכל `trip_id` חדש: אם `booked_confirmed_at` ריק וסטטוס העמלה לא מבוטל → `booked_confirmed_at=now`, `booked_source='cj_commission'`, ואז `queue_booking_congrats(trip_id)`.
- עמלה שהפכה למבוטלת/מתוקנת לסכום 0 ואין לחופשה עמלה תקפה אחרת → `booking_cancelled_at=now` (ואז **לא** שולחים "איך היה?").

### 4. הודעות (מודול `trip_lifecycle_messages.py`)
פנייה ניטרלית ברבים. יעד = שם העיר בעברית מתוך החופשה (`request_name` / היעד ב-answers).

**א. "תיהנו בטיול"** — `queue_booking_congrats(trip_id)`, פעם אחת לחופשה (`congrats_queued_at`):
```
🎉 *איזה כיף — ההזמנה נקלטה!*
{יעד} מחכה לכם {בעוד N ימים | ב-DD.MM}.
אם תצטרכו משהו לפני הטיסה — פשוט כתבו לאריאלה כאן 🌷
שתהיה לכם חופשה מושלמת! ✈️
```
- אם תאריך היציאה כבר עבר או חסר → בלי שורת "מחכה לכם".
- כפתור: `[החופשות שלי]`.

**ב. "איך היה?"** — משימה יומית `queue_how_was_it_messages()`: חופשות עם `booked_confirmed_at`, בלי `booking_cancelled_at`, בלי `how_was_it_queued_at`, ו-`return_date + 2 ימים <= היום` (שעון ישראל), ולא יותר מ-30 יום אחרי החזרה.
```
👋 *ברוכים השבים!*
איך היה ב{יעד}?
```
- כפתורי quick reply: `😍 מעולה` (payload `HOW_WAS_IT:{trip_id}:3`), `🙂 היה בסדר` (`:2`), `😕 פחות` (`:1`).

- כל ההודעות נכנסות ל-`whatsapp_outbound_queue` (kind `booking_congrats` / `how_was_it`, `ref_id=trip_id`, `status='preview'`). **אין שליחה.**
- לא שולחים בשבת לפי `schedule_rules.delivery_status` (רלוונטי לשלב השליחה; בתור — שדה `not_before` אופציונלי).

### 5. קליטת דירוג
- ב-`nova_conversation.route_inbound` (פרמטר `button_payload`, כמו ב-003א): payload `HOW_WAS_IT:{trip_id}:{rating}` → בדיקה שהחופשה שייכת ללקוח של המספר → `INSERT OR REPLACE` ל-`trip_feedback` (source `whatsapp_button`) → תשובה:
  - 3: "איזה כיף לשמוע! 😍 אם בא לכם לספר מה הכי אהבתם — כתבו לי, זה עוזר לי להמליץ טוב יותר."
  - 2: "תודה על השיתוף 🙏 מה היה יכול להיות טוב יותר? אפשר לכתוב לי במילה או שתיים."
  - 1: "מצטערת לשמוע 😕 מה לא היה טוב? אשמח לדעת כדי שבפעם הבאה זה יהיה הרבה יותר טוב."
- ההודעה הבאה של הלקוח (תוך 24 שעות) נשמרת כ-`comment` באותה שורה — ואז אריאלה עונה "תודה, רשמתי ❤️".

### 6. תזמון (scheduler.py)
- `sync_cj_commissions` — פעם ביום ב-07:30 שעון ישראל (וגם ידנית מנתיב מנהל).
- `queue_how_was_it_messages` — פעם ביום ב-10:00.
- שתיהן בתוך try/except עם `log.exception`.

### 7. מסך מנהל (app.py, `_require_admin`)
- `POST /admin/cj-sync` — הרצה ידנית, מחזיר סיכום.
- `GET /admin/partner-commissions` — 50 העמלות האחרונות + החופשה המקושרת.
- ההודעות עצמן נראות ב-`GET /admin/whatsapp-queue` (משימות 002א/003א).

## פרטיות ומשפט
- הודעת "תיהנו בטיול" ו"איך היה?" הן הודעות שירות על חופשה שהלקוח תכנן — לא פרסומת. לא לצרף אליהן דילים.
- לא לשמור פרטי הזמנה מעבר למה ש-CJ מחזיר (בלי פרטי אשראי, בלי שמות נוסעים).
- לעדכן privacy.html: "אנחנו מקבלים מהשותפים אישור על הזמנות שבוצעו דרך האתר, כדי לשלוח לכם עדכונים על החופשה".

## קריטריוני קבלה
1. בלי `CJ_API_TOKEN` → `sync_cj_commissions` מחזיר `disabled` ולא קורא לרשת.
2. תשובת CJ מדומה עם `shopperId='trip42'` → שורה ב-`partner_commissions` עם `trip_id=42`, `booked_confirmed_at` נקבע, והודעת `booking_congrats` בתור.
3. אותה עמלה פעמיים / שתי עמלות (מלון + רכב) לאותה חופשה → הודעת ברכה **אחת** בלבד.
4. `shopperId` לא שלנו → נשמר עם `trip_id=NULL`, בלי הודעה.
5. עמלה מבוטלת בלי עמלה תקפה אחרת → `booking_cancelled_at`, ואין "איך היה?".
6. חופשה שהוזמנה, `return_date` לפני יומיים → הודעת `how_was_it` בתור עם 3 כפתורים; לפני יום אחד → עדיין לא; לפני 40 יום → לא.
7. `route_inbound(phone, '', button_payload='HOW_WAS_IT:42:3')` מהלקוח של החופשה → שורה ב-`trip_feedback` ותשובת "איזה כיף". מלקוח אחר → מתעלמים.
8. הודעה חופשית אחרי הדירוג → נשמרת כ-`comment`.
9. שום קריאה ל-Meta/וואטסאפ.
10. מיגרציה רצה פעמיים בלי שגיאה.

## בדיקות QA
- סקריפט ב-tools/ על DB זמני עם תשובת CJ מדומה (mock ל-`requests.post`): תרחישים 1–8.
- בדיקה ידנית: `/admin/cj-sync` עם המפתחות האמיתיים (קריאה בלבד), ובדיקה שהעמלות האחרונות מופיעות ב-`/admin/partner-commissions`.
- דוח QA_REPORT בסגנון הקיים.

## מחוץ להיקף
- שליחה בפועל בוואטסאפ; פרופיל נוסע קבוע (שלב 2 בתוכנית 001); טיסות (כרגע לא עוברות דרך שותף שמחזיר קרדיט — לבדוק בנפרד).

## צריך מבעלת העסק (לפני הרצת הפיתוח)
- Personal Access Token מ-developers.cj.com ו-CID של החשבון — מוגדרים כמשתני סביבה ב-Render (לא בקוד ולא בשיחה).
