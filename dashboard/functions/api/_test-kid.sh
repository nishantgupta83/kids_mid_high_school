#!/bin/bash
# Living test for /api/kid. Usage: _test-kid.sh [BASE_URL] [CODE]
set -e
BASE="${1:-http://localhost:8788}"; CODE="${2:-gupta-family}"
D=2026-09-01
echo "bare 401"; test "$(curl -s -o /dev/null -w '%{http_code}' $BASE/api/kid)" = 401
echo "mark done"; curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d "{\"date\":\"$D\",\"homeworkId\":\"evt-hw-1\",\"status\":\"done\"}" $BASE/api/kid | grep -q '"ok":true'
echo "GET reflects"; curl -s -H "x-sync-key: $CODE" "$BASE/api/kid?date=$D" | grep -q '"evt-hw-1"'
# Streak sequence (real weekdays): 09-01 Tue, 09-02 Wed, 09-03 Thu, 09-04 Fri, 09-05 Sat, 09-06 Sun, 09-07 Mon, 09-10 Thu
tick(){ curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d "{\"date\":\"$1\",\"allDone\":true}" $BASE/api/kid >/dev/null; }
count(){ curl -s -H "x-sync-key: $CODE" "$BASE/api/kid?date=$1" | /usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin)['streak']['count'])"; }
echo "first tick → count 1"; tick 2026-09-01; test "$(count 2026-09-01)" = 1
echo "same-day idempotent → 1"; tick 2026-09-01; test "$(count 2026-09-01)" = 1
echo "consecutive day → 2"; tick 2026-09-02; test "$(count 2026-09-02)" = 2
echo "skipped weekday (Thu 09-03) resets → 1"; tick 2026-09-04; test "$(count 2026-09-04)" = 1
echo "weekend bridged (Fri→Mon) → 2"; tick 2026-09-07; test "$(count 2026-09-07)" = 2
echo "multi-day gap resets → 1"; tick 2026-09-10; test "$(count 2026-09-10)" = 1
echo "backdated tick ignored (still 1)"; tick 2026-09-08; test "$(count 2026-09-10)" = 1
echo "bad status → 400"  # capture RC in its own assignment — nesting escaped-quote JSON inside test "$(...)" mis-parses in bash
RC=$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d "{\"date\":\"$D\",\"homeworkId\":\"x\",\"status\":\"nope\"}" $BASE/api/kid)
test "$RC" = 400
echo "ALL PASS"
