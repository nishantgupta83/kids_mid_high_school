#!/bin/bash
# Living test for /api/activities. Usage: _test-activities.sh [BASE_URL] [CODE]
set -e
BASE="${1:-http://localhost:8788}"; CODE="${2:-gupta-family}"
echo "bare GET → 401"; test "$(curl -s -o /dev/null -w '%{http_code}' $BASE/api/activities)" = 401
echo "authed empty GET → {activities:[]}"; curl -s -H "x-sync-key: $CODE" $BASE/api/activities | grep -q '"activities"'
echo "PUT valid"; curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' \
  -d '{"activities":[{"id":"act-badminton","name":"Badminton","days":[2,4],"time":"16:00","place":"Gym"}]}' $BASE/api/activities | grep -q '"ok":true'
echo "GET returns it"; curl -s -H "x-sync-key: $CODE" $BASE/api/activities | grep -q '"act-badminton"'
echo "PUT bad id → 400"; test "$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d '{"activities":[{"id":"BAD ID","name":"x","days":[9],"time":"25:00"}]}' $BASE/api/activities)" = 400
echo "ALL PASS"
