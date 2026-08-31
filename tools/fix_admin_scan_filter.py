from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "admin.py"
s = p.read_text(encoding="utf-8")
old = '''<select id="adminOfferScan" aria-label="סינון לפי סריקה">\n        <option value="">הכל</option>\n        {% for sid in offers|map(attribute='scan_run_id')|unique|list %}{% if sid %}<option value="{{ sid }}">#{{ sid }}</option>{% endif %}{% endfor %}\n      </select>'''
new = '''<select id="adminOfferScan" aria-label="סינון לפי סריקה">\n        <option value="">הכל</option>\n        {% for scan in scans %}{% if scan.id %}<option value="{{ scan.id }}">#{{ scan.id }}{% if scan.status %} · {{ scan.status }}{% endif %}</option>{% endif %}{% endfor %}\n      </select>'''
if old not in s:
    raise RuntimeError("admin scan filter pattern not found")
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("admin scan filter patched")
