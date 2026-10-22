# Dry run of live run 11's failing scenarios A (Bari) and E (Rovinj) - for the
# accessibility-question + mixed-baggage fix PR, before merge.
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/run11_dry_AE.sh
# What to check (qa/reports/2026-10-22-stage1-live-run11.md):
#   A: accessibility yes/no asked right after travelers (before baggage), _guided_ask_hint present from turn 0;
#      no final summary while accessibility is unanswered; then shift = one date + yes/no,
#      explicit dates = no redundant confirm, switch to suitcase = no upsell.
#   E: accessibility asked; mixed baggage -> explanation (different baggage only at payment) + yes/no
#      "same baggage for all?"; "כן" -> normal baggage question; Rovinj -> one question on the
#      nearest airport (Pula), not chosen silently; no internal text read out.
reg dr11a 050009931 female
drive dr11a A "אני והחבר שלי לבארי, 6 עד 10 במאי" '{"נגישות":"לא","כבודה":"טרולי לכל אחד","תקציב":"עד 1200 שקל לאדם","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dr11_A.log 2>&1
say dr11a "רגע, אפשר לדחות את כל הטיסה ביום אחד?" "כן" "ובעצם אפשר לצאת ב-9.5 ולחזור ב-13.5?" "ונעדיף בעצם מזוודה לכל אחד" >> dr11_A.log 2>&1
reg dr11e 050009935 female
drive dr11e E "אני ושתי חברות לרוביני, 2 עד 6 ביולי" '{"נגישות":"לא","שדה":"פולה מתאים לנו","כבודה":["לי טרולי, לשתיים האחרות מזוודה","טרולי לכל אחת"],"אחידה":"כן","תקציב":"עד 1100 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr11_E.log 2>&1
