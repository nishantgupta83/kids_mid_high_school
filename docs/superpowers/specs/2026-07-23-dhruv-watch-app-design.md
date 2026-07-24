# Dhruv's Apple Watch App — Design Spec

**Slice 5 of the `kids_mid_high_school` family school-intelligence system.**
Date: 2026-07-23. Status: design approved, pending spec review → implementation plan.

## Context

A glanceable Apple Watch surface for Dhruv (11, 6th grade, Pine Valley Middle School) that helps him stay on top of homework and his day, fed by the family dashboard's existing KV API (`/api/data`, family-code auth) that already serves events, opportunities, and the watchlist.

The value is concentrated in two daily windows — **a morning glance and an after-school glance** — because the watch is a **Family Setup** device (Dhruv wears it; it's managed from the parent's iPhone; he has no iPhone of his own) and Apple's **Schooltime** plus the school's device policy are assumed to lock it down during class. The app is tap-only (an 11-year-old won't type on a watch) and gives a small streak reward so clearing homework *feels* like something.

## Decided requirements (approved through brainstorming)

1. **Family Setup watch** → the watchOS app must be **standalone/independent** (no iOS companion on Dhruv's side); it talks to the network directly.
2. **Two-window usage** (morning + after school). Notifications must respect Schooltime — nothing buzzes during class.
3. **Interaction = tap only.** Each homework item has **✓ Done** and **Later** buttons (no typing). "Later" defers and re-buzzes after school; "Done" checks it off and feeds a **streak**.
4. **Glance + countdowns** at the top of the main screen ("next thing" + one countdown chip).
5. **Weekly-activities schedule** (parent-entered on the dashboard) is added so the "next thing" and countdowns have real, kid-relevant content (Badminton Tue/Thu 4:00, Speech Wed, Finance Mon).
6. **Write-back:** Done/Later status and the streak sync to the KV, so the parent sees Dhruv's progress on the dashboard and in the morning digest.
7. **No custom watch face** (hard Apple limitation — third parties cannot create or install native faces). Dhruv's data reaches his face via a **complication**; optionally a **shared photo/Portrait face** (Apple template + photo + complications + color) set up from the parent's iPhone for the "custom face" feel.
8. **Constraints (inherited):** free tier only; no purple; no AI/assistant branding; the API stays auth-gated (family code); first names only.

## The #1 risk — spike before building

Installing a **custom, dev-signed** watchOS app onto a **Family Setup** watch is not a well-trodden path: those watches run under a child Apple ID managed from the parent's iPhone, and Xcode sideloading to them is genuinely uncertain — it may not work at all.

Per the standing hard rule (prove device feasibility on the oldest/actual target before building on it), **Slice 0 is a throwaway "hello world" watch app** that we attempt to install on Dhruv's *actual* Family Setup watch from the Mac/Xcode.
- **Spike passes** → build the native watchOS app (Slices 1–4 below).
- **Spike fails** → pivot to a **web glance**: a tiny, phone-sized, auth-gated web page (same KV API, same family code) that Dhruv opens, and/or a shared-face complication that links to it. Same features, no App-Store/native constraint.

We do not promise the native app until Slice 0 passes.

## Dhruv-facing: the watch app

**Screen 1 — "Today"** (the morning / after-school screen):
- **Glance line:** the next thing — `Badminton · 4:00` today, or `Next: Speech · Wed` if today is clear — plus one countdown chip (`Weekend in 2 days` / `Break in 12 days`).
- **Homework list:** one row per item due today — subject/task + **✓ Done** and **Later** buttons. "Later" moves it to the bottom and schedules an after-school re-buzz; "Done" checks it off.
- **Streak line:** `4 days all done`, growing each day he clears the list. Clean number, no purple, no cartoon branding.
- **All-clear state:** `All done — nice.` when the list is empty/complete.

**Screen 2 — "This week"** (swipe): upcoming activities + school events for Dhruv, read-only, so he can see what's coming.

**Complication** (watch-face widget, feasibility-gated): `2 to do` or `Badminton 4pm` on his chosen Apple face → tap opens the app. This is the primary "glance" — visible without opening anything.

**Notifications:** two local (on-device, work offline) notifications/day — a **morning** one before school (`3 due today · Badminton 4:00`) and an **after-school** one (`2 due tomorrow`). Scheduled on the watch; Schooltime suppresses anything mid-class.

## Parent-facing: dashboard additions

- **Weekly-activities editor** on the dashboard: add/edit recurring activities (name · day(s) · time · optional place). Stored in KV (`activities:dhruv`). The watch reads it to compute today's activities and countdowns.
- **Homework progress + streak visible to the parent:** Done/Later taps write back, so the dashboard Today tab shows `Dhruv's homework: 2/3 done` and his streak, and the morning digest folds it in (`Dhruv cleared his list — 5-day streak` / `Dhruv still has 2 open`) — quiet accountability, no nagging.

## Architecture & data flow

- **Standalone SwiftUI watchOS app.** `URLSession` → `GET /api/data` with the family-code header. It computes: today's activities from the weekly schedule (day-of-week match) + one-off Dhruv events; today's homework from events with `type=homework` and `kid ∈ {dhruv, both}`.
- **Write path:** extend the existing Pages Function with an authed `PUT /api/kid` — body `{ homeworkId, date, status: "done"|"later" }` → KV key `hw:<date>:<homeworkId>`. The streak is derived from consecutive all-done days. Same family-code auth as the rest of the API.
- **Content doc** (`content:latest`) gains `weekly_activities`; the daily scan reads back Dhruv's homework status to reflect it in the dashboard and digest.
- **Complication** via the current watchOS widget API; **local notifications** scheduled on-device.
- **Family code** provisioned at build time from the Keychain into an xcconfig (gitignored — never committed), consistent with the other dev-signed apps in this workspace; dev-signed → weekly re-sign; watchOS version checked against Dhruv's actual watch model before using any version-gated API.

## Build slices (each independently useful; verify before the next)

0. **Feasibility spike** — install a hello-world watch app on Dhruv's Family Setup watch. Gate: pass → native; fail → web-glance pivot.
1. **Read-only "Today" screen** from `/api/data` — homework list + today's activities + countdowns (no write-back yet).
2. **Weekly-activities editor** on the dashboard + `activities:dhruv` KV + watch renders today's activities.
3. **Done/Later write-back + streak** — watch writes status, dashboard + digest reflect it.
4. **Complication + two daily notifications.**

## Open questions / to verify during implementation

- watchOS version on Dhruv's specific watch model (gates the complication/widget + notification APIs).
- Whether Family Setup permits third-party complications on the child's watch face (verify on-device during Slice 0/4).
- Schooltime's exact interaction with on-device local notifications (expected: suppressed during class — confirm).
- Apple Developer provisioning for a watch under a child Apple ID (may complicate signing; surfaces in Slice 0).
- Whether guardian-summary emails give homework granular enough (per-assignment + due date) to make the checklist useful, or whether the list is coarse — informs how the homework rows are worded.

## Explicitly out of scope for v1

- Dhruv adding his own homework (no typing on the watch; the list is what the scanner surfaces).
- A truly custom-drawn watch face (Apple platform limitation).
- Real-time during-class features.
- Recurring one-off-event generation from the weekly schedule into `events.json` (the watch/dashboard interpret the schedule directly; keep it a separate list).
