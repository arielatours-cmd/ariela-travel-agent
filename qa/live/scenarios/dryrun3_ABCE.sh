# Dry run 3 - integration branch (#145 question arbiter + #144 Hebrew spelling + Ido's mixed-baggage fixes).
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/dryrun3_ABCE.sh
# Checks (qa/reports/2026-10-22-dryrun2.md):
#  A Bari: accessibility asked early with no leaked disclaimer; shift -> the ONE shifted date shown + yes/no
#    (no "בדקתי"); explicit dates without confirmation; suitcase without upsell; "נוסעים: 2 מבוגרים".
#  B Valencia ("וולנסיה"): no "VLC/ולנסיה עצמה משורתת" airport talk, no confirm question; accessibility asked
#    (baby in first message must NOT be inferred); mixed -> payment-page explanation + yes/no -> suitcase.
#  C Bordeaux: accessibility "כן" -> open question -> medical detail -> only the practical need is saved/shown;
#    mixed -> "לא" -> hand bag only.
#  E Rovinj: ONE question on the nearest airport (Pula), saved to destination_airports, Pula in summary;
#    accessibility asked before the closing; mixed while another question is open -> explanation + yes/no;
#    no "מעבירה אותך..." false claim.
reg dr3a 050009941 female
drive dr3a A "אני והחבר שלי לבארי, 6 עד 10 במאי" '{"נגישות":"לא","כבודה":"טרולי לכל אחד","תקציב":"עד 1200 שקל לאדם","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dr3_A.log 2>&1
say dr3a "רגע, אפשר לדחות את כל הטיסה ביום אחד?" "כן" "ובעצם אפשר לצאת ב-9.5 ולחזור ב-13.5?" "ונעדיף בעצם מזוודה לכל אחד" >> dr3_A.log 2>&1
reg dr3b 050009942 male
drive dr3b B "אני, אשתי והתינוק שלנו בן שנה לוולנסיה, 12 עד 17 ביוני" '{"נגישות":"לא","כבודה":"לי ולאשתי מזוודה, לתינוק מספיק תיק קטן","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr3_B.log 2>&1
reg dr3c 050009943 female
drive dr3c C "אני ואמא שלי לבורדו, 20 עד 25 באפריל" '{"נגישות":["כן","אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים"],"כבודה":"לי מזוודה, לאמא מספיק טרולי","אחידה":"לא","תקציב":"עד 1300 שקל לאחת","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dr3_C.log 2>&1
reg dr3e 050009945 female
drive dr3e E "אני ושתי חברות לרוביני, 2 עד 6 ביולי" '{"נגישות":"לא","שדה":"פולה מתאים לנו","כבודה":["לי טרולי, לשתיים האחרות מזוודה","טרולי לכל אחת"],"אחידה":"כן","תקציב":"עד 1100 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr3_E.log 2>&1
