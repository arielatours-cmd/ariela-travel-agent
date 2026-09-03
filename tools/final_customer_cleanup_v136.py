from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = ROOT / "templates" / "account.html"
PUBLIC = ROOT / "public_site.py"
SCANNER = ROOT / "scanner.py"

# Put the real search-opened date above the normal vacation details, with spacing.
a = ACCOUNT.read_text(encoding="utf-8")
for fragment in [
    '''          {% if trip.search_opened_at %}<div><dt>{{ 'Search opened' if site_lang == 'en' else 'החיפוש נפתח' }}</dt><dd>{{ trip.search_opened_at }}</dd></div>{% endif %}\n''',
    '''          {% if trip.search_valid_until %}<div><dt>{{ 'Valid until' if site_lang == 'en' else 'בתוקף עד' }}</dt><dd>{{ trip.search_valid_until }}</dd></div>{% endif %}\n''',
]:
    a = a.replace(fragment, '')
anchor = '        <dl class="trip-details-list">'
opened = '''        {% if trip.search_opened_at %}<div class="trip-search-opened" style="margin:14px 0 24px;padding-bottom:14px;border-bottom:1px solid rgba(180,145,70,.24);"><strong>{{ 'Search opened' if site_lang == 'en' else 'החיפוש נפתח' }}:</strong> {{ trip.search_opened_at }}{% if trip.search_valid_until %}<span> · {{ 'Valid until' if site_lang == 'en' else 'בתוקף עד' }}: {{ trip.search_valid_until }}</span>{% endif %}</div>{% endif %}
        <dl class="trip-details-list">'''
if anchor in a and 'class="trip-search-opened"' not in a:
    a = a.replace(anchor, opened, 1)
ACCOUNT.write_text(a, encoding="utf-8")

# Logout should silently return to the public site; no stale logout banner on Deals.
p = PUBLIC.read_text(encoding="utf-8")
for line in [
    '    flash(_msg("התנתקת מהחשבון.", "You have signed out."), "success")\n',
    '    flash(_msg("התנתקת מהחשבון", "You have signed out"), "success")\n',
    '    flash("התנתקת מהחשבון.", "success")\n',
    '    flash("התנתקת מהחשבון", "success")\n',
]:
    p = p.replace(line, '')
PUBLIC.write_text(p, encoding="utf-8")

# Zero offers is a valid successful scan. Existing scanner status already depends
# on errors, not offers_found; preserve that invariant explicitly and do not turn
# an empty result into a system error.
s = SCANNER.read_text(encoding="utf-8")
old = '''    return {
        "status": "success" if errors == 0 else "partial",
        "scan_run_id": run_id,'''
new = '''    return {
        # Zero results is successful coverage when every requested job completed
        # without an API/system error. offers_found is intentionally not a status gate.
        "status": "success" if errors == 0 else "partial",
        "scan_run_id": run_id,'''
if old in s and 'offers_found is intentionally not a status gate' not in s:
    s = s.replace(old, new, 1)
SCANNER.write_text(s, encoding="utf-8")

print("9.7.136 final customer cleanup active")
