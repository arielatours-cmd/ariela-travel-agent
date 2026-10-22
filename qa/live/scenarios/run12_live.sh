# Live stage-1 run 12 (flight only), 5 new cities. Usage: bash qa/live/scenarios/run12_live.sh EXPECTED_COMMIT OUT_DIR
# One-time owner exception (22.10): ~50 live turns beyond the 150/day cap. Checks today's findings:
#  A Malaga: accessibility asked early (no leaked disclaimer); shift -> ONE date + yes/no (no "בדקתי");
#    explicit dates without confirmation; suitcase switch without upsell; "נוסעים: 2 מבוגרים".
#  B Vilnius spelled "ווילנה" (catalog: וילנה/VNO): no unnecessary airport confirmation; baby in first message
#    NOT inferred as accessibility, question still asked; mixed -> payment-page explanation + yes/no -> suitcase.
#  C Paphos spelled "פפוס" (catalog: פאפוס/PFO): accessibility "כן" -> open question -> medical detail ->
#    only the practical need saved/shown; mixed -> "לא" -> hand bag; no duplicated travelers line.
#  D Hallstatt (no airport; nearest SZG): relative dates with options; ONE question on the nearest airport,
#    saved and shown in the summary; accessibility asked before baggage.
#  E Zadar (not in our catalog, has its own airport ZAD): mixed baggage in the FIRST message (while another
#    question is open) -> explanation + yes/no; correct airport/country (Zadar, Croatia); no false
#    "מעבירה אותך..." claim; no "התקציב כבר ידוע".
set -u
L=$(cd "$(dirname "$0")/.." && pwd); OUT=${2:?out dir}; mkdir -p "$OUT"; export ARIELA_QA_OUT="$OUT"; cd "$OUT"
C=$(curl -s -m 30 https://ariela-travel-agent.onrender.com/health | grep -o '"commit":"[^"]*"'); echo "$C"
case "$C" in *"$1"*) ;; *) echo "WRONG COMMIT, abort"; exit 1;; esac
for x in "r12a 050009951 female" "r12b 050009952 male" "r12c 050009953 female" "r12d 050009954 male" "r12e 050009955 female"; do python3 $L/register.py $x 2>&1 | head -1; done
A=$L/autodrive.py
say(){ sc=$1; shift; for m in "$@"; do echo "[$sc] U: $m @$(date -u +%H:%M:%S)"; timeout 300 python3 $L/chat_multi.py $sc "$m" 2>&1 | sed -n '/ARIELA:/,$p' | tail -n +2; done; }
( timeout 1700 python3 $A r12a A "אני והחברה שלי למלאגה, 6 עד 10 במאי" '{"נגישות":"לא","כבודה":"טרולי לכל אחת","תקציב":"עד 1200 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}'; say r12a "רגע, אפשר לדחות את כל הטיסה ביום אחד?" "כן" "ובעצם אפשר לצאת ב-9.5 ולחזור ב-13.5?" "ונעדיף בעצם מזוודה לכל אחת" ) > r12_A.log 2>&1 &
( timeout 1700 python3 $A r12b B "אני, אשתי והתינוקת שלנו בת שנה לווילנה, 12 עד 17 ביוני" '{"נגישות":"לא","כבודה":"לי ולאשתי מזוודה, לתינוקת מספיק תיק קטן","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' ) > r12_B.log 2>&1 &
wait
( timeout 1700 python3 $A r12c C "אני ואמא שלי לפפוס, 20 עד 25 באפריל" '{"נגישות":["כן","אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים"],"כבודה":"לי מזוודה, לאמא מספיק טרולי","אחידה":"לא","תקציב":"עד 1300 שקל לאחת","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' ) > r12_C.log 2>&1 &
( timeout 1700 python3 $A r12d D "זוג להלשטאט בסוף החודש הבא, לחמישה ימים" '{"תאריכים":["האפשרות הראשונה","כן"],"שדה":"זלצבורג מתאים לנו","נגישות":"לא צריך","כבודה":"מזוודה לכל אחד","תקציב":"עד 1400 שקל לאדם","ישיר":"לא","מסלול":"לא","לינה":"לא","רכב":"לא"}' ) > r12_D.log 2>&1 &
wait
( timeout 1700 python3 $A r12e E "אני ושתי חברות לזדאר, 2 עד 6 ביולי. לי מספיק טרולי, לשתיים האחרות מזוודה" '{"נגישות":"לא","אחידה":"כן","כבודה":"טרולי לכל אחת","תקציב":"עד 1100 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' ) > r12_E.log 2>&1 &
wait; echo ALLDONE
