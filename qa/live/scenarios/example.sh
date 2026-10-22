# Example scenario file for qa/dry_run_local.sh (sourced; cwd = OUT_DIR).
# Use fresh scenario ids (they become QA emails arielatours+qa-<SC>@gmail.com).
reg dx1 050009991 female
drive dx1 A "אני וחברה לפראג, 6 עד 10 במאי" '{"נגישות":"לא","כבודה":"טרולי לכל אחת","תקציב":"עד 1200 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > dx1.log 2>&1
say dx1 "רגע, אפשר לדחות את כל הטיסה ביום אחד?" >> dx1.log 2>&1
