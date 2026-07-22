#!/usr/bin/env python3
"""Run the headless claude CLI for the daily (no-tools) or discovery (web-only) call.

Prompt = prompt file + INPUT DATA (the bundle JSON). Output envelope is
--output-format json; we extract .result, strip any accidental markdown fences,
parse as JSON, and write it to the output path.

Exit codes: 0 ok · 2 CLI failure/timeout · 3 result is not valid JSON.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import write_json
from lib.runlog import log

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"

# Daily classification must be pure text-in/text-out; belt-and-braces tool denial.
DAILY_DISALLOWED = "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Task,Agent,NotebookEdit,TodoWrite"
DISCOVERY_ALLOWED = "WebSearch,WebFetch"

FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--mode", choices=["daily", "discovery"], default="daily")
    args = ap.parse_args()

    with open(os.path.join(REPO, "agent", "config.json")) as f:
        cfg = json.load(f)
    claude_bin = cfg["llm"]["claude_bin"]
    timeout = cfg["llm"]["timeout_seconds"]

    with open(args.prompt) as f:
        prompt = f.read()
    with open(args.input) as f:
        input_data = f.read()

    full_prompt = prompt + "\n\nINPUT DATA:\n" + input_data

    cmd = [claude_bin, "-p", full_prompt, "--output-format", "json"]
    if args.mode == "daily":
        cmd += ["--disallowedTools", DAILY_DISALLOWED]
    else:
        cmd += ["--allowedTools", DISCOVERY_ALLOWED]

    # Log version once per run for the burn-in diagnostics.
    try:
        ver = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        log(f"llm_call: {ver} mode={args.mode} prompt_chars={len(full_prompt)}")
    except Exception:
        pass

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"llm_call: TIMEOUT after {timeout}s")
        return 2
    if proc.returncode != 0:
        log(f"llm_call: CLI exit {proc.returncode}: {proc.stderr[:500]}")
        return 2

    result = None
    try:
        parsed = json.loads(proc.stdout)
        if isinstance(parsed, dict) and "result" in parsed:
            result_text = parsed["result"]           # CLI envelope
        elif isinstance(parsed, (dict, list)):
            result = parsed                          # already the direct result object
            result_text = ""
        else:
            result_text = str(parsed)
    except json.JSONDecodeError:
        # Some CLI versions emit the result directly on stdout in edge cases.
        result_text = proc.stdout

    if result is None:
        result_text = FENCE_RE.sub("", str(result_text).strip()).strip()
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError as e:
            log(f"llm_call: result not JSON ({e}); first 300 chars: {result_text[:300]!r}")
            return 3

    write_json(args.output, result)
    log(f"llm_call: OK, wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
