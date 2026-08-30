# Bakaláři: what a passive, read-only gatherer can see

Research for [school-1] (NIDAR-agzqrm). Researched 2026-08-30 against vendor pages
(bakalari.cz FAQ, module catalogue, Datový konektor page), the official App Store
listing of Bakaláři OnLine, a school-issued parent manual for the web app (PDF),
the community `bakalari-api` GitHub org (reverse-engineered docs of mobile API v1
and v3), PyPI clients, and Home Assistant integrations. No live school system was
logged into. The only live requests made during research were two unauthenticated
GETs on the vendor's public school-directory endpoint. Facts only, no design.

Confidence labels: **[official]** vendor or school documentation, **[community]**
multiple independent third-party implementations agree, **[single]** one
unverified source.

## Summary

A parent account in Bakaláři sees the whole elektronická žákovská knížka (electronic
grade book): grades (známky) with weights and confirmation state, timetable (rozvrh),
substitution (suplování), absence (absence) down to per-subject percentages, homework
(domácí úkoly) with attachments, Komens messages and the school/class noticeboard
(nástěnka), school events (akce), subjects with taught themes and teacher contacts,
term classification history, disciplinary measures, GDPR consents, class-fund
payments, and the child's personal records. All of this is readable through one JSON
interface, mobile API v3, the same one the official mobile app uses: one
username/password login yields a bearer token plus a refresh token, and every module
answers GETs with JSON. What a given account can read is spelled out by the API
itself: `/api/3/user` returns the school's per-account `EnabledModules` list with
fine-grained rights, so a passive gatherer can discover its own visibility at
runtime. There is no published vendor terms-of-service for this API; the vendor's
documented route for third parties is the paid Datový konektor, and community
maintainers treat the mobile API as unofficial but stable. The legal layer is GDPR:
the school is the controller, the credential belongs to one parent, and access is
observable by the account holder through the web app's login-history tool.

## 1. What Bakaláři is and where it runs

