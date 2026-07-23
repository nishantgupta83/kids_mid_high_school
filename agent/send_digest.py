#!/usr/bin/env python3
"""Build and send the morning digest email. Sends EVERY day (short on quiet days).

Health is derived from run artifacts (new_email.json, changed_sources.json,
sources_updates.candidate.json, merge_summary.json) — no extra plumbing.

At-least-once semantics: outbox marker before SMTP, sent marker (+ stable
Message-ID) after accept. A crash in between can duplicate one email; the stable
Message-ID makes duplicates threadable. Already-sent guard checks the sent marker.

Usage: send_digest.py [--mode full|degraded-no-llm|quiet] [--force] [--dry-run]
"""
import argparse
import datetime
import html
import json
import os
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import read_json, write_text
from lib.keychain import get_secret
from lib.runlog import log

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
DATA = os.path.join(REPO, "data")
LOCAL = os.path.join(DATA, "local")

# Palette (no purple): paper/ink + sage/teal/coral/amber
C = {"paper": "#FBF7EE", "ink": "#2A2A25", "soft": "#6B6B60", "sage": "#4E7A5C",
     "teal": "#2F6F6A", "coral": "#C96F4A", "amber": "#B98A2F", "sky": "#4A7BA6",
     "card": "#FFFFFF", "line": "#E8E2D4"}
KID_COLOR = {"ridhi": C["teal"], "dhruv": C["amber"], "both": C["sage"], "family": C["sage"]}


def kid_badge(kid):
    label = {"ridhi": "Ridhi", "dhruv": "Dhruv", "both": "Both", "family": "Family"}[kid]
    return (f'<span style="background:{KID_COLOR[kid]};color:#fff;border-radius:10px;'
            f'padding:1px 8px;font-size:11px;font-weight:bold">{label}</span>')


def within_window(cfg, now):
    start = datetime.time.fromisoformat(cfg["delivery_window"]["start"])
    end = datetime.time.fromisoformat(cfg["delivery_window"]["end"])
    return start <= now.time() <= end


def collect(today):
    events = read_json(os.path.join(DATA, "events.json"), {"events": []})["events"]
    opps = read_json(os.path.join(DATA, "opportunities.json"), {"opportunities": []})["opportunities"]
    watch = read_json(os.path.join(DATA, "watchlist.json"), {"watchlist": []})["watchlist"]
    summary = read_json(os.path.join(LOCAL, "merge_summary.json"), {})
    if summary.get("date") != today.isoformat():
        summary = {}
    active = [e for e in events if e["status"] == "active"]
    horizon = today + datetime.timedelta(days=14)
    week = today + datetime.timedelta(days=7)

    action_needed = sorted(
        (e for e in active if e.get("action") and e["action"].get("due")
         and e["action"]["due"] <= horizon.isoformat()),
        key=lambda e: e["action"]["due"])
    this_week = sorted((e for e in active if today.isoformat() <= e["date"] < week.isoformat()),
                       key=lambda e: (e["date"], e.get("time") or ""))
    # Anything still status "new" from the last 7 days keeps appearing until the
    # family moves it (discuss/applied/passed) — seeds included on day one.
    fresh_cutoff = (today - datetime.timedelta(days=7)).isoformat()
    new_discoveries = [o for o in opps if o["pipeline"]["status"] == "new"
                       and o["provenance"]["first_seen"] >= fresh_cutoff]

    alerts = []
    for w in watch:
        if w["state"] not in ("waiting", "window_open"):
            continue
        for field, verb in (("expected_open", "opens"), ("hard_deadline", "DEADLINE")):
            d = w.get(field)
            if not d:
                continue
            days = (datetime.date.fromisoformat(d) - today).days
            if days in w.get("alert_days_before", [14, 7, 1]) or days == 0:
                alerts.append({"title": w["title"], "verb": verb, "date": d, "days": days, "kid": w["kid"]})
        if w.get("check_from") == today.isoformat():
            alerts.append({"title": w["title"], "verb": "watching starts", "date": w["check_from"], "days": 0, "kid": w["kid"]})

    # Proposed sources awaiting the parent's approve/dismiss (weekly discovery output).
    proposed = [p for p in read_json(os.path.join(DATA, "sources_proposed.json"), {"proposals": []})["proposals"]
                if p.get("state", "pending") == "pending"]

    return {"action_needed": action_needed, "this_week": this_week,
            "new_discoveries": new_discoveries, "watchlist_alerts": alerts,
            "digest_notes": summary.get("digest_notes", []),
            "other_items": summary.get("other_items", []),
            "proposed_sources": proposed,
            "quarantined": summary.get("quarantined", 0)}


