(function(){
  'use strict';

  const originalFetch = window.fetch.bind(window);

  function isAriellaChatRequest(input, init){
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    return /\/api\/ariella\/chat(?:\?|$)/.test(url) && String((init && init.method) || 'GET').toUpperCase() === 'POST';
  }

  function looksLikeCustomerQuestion(text){
    const t=String(text||'').trim();
    if(!t || t==='בחרתי את שירותי החופשה') return false;
    if(/[?？]/.test(t)) return true;
    return /^(למה|מה|איך|איפה|מתי|האם|אפשר|איזה|איזו|כמה|מי|לא הבנתי|לא שאלת|רגע|אבל|ומה לגבי|מה לגבי)/.test(t) || /לא שאלת|לא ענית|לא הבנתי|מה הכוונה|אפשר לדעת|רציתי לשאול/.test(t);
  }

  function enrichCustomerQuestion(message){
    return [
      'הודעת הלקוח המקורית:',
      message,
      '',
      'כלל שיחה מחייב: אם הלקוח שאל שאלה, העיר הערה או תיקן אותך — עני קודם ישירות ובטבעיות למה שכתב. אל תדלגי על דבריו ואל תחזרי מיד לאותה שאלת שאלון.',
      'אחרי המענה, המשיכי בעדינות לשאלה הבאה שחסרה להשלמת החופשה. אם צריך לחזור לנושא קודם כי הלקוח העיר שחסר פרט, תקני את הזרימה ושאלי עליו עכשיו.',
      'בכל שאלת בחירה, החזירי ui_choice עם 2–5 תשובות קצרות, אנושיות ורלוונטיות כדי שהלקוח יוכל לענות במהירות. אל תציגי קודים פנימיים, true/false או ערכי enum.'
    ].join('\n');
  }

  window.fetch = async function(input, init){
    if(isAriellaChatRequest(input, init) && init && typeof init.body==='string'){
      try{
        const payload=JSON.parse(init.body);
        const original=String(payload.message||'').trim();
        if(looksLikeCustomerQuestion(original)){
          payload.message=enrichCustomerQuestion(original);
          init=Object.assign({},init,{body:JSON.stringify(payload)});
        }
      }catch(e){}
    }
    return originalFetch(input, init);
  };

  function chatRoot(){return document.getElementById('ariellaDesktopChat');}
  function messagesRoot(){return chatRoot()?.querySelector('#ariellaChatMessages');}
  function inputEl(){return chatRoot()?.querySelector('#ariellaChatInput');}
  function sendEl(){return chatRoot()?.querySelector('#ariellaChatSend');}

  function optionSet(question){
    const q=String(question||'').trim();
    if(!q) return [];
    if(/טיסה ישיר|קונקשן|עציר/.test(q)) return ['טיסה ישירה בלבד','קונקשן אחד מתאים','לא משנה לי'];
    if(/שדה תעופה|מאיזה שדה|מאיפה תרצו לצאת|מאיפה תרצה לצאת/.test(q)) return ['תל אביב (TLV)','חיפה (HFA)','לא משנה לי'];
    if(/תקציב/.test(q)) return ['אין הגבלת תקציב','עד 1,500 ₪ לאדם','עד 2,500 ₪ לאדם','עד 4,000 ₪ לאדם'];
    if(/כבודה|מזוודה|טרולי/.test(q)) return ['תיק יד בלבד','טרולי 8 ק״ג','מזוודה 23 ק״ג','לא משנה לי'];
    if(/מתי תרצו|מתי תרצה|תאריכים|חודש מועדף/.test(q)) return ['תאריכים מדויקים','חודש מסוים','אני גמיש/ה בתאריכים'];
    if(/לאן תרצו|לאן תרצה|יעד/.test(q)) return ['יש לי יעד מסוים','יש לי כמה יעדים','פתוח/ה להצעות של אריאלה'];
    if(/כמה נוסעים|מי נוסע|מי משתתף/.test(q)) return ['אני לבד','זוג','משפחה עם ילדים','חברים'];
    if(/שמות.*נוסעים|שמות.*ילדים|לשמור.*שמות|רוצה.*שמות/.test(q)) return ['כן','לא'];
    if(/גמישות/.test(q)) return ['בלי גמישות','± יום אחד','± יומיים','± 3 ימים'];
    if(/מה חשוב|על מה חשוב|דגש/.test(q)) return ['מחיר משתלם','טיסה ישירה','כבודה','למקסם זמן בחופשה'];
    if(/האם|רוצה|תרצו|תרצה/.test(q) && q.endsWith('?')) return ['כן','לא'];
    return [];
  }

  function addQuickReplies(question, anchor){
    const root=messagesRoot();
    if(!root || !anchor || root.querySelector('.ac-quick-replies[data-for-latest="1"]')) return;
    const options=optionSet(question);
    if(options.length<2) return;
    root.querySelectorAll('.ac-quick-replies').forEach(x=>x.remove());
    const box=document.createElement('div');
    box.className='ac-quick-replies';
    box.dataset.forLatest='1';
    box.style.cssText='display:flex;flex-wrap:wrap;gap:8px;margin:4px 42px 12px 0;max-width:90%';
    options.forEach(label=>{
      const b=document.createElement('button');
      b.type='button';b.textContent=label;
      b.style.cssText='border:1px solid #0b8f9c;background:#fffaf2;color:#17313a;border-radius:999px;padding:8px 12px;cursor:pointer;font:inherit';
      b.addEventListener('click',()=>{
        const input=inputEl(),send=sendEl();
        if(!input||!send)return;
        input.value=label;
        box.remove();
        send.click();
      });
      box.appendChild(b);
    });
    anchor.insertAdjacentElement('afterend',box);
  }

  function inspectBotRow(row){
    if(!row?.matches?.('.ac-row.bot')) return;
    setTimeout(()=>{
      const root=messagesRoot();
      if(!root) return;
      const latest=[...root.querySelectorAll('.ac-row.bot')].pop();
      if(latest!==row) return;
      if(root.querySelector('.ac-flow-card')) return;
      const text=(row.querySelector('.ac-bubble')?.textContent||'').trim();
      if(text && /[?？]\s*$/.test(text)) addQuickReplies(text,row);
    },40);
  }

  function boot(){
    const root=messagesRoot();
    if(!root || root.dataset.conversationEnhancer==='1') return;
    root.dataset.conversationEnhancer='1';
    root.querySelectorAll('.ac-row.bot').forEach(inspectBotRow);
    new MutationObserver(muts=>muts.forEach(m=>m.addedNodes.forEach(n=>{
      if(n.nodeType===1) inspectBotRow(n);
    }))).observe(root,{childList:true});
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(boot,0));
  else setTimeout(boot,0);
})();
