"""Drive one QA conversation to the final summary. Usage: autodrive.py SC LABEL FIRST_MSG ANSWERS_JSON.
ANSWERS_JSON maps a topic (see keys below) to the customer's answer (a list = successive answers).
Uses chat_multi.py next to this file; output in $ARIELA_QA_OUT (default: current directory)."""
import json,os,subprocess,sys,re,datetime
from pathlib import Path
CHAT=str(Path(__file__).with_name("chat_multi.py"))
OUT=Path(os.environ.get("ARIELA_QA_OUT",".")).resolve()
sc,label,first=sys.argv[1],sys.argv[2],sys.argv[3]
ans=json.loads(sys.argv[4])  # topic->answer
ans.setdefault('שדה','לא משנה, מה שהכי נוח');ans.setdefault('איסוף','בשדה התעופה בנחיתה');ans.setdefault('החזרה','באותו מקום');ans.setdefault('גיר','אוטומטי');ans.setdefault('סוג_רכב','רכב משפחתי מרווח')
order=['אחידה','נגישות','שדה','איסוף','החזרה','גיר','סוג_רכב','תקציב_לינה','כבודה','תקציב','ישיר','מקלחות','סוג_לינה','חדרים','אזור','לינה','רכב','אישור','קצב','מסלול','סגנון']
keys={'אחידה':['אחיד','זהה'],'נגישות':['נגישות','התאמ','עגלת','כיסא גלגלים','עזרה מיוחדת'],'שדה':['שדה תעופה','שדה התעופה מועדף','נמל תעופה מועדף','שדה הנחיתה','שדה קרוב','לנחות','שני שדות','לטוס לשם'],'איסוף':['לאסוף','איסוף'],'החזרה':['להחזיר','החזרה','מקום ההחזרה'],'גיר':['אוטומטי','ידני','גיר'],'סוג_רכב':['איזה סוג רכב','איזה רכב','גודל הרכב'],'מקלחות':['מקלחות','חדרי רחצה','חדרי אמבטיה','שירותים'],'תקציב_לינה':['ללילה','תקציב ללינה','תקציב לינה','כוכבים','רמת','רמה'],'סוג_לינה':['סוג לינה','סוג הלינה','איזו לינה','סוג של לינה'],'חדרים':['חדרים','חדר'],'אזור':['אזור','מיקום','ממוקם','שכונה','איפה תרצו','איפה בעיר','באיזה חלק'],'סגנון':['אוהבים','אוהבות','אוהבת','סגנון','אופי','מעניין','תחומי','לעשות'],'קצב':['קצב','עמוס','רגוע'],'אישור':['מתאים','שהצעתי','לשנות'],'כבודה':['כבודה','מזווד','טרולי','תיק'],'תקציב':['תקציב'],'ישיר':['ישיר','קונקשן'],'מסלול':['מסלול','אטרקציות'],'לינה':['לינה','מלון','לישון'],'רכב':['רכב']}
used=set(); used_count={}
# '__inject': customer messages sent right after the first turn, regardless of Ariela's question
# (e.g. an unrelated question while a guided question is open).
inject=list(ans.pop('__inject',[]) or [])
msg=first
log=[]
for turn in range(32):
    subprocess.run([sys.executable,CHAT,sc,msg],capture_output=True,timeout=320)
    last=json.loads(open(OUT/f'chat_resp_{sc}.jsonl').read().strip().split('\n')[-1])
    b=last.get('body') or {}
    r=b.get('reply') or f'[{last.get("status")}]'
    t=b.get('trip_update') or {}
    log.append((msg,r,(t.get('session_status') or {}),(t.get('travelers') or {}).get('adults'),(t.get('flight') or {}).get('connection_preference')))
    print('⟵',msg);print('   ',r.replace('\n',' | ')[:500]);print('    ss=',t.get('session_status'),'ready=',t.get('ready_for_summary'))
    if 'מאשר' in r and t.get('ready_for_summary'):
        # Live runs with LIVE_SEARCH=1 (owner 23.10), or dry runs with DRY_ALLOW_LOCAL_SEARCH=1 (local server only,
        # no SerpAPI key): approve, so the vacation is created and the hand-off can be checked.
        if os.environ.get('LIVE_SEARCH')=='1' or os.environ.get('DRY_ALLOW_LOCAL_SEARCH')=='1':
            subprocess.run([sys.executable,CHAT,sc,'מאשרת'],capture_output=True,timeout=320)
            sl=OUT/f'search_{sc}.jsonl'
            res=[json.loads(x) for x in sl.read_text().splitlines()] if sl.exists() else []
            print('⟵ מאשרת');print('    search:',res[-1] if res else 'NO start-flight-search request')
        break
    if not b.get('reply'): print('    !! no reply at', datetime.datetime.utcnow().strftime('%H:%M:%S'),'UTC'); msg=msg; continue
    if inject:
        print('    [inject]'); msg=inject.pop(0); continue
    qp=r.rfind('?')
    if qp<0:
        print('    !! no question mark'); qp=len(r.rstrip())-1
    st=max(r.rfind(c,0,qp) for c in '.!\n')+1
    if st>qp: st=r.rfind('\n',0,qp)+1
    q=r[st:qp+1]
    topic=None
    if 'תאריכים' in ans and re.search(r'\d{1,2}\.\d{1,2}', q): topic='תאריכים'
    para=r[r.rfind('\n',0,qp)+1:qp+1]
    for cand in ((q,para) if not topic else ()):
        for k in order:
            if k in ans and any(w in cand for w in keys[k]): topic=k;break
        if topic: break
    if topic=='אישור' and not re.search(r'יום\s*\d', r): topic='סגנון' if 'סגנון' in ans else topic
    if topic not in ('מסלול','סגנון','קצב','אישור') and 'מסלול' in q and 'מסלול' in ans and (t.get('session_status') or {}).get('trip_planning')=='pending': topic='מסלול'
    # Accessibility follow-up (open question after "כן"): it can mention lodging/route words, so trust
    # the state - while guided still waits on accessibility and a scripted detail answer remains, answer it.
    _acc=ans.get('נגישות')
    if isinstance(_acc,list) and used_count.get('נגישות',0)<len(_acc) and used_count.get('נגישות',0)>0 \
            and ((t.get('guided') or {}).get('current_question')=='accessibility'): topic='נגישות'
    print('    [topic]',topic)
    if not topic and 'תאריכים' in ans: topic='תאריכים'
    if not topic:
        print('    !! no topic detected — stopping');break
    v=ans[topic]
    if isinstance(v,list):
        cnt=used_count.get(topic,0); msg=v[min(cnt,len(v)-1)]; used_count[topic]=cnt+1
    else: msg=v
