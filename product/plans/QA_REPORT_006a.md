# QA — 006א: אריאלה עונה בוואטסאפ (שלב 1, מספרים מורשים בלבד)

תוכנית: [006](006-whatsapp-inbound-ariela.md) — אושר: שלב 1

## מה נבדק
`tools/qa_whatsapp_inbound_ariela_stage1.py` (payloads אמיתיים לדוגמה של Meta: טקסט, כפתור, interactive, תמונה, סטטוסי מסירה; mock ל-`send_text_message` ול-`_post_claude` - בלי קריאה אמיתית ל-Meta או ל-Anthropic), כולן PASS:
1. בלי `META_APP_SECRET` מוגדר → הבקשה **לא מעובדת כלל** (רק לוג), מחזירה 200 ל-Meta.
2. חתימת `X-Hub-Signature-256` לא תקינה → 403, שום עיבוד.
3. `WHATSAPP_INBOUND_ENABLED=false` → שום תשובה לאף אחד, כולל מספר ב-allowlist. נרשם `ignored_disabled`.
4. מספר לא ב-allowlist → הודעת "בקרוב" **אחת** בלבד תוך 24 שעות, גם כששתי הודעות נשלחות ברצף.
5. מספר מורשה ורשום, עם חתימה תקינה → ההודעה מגיעה למנוע אריאלה האמיתי (`whatsapp_bridge.ariella_turn` → `/api/ariella/chat-clean` דרך Flask test client, עם session אמיתי) והתשובה נשלחת. השיחה נשמרת ב-`ariella_conversations` (`load_ariella_conversation`) - **אותו מנגנון בדיוק** שהאתר משתמש בו, כך שהמשך שיחה בין הערוצים מובטח באופן מבני, לא רק נבדק נקודתית.
6. אותו `wa_message_id` פעמיים → נענה פעם אחת בלבד (השנייה מזוהה כ-duplicate ומתעלמים).
7. הודעת תמונה → תשובת "רק טקסט", אריאלה לא נקראת כלל.
8. webhook עם `statuses` בלבד (אישור מסירה, בלי `messages`) → מתעלמים, בלי קריסה.
9. כפתור `STOP_HOT_DEALS` → מתנהג **בדיוק** כמו ב-003א (לא נגעתי בקוד הזה).
10. תשובה ארוכה (מעל 4,000 תווים) → מתפצלת למספר הודעות נפרדות, לפי סדר הפסקאות, כל אחת בתוך המגבלה.
11. `channel='whatsapp'` ב-`ai_usage`: נבדק ישירות ברמת ה-plumbing (`set_ai_usage_context(channel=...)` → `record_ai_usage`), כי הבדיקה המלאה דרך `chat_clean()` ממוקה את `_post_claude` (שבתוכו `record_ai_usage` עצמו) ולכן לא עובר קריאה אמיתית. ה-wiring בקוד: `chat_clean()` שם `channel='whatsapp'` אך ורק כש-`session['ariella_channel']=='whatsapp'`, דגל שרק `whatsapp_bridge._client_for_member` קובע - שיחה רגילה מהאתר לעולם לא נוגעת בו.

כל חבילת הבדיקות הקיימת (regression suite המלא, כולל כל הבדיקות הקשורות ל-`chat_clean`) נבדקה ועברה אחרי השינוי - **התנהגות האתר לא השתנתה**, כפי שנדרש: `whatsapp_bridge.ariella_turn` קורא ל-`/api/ariella/chat-clean` ולנתבי ה-save-trip-*/start-flight-search/sync-trip-services הקיימים דרך Flask test client, בלי לשכפל אף שורת לוגיקה עסקית שלהם.

## החלטות עיצוב שתועדו בקוד
- **הוצאת ליבת `chat_clean`**: נבחרה החלופה השנייה מהמשימה (לא הוצאה לפונקציה, אלא קריאה לנתיב הקיים עצמו). הסיבה: `chat_clean()` הוא קובץ ענק ושביר (מאות כללי מוצר ספציפיים שנצברו על פני סשנים רבים); קריאה דרך Flask test client עם session אמיתי מבטיחה הבדל התנהגות אפס מול האתר, במחיר תקורת ביצועים קטנה בלבד (קריאת HTTP פנים-תהליכית, לא רשת אמיתית).
- **`whatsapp_conversation_state.saved_domains_json`** (עמודה חדשה): המקבילה השרתית ל-`savedDomainsKey` של `trip_form.html` - בלי זה, כל תור שבו תחום (לינה/רכב/מסלול) כבר "הושלם" היה שולח שוב את `save-trip-lodging`/`save-trip-car`, שכל אחת מהן **מפעילה חיפוש אמיתי** - חיפוש כפול על כל הודעה.
- **`ai_usage.channel`**: נוסף כעמודה (לא קודד בתוך `source`) כדי לא לגעת בשום call site קיים של `_post_claude(..., source=...)` בתוך `chat_clean`.

## מחוץ להיקף (כפי שסוכם מראש)
תוצאות חיפוש מלאות בוואטסאפ עם תמונה וכפתורים (שלב 2); פתיחה לכל הלקוחות והודעות יזומות (שלב 3); Coexistence.

## צריך מבעלת העסק (ליווי אופק)
ב-Render: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `META_APP_SECRET`, `WHATSAPP_INBOUND_ALLOWLIST`, ולבסוף `WHATSAPP_INBOUND_ENABLED=true`. ב-Meta: כתובת ה-webhook ומינוי ל-`messages`.

## תוצאה
כל הבדיקות שבשליטתי עברו (PASS). שום הסתייגות לא נותרה פתוחה מלבד מה שתלוי בהגדרות Render/Meta אצל בעלת העסק (מחוץ לשליטת הסביבה הזו).
