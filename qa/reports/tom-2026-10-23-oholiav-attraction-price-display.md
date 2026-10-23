# בדיקת ענף: #148 oholiav-attraction-price-display — ✅

- **SHA:** `68314cf7e93a1bb0d86ff580e43c079ac12d59fb`
- **main:** `77f2e1c85cde24bbff1d25d44170cd27f9164f6b`. הענף מבוסס על `bab0dd1` (1 מאחור, 4 קדימה). הבדיקות רצו על מיזוג מקומי של הענף לתוך main.
- **קבצים:** `itinerary_cards.py`, `public_site.py` (שתי שורות ב-context processor), `templates/account.html`, `tools/qa_attraction_price_display.py` (חדש), `tools/qa_attraction_prices.py`. לא נוגע ב-`ariella_chat_clean.py`.
- **ביצעה:** תום, 23.10.2026, ב-worktree נפרד, בלי בדיקות שעולות כסף ובלי האתר החי.

| בדיקה | תוצאה |
|---|---|
| א. `git merge-tree --write-tree origin/main origin/<branch>` | ✅ נקי (auto-merge ב-public_site.py וב-account.html) |
| ב. `python3 qa/run_qa.py` (על הענף ועל המיזוג) | ✅ 0 כשלים |
| ג. `qa_attraction_price_display.py` (חדש) | ✅ ALL PASS, כולל רינדור עמוד בעברית ובאנגלית |
| ג. `qa_attraction_prices.py` (עודכן) ושאר tools/qa_* הרלוונטיים | ✅ הכל עובר |
| ד. השוואת עברית (render_pages + render_member_pages) | ✅ זהה (ר' מגבלה) |
| ה. קריאת ה-diff | ✅ |

## קריאת ה-diff
- בגרסה האנגלית אין שורת מחיר: `account.html` משתמש ב-`attraction_price_view(...) if site_lang != 'en' else none`. כך לא מוצג בה הנוסח העברי של דין. הקישורים נשארים, בטקסט אנגלי.
- בעברית השינוי מכוון: הוסר המחיר בטקסט החופשי (`🎟 {{ item.price }}` ו-"מחיר כניסה:"). מוצגת רק שורה מאומתת לפי `attraction_price_view`, ורק עם הנוסח של דין (`PRICE_TEXT` / `PRICE_TEXT_PER_ADULT` / "כניסה חינם").
- קישור הכרטיסים מסונן דרך `attraction_tickets_url`: מותר רק אותו דומיין כמו האתר הרשמי, או מפעיל מתוך רשימה ידנית. דומיין שמתחזה לאתר הרשמי (`colosseo.it.evil.example`) נחסם, והמבחן מכסה את זה. אין URL גולמי בטקסט, רק ב-`href`.

## בדיקות קצה נוספות שלי (`attraction_price_view`, today=23.10.2026)
| מקרה | תוצאה | הערה |
|---|---|---|
| `adults: "2"` (מחרוזת) | "לאדם" | ✅ |
| טופס אתר: `age_groups: ["children"]` (קבוצה, לא גיל) + `price_child` שונה | "למבוגר … × 3" | ✅ שמרני: גיל שלא מזוהה לא נחשב "לאדם" |
| גילים כמחרוזות `["3","4"]`, `free_under_age=5` | "× 2" (רק המבוגרים) | ✅ ילדים שבוודאות בחינם לא נספרים |
| מחיר 18.5 | "€18.50" | ✅ |
| טווח עם en-dash "6–11", ילד בן 12 | "לאדם" | ✅ |
| 12000 HUF ל-3 אנשים | "12,000 HUF" | ✅ במטבע המקור |
| `price_checked_at` עם שעה | מוצג | ✅ |

## הערות לא חוסמות
- 🟡 `free_under_age` כמחרוזת ("5") לא נלקח בחשבון (`itinerary_cards.py`, `_same_price_for_everyone` / `_certainly_free_children` דורשים `int`). ילד בן 3 יקבל אז "לאדם", למרות שהוא נכנס בחינם. כרגע בכל הנתונים ב-`data/attractions_*.json` השדה הוא int (9/9) או null, ולכן זה לא קורה היום. ההגנה טובה לייבוא עתידי.
- 🟡 קבוצה של 0 מבוגרים שבה כל הילדים בחינם מקבלת "לפי מחיר מבוגר × 1: כ-€18", בגלל `max(1, …)`. זה מקרה לא מציאותי.
- 🟡 שני ערכי `child_age_range` בנתונים מותנים באזרחות: "6-24 (לא-EU, כרטיס מוזל)" ו-"עד 17 (לא-אזרחי EU)". הם מפוענחים כטווח רגיל. התוצאה שמרנית (נוסח "למבוגר"), אבל כדאי שדין ידע.
- 🟡 סגנון: `from datetime import ...` נמצא אחרי `urllib` עם שורה ריקה (`itinerary_cards.py:19`), ו-`urlsplit` מיובא בתוך `_host`. אין לזה השפעה.
- ℹ️ מגבלה של השוואת הרינדור: עם DB ריק אין כרטיסי מסלול. כרטיסי המסלול מכוסים במבחן החדש, שמרנדר עמוד עם נתונים בשתי השפות.
