# בדיקה חוזרת: ron-missed-reasons-en — ✅

- **SHA שנבדק:** `618a32efd9b46e6d99f28a0f04e250bd3f0d069a`. זה הקצה של הענף ב-origin. הוא כולל את `f0e5a6ac26b5c0574947190b5c67b68fd660e9c0`, שעליו נשלחה המשימה, ועוד commit אחד אחריו: `618a32e run_qa: גם "Outbound time (לילה)" בדוגמאות`.
- **main:** `7dec284c423993cead0c879e2fc7a75cb0b9731d`. הענף 2 commits מאחורי main. `git merge-tree` נקי (auto-merge ב-public_site.py, בלי קונפליקט).
- **השינוי מאז f7d2dad:** פונקציה חדשה `_time_pref_label_en(label, pref)`. ארבע התבניות ב-`_MISSED_REASON_PATTERNS_EN` ושתי הקריאות ב-`_objective_match_details` עוברות דרכה. ב-`qa/run_qa.py` נוספו 3 דוגמאות "לילה" ובדיקה ישירה של `_time_pref_label_en`.
- **ביצעה:** תום, 23.10.2026, ב-worktree נפרד, בלי בדיקות שעולות כסף ובלי האתר החי.

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | ערכים לא מוכרים "לילה", "שחר", "מאוחר" ו-"late night", בהלוך ובחזור, בשני הנתיבים | ✅ אין עברית ב-en |
| 1א | נתיב הרינדור (`_missed_reason_en`): 32 תוויות שמורות (4 צורות × 8 ערכים) | ✅ ערך עברי לא מוכר מוצג כ-`Outbound time` / `Return time`. ערך מוכר מוצג כ-`(morning/afternoon/evening)` |
| 1ב | נתיב הבקשה (`_objective_match_details` עם lang=en) | ✅ אותה תוצאה |
| 1ג | כרטיס `deal_card` מלא ב-en עם 34 סיבות | ✅ 0 תווים עבריים בשורת "Missing:" |
| 2 | עברית: `deal_card(lang='he')` ו-`_objective_match_details` עם lang=he, main מול הענף | ✅ זהה תו-בתו |
| 3 | `python3 qa/run_qa.py` על הענף | ✅ 0 כשלים. "תרגום 'לא כולל'": 34 תוויות |
| 3 | `python3 qa/run_qa.py` על המיזוג מול 7dec284 | ✅ 0 כשלים |
| 4א | מוטציה: החזרת `get(x, x)` בארבע התבניות | ✅ run_qa נכשל (3 כשלים) |
| 4ב | מוטציה: החזרת `get(x, x)` בתוך `_time_pref_label_en` | ✅ run_qa נכשל (4 כשלים) |
| 4ג | מוטציה: החזרת `get(x, x)` רק בקריאה של "חזור" ב-`_objective_match_details` | ⚠️ run_qa לא נכשל. ר' הערה 1 |

## הערות לא חוסמות
1. 🟡 **אין הגנה ב-run_qa על נתיב הבקשה.** אם מישהו יחזיר את `get(x, x)` ב-`_objective_match_details`, run_qa לא ייכשל. הלקוח עדיין לא יראה עברית: הכרטיס ב-en מעביר כל סיבה דרך המסנן `missed_reason_en`, וזה המקום היחיד שבו `request_missed_reasons` מוצג (`templates/_deal_card.html`). המסנן מתרגם את "Return time (לילה)" ל-"Return time". כלומר יש הגנה כפולה, אבל רק אחת מהן נבדקת. אם רוצים לסגור את הפער: בדיקה ב-run_qa שקוראת ל-`_objective_match_details` עם `return_time_preference="לילה"` בהקשר en ומוודאת שאין עברית.
2. 🟡 **ערך לא מוכר באנגלית נשאר בסוגריים כמו שהוא.** "late night" מוצג כ-`Return time (late night)`, ו-"Morning" כ-`(Morning)` עם M גדולה. זה לא מפר את הכלל (אין עברית), אבל זה לא בדיוק "ערך לא מוכר יוצג כ-Return time" כמו שנוסח. השאלה אם זה בסדר היא החלטה של מוצר.
3. ℹ️ מבין הדוגמאות החדשות ב-run_qa, "שעת טיסה הלוך (לילה)" בעברית לא נבדקת ישירות. היא מכוסה בעקיפין: התבנית זהה, ומוטציה 4א נתפסה גם בלעדיה.


---

# עדכון: בדיקה על ה-HEAD הסופי — ✅

- **SHA שנבדק:** `2319cfb8a34e4c633ed11e43ed8ea489bee8992a`. כולל את f0e5a6a, את 618a32e ואת `2319cfb אנגלית: "מחיר משתלם" מתורגם "Good price" גם בסקי`.
- **main:** `7dec284c423993cead0c879e2fc7a75cb0b9731d`. `git merge-tree` נקי.
- **שינוי מאז 618a32e:** שורה אחת, `public_site.py:678`, ב-`_ski_selected_condition_details`: `"Good value"` הפך ל-`"Good price"`.

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | "לילה", "שחר", "מאוחר" ו-"late night", בהלוך ובחזור, בשני הנתיבים, וכרטיס מלא ב-en | ✅ 0 תווים עבריים |
| 2 | עברית: `deal_card(he)` ו-`_objective_match_details(he)`, main מול הענף | ✅ זהה תו-בתו |
| 3 | `run_qa` על הענף ועל המיזוג מול 7dec284 | ✅ 0 כשלים בשניהם (34 תוויות) |
| 4 | מוטציות: `get(x, x)` בתבניות / בתוך `_time_pref_label_en` | ✅ run_qa נכשל (3 / 4 כשלים) |
| 5 | "Good value" ב-en | ✅ לא מופיע ב-`templates/`, ב-`*.py` או ב-`static/`, ולא בכרטיס סקי מלא ב-en. ב-en מופיע "Good price" |
| 6 | הקומיט של הסקי לא משנה עברית | ✅ התוויות העבריות של `_ski_selected_condition_details` זהות ל-main (10 תוויות, אחרי מיון). `missed` בעברית ו-`deal_card(he)` של דיל סקי זהים תו-בתו. גם `/trip/new` בעברית, כמשתמש מחובר, זהה |

## הערות לא חוסמות (בנוסף ל-1–3 למעלה)
4. 🟡 "Good value" נשאר רק בקובץ `trip_form.html` שבשורש המאגר (שורה 319). זה עותק ישן שלא בשימוש: `render_template("trip_form.html")` טוען את `templates/trip_form.html`, ושם המחרוזת לא קיימת. אין לזה השפעה על הלקוח, אבל כדאי למחוק את הקובץ הישן או לעדכן אותו כדי שלא יבלבל.
5. ℹ️ סדר התוויות בסקי משתנה מריצה לריצה, כי `priorities` הוא `set`. זה קיים כבר ב-main ולא נגרם בענף. בכרטיס זה מתבטא בסדר שונה של "לא כולל:" בין טעינות של העמוד.
