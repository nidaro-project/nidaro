#!/usr/bin/env bash
# E2E smoke test for the nidaro UI shell. See DESIGN.md and docs/agents/.
#
# Verifies, against a running dev server:
#   1. Home renders the shell (9 nav links, 12 cards, default daylight theme)
#   2. Settings offers all three themes
#   3. Clicking Dusk switches data-theme, persists to localStorage, moves aria-pressed
#   4. The theme survives navigation to another page
#   5. Placeholder sections render their heading and icon
#   6. Meals week view renders the seeded plan (grid, 7 day heads, today's chip)
#   7. HTMX on the week grid: a one-off add swaps the chip in, remove swaps it out
#   8. Dishes page renders the Typical dishes table with the seeded rotation
#   9. No JS exceptions and no failed network requests during the run
#
# Usage: scripts/e2e_ui_shell.sh [BASE_URL]   (default http://localhost:8931)
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

# One Runtime.evaluate that returns a JSON value; echoes the raw value.
read_value() {
  # Emits the evaluated value as compact JSON so assertions can grep exact pairs.
  chrome-agent "$INSTANCE" Runtime.evaluate "{\"expression\":\"$1\",\"returnByValue\":true}" \
    | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['result']['value'],separators=(',',':')))"
}

wait_stream_ready() {
  # Block until the attach session reports ready, or the subscription races the
  # first navigation and load events are dropped.
  python3 "$SCRIPT_DIR/cdp-wait.py" --file "$EVENTS" \
    --contains '"status"' --contains 'ready' --timeout 15 >/dev/null
}

wait_loaded() {
  local out
  out=$(python3 "$SCRIPT_DIR/cdp-wait.py" --file "$EVENTS" \
    --method Page.loadEventFired --timeout 15 --from-offset "$OFFSET" --print-offset 2>&1)
  OFFSET=$(echo "$out" | sed -n 's/^offset=//p')
}

await_value() {
  # Runtime.evaluate that resolves an in-page promise: the expression polls the
  # DOM itself and settles when the post-swap state is observable (or times
  # out), so no fixed sleeps. Echoes the resolved value as compact JSON.
  chrome-agent "$INSTANCE" Runtime.evaluate "{\"expression\":\"$1\",\"awaitPromise\":true,\"returnByValue\":true}" \
    | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['result']['value'],separators=(',',':')))"
}

element_center() {
  # Center coords of the element a JS expression returns, after scrolling it
  # into view (same scroll-then-measure as the theme click in section 3).
  chrome-agent "$INSTANCE" Runtime.evaluate "{\"expression\":\"(()=>{const el=($1);el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()\",\"returnByValue\":true}" \
    | python3 -c "import sys,json; v=json.load(sys.stdin)['result']['value']; print(v['x'],v['y'])"
}

click_at() {
  # Real input pipeline, same as section 3: synthetic el.click() is fabricated
  # in page JS and can silently miss.
  chrome-agent "$INSTANCE" Input.dispatchMouseEvent "{\"type\":\"mousePressed\",\"x\":$1,\"y\":$2,\"button\":\"left\",\"clickCount\":1}" >/dev/null
  chrome-agent "$INSTANCE" Input.dispatchMouseEvent "{\"type\":\"mouseReleased\",\"x\":$1,\"y\":$2,\"button\":\"left\",\"clickCount\":1}" >/dev/null
}

# ------------------------------- setup -----------------------------------------

