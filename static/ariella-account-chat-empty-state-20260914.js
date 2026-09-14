(function(){
  function boot(){
    if(document.documentElement.lang==='en') return;

    const first=[...document.querySelectorAll('a')].find(a=>(a.textContent||'').includes('תכנון החופשה הראשונה'));
    const intro=document.querySelector('.account-intro');
    const empty=document.querySelector('.account-empty-section .empty-state');
    if(!first || !empty) return;

    if(intro){
      intro.textContent='התחברו לאריאלה והיא תעזור לכם לתכנן את החופשה הבאה שלכם — החל ממציאת טיסות, דרך אטרקציות ומקומות לינה ועד להשכרת רכב. והכול במקום אחד! ✈️';
    }

    const title=empty.querySelector('h3');
    const text=empty.querySelector('p');
    if(title) title.textContent='מתכננים חופשה? ✈️';
    if(text) text.textContent='דברו עם אריאלה בדיוק כמו שהייתם מדברים עם סוכנת נסיעות. ספרו לה מה אתם מחפשים, מה חשוב לכם ומה כבר החלטתם — והיא תמשיך את השיחה משם ותעזור לכם לתכנן את החופשה.';

    first.textContent='תכנון החופשה הראשונה שלי';
    empty.appendChild(first);
    first.style.display='block';
    first.style.width='fit-content';
    first.style.margin='28px auto 0';
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
