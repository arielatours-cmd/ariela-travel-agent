# משימת פיתוח 009א: סמל 🛡️ רק כשבוודאות, הסתרת "יש לבדוק", וסמלים באתר

תוכנית: [009](../plans/009-flexibility-and-protection-badges.md). **שלב 1 בלבד.** שלבים 2–3 לא אושרו: אין טבלת fare families ואין וואטסאפ.
אישור: בעלת העסק, 14.10.2026, דרך שלמה ("1 כן רק שלב 1"). נרשם ב-ceo/DECISIONS.md.
**תלות:** בונים על din_agent.py אחרי ש-PR #28 של דין (ענף din, ‏f3219f1) ממוזג ל-main. **לא מתחילים לפני שהוא ממוזג**, ולא משכפלים ממנו לוגיקה.

## מה כבר נכנס ב-PR #28 (לא לשנות)
- `enrich_offer_legal_terms`: הגנת הצרכן ותנאי השינוי נבדקים רק כש-`booking_supplier_is_direct is True`. אחרת הסטטוס `check`.
- `_fare_text` משתמש רק בחבילת התעריף שהמחיר שלה תואם למחיר המוצג (‎±1 ₪).
- ניסוח מסויג או שלילי (`_UNCERTAIN_CHANGE_RE`, `_LAW_LIMIT_RE`) מחזיר `check`.

## מה לבנות
### 1. טבלת ספקים: `data/supplier_protection.json`
- רשומה לכל ספק ב-`APPROVED_BOOKING_SUPPLIERS` (scanner.py:296: trip.com, booking.com, expedia, lastminute.com), ורשומה כללית `"direct_airline"`.
- שדות: `israeli_seller` (true/false/null), `consumer_law_applies` ("applies" / "not_applies" / "unknown"), `source`, `checked_at`, `approved_by_owner` (bool).
- **ערך ההתחלה של כל רשומה: `"unknown"` ו-`approved_by_owner: false`.** את התוכן ממלא אופק ידנית, בעלת העסק מאשרת דרך שלמה, ורצוי שגם עו"ד יעבור. הקוד לא ממציא ערכים.
- פונקציה `supplier_protection(supplier_name, is_direct) -> "applies" | "not_applies" | "unknown"`. מחזירה ערך שאינו unknown **רק** כשקיימת רשומה עם `approved_by_owner: true`.

### 2. לוגיקה (din_agent.py, אחרי #28)
- `consumer_protection` לפי סדר עדיפויות:
  (א) הטבלה. אם הספק מאושר ו-applies, מחזירים applies. אם not_applies, מחזירים not_applies.
  (ב) אחרת, התוצאה הקיימת של #28: רק ישיר, ורק עם אזכור מפורש וללא סייג.
  (ג) אחרת `check`.
- `change_cancel`: אין שינוי בשלב 1. נשאר כמו ב-#28.

### 3. הסתרה (database.py:1153–1175)
- סטטוס `check` / `unknown` → `consumer_protection_label = ""`, ובלי class.
- ברירת המחדל "בכפוף לתנאי הספק" ו-"יש לבדוק..." → `change_cancel_label = ""`.
- המסננים ב-public_site.py:1005 (`flexible_ticket`) ממשיכים לעבוד, כי תווית ריקה פירושה "לא גמיש/לא ידוע".

### 4. תצוגה (templates/_deal_card.html, המאקרו `important_terms`)
- במקום שתי שורות `dl`, שורה אחת של עד 2 סמלים, ורק לסמלים שיש להם תווית:
  - 🛡️ "מוגן בחוק", **רק** כש-applies.
  - 🔁 עם `change_cancel_label`, רק כשהיא לא ריקה (גמיש / שינוי בתשלום / ללא החזר).
- אם אין שום תווית, לא מציגים כלום. בלי כותרת ובלי "יש לבדוק".
- לחיצה על סמל פותחת `<details>` קטן עם ההסבר, המקור (`legal_sources`) ותאריך הבדיקה (`legal_checked_at`).
- **הנוסח של 🛡️ בחלונית:** "מוגן בחוק הגנת הצרכן", עם קישור לעמוד הסבר קיים. **בלי** ימים, אחוזים או סכומים עד שעו"ד יאשר (לפי התוכנית, סעיף "פרטיות ומשפט").
- גרסה באנגלית: "Protected by Israeli consumer law" / "Flexible" / "Change for a fee" / "Non-refundable".
- `data-protection` / `data-change` ב-article נשארים, למסננים.

## בדיקות (לשקד)
1. ספק שאינו ישיר, בלי רשומה מאושרת → אין 🛡️ ואין "יש לבדוק".
2. רשומה `applies` עם `approved_by_owner: false` → אין 🛡️.
3. רשומה `applies` עם `approved_by_owner: true` → 🛡️ "מוגן בחוק".
4. change_cancel "אפשרי בתשלום" → מופיע 🔁 "שינוי בתשלום".
5. אין מידע בכלל → אין שורת סמלים.
6. בדיקות #28 (legal/tests/test_din_agent.py) עוברות בלי שינוי.

## לא בשלב הזה
- `fare_families.json` ו-🔁 מטבלה (שלב 2).
- וואטסאפ וכפתור "פרטי ביטול" (שלב 3).
