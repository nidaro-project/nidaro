# Škola OnLine (skolaonline.cz) — what can a passive gatherer see?

Researched 2026-08 against the vendor's own pages and contract documents (skolaonline.cz), the official
parent/student user manual (rev. 30. 10. 2023), both mobile-store listings, and the source of every
community client found on GitHub (19 repos matched `skolaonline`). Facts are current as of the dates on
the cited pages. Written for an engineer who knows nidaro but not the Czech school-IS landscape.
Confidence markers: **[docs]** = vendor/store/official manual, **[code]** = read in community tooling
source, **[single]** = one unverified source.

## Verdict

A passive, read-only gatherer for Škola OnLine is **plausible and partially mapped**: every route is
credential-bound (a parent's username + password), but the credential unlocks not only HTML but two
HTTP JSON APIs that community projects already drive without an official developer program — the web
app's `SOLWebApi` (HTTP Basic auth) and the mobile app's `solapi` (OAuth2 password grant,
`client_id=test_client`). There is **no official public API and no known vendor policy that permits or
forbids third-party clients**; the one public contract set (vendor ↔ school B2B terms) contains no
explicit anti-automation clause, and GDPR roles make the *school* — not the vendor — the data
controller a parent would answer to. Community tooling is real but small and partly stale: a Rust
crate set (timetable, grades, subjects, iCal export, last pushed 2023), an active Home-Assistant
homework→CalDAV scraper (2026), substitution-XML tooling, and assorted one-off scripts. Canteen data
is **not** in Škola OnLine itself — it lives in external catering systems (VIS, Anete) reached by
SSO. Compared to the sibling Bakaláři ecosystem, the Škola OnLine third-party scene is thin; expect
to write and maintain more of the connector yourself.

## 1. Product and vendor

- Škola OnLine (SOL) is a Czech web-based school information system (SIS) for nursery, primary,
  secondary and higher-secondary schools; users work in a browser, hosted by the vendor.
  **[docs]** (https://www.skolaonline.cz/, https://www.skolaonline.cz/smluvni-dokumentace/)
- Corporate chain, relevant because the ticket's "Software Solutions Olomouc" label is outdated:
  the product was built by **dm Software s.r.o.** (Olomouc), which also shipped the predecessor
  dm Software SIS (still documented as a separate legacy product line on skolaonline.cz);
  the 2023 parent manual is copyrighted by **ŠKOLA ONLINE a.s.** (Plzeň); since a 2024
  "Bakaláři a Škola Online spolupracují" announcement the product is run by **BAKALÁŘI software
  s.r.o.** (Příbram), which is the developer listed on both store listings and the contracting
  party in the current terms. **[docs]** for the store listings + contract pages,
  **[single]** for the corporate-history details (Facebook announcement post,
  https://www.facebook.com/bakalarisoftware/posts/2355524617819762/).
- Scale: the Android app alone has 500 000+ downloads; Bakaláři software claims its SIS family is
  used by ~88 % of Czech schools (vendor claim). **[docs]**
  (https://play.google.com/store/apps/details?id=cz.skolaonline.mobile&hl=cs,
  https://digikoalice.cz/organizace/bakalari-software/)

## 2. What a parent account can see

### 2.1 Web app ("Žákovská" / elektronická žákovská knížka)

Parents log into the same web app as students, with role `zákonný zástupce` (legal guardian). A
guardian can access **multiple children under one account** and switch between them. **[docs]**
(manual §2, §6.1.1)

The home page ("Vstupní stránka – rychlý přehled") shows eight dashboard panels, each linking to a
detail view **[docs]** (manual §6.1.4):

| Panel (Czech) | Content |
|---|---|
| Informační panel | school-wide announcements |
| Kalendář | today's + tomorrow's timetable, incl. icons for newly entered grades (H), lesson notes (P), teaching resources (V) |
| Nepřečtené zprávy | unread internal messages |
| Hodnocení | latest grades (colour-coded 1 green … 5 red) |
| Neodevzdané domácí úkoly | unsubmitted homework |
| Docházka – zameškané hodiny | missed lessons |
| Školní akce | school events |
| Výchovná opatření, hodnocení chování | behavioural measures / conduct grades |

Detail modules reachable from the web app (manual chapter in brackets) **[docs]**:

- **Docházka (attendance)** — arrivals/departures, calendar view, per-lesson absence detail,
  absence per subject, percentage absence (manual §6.2)
- **Hodnocení (grades)** — grade list incl. weight and date, continuous/verbal assessment
  (`průběžné hodnocení`, `slovní hodnocení`), conduct, `index` with exam terms for SŠ/VŠ (§6.2.1.5)
- **Elektronická omluvenka (absence excuse)** — the parent *submits* excuses here (§6.3)
- **Domácí úkoly (homework)** — assigned homework incl. electronic submission and file attachments
  (§7.1.1)
- **Výukové zdroje a testy** — teaching resources linked to lessons; online tests incl. taking them
  (§7.1.2)
- **Informace k výuce** — teacher list, subject info, covered curriculum (`probrané učivo`),
  teachers' timetables (§7.1.3)
- **Zprávy (messages)** — internal messaging: received/sent, replies, subscribed notification
  digests, sending excuse notes as messages (§7.1.4)
- **Stravovací systém (canteen)** — only a *link/SSO* into an external catering system for ordering
  and cancelling meals; "fully in the school's competence". SOL itself has no canteen module; the
  vendor lists integrations with catering systems of VIS and Anete (§8.1; module overview
  "Propojení s externími systémy")
- **Školní družina/klub** — after-school club records (§8.2)
- **Přehled osobních údajů** — the personal data the school holds on the child (§8.3)
- **Zápis na školní akce** — sign-up for school events (clubs, school trips) (§8.4)
- **GDPR souhlasy** — approving data-processing consents (§8.5)
- **Knihovna** — school library, book reservations (§8.6)
- **Absolventské práce** — thesis sign-up (VŠ) (§8.7)
- **Přihláška do 1. ročníku ZŠ** — first-grade application form (chapter 4)

Substitution (`suplování`) is **not a separate parent page in the web manual** — it arrives merged
into the timetable/calendar ("ihned po přihlášení … rozvrh včetně všech mimořádných změn
vyvolaných suplováním a školními akcemi", module overview) and as an explicit calendar layer in the
mobile app. Schools can additionally publish timetables and substitution on **public pages without
login** ("Veřejné stránky školy" module, school's choice). **[docs]**
(https://www.skolaonline.cz/prehled-modulu/)

Feature availability **varies by the school's package tier** (Základ/Standard/Premium): e.g. for
primary schools, Domácí úkoly, Zápisy na školní akce, GDPR, Knihovna and external integrations are
**Premium-only**, while Rozvrh/suplování, Komunikace and Veřejné stránky are Standard. A gatherer
must treat homework, events, GDPR consents as possibly absent per school. **[docs]**
(VOP §VI, https://www.skolaonline.cz/wp-content/uploads/pdf/sol-vseobecne-obchodni-podminky-2023-10-01.pdf)

### 2.2 Mobile app (official)

One official app, "Škola Online", for teachers + students + guardians — Android
(`cz.skolaonline.mobile`, 500k+ downloads, updated 14. 8. 2026) and iOS (`id962406446`, v3.14.2,
free, #4 in Education chart). Developer on both stores: BAKALÁŘI software s.r.o. Built in **Flutter**
by Czech agency netglade. **[docs]** (Play listing, App Store listing) + **[single]** for Flutter
(https://www.netglade.cz/en/reference/skolaonline)

Parent/guardian features per the store listings **[docs]**: notifications about new grades,
homework, conduct; calendar with timetable + substitution + school events; grade lists per subject
with detail; continuous assessment (`průběžné hodnocení`) incl. mass signing; conduct grades and
signing; year report card (`vysvědčení v ročníku`); homework; absence excuses (`omluvenky`);
**switching between children**; account switching; new **Payments module** (school fees/payments,
added May 2025); targeted third-party informational messages (open-day ads for 9th-graders) shown
only with GDPR consent. Signing of grades reportedly still requires the web app per a store review —
**[single]**, unverified.

## 3. Access mechanics

### 3.1 Account creation and login

- The school issues the parent a **one-time PIN**; the parent self-registers at skolaonline.cz with
  name + PIN + captcha and chooses username + password. Password recovery is by e-mail; locked
  accounts are reset by the class teacher or school administrator. Username is case-insensitive,
  password case-sensitive. Some schools offer Microsoft (Windows ID) login. **[docs]**
  (manual §2, §6.1.1–6.1.1.2)
- No MFA is documented anywhere in the manual. **[docs]** (absence of it in §6.1/§9)

### 3.2 Three known access surfaces (all credential-bound)

1. **ASP.NET web app** — login form POSTs to `https://aplikace.skolaonline.cz/SOL/Prihlaseni.aspx`
   (no ViewState token needed for login), then session cookies; `ASP.NET_SessionId` expires in ~20
   minutes but other auth cookies survive; page codes include `App/Spolecne/KZZ010_RychlyPrehled`
   (dashboard), `App/Ukoly/KUK005_UkolyStudenta` (homework list), `App/Ukoly/KUK006_OdevzdaniUkolu`
   (homework detail, `?UkolID=`); multi-child selection via an ASP.NET postback dropdown
   (`ctl00$listOfChildrenPart$listOfChildren$DDLChildren`, value `ORG_ID#OSOBA_ID`). **[code]**
   (hovorkap/sol-sync `src/skolaonline.py`, https://github.com/hovorkap/sol-sync)
2. **`SOLWebApi`** — `https://aplikace.skolaonline.cz/SOLWebApi/api/v1`, JSON, **HTTP Basic auth**
   (username:password). Endpoints used by the Rust client: `/AuthorizationStatus`, `/UzivatelInfo/{username}`,
   `/RozvrhoveUdalosti/{from}/{to}` (timetable events incl. substitution flags), `/VypisHodnoceniStudent`
   (grades), `/Predmety` (subjects), `/DruhyHodnoceni` (grade types). **[code]**
   (HonbraDev/skolaonline-rs `skolaonline/src/client.rs`, `abstractions.rs`,
   https://github.com/HonbraDev/skolaonline-rs — last pushed 2023-12-11, so treat as possibly
   stale against the current server)
3. **`solapi` (current mobile-app API)** — `https://aplikace.skolaonline.cz/solapi/api/`,
   OAuth2/IdentityServer-style token endpoint at `/solapi/api/connect/token` accepting **password
   grant** with `client_id=test_client`, `scope='sol_api offline_access profile openid'`, returning
   access + refresh tokens; refresh via `grant_type=refresh_token`. Bearer-authenticated endpoints:
   `/solapi/api/v1/user`, `/solapi/api/v1/timeTable?StudentId=…&SchoolYearId=…&DateFrom=…&DateTo=…`
   — the timetable payload contains per-lesson `hourType` with ids `SUPLOVANI`/`SUPLOVANA`
   (substituted / cancelled). **[code]** (ondrejnedoma/skolaonlinewidget `lib/login_service.dart`,
   `lib/access_token_service.dart`, `lib/timetable_service.dart`, `lib/user_info_service.dart`,
   https://github.com/ondrejnedoma/skolaonlinewidget, pushed 2026-01)

Neither API is documented by the vendor; both are known **only** through community
reverse-engineering. The widget repo's `client_id=test_client` strongly suggests an app-side
constant rather than a per-deployment secret, but nothing documents rate limits, quotas or
detection heuristics. **[code]**/**[single]**

### 3.3 What the community already built (complete inventory, GitHub search `skolaonline`, 2026-08)

| Repo | What it does | Route | State |
|---|---|---|---|
| HonbraDev/skolaonline-rs (9★) | Rust crates: client, user info, timetable, grades, subjects, grade types; timetable→iCal converter + CLI + "iCal-as-a-service" web wrapper; tz Europe/Prague | SOLWebApi (Basic) | dormant, 2023-12 **[code]** |
| hovorkap/sol-sync | Home-Assistant add-on: scrapes homework (list + detail), tracks completion state, syncs to CalDAV (iCloud Reminders/Nextcloud) | ASP.NET session scraping | **active 2026-05** **[code]** |
| spsehavirov/skolaonline-suplovani | Downloads substitution XML (student + teacher variants) — Selenium/headless and a no-browser multipart/form-POST re-implementation; converts to CSV/HTML/PDF/PNG for a hallway TV; includes a request-recorder script | web form POST / manual XML export | active **[code]** (README: "ŠO bohužel nenabízí API") |
| JakubAndrysek/skola-online-stahovani-znamek (6★) | Requests-session scraper printing the latest grades from the dashboard | ASP.NET session scraping | 2023 **[code]** |
| Cupomaz/skolaonline-sluzba | Weekly GitHub-Action: scrapes a teacher's duty (`služba`) from the calendar page, posts to Discord | scraping | active 2026-06 **[code]** |
| ondrejnedoma/skolaonlinewidget | Flutter home-screen widget: today's lessons, detects SUPLOVANI | solapi (Bearer) | 2026-01 **[code]** |
| others (jberanova, Tomas125CZ, Kredbic, Anax378, batuzekkuba, lukulla343 Stylus CSS, …) | fragments/forks/UI skins, no documented API surface | — | negligible **[code]** |

**Negative findings** (both are useful): no official public API, SDK, or developer program exists
— the vendor's own pages advertise none, and two community READMEs state its absence
(spsehavirov, JakubAndrysek). No known packaged "Škola OnLine library" on PyPI/npm beyond the
throwaway repos above; nobody has mapped the solapi surface beyond `user` + `timeTable` in public
code, so grades/absence/homework/messages endpoints of the *mobile* API are **unmapped** in public
tooling (they exist — the app uses them — but nobody has published them). **[docs]** + **[code]**

### 3.4 Anti-bot posture

The vendor's *marketing* site (www.skolaonline.cz) sits behind **Anubis** proof-of-work bot
protection (observed 2026-08-30 while researching this ticket). The application host
(aplikace.skolaonline.cz) cannot be tested without credentials — and was not tested, per this
ticket's ground rules. **[single]** (direct observation)

## 4. Terms-of-service / legal constraints

- The published **Všeobecné obchodní podmínky** (valid 1. 10. 2023) are a **B2B contract between
  BAKALÁŘI software s.r.o. and the school**; parents and students are not parties, so no clause
  addresses third-party readers directly. The full text contains no prohibition of automated access
  or scraping (searched for automat/robot/API/třetí osoba). **[docs]**
  (https://www.skolaonline.cz/wp-content/uploads/pdf/sol-vseobecne-obchodni-podminky-2023-10-01.pdf)
- The school-side obligations that come closest: the school must not disclose access credentials to
  unauthorised persons and must instruct users in safe credential handling (VOP §III.3), and must
  refrain from activities that could degrade SOL operation (§III.1). A gatherer that a parent
  *authorises* sits in a grey zone: permitted by nothing explicit, restricted by nothing explicit.
  **[docs]**
- **GDPR roles**: the *school* is the data controller (správce) and BAKALÁŘI software only the
  processor (zpracovatel, čl. 28 GDPR); the vendor disclaims responsibility for data leaked by
  persons acting under school-granted access. Data-subject requests and any permission questions
  therefore run against the school, not the vendor. **[docs]**
  ("Zásady ochrany osobních údajů a zabezpečení dat v SOL" v1.2,
  https://www.skolaonline.cz/wp-content/uploads/smlouva/…SOL_v1.2.html)
- The data at stake is **children's personal data** (grades, absence, behaviour, sometimes health
  and location-adjacent data), which raises the sensitivity of any third-party copy regardless of
  ToS; the mobile app additionally processes coarse location, identifiers and usage data for
  analytics and shows consent-gated third-party messages. **[docs]** (GDPR policy; App Store
  privacy labels)
- Vendor may place its own and third-party commercial messages in SOL (VOP §II.11) — the same
  channel the app uses for targeted open-day ads. A gatherer scraping dashboards will also capture
  these. **[docs]**

## 5. Summary table for the wayfinder chart

| Question | Answer |
|---|---|
| Plausible gatherer? | Yes, credential-bound; parent username+password unlocks everything a parent sees |
| Access-mechanics verdict | **Plausible-but-unmapped**: three surfaces known (ASP.NET scraping, SOLWebApi Basic auth, solapi OAuth2); only timetable/grades/subjects/homework covered by public code; mobile-API coverage of absence/messages/canteen unpublished |
| Official API? | None; no developer program, no public ToU for APIs |
| Community tooling | Small but real; one active 2026 scraper (sol-sync), one dormant Rust client set |
| Legal red flags | No anti-automation clause found; GDPR controller is the school; children's data sensitivity; credential-sharing clause binds the school |
| Gaps | solapi endpoint map, rate limits/detection, mobile-app traffic capture, canteen (external systems: VIS, Anete — separate integrations) |
