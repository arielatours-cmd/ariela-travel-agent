(function(){
  'use strict';

  var FLOW_VERSION='20260914-clean-v1';
  var REGULAR_OPENING='איזה כיף 🏖️\nספרו לי קצת על החופשה שאתם מתכננים — לאן תרצו לטוס, מתי ומי נוסע.\nואם עדיין לא החלטתם לאן — אפשר גם לתת לי להמליץ לכם 😊';
  var RULES='אריאלה מנהלת שיחה טבעית כמו סוכנת נסיעות ולא שאלון. אין להציג קודים פנימיים, true/false או enum, ואין לשאול שוב מידע שכבר נמסר. בחופשה רגילה: קודם אוספים יעד או בקשה שאריאלה תבחר, מועד, ומי נוסע. אחר כך ורק אחר כך אוספים תקציב, כבודה, וישיר או קונקשן. רק לאחר שכל פרטי הטיסה נאספו שואלים אם הלקוח רוצה שאריאלה תבנה את הטיול כולו או רק עזרה בדברים מסוימים. אין לשאול אוטומטית על גמישות או משך. אין להציג לינה, רכב, אטרקציות או תכנון מסלול לפני השלמת פרטי הטיסה.';
  var avatarSrc='';

  function isTripPage(){
    return !!document.getElementById('tripWizard') || /\/trip\/new(?:\/|$|\?)/.test(location.pathname+location.search);
  }

  function resetOldFlowOnce(){
    try{
      if(localStorage.getItem('ariellaFlowVersion')===FLOW_VERSION) return;
      localStorage.removeItem('ariellaChatState:v4');
      localStorage.removeItem('ariellaChatState:v3');
      sessionStorage.removeItem('ariellaChatState:v4');
      sessionStorage.removeItem('ariellaChatState:v3');
      localStorage.setItem('ariellaFlowVersion',FLOW_VERSION);
    }catch(e){}
  }

  function patchFetch(){
    if(window.__ariellaCleanFetchPatched) return;
    window.__ariellaCleanFetchPatched=true;
    var original=window.fetch.bind(window);
    window.fetch=async function(input,init){
      var url=typeof input==='string'?input:(input&&input.url)||'';
      if(/\/api\/ariella\/chat(?:\?|$)/.test(url)&&init&&String(init.method||'GET').toUpperCase()==='POST'&&typeof init.body==='string'){
        try{
          var p=JSON.parse(init.body);
          var m=String(p.message||'').trim();
          if(p.profile&&p.profile.vacation_type==='standard'&&(!Array.isArray(p.profile.services)||!p.profile.services.length)) p.profile.services=['flight'];
          if(m) p.message='הודעת הלקוח המקורית:\n'+m+'\n\n'+RULES;
          init=Object.assign({},init,{body:JSON.stringify(p)});
        }catch(e){}
      }
      return original(input,init);
    };
  }

  function removeLegacy(){
    document.querySelectorAll('#vacationTypeGate,.vacation-type-gate,.vacation-type-grid,.trip-back-bar').forEach(function(el){el.remove();});
    var wizard=document.getElementById('tripWizard');
    if(wizard) wizard.style.setProperty('display','none','important');
  }

  function loadAvatar(){
    fetch('/static/ariella-avatar-runtime-20260913.js?avatar_source=clean-v1',{cache:'no-store'})
      .then(function(r){return r.text();})
      .then(function(js){
        var m=js.match(/const\s+src\s*=\s*'([^']+)'/);
        if(m&&m[1]){avatarSrc=m[1];applyAvatar();}
      }).catch(function(){});
  }

  function applyAvatar(){
    if(!avatarSrc) return;
    document.querySelectorAll('#ariellaDesktopChat .ac-avatar,#ariellaDesktopChat .ac-mini-avatar').forEach(function(el){
      el.textContent='';
      el.style.setProperty('background','center 38% / cover no-repeat url("'+avatarSrc+'")','important');
      el.style.setProperty('border-radius','50%','important');
      el.style.setProperty('overflow','hidden','important');
      el.style.setProperty('color','transparent','important');
    });
  }

  function makeChat(){
    var existing=document.getElementById('ariellaDesktopChat');
    if(existing) return existing;
    var isEn=document.documentElement.lang==='en';
    var chat=document.createElement('section');
    chat.id='ariellaDesktopChat';
    var defs=[['destination','🌍',isEn?'Destination':'יעד'],['dates','📅',isEn?'Dates':'תאריכים'],['travelers','👥',isEn?'Travelers':'נוסעים'],['budget','💰',isEn?'Budget':'תקציב'],['flight','✈️',isEn?'Flight':'טיסה'],['baggage','🧳',isEn?'Baggage':'כבודה']];
    var rows=defs.map(function(d){return '<div class="ac-detail" data-summary-key="'+d[0]+'"><div>'+d[1]+'</div><div><b>'+d[2]+'</b><span>'+(isEn?'Not specified yet':'עדיין לא צוין')+'</span></div></div>';}).join('');
    chat.innerHTML='<div class="ac-shell"><div class="ac-chat"><div class="ac-head"><div class="ac-avatar"></div><div class="ac-head-copy"><strong>'+(isEn?'Ariella — your personal travel agent':'אריאלה — סוכנת הנסיעות האישית שלך')+'</strong></div><div class="ac-online">'+(isEn?'Available':'זמינה עכשיו')+'</div></div><div class="ac-messages" id="ariellaChatMessages"></div><div class="ac-compose"><textarea id="ariellaChatInput" rows="1"></textarea><button type="button" class="ac-send" id="ariellaChatSend">'+(isEn?'Send':'שליחה')+'</button></div></div><aside class="ac-summary"><div class="ac-summary-head"><strong>'+(isEn?'My vacation':'החופשה שלי')+'</strong><small>'+(isEn?'The details Ariella understands from the conversation will appear here.':'הפרטים שאריאלה תבין מהשיחה יתעדכנו כאן.')+'</small></div>'+rows+'</aside></div>';
    var wizard=document.getElementById('tripWizard');
    var main=document.querySelector('main');
    if(wizard&&wizard.parentNode) wizard.parentNode.insertBefore(chat,wizard);
    else if(main) main.appendChild(chat);
    else document.body.appendChild(chat);
    return chat;
  }

  function installStyle(){
    if(document.getElementById('ariella-clean-chat-style')) return;
    var style=document.createElement('style');
    style.id='ariella-clean-chat-style';
    style.textContent='#tripWizard,#vacationTypeGate,.vacation-type-gate,.vacation-type-grid,.trip-back-bar{display:none!important}#ariellaDesktopChat .ariella-new-chat{display:none!important}#ariellaDesktopChat{width:min(1280px,92%);margin:18px auto 40px;direction:rtl;font-family:Arial,"Segoe UI",sans-serif}#ariellaDesktopChat .ac-shell{display:grid;grid-template-columns:minmax(0,2fr) minmax(300px,.85fr);gap:22px;align-items:stretch}#ariellaDesktopChat .ac-chat,#ariellaDesktopChat .ac-summary{background:#fffaf2;border:1px solid rgba(201,154,63,.38);border-radius:22px;box-shadow:0 14px 38px rgba(23,40,63,.08);overflow:hidden}#ariellaDesktopChat .ac-chat{height:min(650px,calc(100vh - 150px));min-height:520px;display:flex;flex-direction:column}#ariellaDesktopChat .ac-head{display:flex;align-items:center;gap:14px;padding:20px 24px;background:linear-gradient(135deg,#102b30,#18373a);color:#fff;border-bottom:1px solid #c99a3f}#ariellaDesktopChat .ac-avatar{width:58px;height:58px;border-radius:50%;flex:0 0 58px;border:2px solid #fff3cf;background:#17353a}#ariellaDesktopChat .ac-head-copy strong{display:block;font-size:21px}#ariellaDesktopChat .ac-online{margin-inline-start:auto;color:#d8e7e5;font-size:13px}#ariellaDesktopChat .ac-messages{flex:1;min-height:0;padding:28px 30px;display:flex;flex-direction:column;gap:14px;background:linear-gradient(180deg,#fffdf8,#fbf5e9);overflow-y:auto}#ariellaDesktopChat .ac-compose{padding:17px 20px;border-top:1px solid #eadfc8;background:#fff;display:flex;gap:10px;align-items:center}#ariellaDesktopChat .ac-compose textarea{flex:1;min-height:52px;max-height:125px;resize:none;border:1px solid #d9cdb8;border-radius:14px;padding:14px 15px;font:inherit;background:#fffdf9;color:#17283f}#ariellaDesktopChat .ac-send{height:52px;min-width:92px;border:0;border-radius:13px;background:#0b8f9c;color:#fff;font-weight:800;font-size:15px}#ariellaDesktopChat .ac-summary{padding:0 22px 22px;align-self:start}#ariellaDesktopChat .ac-summary-head{margin:0 -22px 18px;padding:20px 22px 16px;border-bottom:1px solid #eadfc8}#ariellaDesktopChat .ac-summary-head strong{display:block;font-size:22px;color:#17283f}#ariellaDesktopChat .ac-summary-head small{display:block;margin-top:5px;color:#75808b}#ariellaDesktopChat .ac-detail{display:grid;grid-template-columns:34px 1fr;gap:10px;padding:11px 0;border-bottom:1px solid #eee5d5}#ariellaDesktopChat .ac-detail b{display:block;color:#17283f;font-size:14px}#ariellaDesktopChat .ac-detail span{display:block;color:#8a8173;font-size:14px}@media(max-width:899px){#ariellaDesktopChat{width:100%;margin:0 auto 24px;padding:8px 10px}#ariellaDesktopChat .ac-shell{display:flex;flex-direction:column;gap:12px}#ariellaDesktopChat .ac-chat{height:calc(100dvh - 125px);min-height:500px;border-radius:16px}#ariellaDesktopChat .ac-head{padding:10px 12px}#ariellaDesktopChat .ac-online{display:none}#ariellaDesktopChat .ac-messages{padding:18px 12px}#ariellaDesktopChat .ac-compose{padding:10px}#ariellaDesktopChat .ac-compose textarea{min-height:48px}#ariellaDesktopChat .ac-send{height:48px;min-width:68px}#ariellaDesktopChat .ac-summary{border-radius:16px}}';
    document.head.appendChild(style);
  }

  function normalizePurposeCard(){
    var card=document.getElementById('ariellaPurposeCard');
    if(!card) return;
    var title=card.querySelector('strong');
    if(title) title.textContent='איזה סוג חופשה תרצו לתכנן?';
    var labels={standard:'🏖️ נופש',business:'💼 טיסת עסקים',ski:'⛷️ חופשת סקי'};
    var opts=card.querySelector('.ac-flow-options');
    Object.keys(labels).forEach(function(v){
      var input=card.querySelector('input[value="'+v+'"]');
      var label=input&&input.closest('label');
      if(label){
        Array.from(label.childNodes).forEach(function(n){if(n.nodeType===3)n.remove();});
        label.appendChild(document.createTextNode(' '+labels[v]));
      }
    });
    if(opts){['standard','business','ski'].forEach(function(v){var i=card.querySelector('input[value="'+v+'"]');if(i&&i.closest('label'))opts.appendChild(i.closest('label'));});}
  }

  function replaceStandardServiceCard(){
    var card=document.getElementById('ariellaServiceCard');
    if(!card) return;
    var state=null;
    try{state=JSON.parse(localStorage.getItem('ariellaChatState:v4')||'null');}catch(e){}
    if(!state||!state.profile||state.profile.vacation_type!=='standard') return;
    state.profile.services=['flight'];
    try{localStorage.setItem('ariellaChatState:v4',JSON.stringify(state));}catch(e){}
    card.remove();
    var messages=document.getElementById('ariellaChatMessages');
    if(!messages||messages.querySelector('[data-ariella-regular-opening="1"]')) return;
    messages.querySelectorAll('.ac-row.bot').forEach(function(row){
      var t=(row.textContent||'').trim();
      if(/איך אני יכולה לעזור|איך אני יכול לעזור|שמחה שחזרת|שמח שחזרת|טיסה כלולה בחיפוש|מה עוד תרצו שאחפש/.test(t)) row.remove();
    });
    var row=document.createElement('div');
    row.className='ac-row bot';
    row.setAttribute('data-ariella-regular-opening','1');
    var av=document.createElement('div');av.className='ac-mini-avatar';row.appendChild(av);
    var bubble=document.createElement('div');bubble.className='ac-bubble';bubble.textContent=REGULAR_OPENING;row.appendChild(bubble);
    messages.appendChild(row);
    messages.scrollTop=messages.scrollHeight;
    applyAvatar();
  }

  function enforce(){
    removeLegacy();
    document.querySelectorAll('#ariellaDesktopChat .ariella-new-chat').forEach(function(el){el.remove();});
    normalizePurposeCard();
    replaceStandardServiceCard();
    applyAvatar();
  }

  function loadChatController(){
    var chat=document.getElementById('ariellaDesktopChat');
    if(!chat||chat.dataset.ariellaChatBooted==='1'||document.getElementById('ariella-clean-controller-loader')) return;
    var script=document.createElement('script');
    script.id='ariella-clean-controller-loader';
    script.src='/static/ariella-chat-confirmation-20260911.js?v=20260914-clean-v1';
    script.async=false;
    document.body.appendChild(script);
  }

  function boot(){
    if(!isTripPage()) return;
    resetOldFlowOnce();
    patchFetch();
    document.body.classList.add('ariella-chat-preview-active');
    installStyle();
    removeLegacy();
    makeChat();
    loadAvatar();
    loadChatController();
    enforce();
    var chat=document.getElementById('ariellaDesktopChat');
    if(chat) new MutationObserver(enforce).observe(chat,{childList:true,subtree:true});
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot);
  else boot();
})();
