from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
header = ROOT / "templates" / "_site_header.html"
text = header.read_text(encoding="utf-8")

old8 = "html body .site-header .mobile-header-controls{grid-area:controls!important;justify-self:end!important;align-self:center!important;display:flex!important;align-items:center!important;justify-content:center!important;position:relative!important;width:42px!important;height:40px!important;margin:0!important;top:8px!important}"
old18 = "html body .site-header .mobile-header-controls{grid-area:controls!important;justify-self:end!important;align-self:center!important;display:flex!important;align-items:center!important;justify-content:center!important;position:relative!important;width:42px!important;height:40px!important;margin:0!important;top:18px!important}"
new = "html body .site-header .mobile-header-controls{grid-area:controls!important;justify-self:end!important;align-self:center!important;display:flex!important;align-items:center!important;justify-content:center!important;position:relative!important;width:42px!important;height:40px!important;margin:0!important;top:24px!important}"

if old8 in text:
    text = text.replace(old8, new, 1)
elif old18 in text:
    text = text.replace(old18, new, 1)
elif "top:24px!important" not in text:
    raise SystemExit("mobile header controls rule not found")

# Also force the glyph itself lower so later CSS cannot pull it back up.
old_btn = "html body .site-header .mobile-nav-toggle{display:flex!important;width:42px!important;height:40px!important;align-items:center!important;justify-content:center!important;border:0!important;background:transparent!important;color:#fff!important;font-size:28px!important;line-height:1!important;padding:0!important;margin:0!important;box-shadow:none!important;cursor:pointer!important;position:relative!important;top:0!important;transform:none!important}"
new_btn = "html body .site-header .mobile-nav-toggle{display:flex!important;width:42px!important;height:40px!important;align-items:center!important;justify-content:center!important;border:0!important;background:transparent!important;color:#fff!important;font-size:28px!important;line-height:1!important;padding:0!important;margin:0!important;box-shadow:none!important;cursor:pointer!important;position:relative!important;top:0!important;transform:translateY(4px)!important}"
if old_btn in text:
    text = text.replace(old_btn, new_btn, 1)

header.write_text(text, encoding="utf-8")
print("mobile hamburger lowered to logo centerline for phone layout only")
