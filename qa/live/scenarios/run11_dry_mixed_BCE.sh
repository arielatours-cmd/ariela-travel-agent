# Dry run of live run 11's mixed-baggage failures B (Valencia), C (Bordeaux), E (Rovinj) -
# for the mixed-baggage fix (branch oholiav-run11-mixed-baggage), before merge.
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/run11_dry_mixed_BCE.sh
# Expected in all three (owner decision 22.10, qa/stage-scenarios.md): on the mixed answer, Ariela says
# different baggage per passenger can be added only at payment, then ONE yes/no question - same
# baggage for everyone? Nothing saved before the choice (flight.baggage stays empty).
#   B "כן, מזוודה לכולם" -> suitcase saved, no further baggage question (same-turn type).
#   C "לא" -> personal_item (hand bag only) saved, summary "כבודה: תיק יד לכל נוסע (...)".
#   E "כן" -> the normal baggage question -> "טרולי לכל אחת" -> carry_on_only.
# Also note: no repeated "איזו כבודה" loop (C), no "סבבה, קלטתי" (E), no "רק לוודא" confirmation.
reg dr11b 050009932 male
drive dr11b B "אני, אשתי והתינוק שלנו בן שנה לוולנסיה, 12 עד 17 ביוני" '{"נגישות":"לא","כבודה":"לי ולאשתי מזוודה, לתינוק מספיק תיק קטן","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr11_B.log 2>&1
reg dr11c 050009933 female
drive dr11c C "אני ואמא שלי לבורדו, 20 עד 25 באפריל" '{"נגישות":["כן","אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים"],"כבודה":"לי מזוודה, לאמא מספיק טרולי","אחידה":"לא","תקציב":"עד 1300 שקל לאחת","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dr11_C.log 2>&1
reg dr11e 050009935 female
drive dr11e E "אני ושתי חברות לרוביני, 2 עד 6 ביולי" '{"נגישות":"לא","שדה":"פולה מתאים לנו","כבודה":["לי טרולי, לשתיים האחרות מזוודה","טרולי לכל אחת"],"אחידה":"כן","תקציב":"עד 1100 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr11_E.log 2>&1
