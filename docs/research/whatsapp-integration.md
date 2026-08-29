# WhatsApp integration for nidaro — research findings

Researched 2026-08 against Meta's primary documentation (developers.facebook.com, whatsapp.com legal pages), Twilio and 360dialog pricing pages, and the source repos of the unofficial bridges. Facts are current as of the "Updated" dates on the cited pages. Written for an engineer who knows nidaro but not the WhatsApp Business API.

## Verdict

Build WhatsApp on the official **WhatsApp Business Platform Cloud API**: register one WABA + business phone number, receive messages via a signed webhook (`X-Hub-Signature-256`), reply through `POST /{phone_number_id}/messages`, and treat everything as DMs — group participation is effectively unavailable on the official API (the new Groups API requires Official Business Account status, business-created invite-only groups capped at 8 participants, and a Cloud API number cannot be added to ordinary user-created groups). This forces a design change to requirement 2: "passive tracking of conversations" can only cover messages that arrive at the nidaro number after connection — there is no message-history API (the sole exception is a one-time 180-day history sync when migrating a WhatsApp Business *app* number, which requires Tech/Solution-Provider status). So "agreed things" must be captured through trigger-word DMs, reply/quote joins (`context.id`), forwarded messages (flagged in the webhook), and interactive confirmation buttons rather than background group eavesdropping. Within nidaro, keep it at the connector seam: a webhook route that acks in milliseconds and hands raw payloads to a Taskiq task, a staging store drained by a `WhatsAppConnector` into `ExternalRecord`s, deterministic trigger parsing, the existing `AssistantRuntime` for intent, and a `WhatsAppSender` application service for outbound. Two business-level risks need a human decision before building: (a) whether nidaro counts as an "AI Provider" under WhatsApp's Business Solution Terms of Jan 15 2026, which restricts general-purpose AI assistants to jurisdictions where Meta is legally required to allow them; and (b) service-message replies become paid on Oct 1 2026 (small at household volume, e.g. $0.0068/message in Brazil).

**Decision recorded 2026-08:** group listening will be delivered by a read-only browser observer — a real Chrome session on a **sacrificial number** driven through [chrome-agent](https://github.com/captivus/chrome-agent) (§3.4) — feeding the same connector seam as the official webhook. Trigger-word *actions*, outbound sends, and LLM interpretation stay on the official Cloud API number.

## 1. The official path: WhatsApp Business Platform Cloud API

### 1.1 Account model

The Cloud API is one of the surfaces of the WhatsApp Business Platform ([about the platform](https://developers.facebook.com/documentation/business-messaging/whatsapp/about-the-platform)). You create a Meta app, a WhatsApp Business Account (WABA), and register a business phone number identified by a `phone_number_id`; calls authenticate with a Bearer token and go to `https://graph.facebook.com/<API_VERSION>/...`. Messaging limits are business-portfolio-based, not per-number ([about the platform](https://developers.facebook.com/documentation/business-messaging/whatsapp/about-the-platform)). Graph API versions roll quarterly; the docs' examples use v25.0/v26.0 — pin the version in config and track the [changelog](https://developers.facebook.com/documentation/business-messaging/whatsapp/changelog).

### 1.2 Webhook: verification handshake, signature, ack-then-process

Webhooks for WhatsApp follow Meta's generic webhook mechanics ([Get started with webhooks](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/)):

- **Verification handshake** (when you register the callback URL in the App Dashboard): Meta sends `GET .../webhooks?hub.mode=subscribe&hub.challenge=<int>&hub.verify_token=<string>`. The endpoint must check `hub.verify_token` against the token configured in the dashboard and respond `200` with the raw `hub.challenge` value. TLS with a valid certificate is required; self-signed certs are rejected.
- **Event notifications**: `POST` with a JSON payload and a `X-Hub-Signature-256: sha256=<hex>` header — an HMAC-SHA256 of the raw request body keyed with the app's **App Secret**. Validation is optional but strongly recommended: compute the HMAC over the exact bytes received and compare in constant time. Meta additionally supports optional **mTLS**: client certificates signed by Meta's CA (`meta-outbound-api-ca-2025-12.pem`, CN `client.webhooks.fbclientcerts.com`) that your load balancer can enforce ([getting started, mTLS section](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/)).
- **Ack fast, process async**: respond `200 OK` to every event. Failed deliveries are retried "immediately, then ... a few more times with decreasing frequency over the next 36 hours"; unacknowledged updates are dropped after 36 hours. Retries mean **you must deduplicate** (message IDs are stable). Payloads may be batched — "aggregated and sent in a batch with a maximum of 1000 updates" — so iterate `entry`/`changes` arrays; don't assume one message per request. The same page states the historical-data rule: "You will not be able to query historical webhook event notification data, so be sure to capture and store any webhook payload content that you want to keep." This is the primary-source basis for persisting raw payloads at ingest.
- Subscribe to the `messages` field (inbound messages + outbound delivery statuses) and optionally `account_update` (number/WABA status changes).

### 1.3 Inbound payload shape (DMs)

Documented in the [messages webhook reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages) and per-type references such as [text](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text):

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "<WABA_ID>",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": { "display_phone_number": "...", "phone_number_id": "..." },
        "contacts": [{ "profile": { "name": "Sheena Nelson" }, "wa_id": "16505551234" }],
        "messages": [{
          "from": "16505551234",
          "id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQzQTRBNjU5OUFFRTAzODEwMTQ0RgA=",
          "timestamp": "1749416383",
          "type": "text",
          "text": { "body": "Does it come in another color?" }
        }]
      },
      "field": "messages"
    }]
  }]
}
```

Facts that matter for nidaro:

- Inbound messages are in `value.messages[]`; messages *nidaro sent* come back as `value.statuses[]` (`sent`/`delivered`/`read`/`failed`, plus a `pricing` object). Don't create records from statuses.
- `messages[].id` (`wamid.…`) is the globally unique message ID — the natural idempotency key and `external_id`.
- `contacts[].wa_id` is the WhatsApp user ID, "may not always match" the typed phone number ([text reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text)). See §4 for the 2026 BSUID change.
- **Replies/quotes**: when a user replies quoting another message, the message carries `context: { from, id }` where `id` is the quoted message's `wamid` — this lets nidaro join a reply to message content it already stored. Forwarded messages carry `context.forwarded: true` (or `frequently_forwarded: true` for >5 hops) but no origin ID ([text reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text)).
- **Edits and revokes** arrive as separate messages of `type: "edit"` (original editable within 15 minutes) and `type: "revoke"` (within two days), each referencing `original_message_id` ([webhook references](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users), Edit/Revoke sections).
- Interactive replies (taps on nidaro's buttons/lists) arrive as `type: "interactive"` with the chosen button/list ID in the payload, so confirmation UX can be closed deterministically.
- Unsupported content (calls, disappearing messages, view-once, live location) arrives as `type: "unsupported"` with an error object — record but don't interpret.

### 1.4 Sending messages

All sends go to `POST /<WHATSAPP_BUSINESS_PHONE_NUMBER_ID>/messages` with `Authorization: Bearer <token>` ([service messages / sending](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages)):

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+16505551234",
  "type": "text",
  "text": { "preview_url": true, "body": "..." }
}
```

