# Dry run 4 - after Bezalel's fix for the accessibility hint lost after turn 0 (dry run 3, finding 1).
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/dryrun4_ABCEF.sh
# Same A/B/C/E as dry run 3 (qa/reports/2026-10-22-dryrun3.md), plus F. What to check:
#  - every turn while guided.current_question=accessibility is still open: _guided_ask_hint present
#    (chat_resp_*.jsonl), and the question is actually asked before baggage; no leaked
#    "זה לגמרי לא חובה..." sentence without the question.
#  - mixed baggage caught the FIRST time (B, C, E): payment-page explanation + yes/no.
#  - C medical detail: accessibility.details / summary hold only the practical need
#    (e.g. difficulty walking long distances) - never "ניתוח בברך" or any diagnosis.
#  - E Rovinj: a catalog airport in the same country (Pula PUY, Croatia) or an open question -
#    never airports in another country; one question; the choice saved to destination_airports.
#  - F (dedicated): an unrelated question right after the first message, while accessibility is
#    the open guided question -> the hint must stay, and accessibility is asked on the next turn.
reg dr4a 050009961 female
drive dr4a A "אני והחבר שלי לבארי, 6 עד 10 במאי" '{"נגישות":"לא","כבודה":"טרולי לכל אחד","תקציב":"עד 1200 שקל לאדם","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dr4_A.log 2>&1
say dr4a "רגע, אפשר לדחות את כל הטיסה ביום אחד?" "כן" "ובעצם אפשר לצאת ב-9.5 ולחזור ב-13.5?" "ונעדיף בעצם מזוודה לכל אחד" >> dr4_A.log 2>&1
reg dr4b 050009962 male
drive dr4b B "אני, אשתי והתינוק שלנו בן שנה לוולנסיה, 12 עד 17 ביוני" '{"נגישות":"לא","כבודה":"לי ולאשתי מזוודה, לתינוק מספיק תיק קטן","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr4_B.log 2>&1
reg dr4c 050009963 female
drive dr4c C "אני ואמא שלי לבורדו, 20 עד 25 באפריל" '{"נגישות":["כן","אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים"],"כבודה":"לי מזוודה, לאמא מספיק טרולי","אחידה":"לא","תקציב":"עד 1300 שקל לאחת","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dr4_C.log 2>&1
reg dr4e 050009965 female
drive dr4e E "אני ושתי חברות לרוביני, 2 עד 6 ביולי" '{"נגישות":"לא","שדה":"פולה מתאים לנו","כבודה":["לי טרולי, לשתיים האחרות מזוודה","טרולי לכל אחת"],"אחידה":"כן","תקציב":"עד 1100 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr4_E.log 2>&1
reg dr4f 050009966 male
drive dr4f F "אני ואשתי לפראג, 14 עד 18 במרץ" '{"__inject":["יש שם שווקים נחמדים בתקופה הזו?"],"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1000 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"לא","רכב":"לא"}' > dr4_F.log 2>&1
