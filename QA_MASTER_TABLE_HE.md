# Ariella QA Master — v9.7.107

Testing order agreed: finish Regular Vacation first; only then test Ski Vacation.

| Route | Question | Option / condition | Expected behavior | Status |
|---|---:|---|---|---|
| Entry | — | Regular vacation | Opens only regular questionnaire | ⬜ |
| Entry | — | Ski vacation | Opens only ski questionnaire | ⬜ |
| Regular | 01 | One destination | Only selected destination(s) may match | ⬜ |
| Regular | 01 | Several destinations | Search all selected; display all selections | ⬜ |
| Regular | 01 | Ariella chooses | Search qualifying 48h DB inventory before API | ⬜ |
| Regular | 02 | Exact dates | Exact dates only; alternatives must NOT appear automatically | 🟡 fixed in 106, needs live test |
| Regular | 02 | Month(s) | Outbound/return months respected independently | ⬜ |
| Regular | 02 | Anytime | No date restriction | ⬜ |
| Regular | 03 | Solo / couple / friends / family / extended / adults only | Passenger composition saved correctly | ⬜ |
| Regular | 04 | Direct flight | Any connecting deal fails | ⬜ |
| Regular | 04 | Baggage | Deal must satisfy baggage rule | ⬜ |
| Regular | 04 | Selected dates | Date condition is hard | ⬜ |
| Regular | 04 | Best price | Cheapest qualifying deal ranks first | ⬜ |
| Regular | 04 | Convenient times | Non-convenient QA deal is rejected | ⬜ |
| Regular | 04 | Maximize trip | Earlier outbound/later return ranks first | ⬜ |
| Regular | 04 | Best balance | Highest combined fit ranks first | ⬜ |
| Regular | 05 | Per-person budget | Max 10% tolerance | ⬜ |
| Regular | 05 | Unlimited | No price ceiling | ⬜ |
| Regular | 06 | Special needs | Saved and later usable for destination ranking | ⬜ |
| Ski | S1 | One resort/country | Ski DB resolves only selected scope | ⬜ |
| Ski | S1 | Several resorts/countries | Ski DB resolves union of selected scopes | ⬜ |
| Ski | S1 | Ariella chooses | Ski DB opens to all qualifying resorts | ⬜ |
| Ski | S2 | Exact / month(s) / flexible | Correct ski date mode | ⬜ |
| Ski | S3 | Travelers | Passenger composition saved | ⬜ |
| Ski | S4 | Skill level | Resort must support requested level | ⬜ |
| Ski | S5 | ≤1.5h / ≤3h / any | Ski DB filters by transfer estimate | ⬜ |
| Ski | S6 | Level / snow / family / large / value / proximity / atmosphere / nightlife / spa | Resort ranking reacts to selected priorities | ⬜ |
| Ski | S7 | Per person / all passengers / unlimited | Flight budget normalized and 10% tolerance applied | ⬜ |

## v9.7.107 — תרחיש תקציב
| מסלול | בדיקה | תוצאה צפויה | סטטוס |
|---|---|---|---|
| רגיל | תקציב לאדם + דיל בתוך 10% | הדיל מוצג כהתאמה | ⬜ |
| רגיל | אין דיל בתוך 10%, יש דיל שעומד בכל יתר התנאים | מוצגים עד 3 דילים כחלופות מעל התקציב | ⬜ |
| רגיל | חלופות מעל התקציב | אין הצגת הפרש מהתקציב | ⬜ |
| רגיל | כפתור "תמשיכי לחפש בתקציב שלי" | פותח וגולל אוטומטית לבחירת מסלול החיפוש בתשלום | ⬜ |
| רגיל | לחיצה על הכפתור | אינה מפעילה סריקה לפני בחירת מסלול/תשלום | ⬜ |
