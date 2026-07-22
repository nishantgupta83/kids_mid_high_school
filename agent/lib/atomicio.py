"""Atomic JSON/text writes: temp file in the same dir, fsync, os.replace."""
import json
import os
import tempfile


def write_text(path: str, text: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path: str, obj) -> None:
    write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def read_json(path: str, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
