from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
from pathlib import Path

from benedict.config import STATE_DIR

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
STATE_FILE = RUNTIME_DIR / "benedict-state.json"
FOCUS_FILE = RUNTIME_DIR / "benedict-focus"
HEALTH_FILE = RUNTIME_DIR / "benedict-health.json"
LOCK_FILE = STATE_DIR / "run.lock"


def write(state: str, **extra) -> None:
    data = {"state": state, "ts": time.time()}
    data.update(extra)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data))
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def read() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def write_health(ok: bool, detail: str) -> None:
    with contextlib.suppress(OSError):
        HEALTH_FILE.write_text(json.dumps({"ok": ok, "detail": detail, "ts": time.time()}))


def read_health() -> dict:
    try:
        return json.loads(HEALTH_FILE.read_text())
    except (OSError, ValueError):
        return {}


def lock_handle():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    return open(LOCK_FILE, "w")


def daemon_running() -> bool:
    with lock_handle() as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
        except BlockingIOError:
            return True
    return False
