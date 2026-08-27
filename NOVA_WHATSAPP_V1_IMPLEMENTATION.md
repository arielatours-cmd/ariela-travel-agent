# NOVA — WhatsApp v1 Implementation Plan

Status: UX flow approved by product owner. This file turns the approved flow into an implementation backlog; no Meta/WhatsApp credentials are stored here.

## Phase N1 — Website entry
- Add "אריאלה שלי בנייד" in My Ariella.
- Clicking creates a short-lived signed handoff token tied to member_id (never expose raw member id).
- Open WhatsApp to the Ariella Business number with a short handoff code/message.
- On first successful handoff, link the WhatsApp phone identity to the Ariella member.

## Phase N2 — Conversation router
Supported intents:
1. My vacations
2. New vacation
3. Continue an existing vacation
4. Show latest deals
5. Continue paid search
6. Stop/pause search
7. Help / human-readable explanation

The WhatsApp channel uses the SAME trip_requests and deal-selection logic as the website; no second questionnaire engine.

## Phase N3 — New vacation
- First message: Regular / Ski / Business.
- Route to the same question definitions used on web.
- Save answers progressively to a draft trip request.
- Final confirmation creates/activates the vacation.

## Phase N4 — Existing vacation
- Load active vacations for the linked member.
- Show compact choices.
- Continue exactly from current server-side state, including DB matches, fallback stage and paid-search state.

## Phase N5 — Deal delivery
- Send up to 3 top deals.
- Include compact reasons "למה אריאלה בחרה".
- For more results, open the web account/deal view.
- Do not create a separate WhatsApp ranking algorithm.

## Phase N6 — Payment boundary
- When a paid scan is required, WhatsApp sends one CTA to the existing web payment/plan selector.
- The handoff URL identifies the vacation securely and returns the customer to WhatsApp after successful payment when supported.

## Phase N7 — Notifications
- Only send proactive messages to users who opted in.
- New/better deal alerts use the existing vacation rules and Shabbat/send-window policy.
- De-duplicate alerts so the same offer is not repeatedly sent.

## Data / endpoints required
- whatsapp_member_links(member_id, wa_phone_hash, verified_at, status)
- whatsapp_handoffs(token_hash, member_id, expires_at, used_at)
- conversation_state(member_id, active_trip_id, current_intent, updated_at) OR equivalent server-side store
- POST webhook receiver for inbound WhatsApp events
- outbound message service wrapper
- signed web handoff endpoint

## External prerequisites
- Meta WhatsApp Business Platform / Cloud API access
- Business phone number registration
- Webhook verification secret
- Approved message templates where required for proactive messages
- Cost/usage monitoring by conversation/message category

## QA before activation
- Account linking cannot link one phone to the wrong member.
- A user can resume the same vacation across web and WhatsApp.
- No duplicate scans are triggered by repeated messages.
- DB-first policy is preserved.
- Paid scan never starts before successful payment.
- Opt-out immediately stops proactive messages.
