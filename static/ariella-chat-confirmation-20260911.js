(function(){
  function boot(){
    const wizard=document.getElementById('tripWizard');
    let chat=document.getElementById('ariellaDesktopChat');
    if(!chat&&wizard){
      const u=new URL(location.href);
      if(u.searchParams.get('ariella_chat')!=='1'){
        u.searchParams.set('ariella_chat','1');
        location.replace(u.toString());
      }
      return;
    }
    if(!chat)return;
    const input=chat.querySelector('#ariellaChatInput'),send=chat.querySelector('#ariellaChatSend'),messages=chat.querySelector('#ariellaChatMessages');
    if(!input||!send||!messages)return;
    const style=document.createElement('style');
    style.textContent=`#ariellaDesktopChat .ac-row.bot{align-items:flex-start!important}#ariellaDesktopChat .ac-row.bot .ac-mini-avatar{margin-top:4px!important;align-self:flex-start!important}.ac-help-card{max-width:86%;margin:2px 41px 8px 0;background:#fff;border:1px solid #e2d4b8;border-radius:16px;padding:15px;color:#17283f}.ac-help-card strong{display:block;margin-bottom:10px;font-size:16px}.ac-help-options{display:grid;grid-template-columns:1fr 1fr;gap:8px}.ac-help-option{display:flex;align-items:center;gap:7px;border:1px solid #dccb9f;border-radius:11px;padding:10px 11px;background:#fffaf2;cursor:pointer}.ac-help-option input{accent-color:#0b8f9c}.ac-help-actions{display:flex;gap:8px;margin-top:12px}.ac-help-save{border:0;border-radius:10px;background:#0b8f9c;color:#fff;font-weight:800;padding:10px 14px;cursor:pointer}.ac-help-later{border:1px solid #c99a3f;border-radius:10px;background:transparent;color:#17283f;font-weight:700;padding:10px 14px;cursor:pointer}.ac-help-results{margin-top:12px;border-top:1px solid #eee0c5;padding-top:10px;font-size:14px;line-height:1.55}.ac-help-results ul{margin:6px 0 0;padding-right:20px}.ac-help-muted{color:#7d7568;font-size:13px}@media(max-width:600px){.ac-help-options{grid-template-columns:1fr}.ac-help-card{margin-right:0;max-width:100%}}`;
    document.head.appendChild(style);
    const title=chat.querySelector('.ac-head-copy strong');
    if(title)title.textContent='אריאלה — סוכנת הנסיעות הראשית שלך';
    chat.querySelectorAll('.ac-avatar,.ac-mini-avatar').forEach(x=>x.textContent='A');
    const note=chat.querySelector('.ac-note');if(note)note.style.display='none';

    const OLD_STORAGE_KEY='ariellaChatState:v1';
    const STORAGE_KEY='ariellaChatState:v2';
    try{localStorage.removeItem(OLD_STORAGE_KEY);}catch(e){}
    let profile={},history=[],busy=false,assistanceChoices=[],assistanceAsked=false,lastAttractions=[];
    try{
      const saved=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');
      if(saved&&typeof saved==='object'){
        if(saved.profile&&typeof saved.profile==='object')profile=saved.profile;
        if(Array.isArray(saved.history))history=saved.history.slice(-80);
        if(Array.isArray(saved.assistanceChoices))assistanceChoices=saved.assistanceChoices;
        assistanceAsked=!!saved.assistanceAsked;
      }
    }catch(e){}

    const labels={destination:'יעד',dates:'תאריכים',travelers:'נוסעים',budget:'תקציב',flight:'טיסה',baggage:'כבודה'};
    function saveState(){
      try{localStorage.setItem(STORAGE_KEY,JSON.stringify({profile,history:history.slice(-80),assistanceChoices,assistanceAsked,saved_at:new Date().toISOString()}));}catch(e){}
    }
    function add(who,text){const row=document.createElement('div');row.className='ac-row '+who;if(who==='bot'){const a=document.createElement('div');a.className='ac-mini-avatar';a.textContent='A';row.appendChild(a)}const b=document.createElement('div');b.className='ac-bubble';b.textContent=text;row.appendChild(b);messages.appendChild(row);messages.scrollTop=messages.scrollHeight;}
    function valueText(k){const p=profile;if(k==='destination')return (p.destinations||[]).join(', ');if(k==='dates')return p.departure_date&&p.return_date?`${p.departure_date} – ${p.return_date}`:(p.outbound_month||p.return_month||'');if(k==='travelers'){const a=p.adults||0,c=p.children||0,i=p.infants||0;return a||c||i?`${a} מבוגרים${c?`, ${c} ילדים`:''}${i?`, ${i} תינוקות`:''}`:''}if(k==='budget')return p.budget_mode==='unlimited'?'ללא הגבלת תקציב':(p.budget_amount?`${p.budget_amount} ₪ לאדם`:'');if(k==='flight')return p.flight_preference||'';if(k==='baggage')return p.baggage||'';return ''}
    function summary(){Object.keys(labels).forEach(k=>{const row=chat.querySelector(`[data-summary-key="${k}"]`),span=row?.querySelector('span'),v=valueText(k);if(span)span.textContent=v||'עדיין לא צוין';row?.classList.toggle('is-filled',!!v)})}
    function aiErrorMessage(data){const d=String(data?.detail||'');if(/429/.test(d))return 'החיבור ל-OpenAI קיים, אבל אין כרגע מכסת API זמינה. צריך לבדוק Billing / Credits בחשבון OpenAI.';if(/401|403/.test(d))return 'מפתח ה-OpenAI שהוגדר ב-Render לא התקבל. צריך לבדוק שה-OPENAI_API_KEY הודבק במלואו.';if(/400/.test(d))return 'החיבור ל-OpenAI קיים, אבל בקשת המודל נדחתה. אני בודקת את הגדרת המודל והפורמט.';if(/OPENAI_API_KEY is not configured/i.test(d))return 'מפתח OpenAI עדיין לא נטען בשרת. צריך לוודא ששמרת את OPENAI_API_KEY ב-Render ובוצע Deploy.';return 'יש כרגע תקלה זמנית בחיבור לאריאלה. אפשר לנסות שוב בעוד רגע.'}
    function renderAssistance(){
      if(document.getElementById('ariellaHelpCard'))return;
      const card=document.createElement('div');card.id='ariellaHelpCard';card.className='ac-help-card';
      card.innerHTML=`<strong>רוצה שאעזור גם בהמשך תכנון החופשה?</strong><div class="ac-help-options">
        <label class="ac-help-option"><input type="checkbox" value="route"> תכנון מסלול</label>
        <label class="ac-help-option"><input type="checkbox" value="attractions"> אטרקציות</label>
        <label class="ac-help-option"><input type="checkbox" value="lodging"> מקומות לינה</label>
        <label class="ac-help-option"><input type="checkbox" value="car"> השכרת רכב</label>
      </div><div class="ac-help-actions"><button type="button" class="ac-help-save">כן, תעזרי לי</button><button type="button" class="ac-help-later">לא כרגע</button></div><div class="ac-help-results" hidden></div>`;
      messages.appendChild(card);
      assistanceChoices.forEach(v=>card.querySelector(`input[value="${v}"]`)?.setAttribute('checked','checked'));
      const results=card.querySelector('.ac-help-results');
      card.querySelector('.ac-help-save').addEventListener('click',()=>{
        assistanceChoices=[...card.querySelectorAll('input:checked')].map(x=>x.value);
        profile.assistance_choices=assistanceChoices;
        saveState();
        results.hidden=false;
        if(!assistanceChoices.length){results.innerHTML='לא סומן תחום. אפשר לבחור אחד או יותר.';return;}
        const parts=[];
        if(assistanceChoices.includes('attractions')){
          if(lastAttractions.length){parts.push('<b>אטרקציות שמתאימות למה שסיפרת:</b><ul>'+lastAttractions.slice(0,5).map(x=>`<li>${x.name}${x.city?' — '+x.city:''}</li>`).join('')+'</ul>');}
          else parts.push('<b>אטרקציות:</b> אבדוק מול מאגר האטרקציות שלנו לפי היעד וההעדפות שלך.');
        }
        if(assistanceChoices.includes('route'))parts.push('<b>תכנון מסלול:</b> אשתמש בפרטי החופשה ובהעדפות שכבר אספתי כדי לבנות מסלול בהמשך.');
        if(assistanceChoices.includes('lodging'))parts.push('<b>מקומות לינה:</b> האפשרות נשמרה. מאגר המלונות/דירות יחובר בהמשך.');
        if(assistanceChoices.includes('car'))parts.push('<b>השכרת רכב:</b> האפשרות נשמרה. מאגר הרכב יחובר בהמשך.');
        results.innerHTML=parts.join('<div style="height:8px"></div>');
        messages.scrollTop=messages.scrollHeight;
      });
      card.querySelector('.ac-help-later').addEventListener('click',()=>{assistanceChoices=[];profile.assistance_choices=[];saveState();card.remove();add('bot','בשמחה. אם תרצי בהמשך עזרה בתכנון החופשה, פשוט תגידי לי.');});
      messages.scrollTop=messages.scrollHeight;
    }
    async function submit(){const raw=input.value.trim();if(!raw||busy)return;busy=true;input.value='';send.disabled=true;add('user',raw);const priorHistory=history.slice(-12);try{const res=await fetch('/api/ariella/chat',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({message:raw,history:priorHistory,profile})});const data=await res.json();if(!res.ok||data.status!=='success'){add('bot',aiErrorMessage(data));return;}profile=data.profile||profile;lastAttractions=data.travel_agent?.attractions||[];summary();const reply=data.reply||'ספרו לי עוד קצת על החופשה שאתם מחפשים.';add('bot',reply);history.push({role:'user',content:raw},{role:'assistant',content:reply});chat.dataset.tinkerbellHandoff=JSON.stringify(data.tinkerbell_handoff||{});chat.dataset.readyForFlights=data.ready_for_flights?'1':'0';if(data.ready_for_flights&&data.intake_complete&&!assistanceAsked){assistanceAsked=true;renderAssistance();}saveState();}catch(e){add('bot','יש כרגע תקלה זמנית בחיבור לאריאלה. אפשר לנסות שוב בעוד רגע.');}finally{busy=false;send.disabled=false;input.focus()}}
    send.addEventListener('click',function(e){e.preventDefault();e.stopImmediatePropagation();submit()},true);
    input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();e.stopImmediatePropagation();submit()}},true);

    messages.innerHTML='';
    if(history.length){history.forEach(item=>add(item.role==='assistant'?'bot':'user',String(item.content||'')));}
    else add('bot','היי, אני אריאלה. ספרו לי חופשי איזו חופשה אתם מחפשים — גם אם עדיין אין לכם יעד. אני אוביל אתכם בכמה שאלות קצרות כדי לבנות את החופשה שמתאימה לכם.');
    summary();
    if(assistanceAsked)renderAssistance();
    input.placeholder='';
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();