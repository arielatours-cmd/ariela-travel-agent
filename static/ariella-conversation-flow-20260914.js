(function(){
  'use strict';

  var FLOW_VERSION='20260914-natural-v3';
  var REGULAR_OPENING='איזה כיף 🏖️\nספרו לי קצת על החופשה שאתם מתכננים — לאן תרצו לטוס, מתי ומי נוסע.\nואם עדיין לא החלטתם לאן — אפשר גם לתת לי להמליץ לכם 😊';
  var RULES='אריאלה מנהלת שיחה טבעית כמו סוכנת נסיעות ולא שאלון. אין להציג קודים פנימיים, true/false או enum, ואין לשאול שוב מידע שכבר נמסר. בחופשה רגילה: קודם אוספים יעד או בקשה שאריאלה תבחר, מועד, ומי נוסע. אחר כך ורק אחר כך אוספים תקציב, כבודה, וישיר או קונקשן. רק לאחר שכל פרטי הטיסה נאספו שואלים אם הלקוח רוצה שאריאלה תבנה את הטיול כולו או רק עזרה בדברים מסוימים. אין לשאול אוטומטית על גמישות או משך. אין להציג לינה, רכב, אטרקציות או תכנון מסלול לפני השלמת פרטי הטיסה.';
  var avatarSrc='';

  function migrateOldFlowOnce(){
    try{
      if(localStorage.getItem('ariellaFlowVersion')===FLOW_VERSION)return;
      localStorage.removeItem('ariellaChatState:v4');
      localStorage.removeItem('ariellaChatState:v3');
      sessionStorage.removeItem('ariellaChatState:v4');
      sessionStorage.removeItem('ariellaChatState:v3');
      localStorage.setItem('ariellaFlowVersion',FLOW_VERSION);
    }catch(e){}
  }

  function patchFetch(){
    if(window.__ariellaNaturalFetchPatched)return;
    window.__ariellaNaturalFetchPatched=true;
    var original=window.fetch.bind(window);
    window.fetch=async function(input,init){
      var url=typeof input==='string'?input:(input&&input.url)||'';
      if(/\/api\/ariella\/chat(?:\?|$)/.test(url)&&init&&String(init.method||'GET').toUpperCase()==='POST'&&typeof init.body==='string'){
        try{
          var p=JSON.parse(init.body),m=String(p.message||'').trim();
          if(m)p.message='הודעת הלקוח המקורית:\n'+m+'\n\n'+RULES;
          init=Object.assign({},init,{body:JSON.stringify(p)});
        }catch(e){}
      }
      return original(input,init);
    };
  }

  function loadAvatarSource(){
    fetch('/static/ariella-avatar-runtime-20260913.js?avatar_source=20260914',{cache:'no-store'})
      .then(function(r){return r.text();})
      .then(function(js){
        var m=js.match(/const\s+src\s*=\s*'([^']+)'/);
        if(m&&m[1]){avatarSrc=m[1];applyAvatar();}
      }).catch(function(){});
  }

  function applyAvatar(){
    if(!avatarSrc)return;
    document.querySelectorAll('#ariellaDesktopChat .ac-avatar,#ariellaDesktopChat .ac-mini-avatar').forEach(function(el){
      el.textContent='';
      el.style.setProperty('background','center 38% / cover no-repeat url("'+avatarSrc+'")','important');
      el.style.setProperty('border-radius','50%','important');
      el.style.setProperty('overflow','hidden','important');
      el.style.setProperty('color','transparent','important');
    });
  }

  function removeNewChat(){
    document.querySelectorAll('#ariellaDesktopChat .ariella-new-chat').forEach(function(el){el.remove();});
  }

  function normalizePurposeCard(){
    var card=document.getElementById('ariellaPurposeCard');
    if(!card)return;
    var title=card.querySelector('strong');
    if(title)title.textContent='איזה סוג חופשה תרצו לתכנן?';
    var labels={standard:'🏖️ נופש',business:'💼 טיסת עסקים',ski:'⛷️ חופשת סקי'};
    Object.keys(labels).forEach(function(v){
      var input=card.querySelector('input[value="'+v+'"]');
      var label=input&&input.closest('label');
      if(label){
        Array.from(label.childNodes).forEach(function(n){if(n.nodeType===3)n.remove();});
        label.appendChild(document.createTextNode(' '+labels[v]));
      }
    });
    var opts=card.querySelector('.ac-flow-options');
    if(opts){['standard','business','ski'].forEach(function(v){var i=card.querySelector('input[value="'+v+'"]');if(i&&i.closest('label'))opts.appendChild(i.closest('label'));});}
    var messages=document.getElementById('ariellaChatMessages');
    if(messages){
      messages.querySelectorAll('.ac-row.bot').forEach(function(row){
        var t=(row.textContent||'').trim();
        if(/איך אני יכולה לעזור|איך אני יכול לעזור|שמחה שחזרת|שמח שחזרת/.test(t))row.remove();
      });
    }
  }

  function replacePrematureServiceCard(){
    var card=document.getElementById('ariellaServiceCard');
    if(!card)return;
    var state=null;
    try{state=JSON.parse(localStorage.getItem('ariellaChatState:v4')||'null');}catch(e){}
    var type=state&&state.profile&&state.profile.vacation_type;
    if(type!=='standard')return;
    card.remove();
    var messages=document.getElementById('ariellaChatMessages');
    if(!messages||messages.querySelector('[data-ariella-regular-opening="1"]'))return;
    messages.querySelectorAll('.ac-row.bot').forEach(function(row){
      var t=(row.textContent||'').trim();
      if(/טיסה כלולה בחיפוש|מה עוד תרצו שאחפש/.test(t))row.remove();
    });
    var row=document.createElement('div');row.className='ac-row bot';row.setAttribute('data-ariella-regular-opening','1');
    var av=document.createElement('div');av.className='ac-mini-avatar';row.appendChild(av);
    var bubble=document.createElement('div');bubble.className='ac-bubble';bubble.textContent=REGULAR_OPENING;row.appendChild(bubble);
    messages.appendChild(row);messages.scrollTop=messages.scrollHeight;applyAvatar();
    try{
      if(state&&state.profile){state.profile.services=['flight'];localStorage.setItem('ariellaChatState:v4',JSON.stringify(state));}
    }catch(e){}
  }

  function enforceCurrentUi(){
    removeNewChat();
    normalizePurposeCard();
    replacePrematureServiceCard();
    applyAvatar();
  }

  function bootDirectChat(){
    var wizard=document.getElementById('tripWizard');
    if(!wizard)return;
    migrateOldFlowOnce();patchFetch();
    document.body.classList.add('ariella-chat-preview-active');
    wizard.style.setProperty('display','none','important');
    document.querySelectorAll('#vacationTypeGate,.vacation-type-gate,.vacation-type-grid,.trip-back-bar').forEach(function(el){el.style.setProperty('display','none','important');});
    var existing=document.getElementById('ariellaDesktopChat');
    if(!existing){
      var isEn=document.documentElement.lang==='en';
      var style=document.createElement('style');style.id='ariella-direct-chat-style';
      style.textContent='#tripWizard,#vacationTypeGate,.vacation-type-gate,.vacation-type-grid,.trip-back-bar{display:none!important}#ariellaDesktopChat .ariella-new-chat{display:none!important}#ariellaDesktopChat{width:min(1280px,92%);margin:18px auto 40px;direction:'+(isEn?'ltr':'rtl')+';font-family:Arial,"Segoe UI",sans-serif}#ariellaDesktopChat .ac-shell{display:grid;grid-template-columns:minmax(0,2fr) minmax(300px,.85fr);gap:22px;align-items:stretch}#ariellaDesktopChat .ac-chat,#ariellaDesktopChat .ac-summary{background:#fffaf2;border:1px solid rgba(201,154,63,.38);border-radius:22px;box-shadow:0 14px 38px rgba(23,40,63,.08);overflow:hidden}#ariellaDesktopChat .ac-chat{height:min(650px,calc(100vh - 150px));min-height:520px;display:flex;flex-direction:column}.ac-head{display:flex;align-items:center;gap:14px;padding:20px 24px;background:linear-gradient(135deg,#102b30,#18373a);color:#fff;border-bottom:1px solid #c99a3f}.ac-avatar{width:58px;height:58px;border-radius:50%;display:grid;place-items:center;flex:0 0 auto;border:2px solid #fff3cf}.ac-head-copy strong{display:block;font-size:21px}.ac-online{margin-inline-start:auto;color:#d8e7e5;font-size:13px}.ac-messages{flex:1;min-height:0;padding:28px 30px;display:flex;flex-direction:column;gap:14px;background:linear-gradient(180deg,#fffdf8,#fbf5e9);overflow-y:auto}.ac-compose{padding:17px 20px;border-top:1px solid #eadfc8;background:#fff;display:flex;gap:10px;align-items:center}.ac-compose textarea{flex:1;min-height:52px;max-height:125px;resize:none;border:1px solid #d9cdb8;border-radius:14px;padding:14px 15px;font:inherit;background:#fffdf9;color:#17283f}.ac-send{height:52px;min-width:92px;border:0;border-radius:13px;background:#0b8f9c;color:#fff;font-weight:800;font-size:15px}.ac-summary{padding:0 22px 22px;align-self:start}.ac-summary-head{margin:0 -22px 18px;padding:20px 22px 16px;border-bottom:1px solid #eadfc8}.ac-summary-head strong{display:block;font-size:22px;color:#17283f}.ac-summary-head small{display:block;margin-top:5px;color:#75808b}.ac-detail{display:grid;grid-template-columns:34px 1fr;gap:10px;padding:11px 0;border-bottom:1px solid #eee5d5}.ac-detail b{display:block;color:#17283f;font-size:14px}.ac-detail span{display:block;color:#8a8173;font-size:14px}@media(max-width:899px){#ariellaDesktopChat{width:100%;margin:0 auto 24px;padding:8px 10px}#ariellaDesktopChat .ac-shell{display:flex;flex-direction:column;gap:12px}#ariellaDesktopChat .ac-chat{height:calc(100dvh - 125px);min-height:500px;border-radius:16px}#ariellaDesktopChat .ac-head{padding:10px 12px}.ac-online{display:none}.ac-messages{padding:18px 12px}.ac-compose{padding:10px}.ac-compose textarea{min-height:48px}.ac-send{height:48px;min-width:68px}.ac-summary{border-radius:16px}}';
      document.head.appendChild(style);
      var defs=[['destination','🌍',isEn?'Destination':'יעד'],['dates','📅',isEn?'Dates':'תאריכים'],['travelers','👥',isEn?'Travelers':'נוסעים'],['budget','💰',isEn?'Budget':'תקציב'],['flight','✈️',isEn?'Flight':'טיסה'],['baggage','🧳',isEn?'Baggage':'כבודה']];
      var rows=defs.map(function(d){return '<div class="ac-detail" data-summary-key="'+d[0]+'"><div>'+d[1]+'</div><div><b>'+d[2]+'</b><span>'+(isEn?'Not specified yet':'עדיין לא צוין')+'</span></div></div>';}).join('');
      var chat=document.createElement('section');chat.id='ariellaDesktopChat';
      chat.innerHTML='<div class="ac-shell"><div class="ac-chat"><div class="ac-head"><div class="ac-avatar"></div><div class="ac-head-copy"><strong>'+(isEn?'Ariella — your personal travel agent':'אריאלה — סוכנת הנסיעות האישית שלך')+'</strong></div><div class="ac-online">'+(isEn?'Available':'זמינה עכשיו')+'</div></div><div class="ac-messages" id="ariellaChatMessages"></div><div class="ac-compose"><textarea id="ariellaChatInput" rows="1"></textarea><button type="button" class="ac-send" id="ariellaChatSend">'+(isEn?'Send':'שליחה')+'</button></div></div><aside class="ac-summary"><div class="ac-summary-head"><strong>'+(isEn?'My vacation':'החופשה שלי')+'</strong><small>'+(isEn?'The details Ariella understands from the conversation will appear here.':'הפרטים שאריאלה תבין מהשיחה יתעדכנו כאן.')+'</small></div>'+rows+'</aside></div>';
      wizard.parentNode.insertBefore(chat,wizard);
      var script=document.createElement('script');script.src='/static/ariella-chat-confirmation-20260911.js?v=20260914-natural-v3';script.async=false;document.body.appendChild(script);
    }
    loadAvatarSource();
    enforceCurrentUi();
    new MutationObserver(enforceCurrentUi).observe(document.body,{childList:true,subtree:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bootDirectChat);else bootDirectChat();
})();
