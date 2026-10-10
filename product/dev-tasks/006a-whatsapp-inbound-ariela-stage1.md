# משימת פיתוח 006א — אריאלה עונה בוואטסאפ (שלב 1, מספרים מורשים בלבד)

תוכנית: [006 — לחבר את הוואטסאפ לאריאלה](../plans/006-whatsapp-inbound-ariela.md) — **אושר: שלב 1**
נוצרה: 2026-10-10

## המטרה
לקוח **מורשה** (allowlist) כותב בוואטסאפ, ואריאלה עונה **באותו מנוע ובאותה שיחה שמורה** כמו באתר. אפשר להמשיך את השיחה באתר, ולהפך. תוצאות חיפוש בשלב הזה = קישור לכרטיס החופשה באתר.

## מה קיים (לקרוא לפני שמתחילים)
- Webhook: `whatsapp_webhook` (whatsapp.py:58). ה-GET מאמת verify token, ה-POST מתעלם מההודעה.
- שליחה: `send_text_message(message, recipient)` (whatsapp.py:80).
- נתב וואטסאפ: `nova_conversation.route_inbound(phone, text, profile_name, button_payload)` (nova_conversation.py:498). מזהה לקוח (`linked_member_for_phone`, `registered_member_for_phone`), עושה onboarding למספר לא מוכר, ומטפל בכפתורים `STOP_HOT_DEALS` ו-`HOW_WAS_IT:*`. כרגע טקסט מלקוח מזוהה הולך לתפריט של נובה (`_route_member`).
- שיחת אריאלה בשרת: `save_ariella_conversation` / `load_ariella_conversation` (database.py:1684/1700). האתר טוען אותה ב-`/api/ariella/resume`.
- **מנוע אריאלה** — `chat_clean` (ariella_chat_clean.py:3876) הוא route שתלוי ב-`session['member_id']` וב-`history` שהדפדפן שולח.
- **חשוב:** חלק מהזרימה מתבצע **בדפדפן** (templates/trip_form.html, שורות ~270–400). אחרי תשובה מ-`chat-clean` ה-JS מבצע לפי הדגלים:
  - `persist_trip_plan` → POST `/api/ariella/save-trip-plan` (עם `trip_id` פעיל מ-localStorage)
  - `reopen_trip_id` → מעדכן את החופשה הפעילה
  - `open_existing_flights` → פותח את התוצאות הקיימות
  - `start_flight_search` → POST `/api/ariella/start-flight-search` (עם `trip_state`, `history`, `existing_trip_id`) → `waiting_url`
  - וגם `/api/ariella/sync-trip-services` (שורה ~65)
  בוואטסאפ אין דפדפן, ולכן **הגשר צריך לבצע את אותן פעולות בצד השרת**, עם "חופשה פעילה" שנשמרת ב-`whatsapp_conversation_state.active_trip_id`.

## שינויים

### 1. הגדרות (config.py + env.example, בלי ערכים)
- `WHATSAPP_INBOUND_ENABLED` (ברירת מחדל `false`)
- `WHATSAPP_INBOUND_ALLOWLIST` — מספרים מופרדים בפסיק, בפורמט שמנורמל ב-`canonical_phone`
- `META_APP_SECRET` — **כבר קיים** (whatsapp_coexistence.py:51). משמש לאימות חתימה.
- `PUBLIC_SITE_URL` — לקישורים בהודעות (אם עדיין לא קיים)