def derive_health(mode):
    new_email = read_json(os.path.join(LOCAL, "new_email.json"), {"messages": []})
    changed = read_json(os.path.join(LOCAL, "changed_sources.json"), {"changed": []})
    cand = read_json(os.path.join(LOCAL, "sources_updates.candidate.json"), {"updates": {}})
    failing = [sid for sid, u in cand.get("updates", {}).items() if u.get("consecutive_failures", 0) > 0]
    return {"mode": mode, "emails_scanned": len(new_email.get("messages", [])),
            "sources_checked": len(cand.get("updates", {})),
            "sources_changed": len(changed.get("changed", [])), "sources_failing": failing}


def fmt_date(d):
    return datetime.date.fromisoformat(d).strftime("%a %b %-d")


def render_html(today, sections, health, degraded_raw):
    def sec(title, color, inner):
        return (f'<div style="margin:18px 0 6px;font-family:Georgia,serif;font-size:16px;'
                f'font-weight:bold;color:{color}">{title}</div>{inner}')

    def row(content):
        return (f'<div style="background:{C["card"]};border:1px solid {C["line"]};border-radius:8px;'
                f'padding:8px 12px;margin:6px 0;font-size:14px;color:{C["ink"]}">{content}</div>')

    parts = []
    if sections["digest_notes"]:
        parts.append(sec("Highlights", C["sage"], "".join(
            row(html.escape(n)) for n in sections["digest_notes"])))
    if sections["action_needed"]:
        parts.append(sec("Action needed", C["coral"], "".join(
            row(f'{kid_badge(e["kid"])} <b>{html.escape(e["action"]["what"])}</b> — '
                f'{html.escape(e["title"])} <span style="color:{C["coral"]};font-weight:bold">'
                f'due {fmt_date(e["action"]["due"])}</span>')
            for e in sections["action_needed"])))
    if sections["this_week"]:
        parts.append(sec("This week", C["teal"], "".join(
            row(f'<span style="color:{C["soft"]}">{fmt_date(e["date"])}</span> '
                f'{kid_badge(e["kid"])} {html.escape(e["title"])}'
                + (f' <span style="color:{C["soft"]}">{e["time"]}</span>' if e.get("time") else ""))
            for e in sections["this_week"])))
    if sections["new_discoveries"]:
        parts.append(sec("New finds", C["sage"], "".join(
            row(f'{kid_badge(o["kid"])} <b>{html.escape(o["title"])}</b> — {html.escape(o["org"])}'
                f'<br><span style="color:{C["soft"]}">{html.escape(o["eligibility"]["reason"])}'
                + (f' · {html.escape(o["notes"])}' if o.get("notes") else "") + "</span>"
                + (f'<br><a href="{html.escape(o["url"])}" style="color:{C["teal"]}">details</a>'
                   if o.get("url") else f'<br><span style="color:{C["soft"]}">from a school email</span>'))
            for o in sections["new_discoveries"])))
    if sections["watchlist_alerts"]:
        parts.append(sec("Coming windows", C["amber"], "".join(
            row(f'{kid_badge(a["kid"])} {html.escape(a["title"])} — {a["verb"]} '
                f'{fmt_date(a["date"])} ({a["days"]}d)')
            for a in sections["watchlist_alerts"])))
    if sections.get("proposed_sources"):
        parts.append(sec("New sources to approve", C["sky"], "".join(
            row(f'{kid_badge(p["kid"])} <b>{html.escape(p["name"])}</b>'
                f'<br><span style="color:{C["soft"]}">{html.escape(p.get("why",""))}</span>'
                f'<br><span style="color:{C["soft"]}">Approve or dismiss on the dashboard Watchlist tab.</span>')
            for p in sections["proposed_sources"])))
    if sections.get("other_items"):
        parts.append(sec("Other (noticed, worth a glance)", C["soft"], "".join(
            row(f'{kid_badge(o.get("kid","family"))} <span style="color:{C["soft"]}">{html.escape(o["title"])}</span>')
            for o in sections["other_items"])))
    if degraded_raw:
        parts.append(sec("Needs a look (summary unavailable today)", C["coral"], "".join(
            row(html.escape(line)) for line in degraded_raw)))
    if sections["quarantined"]:
        parts.append(row(f'<span style="color:{C["soft"]}">{sections["quarantined"]} item(s) '
                         f'quarantined for review (see data/local/quarantine.json)</span>'))
    if not parts:
        parts.append(row("Quiet day — nothing new. Full picture is on the dashboard."))

    failing = ", ".join(health["sources_failing"]) if health["sources_failing"] else "none"
    footer = (f'<div style="margin-top:20px;padding-top:10px;border-top:1px solid {C["line"]};'
              f'font-size:11px;color:{C["soft"]}">scan {health["mode"]} · '
              f'{health["emails_scanned"]} emails · {health["sources_checked"]} sources checked · '
              f'{health["sources_changed"]} changed · failing: {failing}</div>')

    return (f'<body style="margin:0;background:{C["paper"]};padding:20px">'
            f'<div style="max-width:640px;margin:0 auto;font-family:-apple-system,Helvetica,Arial,sans-serif">'
            f'<div style="font-family:Georgia,serif;font-size:20px;color:{C["sage"]};font-weight:bold">'
            f'School Intel</div>'
            f'<div style="font-size:13px;color:{C["soft"]}">{today.strftime("%A, %B %-d, %Y")}</div>'
            + "".join(parts) + footer + "</div></body>")


