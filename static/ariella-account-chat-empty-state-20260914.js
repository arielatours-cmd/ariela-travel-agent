(function(){
  function toChatHref(href){
    try{
      const u=new URL(href,location.origin);
      u.searchParams.set('ariella_chat','1');
      return u.pathname+u.search+u.hash;
    }catch(e){return href;}
  }

  function wireDirectChatLinks(){
    [...document.querySelectorAll('a')].forEach(a=>{
      const t=(a.textContent||'').trim();
      if(t.includes('תכנון החופשה הראשונה')||t.includes('תכנון החופשה הבאה')){
        a.href=toChatHref(a.href);
      }
    });
  }

  function wireMobileMenu(){
    const b=document.getElementById('mobileNavToggle');
    const m=document.getElementById('mobileNavMenu');
    const a=document.getElementById('mobileMyAriellaToggle');
    const s=document.getElementById('mobileMyAriellaSubmenu');
    if(!b||!m||b.dataset.ariellaMenuFixed==='1') return;
    b.dataset.ariellaMenuFixed='1';
    const closeSub=()=>{if(s){s.hidden=true;s.style.display='none';}if(a)a.setAttribute('aria-expanded','false');};
    const closeAll=()=>{m.hidden=true;m.style.display='none';b.setAttribute('aria-expanded','false');closeSub();};
    b.addEventListener('click',function(e){
      e.preventDefault();e.stopImmediatePropagation();
      const opening=m.hidden||getComputedStyle(m).display==='none';
      if(opening){m.hidden=false;m.style.setProperty('display','block','important');b.setAttribute('aria-expanded','true');}
      else closeAll();
    },true);
    if(a&&s){
      a.addEventListener('click',function(e){
        e.preventDefault();e.stopImmediatePropagation();
        const opening=s.hidden||getComputedStyle(s).display==='none';
        if(opening){s.hidden=false;s.style.setProperty('display','flex','important');s.style.setProperty('flex-direction','column','important');a.setAttribute('aria-expanded','true');}
        else closeSub();
      },true);
    }
    document.addEventListener('click',function(e){if(!m.contains(e.target)&&e.target!==b)closeAll();});
  }

  function buildFirstVacationButton(empty){
    let btn=empty.querySelector('.ariella-first-vacation-chat');
    if(!btn){
      btn=document.createElement('a');
      btn.className='button primary ariella-first-vacation-chat';
      btn.textContent='תכנון החופשה הראשונה שלי';
      btn.href='/trip/new?ariella_chat=1';
      empty.appendChild(btn);
    }
    btn.style.display='flex';
    btn.style.alignItems='center';
    btn.style.justifyContent='center';
    btn.style.textAlign='center';
    btn.style.width='fit-content';
    btn.style.minHeight='48px';
    btn.style.margin='0 auto';
    btn.style.padding='12px 24px';
    btn.style.lineHeight='1.2';
    btn.style.background='#17283f';
    btn.style.color='#ffffff';
    btn.style.border='1px solid #17283f';
    btn.style.borderRadius='8px';
    btn.style.textDecoration='none';
    btn.style.fontWeight='700';
    return btn;
  }

  function boot(){
    if(document.documentElement.lang==='en') return;
    wireDirectChatLinks();
    wireMobileMenu();

    const intro=document.querySelector('.account-intro');
    const emptySection=document.querySelector('.account-empty-section');
    const empty=document.querySelector('.account-empty-section .empty-state');

    if(intro){
      intro.textContent='התחברו לאריאלה והיא תעזור לכם לתכנן את החופשה הבאה שלכם — החל ממציאת טיסות, דרך אטרקציות ומקומות לינה ועד להשכרת רכב. והכול במקום אחד! ✈️';
    }

    if(!empty) return;
    empty.querySelector('h3')?.remove();
    empty.querySelector('p')?.remove();
    [...empty.querySelectorAll('a')].forEach(a=>{if(!a.classList.contains('ariella-first-vacation-chat'))a.remove();});

    if(emptySection){emptySection.style.paddingTop='12px';emptySection.style.marginTop='0';}
    empty.style.paddingTop='18px';
    empty.style.paddingBottom='18px';
    buildFirstVacationButton(empty);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
