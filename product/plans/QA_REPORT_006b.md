# QA — 006ב: בדיקה ותיקון של המינוי של חשבון הוואטסאפ לאפליקציה

תוכנית: [006](006-whatsapp-inbound-ariela.md) — השלמה ל-006א (שלב 1 מאושר)

## מה נבדק
`tools/qa_whatsapp_subscription_check.py` (mock מלא ל-`requests` - שום קריאה אמיתית ל-Meta), כולן PASS:
1. בלי טוקן מנהל → 401.
2. בלי `WHATSAPP_ACCESS_TOKEN` מוגדר → `token_ok:false` עם הודעה ברורה, בלי שום קריאת רשת.
3. WABA שלא מנוי לאפליקציה → `subscribed:false`; בלי `apply=1` לא נשלחת שום `POST` (קריאה בלבד). עם `apply=1` → `POST /{waba_id}/subscribed_apps` נשלח בדיוק פעם אחת, ואז נבדק שוב ומחזיר `subscribed:true`.
4. הטוקן שייך ל-WABA אחר (שגיאת הרשאה מ-Meta, `OAuthException`) → `token_ok:false`, וההודעה מ-Meta מוצגת.
5. מספר הטלפון: תמיד רק 4 הספרות האחרונות (`display_phone_number_ending`) - המספר המלא לעולם לא מופיע בתוצאה.
6. הטוקן עצמו (`WHATSAPP_ACCESS_TOKEN`) לעולם לא מופיע בשום מקום ב-JSON המוחזר, גם לא בשגיאות.

## המימוש
`whatsapp.whatsapp_subscription_check(apply=False)` ב-`whatsapp.py`, נחשף דרך `GET /admin/whatsapp-subscription` (עם `_require_admin`, ו-`?apply=1` כדי גם לתקן). משתמש ב-header `Authorization: Bearer` (לא בפרמטר URL) כדי שהטוקן לעולם לא יגיע ללוג שרת. `WHATSAPP_WABA_ID` (משתנה סביבה חדש, אופציונלי) נוסף ל-`config.py` ול-`env.example`.

כל חבילת הבדיקות הקיימת (`qa/run_qa.py`) נבדקה ועברה אחרי השינוי - שום נתיב קיים לא הושפע.
