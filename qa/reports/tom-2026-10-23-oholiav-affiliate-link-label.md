# בדיקת ענף: oholiav-affiliate-link-label — ✅

- **SHA:** `96a01f414d0d02e0da2feef7ab266c3e93a242bc` (לא cc5f5a4: עידו כבר ביסס את הענף מחדש על main)
- **main:** `77f2e1c85cde24bbff1d25d44170cd27f9164f6b`. הענף מבוסס עליו ישירות (0 מאחור, 1 קדימה).
- **קבצים:** `templates/account.html`, `tools/qa_kiwi_affiliate_013a.py`, `tools/qa_partner_cards_affiliate_label.py` (חדש). לא נוגע ב-`ariella_chat_clean.py`.
- **ביצעה:** תום, 23.10.2026, ב-worktree נפרד, בלי בדיקות שעולות כסף ובלי האתר החי.

| בדיקה | תוצאה |
|---|---|
| א. `git merge-tree --write-tree origin/main origin/<branch>` | ✅ נקי, בלי קונפליקט |
| ב. `python3 qa/run_qa.py` | ✅ 0 כשלים (65 עמודים × מבקר/מחובר, 200 מקרים) |
| ג. tools/qa_* (lodging_* ×11, affiliate_link_html_guard, kiwi_affiliate_013a, deal_card_en_baggage_overlap, pinned_offer_condition_labels, budget_currency_and_scale, vacation_flights_not_shown_fallback, attraction_prices) | ✅ הכל עובר |
| ג. הקובץ החדש `qa_partner_cards_affiliate_label.py` | ✅ ALL PASS |
| ד. השוואת עברית (`render_pages` + `render_member_pages`, main מול הענף) | ✅ כל העמודים זהים (ר' מגבלה בהערות) |
| ה. קריאת ה-diff | ✅ |

## קריאת ה-diff
- `templates/account.html:209`, `:350`: המשפט "קישור שותף: אם תזמינו דרך X, אריאלה מקבלת עמלה מהספק" בכרטיסי הלינה והרכב הוחלף בתווית `קישור שותף` / `Affiliate link`. התווית מקשרת ל-`site.affiliates` (`/affiliate-disclosure`), כמו התווית הקיימת מ-#153 (`:259`).
- התרגום מוגבל ל-`site_lang == 'en'`. במבחן החדש בגרסה האנגלית אין "קישור שותף" ואין "commission", ואין URL גולמי בטקסט.
- השינוי בעברית מכוון: המשפט הארוך נעלם והתווית הקצרה נשארת. דין אישר את הנוסח.
- `qa_kiwi_affiliate_013a.py`: הבדיקה הישנה, שספרה את המשפט הארוך, הוחלפה בבדיקה שמחפשת בדיוק 3 תוויות-קישור ומוודאת שהמשפט הישן לא קיים. הבדיקה מחמירה, לא מוחלשת.

## הערות לא חוסמות
- 🟡 הקישור `url_for('site.affiliates')` נבנה בלי `?lang=`. זה לא באג, כי השפה נשמרת ב-session (`public_site.py:_lang`). אותו דבר קורה בתווית הקיימת.
- 🟡 שם המחלקה `lodging-affiliate-label` מופיע גם על כרטיס הרכב (`:350`). זה נכון בעיצוב, השם רק קצת מטעה.
- ℹ️ מגבלה של השוואת הרינדור: הכלים מרנדרים עם DB ריק, ולכן כרטיסי השותפים לא מופיעים בעמודים בכלל. הכרטיסים עצמם מכוסים במבחן החדש, שמרנדר את הפאנל עם נתונים.
- ℹ️ בכלי `qa/tools/render_pages.py` הכתובת `/affiliates` מחזירה 404 בשני הצדדים. הנתיב האמיתי הוא `/affiliate-disclosure`, וכדאי לתקן את רשימת ה-URLs בכלי.
