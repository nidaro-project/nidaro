#!/usr/bin/env bash
# E2E smoke test for the school portal page. See [portal-10] and DESIGN.md.
#
# Verifies, against a running dev server (with seeded school data):
#   1. /school renders the kid rail with the children only (no parents)
#   2. Today at school lists seeded lessons; a canceled lesson is struck and badged
#   3. Grades render with the seeded value and an unconfirmed badge
#   4. Emma shows seeded homework; Leo shows the graceful-empty state
#   5. What to pack shows the seeded equipment and per-subject editors
#   6. Switching kid via ?kid= swaps the selected rail card
#   7. No page exceptions or broken requests during the run
#
# Usage: scripts/e2e_school.sh [BASE_URL]   (default http://localhost:8931)
# Exit code 0 = pass. On failure: prints expected vs observed and saves
# /tmp/nidaro-e2e-failure.png.

set -euo pipefail

BASE_URL="${1:-http://localhost:8931}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVENTS="$(mktemp /tmp/nidaro-e2e-events.XXXXXX.jsonl)"
FAIL_SHOT="/tmp/nidaro-e2e-failure.png"
OFFSET=0

INSTANCE=""  # set by launch; the name is derived from the working directory

cleanup() {
  [ -n "$INSTANCE" ] && chrome-agent stop "$INSTANCE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "FAIL: $1" >&2
  echo "  expected: $2" >&2
  echo "  observed: $3" >&2
  chrome-agent "$INSTANCE" Page.captureScreenshot '{"format":"png"}' 2>/dev/null \
    | python3 -c "import sys,json,base64; open('$FAIL_SHOT','wb').write(base64.b64decode(json.load(sys.stdin)['data']))" 2>/dev/null \
    && echo "  screenshot: $FAIL_SHOT" >&2
  exit 1
}

read_value() {
  # Emits the evaluated value as compact JSON so assertions can grep exact pairs.
  chrome-agent "$INSTANCE" Runtime.evaluate "{\"expression\":\"$1\",\"returnByValue\":true}" \
    | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['result']['value'],separators=(',',':')))"
}

wait_loaded() {
  local out
  out=$(python3 "$SCRIPT_DIR/cdp-wait.py" --file "$EVENTS" \
    --method Page.loadEventFired --timeout 15 --from-offset "$OFFSET" --print-offset 2>&1)
  OFFSET=$(echo "$out" | sed -n 's/^offset=//p')
}

wait_stream_ready() {
  # Block until the attach session reports ready, or the subscription races the
  # first navigation and load events are dropped.
  python3 "$SCRIPT_DIR/cdp-wait.py" --file "$EVENTS" \
    --contains '"status"' --contains 'ready' --timeout 15 >/dev/null
}

# ------------------------------- setup -----------------------------------------

INSTANCE=$(chrome-agent launch --headless | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")

# Watch for failures in every observation (skill rule 3).
chrome-agent attach "$INSTANCE" +Page.loadEventFired +Runtime.exceptionThrown +Network.loadingFailed > "$EVENTS" 2>&1 &
ATTACH_PID=$!
trap 'kill $ATTACH_PID 2>/dev/null || true; cleanup' EXIT
wait_stream_ready

# Deterministic viewport so layout-dependent assertions are stable.
chrome-agent "$INSTANCE" Emulation.setDeviceMetricsOverride '{"width":1600,"height":1000,"deviceScaleFactor":1,"mobile":false}' >/dev/null

# ------------------- 1. kid rail: children only, both kids present -------------
chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/school\"}" >/dev/null
wait_loaded
STATE=$(read_value "(()=>({kids:[...document.querySelectorAll('.sp-kid strong')].map(e=>e.textContent),parents:document.body.textContent.includes('Alex')||document.body.textContent.includes('Sam')}))()")
echo "$STATE" | grep -q '"kids":\["Emma","Leo"\]' || fail "kid rail children" 'kids == ["Emma","Leo"]' "$STATE"
echo "$STATE" | grep -q '"parents":false' || fail "parents hidden from rail" "false" "$STATE"

# ------------------- 2. today's lessons with a canceled one --------------------
STATE=$(read_value "(()=>({subjects:[...document.querySelectorAll('.sp-row .sp-subject')].map(e=>e.textContent),dead:document.querySelectorAll('.sp-row--dead').length,canceled:!!document.querySelector('.sp-sub-badge--canceled')}))()")
echo "$STATE" | grep -q '"subjects":\["Matematika"' || fail "seeded lessons listed" 'first subject Matematika' "$STATE"
echo "$STATE" | grep -q '"dead":1' || fail "canceled lesson struck" "1 struck row" "$STATE"
echo "$STATE" | grep -q '"canceled":true' || fail "canceled badge" "true" "$STATE"

# ------------------- 3. grades with unconfirmed badge --------------------------
STATE=$(read_value "(()=>({grade:document.querySelector('.sp-grade')?.textContent,unconfirmed:document.body.textContent.includes('not confirmed')}))()")
echo "$STATE" | grep -q '"grade":"1"' || fail "seeded grade value" '"1"' "$STATE"
echo "$STATE" | grep -q '"unconfirmed":true' || fail "unconfirmed badge" "true" "$STATE"

# ------------------- 4. homework: Emma seeded, Leo graceful-empty --------------
STATE=$(read_value "(()=>({hw:document.body.textContent.includes('Worksheet p. 34')}))()")
echo "$STATE" | grep -q '"hw":true' || fail "Emma homework" 'Worksheet p. 34 present' "$STATE"

KID_LEO=$(read_value "(()=>[...document.querySelectorAll('.sp-kid')].find(a=>a.textContent.includes('Leo'))?.href.match(/kid=([^&]+)/)?.[1])()" | tr -d '"')
chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/school?kid=$KID_LEO\"}" >/dev/null
wait_loaded
STATE=$(read_value "(()=>({selected:document.querySelector('.sp-kid[aria-current=page] strong')?.textContent,clear:document.body.textContent.includes('Nothing due — all clear.')}))()")
echo "$STATE" | grep -q '"selected":"Leo"' || fail "kid switch selects Leo" 'Leo aria-current' "$STATE"
echo "$STATE" | grep -q '"clear":true' || fail "Leo homework empty state" 'all clear text' "$STATE"

# ------------------- 5. what to pack: equipment + editors ----------------------
KID_EMMA=$(read_value "(()=>[...document.querySelectorAll('.sp-kid')].find(a=>a.textContent.includes('Emma'))?.href.match(/kid=([^&]+)/)?.[1])()" | tr -d '"')
chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/school?kid=$KID_EMMA\"}" >/dev/null
wait_loaded
STATE=$(read_value "(()=>({pack:document.body.textContent.includes('Gym kit'),editors:document.querySelectorAll('#packing details').length}))()")
echo "$STATE" | grep -q '"pack":true' || fail "packing equipment" 'Gym kit present' "$STATE"
echo "$STATE" | grep -q '"editors":4' || fail "packing editors" "4 subject editors" "$STATE"

# ------------------- 6. no page exceptions or broken requests -------------------

if grep -qE 'exceptionThrown|loadingFailed' "$EVENTS"; then
  grep -E 'exceptionThrown|loadingFailed' "$EVENTS" | head -3 >&2
  fail "page raised exceptions or failed requests during the run" "clean event stream" "see events above ($EVENTS)"
fi

echo "PASS: school portal smoke test ($BASE_URL)"