INSTANCE=$(chrome-agent launch --headless | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")

# Watch for failures in every observation (skill rule 3).
chrome-agent attach "$INSTANCE" +Page.loadEventFired +Runtime.exceptionThrown +Network.loadingFailed > "$EVENTS" 2>&1 &
ATTACH_PID=$!
trap 'kill $ATTACH_PID 2>/dev/null || true; cleanup' EXIT
wait_stream_ready

# Deterministic viewport so layout-dependent assertions and clicks are stable.
chrome-agent "$INSTANCE" Emulation.setDeviceMetricsOverride '{"width":1600,"height":1000,"deviceScaleFactor":1,"mobile":false}' >/dev/null

# ------------------------- 1. home renders the shell ---------------------------

chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/\"}" >/dev/null
wait_loaded
STATE=$(read_value "(()=>({theme:document.documentElement.dataset.theme,navLinks:document.querySelectorAll('.nav__link').length,cards:document.querySelectorAll('.card').length}))()")
echo "$STATE" | grep -q '"theme":"daylight"' || fail "home default theme" "daylight" "$STATE"
echo "$STATE" | grep -q '"navLinks":9' || fail "home nav link count" "9" "$STATE"
echo "$STATE" | grep -q '"cards":12' || fail "home card count" "12" "$STATE"

# ------------------------- 2. settings lists the themes ------------------------

chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/settings\"}" >/dev/null
wait_loaded
CHOICES=$(read_value "[...document.querySelectorAll('[data-theme-choice]')].map(b=>b.dataset.themeChoice).join(',')")
[ "$CHOICES" = "\"daylight,meadow,dusk\"" ] || fail "settings theme choices" "\"daylight,meadow,dusk\"" "$CHOICES"

# --------------- 3. clicking Dusk switches theme and persists ------------------

chrome-agent "$INSTANCE" Runtime.evaluate '{"expression":"[...document.querySelectorAll(\u005Bdata-theme-choice\u005D)].find(b=>b.dataset.themeChoice===\u0027dusk\u0027).scrollIntoView({block:\u0027center\u0027})"}' >/dev/null
COORDS=$(read_value "(()=>{const el=[...document.querySelectorAll('[data-theme-choice]')].find(b=>b.dataset.themeChoice==='dusk');const r=el.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()")
X=$(echo "$COORDS" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['x'])")
Y=$(echo "$COORDS" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['y'])")
chrome-agent "$INSTANCE" Input.dispatchMouseEvent "{\"type\":\"mousePressed\",\"x\":$X,\"y\":$Y,\"button\":\"left\",\"clickCount\":1}" >/dev/null
chrome-agent "$INSTANCE" Input.dispatchMouseEvent "{\"type\":\"mouseReleased\",\"x\":$X,\"y\":$Y,\"button\":\"left\",\"clickCount\":1}" >/dev/null
STATE=$(read_value "(()=>({theme:document.documentElement.dataset.theme,stored:localStorage.getItem('nidaro-theme'),pressed:[...document.querySelectorAll('[data-theme-choice]')].map(b=>b.getAttribute('aria-pressed')).join(',')}))()")
echo "$STATE" | grep -q '"theme":"dusk"' || fail "dusk click applies theme" "theme=dusk" "$STATE"
echo "$STATE" | grep -q '"stored":"dusk"' || fail "dusk click persists" "localStorage=dusk" "$STATE"
echo "$STATE" | grep -q '"pressed":"false,false,true"' || fail "aria-pressed moves to dusk" "false,false,true" "$STATE"

# ------------------- 4. theme survives navigation -------------------------------

chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/\"}" >/dev/null
wait_loaded
STATE=$(read_value "document.documentElement.dataset.theme")
[ "$STATE" = "\"dusk\"" ] || fail "theme survives navigation" "\"dusk\"" "$STATE"

# ------------------- 5. placeholder sections render ------------------------------

chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/shopping\"}" >/dev/null
wait_loaded
STATE=$(read_value "(()=>({h2:document.querySelector('.placeholder h2')?.textContent,icon:!!document.querySelector('.placeholder .tile svg')}))()")
echo "$STATE" | grep -q '"h2":"Shopping is on its way"' || fail "placeholder heading" "Shopping is on its way" "$STATE"
echo "$STATE" | grep -q '"icon":true' || fail "placeholder icon present" "true" "$STATE"

# ------------------- 6. meals week view renders the seeded plan ------------------

STATUS=$(await_value "fetch('/meals').then(r=>String(r.status))")
[ "$STATUS" = '"200"' ] || fail "GET /meals status" '"200"' "$STATUS"
chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/meals\"}" >/dev/null
wait_loaded
STATE=$(read_value "(()=>({placeholder:!!document.querySelector('.placeholder'),grid:!!document.querySelector('.meals-grid'),dayHeads:document.querySelectorAll('.meals-dayhead').length,todayChip:document.querySelector('.meals-cell.a-0-dinner .meals-chip__name')?.textContent}))()")
echo "$STATE" | grep -q '"placeholder":false' || fail "meals week view" "no on-its-way placeholder" "$STATE"
echo "$STATE" | grep -q '"grid":true' || fail "meals week view" "week grid renders" "$STATE"
echo "$STATE" | grep -q '"dayHeads":7' || fail "meals week view day heads" "7" "$STATE"
echo "$STATE" | grep -q '"todayChip":"Spaghetti Bolognese"' || fail "seeded chip on today" "Spaghetti Bolognese" "$STATE"

# ---------- 7. HTMX on the week grid: add a one-off, remove it again -------------

# The add form targets today's lunch cell (day index 0, slot lunch) via its
# stable grid-area class; the one-off name is per-run so a crashed earlier run
# can never satisfy the assertion.
NAME="E2E smoke $(date +%s)"
STATE=$(read_value "(()=>{const cell=document.querySelector('.meals-cell.a-0-lunch');cell.querySelector('details').open=true;cell.querySelector('input[name=name]').value='$NAME';return {open:cell.querySelector('details').open};})()")
echo "$STATE" | grep -q '"open":true' || fail "open the lunch add form" "details open" "$STATE"
read X Y <<< "$(element_center "document.querySelector('.meals-cell.a-0-lunch .meals-addbtn')")"
click_at "$X" "$Y"
STATE=$(await_value "new Promise(res=>{const t0=Date.now();(function poll(){const chip=[...document.querySelectorAll('.meals-cell.a-0-lunch .meals-chip__name')].find(n=>n.textContent==='$NAME');if(chip)return res({chip:chip.textContent});if(Date.now()-t0>5000)return res({chip:null});setTimeout(poll,100)})()})")
echo "$STATE" | grep -q "\"chip\":\"$NAME\"" || fail "one-off chip appears after HTMX add" "chip $NAME" "$STATE"
read X Y <<< "$(element_center "[...document.querySelectorAll('.meals-cell.a-0-lunch .meals-chip')].find(c=>c.querySelector('.meals-chip__name').textContent==='$NAME').querySelector('.meals-x')")"
click_at "$X" "$Y"
STATE=$(await_value "new Promise(res=>{const t0=Date.now();(function poll(){const gone=![...document.querySelectorAll('.meals-cell.a-0-lunch .meals-chip__name')].some(n=>n.textContent==='$NAME');if(gone)return res({chip:null,form:!!document.querySelector('.meals-cell.a-0-lunch .meals-add form')});if(Date.now()-t0>5000)return res({chip:'still there'});setTimeout(poll,100)})()})")
echo "$STATE" | grep -q '"chip":null' || fail "one-off chip removed again" '"chip":null' "$STATE"
echo "$STATE" | grep -q '"form":true' || fail "add form back after remove" '"form":true' "$STATE"

# ------------------- 8. dishes page renders the table ----------------------------

STATUS=$(await_value "fetch('/meals/dishes').then(r=>String(r.status))")
[ "$STATUS" = '"200"' ] || fail "GET /meals/dishes status" '"200"' "$STATUS"
chrome-agent "$INSTANCE" Page.navigate "{\"url\":\"$BASE_URL/meals/dishes\"}" >/dev/null
wait_loaded
STATE=$(read_value "(()=>({title:document.querySelector('.dishes-title')?.textContent,rows:document.querySelectorAll('.dishes-table tbody tr').length,bolognese:[...document.querySelectorAll('.dishes-cell-name')].some(c=>c.textContent.includes('Spaghetti Bolognese'))}))()")
echo "$STATE" | grep -q '"title":"Typical dishes"' || fail "dishes heading" "Typical dishes" "$STATE"
echo "$STATE" | grep -q '"rows":6' || fail "seeded dish rows" "6" "$STATE"
echo "$STATE" | grep -q '"bolognese":true' || fail "seeded dish listed" "Spaghetti Bolognese" "$STATE"

# ------------------- 9. no page exceptions or broken requests -------------------

if grep -qE 'exceptionThrown|loadingFailed' "$EVENTS"; then
  grep -E 'exceptionThrown|loadingFailed' "$EVENTS" | head -3 >&2
  fail "page raised exceptions or failed requests during the run" "clean event stream" "see events above ($EVENTS)"
fi

echo "PASS: UI shell smoke test ($BASE_URL)"
