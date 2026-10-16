# משימת פיתוח 010א — כרטיס לקוח: רשימת נוסעים מצטברת, "מי מצטרף הפעם?" והעדפות שמאושרות מול הלקוח

תוכנית: [010](../plans/010-customer-profile.md) — מאושר (2026-10-12)
נוצרה: 2026-10-12
**עדכון 16.10 (החלטת בעלת העסק דרך שלמה):** שלב 1 עובר לעידו דרך בצלאל, בתור **אחרי** תיקוני דין ל-013א ואחרי 011א. ב-15.10 המשימה לא הגיעה אליו בפועל, וזה תוקן. שלבים 2–3 ממתינים עד שבצלאל יסיים את איחוד זיכרון החופשה. מבצעים commit לכל שלב.

## שלב 1 — רשימת נוסעים מצטברת ועמוד "הפרופיל שלי"
### נתונים
טבלה חדשה (database.py, `CREATE TABLE IF NOT EXISTS`):
```sql
CREATE TABLE IF NOT EXISTS member_travelers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    kind TEXT NOT NULL,              -- 'adult' | 'child' | 'infant'
    first_name TEXT,                 -- רק אם הלקוח אמר
    relationship TEXT,               -- למשל 'partner', 'son', 'daughter' (רק אם נאמר)
    gender TEXT,                     -- 'male' | 'female' | NULL
    age_at_record INTEGER,           -- לילדים/תינוקות; NULL למבוגר
    age_recorded_at TEXT,            -- ISO date
    source TEXT NOT NULL,            -- 'said_in_chat' | 'edited_by_customer'
    needs_review INTEGER NOT NULL DEFAULT 0,
    last_travelled_at TEXT,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    FOREIGN KEY(member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_member_travelers_member ON member_travelers(member_id);
```
- **מיגרציה חד-פעמית:** שורות קיימות מ-`ariella_travel_companions` (travel_agents.py:64) מועתקות ל-`member_travelers` כ-`kind='adult'` עם first_name ו-relationship. את הטבלה הישנה לא מוחקים.
- `delete_member_account` מוחק גם את `member_travelers` וגם את `member_preferences`.

### לוגיקה: `sync_trip_travelers(member_id, travelers, trip_date)`, מודול חדש `member_profile.py`
- נקראת כשנוצרת או מתחילה חופשה (באותו מקום שבו `start_flight_search` יוצר את `trip_requests`), עם `travelers` מתוך trip_state (`adults`, `child_ages`, `child_genders`).
- **גיל משוער היום** = `age_at_record` + השנים השלמות שעברו מאז `age_recorded_at`.
- **ילדים:** לכל ילד בחופשה מחפשים ילד קיים (לא מחוק) עם אותו מגדר (או מגדר לא ידוע אצל אחד מהם) והפרש של עד 1 בין הגיל המשוער לגיל החדש.
  - **התאמה אחת:** מעדכנים את `age_at_record`, `age_recorded_at` ו-`last_travelled_at`.
  - **אין התאמה:** מוסיפים ילד חדש.
  - **יותר מהתאמה אחת:** מוסיפים ילד חדש עם `needs_review=1`. לא ממזגים.
  - ילדים שכבר ברשימה ולא נסעו הפעם **נשארים**. הרשימה מצטברת.
- **מבוגרים:** אם `adults` גדול ממספר המבוגרים הידועים, כולל בעל החשבון, מוסיפים מבוגרים בלי שם. מבוגר עם שם מגיע מ-companions או מהשיחה.
- **ילד שהגיל המשוער שלו 18 ומעלה:** בתצוגה הוא נחשב מבוגר. ברשומה מעדכנים `kind='adult'`.
### ממשק: "מה אריאלה זוכרת עליי"
- באזור האישי (templates/account.html), אזור קטן ונפתח: רשימת הנוסעים ("ילד, בערך בן 10", "ילדה, בערך בת 17", "בן/בת זוג"), וליד כל אחד [תיקון גיל] ו-[מחיקה]. שורות עם `needs_review` מסומנות בעדינות: "ייתכן שזה אותו ילד, תקנו אם צריך".
- נתיבים: `POST /account/travelers/<id>/update` (גיל ומגדר), `POST /account/travelers/<id>/delete`, עם `@login_required` ובדיקת בעלות.

