#!/bin/bash
# Living test for /api/roadmap. Usage: _test-roadmap.sh [BASE_URL] [CODE]
# Run against `wrangler pages dev public` on a throwaway KV (--persist-to a scratch dir).
set -e
BASE="${1:-http://localhost:8799}"
# Default code comes from the gitignored dashboard/.dev.vars, never from this file.
CODE="${2:-$(sed -n 's/^SYNC_KEY=//p' "$(dirname "$0")/../../.dev.vars" 2>/dev/null)}"
[ -n "$CODE" ] || { echo "no CODE: pass it as arg 2 or set SYNC_KEY in dashboard/.dev.vars"; exit 2; }
H=(-H "x-sync-key: $CODE" -H 'content-type: application/json')
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
put() { curl -s -X PUT "${H[@]}" -d "$1" "$BASE/api/roadmap"; }
putcode() { code -X PUT "${H[@]}" -d "$1" "$BASE/api/roadmap"; }
get() { curl -s "${H[@]}" "$BASE/api/roadmap"; }

echo "bare GET → 401";            test "$(code "$BASE/api/roadmap")" = 401
echo "wrong code GET → 401";      test "$(code -H 'x-sync-key: nope' "$BASE/api/roadmap")" = 401
echo "bare PUT → 401";            test "$(code -X PUT -H 'content-type: application/json' -d '{"id":"app:x","patch":{"status":"done"}}' "$BASE/api/roadmap")" = 401
echo "authed GET has content+state keys"; get | grep -q '"state"'; get | grep -q '"content"'

echo "agent writes content";      put '{"content":{"version":1,"applications":[{"id":"t-app","title":"Test app"}]}}' | grep -q '"ok":true'
echo "GET returns the content";   get | grep -q '"t-app"'

echo "parent sets a status";      put '{"id":"app:t-app","patch":{"status":"in_progress","note":"called them"}}' | grep -q '"ok":true'
echo "GET returns the status";    get | grep -q '"app:t-app":{[^}]*"status":"in_progress"'
echo "a second patch merges, keeping the note"
put '{"id":"app:t-app","patch":{"status":"submitted"}}' | grep -q '"ok":true'
get | grep -q '"status":"submitted"'; get | grep -q '"note":"called them"'

echo "agent content write leaves parent state alone"
put '{"content":{"version":2,"applications":[]}}' | grep -q '"ok":true'
get | grep -q '"note":"called them"'; get | grep -q '"version":2'

echo "decision choice + course list + shortlist"
put '{"id":"dec:summer-2027","patch":{"choice":"Still open","note":""}}' | grep -q '"ok":true'
put '{"id":"plan:grade11","patch":{"courses":["g11-ap-biology","g11-us-history"]}}' | grep -q '"ok":true'
put '{"id":"sum:bay-ucsc-sip","patch":{"shortlist":true}}' | grep -q '"ok":true'
get | grep -q '"g11-ap-biology"'; get | grep -q '"shortlist":true'

echo "money shortlist"
put '{"id":"mon:alabama-automatic","patch":{"shortlist":true,"note":"check SAT tier"}}' | grep -q '"ok":true'
get | grep -q '"mon:alabama-automatic"'

echo "route choice, question asked, family note"
put '{"id":"opt:uc-resident","patch":{"choice":"active","note":"first choice"}}' | grep -q '"ok":true'
put '{"id":"q:attorney-cspa","patch":{"seen":true,"note":"asked in Dec"}}' | grep -q '"ok":true'
put '{"id":"fam:stay-dependent-first","patch":{"choice":"useful"}}' | grep -q '"ok":true'
get | grep -q '"opt:uc-resident"'; get | grep -q '"q:attorney-cspa"'; get | grep -q '"fam:stay-dependent-first"'

echo "list interest mark"
put '{"id":"lst:bayarea-local-0123456789","patch":{"choice":"interested"}}' | grep -q '"ok":true'
get | grep -q '"lst:bayarea-local-0123456789"'

echo "custom item add then remove"
put '{"id":"custom:abc123","patch":{"item":{"title":"New program","deadline":"2027-03-01","track":"research","link":"https://example.org/p"}}}' | grep -q '"ok":true'
get | grep -q '"New program"'
put '{"id":"custom:abc123","patch":{"deleted":true}}' | grep -q '"ok":true'
get | grep -q '"deleted":true'; get | grep -q '"New program"'   # removal is a flag; the record stays

echo "bad status → 400";          test "$(putcode '{"id":"app:t-app","patch":{"status":"winning"}}')" = 400
echo "bad id → 400";              test "$(putcode '{"id":"BAD ID","patch":{"status":"done"}}')" = 400
echo "unknown prefix → 400";      test "$(putcode '{"id":"opp:t-app","patch":{"status":"done"}}')" = 400
echo "unknown field → 400";       test "$(putcode '{"id":"app:t-app","patch":{"admin":true}}')" = 400
LONG=$(head -c 1300 /dev/zero | tr '\0' 'x'); LONGBODY='{"id":"app:t-app","patch":{"note":"'"$LONG"'"}}'
echo "long note → 400";           R=$(putcode "$LONGBODY"); test "$R" = 400
echo "script link → 400";         test "$(putcode '{"id":"custom:abc124","patch":{"item":{"title":"X","link":"javascript:alert(1)"}}}')" = 400
echo "bad date → 400";            test "$(putcode '{"id":"custom:abc124","patch":{"item":{"title":"X","deadline":"March"}}}')" = 400
echo "impossible date → 400";     test "$(putcode '{"id":"custom:abc124","patch":{"item":{"title":"X","deadline":"2027-02-30"}}}')" = 400
echo "item on a non-custom id → 400"; test "$(putcode '{"id":"app:t-app","patch":{"item":{"title":"X"}}}')" = 400
echo "content + id together → 400";   test "$(putcode '{"content":{"a":1},"id":"app:t-app","patch":{"status":"done"}}')" = 400
echo "content not an object → 400";   test "$(putcode '{"content":"hello"}')" = 400
echo "empty body → 400";          test "$(putcode '{}')" = 400
echo "broken json → 400";         test "$(putcode '{nope')" = 400
echo "rejected writes changed nothing"; get | grep -q '"status":"submitted"'

echo "existing endpoints still answer"; test "$(code "${H[@]}" "$BASE/api/pipeline")" = 200; test "$(code "${H[@]}" "$BASE/api/data")" = 200
echo "ALL PASS"
