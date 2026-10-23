# בדיקת PR #162: oholiav-kiwi-affiliate-label — ❌ (ממצא 🟠 אחד: עיצוב בכרטיס הטיסה)

- **SHA:** `07e6e1d1dd419d7b84dd2b22a88f8c671370d22f`
- **main:** המשימה ציינה `767e1ee8b863e1fca7d0992c3e0b5bdb0de7dcce`, אבל בזמן הבדיקה origin/main כבר היה ב-`02e55370e25503363ceada090a2e8cbaa2f77bf4`, ארבעה commits אחריו, ביניהם #159 ו-#160 שנוגעים בכרטיס הטיסה. הבדיקות רצו מול 02e5537. `git merge-tree` נקי מול שניהם (auto-merge ב-`_deal_card.html` וב-`qa_kiwi_affiliate_013a.py`).
- **קבצים:** `templates/_deal_card.html`, `templates/booking_forward.html`, `tools/qa_kiwi_affiliate_013a.py`. אין שינוי בקוד Python של המוצר.
- **ביצעה:** תום, 23.10.2026, ב-worktree נפרד, בלי בדיקות שעולות כסף ובלי האתר החי.

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | רק משפט העמלה הוחלף בתווית שמקשרת ל-`/affiliate-disclosure`. נבדק בכרטיס ובדף ההעברה, he/en | ✅ ב-diff של ה-HTML (main מול המיזוג) רק "אם תזמינו דרך Kiwi.com, אריאלה מקבלת עמלה מ-Kiwi.com." (ובאנגלית "if you book through…commission…") הפכו ל-`<a …href="/affiliate-disclosure">קישור שותף</a> ·`. המשפט "ההזמנה, התשלום… מול Kiwi.com" נשאר במלואו. דף ההעברה עובר עכשיו דרך אותו מאקרו, `kiwi_disclosure` |
| 2 | אזהרת 5.9 (כרטיסים נפרדים) | ✅ השורה ב-`booking_forward.html:32` (בתוך ה-JS) זהה ל-main, בעברית ובאנגלית. ℹ️ ב-`_deal_card.html` אין את האזהרה הזו, גם לא ב-main |
| 3 | אין עברית ב-en ואין אנגלית ב-he | ✅ ב-en: 0 תווים עבריים, בכרטיס ובדף ההעברה. ב-he: האותיות הלטיניות היחידות הן שמות מותג (Kiwi.com, Wizz Air) |
| 3 | RTL | ✅ הטקסט: התווית כולה בעברית, אין ערבוב כיוונים חדש שצריך bdi. ❌ העיצוב בכרטיס: ר' ממצא 1 |
| 4 | קישורי Kiwi לא השתנו | ✅ ה-`href` של כפתור Kiwi (`/go/kiwi/42?trip_id=7`) וה-`redirectUrl` בדף ההעברה זהים ל-main, עם כל הפרמטרים (`from`, `to`, `departure`, `return`, `adults`, `children`, `affilid`, `tid=***`, `aff=***`, `aid=***`, `sid=***`, `utm_source`). `go_kiwi` ו-`kiwi_affiliate_target` לא השתנו |
| 5 | `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים בשניהם |
| 5 | `qa_kiwi_affiliate_013a` | ✅ ALL PASS על הענף ועל המיזוג |
| 5 | `qa_partner_cards_affiliate_label` | ✅ ALL PASS על המיזוג. ℹ️ הקובץ לא קיים בענף עצמו, כי הענף מבוסס על 77f2e1c, לפני שהמבחן נכנס ל-main |
| 6 | מוטציה: החזרת משפט העמלה | ✅ במאקרו (he+en): 8 כשלים. רק ב-`booking_forward`: 4 כשלים. רק האנגלית במאקרו: 4 כשלים |

## ממצא 1 — 🟠 "קישור שותף" מוצג בכרטיס הטיסה ככפתור הזמנה כחול וגדול
- **מיקום:** `templates/_deal_card.html`, מאקרו `kiwi_disclosure`: `<a class="lodging-affiliate-label" …>`. הבעיה נגרמת מה-CSS הקיים ב-`static/site.css:46`: `.deal-price-box a{display:block;width:100%;padding:13px 10px;background:linear-gradient(…deal-blue…);color:white;font-weight:700}` וגם ב-`:1294`: `.deal-card-v970 .deal-price-box a{font-size:18px!important;padding:16px 12px}`.
- **מה קורה:** בלוק Kiwi נמצא בתוך `.deal-price-box`. לכן כל `<a>` בתוכו מקבל את העיצוב של כפתור ההזמנה הראשי. התווית "קישור שותף" / "Affiliate link" מוצגת כפס כחול ברוחב מלא, בגופן 18px, ונראית ככפתור הזמנה שני מתחת ל"לבדוק גם ב-Kiwi.com". ה-"·" נשאר יתום בתחילת השורה הבאה. ל-`lodging-affiliate-label` אין CSS משלו בשום מקום.
- **דף ההעברה (`booking_forward.html`) תקין:** שם התווית היא קישור רגיל בתוך המסגרת (`img/kiwi-label-forward-pr162-he.png`).
- **שחזור:** לרנדר `kiwi_affiliate(offer, lang)` בתוך `<article class="ariella-deal-card deal-card-v970"><div class="deal-price-box">…` עם `static/site.css`, ולצלם ב-Chromium headless. צילומים:
  - `img/kiwi-label-card-main-he.png`: main, משפט רגיל.
  - `img/kiwi-label-card-pr162-he.png`: PR, כפתור כחול "קישור שותף".
  - `img/kiwi-label-card-pr162-en.png`: PR, כפתור כחול "Affiliate link".
- **למה הבדיקות לא תפסו את זה:** `qa_kiwi_affiliate_013a` בודק מחרוזות HTML ולא עיצוב.
- **הצעת תיקון (לעידו):** כלל CSS ממוקד, למשל
  `.ariella-deal-card .deal-price-box .kiwi-affiliate .affiliate-disclosure a{display:inline;width:auto;padding:0!important;background:none;color:inherit;font-size:inherit!important;font-weight:700;text-decoration:underline;border-radius:0;max-width:none}`
  ומומלץ להוסיף לבדיקה תנאי שהכלל קיים.

## הערות לא חוסמות
- 🟡 שם המחלקה `lodging-affiliate-label` משמש עכשיו גם לטיסות, ואין לו CSS משלו. מחלקה כללית כמו `affiliate-label`, עם עיצוב אחד, הייתה פותרת גם את ממצא 1.
- 🟡 `{% from "_deal_card.html" import kiwi_disclosure %}` נמצא בין `<!doctype>` ל-`<html>`, ולכן בפלט של דף ההעברה נוספת שורה ריקה. אין לזה השפעה.
- ℹ️ בצילום של main, דף ההעברה מציג את משפט העמלה המלא בתיבה, ובענף את התווית ואחריה המשפט על ההזמנה. השינוי מכוון.
