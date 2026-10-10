# QA — 005א: רישום שימוש ב-Claude API ועלות משוערת

תוכנית: [005](005-ai-usage-tracking.md)

## מה נבדק
- `tools/qa_ai_usage_tracking.py`: `client.messages.create` מדומה עם usage קבוע.
  - קריאה רגילה → שורה ב-`ai_usage` עם `member_id`/`trip_id`/`conversation_id`/`is_test` נכונים וטוקנים תואמים.
  - חישוב עלות לפי מחירון בדיקה (`AI_PRICING_JSON`) תואם בדיוק.
  - מודל בלי מחירון → עלות `None`, בלי ניחוש ובלי קריסה.
  - שגיאת API → שורה עם `error` וטוקנים 0, וה-`RuntimeError` הרגיל עדיין עולה לקורא.
  - כשל כתיבה ל-DB (mock שזורק חריגה בתוך `record_ai_usage`) → **לא** מפיל את קריאת הצ'אט; `_post_claude` מחזיר תשובה כרגיל.
- `/admin/ai-usage`, `/admin/ai-usage.csv`, `/admin/ai-usage/conversation/<id>` — נבדקו עם Flask test client אמיתי (ללא `ADMIN_TOKEN` בסביבת הבדיקה; עם `ADMIN_TOKEN` מוגדר, 401 נבדק).
- כל חבילת הבדיקות הקיימת (regression suite, ~39 סקריפטים ב-scratchpad) הורצה מחדש אחרי השינוי ב-`_post_claude` (פרמטר `source` חדש) — כולן עברו.
- `py_compile` על כל הקבצים שהשתנו.

## תוצאה
כל הבדיקות עברו (PASS). ראו commit: <TO BE FILLED IN FOLLOW-UP COMMIT>.

## הערות ליוסף
- `conversation_id` תמיד `NULL` כרגע: אין בקוד מושג "שיחה" עם מזהה נפרד מ-`member_id` (טבלת `ariella_conversations` ממפתחת לפי `member_id` בלבד, שיחה אחת פעילה ללקוח). `/admin/ai-usage/conversation/<id>` ו-"20 השיחות הגבוהות" לכן ריקים כרגע בפועל — מוכנים ברגע שתיווסף מזהה שיחה אמיתי.
- מחירון claude-sonnet-5 (ARIELLA_MODEL הנוכחי) מולא מדף התמחור הרשמי: קלט $2.00/MTok, פלט $10.00/MTok, קריאת מטמון $0.20/MTok, כתיבת מטמון (ephemeral) $2.50/MTok.
