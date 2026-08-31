#!/bin/sh
# Entrypoint of the persistent-Chromium image (deploy/chromium.Containerfile).
#
# Runs headed Chromium under Xvfb — never --headless: WhatsApp's browser
# check gates on the HeadlessChrome user agent (whatsapp-integration.md
# §3.4, PoC result 4). CDP listens on 9222 for the supervisor
# (nidaro.chromium) and any chrome-agent attach session; the profile
# directory holds the linked WhatsApp session and must sit on a persistent
# volume. Nothing here uses chrome-agent's launch/registry: it wipes
# instance session dirs on stop, logging the device out (§3.4 gotcha).
set -eu

: "${CHROMIUM_PROFILE_DIR:=/data/profile}"
: "${CHROMIUM_SCREEN:=1920x1080x24}"
: "${CHROMIUM_START_URL:=https://web.whatsapp.com}"
# Default claims the packaged Chromium's own major version so the UA string
# agrees with the Sec-CH-UA headers the browser really sends. Override with
# CHROMIUM_USER_AGENT if a specific UA is ever needed.
: "${CHROMIUM_USER_AGENT:=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$(chromium --version | sed -E 's/^[^0-9]*([0-9.]+).*/\1/') Safari/537.36}"

# A hard kill leaves Singleton* files behind; exactly one container owns a
# profile volume, so any such file is stale, and Chromium refuses to start
# while it believes another instance holds the profile. Same for Xvfb's
# lock/socket in the container's persistent /tmp — a stale one makes every
# subsequent start fail with "server is no longer running".
rm -f "$CHROMIUM_PROFILE_DIR"/Singleton* /tmp/.X99-lock /tmp/.X11-unix/X99
mkdir -p "$CHROMIUM_PROFILE_DIR"

Xvfb :99 -screen 0 "$CHROMIUM_SCREEN" -nolisten tcp &

# Chromium hard-codes the DevTools HTTP/WebSocket server to 127.0.0.1
# (--remote-debugging-address was removed for security; the flag is ignored
# by current Chrome). In the prod pod every consumer shares the pod's
# network namespace and uses 127.0.0.1:9222 directly. The published-port
# development setup instead needs a listener on a non-loopback address, so
# a fork-mode socat forwards 0.0.0.0:9223 → 127.0.0.1:9222 inside the
# container; compose publishes host 127.0.0.1:9222 to it. Reachability
# stays local everywhere: dev publishes to host loopback only, prod
# publishes nothing.
socat TCP-LISTEN:9223,bind=0.0.0.0,fork,reuseaddr TCP:127.0.0.1:9222 &

# --no-sandbox: Chromium's sandbox needs setuid/user-namespace help that
# rootless podman does not provide; the container has no published port and
# its only network neighbours are the pod's own services.
# --disable-dev-shm-usage: containers ship a 64M /dev/shm; a heavy site on
# a long-lived session can exhaust it and crash the tab.
exec env DISPLAY=:99 chromium \
  --user-data-dir="$CHROMIUM_PROFILE_DIR" \
  --remote-debugging-port=9222 \
  --user-agent="$CHROMIUM_USER_AGENT" \
  --window-size="$(echo "$CHROMIUM_SCREEN" | cut -dx -f1),$(echo "$CHROMIUM_SCREEN" | cut -dx -f2)" \
  --no-first-run \
  --no-default-browser-check \
  --password-store=basic \
  --disable-session-crashed-bubble \
  --hide-crash-restore-bubble \
  --disable-dev-shm-usage \
  --no-sandbox \
  "$CHROMIUM_START_URL"
