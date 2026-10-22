"""Register a QA customer (arielatours+qa-SC@gmail.com). Usage: register.py SC PHONE [female|male].
Target: $ARIELA_BASE (default: the live site)."""
import os, sys
from playwright.sync_api import sync_playwright
BASE=os.environ.get("ARIELA_BASE","https://ariela-travel-agent.onrender.com").rstrip("/"); SC=sys.argv[1]; PHONE=sys.argv[2]; GENDER=(sys.argv[3] if len(sys.argv)>3 else "female")
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(locale="he-IL")
    pg.goto(BASE+"/join?lang=he")
    pg.fill("input[name=full_name]", f"QA שקד בדיקה {SC}"); pg.fill("input[name=email]", f"arielatours+qa-{SC}@gmail.com")
    pg.fill("input[name=phone]", PHONE); pg.fill("input[name=password]", "QA-shaked-2026!")
    pg.select_option("select[name=gender]", value=GENDER); pg.select_option("select[name=country]", index=1)
    pg.eval_on_selector("input[name=preferred_airports]", "e => e.value = 'TLV'"); pg.check("input[name=consent]")
    pg.click("button[type=submit]"); pg.wait_for_load_state("domcontentloaded")
    print(SC, pg.url.replace(BASE,"")); print([t for t in pg.locator(".error, .flash, .alert, [role=alert]").all_inner_texts()][:3]); b.close()
