# Ariella search renewal model — v9.5.5

- No recurring subscription and no automatic billing.
- Prices remain displayed as price / month.
- Customer action label: "חדש חיפוש" / "Renew search".
- Each checkout is a one-time payment.
- Four days before expiry, send an email with a direct link to My Ariella / the customer's vacations.
- The customer chooses the desired search frequency again and pays again.
- On confirmed renewal payment, set the new paid search expiry to payment time + 34 days.
- If the customer does nothing, search stops at expiry with no charge.
- Mobile alerts are available only while a paid search period is active.
- Payment integration must not mark a period active until Isracard confirms payment.

## UI state flow
1. New vacation submission triggers the initial free scan automatically.
2. Results from that scan are displayed for the vacation.
3. Before any paid search purchase, CTA = "התחל חיפוש" / "Start search".
4. CTA opens the three paid frequency choices.
5. After confirmed payment, the paid search is active and WhatsApp alerts toggle is available.
6. If the customer has paid for this vacation before and the paid period is no longer active, CTA = "חדש חיפוש" / "Renew search".
7. Renewal opens the same three frequency choices.
8. WhatsApp alerts are never offered for the initial free scan; only for an active paid search.
