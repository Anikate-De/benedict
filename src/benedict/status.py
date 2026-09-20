from __future__ import annotations

import json
import os
import time
from pathlib import Path

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
STATE_FILE = RUNTIME_DIR / "benedict-state.json"
FOCUS_FILE = RUNTIME_DIR / "benedict-focus"


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
