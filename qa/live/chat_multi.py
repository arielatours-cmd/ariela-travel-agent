"""Send one customer message to Ariela ($ARIELA_BASE, default: the live site) and print her reply.
Persistent browser profile keeps cookies + localStorage (trip_state) between steps.
HARD GUARD: every scan/search/payment endpoint is aborted at the network layer."""
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
BLOCK = re.compile(r"/(api/ariella/start-flight-search|trip/\d+/(search-now|renew-search|search-lodging|search-car|free-alternative|checkout|dev-bypass-payment)|book/|whatsapp-opt-in)")
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
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            if page.locator(sel).count() > before and page.locator("#ariellaNewChatMessages .ariella-typing").count() == 0:
                break
        page.wait_for_timeout(2500)
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
