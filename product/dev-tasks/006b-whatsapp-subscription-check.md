# משימת פיתוח 006ב — בדיקה ותיקון של המינוי של חשבון הוואטסאפ לאפליקציה

תוכנית: [006](../plans/006-whatsapp-inbound-ariela.md) — השלמה ל-006א (שלב 1 מאושר)
נוצרה: 2026-10-11

## הרקע
בבדיקה החיה (11.10, ערב) הכל הוגדר: ב-Render יש ACCESS_TOKEN, PHONE_NUMBER_ID=551450234708715, META_APP_SECRET, VERIFY_TOKEN, ALLOWLIST ו-ENABLED=true. ב-Meta: Callback URL נכון, `messages` במצב Subscribed, והאפליקציה ARIELA TOURS (919805650390657) **פורסמה**. למרות זה, הודעה מהנייד המורשה **לא מגיעה בכלל**, ואין שום `POST /whatsapp-webhook` ביומן של Render.
החשוד המרכזי: חשבון הוואטסאפ האמיתי "אריאלה טורס" (WABA **453734811161130**) **לא מנוי לאפליקציה** (`/{waba_id}/subscribed_apps`). המינוי מתבצע רק בזרימת ה-coexistence (whatsapp_coexistence.py:100), ולא ידוע אם היא הושלמה. המספר עובד ב-Coexistence עם אפליקציית WhatsApp Business.

## שינוי
`GET /admin/whatsapp-subscription` (app.py, עם `_require_admin`). **קריאה בלבד** כברירת מחדל:
1. `GET https://graph.facebook.com/{v}/{WHATSAPP_PHONE_NUMBER_ID}?fields=id,display_phone_number,verified_name,quality_rating,platform_type,code_verification_status,status` → מחזיר את פרטי המספר. **בלי** מספר מלא: רק 4 ספרות אחרונות.
2. ה-WABA: מתוך `WHATSAPP_WABA_ID` (משתנה סביבה חדש, אופציונלי, ברירת מחדל ריקה). אם אין, לנסות דרך ה-API.
3. `GET /{waba_id}/subscribed_apps` → האם האפליקציה 919805650390657 ברשימה.
4. מחזיר JSON: `phone`, `waba_id`, `subscribed` (true/false), `subscribed_apps` (מזהה ושם בלבד), `token_ok` (האם ה-ACCESS_TOKEN עובד מול ה-WABA הזה), `errors` (מ-Meta, **בלי הטוקן**).

עם `?apply=1`: אם `subscribed=false` → `POST /{waba_id}/subscribed_apps` עם ה-ACCESS_TOKEN, ואז שוב GET. מחזיר `applied: true` ואת הסטטוס החדש. (GET משנה מצב רק בפרמטר מפורש, כי בעלת העסק עובדת מטלפון.)

- להוסיף `WHATSAPP_WABA_ID=` ל-env.example.
- אסור לרשום או להחזיר את ה-ACCESS_TOKEN.

## קריטריוני קבלה
1. בלי טוקן מנהל → 401.
2. בלי `WHATSAPP_ACCESS_TOKEN` → `token_ok:false` עם הודעה ברורה.
3. mock: WABA שלא מנוי → `subscribed:false`. אחרי `apply=1` → `POST` נשלח, ו-`subscribed:true`.
4. mock: הטוקן שייך ל-WABA אחר (שגיאת הרשאה מ-Meta) → `token_ok:false`, והשגיאה מוצגת. זה תרחיש סביר, כי בעלת העסק יצרה את הטוקן ממסך שהציג קודם את חשבון הבדיקה.
5. בדיקת QA עם mock ל-requests. שום קריאה אמיתית ל-Meta בבדיקות.

## אחרי
בעלת העסק תפתח את הקישור בלי `apply`. אם `subscribed:false`, תפתח עם `apply=1`, ותשלח שוב הודעה מהנייד.