- A `200` response only means the API **accepted** the message (it returns `contacts[].wa_id` and `messages[].id`); delivery is confirmed via status webhooks. Delivery order of a message burst is not guaranteed — wait for `delivered` between ordered sends ([sending doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages)).
- **24-hour customer service window (CSW)**: every user message opens/resets a 24h timer. While open, nidaro may send **service messages** — free-form text, images, and the interactive types (reply buttons with up to 3 options, list messages with up to 10 rows, Flows, CTA-URL buttons) — without pre-approval. After it closes, only pre-approved **template messages** (marketing/utility/authentication) may be sent. The doc also re-states the consent rule: "you can only send messages to WhatsApp users who have opted in to receiving messages from you" ([sending doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages)).
- Useful UX primitives in the same doc: **contextual replies** (send a message quoting a prior message), **mark message as read**, and **typing indicators** — all relevant for making the assistant feel responsive while it processes.
- Include the `+` and country code on send; otherwise the business number's country code is prepended and messages can misdeliver ([sending doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages)).
- Undelivered messages retry until a TTL (default 30 days; auth templates 10 minutes) and are then dropped ([sending doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages)).

### 1.5 Current pricing (2025–2026)

Per-message pricing replaced conversation-based pricing on **July 1, 2025**; the old model is deprecated ([pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)):

- Meta charges only for **delivered template messages**, by category (marketing/utility/authentication) × recipient country code. Rate cards are published as CSVs on the [pricing page](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing) and refreshed up to quarterly (pricing-calendar rules: 1 month notice for rate changes, 3 for add-ons, 6 for model changes).
- **Non-template (service) messages in an open CSW are free today**, but only until **Oct 1, 2026**: from that date service messages are charged per message at market rates "the same as the rates for utility and authentication messages" (the page's worked example uses Brazil's $0.0068/message), and utility templates *inside* the CSW become chargeable again ([non-template pricing updates](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages)).
- Utility templates in the CSW are free until then; messages inside a **72-hour free entry point window** (Click-to-WhatsApp ads / FB page CTA) are free ([pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)).
- **Volume tiers** lower utility/auth rates for high monthly volumes at portfolio level — irrelevant at household scale.
- Billing events surface in status webhooks via `pricing: { billable, pricing_model: "PMP", category }` ([pricing → webhooks](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)).