def render_text(today, sections, health, degraded_raw):
    lines = [f"SCHOOL INTEL — {today.strftime('%A, %B %-d, %Y')}", ""]
    for n in sections["digest_notes"]:
        lines.append(f"* {n}")
    if sections["action_needed"]:
        lines += ["", "ACTION NEEDED:"]
        lines += [f"  [{e['kid']}] {e['action']['what']} — {e['title']} (due {e['action']['due']})"
                  for e in sections["action_needed"]]
    if sections["this_week"]:
        lines += ["", "THIS WEEK:"]
        lines += [f"  {e['date']} [{e['kid']}] {e['title']}" for e in sections["this_week"]]
    if sections["new_discoveries"]:
        lines += ["", "NEW FINDS:"]
        lines += [f"  [{o['kid']}] {o['title']} — {o['org']} ({o.get('url') or 'from a school email'})"
                  for o in sections["new_discoveries"]]
    if sections["watchlist_alerts"]:
        lines += ["", "COMING WINDOWS:"]
        lines += [f"  [{a['kid']}] {a['title']} — {a['verb']} {a['date']} ({a['days']}d)"
                  for a in sections["watchlist_alerts"]]
    if sections.get("proposed_sources"):
        lines += ["", "NEW SOURCES TO APPROVE (dashboard Watchlist tab):"]
        lines += [f"  [{p['kid']}] {p['name']} — {p.get('why','')}" for p in sections["proposed_sources"]]
    if sections.get("other_items"):
        lines += ["", "OTHER (noticed, worth a glance):"]
        lines += [f"  [{o.get('kid','family')}] {o['title']}" for o in sections["other_items"]]
    if degraded_raw:
        lines += ["", "NEEDS A LOOK (summary unavailable):"] + [f"  {l}" for l in degraded_raw]
    if len(lines) <= 2:
        lines.append("Quiet day — nothing new.")
    failing = ", ".join(health["sources_failing"]) or "none"
    lines += ["", f"-- scan {health['mode']} · {health['emails_scanned']} emails · "
                  f"{health['sources_changed']} changed · failing: {failing}"]
    return "\n".join(lines)


def subject_line(cfg, today, sections):
    bits = []
    if sections["action_needed"]:
        bits.append(f"{len(sections['action_needed'])} action due")
    if sections["new_discoveries"]:
        bits.append(f"{len(sections['new_discoveries'])} new finds")
    if sections["watchlist_alerts"]:
        bits.append(f"{len(sections['watchlist_alerts'])} window alerts")
    tail = ", ".join(bits) if bits else "quiet day"
    return f"{cfg['digest']['subject_prefix']} · {today.strftime('%a %b %-d')} · {tail}"


