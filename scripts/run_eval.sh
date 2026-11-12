#!/usr/bin/env bash
# Run a failure-suite eval to the end without losing work.
#
#   scripts/run_eval.sh <results.json> [chaos_suite args...]
#
# - Every finished run is saved atomically to <results.json>; restarting with the same file resumes it.
# - Usage stop (80% of the 5-hour or weekly window): waits until the window resets, then resumes.
#   Waits longer than MAX_WAIT_S (default 6 h, i.e. the weekly window) end the script; rerun it later.
# - Paid extra usage or an unclean CLI environment: stops for good (exit 2).
# - Crash (portal or database down, killed process): restarts the portal/database and resumes; gives up after
#   3 crashes in a row without a new saved run.
# - Extraction always runs fresh (no cache), so every number comes from this run.
set -uo pipefail
cd "$(dirname "$0")/.."

OUT="${1:?usage: scripts/run_eval.sh <results.json> [chaos_suite args...]}"
shift
export LPA_NO_EXTRACT_CACHE=1
BASE="${PORTAL_BASE_URL:-http://127.0.0.1:8061}"
MAX_WAIT_S="${MAX_WAIT_S:-21600}"
LOG="${OUT%.json}.log"
mkdir -p "$(dirname "$OUT")"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
saved() { [ -f "$OUT" ] && python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$OUT" || echo 0; }

ensure_services() {
  if ! nc -z 127.0.0.1 55434 2>/dev/null; then
    log "database down: starting it"
    scripts/dev_db.sh up >>"$LOG" 2>&1
  fi
  if ! curl -sf "$BASE/healthz" >/dev/null; then
    log "portal server down: starting it"
    nohup uv run uvicorn legacy_portal.portals.app:app --port 8061 >>"${OUT%.json}.portal.log" 2>&1 &
    for _ in $(seq 30); do curl -sf "$BASE/healthz" >/dev/null && break; sleep 1; done
  fi
}

crashes=0
while true; do
  ensure_services
  before=$(saved)
  log "start/resume: $before runs saved in $OUT"
  uv run python -m legacy_portal.chaos_suite --out "$OUT" "$@" 2>&1 | tee -a "$LOG"
  code=${PIPESTATUS[0]}
  after=$(saved)
  if [ "$code" -eq 0 ]; then
    log "finished: $after runs in $OUT"
    exit 0
  fi
  if [ "$code" -eq 75 ]; then
    retry_at=$(grep -o 'EVAL_RETRY_AT=[0-9]*' "$LOG" | tail -1 | cut -d= -f2)
    wait_s=$(( retry_at - $(date +%s) + 120 ))
    if [ "$wait_s" -gt "$MAX_WAIT_S" ]; then
      log "usage stop; window resets at $(date -r "$retry_at"), too far to wait. Rerun this script after that."
      exit 75
    fi
    log "usage stop at $after runs; waiting $(( wait_s / 60 )) min (until $(date -r $(( retry_at + 120 ))))"
    sleep "$(( wait_s > 0 ? wait_s : 60 ))"
    crashes=0
    continue
  fi
  if [ "$code" -eq 2 ]; then
    log "stopped for good (extra usage or unclean environment): see the log. $after runs saved."
    exit 2
  fi
  if [ "$after" -gt "$before" ]; then crashes=0; else crashes=$((crashes + 1)); fi
  if [ "$crashes" -ge 3 ]; then
    log "3 crashes in a row without progress (exit $code); giving up. $after runs saved; rerun to resume."
    exit "$code"
  fi
  log "crash (exit $code) at $after runs; restarting in 60 s"
  sleep 60
done
