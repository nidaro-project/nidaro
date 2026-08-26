#!/usr/bin/env bash
# First install of the Nidaro prod pod: build the image, install the
# Quadlet units, and prepare the environment file. Run from anywhere; the
# script locates the repository on its own.
#
# See docs/deployment.md for the full runbook (linger, start, logs).
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
image=localhost/nidaro-prod:latest
env_file="${HOME}/.config/nidaro/prod.env"
quadlet_dir="${HOME}/.config/containers/systemd"

echo "Building ${image}"
podman build --ignorefile "${repo}/deploy/.containerignore" \
  -t "${image}" -f "${repo}/deploy/Containerfile" "${repo}"

mkdir -p "$(dirname "${env_file}")" "${quadlet_dir}"
if [[ ! -f "${env_file}" ]]; then
  install -m 600 "${repo}/deploy/env.prod.example" "${env_file}"
  cat <<EOF
Created ${env_file} from the template (mode 600).

Edit it now:
  - POSTGRES_PASSWORD (and the same value inside NIDARO_DATABASE_URL)
  - NIDARO_MODEL and the matching provider key
Then re-run this script to finish the installation.
EOF
  exit 1
fi

for unit in "${repo}"/deploy/quadlet/*; do
  ln -sfn "${unit}" "${quadlet_dir}/"
done
systemctl --user daemon-reload

echo "Installed $(ls "${repo}"/deploy/quadlet | wc -l) Quadlet units"
echo "Start the pod with:"
echo "  systemctl --user start nidaro-prod-pod.service"
echo "(Boot start needs no 'systemctl enable': the Quadlet generator"
echo " applies the [Install] section on its own.)"