def degraded_lines(mode):
    if mode != "degraded-no-llm":
        return []
    lines = []
    changed = read_json(os.path.join(LOCAL, "changed_sources.json"), {"changed": []})
    for c in changed.get("changed", []):
        lines.append(f"{c['name']} changed — {c['url']}")
    new_email = read_json(os.path.join(LOCAL, "new_email.json"), {"messages": []})
    for m in new_email.get("messages", [])[:15]:
        lines.append(f"Email: {m['subject']}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="full", choices=["full", "degraded-no-llm", "quiet"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(os.path.join(REPO, "agent", "config.json")) as f:
        cfg = json.load(f)
    today = datetime.date.today()
    now = datetime.datetime.now()

    sent_marker = os.path.join(LOCAL, f"sent-{today.isoformat()}")
    if os.path.exists(sent_marker) and not args.dry_run and not args.force:
        log("send_digest: already sent today, skipping (--force for a deliberate resend)")
        return 0

    # A render bug must never silence the family's only alert channel — degrade to a
    # minimal email rather than crash before SMTP.
    try:
        sections = collect(today)
        health = derive_health(args.mode)
        raw = degraded_lines(args.mode)
        html_body = render_html(today, sections, health, raw)
        text_body = render_text(today, sections, health, raw)
        subject = subject_line(cfg, today, sections)
    except Exception as e:
        log(f"send_digest: RENDER FAILED ({e}) — sending minimal fallback")
        subject = f"{cfg['digest']['subject_prefix']} · {today.strftime('%a %b %-d')} · digest error"
        text_body = (f"School Intel could not render today's digest ({e}).\n"
                     "The scan data is safe; open the dashboard for the full picture.")
        html_body = f"<body><p>{html.escape(text_body)}</p></body>"

    archive = os.path.join(DATA, "digests", f"{today.isoformat()}.html")
    write_text(archive, html_body)

    if args.dry_run:
        print(f"DRY-RUN subject: {subject}")
        print(text_body)
        log(f"send_digest: dry-run archived {archive}")
        return 0

    # Exit 4 = window-deferred: scan.sh must NOT record a successful day, so the
    # next scheduled trigger re-runs and actually delivers (RunAtLoad-at-5am trap).
    if not within_window(cfg, now) and not args.force:
        log("send_digest: outside delivery window — DEFERRED to next trigger")
        return 4

    # At-most-once: atomically claim the day BEFORE SMTP. If a claim exists without
    # a sent marker, an earlier attempt died ambiguously mid-send — do not resend
    # automatically (the archive exists; --force overrides deliberately).
    claim = os.path.join(LOCAL, f"outbox-{today.isoformat()}")
    try:
        fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, now.isoformat().encode())
        os.close(fd)
    except FileExistsError:
        if not args.force:
            log("send_digest: day already claimed with no sent marker — ambiguous earlier attempt, NOT resending (use --force to override)")
            return 0

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["smtp"]["from"]
    msg["To"] = ", ".join(cfg["recipients"])
    msg["Message-ID"] = f"<school-intel-{today.strftime('%Y%m%d')}@familydigest.local>"
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    password = get_secret(cfg["keychain"]["gmail"])
    last_err = None
    for attempt, delay in enumerate((0, 10, 30), 1):
        if delay:
            time.sleep(delay)
        if not within_window(cfg, datetime.datetime.now()) and not args.force:
            log("send_digest: window closed during retries — stopping")
            return 4
        try:
            with smtplib.SMTP(cfg["smtp"]["host"], cfg["smtp"]["port"], timeout=30) as s:
                s.starttls()
                s.login(cfg["smtp"]["from"], password)
                s.send_message(msg)
            write_text(sent_marker, json.dumps({"at": datetime.datetime.now().isoformat(),
                                                "message_id": msg["Message-ID"], "subject": subject}))
            log(f"send_digest: SENT to {msg['To']} ({subject})")
            return 0
        except Exception as e:
            last_err = e
            log(f"send_digest: attempt {attempt} failed: {e}")
    # Definite failure after retries: release the day-claim so the next trigger can
    # retry (the stable Message-ID makes a rare double delivery threadable), and
    # return 1 so scan.sh marks the day not-successful and the noon run re-fires.
    try:
        os.unlink(claim)
    except OSError:
        pass
    log(f"send_digest: FAILED after retries: {last_err} — archived at {archive}, day-claim released for retry")
    return 1


if __name__ == "__main__":
    sys.exit(main())
