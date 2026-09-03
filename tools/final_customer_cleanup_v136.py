from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = ROOT / "templates" / "account.html"
PUBLIC = ROOT / "public_site.py"
SCANNER = ROOT / "scanner.py"

# Account card: search-opened date belongs above the request details, visually
# separated from the rest of the vacation data.
a = ACCOUNT.read_text(encoding="utf-8")
old_title = '''        <div class="trip-title-line">
          <h3>{{ trip.destination_display }}</h3>'''
new_title = '''        <div class="trip-title-line">
          <h3>{{ trip.destination_display }}</h3>'''
a = a.replace(old_title, new_title, 1)
# Remove any date row injected inside the normal dl by earlier runtime cleanup.
for fragment in [
    '''          {% if trip.search_opened_at %}<div><dt>{{ 'Search opened' if site_lang == 'en' else 'החיפוש נפתח' }}</dt><dd>{{ trip.search_opened_at }}</dd></div>{% endif %}\n''',
    '''          {% if trip.search_valid_until %}<div><dt>{{ 'Valid until' if site_lang == 'en' else 'בתוקף עד' }}</dt><dd>{{ trip.search_valid_until }}</dd></div>{% endif %}\n''',
]:
    a = a.replace(fragment, '')
anchor = '''        <dl class="trip-details-list">'''
opened = '''        {% if trip.search_opened_at %}<div class="trip-search-opened" style="margin:14px 0 24px;padding-bottom:14px;border-bottom:1px solid rgba(180,145,70,.24);"><strong>{{ 'Search opened' if site_lang == 'en' else 'החיפוש נפתח' }}:</strong> {{ trip.search_opened_at }}{% if trip.search_valid_until %}<span> · {{ 'Valid until' if site_lang == 'en' else 'בתוקף עד' }}: {{ trip.search_valid_until }}</span>{% endif %}</div>{% endif %}
        <dl class="trip-details-list">'''
if anchor in a and 'class="trip-search-opened"' not in a:
    a = a.replace(anchor, opened, 1)
ACCOUNT.write_text(a, encoding="utf-8")

# Logout is a navigation action, not a warning that should persist into public pages.
p = PUBLIC.read_text(encoding="utf-8")
# Cover Hebrew/English logout flash variants without changing login or error messages.
for line in [
    '    flash(_msg("התנתקת מהחשבון.", "You have signed out."), "success")\n',
    '    flash(_msg("התנתקת מהחשבון", "You have signed out"), "success")\n',
    '    flash("התנתקת מהחשבון.", "success")\n',
    '    flash("התנתקת מהחשבון", "success")\n',
]:
    p = p.replace(line, '')
PUBLIC.write_text(p, encoding="utf-8")

# A completed scan with zero offers is still a successful scan. Only actual
# errors/stops/caps make it partial. This keeps zero-result monthly coverage fresh.
s = SCANNER.read_text(encoding="utf-8")n
