# Ariella QA — v9.7.107

## Changes for this build
- Entry screen: removed explanatory sentence.
- Entry screen: removed Continue button; clicking Regular/Ski immediately opens that route.
- Removed "Change vacation type" buttons from both questionnaires.
- Enlarged date/month controls.
- Budget remains a hard filter with 10% tolerance.
- NEW budget fallback: if no offer is within the budget but offers satisfy all other hard conditions and requested date scope, show up to 3 closest-priced offers without displaying the budget difference.
- NEW single CTA: "תמשיכי לחפש בתקציב שלי".
- CTA automatically opens and scrolls to the existing paid-search plan selector for that vacation; user only chooses a search plan.

## Required live QA next
Use the already-tested Tbilisi 2–10 Nov 2026 case with ₪700/person. Expected:
1. No offer is labeled as a budget match above the 10% ceiling (₪770).
2. Existing qualifying Tbilisi offer(s) above budget are shown under the budget fallback message.
3. No budget-difference arithmetic is displayed.
4. Only one budget CTA is shown.
5. Clicking it opens/scrolls to the paid search plan selector for the same vacation.
6. No additional search is launched before a plan/payment flow is selected.
