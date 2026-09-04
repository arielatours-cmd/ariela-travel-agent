from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
header = ROOT / "templates" / "_site_header.html"
text = header.read_text(encoding="utf-8")

old = "html body .site-header .mobile-header-controls{grid-area:controls!important;justify-self:end!important;align-self:center!important;display:flex!important;align-items:center!important;justify-content:center!important;position:relative!important;width:42px!important;height:40px!important;margin:0!important;top:8px!important}"
new = "html body .site-header .mobile-header-controls{grid-area:controls!important;justify-self:end!important;align-self:center!important;display:flex!important;align-items:center!important;justify-content:center!important;position:relative!important;width:42px!important;height:40px!important;margin:0!important;top:18px!important}"

if old in text:
    text = text.replace(old, new, 1)
elif "top:18px!important" not in text:
    raise SystemExit("mobile header controls rule not found")

header.write_text(text, encoding="utf-8")
print("mobile hamburger lowered for phone layout only")
