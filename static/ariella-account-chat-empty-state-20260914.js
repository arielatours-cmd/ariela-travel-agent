(function(){
  function boot(){
    if(document.documentElement.lang==='en') return;
    const links=[...document.querySelectorAll('a')];
    const first=links.find(a=>(a.textContent||'').includes('תכנון החופשה הראשונה'));
    if(!first) return;
    const root=first.closest('section')||first.parentElement;
    if(!root) return;
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT);
    let el;
    while(el=walker.nextNode()){
      const t=(el.textContent||'').trim();
      if(/^עדיין לא חיפשת חופשה$/.test(t)) el.textContent='מתכננים חופשה? ✈️';
      else if(t.includes('מילוי השאלון')) el.textContent='דברו עם אריאלה בדיוק כמו שהייתם מדברים עם סוכנת נסיעות. ספרו לה מה אתם מחפשים, מה חשוב לכם ומה כבר החלטתם — והיא תמשיך את השיחה משם ותעזור לכם לתכנן את החופשה.';
    }
    first.textContent='תכנון החופשה הראשונה שלי';
    const card=[...root.querySelectorAll('div,article')].find(x=>(x.textContent||'').includes('מתכננים חופשה? ✈️'));
    if(card && first.parentElement!==card){card.appendChild(first);}
    first.style.display='block';first.style.width='fit-content';first.style.margin='28px auto 0';
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
