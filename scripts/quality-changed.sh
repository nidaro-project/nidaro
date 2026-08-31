#!/usr/bin/env bash
# Pre-gate check: pinned analyzers on changed Python only.
# Cheap loop between micro-edits; `aufsicht fast`/`full` remain the gates of record.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PIN_RUFF=$(awk -F'"' '/^ruff =/{print $2}' .quality/toolchain.lock)
PIN_PYRIGHT=$(awk -F'"' '/^pyright =/{print $2}' .quality/toolchain.lock)
VENV_PY="$PWD/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "error: $VENV_PY not found — run 'uv sync' in this checkout first" >&2
  exit 1
fi
# Tracked changes vs HEAD plus untracked files; drop paths that no longer exist
# (git diff lists deletions, and the analyzers would fail on them).
mapfile -t FILES < <(
  { git diff --name-only HEAD -- '*.py'; git ls-files -o --exclude-standard -- '*.py'; } \
    | sort -u | while IFS= read -r f; do [ -f "$f" ] && printf '%s\n' "$f"; done
)
if [ "${#FILES[@]}" -eq 0 ]; then
  echo "no changed python files"
  exit 0
fi
uvx "ruff@${PIN_RUFF}" format --check --config .quality/ruff.toml "${FILES[@]}"
uvx "ruff@${PIN_RUFF}" check --config .quality/ruff.toml "${FILES[@]}"
uvx "pyright@${PIN_PYRIGHT}" --pythonpath "$VENV_PY" "${FILES[@]}"
echo "precheck clean: ${FILES[*]}"
