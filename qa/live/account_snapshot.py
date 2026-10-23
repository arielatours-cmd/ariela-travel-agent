"""Open /account in the scenario's browser profile (same session as chat_multi.py) in a given language and record
the route tab: visible text, whether Hebrew appears on the English page, maps/cards count, and a screenshot.
Usage: account_snapshot.py SC LANG   ->  $ARIELA_QA_OUT/account_<SC>_<LANG>.json/.png
Read-only: no form is submitted, nothing is clicked; every scan/payment endpoint stays blocked."""
import json, os, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ARIELA_BASE", "https://ariela-travel-agent.onrender.com").rstrip("/")
HERE = Path(os.environ.get("ARIELA_QA_OUT", ".")).resolve()
SC, LANG = sys.argv[1], sys.argv[2]
BLOCK = re.compile(r"/(api/ariella/start-flight-search|trip/\d+/(search-now|renew-search|search-lodging|search-car|free-alternative|checkout|dev-bypass-payment|rent-car|book-lodging)|book/|go/|whatsapp-opt-in)")
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(HERE / f"chat_profile_{SC}"), viewport={"width": 1280, "height": 900})
    ctx.route("**/*", lambda r: r.abort() if BLOCK.search(r.request.url) else r.continue_())
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(f"{BASE}/account?lang={LANG}", wait_until="networkidle", timeout=90000)
    info = page.evaluate("""() => { const panels = [...document.querySelectorAll('.vacation-panel')];
      const p = panels.find(e => /מסלול|Itinerary|itinerary|Route|route/.test(e.querySelector('h3')?.textContent || ''));
      if (!p) return {route_panel: null, url: location.pathname};
      const t = p.innerText || '';
      return {route_panel: true, url: location.pathname, text: t.slice(0, 1500), length: t.length,
              maps: p.querySelectorAll('iframe, img, .map, [class*=map]').length,
              cards: p.querySelectorAll('[class*=itin-card], [class*=itin-day]').length}; }""")
    if info.get("text") is not None:
        # Hebrew letters on the English page (place names in Hebrew are a finding too - English names expected)
        info["hebrew_runs"] = re.findall(r"[֐-׿][֐-׿\s'\"-]{2,}", info["text"])[:10]
    (HERE / f"account_{SC}_{LANG}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    page.screenshot(path=str(HERE / f"account_{SC}_{LANG}.png"), full_page=True)
    print(json.dumps({k: v for k, v in info.items() if k != "text"}, ensure_ascii=False))
    ctx.close()
