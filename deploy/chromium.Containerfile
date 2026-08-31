# Persistent Chromium for the WhatsApp web bridge: headed Chromium under
# Xvfb with a normal-Chrome user agent (WhatsApp's browser check gates on
# HeadlessChrome), CDP on 9222, and the profile directory on a volume so a
# linked WhatsApp session survives browser and supervisor restarts. The
# entrypoint script next to this file owns the details; docs/deployment.md
# documents the runbook and docs/research/whatsapp-integration.md §3.4 the
# PoC findings that forced this shape.
#
# Build context is this directory: podman build -f deploy/chromium.Containerfile deploy/
FROM docker.io/alpine:3.22

# font-noto/font-noto-emoji keep WhatsApp Web's text and emoji from
# rendering as boxes on the headless-server font set. socat bridges the
# CDP port to the outside (see chromium-run.sh: Chromium hard-codes the
# DevTools server to 127.0.0.1; --remote-debugging-address is gone).
RUN apk add --no-cache chromium xvfb socat font-noto font-noto-emoji

COPY chromium-run.sh /usr/local/bin/chromium-run
RUN chmod 0755 /usr/local/bin/chromium-run

ENV CHROMIUM_PROFILE_DIR=/data/profile
# The volume itself is declared by the compose service / Quadlet unit, not
# here: a VOLUME directive would make podman create an anonymous volume per
# container, which is exactly the session loss this setup exists to avoid.

ENTRYPOINT ["/usr/local/bin/chromium-run"]
