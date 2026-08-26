# Ariella QA Master — questionnaire conditions

Status legend: ⬜ not tested | ✅ PASS | ❌ FAIL | 🟡 partial / fix pending

| Question | Choice | Rule to verify | QA scenario | Status |
|---|---|---|---|---|
| 01 | One destination | Results only for selected destination | SOF / Nov 2026 | ✅ |
| 01 | Several destinations | Results may come from every selected destination; card lists all selections | select SOF+GVA+MXP | 🟡 fix included in 9.7.105 |
| 01 | Ariella suggestions | Search all qualifying 48h DB inventory before API | Nov 2026 | 🟡 fix included in 9.7.105 |
| 01 add-on | Ski vacation | Can be combined with one/several/open destination mode | ski checkbox | 🟡 new in 9.7.105 |
| 02 | Exact dates | Exact date constraint when selected | 10–18 Nov 2026 | ⬜ |
| 02 | Specific month | Both outbound/return month constraints | Nov 2026 | ⬜ |
| 02 | Anytime | No date restriction | standard | ⬜ |
| 02 ski | Ariella chooses ski period | Route through ski flow/DB | ski | ⬜ |
| 03 | Solo | 1 adult saved | | ⬜ |
| 03 | Couple | 2 adults saved | | ⬜ |
| 03 | Friends | selected adult count saved | | ⬜ |
| 03 | Family | adults+children+ages saved | | ⬜ |
| 03 | Extended family | adults+children+ages saved | | ⬜ |
| 03 | Adults only | adults/age group saved | | ⬜ |
| 04 | Direct flight | Any non-direct offer fails | QA SOF Nov | ⬜ |
| 04 | Baggage | Require trolley or checked bag included | QA SOF Nov | ⬜ |
| 04 | Selected dates | Offer must satisfy chosen date mode | QA SOF Nov | ⬜ |
| 04 | Best price | Cheapest qualifying offer ranks first | QA SOF Nov | ⬜ |
| 04 | Convenient times | Only 06:00–22:00 outbound / 06:00–22:30 return | QA SOF Nov | ⬜ |
| 04 | Maximize trip | Earlier outbound + later return gets priority | QA SOF Nov | ⬜ |
| 04 | Ariella best balance | Highest combined quality ranks first | QA SOF Nov | ⬜ |
| 04 ski | Ski resort proximity | Transfer <=120 min when selected; shorter ranks first | QA ski Jan 2027 | ⬜ |
| 05 | Per-person budget | Hard ceiling = entered budget + max 10% | QA SOF Nov | 🟡 fix included in 9.7.105 |
| 05 | Unlimited | No price ceiling | | ⬜ |
