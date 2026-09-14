(function(){
'use strict';

const originalFetch=window.fetch.bind(window);
const MAX_QUESTION_WAIT_MS=4000;

const FLOW_RULES=`
שפת השיחה של אריאלה חייבת להרגיש כמו שיחה עם סוכנת נסיעות אמיתית, לא כמו שאלון.
אל תציגי ערכים טכניים, enum, true/false או שמות שדות פנימיים.
אל תציגי כפתורי בחירה בתוך שלבי החופשה הרגילה. בקשי תשובה חופשית, אלא אם הממשק עצמו מחייב בחירה.
לעולם אל תשאלי שוב מידע שהלקוח כבר מסר, גם אם הוא מסר אותו מוקדם מהצפוי.

זרימת נופש רגיל:
1. בתחילת החופשה בקשי יחד ובמשפט טבעי: יעד, מתי ומי נוסע. הנוסח המועדף הוא: "ספרו לי קצת על החופשה שאתם מתכננים — לאן תרצו לטוס, מתי ומי נוסע. ואם עדיין לא החלטתם לאן — אפשר גם לתת לי להמליץ לכם 😊".
2. חלצי מהתשובה את כל המידע שנמסר ושאלי רק על מה שחסר מתוך יעד/מועד/נוסעים. אם הלקוח ביקש המלצה או כתב שלא משנה היעד, התייחסי לכך כבקשה מאריאלה לבחור יעד ואל תשאלי שוב לאן.
3. פרשי זמן באופן טבעי: תאריכים מדויקים נשמרים כפי שנמסרו; חודש כללי פירושו חיפוש בכל החודש; "סופ״ש" פירושו יציאה ברביעי/חמישי וחזרה בשבת/ראשון; "שבוע" פירושו ראשון עד חמישי; תקופה כמו "סוף אוקטובר" נשמרת כטווח התקופה שנאמרה. אין לשאול שאלת גמישות אוטומטית.
4. אחרי שיש יעד/המלצה + זמן + נוסעים, שאלי יחד ובתשובה חופשית על תקציב, כבודה וישיר/קונקשן. הנוסח המועדף: "מעולה 😊 ומה חשוב לכם מבחינת הטיסה? ספרו לי אם יש תקציב שתרצו לעמוד בו, איזו כבודה תצטרכו ואם חשוב לכם לטוס ישיר או שגם קונקשן יכול להתאים." אם חלק מהפרטים כבר נמסרו, שאלי רק על החסרים.
5. אחר כך שאלי האם הלקוח רוצה שאריאלה תבנה גם את הטיול כולו או רק תעזור בדברים מסוימים. הנוסח המועדף: "ומה לגבי החופשה עצמה? 😊 תרצו שאעזור לכם לבנות גם את הטיול — מסלול, אטרקציות, מקומות לינה ורכב — או שאתם כבר יודעים מה אתם רוצים ורק צריכים עזרה בדברים מסוימים?"
6. אם אריאלה בונה את הטיול: קודם שאלי מה אוהבים לעשות ומה פחות; אחר כך בונים מסלול הגיוני לפי הימים; רק לאחר מבנה המסלול מתאימים מקומות לינה; ורק לאחר מכן קובעים אם צריך רכב, לאילו ימים, והיכן נכון לקחת ולהחזיר אותו.
7. אם הלקוח רוצה אטרקציות בלבד, שאלי: "בשמחה 😊 איזה דברים אתם אוהבים לעשות בחופשה? ספרו לי מה מעניין אתכם ומה פחות, כדי שאוכל להתאים לכם אטרקציות שבאמת תיהנו מהן." השתמשי בגילי הילדים והרכב הנוסעים שכבר נמסרו.
8. אם הלקוח רוצה לינה, קודם בררי אם מלון או וילה/דירה. למלון תני דוגמאות כמו רמה, תקציב, מיקום, ארוחת בוקר/הכול כלול, בריכה, ספא וחדרי משפחה. לוילה/דירה תני דוגמאות כמו חדרי שינה, תקציב, מיקום, מטבח, בריכה, חצר וחדרי רחצה. הדוגמאות הן כיוון בלבד ולא שדות חובה.
9. אם הלקוח רוצה רכב, שאלי באופן פתוח על העדפות כמו אוטומטי/ידני, רגיל/SUV וכיסאות ילדים. אל תשאלי שוב כמה נוסעים או כמה מזוודות אם המידע כבר קיים. התאמת הרכב חייבת לקחת בחשבון גם מספר נוסעים וגם כמות כבודה, ולסנן מראש רכבים קטנים מדי. אם אריאלה בנתה מסלול, נקודות וימי האיסוף/ההחזרה של הרכב נגזרים מהמסלול ולא נשאלים סתם.
10. בסיום ההשלמות שאלי: "יש עוד משהו שחשוב לכם בחופשה שאדע לפני שאני מתחילה לחפש? 😊" ואז עוברים לחיפוש.
11. "חופשה חדשה" ומשפטים מקבילים כמו "בואי נחפש משהו אחר" או "נתחיל מחדש" פותחים חופשה/חיפוש חדש לאותו משתמש. אין למחוק משתמש, היסטוריה או חופשות קודמות.
`;

function isAriellaChatRequest(input,init){
  const url=typeof input==='string'?input:(input&&input.url)||'';
  return /\/api\/ariella\/chat(?:\?|$)/.test(url)&&String((init&&init.method)||'GET').toUpperCase()==='POST';
}

function looksLikeCustomerQuestion(text){
  const t=String(text||'').trim();
  if(!t)return false;
  if(/[?？]/.test(t))return true;
  return /^(למה|מה|איך|איפה|מתי|האם|אפשר|איזה|איזו|כמה|מי|לא הבנתי|לא שאלת|רגע|אבל|ומה לגבי|מה לגבי)/.test(t)||/לא שאלת|לא ענית|לא הבנתי|מה הכוונה|אפשר לדעת|רציתי לשאול/.test(t);
}

function enrichMessage(message){
  const questionRule=looksLikeCustomerQuestion(message)
    ?'הודעת הלקוח היא שאלה/הערה/תיקון: עני קודם ישירות ובטבעיות למה שכתב, ורק אחר כך המשיכי מהנקודה המתאימה בלי לחזור על מידע שכבר התקבל.'
    :'';
  return [
    'הודעת הלקוח המקורית:',message,'',FLOW_RULES,questionRule,
    'העדיפי שאלה אחת טבעית שמאפשרת ללקוח למסור כמה פרטים יחד, ולא סדרה של שאלות טופס.'
  ].filter(Boolean).join('\n');
}

function hasTime(p){
  return !!((p.departure_date&&p.return_date)||p.outbound_month||p.return_month||p.travel_window||p.date_text||p.period_text);
}
function hasParty(p){
  return Number(p.adults)>0||Number(p.children)>0||Number(p.infants)>0||!!p.travel_party||!!p.party_text;
}
function hasDestination(p){
  return !!((Array.isArray(p.destinations)&&p.destinations.length)||p.destination_mode==='ariella_choice'||p.ariella_recommends||p.destination_text);
}
function hasBudget(p){return !!(p.budget_amount||p.budget_mode==='unlimited'||p.budget_text);}
function hasBaggage(p){return !!(p.baggage||p.baggage_text);}
function hasFlightPreference(p){return !!(p.flight_preference||p.connection_preference||p.stops_preference);}

function fastQuestionFromProfile(p){
  p=p||{};
  const missingBasic=[];
  if(!hasDestination(p))missingBasic.push('לאן תרצו לטוס');
  if(!hasTime(p))missingBasic.push('מתי תרצו לנסוע');
  if(!hasParty(p))missingBasic.push('מי נוסע');
  if(missingBasic.length){
    if(missingBasic.length===3)return 'ספרו לי קצת על החופשה שאתם מתכננים — לאן תרצו לטוס, מתי ומי נוסע. ואם עדיין לא החלטתם לאן — אפשר גם לתת לי להמליץ לכם 😊';
    return `חסר לי רק עוד קצת כדי להתקדם 😊 ${missingBasic.join(', ')}?`;
  }
  const missingFlight=[];
  if(!hasBudget(p))missingFlight.push('תקציב');
  if(!hasBaggage(p))missingFlight.push('כבודה');
  if(!hasFlightPreference(p))missingFlight.push('טיסה ישירה או קונקשן');
  if(missingFlight.length){
    if(missingFlight.length===3)return 'מעולה 😊 ומה חשוב לכם מבחינת הטיסה? ספרו לי אם יש תקציב שתרצו לעמוד בו, איזו כבודה תצטרכו ואם חשוב לכם לטוס ישיר או שגם קונקשן יכול להתאים.';
    return `מעולה 😊 נשאר לי להבין רק ${missingFlight.join(', ')}. ספרו לי מה מתאים לכם.`;
  }
  if(!p.trip_planning_preference&&!p.full_trip_planning&&!p.services_decided){
    return 'ומה לגבי החופשה עצמה? 😊 תרצו שאעזור לכם לבנות גם את הטיול — מסלול, אטרקציות, מקומות לינה ורכב — או שאתם כבר יודעים מה אתם רוצים ורק צריכים עזרה בדברים מסוימים?';
  }
  return '';
}

function syntheticResponse(question,profile){
  return new Response(JSON.stringify({status:'success',reply:question,profile:profile||{},ariella_fast_fallback:true}),{status:200,headers:{'Content-Type':'application/json'}});
}

window.fetch=async function(input,init){
  if(isAriellaChatRequest(input,init)&&init&&typeof init.body==='string'){
    try{
      const payload=JSON.parse(init.body);
      const original=String(payload.message||'').trim();
      const profile=payload.profile||{};
      if(original){
        payload.message=enrichMessage(original);
        init=Object.assign({},init,{body:JSON.stringify(payload)});
      }
      const requestPromise=originalFetch(input,init);
      const fastQuestion=fastQuestionFromProfile(profile);
      if(fastQuestion&&!looksLikeCustomerQuestion(original)){
        const timeoutPromise=new Promise(resolve=>setTimeout(()=>resolve(syntheticResponse(fastQuestion,profile)),MAX_QUESTION_WAIT_MS-250));
        return await Promise.race([requestPromise,timeoutPromise]);
      }
      return await requestPromise;
    }catch(e){
      return originalFetch(input,init);
    }
  }
  return originalFetch(input,init);
};

// Intentionally no quick-reply, date-picker or passenger-picker injection here.
// The regular vacation flow is free-form so the same conversational language can be reused in WhatsApp.
})();
