# Nidaro production deployment

Nidaro runs as a fully containerized service in its own Podman pod,
`nidaro-prod`, managed by systemd user units (Quadlet). The pod shares one
network namespace: PostgreSQL, Redis, the API, the Taskiq worker, and the
Taskiq scheduler talk to each other over `localhost`. The only published
port is HTTP on `0.0.0.0:8100`: the UI shell is served at `/` (see
[DESIGN.md](../DESIGN.md)), the API under `/api/v1`, and `/health` and
`/ready` remain process/dependency checks. The development setup (compose
on host ports 5432/6379, dev server on 8000) is not touched and can run in
parallel.

## Prerequisites (one time)

Rootless Podman 5.x and Quadlet (standard on Fedora). Enable lingering so
the user manager — and with it the pod — starts at boot without a login:

```bash
sudo loginctl enable-linger "$USER"
loginctl show-user "$USER" -p Linger   # expect: Linger=yes
```

## First install

```bash
./deploy/install.sh
```

The script builds the image `localhost/nidaro-prod:latest`, installs the
Quadlet units into `~/.config/containers/systemd/` (symlinks to the
repository), and creates `~/.config/nidaro/prod.env` from the template with
mode 600. On the first run it stops and asks you to edit that file:

- `POSTGRES_PASSWORD` — generate one, e.g. `openssl rand -base64 24`. The
  same value must appear inside `NIDARO_DATABASE_URL` (Podman env files do
  not interpolate).
- `NIDARO_MODEL` and the matching provider key.

Re-run `./deploy/install.sh` after editing, then start the pod:

```bash
systemctl --user start nidaro-prod-pod.service
```

`systemctl enable` does not work for Quadlet units (systemd refuses to
enable generated units). It is not needed: the generator applies the
`[Install] WantedBy=default.target` section on its own, so with lingering
enabled the pod starts at boot.

Pre-pulling the database and Redis images avoids first-start latency:

```bash
podman pull docker.io/library/postgres:17-alpine docker.io/library/redis:8-alpine
```

## What runs where

| systemd unit (user) | Container | Role |
|---|---|---|
| `nidaro-prod-pod.service` | pod `nidaro-prod` | Network namespace, publishes 8100→8000 |
| `nidaro-prod-db.service` | `nidaro-prod-db` | PostgreSQL 17, volume `systemd-nidaro-prod-pgdata` |
| `nidaro-prod-redis.service` | `nidaro-prod-redis` | Redis 8, volume `systemd-nidaro-prod-redisdata` |
| `nidaro-prod-migrate.service` | `nidaro-prod-migrate` | One-shot: `alembic upgrade head` + `nidaro-seed` |
| `nidaro-prod-api.service` | `nidaro-prod-api` | uvicorn API on 8000 (published as 8100) |
| `nidaro-prod-worker.service` | `nidaro-prod-worker` | Taskiq worker |
| `nidaro-prod-scheduler.service` | `nidaro-prod-scheduler` | Taskiq scheduler (cron labels) |

Start order is enforced by systemd: the database and Redis report "started"
only when their healthchecks pass (`Notify=healthy`), the migration unit
requires both, and the API, worker, and scheduler require the migration. A
failed migration therefore stops the stack from starting half-broken.

## Checking and logs

```bash
systemctl --user list-units 'nidaro-prod*'
podman ps --pod                       # per-container health
curl -s http://localhost:8100/health  # process-only
curl -s http://localhost:8100/ready   # checks PostgreSQL and Redis
open http://127.0.0.1:8100/           # the UI shell (rootless quirk: use 127.0.0.1)
journalctl --user -u nidaro-prod-api.service -f
journalctl --user -u nidaro-prod-worker.service -f
journalctl --user -u nidaro-prod-migrate.service    # migration/seed output
```

Static assets (CSS, JS, images) are served by the same uvicorn process
from `/static/*`; they are part of the project wheel, so no extra image
content or volume is needed.

Use `journalctl --user -u <unit>`, not `podman logs`: containers are
re-created on every restart, and only journald keeps the history.

## Deploying a new build

```bash
./deploy/update.sh
```

Rebuilds the image, re-runs the (idempotent) migration and seed gate, and
restarts the API, worker, and scheduler. Restarting a single app unit by
hand (`systemctl --user restart nidaro-prod-api.service`) does not re-run
migrations; only `nidaro-prod-migrate.service` does.

## Changing configuration or secrets

Edit `~/.config/nidaro/prod.env`, then restart:

```bash
systemctl --user restart nidaro-prod-pod.service
```

Configuration is read once per process at container start (`get_settings()`
is cached). Note that `POSTGRES_PASSWORD` applies only when the data volume
is initialized; changing it later does not change the database password.

### Rotating the connector credential key

Connector secrets (Bakaláři passwords, OAuth refresh tokens, app-specific
passwords) are stored in PostgreSQL as Fernet ciphertext keyed by
`NIDARO_CREDENTIAL_KEY`. Plaintext never reaches the database, so statement
logs, `pg_dump` output, and migrations carry no secrets. To rotate the key
without losing access:

