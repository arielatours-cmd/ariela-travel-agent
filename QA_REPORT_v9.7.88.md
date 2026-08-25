# Ariella QA Report — v9.7.93

## QA scope
Code audit + deterministic integration tests for scan robustness, scoring, DB-first flow, My Vacations display logic, no-result alternatives, filters, admin controls, baggage fallback, and direct booking handoff.

## Critical findings fixed

1. **Wide scan could stop around 24/30 and look stuck**
   - `_run_jobs_scan()` used an undefined variable `messages` when the API safety cap or manual stop was reached.
   - Result: the worker could fail exactly when trying to stop safely.
   - Fixed: dedicated `status_messages` list and clean shutdown.

2. **Wide-scan API safety cap was too low for 30 destinations**
   - Cap was 120 API requests.
   - Observed real usage was already ~5–6 requests per destination, so 30 destinations can legitimately require ~165–180.
   - Fixed: wide-scan cap raised to 220. This is still a safety cap, not a target.

3. **Failed destinations made progress look frozen**
   - `searches_completed` increased only after a successful API call.
   - A scan with 4 failed destinations could display 24/30 even after 28 destinations had actually been attempted.
   - Fixed: every attempted destination counts toward progress.
   - Expected behavior now: e.g. `30/30, 4 errors, partial`, instead of appearing stuck.

4. **Single external request could wait 60 seconds**
   - Reduced SerpAPI HTTP timeout to 45 seconds so one bad request does not hold the whole scan as long.

5. **Score 70 was structurally too hard during the data-bootstrap stage**
   - Without reliable historical data, the same-search price comparison is intentionally capped at 20 points.
   - Before this fix, even an excellent direct flight with baggage and good times often topped out below 70.
   - Fixed: added a small booking-reliability component:
     - direct airline booking: +8
     - approved supplier: +6
     - bookable options found: +3
   - This does **not** force deals above 70. It only makes 70 reachable for a genuinely strong, bookable deal before Ariella has deep route history.

6. **Admin score diagnostics were incomplete**
   - Reliability was always displayed as blank even if calculated.
   - Hours column did not consistently use the actual time-value component.
   - Fixed both.

## Automated QA checks passed

- Python syntax compilation
- Jinja template parsing
- Strong bootstrap-quality deal can reach 70
- Weak deal remains below 70
- Reliability component is included in scoring
- Mock 30-destination wide scan completes 30/30
- Mock 30-destination scan stays below the 220 safety budget
- One timed-out destination still yields 3/3 attempted and `partial`, not a fake stall
- API safety-cap exit is clean and records the reason
- Ski/standard questionnaire split exists
- Switching to one destination clears previous multi-destination values
- DB-first matching exists
- Exact DB match IDs are persisted for My Vacations display
- Newest vacation auto-opens
- No-result state contains both alternative searches
- Close/open handler is wired
- Direct selected-flight booking handoff exists
- Deals-page filters cover new + previous deals
- Admin filters are in table headers
- No invented baggage-price fallback remains
- Missing baggage price displays “באתר הספק”

## Important live checks after deployment

These require the deployed site and real SerpAPI/airline responses:

1. Run one wide scan and verify it reaches 30/30.
2. Record API quota before/after and total duration.
3. Check errors: a few failures are acceptable; the scan must still finish.
4. Check whether any results cross 70. Zero is possible if the market is genuinely weak; it should no longer be structurally impossible for a strong bootstrap deal.
5. Test a vacation that exactly matches a fresh DB deal: no new scan, result auto-opens.
6. Test a destination/month with no matching deal: both alternative-search buttons appear and work.
7. Test “מעבר להזמנה” on a newly scanned deal and verify it lands on the selected outbound + return booking flow.
8. Verify baggage add-on price is real when supplied; otherwise “באתר הספק”.
9. Test filters on both current and previous deals.
10. Test mobile layout and English after the functional pass.

## Release status
**QA status: READY FOR LIVE REGRESSION TESTING**

The code-level blockers found in v9.7.87 were fixed. Live external-provider behavior still needs the deployment test above before production approval.