## שלב 2 — "מי מצטרף הפעם?" בשיחה
- בתחילת חופשה חדשה (`chat_clean`, כשאין `travelers` ב-trip_state הנוכחי), אם יש ללקוח נוסעים פעילים: להוסיף ל-`system_dynamic` הקשר קצר, למשל: "נוסעים ידועים של הלקוח: מבוגר נוסף (בן/בת זוג); ילד ~10; ילדה ~17. אם מתאים, שאלי שאלה אחת טבעית: 'מי מצטרף הפעם?', ומלאי את travelers לפי התשובה. אל תמלאי בלי תשובה מפורשת."
- **אסור** למלא את `travelers` אוטומטית.
- גם בוואטסאפ, כי אותו מנוע משמש את שניהם (006א).

## שלב 3 — העדפות מוסקות שמאושרות מול הלקוח
- טבלה `member_preferences` (member_id PK, `prefs_json`, updated_at). ב-JSON: `origin_airport`, `checked_bag`, `direct_tendency` (0–1), `liked_destinations`, `disliked_destinations`, ולכל שדה `source` ו-`updated_at`.
- **עדכון:** מתוך `booking_clicks` (מה נבחר בפועל), מהזמנות מאושרות (001א) ומדירוגי "איך היה?" (`trip_feedback`).
- **שימוש:** בתחילת חופשה, `system_dynamic` מקבל "העדפות משוערות (לא מאושרות): ישירה, מנתב\"ג, עם מזוודה". ההנחיה: לשאול **שאלת אישור אחת מאוחדת**: "כרגיל: ישירה מנתב\"ג, עם מזוודה?". רק מה שהלקוח אישר נכנס ל-trip_state.
- **דירוג:** משקל קטן ב-`_customer_rank_value` לפי ההעדפות. אף פעם לא מסנן קשיח.

## קריטריוני קבלה
1. חופשה ראשונה עם ילד בן 9: נוספת שורה אחת. חופשה אחרי 6 חודשים עם ילדה בת 16: שתי שורות. אחרי שנה, ילד בן 10: עדכון השורה הקיימת, בלי שורה שלישית.
2. שני ילדים בני 9 ו-10 בלי מגדר, ואז "ילד בן 10": `needs_review=1`, בלי מיזוג.
3. ילד שלא נסע הפעם נשאר ברשימה.
4. מחיקה מ"הפרופיל שלי" מסמנת `deleted_at`, והרשומה לא חוזרת בהצעות. מחיקת החשבון מוחקת את הכל.
5. בשיחה חדשה עם נוסעים ידועים, אריאלה שואלת "מי מצטרף הפעם?", ו-`travelers` **לא** מתמלא לפני תשובה.
6. העדפות: שאלת אישור אחת. אחרי "לשנות", לא נכנס כלום מההעדפות. בלי העדפות שמורות, אין שאלה.
7. **האתר לא השתנה** ללקוח חדש בלי היסטוריה. כל חבילת הבדיקות עוברת.
8. לקוח אחר לא יכול לערוך או למחוק נוסע שלא שלו (403/404).

## בדיקות QA
- סקריפט ב-tools/ על DB זמני לתרחישים 1–4, 8.
- בדיקת שיחה עם mock ל-Claude: ההקשר נכנס ל-`system_dynamic`, ו-`travelers` לא מתמלא לבד (תרחישים 5–6).
- עדכון privacy.html: שמירת גילאי נוסעים והעדפות, וזכות לעיין ולמחוק.
