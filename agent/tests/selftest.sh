#!/bin/bash
# Known-BAD fixture battery: the diff detector and the merge fail-closed path.
# Run: bash agent/tests/selftest.sh   (exit 0 = all pass)
set -u
REPO="/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
PY=/usr/bin/python3
FAIL=0

echo "== 1. diff detector fixtures =="
if ! $PY "$REPO/agent/fetch_sources.py" --selftest; then FAIL=1; fi

echo "== 2. truncated LLM output must be rejected wholesale =="
BEFORE=$(git -C "$REPO" status --porcelain data/ | wc -l | tr -d ' ')
if $PY "$REPO/agent/merge_results.py" --llm-output "$REPO/agent/tests/fixtures/llm_output_truncated.json" 2>/dev/null; then
  echo "SELFTEST FAIL: truncated output was accepted (exit 0)"; FAIL=1
else
  echo "ok: truncated envelope rejected (nonzero exit)"
fi
AFTER=$(git -C "$REPO" status --porcelain data/ | wc -l | tr -d ' ')
if [ "$BEFORE" != "$AFTER" ]; then
  echo "SELFTEST FAIL: data/ was modified by a rejected envelope"; FAIL=1
else
  echo "ok: data/ untouched by rejected envelope"
fi

echo "== 3. one bad item quarantines, good item still merges (dry-run) =="
OUT=$($PY "$REPO/agent/merge_results.py" --llm-output "$REPO/agent/tests/fixtures/llm_output_one_bad_item.json" --dry-run)
echo "$OUT"
echo "$OUT" | grep -q '"new_opportunities": 1' || { echo "SELFTEST FAIL: good item not merged"; FAIL=1; }
echo "$OUT" | grep -q '"quarantined": 1' || { echo "SELFTEST FAIL: bad item not quarantined"; FAIL=1; }

echo "== 4. digest grid + skip rules =="
if ! $PY "$REPO/scripts/test_digest.py"; then FAIL=1; fi

if [ "$FAIL" -eq 0 ]; then
  echo "SELFTEST: ALL PASS"
else
  echo "SELFTEST: FAILURES PRESENT"
fi
exit $FAIL
