# Same as render_pages.py, as a logged-in member (trip form, /account, deals). Usage: python3 qa/tools/render_member_pages.py <worktree> <out.json>
import os, sys, re, tempfile, logging, json, sqlite3
root=sys.argv[1]; out=sys.argv[2]
os.chdir(root); sys.path.insert(0, root)
os.environ["DB_PATH"]=tempfile.mktemp(suffix=".db"); os.environ["SCHEDULER_ENABLED"]="false"; os.environ["SCANNER_ENABLED"]="false"
for k in list(os.environ):
    if any(s in k for s in ("SERPAPI","WHATSAPP","ANTHROPIC","CJ_")): del os.environ[k]
logging.disable(logging.CRITICAL)
import app as A
from werkzeug.security import generate_password_hash
app=A.app
with app.test_client() as c: c.get("/")
conn=sqlite3.connect(os.environ["DB_PATH"])
mid=conn.execute("INSERT INTO members (full_name,email,phone,password_hash,created_at,status) VALUES(?,?,?,?,datetime('now'),'active')",("QA","qa@example.com","0500000000",generate_password_hash("x"))).lastrowid; conn.commit()
res={}
with app.test_client() as c:
    with c.session_transaction() as s: s["member_id"]=mid
    for u in ["/trip/new?lang=he","/account?lang=he","/deals?lang=he","/","/trip/new?lang=en"]:
        r=c.get(u); html=re.sub(r"<script.*?</script>|<style.*?</style>","",r.get_data(as_text=True),flags=re.S)
        res[u]=[r.status_code,re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html)).strip()]
json.dump(res,open(out,"w"),ensure_ascii=False)
