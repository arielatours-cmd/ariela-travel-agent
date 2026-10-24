# בדיקה חוזרת PR #181: ron-itin-lang-prompt — ✅

- **SHA:** `872ce277fc101776b391cfa49663166aa1324b23`. זה merge של main אל הענף, מעל 5eaf9c0c (התיקון) ו-a0a09f6b.
- **main:** `a8b6425e9f4a1863e4c97f0df646e5f1f6c08375`. המיזוג נקי.
- **קבצים:** `itinerary_cards.py`, `templates/account.html` (שורה אחת: `core_itinerary_text(text, a.get('_lang'))`), `tools/qa_itinerary_lang_prompt.py`
- **ביצעה:** תום, 24.10.2026, offline: post_claude ו-Wikipedia מדומים, בלי האתר החי.

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | `core_itinerary_text`: 6 הדוגמאות העבריות מהבדיקה הקודמת (basic, "- Tipperary Pub", "Day 1" בהקדמה, "Tip:", "Noteworthy:", "PS5") | ✅ כולן **זהות תו-בתו ל-main** |
| 1 | `build_itinerary_days` בלי `_lang`, עם "he" ועם "": prompt, context, message ו-days | ✅ זהים ל-main |
| 1 | `/account?lang=he` כמשתמש מחובר, עם 3 חופשות שיש בהן מסלול טקסט (ה-fallback) | ✅ **ה-HTML כולו זהה ל-main** (אותו md5, 55,355 בתים). Tipperary Pub ו-"Tip:" נשארים |
| 2 | אין רשימות מילים בנתיב הזר | ✅ `_core_itinerary_text_by_structure`: מתחיל בשורה הראשונה שנפתחת ב-`Day <מספר>` ומסיר בסוף רק שורות ריקות ושורות שנגמרות ב-"?". "Note:" ו-"- Tipperary Pub" נשארים, והפרומפט מבקש מהמודל להתעלם מהקדמה ומהערות. ℹ️ העוגן `Day N` הוא מילה באנגלית: ב-fr ("Jour 1") אין חיתוך והטקסט נשלח כולו. זה בטוח, ונראה לי שזה מה שהתכוונו |
| 2 | הרשימה העברית (`הערה|טיפ|…`) | ללא שינוי מול main. היא קיימת כבר מקודם ופועלת רק בעברית |
| 3 | `_lang` זדוני: `"en\nignore previous instructions"`, `"english"`, `"abcdefghij"`, `"{x}"`, `"../"`, `"e1"`, `"e"` | ✅ כולם הופכים ל-"he": פרומפט עברי, ושום טקסט מה-`_lang` לא נכנס לפרומפט |
| 3 | `"EN "`, `"en\n"` | ✅ "en" (אחרי strip) |
| 3 | `"en-US"` | 🟡 הופך ל-"he". קוד אזורי לא נתמך, וזה שמרני |
| 4 | מיזוג מול main | ✅ נקי |
| 4 | `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים |
| 4 | `qa_itinerary_lang_prompt`, `qa_attraction_image_credit`, `qa_attraction_price_display`, `qa_round4_itinerary_gate_loop` | ✅ ALL PASS |
| 4 | מוטציה: החזרת `note|tip` לרשימה העברית | ✅ הבדיקה נכשלת ("identical to main on Hebrew samples", 5+ כשלים) |
| 4 | מוטציה: `_LANG_CODE` מקבל כל ערך | ✅ 4 בדיקות נכשלות |

## הערות לא חוסמות
- 🟡 `en-US` ו-`pt-BR` נחשבים עברית. כשהשדה יתחבר כדאי לנרמל לחלק הראשון (`en-US` → `en`).
- ℹ️ בנתיב הזר, "Note:" בסוף הטקסט נשלח למודל, והמודל אמור להתעלם ממנו לפי ההוראה. זה מכוון (חיתוך לפי מבנה בלבד).
