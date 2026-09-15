"""Runtime conversation hotfix for Ariella/Tinkerbell, 2026-09-15."""
try:
    import travel_agents as ta

    ta.TINKERBELL_SYSTEM += r'''

כל הודעת לקוח עוברת דרכך להבנה סמנטית, גם אם היא קצרה או כוללת שגיאות כתיב. אל תסתמכי רק על מילות מפתח קשיחות.
הביני יחסי משפחה ומספר נוסעים מן ההקשר: "אני והבת שלי"/"עם הבת שלי" = מבוגר אחד + ילדה אחת; "אני והבן שלי" = מבוגר אחד + ילד אחד; "אני ובעלי"/"אני ואשתי" = שני מבוגרים; "אני ובעלי ושני הילדים" = שני מבוגרים ושני ילדים. אם מספר הילדים ידוע אבל גיליהם חסרים, סמני children בהתאם ואל תבקשי שוב את מספר הנוסעים; הגילים בלבד חסרים.
זהי כוונת שינוי גם בלי מילת מפתח מדויקת. ניסוחים כגון "בעצם", "תשני", "טעיתי", "במקום", "שיניתי את דעתי", "לא, אני רוצה", או ניסוח סמנטי שמתקן פרט קודם, משמעותם עדכון הנתון הקיים. החזירי profile_patch עם הערך החדש. אם לא ברור מה לשנות, הוסיפי change_intent לרשימת unclear ואל תנחשי.
"מהתחלה" לבדו הוא בקשה אפשרית להתחיל מחדש ולכן יש לאמת אם הלקוח רוצה להתחיל את כל תכנון החופשה מחדש או רק לשנות פרט מסוים.
טיסה מישראל: אם הלקוח לא ציין שדה יציאה אחר, ברירת המחדל היא TLV/נתב״ג. אם צוין שדה אחר, החליפי את ברירת המחדל.
ישיר/קונקשן וכבודה הם שני פרטים שניתן להבין מאותה תשובה. למשל "ישיר וטרולי" => flight_preference=direct וגם baggage=trolley.
'''

    ta.ARIELLA_SYSTEM += r'''

סדר השיחה לטיסה: יעד/מועד/נוסעים; אחר כך ישיר או קונקשן וכבודה יחד; ורק בסוף מגבלת תקציב לאדם. נתב״ג הוא ברירת המחדל ואין לשאול על שדה יציאה אלא אם הלקוח ביקש לשנותו.
אם חסרים גילי ילדים שכבר נספרו, שאלי רק לגילים ולא שוב כמה נוסעים יש.
כאשר הלקוח מבקש שינוי, אשרי בקצרה את השינוי. אם הוא כתב רק "מהתחלה", שאלי אם להתחיל את כל התכנון מחדש או לשנות פרט מסוים.
מותר להוסיף מדי פעם תגובה אנושית קצרה ורלוונטית למה שנאמר, אך לא אחרי כל הודעה ולא באופן שמאריך את התהליך.
'''

    _orig_tinkerbell = ta._call_tinkerbell
    def _fast_tinkerbell(message, history, profile):
        base = dict(profile or {})
        # TLV is the product default unless the customer explicitly changes it.
        base.setdefault("departure_airports", ["TLV"])
        result = _orig_tinkerbell(message, history, base)
        patch = result.setdefault("profile_patch", {})
        patch.setdefault("departure_airports", base.get("departure_airports") or ["TLV"])
        return result
    ta._call_tinkerbell = _fast_tinkerbell

    # Ariella's model response was not used by the endpoint: _next_question decides
    # the customer reply. Avoiding this second sequential model call roughly halves
    # conversational model latency while Tinkerbell remains the semantic interpreter.
    def _fast_ariella(message, history, profile, tinkerbell):
        return {"profile": dict(profile or {})}
    ta._call_ariella = _fast_ariella

    def _shared_question(p):
        if not ta._has_destination(p):
            return "לאן תרצו לנסוע? אם עדיין לא החלטתם, אני יכולה גם להמליץ 😊"
        if not ta._has_dates(p):
            return "מתי תרצו לנסוע? אפשר תאריכים מדויקים או חודש מועדף."
        if not ta._has_travelers(p):
            return "מי נוסע איתכם?"
        children = int(p.get("children") or 0)
        ages = p.get("child_ages") or []
        if children and len(ages) < children:
            if children == 1:
                return "בת/בן כמה הילד או הילדה שנוסעים איתכם?"
            return "מה הגילים של הילדים שנוסעים איתכם?"
        party = str(p.get("travel_party_type") or "").lower()
        if party in {"family", "friends", "couple", "משפחה", "חברים", "זוג"} and p.get("save_traveler_names") is None:
            return "רוצים לשתף את השמות הפרטיים של מי שנוסע איתכם כדי שאזכור אותם לחיפושים הבאים?"
        if p.get("save_traveler_names") is True and not p.get("traveler_names"):
            return "כתבו את השמות הפרטיים של הנוסעים שתרצו שאזכור."
        return ""
    ta._shared_question = _shared_question

    def _flight_question(p):
        direct_missing = not p.get("flight_preference")
        baggage_missing = not p.get("baggage")
        if direct_missing or baggage_missing:
            if direct_missing and baggage_missing:
                return "ומה חשוב לכם מבחינת הטיסה? חשוב לכם לטוס ישיר, או שגם קונקשן יכול להתאים? ואיזו כבודה תצטרכו — תיק יד, טרולי או מזוודה?"
            if direct_missing:
                return "חשוב לכם לטוס ישיר, או שגם קונקשן יכול להתאים?"
            return "איזו כבודה תצטרכו — תיק יד, טרולי או מזוודה?"
        if not ta._has_budget(p):
            return "ולסיום, יש תקציב לאדם שתרצו שאשתדל לעמוד בו, או שאין מגבלת תקציב?"
        return ""
    ta._flight_question = _flight_question

    _orig_next = ta._next_question
    def _human_next_question(p):
        q, stage = _orig_next(p)
        previous = p.get("_ariella_chatter_stage")
        if q and previous != stage:
            p["_ariella_chatter_stage"] = stage
            if stage == "flight" and ta._has_destination(p):
                q = "מעולה 😊 " + q
        return q, stage
    ta._next_question = _human_next_question
except Exception:
    # Startup must never fail because of a conversational hotfix.
    pass