### 2. Webhook (whatsapp.py)
- POST: לאמת `X-Hub-Signature-256` (HMAC-SHA256 של ה-body הגולמי עם `META_APP_SECRET`). חתימה לא תקינה → 403. אם אין סוד מוגדר → לא מעבדים (רק לוג).
- להחזיר 200 **מיד**, ולעבד ברקע (thread daemon, או תור בטבלה ו-job של ה-scheduler כל כמה שניות — לבחור את הפשוט והיציב).
- לפענח מ-`entry[].changes[].value.messages[]`: `from`, `id`, `timestamp`, `type`; טקסט מ-`text.body`; כפתור מ-`button.payload` או `interactive.button_reply.id` / `interactive.list_reply.id`. `contacts[].profile.name` → `profile_name`.
- להתעלם מ-`statuses` (אישורי מסירה) — אבל לשמור אותם בלוג אם זה פשוט.
- סוגים אחרים (תמונה, קול, מסמך) → תשובה: "כרגע אני קוראת רק הודעות טקסט 🙏 אפשר לכתוב לי במילים?"

### 3. טבלה (database.py)
```sql
CREATE TABLE IF NOT EXISTS whatsapp_inbound_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_message_id TEXT NOT NULL UNIQUE,
    phone_hash TEXT NOT NULL,
    member_id INTEGER,
    direction TEXT NOT NULL,        -- 'in' | 'out'
    msg_type TEXT,
    body TEXT,
    button_payload TEXT,
    status TEXT NOT NULL,           -- 'received' | 'processed' | 'ignored_not_allowlisted' | 'error' | 'sent' | 'send_failed'
    error TEXT,
    created_at TEXT NOT NULL
);
```
- כפילות `wa_message_id` → מתעלמים בשקט (Meta שולחת שוב לפעמים).
- הודעות יוצאות: שורה עם `direction='out'` ו-`wa_message_id` שחזר מ-Meta.
- לא לשמור מספר טלפון גלוי. רק hash, כמו `_phone_hash`.

### 4. allowlist
- `WHATSAPP_INBOUND_ENABLED=false` → לא עונים לאף אחד (רק לוג).
- מספר שלא ב-allowlist → תשובה אחת ביום לכל מספר לכל היותר: "היי 🌷 אריאלה בוואטסאפ תיפתח בקרוב. בינתיים אפשר לתכנן איתה חופשה באתר: {PUBLIC_SITE_URL}". סטטוס `ignored_not_allowlisted`.

### 5. הגשר למנוע אריאלה — `ariella_turn(member_id, message, channel='whatsapp')`
- **עדיף:** להוציא את ליבת `chat_clean` לפונקציה שמקבלת `member_id` ו-`message`, טוענת את `history` מ-`load_ariella_conversation`, ומחזירה dict (`reply`, `trip_update`, הדגלים). ה-route של האתר יקרא לה. **אסור לשנות את התנהגות האתר.**
- **אם ההוצאה מסוכנת מדי:** לעטוף ב-`app.test_request_context(json={...})` עם `session['member_id']` ו-history מהשרת, ולקרוא ל-`chat_clean()`. לתעד בקוד שזה זמני.
- אחרי התשובה, לבצע בצד השרת את מה שה-JS עושה (סעיף "מה קיים"), עם `active_trip_id` מ-`whatsapp_conversation_state`:
  - `persist_trip_plan` → אותה פונקציה ש-`/api/ariella/save-trip-plan` מפעילה.
  - `reopen_trip_id` → לעדכן `active_trip_id`.
  - `start_flight_search` → אותה פונקציה ש-`/api/ariella/start-flight-search` מפעילה. אחרי ההפעלה, לשלוח הודעה: "מתחילה לחפש ✈️ התוצאות יופיעו כאן: {PUBLIC_SITE_URL}/account#vacation-{trip_id}". אם הוחזר `waiting_url`, להשתמש בו.
  - `open_existing_flights` → קישור לכרטיס החופשה.
- לוודא שהשיחה נשמרת (`save_ariella_conversation`) גם מוואטסאפ, כדי שהאתר יראה אותה ב-`/api/ariella/resume`.

