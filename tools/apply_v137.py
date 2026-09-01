from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected marker not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) My Ariella: replace the legacy 3-frequency pricing with the approved 19/29 plans.
account = ROOT / "templates" / "account.html"
old_plans = '''              {% for plan, he_name, en_name, he_freq, en_freq, price in [
                ('calm','רגוע','Relaxed','פעם ב־3 ימים','Every 3 days','₪4.90'),
                ('daily','יומי','Daily','פעם ביום','Once a day','₪9.90'),
                ('intensive','אינטנסיבי','Intensive','3 פעמים ביום','3 times a day','₪14.90')
              ] %}
              <form method="post" action="{{ url_for('site.renew_trip_search', trip_id=trip.id) }}">
                <input type="hidden" name="plan" value="{{ plan }}">
                <button type="submit" class="plan-choice {{ 'recommended' if plan == 'daily' else '' }}">
                  {% if plan == 'daily' %}<em>{{ 'Recommended' if site_lang == 'en' else 'מומלץ' }}</em>{% endif %}
                  <strong>{{ en_name if site_lang == 'en' else he_name }}</strong>
                  <span>{{ en_freq if site_lang == 'en' else he_freq }}</span>
                  <b>{{ price }} / {{ 'month' if site_lang == 'en' else 'חודש' }}</b>
                </button>
              </form>
              {% endfor %}'''
new_plans = '''              {% for plan, he_name, en_name, he_freq, en_freq, price in [
                ('monitor','מעקב אישי','Personal monitoring','עדכון על דילים חדשים שמתאימים לחיפוש שלך','New deals that match your search','₪19'),
                ('daily_scan','מעקב + סריקה יומית','Monitoring + daily scan','עדכונים + סריקה אישית נוספת פעם ביום','Updates + one additional personal scan per day','₪29')
              ] %}
              <form method="post" action="{{ url_for('site.renew_trip_search', trip_id=trip.id) }}">
                <input type="hidden" name="plan" value="{{ plan }}">
                <button type="submit" class="plan-choice {{ 'recommended' if plan == 'daily_scan' else '' }}">
                  {% if plan == 'daily_scan' %}<em>{{ 'Recommended' if site_lang == 'en' else 'מומלץ' }}</em>{% endif %}
                  <strong>{{ en_name if site_lang == 'en' else he_name }}</strong>
                  <span>{{ en_freq if site_lang == 'en' else he_freq }}</span>
                  <b>{{ price }} / {{ 'month' if site_lang == 'en' else 'חודש' }}</b>
                </button>
              </form>
              {% endfor %}
              <small class="paid-search-note">{{ 'One-time payment for one month. No automatic renewal.' if site_lang == 'en' else 'תשלום חד־פעמי לחודש אחד. ללא חידוש אוטומטי.' }}</small>'''
replace_once(account, old_plans, new_plans)


# 2) Backend plan names + payment-completion activation hook.
site = ROOT / "public_site.py"
replace_once(
    site,
    'from booker import resolve_booking_target\n',
    'from booker import resolve_booking_target\nfrom whatsapp import WhatsAppConfigurationError, WhatsAppSendError, send_text_message\n',
)
replace_once(
    site,
    '    allowed = {"calm", "daily", "intensive"}\n',
    '    allowed = {"monitor", "daily_scan"}\n',
)

payment_marker = '''@site.post("/trip/<int:trip_id>/renew-search")
@login_required
def renew_trip_search(trip_id):'''
payment_helpers = '''PAID_SEARCH_PLANS = {
    "monitor": {"amount_ils": 19.0, "daily_scan": False},
    "daily_scan": {"amount_ils": 29.0, "daily_scan": True},
}


def activate_paid_search_after_payment(trip_id: int, member_id: int, plan: str) -> bool:
    """Activate one paid search only after the payment provider confirms payment.

    The payment callback should call this function after it has validated the
    provider response and persisted the paid transaction. Payment failure must
    never call this function.
    """
    if plan not in PAID_SEARCH_PLANS:
        return False

    started = datetime.now(timezone.utc)
    ends = started + timedelta(days=30)
    with _db() as conn:
        row = conn.execute(
            """SELECT t.id,t.request_name,t.travel_window,m.full_name,m.phone
               FROM trip_requests t
               JOIN members m ON m.id=t.member_id
               WHERE t.id=? AND t.member_id=? AND m.status='active'""",
            (trip_id, member_id),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            """UPDATE trip_requests
               SET status='active', ended_at=NULL, subscription_plan=?,
                   subscription_status='active', subscription_started_at=?,
                   search_period_started_at=?, search_period_ends_at=?,
                   renewal_reminder_sent_at=NULL, has_paid_search=1,
                   mobile_notifications=1, subscription_cancel_at_period_end=0
               WHERE id=? AND member_id=?""",
            (plan, started.isoformat(), started.isoformat(), ends.isoformat(), trip_id, member_id),
        )
        conn.commit()
        member = dict(row)

    # WhatsApp delivery is best-effort and must not undo an already confirmed payment.
    phone = str(member.get("phone") or "").strip()
    if phone:
        first_name = str(member.get("full_name") or "").strip().split(" ")[0] or ""
        vacation = str(member.get("request_name") or "החופשה שלך").strip()
        if plan == "daily_scan":
            body = (
                f"היי {first_name} 😊\n"
                f"החיפוש שלך עבור {vacation} פעיל ✈️\n\n"
                "מעכשיו אעדכן אותך כאן על דילים חדשים שמתאימים לחיפוש שלך, "
                "ובנוסף אצא פעם ביום לסריקה עבור החיפוש.\n\n"
                "השירות פעיל למשך חודש, בתשלום חד־פעמי וללא חידוש אוטומטי."
            )
        else:
            body = (
                f"היי {first_name} 😊\n"
                f"החיפוש שלך עבור {vacation} פעיל ✈️\n\n"
                "מעכשיו אעדכן אותך כאן כשייכנס דיל חדש שמתאים לחיפוש שלך.\n\n"
                "השירות פעיל למשך חודש, בתשלום חד־פעמי וללא חידוש אוטומטי."
            )
        try:
            send_text_message(body, recipient=phone)
        except (WhatsAppConfigurationError, WhatsAppSendError):
            pass
    return True


''' + payment_marker
replace_once(site, payment_marker, payment_helpers)

print("Applied Ariella v9.7.137 paid-search / WhatsApp activation patch")
