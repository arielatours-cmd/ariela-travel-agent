(function(){
  function toChatHref(href){
    try{
      const u=new URL(href,location.origin);
      u.searchParams.set('ariella_chat','1');
      return u.pathname+u.search+u.hash;
    }catch(e){return href;}
  }

  function boot(){
    if(document.documentElement.lang==='en') return;

    const first=[...document.querySelectorAll('a')].find(a=>(a.textContent||'').includes('תכנון החופשה הראשונה'));
    const next=[...document.querySelectorAll('a')].find(a=>(a.textContent||'').includes('תכנון החופשה הבאה'));
    const intro=document.querySelector('.account-intro');
    const empty=document.querySelector('.account-empty-section .empty-state');

    [first,next].filter(Boolean).forEach(a=>{a.href=toChatHref(a.href);});

    if(!first || !empty) return;

    if(intro){
      intro.textContent='התחברו לאריאלה והיא תעזור לכם לתכנן את החופשה הבאה שלכם — החל ממציאת טיסות, דרך אטרקציות ומקומות לינה ועד להשכרת רכב. והכול במקום אחד! ✈️';
    }

    empty.querySelector('h3')?.remove();
    empty.querySelector('p')?.remove();

    first.textContent='תכנון החופשה הראשונה שלי';
    empty.appendChild(first);
    first.style.display='block';
    first.style.width='fit-content';
    first.style.margin='0 auto';
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