### 6. ניתוב ב-`route_inbound`
- כפתור → כמו היום (לפני הכל).
- לקוח מזוהה + טקסט → `ariella_turn` (במקום `_route_member`). להשאיר את `_route_member` לפקודות המפורשות "תפריט" ו"החופשות שלי".
- `_maybe_capture_feedback_comment` (001א) → נשאר לפני `ariella_turn`.
- מספר לא מוכר → ה-onboarding הקיים. בסופו, ההודעה הבאה הולכת ל-`ariella_turn`.

### 7. התאמת טקסט לוואטסאפ
- להסיר HTML ותגיות. `**מודגש**` → `*מודגש*`.
- הודעה מעל 4,000 תווים → לפצל לפי פסקאות, ולשלוח לפי הסדר.
- תשובה ריקה → "אני איתכם 😊" (כמו באתר).

### 8. עלות AI
כל `_post_claude` בתוך תור של וואטסאפ נרשם ב-`ai_usage` עם ה-member וה-conversation (005א). להוסיף `channel` לטבלה אם פשוט, או לקודד ב-`source` (`ariella_reply_wa`).

### 9. מסך מנהל
`GET /admin/whatsapp-inbox?token=...` — 50 השורות האחרונות מ-`whatsapp_inbound_log` (נכנס/יוצא), עם member, סוג, טקסט מקוצר ל-200 תווים, וסטטוס.

## קריטריוני קבלה
1. חתימה לא תקינה → 403, ושום עיבוד.
2. אותה הודעה פעמיים (אותו `id`) → נענית פעם אחת.
3. מספר לא ב-allowlist → הודעת "בקרוב" אחת ביום, אריאלה לא נקראת.
4. מספר מורשה ורשום → "רוצה חופשה ביוון באוגוסט" → תשובת אריאלה תוך שניות, והשיחה נשמרת. `/api/ariella/resume` באתר (אותו חשבון) מחזיר את ההודעה ואת התשובה.
5. המשך באתר ואחר כך שוב בוואטסאפ → אריאלה ממשיכה מאותה נקודה.
6. שיחה שמגיעה ל-`start_flight_search` → נוצרת חופשה, החיפוש מתחיל, ונשלחת הודעה עם קישור לכרטיס החופשה.
7. כפתור `STOP_HOT_DEALS` → מתנהג בדיוק כמו ב-003א.
8. תמונה או הודעה קולית → תשובת "רק טקסט".
9. תשובה ארוכה → מפוצלת לכמה הודעות בסדר הנכון.
10. **האתר לא השתנה:** כל חבילת הבדיקות הקיימת עוברת, ושיחה ידנית באתר עובדת כמו קודם.
11. `ai_usage` מקבל שורות לתורות מוואטסאפ.
12. `/admin/whatsapp-inbox` עובד, ובלי טוקן מנהל → 401.
13. `WHATSAPP_INBOUND_ENABLED=false` → שום תשובה לאף אחד.

## בדיקות QA
- סקריפט ב-tools/ עם payloads אמיתיים לדוגמה של Meta (טקסט, כפתור, interactive, תמונה, statuses), חתימה תקינה ולא תקינה, ו-mock ל-`send_text_message` ול-Claude.
- בדיקה ידנית (אחרי שבעלת העסק תגדיר את Meta ואת Render): הודעה מהמספר שלה → תשובה; המשך באתר.
- דוח QA_REPORT בסגנון הקיים.

## מחוץ להיקף
תוצאות חיפוש מלאות בוואטסאפ עם תמונה וכפתורים (שלב 2); פתיחה לכל הלקוחות והודעות יזומות (שלב 3); Coexistence (מי עונה כשבעלת העסק עונה ידנית מהאפליקציה) — לשאול את בעלת העסק לפני שמשנים משהו בזה.

## צריך מבעלת העסק (אחרי שהקוד מוכן, בליווי אופק)
ב-Render: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `META_APP_SECRET`, `WHATSAPP_INBOUND_ALLOWLIST`, `WHATSAPP_INBOUND_ENABLED=true`. ב-Meta: כתובת webhook ומינוי ל-`messages`.
