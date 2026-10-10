# משימת פיתוח 007א — מדידת שיתוף סריקות ("חיפושים שנחסכו")

תוכנית: [007](../plans/007-scan-sharing-check.md) — מאושר, שלב 1 (מדידה בלבד, **בלי לשנות את לוגיקת הסריקה**)
נוצרה: 2026-10-10

## שינויים
1. **עמודות ב-`scan_runs`** (ALTER TABLE בסגנון הקיים):
   - `reused_coverage_keys INTEGER NOT NULL DEFAULT 0`: כמה קבוצות מסלול-חודש דולגו כי היו טריות.
   - `estimated_requests_saved INTEGER NOT NULL DEFAULT 0`: הערכת הבקשות שנחסכו. לכל קבוצה שדולגה, כמות ה-jobs שלה (מ-`coverage_expected_all`) כפול הבקשות הממוצעות לחיפוש. אם אין נתון, 1 לכל job. לתעד את הנוסחה בקוד.
   - `stopped_by_cap INTEGER NOT NULL DEFAULT 0`: 1 אם הריצה נעצרה ב"עצירת בטיחות".
   - `coverage_groups_completed INTEGER NOT NULL DEFAULT 0`, `coverage_groups_total INTEGER NOT NULL DEFAULT 0`.
2. **`run_customer_trip_search`** (scanner.py ~1432–1591): למלא את העמודות האלה גם בריצה שבה כל הקבוצות נחסכו (`monthly_coverage_reused`), וגם בריצה חלקית. **לא לשנות שום החלטה** (תקרה, חלון, מה נרשם ככיסוי). רק לרשום.
3. **מסך מנהל:** `GET /admin/scan-sharing?days=30&token=...` (JSON):
   - לפי יום: מספר ריצות אישיות, ריצות עם שיתוף מלא או חלקי, `estimated_requests_saved`, ריצות שנעצרו בתקרה, ו-% קבוצות שנסגרו.
   - לפי `scan_type`: אותם מדדים.
   - שורת סיכום: "חיפושים שנחסכו בזכות שיתוף" בתקופה.
4. **דוח על הנתונים הקיימים:** סקריפט `tools/report_scan_sharing_history.py` (קריאה בלבד) שמריץ על ה-DB:
   - כמה ריצות אישיות יש בכלל.
   - כמה הסתיימו ב-`monthly_coverage_reused` (ריצה עם `searches_planned=0` ו-`api_requests=0`).
   - כמה נעצרו ב"עצירת בטיחות" (`error_message LIKE '%עצירת בטיחות%'`).
   - כמה שורות יש ב-`monthly_scan_coverage`, ומה התפלגות `scanned_at`.
   - לפי קבוצת מסלול-חודש: כמה ריצות ביקשו אותה, ובכמה היא נסגרה.
   להריץ אותו מנתיב מנהל: `GET /admin/scan-sharing/history?token=...`.
5. **ai_usage לא רלוונטי.** בלי שינוי.

## קריטריוני קבלה
1. ריצה ששוחזרה במלואה → `reused_coverage_keys>0`, `estimated_requests_saved>0`, `api_requests=0`.
2. ריצה חלקית (חלק טרי) → `reused_coverage_keys` נכון, ושאר הריצה נמשכת כמו היום.
3. ריצה שנעצרה בתקרה → `stopped_by_cap=1`.
4. **אין שום שינוי** בכמות הבקשות או בתוצאות. מוודאים בבדיקת QA שמשווה לפני ואחרי על אותו mock.
5. `/admin/scan-sharing` ו-`/admin/scan-sharing/history` עובדים, ובלי טוקן → 401.
6. מיגרציה רצה פעמיים בלי שגיאה.

## אחרי
בעלת העסק תפתח את `/admin/scan-sharing/history` ותשלח לאופק או ליוסף את התוצאה, ועל פיה נחליט על שלב 2.
