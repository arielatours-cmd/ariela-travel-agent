# בדיקת PR #181: ron-itin-lang-prompt — ❌ (ממצא 🟠: שינוי בפלט העברי בלי `_lang`, דרך `core_itinerary_text`)

- **SHA:** `a0a09f6b02414b658db84370c6f3f7e5700e4885` (מכיל את 56f4db7e)
- **main:** `a8b6425e9f4a1863e4c97f0df646e5f1f6c08375`. המיזוג נקי.
- **קבצים:** `itinerary_cards.py`, `tools/qa_itinerary_lang_prompt.py`
- **ביצעה:** תום, 24.10.2026, offline לגמרי: post_claude ו-Wikipedia מדומים, בלי האתר החי ובלי רשת.

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | `build_itinerary_days` בלי `_lang`, עם `_lang="he"` ועם `_lang=""`: prompt, context, message ו-days | ✅ זהים ל-main (אותו `_STRUCTURE_PROMPT`) |
| 1 | **`core_itinerary_text` על טקסט עברי בלי `_lang`** | ❌ **הפלט שונה ב-4 מתוך 6 דוגמאות עבריות** (ממצא 1) |
| 2 | `_lang=en` | ✅ הפרומפט מבקש English, ה-context וה-message באנגלית, קריאה אחת. `duration` מהקטלוג נלקח מ-`duration_en` ("2 hours") ולא מ-"משך מומלץ" |
| 2 | `_lang=fr` (אין `duration_fr`) | ✅ אין קריסה. הפרומפט "in French", ו-duration ריק (לא עברי) |
| 2 | `_lang="xx"` ו-`"EN"` | ✅ "in xx" נשלח כמו שהוא. "EN" מנורמל ל-English |
| 3 | אין re.sub או replace על פלט המודל ב-`build_itinerary_days` | ✅ השדות נלקחים כמו שהם (רק strip) |
| 3 | **רשימת מילים על טקסט המודל** | ⚠️ **כן**: ל-`note_start` ב-`core_itinerary_text` נוספה רשימה באנגלית (`note|notes|tip|important|p\.?s\b`), ו-`_DAY_LINE_EN` נוסף. זה regex שמסנן שורות לפי מילים בטקסט המסלול שהמודל כתב (ממצא 1) |
| 4 | גבולות | ✅ ה-diff רק ב-`itinerary_cards.py` ובכלי הבדיקה. לא נוגע ב-`account()` ולא ב-`_chat_destination_codes` |
| 5 | `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים |
| 5 | `qa_itinerary_lang_prompt` | ✅ ALL PASS. גם `qa_attraction_image_credit`, `qa_attraction_price_display` ו-`qa_round4_itinerary_gate_loop` עוברים. (`qa_baggage_and_itinerary_acceptance_by_meaning` נכשל ב-2, **גם על main**, ולא קשור ל-PR) |
| 5 | מוטציה: `_vacation_lang` תמיד מחזיר "he" | ✅ 6 בדיקות נכשלות |

## ממצא 1 — 🟠 `core_itinerary_text` משנה את הפלט העברי גם בלי `_lang`
- **מיקום:** `itinerary_cards.py`, `core_itinerary_text`: `_DAY_LINE_EN` ושורת `note_start`.
- **למה זה חשוב:** הפונקציה משותפת לכל החופשות. היא מכינה את הטקסט שנשלח למודל ב-`build_itinerary_days`, ואת הטקסט שמוצג בעמוד עד שהכרטיסים נבנים (`account.html:426`). לכן השינוי חל גם על חופשות בעברית, בניגוד ל"בלי השדה, אין שום שינוי".
- **שחזור (main מול הענף):**

| קלט עברי | main | PR |
|---|---|---|
| `…יום 2: נוטינג היל\n- Tipperary Pub` | נשאר | **השורה "Tipperary Pub" נמחקת**: `tip` בלי `\b` תופס את תחילת "Tipperary". זה **אובדן של פריט אמיתי** במסלול |
| `…יום 2: פוטסדאם\nNoteworthy: Sanssouci` | נשאר | נמחק (`note` בלי `\b`) |
| `…יום 2: פלאקה\nTip: לקחת כובע` | נשאר | נמחק (כמו שהתכוונו לאנגלית, אבל עכשיו זה חל גם על עברית) |
| `סיכום קצר (Day 1 = יום ההגעה)\nיום 1: פריז…` | ההקדמה נחתכת | **ההקדמה נשארת**, כי `_DAY_LINE_EN` תופס "Day 1" בשורת ההקדמה |
| `…הערה: …\nרוצה שאשנה משהו?` | נחתך | נחתך (זהה) |

- **מול סעיף (3):** זו רשימת מילים באנגלית על טקסט שהמודל כתב, הרחבה של הרשימה העברית שכבר קיימת. אם הכלל חל גם על חיתוך שורות (ולא רק על "תיקון" תוכן), זו הפרה של הכלל.
- **הצעת תיקון (לרון):** להשאיר את `core_itinerary_text` זהה ל-main כשהשפה היא עברית. למשל להוסיף פרמטר `lang` ולהפעיל את `_DAY_LINE_EN` ואת רשימת האנגלית רק כש-`lang != "he"`, ולהוסיף `\b` אחרי `note`, `notes` ו-`tip` (`(?:notes?|tip|important)\b`). אם לא רוצים רשימת מילים בכלל, אפשר לבקש מהמודל ב-FOREIGN להחזיר את הימים בלבד, או לחתוך לפי מבנה ולא לפי מילים. ההחלטה של שקד או שלמה. וכדאי בדיקה שמשווה את `core_itinerary_text` ל-main על דוגמאות עבריות.

## הערות לא חוסמות
- 🟡 `_lang` נכנס לפרומפט כמו שהוא (`{language}`) כשהקוד לא מוכר. היום אף קוד ב-main לא כותב `_lang`, אבל כשזה יתחבר כדאי להגביל ל-`^[a-z]{2,3}$`, כדי שלא ייכנס לפרומפט טקסט חופשי.
- ℹ️ אם המודל יחזיר `name_he` עברי גם בפרומפט FOREIGN, הוא יוצג ב-en (`name_he` קודם ל-`name`). ההוראה למודל ברורה, וזה תלוי בו ולא בקוד.
