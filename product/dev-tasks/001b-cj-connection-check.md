# משימת פיתוח 001ב — בדיקת חיבור ל-CJ מהטלפון (קריאה בלבד)

תוכנית: [001](../plans/001-traveler-profile-and-trip-lifecycle.md) — השלמה ל-001א
נוצרה: 2026-10-10

## למה
בעלת העסק הזינה ב-Render את `CJ_API_TOKEN` ואת `CJ_PUBLISHER_ID`. עכשיו צריך לוודא ששמות השדות בשאילתה של `partner_commissions.py` נכונים (ראו הסתייגות ב-QA_REPORT_001a). זה בלי להפעיל את הסנכרון (`CJ_COMMISSIONS_SYNC_ENABLED=false`), ובלי לשמור שום דבר במסד.
הבעיה היום: `/admin/cj-sync` הוא POST, ואי אפשר להפעיל אותו מדפדפן בטלפון. וגם כשהוא מופעל, כל עוד המתג כבוי הוא מחזיר רק `disabled`.

## שינוי
`GET /admin/cj-check?token=...&days_back=31` ב-app.py (עם `_require_admin`):
- דורש רק שני מפתחות. **לא** בודק את `CJ_COMMISSIONS_SYNC_ENABLED`.
- שולח את אותה שאילתה ש-`sync_cj_commissions` שולחת (להוציא פונקציה משותפת `_fetch_cj_records(since, before)`). **לא כותב למסד ולא יוצר הודעות.**
- מחזיר JSON:
  - `ok: true/false`
  - `http_status`
  - `graphql_errors`: רשימת השגיאות כפי שהגיעו מ-CJ, בלי המפתח
  - `records_count`
  - `sample`: עד 3 רשומות. בלי סכומים, רק `commissionId`, sid, `actionStatus`, `advertiserName`, `postingDate`
  - `field_check`: לכל שדה בשאילתה, האם הוא הופיע ברשומה הראשונה
- אם יש `graphql_errors` שמזכירות שדה לא קיים → `hint`: "שם שדה שגוי. לתקן את `_QUERY` לפי השגיאה." ורצוי להריץ גם שאילתת introspection על הטיפוס, ולהחזיר את רשימת השדות האמיתית (`available_fields`).
- אם יש שגיאות, לתקן את `_QUERY` לפי `available_fields` ולהריץ שוב, עד ש-`ok: true`.
- בשום מקרה לא להחזיר או לרשום בלוג את `CJ_API_TOKEN`.

## קריטריוני קבלה
1. בלי מפתחות → `ok:false` עם הודעה ברורה.
2. עם המפתחות האמיתיים → `ok:true` ו-`graphql_errors` ריק (גם אם `records_count=0`, כי בחשבון עדיין אין עמלות).
3. שום שורה לא נוספת ל-`partner_commissions` ושום הודעה לא נכנסת לתור.
4. אפשר לפתוח את הקישור מהדפדפן בטלפון (GET עם `?token=`).
5. בדיקת QA עם mock: הצלחה, שגיאת GraphQL על שדה, ו-401 מ-CJ.

## אחרי שזה עובד
בעלת העסק פותחת את הקישור. אם `ok:true`, אפשר יהיה להדליק `CJ_COMMISSIONS_SYNC_ENABLED=true` (החלטה שלה).