1. Generate a new key:

   ```bash
   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. In `~/.config/nidaro/prod.env`, set `NIDARO_CREDENTIAL_KEY` to the new key
   and list the old one in `NIDARO_CREDENTIAL_PREVIOUS_KEYS` (comma-separated
   when more than one old key is still in flight). Stored ciphertext stays
   decryptable through the fallback keys.
3. Restart the pod (`systemctl --user restart nidaro-prod-pod.service`) and
   re-encrypt every stored secret under the new primary key:

   ```bash
   podman exec nidaro-prod-api nidaro-rotate-credentials
   ```

4. Remove the old key from `NIDARO_CREDENTIAL_PREVIOUS_KEYS` and restart the
   pod again. From here on only the new key can read the stored secrets.

A row that no longer matches any configured key makes
`nidaro-rotate-credentials` fail with the row's connector/name/household —
never the secret itself. The affected credential must be re-entered
(`set` through the service seam) and the rotation re-run.

### Connecting Google Calendar

The Google Calendar connector uses three-legged OAuth (one consent per
family member — service accounts cannot reach personal `@gmail.com`
calendars). Setup, once per nidaro instance:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project, configure the OAuth consent screen as **External**, and create
   an **OAuth client ID** of type **Web application**.
2. Register the exact redirect URI
   `http://<host>:8100/api/v1/connectors/google-calendar/callback`
   (Authorized redirect URIs). The default `NIDARO_GOOGLE_REDIRECT_URI`
   already matches this route on `localhost:8100`; change it if the API is
   reached under another address.
3. Put the client id and secret into `~/.config/nidaro/prod.env` as
   `NIDARO_GOOGLE_CLIENT_ID` / `NIDARO_GOOGLE_CLIENT_SECRET` and restart
   the pod.

Each family member then opens
`http://<host>:8100/api/v1/connectors/google-calendar/connect` in their own
browser, clicks through Google's screens, and lands back in Settings. The
refresh token is stored encrypted (same `NIDARO_CREDENTIAL_KEY` store as the
other connector secrets); only its ciphertext reaches PostgreSQL.

**Publishing status (decided):** the consent screen should be switched to
**In production (unverified)** before real use. Consequences of the two
options:

- *In production, unverified*: members see an "unverified app" warning
  screen, and the app is capped at 100 new users until it is verified —
  both irrelevant for one household. Refresh tokens are **stable**.
- *Testing*: no warning-screen hurdle, but every refresh token **expires
  after 7 days** and each member must re-consent weekly. Unusable for an
  always-on sync.

If a member's sync stops with `invalid_grant` (worker log: "must reconnect
their account"), their token was revoked or expired — they re-run the
connect link. Sync cadence per household comes from the connector config
(`poll_seconds`); the sync itself is read-mostly polling plus the
assistant's create/update/delete writes through the Google write service.

## Data backup

```bash
podman exec nidaro-prod-db pg_dump -U nidaro -d nidaro > "nidaro-$(date +%F).sql"
```

Cold volume copy (stops nothing by itself; do it while the pod is stopped
for a consistent snapshot):

```bash
systemctl --user stop nidaro-prod-pod.service
podman volume export systemd-nidaro-prod-pgdata -o pgdata.tar
systemctl --user start nidaro-prod-pod.service
```

## Teardown

```bash
systemctl --user disable --now nidaro-prod-pod.service
rm ~/.config/containers/systemd/nidaro-prod*      # removes the symlinks
systemctl --user daemon-reload
podman pod rm -f nidaro-prod
podman volume rm systemd-nidaro-prod-pgdata systemd-nidaro-prod-redisdata   # destroys data
podman image rm localhost/nidaro-prod:latest       # optional
sudo loginctl disable-linger "$USER"               # only when abandoning auto-start
```

## Troubleshooting

- **API unreachable on 8100**: use `127.0.0.1` or the machine's address.
  The rootless port forwarder serves IPv4 only; `localhost` resolving to
  `::1` gets a connection reset. Also, uvicorn must bind `0.0.0.0` (the
  unit's `Exec=` pins it); the default `127.0.0.1` is not reachable
  through the pod's published port.
- **Everything waits for `nidaro-prod-db.service`**: the unit starts only
  when `pg_isready` passes (`Notify=healthy`). Check
  `journalctl --user -u nidaro-prod-db.service` — the usual cause is a
  first-run image pull or a wrong `POSTGRES_PASSWORD`.
- **App units stay stopped**: a failed migration stops the chain on
  purpose. Read `journalctl --user -u nidaro-prod-migrate.service`. After
  fixing the cause, restarting the migrate unit alone does not pull the
  app units back in — start them too, or run `./deploy/update.sh`, which
  restarts all four.
- **Nothing starts after reboot**: lingering is off
  (`loginctl show-user "$USER" -p Linger`).
- **`systemctl --user enable` fails with "transient or generated"**: this
  is expected for Quadlet units. Start with `systemctl --user start`; boot
  start comes from the `[Install]` section the generator applies.
- **Env changes have no effect**: restart the pod service; env is read at
  container start only.
