# The school portal is passive and read-only

Nidaro's school section only shows information gathered from school systems
(Bakaláři first; Škola OnLine observed for later) — it never writes back or
triggers a change in the school system: no mark-as-read, no replies, no
sign-ups, no homework entry. The gatherer reads parent-scoped endpoints
GET-only over the community-documented mobile API, polls rather than pushes,
and uses the parent's own credentials stored encrypted. We decided this
because the school systems have their own apps for interaction and Nidaro is
not trying to replace them; the vendor's only sanctioned third-party route is
a paid B2B connector we deliberately decline; the school, not the vendor, is
the GDPR controller for the children's data; and parent access is observable
(login history, Komens read receipts), so any write would carry legal and
social risk a family assistant should not take on.

Consequences, because they will surprise readers:

- Messages (Komens) shown in Nidaro never become "read" in the school
  system; replies happen in the school's own app.
- Homework arrives only if the school enters it. For paper-method schools the
  feed stays empty by design; Nidaro does not add its own interactive
  homework tracking to fill the gap.
- Any future interactivity (replies, event sign-ups, canteen ordering)
  supersedes this ADR — it is not an extension of the gatherer.
