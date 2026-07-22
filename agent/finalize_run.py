#!/usr/bin/env python3
"""Write data/state/last_run.json at the end of every scan (success or degraded).

Usage: finalize_run.py --mode <mode> --ok true|false --duration <s> [--step NAME=STATUS ...]
"""
import argparse
import datetime
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import write_json
from lib.runlog import log

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True)
    ap.add_argument("--ok", required=True, choices=["true", "false"])
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--step", action="append", default=[])
    args = ap.parse_args()

    now = datetime.datetime.now()
    run = {
        "run_id": f"run-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "date": now.date().isoformat(),
        "at": now.isoformat(timespec="seconds"),
        "mode": args.mode,
        "ok": args.ok == "true",
        "duration_s": args.duration,
        "steps": dict(s.split("=", 1) for s in args.step if "=" in s),
    }
    write_json(os.path.join(REPO, "data", "state", "last_run.json"), run)
    log(f"finalize_run: {run['run_id']} mode={args.mode} ok={args.ok}")
    print(run["run_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
