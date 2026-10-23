"""Send one customer message to Ariela ($ARIELA_BASE, default: the live site) and print her reply.
Persistent browser profile keeps cookies + localStorage (trip_state) between steps.
HARD GUARD: every scan/search/payment endpoint is aborted at the network layer.
Single exception (business owner, in this session, 23.10.2026: "מאשרת ריצה בסבבים חיים אבל לא בכל ריצה"):
LIVE_SEARCH=1, set per live run, lets /api/ariella/start-flight-search through - live site only, never a
local dry-run server. Payment/booking/lodging and car searches/WhatsApp stay blocked always. Default: blocked."""
import json, os, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ARIELA_BASE", "https://ariela-travel-agent.onrender.com").rstrip("/")
# Output (browser profile, logs, state) goes to $ARIELA_QA_OUT, default: the current directory.
HERE = Path(os.environ.get("ARIELA_QA_OUT", ".")).resolve()
SC = sys.argv[1]  # scenario id, e.g. s1
PROFILE = HERE / f"chat_profile_{SC}"
LOG = HERE / f"chat_log_{SC}.jsonl"
EMAIL, PASSWORD = f"arielatours+qa-{SC}@gmail.com", "QA-shaked-2026!"
LIVE_SEARCH = os.environ.get("LIVE_SEARCH") == "1"
if LIVE_SEARCH and BASE != "https://ariela-travel-agent.onrender.com":
    sys.exit("LIVE_SEARCH=1 is allowed only against the live site - dry runs stay blocked")
# Dry runs only (Shlomo 23.10): DRY_ALLOW_LOCAL_SEARCH=1 lets start-flight-search reach the LOCAL dry-run server,
# which has no SerpAPI key and SCANNER_ENABLED=false (qa/dry_run_local.sh) - the vacation is created locally so
# the route cards / hand-off can be checked; nothing leaves the machine. Never against a non-local server.
DRY_LOCAL_SEARCH = os.environ.get("DRY_ALLOW_LOCAL_SEARCH") == "1"
if DRY_LOCAL_SEARCH and not BASE.startswith("http://127.0.0.1:"):
    sys.exit("DRY_ALLOW_LOCAL_SEARCH=1 is allowed only against the local dry-run server")
BLOCK = re.compile(r"/(" + ("" if (LIVE_SEARCH or DRY_LOCAL_SEARCH) else r"api/ariella/start-flight-search|") + r"trip/\d+/(search-now|renew-search|search-lodging|search-car|free-alternative|checkout|dev-bypass-payment)|book/|whatsapp-opt-in)")
blocked = []
T0 = time.time()*1000

