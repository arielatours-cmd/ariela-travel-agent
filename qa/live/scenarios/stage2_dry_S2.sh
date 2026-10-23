# Stage 2 dry run - scenario S2 only (Florence + Siena route, lodging along the route, route cards he/en).
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 DRY_ALLOW_LOCAL_SEARCH=1 [DRY_RUN_PORT=8766] \
#        qa/dry_run_local.sh <ref> qa/live/scenarios/stage2_dry_S2.sh [OUT]
# Two runs in parallel need different DRY_RUN_PORT values (default 8765). ~15 turns.
P=s2d; PH=05000997
reg ${P}2 ${PH}2 female
( drive ${P}2 S2 "זוג לפירמצה, 15 עד 21 באפריל, ובא לנו גם כמה ימים בסיינה" '{"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1500 שקל לאדם","ישיר":"לא משנה","מסלול":"כן","סגנון":"אמנות, יין ואוכל טוב, בלי לרוץ","קצב":"רגוע","אישור":"מושלם, מתאים לנו","לינה":"כן","סוג_לינה":"מלון","תקציב_לינה":"עד 700 שקל ללילה","חדרים":"חדר אחד","אזור":"במרכז, קרוב למה שבמסלול","רכב":"לא"}' 
  # route cards in English (Ron's bf8ac89): only when the vacation exists - live, or dry with DRY_ALLOW_LOCAL_SEARCH=1
  if [ "${LIVE_SEARCH:-0}" = 1 ] || [ "${DRY_ALLOW_LOCAL_SEARCH:-0}" = 1 ]; then
    python3 "${LIVE_DIR:-$L}/account_snapshot.py" ${P}2 he; python3 "${LIVE_DIR:-$L}/account_snapshot.py" ${P}2 en
  fi ) > ${P}_S2.log 2>&1
