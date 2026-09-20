from __future__ import annotations

import re
import subprocess


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _field(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*\*?\s*{re.escape(key)}\s*=\s*\"(.*)\"", text, re.M)
    return match.group(1) if match else None


def default_source() -> tuple[str | None, str | None]:
    out = _run(["wpctl", "inspect", "@DEFAULT_AUDIO_SOURCE@"])
    if not out:
        return None, None
    return _field(out, "node.name"), _field(out, "node.description") or _field(out, "node.nick")
