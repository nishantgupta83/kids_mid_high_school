"""Dated run logfile + step status lines. One log per day under logs/runs/."""
import datetime
import os

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
LOG_DIR = os.path.join(REPO, "logs", "runs")


def log(message: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    now = datetime.datetime.now()
    line = f"{now.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    with open(os.path.join(LOG_DIR, f"{now.strftime('%Y-%m-%d')}.log"), "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def step(n, name: str, status: str, detail: str = "") -> None:
    suffix = f" {detail}" if detail else ""
    log(f"STEP {n} {name} {status}{suffix}")
