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
    const emptySection=document.querySelector('.account-empty-section');
    const empty=document.querySelector('.account-empty-section .empty-state');

    [first,next].filter(Boolean).forEach(a=>{a.href=toChatHref(a.href);});

    if(!first || !empty) return;

    if(intro){
      intro.textContent='התחברו לאריאלה והיא תעזור לכם לתכנן את החופשה הבאה שלכם — החל ממציאת טיסות, דרך אטרקציות ומקומות לינה ועד להשכרת רכב. והכול במקום אחד! ✈️';
    }

    empty.querySelector('h3')?.remove();
    empty.querySelector('p')?.remove();

    if(emptySection){
      emptySection.style.paddingTop='12px';
      emptySection.style.marginTop='0';
    }
    empty.style.paddingTop='18px';
    empty.style.paddingBottom='18px';

    first.textContent='תכנון החופשה הראשונה שלי';
    empty.appendChild(first);
    first.style.display='flex';
    first.style.alignItems='center';
    first.style.justifyContent='center';
    first.style.textAlign='center';
    first.style.width='fit-content';
    first.style.minHeight='48px';
    first.style.margin='0 auto';
    first.style.padding='12px 24px';
    first.style.lineHeight='1.2';
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
