# Nidaro production deployment

Nidaro runs as a fully containerized service in its own Podman pod,
`nidaro-prod`, managed by systemd user units (Quadlet). The pod shares one
network namespace: PostgreSQL, Redis, the API, the Taskiq worker, and the
Taskiq scheduler talk to each other over `localhost`. The only published
port is HTTP on `0.0.0.0:8100`: the UI shell is served at `/` (see
[DESIGN.md](../DESIGN.md)), the API under `/api/v1`, and `/health` and
`/ready` remain process/dependency checks. The development setup (compose
on host ports 5432/6379 plus the bridge browser on 127.0.0.1:9222, dev
server on 8000) is not touched and can run in parallel.

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
| `nidaro-prod-chromium.service` | `nidaro-prod-chromium` | Persistent Chromium (WhatsApp web bridge), CDP on pod-localhost:9222 |

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

## The WhatsApp bridge browser

The `nidaro-prod-chromium` unit runs a real, headed Chromium (under Xvfb,
with a normal-Chrome user agent — WhatsApp's browser check gates on
`HeadlessChrome`) inside the pod. It is the browser of the WhatsApp web
bridge; the rationale and the PoC findings that forced this shape live in
docs/research/whatsapp-integration.md §3.4.

Properties that matter:

- **The profile is a volume** (`systemd-nidaro-prod-chromium-profile`,
  mounted at `/data/profile`). A WhatsApp device linked via QR survives
  browser crashes, container restarts, and supervisor restarts. Deleting
  the volume logs the device out; a new QR pairing is then needed. Never
  move the profile into the container filesystem, and never manage this
  browser with `chrome-agent launch`/`stop` — its registry wipes session
  directories on stop.
- **CDP on pod-localhost:9222, not published.** Only pod members (the
  worker, the supervisor) can reach it. Chromium hard-codes the DevTools
  server to `127.0.0.1`, so the image carries a small socat forwarder for
  the published-port development setup; in the pod it is unused.
- **No WhatsApp credentials in env or database.** The linked session IS
  the credential; it lives only in the profile volume. Back it up like the
  database volume (cold copy while the pod is stopped).

The supervisor itself is `nidaro-chromium-supervisor` (console script over
`nidaro.chromium.supervisor.ChromiumSupervisor`): it attaches
chrome-agent's `CDPClient` to the browser-level WebSocket endpoint, pings
`Browser.getVersion` every 10 s, and on failure reconnects with capped
backoff until the browser service returns. The WhatsApp observer task will
embed it in the worker; run standalone it is the smoke test for the whole
path:

```bash
# attach logs the browser version; restart the chromium container and watch
# "Lost Chromium" → backoff → "Attached to Chromium" again
podman exec nidaro-prod-api nidaro-chromium-supervisor   # or: uv run nidaro-chromium-supervisor
```

### QR pairing (once per install, needs the sacrificial number)

The browser opens web.whatsapp.com on start. Grab the login QR as a CDP
screenshot — from a dev checkout against the published port, or from the
API container (chrome-agent is a nidaro dependency) in prod — and scan it
with the sacrificial phone:

```bash
podman exec nidaro-prod-api python - <<'EOF' > qr.png
import asyncio, base64, sys
from chrome_agent.cdp_client import CDPClient, get_ws_url

async def main():
    url = await asyncio.to_thread(get_ws_url, 9222, "page")
    async with CDPClient(ws_url=url) as cdp:
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        page = await cdp.send("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
        await cdp.send("Page.navigate", {"url": page["result"]["value"]})
        await asyncio.sleep(8)  # let the QR frame render
        info = await cdp.send("Page.captureScreenshot", {"format": "png"})
        sys.stdout.buffer.write(base64.b64decode(info["data"]))

asyncio.run(main())
EOF
```

The QR refreshes periodically; re-run until the scan takes. Afterwards
"Linked devices" on the phone should list the session, and the profile
volume holds it across restarts. (Verified end to end on 2026-08-31
against the compose container: the login page renders fully under Xvfb
with the spoofed UA, and `Page.captureScreenshot` captures the QR frame.)

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

## Data backup

```bash
podman exec nidaro-prod-db pg_dump -U nidaro -d nidaro > "nidaro-$(date +%F).sql"
```

Cold volume copy (stops nothing by itself; do it while the pod is stopped
for a consistent snapshot):

```bash
systemctl --user stop nidaro-prod-pod.service
podman volume export systemd-nidaro-prod-pgdata -o pgdata.tar
podman volume export systemd-nidaro-prod-chromium-profile -o chromium-profile.tar
systemctl --user start nidaro-prod-pod.service
```

The Chromium profile volume holds the linked WhatsApp session — without a
backup, losing it means a new QR pairing for the bridge.

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
