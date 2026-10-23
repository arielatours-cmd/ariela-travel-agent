# בדיקת PR #174: oholiav-lca-commons-image — ✅

- **SHA:** `316feed9caace64e331b25410641207608f1550e`
- **main:** `95c031a0af57c0b5d63d9bf7b0ea945b0c65a6c6`. המיזוג נקי.
- **קבצים:** `database.py` (הוסרה הדריסה של LCA לתמונה הכללית), `static/img/destinations/landmarks.json` (רשומת LCA מסוג replacement), `tools/qa_landmark_images_fix.py`
- **ביצעה:** תום, 23.10.2026. GET חינמיים ל-upload.wikimedia.org ול-commons API, עם User-Agent והפסקות של 4–16 שניות. בלי בדיקות שעולות כסף.

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | רוחב ה-URL | ✅ `…/1280px-Church_of_Saint_Lazarus_–_Front_Façade.jpg` |
| 1 | התמונה נטענת | ✅ GET מחזיר **200** (JPEG 1280×960), ו-Range מחזיר **206** |
| 2 | Commons API: רישיון ויוצר | ✅ `LicenseShortName = CC BY-SA 4.0`, `Artist = Viaggiamocela` (קישור משתמש), `descriptionurl` זהה ל-`page` בקובץ |
| 2 | מה מופיע בתמונה | ✅ **כנסיית לזרוס הקדוש בלרנקה.** ObjectName "Church of Saint Lazarus – Front Façade". הקואורדינטות 34.911789, 33.634790 הן מיקום הכנסייה בלרנקה. קטגוריות: "Churches in Larnaca", "Cultural heritage monuments in Cyprus", ו-Wiki Loves Monuments 2025 Cyprus. בדקתי גם בעין את הקובץ שהורד: הכנסייה האבנית ומגדל הפעמונים, בלי אנשים מזוהים ובלי לוגו |
| 3 | הקרדיט הוא קישור | ✅ `<a class="deal-image-credit" href="https://commons.wikimedia.org/wiki/File:Church_of_Saint_Lazarus_…" target="_blank" rel="noopener">` |
| 3 | bdi בעברית | ✅ `צילום: <bdi>Viaggiamocela / CC BY-SA 4.0</bdi>, דרך Wikimedia Commons` |
| 3 | הנוסח באנגלית | ✅ `Photo: Viaggiamocela / CC BY-SA 4.0, via Wikimedia Commons` |
| 3 | צילום ב-375 | ✅ `img/lca-credit-he-375.png`, `img/lca-credit-en-375.png`. הקרדיט מופיע על התמונה ולא כפתור |
| 4 | אין Unsplash ב-LCA | ✅ `DESTINATION_LANDMARK_IMAGES["LCA"]` הוא ה-URL של Commons. ה-pool הוא [Commons, `_default.webp`]. אין Unsplash באף מפה או pool. 🟡 ר' הערה |
| 5 | מיזוג מול main | ✅ נקי |
| 5 | `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים |
| 5 | `qa_landmark_images_fix`, `qa_legal_images` | ✅ ALL PASS |
| 5 | מוטציה: LCA חוזר לתמונת החוף של Unsplash | ✅ 3 בדיקות נכשלות |
| 5 | מוטציה: `/1280px-` → `/1200px-` ב-LCA | ✅ הבדיקה "every Commons thumbnail is 1280px wide" נכשלת. הבדיקה מ-#165 תופסת גם את זה |

## הערות לא חוסמות
- 🟡 `public_site.py:3346-3366`: בחישוב `trip["image_url"]` עדיין יש כתובות Unsplash, כולל תמונת החוף של LCA (`photo-1507525428034`) והכביש המדברי. בבדיקה של #165 וידאתי שאף template או קוד לא משתמשים ב-`trip["image_url"]`, כך שזה קוד מת בלי השפעה. כדאי לנקות אותו כדי שלא יחזור לשימוש בטעות.