msg = sys.argv[2] if len(sys.argv) > 2 else ""
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), viewport={"width": 1280, "height": 900}, locale="he-IL")
    ctx.route("**/*", lambda route: (blocked.append(route.request.url), route.abort()) if BLOCK.search(route.request.url) else route.continue_())
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    RESP_LOG = HERE / f"chat_resp_{SC}.jsonl"
    def _cap(resp):
        if "/api/ariella/chat-clean" in resp.url:
            try:
                body = resp.json()
            except Exception:
                body = {"_raw_status": resp.status}
                try: body["_raw_text"] = resp.text()[:500]
                except Exception: pass
            if resp.status != 200:
                try:
                    h = resp.headers
                    body["_headers"] = {k: h.get(k) for k in ("server", "cf-ray", "rndr-id", "x-render-origin-server", "content-type", "date", "via", "x-request-id")}
                except Exception: pass
            with RESP_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"msg": msg, "status": resp.status, "at": time.strftime("%H:%M:%S", time.gmtime()), "ms": round(time.time()*1000 - T0), "body": body}, ensure_ascii=False) + "\n")
    page.on("request", lambda r: globals().__setitem__("T0", time.time()*1000) if "/api/ariella/chat-clean" in r.url else None)
    page.on("response", _cap)
    def _search(resp):
        if "/api/ariella/start-flight-search" in resp.url:
            try: body = resp.json()
            except Exception: body = {"_raw_status": resp.status}
            keep = {k: body.get(k) for k in ("status", "message", "trip_id", "account_url")} if isinstance(body, dict) else {}
            with (HERE / f"search_{SC}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"msg": msg, "http": resp.status, "at": time.strftime("%H:%M:%S", time.gmtime()), "body": keep}, ensure_ascii=False) + "\n")
    page.on("response", _search)
    page.goto(BASE + "/trip/new?lang=he", wait_until="networkidle", timeout=90000)
    if "/login" in page.url:
        page.fill("input[name=email]", EMAIL); page.fill("input[name=password]", PASSWORD)
        page.click("button[type=submit]"); page.wait_for_load_state("networkidle")
        page.goto(BASE + "/trip/new?lang=he", wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(2500)
    sel = "#ariellaNewChatMessages .ariella-msg.assistant:not(.ariella-typing)"
    before = page.locator(sel).count()
    if msg:
        try:
            page.wait_for_selector("#ariellaNewChatInput", state="visible", timeout=30000)
        except Exception:
            page.screenshot(path=str(HERE / f"chat_fail_{SC}.png"), full_page=True)
            vis = page.evaluate("() => { const e = document.getElementById('ariellaNewChatInput'); if (!e) return 'missing'; const chain = []; let n = e; while (n && n !== document.body) { const cs = getComputedStyle(n); if (cs.display === 'none' || cs.visibility === 'hidden' || n.hidden) chain.push((n.id || n.className || n.tagName) + ':' + cs.display + '/' + cs.visibility); n = n.parentElement; } return chain.join(' | ') || 'visible?'; }")
            print("INPUT HIDDEN BY:", vis); ctx.close(); sys.exit(2)
        page.fill("#ariellaNewChatInput", msg)
        page.press("#ariellaNewChatInput", "Enter")
        deadline = time.time() + 180
        start_url = page.url
        HANDOFF = HERE / f"handoff_{SC}.jsonl"
        def _route_panel():
            return page.evaluate("""() => { const p = [...document.querySelectorAll('.vacation-panel')].find(e => /מסלול|Itinerary|itinerary/.test(e.querySelector('h3')?.textContent || ''));
              if (!p) return {route_panel: null};
              return {route_panel: true, route_panel_open: p.classList.contains('active') || getComputedStyle(p).display !== 'none',
                      text: (p.innerText || '').slice(0, 600), maps: p.querySelectorAll('iframe, img, .map, [class*=map]').length,
                      cards: p.querySelectorAll('[class*=card], [class*=day]').length}; }""")
        def _log_handoff(rec):
            with HANDOFF.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"msg": msg, **rec}, ensure_ascii=False) + "\n")
        if msg.strip() == "מאשרת":
            # Owner 23.10 (updated): no hand-off before "מאשרת"; after it a waiting page, then /account with the
            # route tab already enriched and open - no reload. Record every page on the way, screenshot at arrival
            # on /account and 30s later.
            seen = [start_url]
            for _ in range(120):  # up to ~3 minutes for waiting page -> /account
                page.wait_for_timeout(1500)
                if page.url != seen[-1]:
                    seen.append(page.url)
                    page.screenshot(path=str(HERE / f"handoff_{SC}_step{len(seen)-1}.png"), full_page=True)
                    _log_handoff({"at": "navigated", "url": page.url.replace(BASE, "")})
                if "/account" in page.url:
                    break
            if "/account" in page.url:
                try: page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception: pass
                for tag, wait_ms in (("0s", 0), ("30s", 30000)):
                    page.wait_for_timeout(wait_ms)
                    page.screenshot(path=str(HERE / f"handoff_{SC}_{tag}.png"), full_page=True)
                    _log_handoff({"at": tag, "url": page.url.replace(BASE, ""), "path": [u.replace(BASE, "") for u in seen], **_route_panel()})
            if page.url != start_url:
                deadline = 0  # left the chat page - no reply bubble to wait for
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            if page.url != start_url:
                break
            if page.locator(sel).count() > before and page.locator("#ariellaNewChatMessages .ariella-typing").count() == 0:
                break
        page.wait_for_timeout(2500)
        if msg.strip() != "מאשרת" and page.url != start_url:
            # FAIL by the owner's rule: the chat left for another page without the customer's approval.
            page.screenshot(path=str(HERE / f"handoff_{SC}_before_confirm.png"), full_page=True)
            _log_handoff({"at": "NAVIGATED_BEFORE_CONFIRM", "url": page.url.replace(BASE, "")})
            print("!! NAVIGATED BEFORE CONFIRM:", page.url.replace(BASE, ""))
        if (LIVE_SEARCH or DRY_LOCAL_SEARCH) and msg.strip() == "מאשרת":
            # the approved trip hands off to the vacation card - let the scan launch finish
            try: page.wait_for_load_state("networkidle", timeout=60000)
            except Exception: pass
            page.wait_for_timeout(5000)
    replies = [t.strip() for t in page.locator(sel).all_inner_texts()]
    new = replies[before:] if msg else replies[-1:]
    state = page.evaluate("() => { const out = {}; for (const k of Object.keys(localStorage)) out[k] = localStorage.getItem(k); return out; }")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"user": msg, "ariela": new, "blocked": blocked, "url": page.url}, ensure_ascii=False) + "\n")
    print("URL:", page.url.replace(BASE, ""))
    if blocked: print("BLOCKED:", blocked)
    print("ARIELA:\n" + "\n---\n".join(new))
    Path(HERE / f"chat_state_{SC}.json").write_text(json.dumps(state, ensure_ascii=False, indent=1))
    page.screenshot(path=str(HERE / f"chat_last_{SC}.png"), full_page=False)
    ctx.close()
