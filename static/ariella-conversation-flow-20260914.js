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
      'הודעת הלקוח המקורית:', message, '',
      'כלל שיחה מחייב: אם הלקוח שאל שאלה, העיר הערה או תיקן אותך — עני קודם ישירות ובטבעיות למה שכתב. אל תדלגי על דבריו ואל תחזרי מיד לאותה שאלת שאלון.',
      'אחרי המענה, המשיכי בעדינות לשאלה הבאה שחסרה להשלמת החופשה. אם צריך לחזור לנושא קודם כי הלקוח העיר שחסר פרט, תקני את הזרימה ושאלי עליו עכשיו.',
      'בכל שאלת בחירה, החזירי ui_choice עם 2–5 תשובות קצרות, אנושיות ורלוונטיות כדי שהלקוח יוכל לענות במהירות. אל תציגי קודים פנימיים, true/false או ערכי enum.'
    ].join('\n');
  }

  window.fetch = async function(input, init){
    if(isAriellaChatRequest(input, init) && init && typeof init.body==='string'){
      try{const payload=JSON.parse(init.body),original=String(payload.message||'').trim();if(looksLikeCustomerQuestion(original)){payload.message=enrichCustomerQuestion(original);init=Object.assign({},init,{body:JSON.stringify(payload)});}}catch(e){}
    }
    return originalFetch(input, init);
  };

  function chatRoot(){return document.getElementById('ariellaDesktopChat');}
  function messagesRoot(){return chatRoot()?.querySelector('#ariellaChatMessages');}
  function inputEl(){return chatRoot()?.querySelector('#ariellaChatInput');}
  function sendEl(){return chatRoot()?.querySelector('#ariellaChatSend');}
  function isDateQuestion(q){return /מתי תרצו|מתי תרצה|מתי אתם רוצים|מתי אתם מעוניינים|תאריכי.*טיסה|תאריכי.*נסיעה|באילו תאריכים/.test(String(q||''));}

  function optionSet(question){
    const q=String(question||'').trim();if(!q)return [];
    if(/טיסה ישיר|קונקשן|עציר/.test(q))return ['טיסה ישירה בלבד','קונקשן אחד מתאים','לא משנה לי'];
    if(/שדה תעופה|מאיזה שדה|מאיפה תרצו לצאת|מאיפה תרצה לצאת/.test(q))return ['תל אביב (TLV)','חיפה (HFA)','לא משנה לי'];
    if(/תקציב/.test(q))return ['אין הגבלת תקציב','עד 1,500 ₪ לאדם','עד 2,500 ₪ לאדם','עד 4,000 ₪ לאדם'];
    if(/כבודה|מזוודה|טרולי/.test(q))return ['תיק יד בלבד','טרולי 8 ק״ג','מזוודה 23 ק״ג','לא משנה לי'];
    if(/מתי תרצו|מתי תרצה|תאריכים|חודש מועדף/.test(q))return ['תאריכים מדויקים','חודש מסוים','אני גמיש/ה בתאריכים'];
    if(/לאן תרצו|לאן תרצה|יעד/.test(q))return ['יש לי יעד מסוים','יש לי כמה יעדים','פתוח/ה להצעות של אריאלה'];
    if(/כמה נוסעים|מי נוסע|מי משתתף/.test(q))return ['אני לבד','זוג','משפחה עם ילדים','חברים'];
    if(/שמות.*נוסעים|שמות.*ילדים|לשמור.*שמות|רוצה.*שמות/.test(q))return ['כן','לא'];
    if(/גמישות/.test(q))return ['בלי גמישות','± יום אחד','± יומיים','± 3 ימים'];
    if(/מה חשוב|על מה חשוב|דגש/.test(q))return ['מחיר משתלם','טיסה ישירה','כבודה','למקסם זמן בחופשה'];
    if(/האם|רוצה|תרצו|תרצה/.test(q)&&q.endsWith('?'))return ['כן','לא'];return [];
  }

  function todayIso(){const d=new Date(),o=d.getTimezoneOffset();return new Date(d.getTime()-o*60000).toISOString().slice(0,10);}
  function formatDate(v){if(!v)return '';const [y,m,d]=v.split('-');return `${d}.${m}.${y}`;}
  function addDatePicker(anchor){
    const root=messagesRoot();if(!root||!anchor||root.querySelector('.ac-date-range[data-for-latest="1"]'))return;
    root.querySelectorAll('.ac-date-range,.ac-quick-replies').forEach(x=>x.remove());
    const box=document.createElement('div');box.className='ac-date-range';box.dataset.forLatest='1';box.dir='rtl';
    box.style.cssText='display:flex;flex-wrap:wrap;align-items:end;gap:10px;margin:5px 42px 12px 0;max-width:92%;padding:12px 14px;border:1px solid #dccb9f;border-radius:14px;background:#fffaf2';
    box.innerHTML=`<label style="display:grid;gap:5px;font-weight:700">מ־<input type="date" data-date-from min="${todayIso()}" style="font:inherit;padding:8px;border:1px solid #cdbd9a;border-radius:9px;background:#fff"></label><label style="display:grid;gap:5px;font-weight:700">עד<input type="date" data-date-to min="${todayIso()}" style="font:inherit;padding:8px;border:1px solid #cdbd9a;border-radius:9px;background:#fff"></label><button type="button" data-date-send style="border:0;background:#0b8f9c;color:#fff;border-radius:10px;padding:10px 16px;font:inherit;font-weight:800;cursor:pointer">המשך</button><div data-date-error hidden style="width:100%;color:#9b3b31;font-size:13px">יש לבחור תאריך יציאה ותאריך חזרה.</div>`;
    const from=box.querySelector('[data-date-from]'),to=box.querySelector('[data-date-to]'),go=box.querySelector('[data-date-send]'),err=box.querySelector('[data-date-error]');
    from.addEventListener('change',()=>{to.min=from.value||todayIso();if(to.value&&to.value<from.value)to.value='';});
    go.addEventListener('click',()=>{if(!from.value||!to.value||to.value<from.value){err.hidden=false;return;}const input=inputEl(),send=sendEl();if(!input||!send)return;input.value=`מ־${formatDate(from.value)} עד ${formatDate(to.value)}`;box.remove();send.click();});
    anchor.insertAdjacentElement('afterend',box);
  }

  function addQuickReplies(question,anchor){
    const root=messagesRoot();if(!root||!anchor||root.querySelector('.ac-quick-replies[data-for-latest="1"]'))return;
    const options=optionSet(question);if(options.length<2)return;root.querySelectorAll('.ac-quick-replies').forEach(x=>x.remove());
    const box=document.createElement('div');box.className='ac-quick-replies';box.dataset.forLatest='1';box.style.cssText='display:flex;flex-wrap:wrap;gap:8px;margin:4px 42px 12px 0;max-width:90%';
    options.forEach(label=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.style.cssText='border:1px solid #0b8f9c;background:#fffaf2;color:#17313a;border-radius:999px;padding:8px 12px;cursor:pointer;font:inherit';b.addEventListener('click',()=>{const input=inputEl(),send=sendEl();if(!input||!send)return;input.value=label;box.remove();send.click();});box.appendChild(b);});anchor.insertAdjacentElement('afterend',box);
  }

  function inspectBotRow(row){
    if(!row?.matches?.('.ac-row.bot'))return;
    setTimeout(()=>{const root=messagesRoot();if(!root)return;const latest=[...root.querySelectorAll('.ac-row.bot')].pop();if(latest!==row||root.querySelector('.ac-flow-card'))return;const text=(row.querySelector('.ac-bubble')?.textContent||'').trim();if(!text)return;if(isDateQuestion(text)){addDatePicker(row);return;}if(/[?？]\s*$/.test(text))addQuickReplies(text,row);},40);
  }

  function boot(){const root=messagesRoot();if(!root||root.dataset.conversationEnhancer==='1')return;root.dataset.conversationEnhancer='1';root.querySelectorAll('.ac-row.bot').forEach(inspectBotRow);new MutationObserver(muts=>muts.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1)inspectBotRow(n);}))).observe(root,{childList:true});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(boot,0));else setTimeout(boot,0);
})();
