# בדיקה חוזרת PR #170: oholiav-attraction-image-credit — ✅

- **SHA:** `cb0971dddefc7eec8f63e58c291ae37a593d978d` (rebase על main: e6a0d19 + cb0971d)
- **main:** `2ce7bef3a2e3b56a015e2faac246e38772826f63`. המיזוג נקי.
- **התיקון:** `_commons_text()` מסיר קודם רכיבים עם `display:none`, אחר כך את שאר התגים, ומפענח entities עד 3 פעמים. נוסף `_UNKNOWN_ARTIST`. NC/ND נבדקים על `license_name.lower()`. ב-account.html נוסף `<bdi>` בעברית.
- **ביצעה:** תום, 23.10.2026. Commons API, קריאה בלבד, בהפסקות של 4–16 שניות. en.wikipedia.org עדיין חסום בסביבה הזו (proxy 403).

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | הקובץ האמיתי `File:Ponte Vecchio, Florence.jpg` (Anonymous + span מוסתר) | ✅ נדחה (`None`) |
| 2 | "Unknown author", "Anonymous", "unknown", "Unknown photographer", `<i>Unknown</i>` | ✅ נדחים |
| 2 | יוצר אמיתי עם HTML: Sailko (קובץ אמיתי, CC BY 3.0) ו-Petar Milošević (קובץ אמיתי, CC BY-SA 4.0) | ✅ עוברים, השם נקי |
| 2 | `<div style="DISPLAY: NONE">x</div>Real Name` | ✅ "Real Name" |
| 3 | `cc by-nc 2.0`, `CC BY-NC-ND`, `cc-by-nd 4.0` | ✅ נדחים |
| 3 | `cc by-sa 4.0`, `CC BY-SA 4.0` | ✅ עוברים |
| 4 | `Tom &amp;amp; Jerry`, `Tom &amp; Jerry` | ✅ "Tom & Jerry" |
| 4 | `A &lt;b&gt;` | ✅ "A <b>" כטקסט. Jinja עושה escape בתבנית, ולכן אין הזרקה |
| 5 | bdi בעברית | ✅ `צילום: <bdi>Petar Milošević / CC BY-SA 4.0</bdi>, דרך Wikimedia Commons`. ב-375 הסדר נכון והפסיק בצד הנכון (`img/attr-credit2-bdi-he-375.png`). ב-en אין bdi ואין צורך בו |
| 6 | מיזוג מול main | ✅ נקי |
| 6 | `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים |
| 6 | `qa_attraction_image_credit`, `qa_attraction_price_display`, `qa_attraction_prices`, `qa_legal_images` | ✅ ALL PASS |
| 6 | מוטציה: הסרת בדיקת NC/ND | ✅ 3 בדיקות נכשלות (כולל 'cc by-nc') |
| 6 | מוטציה: הסרת `_UNKNOWN_ARTIST` | ✅ 5 בדיקות נכשלות (כולל Ponte Vecchio האמיתי) |

## הערות לא חוסמות
- 🟡 **"Unknown artist"** ו-**"Anonymous (photographer)"** עוברים. `_UNKNOWN_ARTIST` מכסה רק author/photographer, ורק התאמה מלאה. "Unknown artist" נפוץ ב-Commons. הצעה: להוסיף `artist` לרשימה, או לדחות כל שם שמתחיל ב-unknown/anonymous.
- 🟡 span מוסתר מקונן (`<span style="display:none"><span>a</span>b</span>Name`) מחזיר "bName". ה-regex הלא-חמדן נעצר ב-`</span>` הראשון. זה נדיר ב-Commons.
- ℹ️ ב-cb0971d יש גם שינויים מ-main אחרי ה-rebase (`plan_from_tab` מ-#166). הם לא חלק מהתיקון.
