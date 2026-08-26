#!/usr/bin/env bash
# Deploy a new build of Nidaro prod: rebuild the image, re-run the
# idempotent migration/seed gate, and cycle the app units. Container
# re-creation resolves the :latest tag at start, so the new image is
# picked up without removing anything by hand.
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

podman build --ignorefile "${repo}/deploy/.containerignore" \
  -t localhost/nidaro-prod:latest -f "${repo}/deploy/Containerfile" "${repo}"

# Requires= makes the app units follow the migrate restart; they are listed
# explicitly for clarity.
systemctl --user restart \
  nidaro-prod-migrate.service \
  nidaro-prod-api.service \
  nidaro-prod-worker.service \
  nidaro-prod-scheduler.service

echo "Deployed. Check with:"
echo "  systemctl --user list-units 'nidaro-prod*'"
echo "  curl -s http://localhost:8100/health"
