# Runbook — Family School-Intelligence System

## One-time setup (user actions)

### Gate A — Gmail app password (blocks email ingestion + digest sending)
1. Go to https://myaccount.google.com/apppasswords (requires 2-Step Verification on nishugupta@gmail.com).
2. Create an app password named `school-intel`.
3. Store it in the Keychain (paste the 16-char password, spaces optional):
   ```
   security add-generic-password -a nishugupta@gmail.com -s school-intel-gmail -w '<app-password>'
   ```
4. Verify: `security find-generic-password -s school-intel-gmail -w | wc -c` → non-zero.

### Gate C — launchd bootstrap (after Gate A and a successful manual run)
```
cp /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/agent/launchd/com.nishant.school-intel.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nishant.school-intel.plist
launchctl kickstart -k gui/$(id -u)/com.nishant.school-intel
```
⚠ **Full Disk Access (TCC):** the repo lives under ~/Documents, so the first launchd run may hit EPERM (Control Panel's agent died this exact way on this Mac, 2026-07-21). If `logs/launchd.err` shows "Operation not permitted": System Settings → Privacy & Security → Full Disk Access → add `/bin/bash` (or grant when prompted), then kickstart again.

### Slice 2 — DONE 2026-07-22
- Dashboard LIVE: https://school-compass-anq.pages.dev (project `school-compass`, KV `FAMILY_OPS` 4d1cbb0d…). Gate E dissolved (agent uses the authed API, no CF token). Family code: Keychain `school-intel-family-code` — read it with `security find-generic-password -w -s school-intel-family-code`; enter once per browser/phone.

### Slice 3 — DONE 2026-07-22
- Class Companion LIVE: https://ridhi-class-companion.pages.dev (project `ridhi-class-companion`). 6 courses, 41 units, skills-first study guides + links out; noindex; PWA-installable (home-screen). NO auth (public but noindex + unguessable + no PII — it's generic study guidance, not personal data). Validator: `scripts/validate_companion.py`. Ridhi-clean verified (word-boundary grep = 0). Content authored from public frameworks — skim English-10 book list + Chem unit order for teacher-specific accuracy.

## Daily operations
- Manual run: `bash agent/scan.sh --force`
- Dry-run the digest: `/usr/bin/python3 agent/send_digest.py --mode full --dry-run`
- Logs: `logs/runs/<date>.log` (pipeline), `logs/launchd.{out,err}` (launchd)
- Health: the digest footer shows emails scanned / sources changed / failing sources. A degraded morning run (LLM failure) is retried automatically by the noon trigger — inputs are never lost (cursors only advance after a successful merge), and the sent-marker prevents duplicate emails.

## Monthly manual checklist (login-gated sources the scanner can't see)
- Kaiser Samaritan portal: https://kpvolunteer.samaritan.com/custom/511/organization_details/636 (teen roles 16-17)
- Vitalant volunteer portal: https://vitalant.volunteerportal.org/
- SanRamonVolunteers.com (city listings behind account)

## School-year actions that go through humans
- **SRMC junior volunteer:** Ridhi visits the Cal High College & Career Center counselor early in the school year (watchlist alerts from Aug 20).
- **PSAT:** register by Sep 20 via the school link; accommodations by Aug 17.

## Recovery
- Restore state after a bad merge: `git -C <repo> checkout -- data/` (committed state is the rollback truth; scan.sh does this automatically when the validator fails post-merge).
- Rotate the Gmail app password: delete at myaccount.google.com/apppasswords, create new, re-run the `security add-generic-password` command with `-U` to update.
- Quarantined LLM items: review `data/local/quarantine.json` (gitignored; may contain raw email text — never commit).
- Re-baseline a source after fixing its URL: edit `data/sources.json` — set `scan.last_hash` to null and `next_check_date` to today.
