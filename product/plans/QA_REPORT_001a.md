# QA — 001א: זיהוי הזמנה לפי קרדיט מ-CJ, "תיהנו בטיול" ו"איך היה?"

תוכנית: [001](001-traveler-profile-and-trip-lifecycle.md)

## מה נבדק
`tools/qa_booking_lifecycle_cj.py`, 21 בדיקות (עם mock ל-`requests.post`), כולן PASS:
1. בלי `CJ_API_TOKEN`/`CJ_PUBLISHER_ID` → `{"status": "disabled"}`, **בלי** קריאת רשת בכלל.
2. תשובת CJ מדומה עם `sid='trip{id}'` → `trip_id` נפתר נכון, `booked_confirmed_at` נקבע, `booked_source='cj_commission'`, הודעת `booking_congrats` נכנסת לתור עם שורת "בעוד N ימים".
3. אותה עמלה פעמיים + עמלה שנייה (מלון+רכב) לאותה חופשה → הודעת ברכה **אחת** בלבד.
4. `sid` לא שלנו → נשמר עם `trip_id=NULL`, בלי שום הודעה.
5. עמלה מבוטלת בלי עמלה תקפה אחרת לאותה חופשה → `booking_cancelled_at` נקבע, `booked_confirmed_at` **לא**.
6. `queue_how_was_it_messages()`: חופשה שחזרה לפני יומיים → בתור; לפני יום אחד → עדיין לא; לפני 40 יום → לא בכלל. ההודעה כוללת 3 כפתורי דירוג בפורמט `HOW_WAS_IT:{trip_id}:{rating}`.
7. `route_inbound(phone, '', button_payload='HOW_WAS_IT:{trip}:3')` מהלקוח האמיתי של החופשה → שורה ב-`trip_feedback` (rating=3, source='whatsapp_button') ותשובת "איזה כיף לשמוע".
8. הודעת טקסט חופשית מיד אחרי → נשמרת כ-`comment` על אותה שורה, ותשובת "תודה, רשמתי ❤️".
9. אותו payload מלקוח **אחר** (לא בעל החופשה) → מתעלמים, חוזר לניתוב הרגיל במקום תשובת הדירוג.

כל חבילת הבדיקות הקיימת (regression suite) ובדיקת ה-admin endpoints (`/admin/cj-sync`, `/admin/partner-commissions`) ורישום משימות ה-scheduler (`cj_commissions_sync`, `how_was_it_queue`) נבדקו ועברו.

## ⚠️ פער שלא ניתן היה לסגור בסביבה הזו
המפרט דרש "לוודא את שמות השדות מול התיעוד העדכני של CJ לפני הכתיבה (developers.cj.com → Commission Detail API)". **לסביבת הבדיקה הזו אין גישת רשת יוצאת ל-developers.cj.com** (לא WebFetch ולא חיפוש הצליחו להביא את הסכמה המדויקת). כתבתי את ה-GraphQL query (`partner_commissions.py`, שם השדות: `commissionId`, `sid`, `actionStatus`, `advertiserName`, `eventDate`, `postingDate`, `saleAmountPubCurrency`, `pubCommissionAmountPubCurrency`, `pubCurrency`) לפי הידע הכללי שלי על ה-API - **לא מאומת מול תיעוד חי**. זה מתועד גם בראש הקובץ עצמו.

**לפני שמפעילים `CJ_COMMISSIONS_SYNC_ENABLED=true` בפרודקשן: חובה להריץ `sync_cj_commissions()` אחת עם מפתח אמיתי (או query של introspection מול https://commissions.api.cj.com/query) ולוודא ששמות השדות תואמים בפועל.** שם שגוי יגרום לשגיאת GraphQL שתיתפס ותירשם בלוג (`sync_cj_commissions` לעולם לא קורס/זורק) - אבל שום עמלה לא תזוהה עד שהשדות מתוקנים.

## תוצאה
כל הבדיקות שבשליטתי עברו (PASS), עם הסתייגות אחת מתועדת למעלה. ראו commit (יתועד בעדכון הבא).

## הערות
- עמודת ה-sid היא `trip{id}` - בדיוק כפי שכבר קיים ב-`_lodging_partner_url`/`_car_partner_url`.
- עדכנתי את `privacy.html` (עברית ואנגלית) עם המשפט שהתבקש על קבלת אישורי הזמנה מהשותפים.
- "פרופיל נוסע קבוע" (שלב 2 בתוכנית 001) וטיסות (לא עוברות היום דרך שותף שמחזיר קרדיט) - מחוץ להיקף, כפי שנאמר במשימה.
