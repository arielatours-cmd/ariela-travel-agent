# Dry run 5 - typo robustness (owner principle 22.10: cheap check first, model on doubt, verify in code,
# never spelling lists) + the open findings of live run 12 (qa/reports/2026-10-22-stage1-live-run12.md).
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/dryrun5_typos.sh
# Every scenario has at least one real adjacent-key typo. Check: Ariela understands the destination,
# never says "אין שדה" for a city that has one, no needless spelling confirmation.
#  A "מלאדה" (Malaga, ג->ד): understood as Malaga/AGP; shift/explicit dates/suitcase as before.
#  B "ווילמה" (Vilnius, נ->מ) + baby: VNO; accessibility asked; mixed -> "כן, מזוודה לכולם".
#  C "פפוס" (Paphos, missing א): PFO, never "no airport"; accessibility + medical -> practical need only;
#    mixed -> "לא" -> hand bag; car never marked done without being asked.
#  D Hallstatt + answer typo "זלצבורד מתאים לנו" given while ANOTHER question (dates) is open:
#    saved to destination_airports (SZG), never asked again.
#  E "זדאק" (Zadar, ר->ק) + mixed in first message: ZAD, never "no airport"; "כן" -> the normal
#    baggage question (Ariela must not pick the type herself); accessibility before closing.
#  F "ליסבוו" (Lisbon, ן->ו): LIS; plain trip.
reg dr5a 050009971 female
drive dr5a A "אני והחברה שלי למלאדה, 6 עד 10 במאי" '{"נגישות":"לא","כבודה":"טרולי לכל אחת","תקציב":"עד 1200 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dr5_A.log 2>&1
say dr5a "רגע, אפשר לדחות את כל הטיסה ביום אחד?" "כן" "ובעצם אפשר לצאת ב-9.5 ולחזור ב-13.5?" "ונעדיף בעצם מזוודה לכל אחת" >> dr5_A.log 2>&1
reg dr5b 050009972 male
drive dr5b B "אני, אשתי והתינוקת שלנו בת שנה לווילמה, 12 עד 17 ביוני" '{"נגישות":"לא","כבודה":"לי ולאשתי מזוודה, לתינוקת מספיק תיק קטן","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr5_B.log 2>&1
reg dr5c 050009973 female
drive dr5c C "אני ואמא שלי לפפוס, 20 עד 25 באפריל" '{"נגישות":["כן","אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים"],"שדה":"פאפוס מתאים לנו","כבודה":"לי מזוודה, לאמא מספיק טרולי","אחידה":"לא","תקציב":"עד 1300 שקל לאחת","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dr5_C.log 2>&1
reg dr5d 050009974 male
drive dr5d D "זוג להלשטאט בסוף החודש הבא, לחמישה ימים" '{"תאריכים":["האפשרות הראשונה, ונוחת לנו לנחות בזלצבורד","כן"],"שדה":"זלצבורד מתאים לנו","נגישות":"לא צריך","כבודה":"מזוודה לכל אחד","תקציב":"עד 1400 שקל לאדם","ישיר":"לא","מסלול":"לא","לינה":"לא","רכב":"לא"}' > dr5_D.log 2>&1
reg dr5e 050009975 female
drive dr5e E "אני ושתי חברות לזדאק, 2 עד 6 ביולי. לי מספיק טרולי, לשתיים האחרות מזוודה" '{"נגישות":"לא","אחידה":"כן","כבודה":"טרולי לכל אחת","שדה":"זדאר מתאים לנו","תקציב":"עד 1100 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > dr5_E.log 2>&1
reg dr5f 050009976 male
drive dr5f F "אני ואשתי לליסבוו, 14 עד 18 במרץ" '{"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1300 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"לא","רכב":"לא"}' > dr5_F.log 2>&1