- Vendor: BAKALÁŘI software s.r.o. (Pribram, Czechia). Self-described as the most
  widely used school system in the Czech Republic, 3,500+ schools, in development
  since the early 1990s. [official](https://www.bakalari.cz/,
  https://www.bakalari.cz/Schools/Novelties?version=20/21&daysOfHistory=All&type=Novelty,%20FixedBug&typeOfModule=WEB)
- Server-side modules sold to schools: Evidence žáků (student and staff records,
  school registry, classification, report cards), Internetová žákovská knížka (the
  web app that parents and students use), Rozvrh (timetable generation),
  Suplování (substitution), Plán akcí (school event plan), Elektronická třídní
  kniha (electronic class register), plus admissions, library, and inventory.
  [official](https://bakalari.cz/Home/Modules)
- Deployment is per school. The FAQ states that the app in most cases runs "na
  serverech dané školy" (on the school's own servers), so connectivity problems are
  the school's server, not the vendor's. Some schools self-host under their own
  domain, classically under a `/bakaweb` path; others moved to the vendor cloud and
  use `https://<school>.bakalari.cz` addresses.
  [official](https://www.bakalari.cz/static/faq,
  https://www.zspostoloprty.cz/pristup-do-systemu-bakalari-zmena/d-1528,
  App Store listing: "http://www.naseskola.cz/bakaweb" example)
- Canteen (jídelna) is **not** a Bakaláři module. Schools run separate catering
  products and link them: the vendor newsletter promotes Strava.cz by partner VIS
  Plzeň with single-sign-on launch from the Bakaláři web app ("už nemusíte zadávat
  další heslo do stravovacího systému"); iCanteen is another third-party catering
  system schools deploy alongside. A Bakalá gatherer therefore sees no meal data;
  canteen data would need its own connector.
  [official](https://www.bakalari.cz/Schools/NewsDetail/92,
  https://zsplovarna.ji.cz/file.php?nid=19411&oid=8390854)

## 2. What a parent account can see

### 2.1 The web app's parent tabs

From a school-issued parent manual for the web app (SPŠPB Plzeň, 2024):

- Dashboard (Úvod): overview of new marks, messages, substitution, events.
- Osobní údaje (personal data): the records the school keeps about the child and
  the guardians. Parents only; students cannot open this module.
- Klasifikace: průběžná (current marks per subject, with weights shown per mark),
  pololetní (term marks and summaries for the whole study history, averages,
  excused/unexcused hours, report-card dates), výchovná opatření (praise, warnings,
  reprimands), opravné zkoušky (resit exams).
- Výuka: rozvrh hodin (timetable with per-lesson substitution changes, assigned
  homework, and absence colouring), suplování (substitution list), přehled
  předmětů (subjects with teachers), přehled výuky (topics taught, from the class
  register).
- Plán akcí (school events, filterable, can be limited to the child's events).
- Průběžná absence: current attendance, per-day overview, missed-lesson percentage
  per subject (highlighted from 20% at this school).
- Komens: messaging between parents, students, and teachers; excuse notes
  (omluvenky) for absence; read confirmations; nástěnka (noticeboard) with school
  and class boards.
- Nástroje: přehled přihlášení (login history with IP addresses), propojení účtů
  (sibling account linking under one login), password change, language settings.

[official](https://www.spspb.cz/wp-content/uploads/2024/09/bakalari_web_navod_pro_rodice.pdf)

### 2.2 The official mobile app

Bakaláři OnLine (Android `cz.bakalari.mobile`, iOS id1459368580), 2nd generation
official app for parents, students, and teachers:

- Shows marks, timetable and substitution, homework, absence, and Komens
  communication, "similarly as in the web application".
- Stays connected without daily re-login (persistent session), has an offline
  mode for timetable and substitution, supports a parent switching between
  multiple children across multiple schools, offers a timetable widget and push
  notifications for Komens, homework, and marks.
- Contains advertising: "informativní sdělení třetích stran" (targeted
  informational messages from third parties, e.g. open-house notices from nearby
  secondary schools), shown on the basis of a GDPR consent given at install.

[official](https://apps.apple.com/cz/app/bakal%C3%A1%C5%99i-online/id1459368580,
https://www.bakalari.cz/static/faq)

### 2.3 What the API reports as visible

`GET /api/3/user` returns the account type (`"UserType": "parents"`,
`"UserTypeText": "rodič"`) and an `EnabledModules` array with per-module rights. A
parent response documented by the community contains: Komens
(ShowReceivedMessages, ShowSentMessages, ShowNoticeBoardMessages, SendMessages,
ShowRatingDetails, SendAttachments), Absence (ShowAbsence, ShowAbsencePercentage),
Events, Marks (ShowMarks, ShowFinalMarks, PredictMarks), Timetable, Substitutions,
Subjects (ShowSubjects, ShowSubjectThemes), Homeworks, Gdpr (ShowOwnConsents,
ShowChildConsents, ShowCommissioners), Campaign (ShowCampaign). Rights gate the
data: absence percentages are only returned when the school grants
`ShowAbsencePercentage`. Documented extras beyond that list: Payments (class fund
endpoints), and AccessSystem (`/api/3/user/student-at-school`, right
`CanShowStudentPresentAtSchool`, requires the school to run the Přístupový systém
module). So a gatherer can enumerate its own visibility at runtime instead of
assuming it.

[community](https://github.com/bakalari-api/bakalari-api-v3/blob/master/moduly/user.md,
https://github.com/bakalari-api/bakalari-api-v3/blob/master/moduly/student_at_school.md,
https://github.com/bakalari-api/bakalari-api-v3/blob/master/moduly/absence.md);
the module name list independently matches the `bakapi` client's docs
[community](https://pypi.org/project/bakapi/)

### 2.4 Module-by-module: endpoints and payloads (API v3)

All under the school's base URL, Bearer-authenticated, JSON, UTF-8. GET unless
noted.

| Module (Czech) | Endpoints | What comes back |
| --- | --- | --- |
| Grades (známky) | `/api/3/marks`, `/api/3/marks/final`, `/api/3/marks/measures`, `/api/3/marks/count-new` | Per subject: marks with date, caption, theme, mark text (1, 1-, points, percent), type note (e.g. písemná práce), weight, teacher, points, confirmation state. Final marks and measures (disciplinary) separate. |
| Predict (předvídač) | `POST /api/3/marks/what-if` | Weighted-average prediction calculator, client posts hypothetical marks. |
| Timetable (rozvrh) | `/api/3/timetable/actual?date=YYYY-MM-dd`, `/api/3/timetable/permanent` | Days, hours, subjects, rooms, teachers, groups, change annotations, day types (WorkDay, Holiday, Celebration, DirectorDay...). Public timetables exist at `/Timetable/Public/` without login. |
| Substitution (suplování) | `/api/3/substitutions?from=` | Change list (Removed/Added/Canceled...) for a 14-day window by default. |
| Absence (absence) | `/api/3/absence/student` | Per-day counts (missed, late, early leave, school, distance teaching) and per-subject counts with percentage against the school's threshold. |
| Homework (domácí úkoly) | `/api/3/homeworks?from=&to=`, `/api/3/homeworks/count-actual` | Assignments with content, done/closed/electronic flags, subject, teacher, class/group, attachments. Default window: 14 days back, 1 day forward. |
| Messages (komens) | `POST /api/3/komens/messages/received`, `/sent`, `/noticeboard`, `/noticeboard/unread`, `/apology`, `/rating`; `/api/3/komens/message/$ID`, `.../mark-as-read`; `message-types`; `/api/3/komens/attachment/$ID` | Inbox with type-tagged messages (general, noticeboard, apology excuse, rating), HTML text, sender, attachments, read/confirm flags. The attachment endpoint also serves homework attachments. |
| Events (akce) | `/api/3/events`, `/api/3/events/my`, `/api/3/events/public?from=` | School events with times, type (školní akce...), classes, teachers, rooms. |
| Subjects and themes (předměty, témata) | `/api/3/subjects`, `/api/3/subjects/themes/$ID` | Subjects with teacher name and contact details (email, phones); per-subject list of lessons with taught topics for the whole school year. |
| User (uživatel) | `/api/3/user`, `/api/3/user/student-at-school` | Profile (name, class, school, user type, semester), enabled modules and rights; child-presence boolean. |
| GDPR (gdpr) | `/api/3/gdpr/commissioners`, `/consent`, `/consents/person`, `/consents/person/child` | Data-protection officer contact, consent records including the child's. |
| Payments (platby) | `/api/3/payments/classfund`, `/classfund/paymentsinfo`, `/classfund/summary` | Class-fund balance, monthly payment history with items. |
| Web bridge (web) | `/api/3/webmodule`, `/api/3/logintoken`, `/api/3/login/$TOKEN` | Web-only extras the school enabled (Dokumenty, Výukové zdroje) as `next/*.aspx` pages; one-time token that logs a browser into the web session. |
| Campaign (kanál) | `https://campaign.bakalari.cz/bannerinfo/$Location/$CampaignCategoryCode` | Vendor-operated banner service; the category code comes from `/api/3/user` and encodes school id, user type, study year. |

[community](https://github.com/bakalari-api/bakalari-api-v3/blob/master/endpoints.md
and moduly/ docs: marks.md, marks_final.md, marks_measures.md, whatif.md,
timetable.md, timetable_public.md, substitutions.md, absence.md, homework.md,
komens.md, attachment.md, events.md, subjects.md, themes.md, user.md,
student_at_school.md, gdpr.md, payments.md, web.md;
[campaign](https://github.com/bakalari-api/bakalari-api-v3/blob/master/campaign.md))

Not exposed by API v3 as documented: schůzky (parent-teacher consultation slots)
are part of the web Plán akcí experience rather than a documented v3 endpoint, and
the canteen lives in a separate system (section 1).

## 3. Access mechanics

### 3.1 Server address and school discovery

Every request goes to the school's own Bakaláři web address. The official app finds
schools through a vendor directory at `sluzby.bakalari.cz`; the endpoint
`/api/v1/municipality` returns public JSON listing municipalities and school
counts (verified live 2026-08-30, no authentication). Community maintainers
confirm this is the same list the mobile app uses, and that API access works at
every school that supports the mobile app.

[community](https://github.com/bakalari-api/bakalari-api-v3/blob/master/schools_list.md,
https://github.com/bakalari-api/bakalari-api/issues/47)

### 3.2 Login and tokens (API v3)

```
POST /api/login
Content-Type: application/x-www-form-urlencoded
client_id=ANDR&grant_type=password&username=...&password=...
```

Response: `access_token` (~2,500 chars), `refresh_token` (~3,500 chars), optional
`id_token`, `token_type: Bearer`, `expires_in: 3599` (599 on older servers),
scope `openid profile offline_access bakalari_api`, plus API/app version and user
id. Tokens are encrypted JWTs (JWE, `RSA-OAEP` + `A256CBC-HS512`); the id_token is
a plain RS256 JWT with `aud`/`azp` of `ANDR` (the Android client id) and the
school server as issuer. All module calls carry
`Authorization: Bearer <access_token>`; an expired or invalid token answers 401
with `{"Message":"Authorization has been denied for this request."}`, a bad
password answers 400 with `invalid_grant`.

Refresh: `grant_type=refresh_token&refresh_token=...`. Per the community doc, a
refresh token can be redeemed at most three times before the server rejects it,
and expires after roughly a month without use; both details are single-source
observations, not vendor docs.

[community](https://github.com/bakalari-api/bakalari-api-v3/blob/master/login.md)

### 3.3 Web single sign-on bridge

The app can log a browser in without the password: `GET /api/3/logintoken` with
the Bearer token returns a one-time `LOGIN_TOKEN`, and
`GET /api/3/login/$LOGIN_TOKEN?returnUrl=next/dash.aspx` answers 302 into an
authenticated web session. One credential set therefore drives both the mobile
API and the web app.

[community](https://github.com/bakalari-api/bakalari-api-v3/blob/master/moduly/web.md)

### 3.4 Legacy API v1 (phase-out)

The previous mobile interface lived on `/login.aspx` with a computed token `hx`
and a module name `pm` (e.g. `?hx=...&pm=rozvrh`), answering XML. Documented
modules: rozvrh, znamky, absence, ukoly, komenslisty/komsend/komdel, nastenka,
suplovani, akce, pololetni, predmety, and others. The token was computed from
username and password (community algorithm in `vypocitani_tokenu.md`). This
generation is being phased out; the community tracks the phase-out as "API v1
phaseout", and users report schools that already disabled it so that even the old
official app cannot connect. New work targets API v3.

[community](https://github.com/bakalari-api/bakalari-api,
https://github.com/bakalari-api/bakalari-api/issues/56,
https://github.com/bakalari-api/bakalari-api/issues/47)

### 3.5 Read-only is a choice the caller makes

The v3 interface mixes reads and writes. Reads that are still POSTs: all Komens
list endpoints. Writes: sending Komens messages, mark-as-read, read
confirmations, the what-if calculator, payments info, push-notification
registration (`/api/3/register-notification`). A passive gatherer can restrict
itself to GETs plus the Komens list POSTs, and should avoid mark-as-read and
confirmations because they change state the human sees: the web app displays
read/unread and confirmation badges, and the manual tells parents to check them.

[community](https://github.com/bakalari-api/bakalari-api-v3/blob/master/endpoints.md,
https://www.spspb.cz/wp-content/uploads/2024/09/bakalari_web_navod_pro_rodice.pdf)

### 3.6 Polling versus push

Push notifications (new marks, homework, Komens) belong to the official app via
the notification-registration endpoints and vendor infrastructure. A third-party
passive gatherer has no push channel into Bakaláři; it polls.

[official, app features](https://apps.apple.com/cz/app/bakal%C3%A1%C5%99i-online/id1459368580;
[community, endpoints](https://github.com/bakalari-api/bakalari-api-v3/blob/master/endpoints.md))

## 4. Community ecosystem

- The `bakalari-api` GitHub org hosts the de-facto documentation: API v1 module
  docs (55 stars), the API v3 analysis (141 stars, commits as recent as April
  2026), a token generator, and PHP utilities. Nothing there is vendor-authored.
  [community](https://github.com/bakalari-api,
  https://github.com/bakalari-api/bakalari-api-v3)
- Python: `bakapi` on PyPI (MIT, API v3, works from a refresh token alone,
  documents the EnabledModules names), and `async-bakalari-api3` (async client
  with its own docs site) which underpins the `bakalari-ha` Home Assistant
  integration; a second HA integration exists at `VitisEK/home-assistant-bakalari`.
  Note that the PyPI name `bakalari-api3` itself does not exist (checked
  2026-08-30, 404); the name maps to the GitHub org's v3 project and to these
  client libraries.
  [community](https://pypi.org/project/bakapi/,
  https://github.com/schizza/async-bakalari-api3,
  https://github.com/schizza/bakalari-ha,
  https://github.com/VitisEK/home-assistant-bakalari)
- Other platforms and clients built on the same interfaces: Bakalab (unofficial
  mobile client), Lepší Rozvrh, pain, Průměr Známek, Baka4J (Java),
  `bakalari-js` (Node), Bakalarium, Plochý rozvrh, and a community MCP server.
  [community](https://github.com/bakalari-api/bakalari-api-v3#aplikace-postaven%C3%A9-na-bakal%C3%A1%C5%99i-api-verze-3,
  https://github.com/bakalari-api/bakalari-api#programy-postaven%C3%A9-na-tomto-api,
  https://lobehub.com/mcp/mirecekd-bakalari-mcp)
- The breadth and age of third-party clients (some in stores for years) show the
  v3 interface is stable in practice. No vendor endorsement exists anywhere in
  these sources.

## 5. Terms of service and legal position

- **The sanctioned third-party route is the Datový konektor, and it is a paid
  B2B product.** The vendor's page defines it as the way "aplikace třetích stran"
  access Bakaláři data, read and modify. Licensing: paid; external companies get
  credentials under contract with Bakaláři; fee waivers are exceptional and only
  for apps a school develops for itself, requiring the school's consent statement
  including a GDPR clause. Transport: REST over HTTP(S), HTTP Basic
  authentication, XML or JSON. Scope: unauthenticated version/diagnostics,
  personal data of students, employees, and guardians, buildings, rooms, classes,
  access-system records, public events, timetables (permanent and current, per
  class/teacher/room/all), public substitution, and teachers' grade entry. It is
  aimed at integrators and schools, not at parents.
  [official](https://www.bakalari.cz/Static/konektor)
- **The mobile API has no published end-user terms.** Asked directly about usage
  conditions, community maintainers answered that the documented API exists for
  the official mobile app and is "not intended for any other use", that it is
  entirely separate from the Datový konektor, that they do not recommend
  commercial use, and that the binding terms for any user are the school's
  contract with Bakaláři software, which only the vendor or the school can
  interpret. [community](https://github.com/bakalari-api/bakalari-api-v3/issues/50)
- **GDPR shape.** The school is the data controller; the parent credential is
  issued by the school (possibly with the self-service password reset disabled),
  and the manual instructs parents to keep credentials private. The official app
  collects its own telemetry (coarse location, device id, crash data per the App
  Store privacy label) and needs explicit GDPR consent to show targeted
  third-party messages. Inside the system, GDPR is first-class: consents for self
  and child plus the data-protection officer are readable through the API.
  [official](https://www.bakalari.cz/static/faq,
  https://apps.apple.com/cz/app/bakal%C3%A1%C5%99i-online/id1459368580,
  https://www.spspb.cz/wp-content/uploads/2024/09/bakalari_web_navod_pro_rodice.pdf;
  [community](https://github.com/bakalari-api/bakalari-api-v3/blob/master/moduly/gdpr.md))
- **Access is observable.** The web app gives parents a login history with IP
  addresses and advises a password change on anything suspicious; whether API
  token issuance appears in that list is not publicly documented. Read receipts
  in Komens are shared state, so a gatherer that marks messages read leaves
  traces the co-parent or student notices. Server-side, every request is by
  definition an authenticated event the school can audit.
  [official manual](https://www.spspb.cz/wp-content/uploads/2024/09/bakalari_web_navod_pro_rodice.pdf);
  coverage of API logins in that list: unknown [single]
- **Credential lifetime is school-controlled.** Schools hand out and retire
  accounts; whether a parent keeps access after the child turns 18 (the child
  then holds the GDPR rights) is a live concern in parent communities, not
  something the vendor documents.
  [single, unverified](https://www.facebook.com/groups/pravadetiarodicu/posts/25202770099320243/)
- No source consulted records the vendor or a school taking action against a
  third-party client author. Community clients operate in a tolerated grey zone
  that could end per school, since each school runs its own server.

## 6. Confidence summary

- Confirmed by official documents: the module catalogue, what the web app and
  mobile app show parents, the Datový konektor terms, credential issuance, the
  advertising consent, per-school deployment.
- Confirmed by community tooling (multiple independent implementations over
  years, still maintained): the v3 login and token shape, the full v3 endpoint
  catalogue and payloads, the school-directory endpoint (also verified live),
  the v1 interface and its phase-out, the `/api/3/user` rights model.
- Single unverified sources: refresh-token triple-redeemability and its
  roughly-monthly expiry, `marks/count-new` always answering 0, whether API
  logins show up in the parent's login history, and the majority-age access
  thread.

## Sources

- https://www.bakalari.cz/ (vendor site, module catalogue at /Home/Modules)
- https://www.bakalari.cz/static/faq (official parent FAQ)
- https://www.bakalari.cz/Static/konektor (Datový konektor)
- https://www.bakalari.cz/Schools/NewsDetail/92 (Strava.cz canteen integration)
- https://apps.apple.com/cz/app/bakal%C3%A1%C5%99i-online/id1459368580 (official app)
- https://play.google.com/store/apps/details?id=cz.bakalari.mobile (official app, Android)
- https://www.spspb.cz/wp-content/uploads/2024/09/bakalari_web_navod_pro_rodice.pdf (school parent manual)
- https://www.zspostoloprty.cz/pristup-do-systemu-bakalari-zmena/d-1528 (cloud address format)
- https://zsplovarna.ji.cz/file.php?nid=19411&oid=8390854 (iCanteen as separate system)
- https://github.com/bakalari-api/bakalari-api-v3 (API v3 analysis; endpoints.md, login.md, moduly/*)
- https://github.com/bakalari-api/bakalari-api (API v1 docs; issues #47, #56)
- https://github.com/bakalari-api/bakalari-api-v3/issues/50 (usage-conditions question)
- https://sluzby.bakalari.cz/api/v1/municipality (school directory, verified live)
- https://pypi.org/project/bakapi/ (Python v3 client)
- https://github.com/schizza/async-bakalari-api3 and https://github.com/schizza/bakalari-ha
- https://github.com/VitisEK/home-assistant-bakalari
- https://lobehub.com/mcp/mirecekd-bakalari-mcp (community MCP server)
- https://www.facebook.com/groups/pravadetiarodicu/posts/25202770099320243/ (parent discussion, unverified)
