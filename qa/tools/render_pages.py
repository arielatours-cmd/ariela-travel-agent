# Render public pages (lang=he by default) on a local copy and dump visible text to JSON - compare two refs
# to prove a display change did not alter the Hebrew site. Usage: python3 qa/tools/render_pages.py <worktree> <out.json>
import os, sys, re, tempfile, logging, json
root=sys.argv[1]; out=sys.argv[2]
os.chdir(root); sys.path.insert(0, root)
os.environ["DB_PATH"]=tempfile.mktemp(suffix=".db"); os.environ["SCHEDULER_ENABLED"]="false"; os.environ["SCANNER_ENABLED"]="false"
for k in list(os.environ):
    if any(s in k for s in ("SERPAPI","WHATSAPP","ANTHROPIC","CJ_")): del os.environ[k]
logging.disable(logging.CRITICAL)
import app as A
app=A.app
urls=["/","/deals","/trip/new","/about","/contact","/join","/login","/affiliate-disclosure","/terms","/privacy","/account"]
res={}
with app.test_client() as c:
    for u in urls:
        for lang in ("?lang=he",):
            r=c.get(u+lang)
            html=r.get_data(as_text=True)
            html=re.sub(r"<script.*?</script>|<style.*?</style>","",html,flags=re.S)
            txt=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html)).strip()
            res[u+lang]=[r.status_code,txt]
json.dump(res,open(out,"w"),ensure_ascii=False)