**AI-provider clause (load-bearing for nidaro).** WhatsApp's Business Solution Terms were updated **Jan 15, 2026** to define "AI Providers" — "Providers and developers of artificial intelligence or machine learning technologies, such as large language models, generative artificial intelligence platforms, general-purpose artificial intelligence assistants" ([AI-provider pricing policy](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers), [Business Solution Terms](https://www.whatsapp.com/legal/business-solution-terms/)). The terms state AI Providers "are only permitted to offer general-purpose AI assistants on the WhatsApp Business Platform where Meta is legally required to permit this use case" (i.e., DMA-style jurisdictions), and Meta charges AI Providers per non-template message in those markets (Brazil from Mar 11 2026; an EU country list was charged Mar 11–May 12 2026, then exempted per the May 12, 2026 update; Italy Feb 16–May 12 2026). Status webhooks tag these messages `pricing.category: "general_purpose_ai"`. A household assistant whose surface is a fixed set of typed domain tools (calendar/tasks/commitments/family/memory) is arguably a domain-specific business assistant, not a "general-purpose AI assistant" — but this is a classification judgment on nidaro's product shape, not a technical question. Flag it for a human read of the ToS before launch; keeping the WhatsApp surface strictly scoped to nidaro's existing tools is the safest posture.

### 1.6 Group messaging: the hard constraint

Three independent sources agree:

