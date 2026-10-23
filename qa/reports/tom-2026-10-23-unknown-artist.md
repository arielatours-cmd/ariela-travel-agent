# בדיקת PR #173: oholiav-unknown-artist — ✅

- **SHA:** `fc0d5106a1750705debf94ea4edc554224caecef`
- **main:** `082c191d2280c1b5d19f4b115bfdf8344d98912a`. המיזוג נקי.
- **התיקון:** `_is_unknown_artist()` במקום ה-regex. הפונקציה מפרקת את השם למילים (אותיות Unicode), מסירה מילות תפקיד (artist, author, photographer, photo, creator, painter, by), ודוחה כשלא נשאר כלום, כשנשאר רק "n a", "na" או "not known", או כשכל המילים שנשארו הן unknown, anonymous, anon, unidentified או unnamed.
- **ביצעה:** תום, 23.10.2026, עם API מדומה. בלי רשת ובלי בדיקות שעולות כסף.

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | "Unknown artist", "Anonymous (photographer)", "Author unknown", "unknown photographer", "Unknown (photographer)", "Unidentified photographer", "Photo: unknown", `<i>Unknown</i> artist`, "N/A", "Not known" | ✅ כולם נדחים |
| 1 | "Unbekannt" | 🟡 **עובר**. לא נוסף, וגם לא "Inconnu", "Sconosciuto" ו-"Autor desconocido" |
| 2 | false positive: "Anonymous Studio Ltd" | ✅ עובר. לדעתי זה נכון, כי זה שם של גוף ולא "לא ידוע" |
| 2 | "Unknownman", "John Painter", "Anna Photo" | ✅ עוברים (מילות תפקיד מוסרות רק כמילה שלמה, והשם נשאר) |
| 2 | Sailko, Petar Milošević (עם HTML), Diego Delso, User:Diliff, "Thomas Wolf, www.foto-tw.de", "Œil de verre", ארמנית, סינית | ✅ עוברים, השם נקי |
| 2 | "123", "—" או "By" לבד | נדחים, כי אין בהם שם. סביר |
| 3 | span מוסתר מקונן | 🟡 **לא טופל**: `<span style="display:none"><span>a</span>b</span>Name` עדיין מחזיר "bName". נדיר |
| 4 | מיזוג מול main | ✅ נקי |
| 4 | `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים |
| 4 | `qa_attraction_image_credit`, `qa_legal_images`, `qa_attraction_price_display` | ✅ ALL PASS |
| 4 | מוטציה: מילות התפקיד לא מוסרות (`core = list(words)`) | ✅ 8 בדיקות נכשלות |

## הערות לא חוסמות
- 🟡 "לא ידוע" בשפות אחרות עובר: Unbekannt, Inconnu, Sconosciuto, Desconocido. אפשר להוסיף ל-`_UNKNOWN_WORDS`, וגם את "autor" ל-`_ROLE_WORDS`.
- 🟡 ערכים מורכבים שמתחילים ב-"Unknown" עוברים כשלם: "Unknown author / Wikimedia user" ו-"Unknown photographer for the Library of Congress". השני הוא בעצם ייחוס למוסד וסביר שיעבור. הראשון כנראה צריך להידחות. נדיר.
- 🟡 span מוסתר מקונן, כמו בבדיקה הקודמת.
