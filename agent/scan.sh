#!/bin/bash
# Daily school-intelligence scan orchestrator. Run by launchd (7:00 + 12:00 catch-up)
# or manually: scan.sh [--force] [--weekly]
#
# Degraded-mode philosophy: individual step failures set flags, the digest still
# goes out. Only setup errors (missing secrets) are fatal.
set -u
export TZ=America/Los_Angeles

REPO="/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
AGENT="$REPO/agent"
PY=/usr/bin/python3
LOCAL="$REPO/data/local"
LOCK="$LOCAL/scan.lock"
START_TS=$(date +%s)
TODAY=$(date +%F)

FORCE=0; WEEKLY=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --weekly) WEEKLY=1 ;;
  esac
done

logln() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; mkdir -p "$REPO/logs/runs"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$REPO/logs/runs/$TODAY.log"; }

# ---- STEP 0: guard + lock -------------------------------------------------
if [ "$FORCE" -eq 0 ]; then
  ALREADY=$($PY -c "
import json
try:
    r = json.load(open('$REPO/data/state/last_run.json'))
    print('yes' if r.get('date') == '$TODAY' and r.get('ok') and r.get('mode') in ('full', 'quiet') else 'no')
except Exception:
    print('no')")
  if [ "$ALREADY" = "yes" ]; then
    logln "STEP 0 guard SKIP already ran successfully today"
    exit 0
  fi
fi
mkdir -p "$LOCAL"
if ! mkdir "$LOCK" 2>/dev/null; then
  # Stale lock (>2h) gets removed; otherwise another run is live.
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then
    logln "STEP 0 guard WARN removing stale lock"
    rmdir "$LOCK" 2>/dev/null || rm -rf "$LOCK"
    mkdir "$LOCK" || { logln "STEP 0 guard FAIL cannot lock"; exit 1; }
  else
    logln "STEP 0 guard SKIP another scan is running"
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
logln "STEP 0 guard OK (force=$FORCE weekly=$WEEKLY)"

# ---- STEP 1: network readiness (retry loop, not sleep-and-hope) -----------
NET_OK=0
for i in 1 2 3 4 5 6; do
  if /usr/bin/curl -s --max-time 10 -o /dev/null https://www.gstatic.com/generate_204; then NET_OK=1; break; fi
  logln "STEP 1 network retry $i"
  sleep $(( i * 10 ))
done
if [ "$NET_OK" -eq 0 ]; then
  logln "STEP 1 network FAIL — no connectivity, exiting (launchd will re-fire)"
  exit 75
fi
logln "STEP 1 network OK"

# ---- STEP 2: secrets ------------------------------------------------------
if ! /usr/bin/security find-generic-password -s school-intel-gmail -w >/dev/null 2>&1; then
  logln "STEP 2 secrets FAIL — Keychain item 'school-intel-gmail' missing (see docs/runbook.md Gate A)"
  exit 1
fi
logln "STEP 2 secrets OK"

# ---- STEP 3: KV status read-back (slice 2 — stubbed via config) -----------
KV_ENABLED=$($PY -c "import json;print(str(json.load(open('$AGENT/config.json'))['features']['kv_enabled']).lower())")
if [ "$KV_ENABLED" = "true" ]; then
  $PY "$AGENT/push_content.py" --pull || logln "STEP 3 kv-readback WARN failed, using last-known statuses"
  logln "STEP 3 kv-readback OK"
else
  logln "STEP 3 kv-readback SKIP (kv_enabled=false)"
fi

# ---- STEP 4: email pull ---------------------------------------------------
EMAIL_OK=1
if ! $PY "$AGENT/fetch_email.py"; then
  EMAIL_OK=0
  logln "STEP 4 email FAIL — continuing registry-only"
  echo '{"messages": []}' > "$LOCAL/new_email.json"
fi
[ "$EMAIL_OK" -eq 1 ] && logln "STEP 4 email OK"

# ---- STEP 5: registry diff ------------------------------------------------
$PY "$AGENT/fetch_sources.py" || logln "STEP 5 sources WARN (per-source failures logged)"
logln "STEP 5 sources OK"

# ---- STEP 6: bundle (rc 3 = quiet day) ------------------------------------
MODE="full"
$PY "$AGENT/build_bundle.py"
BUNDLE_RC=$?
if [ "$BUNDLE_RC" -eq 3 ]; then
  MODE="quiet"
  logln "STEP 6 bundle QUIET"
elif [ "$BUNDLE_RC" -ne 0 ]; then
  MODE="degraded-no-llm"
  logln "STEP 6 bundle FAIL — degraded"
else
  logln "STEP 6 bundle OK"
fi

# ---- STEP 7+8: LLM + merge ------------------------------------------------
# No separate preflight: llm_call.py owns the timeout, and a failed call lands in
# the same degraded path a failed preflight would.
if [ "$MODE" = "full" ]; then
  if $PY "$AGENT/llm_call.py" --mode daily \
      --prompt "$AGENT/prompts/scan_prompt.md" \
      --input "$LOCAL/scan_input.json" \
      --output "$LOCAL/llm_output.json"; then
    logln "STEP 7 llm OK"
    if $PY "$AGENT/merge_results.py" --llm-output "$LOCAL/llm_output.json"; then
      logln "STEP 8 merge OK"
      if ! $PY "$REPO/scripts/validate_data.py" > "$LOCAL/validate_out.txt" 2>&1; then
        logln "STEP 8 validate FAIL — rolling back data/ via git"
        git -C "$REPO" checkout -- data/
        MODE="degraded-no-llm"
      fi
    else
      logln "STEP 8 merge FAIL — cursors untouched, degraded"
      MODE="degraded-no-llm"
    fi
  else
    logln "STEP 7 llm FAIL — degraded"
    MODE="degraded-no-llm"
  fi
fi
if [ "$MODE" != "full" ]; then
  # Quiet/degraded: promote only safe checkpoints (unchanged sources; cursor iff no messages).
  $PY "$AGENT/merge_results.py" --finalize-only || logln "STEP 8 finalize-only WARN"
fi

# ---- STEP 8c: WEEKLY discovery (Sunday, or --weekly) ----------------------
# Fully isolated from the email scan: web-only LLM call, own schema, proposals only.
# On a discovery validation failure we restore ONLY the two files discovery touches
# (events.json, sources_proposed.json) — never a tree-wide checkout that would wipe
# the successful daily merge that already ran at step 8.
if [ "$WEEKLY" -eq 1 ] || [ "$(date +%u)" = "7" ]; then
  $PY "$AGENT/build_discovery.py"
  if $PY "$AGENT/llm_call.py" --mode discovery \
      --prompt "$AGENT/prompts/discovery_prompt.md" \
      --input "$LOCAL/discovery_input.json" \
      --output "$LOCAL/discovery_output.json"; then
    cp "$REPO/data/events.json" "$LOCAL/events.pre8c.json"
    cp "$REPO/data/sources_proposed.json" "$LOCAL/proposed.pre8c.json"
    if $PY "$AGENT/merge_discovery.py" --llm-output "$LOCAL/discovery_output.json"; then
      if $PY "$REPO/scripts/validate_data.py" >/dev/null 2>&1; then
        logln "STEP 8c discovery OK"
      else
        logln "STEP 8c discovery validate FAIL — restoring events.json + sources_proposed.json only"
        cp "$LOCAL/events.pre8c.json" "$REPO/data/events.json"
        cp "$LOCAL/proposed.pre8c.json" "$REPO/data/sources_proposed.json"
      fi
    else
      logln "STEP 8c discovery merge FAIL (skipped)"
    fi
  else
    logln "STEP 8c discovery LLM FAIL (skipped)"
  fi
else
  logln "STEP 8c discovery SKIP (not Sunday)"
fi

# ---- STEP 9: (KV push moved after finalize so health reflects THIS run) ---
logln "STEP 9 kv-push deferred to post-finalize"

# ---- STEP 9b: Dhruv homework status for the digest (events.json now current) ---
if [ "$KV_ENABLED" = "true" ]; then
  $PY "$AGENT/push_content.py" --kidstatus || logln "STEP 9b kidstatus WARN"
fi

# ---- STEP 10: digest ------------------------------------------------------
DIGEST_MODE="$MODE"
[ "$MODE" = "quiet" ] && DIGEST_MODE="quiet"
$PY "$AGENT/send_digest.py" --mode "$DIGEST_MODE"
DIGEST_RC=$?
DIGEST_DEFERRED=0
if [ "$DIGEST_RC" -eq 0 ]; then
  logln "STEP 10 digest OK"
elif [ "$DIGEST_RC" -eq 4 ]; then
  DIGEST_DEFERRED=1
  logln "STEP 10 digest DEFERRED (outside delivery window) — day NOT marked successful"
else
  logln "STEP 10 digest FAIL (archived locally; next digest reports the gap)"
fi

# ---- STEP 11: finalize ----------------------------------------------------
DURATION=$(( $(date +%s) - START_TS ))
OK="true"
[ "$MODE" = "degraded-no-llm" ] && OK="false"
[ "$DIGEST_DEFERRED" -eq 1 ] && OK="false"
# A hard digest failure (rc not 0 or 4) leaves the day not-successful so the noon
# catch-up trigger re-fires and retries delivery.
[ "$DIGEST_RC" -ne 0 ] && [ "$DIGEST_RC" -ne 4 ] && OK="false"
$PY "$AGENT/finalize_run.py" --mode "$MODE" --ok "$OK" --duration "$DURATION" \
  --step "email=$EMAIL_OK" --step "mode=$MODE" >/dev/null
logln "STEP 11 finalize OK mode=$MODE duration=${DURATION}s"

# ---- STEP 11b: KV push (health every run; content only when changed) ------
if [ "$KV_ENABLED" = "true" ]; then
  if $PY "$AGENT/push_content.py" --push; then
    logln "STEP 11b kv-push OK"
  else
    logln "STEP 11b kv-push WARN failed (dashboard may show stale)"
  fi
fi

# ---- STEP 12: commit state (PII lint gates it) ----------------------------
if $PY "$REPO/scripts/validate_data.py" >/dev/null 2>&1; then
  git -C "$REPO" add data/sources.json data/events.json data/opportunities.json \
    data/watchlist.json data/sources_proposed.json data/summer_apps.json \
    data/state/last_run.json data/state/email_cursor.json
  if ! git -C "$REPO" diff --cached --quiet; then
    git -C "$REPO" commit -q -m "scan $TODAY mode=$MODE" && logln "STEP 12 commit OK"
  else
    logln "STEP 12 commit SKIP no changes"
  fi
else
  logln "STEP 12 commit BLOCKED — validator/PII lint failed (see $LOCAL/validate_out.txt)"
fi

# ---- STEP 13: prune local artifacts ---------------------------------------
find "$REPO/data/snapshots/email" -name '*.json' -mtime +30 -delete 2>/dev/null
find "$REPO/data/digests" -type f -mtime +90 -delete 2>/dev/null
find "$REPO/logs/runs" -name '*.log' -mtime +60 -delete 2>/dev/null
logln "STEP 13 prune OK — run complete"
exit 0