1. **Groups API** ([groups](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups), [group messaging](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/groups-messaging)): a business can *create* groups programmatically and users join via invite links the business sends. Eligibility: **Official Business Account (OBA) only**. Quick facts: max **8 participants**, max 10,000 groups per number, **1 Cloud API business per group**, supported types text/media/templates, **no interactive messages**, no edit/delete. Sending uses `recipient_type: "group"` with a group ID; inbound group messages arrive on the `messages` webhook with `group_id` and `from` = participant phone number.
2. **Coexistence feature table** (Business-app numbers onboarded to Cloud API): "Group chats — Not supported. Group chats will not be synchronized" ([onboarding WhatsApp Business app users](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)). A Cloud API number cannot participate in ordinary, user-created groups.
3. **OBA gating** ([official business accounts](https://developers.facebook.com/documentation/business-messaging/whatsapp/official-business-accounts)): OBA requires ≥30 days on the platform, business verification of the portfolio, two-step verification, display-name approval, and Messaging-Policy compliance; "We do not grant OBA status to business employees, test accounts, and WhatsApp Business app phone numbers." A household deployment is unlikely to qualify and would be a strained reading of "business".

**Consequence for requirement 1:** a trigger word in a *DM to the nidaro number* works today, end to end. A trigger word in an *existing family group* does not: nidaro's number cannot be added to user-created groups, and Groups-API groups are business-created, OBA-gated, 8-participant rooms — not the family's existing chat. If group listening is a hard requirement, the official API cannot deliver it in 2026; the only working implementations are unofficial bridges (§3), which put the family's number at risk of a permanent ban.

## 2. The message-history constraint and legitimate mitigation patterns

### 2.1 What the API does and does not give you

- Standard Cloud API: messages exist for nidaro only from the moment they arrive on the webhook. There is no endpoint to fetch past conversations; the webhooks doc says so directly ("You will not be able to query historical webhook event notification data") ([getting started](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/)).
- The single exception is **coexistence**: onboarding a number that already runs the WhatsApp Business *app*, where the app user is offered chat-history sharing. A one-time `POST /<phone_number_id>/smb_app_data {"sync_type":"history"}` triggers a series of `history` webhooks covering **the last 180 days** in three phases (day 0–1, 1–90, 90–180), chunked and re-orderable via `chunk_order`; media contents are included only for the last 14 days (elsewhere a `media_placeholder`); **group chats are excluded**; the user can decline; the sync must be initiated within 24 hours of onboarding and can never be repeated without offboarding ([onboarding WhatsApp Business app users](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)). The catch: this flow is only available to **Solution Partners / Tech Providers** doing Embedded Signup — Meta-reviewed business programs, not something a personal deployment realistically obtains.
- Practical meaning: "track conversations for agreed things" is **forward-looking only**. Whatever is agreed in WhatsApp before the number is connected, or in groups nidaro isn't part of, is invisible to the official API.

### 2.2 Mitigation patterns (all official-API-compatible)

1. **Trigger-word capture (requirement 1, works as specified).** Any DM beginning with the configurable trigger is routed to the assistant; everything else from opted-in members is recorded for the passive pipeline. This is deterministic prefix/word matching in nidaro code; the LLM only interprets the remainder.
2. **Reply/quote joins.** When a user *replies* to any message (their own or a family member's) inside the DM thread, the webhook's `context.id` names the quoted `wamid`. nidaro stores every observed message with its `wamid`, so "@nidaro remember what Mara said" + a quote resolves to exact stored text deterministically. "Reply to this to confirm" flows become first-class.
3. **Forwarding into the DM.** Users can forward any message (including from group chats) to the nidaro number; the webhook flags it with `context.forwarded: true` ([text reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text)). This is the official answer to "capture that group agreement": a member forwards it and nidaro has the full body.
4. **Interactive confirmation of captured todos.** Reply buttons (≤3) and list messages are service messages available inside the CSW ([sending doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages)). The passive pipeline should *propose* a commitment ("I heard 'Mara takes the car Thursday' — track it?") with Track/Ignore buttons; the tap arrives as an `interactive` webhook and only then does nidaro write to the commitments domain. This bounds hallucination damage and gives non-initiating members a visible consent moment.
5. **Scheduled extraction over recorded DMs.** A periodic Taskiq job runs semantic interpretation over recent unprocessed messages of opted-in members, emitting pending captures (see §5). Deterministic code decides *which* messages to consider and *whether* a capture persists; the LLM only classifies/extracts.
6. **Coexistence, if ever available.** If nidaro the product ever becomes a Tech Provider, the 180-day history sync gives a legitimate bootstrap corpus for DMs (never groups) ([onboarding doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)).

## 3. Alternatives and tradeoffs

### 3.1 BSPs vs direct Cloud API

A BSP resells the same official platform; the deltas are price and onboarding ergonomics.

- **Twilio WhatsApp**: Twilio's own pricing page lists a **$0.005/message handling fee (inbound or outbound) plus Meta's fees passed through**, and a $0.001 failed-message processing fee ([Twilio WhatsApp pricing](https://www.twilio.com/en-us/whatsapp/pricing)). At a household's volumes the fee is trivial, but Twilio adds a second vendor, second webhook format, and its own number-registration flow.
- **360dialog**: plans **from €49/$59 per number per month with no markup on Meta fees** ([360dialog pricing](https://360dialog.com/pricing), [developer page](https://360dialog.com/whatsapp-api)). Makes sense for agencies managing many client numbers; pointless overhead for one household number.
- **Direct Cloud API** (recommended): pay only Meta's rates (at household volume: effectively the Oct-2026 service-message charge plus optional utility templates), one integration surface, and the webhook/payload shapes documented in §1 are *the* shapes nidaro codes against — no BSP dialect to unlearn. Cost of directness: creating a Meta app, business verification for production tiers, and managing system-user tokens yourself.

### 3.2 Unofficial bridges

- **whatsapp-web.js** drives the real WhatsApp Web client through Puppeteer ("uses Puppeteer to access WhatsApp Web's internal functions") ([README](https://github.com/pedroslopez/whatsapp-web.js)). Full feature surface including ordinary groups, but it is browser automation of a consumer client.
- **Baileys** is a reverse-engineered WebSocket implementation of the WhatsApp multi-device protocol; its README disclaims any WhatsApp affiliation, states the maintainers "do not in any way condone the use of this application in practices that violate the Terms of Service", and discourages "stalkerware, bulk or automated messaging usage". The original repository "had to be removed by the original author" — circumstantial evidence of platform pressure ([README](https://github.com/WhiskeySockets/Baileys)).
- **Evolution API** is a self-hosted REST wrapper offering "both the Baileys-based WhatsApp Web API and the official WhatsApp Cloud API" ([README](https://github.com/EvolutionAPI/evolution-api)). Note it has an official-API mode — if you want Evolution's operational shell without ToS risk, use that mode.

**Why ToS risk is concrete, not hypothetical.** WhatsApp's Terms of Service acceptable-use clause forbids accessing the service "directly, indirectly, through automated or other means ... in impermissible or unauthorized manners", including gaining "unauthorized access to our Services or systems", collecting "information of or about our users in any impermissible or unauthorized manner", and creating "software or APIs that function substantially the same as our Services" ([WhatsApp ToS](https://www.whatsapp.com/legal/terms-of-service-eea/revisions/20180424); current edition at [whatsapp.com/legal/terms-of-service](https://www.whatsapp.com/legal/terms-of-service)). Baileys and whatsapp-web.js are precisely unauthorized access and reimplementation. Enforcement is account bans, applied to the number running the bridge — for nidaro that number is the family's; a permanent ban means re-onboarding every household member on a new number. It also forfeits everything official: signed webhooks, delivery statuses, templates, the 24h window semantics. Verdict: acceptable only as a throwaway experiment on a sacrificial number; not for the product.

### 3.3 WhatsApp Business app vs API vs multi-device

- The **WhatsApp Business app** is a client for humans: it has groups, broadcast lists, catalogs, and up to four linked companion devices, but no programmatic API. The **Business Platform (Cloud API)** is the automatable surface: webhooks, templates, 24h window — and no ordinary groups ([onboarding doc feature table](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)).
- **Coexistence** runs both on one number: the family keeps using the app while the API mirrors traffic. Constraints if nidaro ever supports it: fixed 20 msg/s throughput, companion devices must be re-linked after onboarding, messages sent from unsupported companion devices don't produce webhooks, disappearing messages and view-once get disabled ([onboarding doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)). Consumer (non-Business) WhatsApp numbers cannot be onboarded to the API at all.

### 3.4 chrome-agent + real Chrome as the bridge runtime (chosen mechanism)

[chrome-agent](https://github.com/captivus/chrome-agent) is a Python CLI/library (MIT; single runtime dependency `websockets`; async Python API `CDPClient`) that drives a real system-installed Chrome over the Chrome DevTools Protocol, with instance lifecycle management (`launch`/`status`/`attach`/`stop`/`cleanup`) tracked in a registry ([README](https://github.com/captivus/chrome-agent)). Unlike whatsapp-web.js or Evolution API it needs no Node runtime and no second service: the WhatsApp observer is a long-lived asyncio task inside nidaro's monolith — one library dependency, not a microservice. It drives a genuine Chrome without patching the JS environment (`navigator.webdriver` stays native; the README documents verification against bot.sannysoft.com and CreepJS), so the browser presents a consumer-client fingerprint rather than a known automation one. It is pre-1.0 (v0.5.8, Aug 2026) — pin the version.

**Load-bearing constraint: frame sniffing does not work.** WhatsApp Web's WebSocket traffic is end-to-end encrypted at the protocol layer; the page's own JavaScript decrypts it. CDP's `Network.webSocketFrameReceived` therefore yields ciphertext, not messages (this is why whatsapp-web.js hooks page internals instead of the network). Observation must happen inside the page:

1. **Inject a shim once** with `Page.addScriptToEvaluateOnNewDocument` (survives navigations). Two strategies: a `MutationObserver` over the chat DOM (simple, breaks on UI redesigns) or hooking the web client's internal module store — the whatsapp-web.js approach — which yields structured data (message ids, sender, type, reactions, edits) but breaks when WhatsApp changes its module graph. Own the shim either way; keep it minimal.
2. **Ship events out** via `Runtime.addBinding`: the shim calls the binding with a JSON payload per observed message; Python receives `Runtime.bindingCalled` events through chrome-agent's attach stream or `CDPClient`. This is chrome-agent's documented binding-bridge pattern for full interaction observation ([collaboration guide](https://github.com/captivus/chrome-agent/blob/main/docs/collaboration-guide.md), [event-driven observation](https://github.com/captivus/chrome-agent/blob/main/docs/event-driven-without-monitor.md)).

Sketch — same connector seam as §5, bridge quarantined in one producer:

```text
asyncio observer task (jobs worker)
  └─ CDPClient → real Chrome, web.whatsapp.com (QR-paired once, persistent profile dir)
       └─ in-page shim (addScriptToEvaluateOnNewDocument)
            └─ Runtime.addBinding → bindingCalled per new message
                 └─ staging table → WhatsAppConnector.sync → ExternalRecords
```

The official webhook path (§5.1) and the observer feed the same staging → connector pipeline; the observer only adds records (tagged `source: "web_bridge"`, group messages included). Sends, trigger-word actions, and LLM interpretation stay on the official Cloud API number (§5.4, §5.6) — the bridge is a dumb listener.

**ToS posture unchanged.** chrome-agent is a mechanism, not a legal carve-out: an automated session reading messages is still "unauthorized access ... through automated means" under the consumer ToS cited above. Risk bounding: sacrificial number (never a family member's), read-only v1, headed Chrome on the household server, low message volume. The Jan 2026 AI-provider clause is Business-Solution-Terms surface; keeping interpretation on the official-API side keeps the consumer-session exposure to passive reading.

**PoC results (2026-08-29, linked session on a live account, Chrome/Chromium 151 + chrome-agent 0.5.8):**

1. **Binding bridge works.** A `MutationObserver` shim injected via `Page.addScriptToEvaluateOnNewDocument` + `Runtime.addBinding("__nidaro")` delivered `Runtime.bindingCalled` events into a Python asyncio callback (chrome-agent's `CDPClient.send`/`CDPClient.on`) within ~1s of a real message arriving. The page→Python pipe is proven end to end.
2. **Frame encryption confirmed.** `Network.webSocketFrameReceived` on the live session shows only `opcode: 2` binary frames carrying base64 ciphertext — no plaintext. Raw frame sniffing is ruled out; in-page observation is required, as predicted. Real gateway captured: `wss://web.whatsapp.com/ws/chat` with a `wss://web.whatsapp.com:5222/ws/chat` fallback (the `wN.web.whatsapp.com` hosts from older write-ups don't resolve).
3. **Profile does NOT survive chrome-agent's stop/relaunch.** A linked session was logged out after `chrome-agent stop` + `launch` (registry cleans instance session dirs). Deployment consequence: production runs its own Chromium with a persistent `--user-data-dir` (systemd unit or compose volume), and the observer connects `CDPClient(ws_url=get_ws_url(port=<cdp port>))` directly to it. chrome-agent's launch/registry is a dev-time convenience only.
4. **Headless UA gets gated; headed-in-Xvfb works.** A headless launch is blocked by WhatsApp's browser check ("WhatsApp works with Google Chrome 100+") based on the `HeadlessChrome` UA; headed Chromium under Xvfb with chrome-agent's `--fingerprint` UA profile (spoofed via launch flags, no JS injection) loads the full client. No QR-expiry problems from the Xvfb round trip.
5. Group visibility confirmed in the linked session (existing family groups visible in the chat list). Still open: shim strategy bake-off (DOM `MutationObserver` vs module-store hook) for structured message data (wamid, sender, type), and QR re-pair frequency over days of runtime.

## 4. Identity model and consent

- **Identifiers today.** Inbound webhooks carry `contacts[].wa_id` — the WhatsApp user ID, nominally the phone number but "may not always match" user input ([text reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text)). Map `wa_id → household member` at opt-in time (§5 binding flow), not by guessing from contacts.
- **Identifiers 2026 (BSUID/usernames).** Meta is rolling out user usernames during 2026 and a new identifier, the **business-scoped user ID (BSUID)**, which "will be included in any webhooks that would normally include their phone number" as `user_id`. Once a user adopts a username, **their phone number is omitted from webhooks** unless nidaro interacted with that number in the last 30 days or the number is in Meta's hosted **contact book**; a `REQUEST_CONTACT_INFO` button (interactive message, from July 2026) makes a user share their number explicitly ([business-scoped user IDs](https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids)). Design consequence: key the member mapping on `user_id` (BSUID) with `wa_id` as a display/secondary field, keep the 30-day interaction cadence naturally satisfied by household use, and support the `REQUEST_CONTACT_INFO` button in the binding flow. BSUIDs are portfolio-scoped, so they're stable for nidaro's single portfolio.
- **Consent for proactive messaging.** Businesses "are required to obtain opt-in before messaging people on WhatsApp" (WhatsApp Business Messaging Policy, Nov 2024 update); opt-in can be general and need not name WhatsApp specifically, but must comply with local law ([getting opt-in](https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in), [Business Messaging Policy](https://business.whatsapp.com/policy)). Replies within the CSW are uncontroversial (the user just messaged); *proactive* nudges (morning reminders) require template sends and therefore explicit opt-in.
- **Consent for passive tracking (the GDPR-flavored part).** The passive pipeline processes messages written by people who never installed anything: a partner's offhand "I'll fix the tap Saturday" becomes a tracked commitment. Fairness constraints nidaro should encode: (1) per-member opt-in at binding time — recording/extraction runs only for members who accepted; (2) nothing from non-members or groups is ever extracted (moot on Cloud API for groups, but hold the line in code); (3) captures stay *pending* until a human confirms via button or explicit command — the confirmation message is visible to the whole DM thread; (4) raw webhook payloads are staging data — after ExternalRecord/extraction, purge or truncate bodies per household retention setting; (5) erasure of a member (mapping + stored messages + derived commitments) must be one service call. Message content of EU residents transits Meta's infrastructure regardless; nidaro's obligation is to minimize and to be able to answer "what do you know about me" from its own tables.

## 5. Plugin design for nidaro

Everything below stays inside `route/tool/worker -> service -> repository -> database`. Connectors still only produce `ExternalRecord`s; domain writes go through `ApplicationServices`.

### 5.1 Component map

```
Meta webhook
  -> web/routes/whatsapp.py        GET handshake, POST verify+ack (ms)
     -> Taskiq task whatsapp_ingest(payload)          (jobs/tasks.py)
        -> WhatsAppIngestService                      (service)
           - signature already verified at the route
           - dedupe on wamid (repository lookup)
           - persist raw event  (WhatsAppEventRepository -> staging table)
           - deterministic: member binding status, trigger match
        -> [trigger message] AssistantRuntime.run(household_id, text, conversation_id)
        -> [confirmation taps] CommitmentService.record(RecordCommitmentRequest)
  -> connector sync (Taskiq connector_sync / scheduler)
        WhatsAppConnector.sync(context, cursor)       (connectors/whatsapp/…)
           drains staging -> ExternalRecord list, next_cursor = high-water event id
  -> WhatsAppSenderService                            (service)
     POST /{phone_number_id}/messages via httpx; CSW check; interactive buttons
```

### 5.2 Webhook route (contract level)

```python
# web/routes/whatsapp.py
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])

@router.get("")  # verification handshake
async def verify(hub_mode: str, hub_challenge: str, hub_verify_token: str):
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403)

@router.post("")  # event notifications
async def events(request: Request):
    body = await request.body()  # raw bytes: signature is computed over these
    if not valid_signature(body, request.headers.get("x-hub-signature-256", ""),
                           settings.whatsapp_app_secret):
        raise HTTPException(403)
    await whatsapp_ingest.kiq(orjson.loads(body))   # enqueue, ack immediately
    return Response(status_code=200)

def valid_signature(body: bytes, header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)
```

Details that matter: read the **raw body** (not a parsed model) for the HMAC; ack `200` before any parsing (Meta retries non-acks for 36h); the Taskiq task does the dedupe (`wamid` unique index) so retries and Meta's batching (≤1000 updates per POST) collapse safely.

### 5.3 Ingest, staging, and the connector seam

`Connector.sync` is pull-shaped; webhooks are push. The clean mapping: the ingest task persists every message event to a small staging table (`whatsapp_events`: unique `wamid`, `payload JSONB`, `observed_at`, `processed_at`), and the connector drains staging on schedule.

```python
class WhatsAppConnector:
    name = "whatsapp"

    def __init__(self, events: WhatsAppEventRepository) -> None: ...

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult:
        rows = await self.events.unprocessed(after_id=cursor, household_id=context.household_id)
        records = [ExternalRecord(
            connector="whatsapp",
            external_type="message",                      # payload.type carries text/image/interactive/...
            external_id=row.wamid,                        # globally unique, idempotent
            payload={                                     # minimal, normalized
                "type": row.type, "body": row.body, "from_user_id": row.user_id,
                "wa_id": row.wa_id, "group_id": row.group_id,
                "context_id": row.context_id,             # quoted wamid, for reply joins
                "forwarded": row.forwarded, "wamid": row.wamid,
            },
            content_hash=sha256(f"{row.wamid}:{row.body}".encode()).hexdigest(),
            observed_at=row.observed_at,
        ) for row in rows]
        return SyncResult(records=records, next_cursor=rows[-1].id if rows else cursor)
```

Registering it in `ApplicationServices.build`'s `ConnectorRegistry` costs one line. `edits`/`revokes` are staged and emitted as their own `ExternalRecord`s (`external_type="message.edit"` / `"message.revoked"` with the original `wamid` in the payload) so downstream interpreters see corrections without mutating history. Statuses (`sent`/`delivered`/`read`) update a small outbound-message table for CSW bookkeeping and are never emitted as records.

### 5.4 Trigger parsing (deterministic) and assistant handoff

```python
def strip_trigger(body: str, trigger: str) -> str | None:
    text = body.lstrip()
    return text[len(trigger):].lstrip(" :,") if text.lower().startswith(trigger.lower()) else None
```

- `trigger` from `Settings` (e.g. `NIDARO_WHATSAPP_TRIGGER="@nidaro"`); no model calls in this path.
- If the message has `context.id` and that `wamid` is stored, prepend the quoted body to the prompt: deterministic context assembly.
- Hand off with the existing runtime: `conversation_id, reply = await runtime.run(household_id, prompt)`; the typed tools (`build_commitment_tools`, `build_task_tools`, …) already enforce that state changes go through services.
- Send `reply` through `WhatsAppSenderService` as a plain service message (always inside the CSW the trigger message just opened). Mark the inbound message read and show the typing indicator first ([sending doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages)).

### 5.5 Capturing "agreed things" into commitments

1. **Explicit path**: "@nidaro remind Mara to take the car Thursday" — the assistant's commitment tool builds a `RecordCommitmentRequest`; `CommitmentService.record` persists; the reply quotes the request message (`contextual reply`) for auditability.
2. **Passive path**: a scheduled Taskiq task (same cron mechanism as `heartbeat`) selects recent unextracted messages of **opted-in** members, asks the LLM only "does this message state an agreement/task? return structured draft or null", and on a draft sends an interactive reply-button message ("Track 'Mara takes the car Thursday'? [Track] [Ignore]"). The tap returns as an `interactive` webhook; only then does the task call `CommitmentService.record`. Pending captures live in a small table keyed by the button message's `wamid` so the tap resolves deterministically.
3. Both paths converge on `CommitmentService` — the connector never writes domain tables.

### 5.6 Identity binding and opt-in

- Unmapped inbound DM → deterministic onboarding reply: "Reply LINK <household code> to connect." Code generated by `HouseholdService`; on success store `(household_id, member_id, user_id, wa_id, consent_at)` — one row per member, keyed on BSUID `user_id` (§4). Consent timestamp is the passive-tracking gate.
- Include a `REQUEST_CONTACT_INFO` button in the binding flow so the phone number survives username adoption ([BSUID doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids)).
- `WhatsAppSenderService` resolves recipients as `user_id` if known else `to` phone; proactive template nudges check the consent row first.

### 5.7 Config additions (no secrets in source)

`whatsapp_enabled`, `whatsapp_app_secret`, `whatsapp_verify_token`, `whatsapp_access_token` (system-user token; rotate via env), `whatsapp_phone_number_id`, `whatsapp_graph_version` (pin, e.g. `v26.0`), `whatsapp_trigger_word`. All via `Settings`/env, consistent with the existing `logfire_token` pattern.

## 6. Open questions, risks, pricing summary

**Open questions for a human**

1. AI-provider classification: does nidaro's WhatsApp surface make it an "AI Provider" under the Jan 15, 2026 Business Solution Terms? The docs restrict *general-purpose* AI assistants to jurisdictions where Meta is legally required to allow them ([ai-providers](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers), [ToS](https://www.whatsapp.com/legal/business-solution-terms/)). Keeping the surface domain-scoped (typed tools only) is the mitigation; a lawyer-level read is the decision.
2. Group requirement: **decided** — hybrid (§3.4): DM-first on the official API for actions, plus a read-only chrome-agent observer on a sacrificial number for groups. Remaining: run the PoC (profile persistence, shim stability) before building the connector.
3. Meta app ownership: whose Meta business account hosts the WABA (personal deployment vs agenterio), and who completes business verification for production messaging tiers.

**Risks**

- Oct 1, 2026: every nidaro reply becomes a charged service message; utility templates in-CSW too ([non-template pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages)). Tiny at household scale, but build the CSW/pricing accounting now (status webhook `pricing.category`).
- Webhook retries (36h) + batching (≤1000) make idempotent ingest non-optional; a bug that 500s repeatedly re-queues the same events.
- BSUID/usernames migration can strip phone numbers from webhooks for dormant members ([BSUID doc](https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids)); store `user_id` from day one.
- Rate cards and category rules change quarterly; treat the pricing CSVs as data, not constants.
- Groups-API shape (OBA, 8 participants) could evolve — recheck the [Groups page](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups) before writing any group code.

**Pricing summary (household scale, direct Cloud API)**

| Item | Cost |
| --- | --- |
| Receiving messages | Free |
| Replies (service messages) in 24h CSW | Free until Oct 1, 2026; then per-message at market utility/auth rates (e.g. $0.0068 in Brazil; see rate-card CSVs) |
| Utility templates (proactive reminders outside CSW) | Per delivered message by market; volume tiers exist |
| Marketing templates / auth templates | Not expected in this product |
| BSP markup (if Twilio/360dialog) | Twilio +$0.005/message; 360dialog €49/$59 per number/month |
| 180-day history bootstrap | Free, but requires Tech/Solution-Provider status (coexistence) |

## Sources

- Graph API webhooks — getting started (handshake, `X-Hub-Signature-256`, retries, batching, mTLS, no-history statement): https://developers.facebook.com/docs/graph-api/webhooks/getting-started/
- messages webhook reference (inbound/outbound payload structures): https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages
- text messages webhook reference (`wa_id` semantics, `context` for quotes/forwards): https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text
- Service messages / sending (`POST /{phone_number_id}/messages`, 24h CSW, interactive types, contextual replies, TTL, opt-in reminder): https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages
- Pricing on the WhatsApp Business Platform (per-message model, free windows, volume tiers, rate cards, pricing calendar): https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- Upcoming pricing updates (Meta Business Agent per-token Aug 1 2026; service + in-CSW utility charged Oct 1 2026): https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
- AI-provider pricing policy and ToS restriction (Jan 15 2026; `general_purpose_ai` category): https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers and https://www.whatsapp.com/legal/business-solution-terms/
- Groups API (OBA eligibility, 8-participant invite-only groups, supported types): https://developers.facebook.com/documentation/business-messaging/whatsapp/groups
- Group messaging reference (`recipient_type: "group"`, group webhook shapes): https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/groups-messaging
- Official Business Accounts (OBA eligibility criteria): https://developers.facebook.com/documentation/business-messaging/whatsapp/official-business-accounts
- Onboard WhatsApp Business app users / coexistence (180-day history sync, `smb_app_data`, edit/revoke webhooks, group chats unsupported, feature table, 20 mps): https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users
- Business-scoped user IDs and usernames (BSUID, phone-number omission rules, contact book, `REQUEST_CONTACT_INFO`): https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids
- Get opt-in for WhatsApp (mandatory opt-in, Nov 2024 policy update): https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in and https://business.whatsapp.com/policy
- About the WhatsApp Business Platform (surfaces, portfolio-based messaging limits): https://developers.facebook.com/documentation/business-messaging/whatsapp/about-the-platform
- WhatsApp Business Platform changelog: https://developers.facebook.com/documentation/business-messaging/whatsapp/changelog
- Twilio WhatsApp pricing ($0.005/message fee, Meta pass-through, failed-message fee): https://www.twilio.com/en-us/whatsapp/pricing
- 360dialog pricing (from €49/$59 per number/month, no Meta markup): https://360dialog.com/pricing and https://360dialog.com/whatsapp-api
- whatsapp-web.js (Puppeteer WhatsApp Web automation): https://github.com/pedroslopez/whatsapp-web.js
- Baileys (reverse-engineered multi-device WebSocket client; disclaimer; removed original repo): https://github.com/WhiskeySockets/Baileys
- Evolution API (self-hosted wrapper; Baileys and official Cloud API modes): https://github.com/EvolutionAPI/evolution-api
- WhatsApp Terms of Service, acceptable-use clause (no unauthorized automated access / collection / reimplementation): https://www.whatsapp.com/legal/terms-of-service-eea/revisions/20180424 (current edition: https://www.whatsapp.com/legal/terms-of-service)
- chrome-agent (CDP driver CLI/library; Python `CDPClient`; instance registry; fingerprint/no-JS-patching notes): https://github.com/captivus/chrome-agent
- chrome-agent, full interaction observation via the binding bridge: https://github.com/captivus/chrome-agent/blob/main/docs/collaboration-guide.md
- chrome-agent, event-driven page observation (attach + waiter pattern, verified against Chrome 150): https://github.com/captivus/chrome-agent/blob/main/docs/event-driven-without-monitor.md
