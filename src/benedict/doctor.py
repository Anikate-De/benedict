from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from benedict.audio import default_source
from benedict.config import Config
from benedict.status import FOCUS_FILE

GREEN = "\x1b[32m"
RED = "\x1b[31m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"

COOKIE_PATHS = ("Default/Network/Cookies", "Default/Cookies", "Cookies")
SESSION_COOKIES = ("session-token", "session_token")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    hint: str = ""


def _service_active(name: str, user: bool = False) -> bool:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["is-active", name]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.stdout.strip() == "active"


def _display_alive(display: str) -> bool:
    path = f"/tmp/.X11-unix/X{display.lstrip(':')}"
    if not Path(path).exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            sock.connect(path)
        return True
    except OSError:
        return False


def _can_read_keyboard() -> bool:
    try:
        from evdev import InputDevice, ecodes, list_devices

        for path in list_devices():
            try:
                device = InputDevice(path)
            except (PermissionError, OSError):
                continue
            keys = device.capabilities(absinfo=False).get(ecodes.EV_KEY, [])
            device.close()
            if keys:
                return True
    except Exception:
        return False
    return False


def _session_cookie(profile: Path) -> bool:
    for relative in COOKIE_PATHS:
        cookies = profile / relative
        if not cookies.exists():
            continue
        try:
            uri = f"file:{cookies}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1) as db:
                rows = db.execute(
                    "SELECT name FROM cookies WHERE host_key LIKE '%chatgpt.com%'"
                ).fetchall()
        except sqlite3.Error:
            continue
        if any(any(hint in name for hint in SESSION_COOKIES) for (name,) in rows):
            return True
    return False


def _keyd_chord(key: str) -> tuple[bool, str]:
    try:
        config = Path("/etc/keyd/default.conf").read_text()
    except OSError:
        return False, ""
    if f"= {key}" not in config:
        return False, ""
    style = "layer(dictation)" if "layer(dictation)" in config else "chord"
    return True, f"{key} via {style}"


def run(cfg: Config) -> list[Check]:
    checks: list[Check] = []

    chord_ok, chord_detail = _keyd_chord(cfg.hotkey.key)
    keyd_ok = _service_active("keyd")
    checks.append(
        Check(
            "keyd chord",
            chord_ok and keyd_ok,
            chord_detail or cfg.hotkey.key,
            "install /etc/keyd/default.conf and restart keyd: sudo ./scripts/setup.sh",
        )
    )

    checks.append(
        Check(
            "keyboard access",
            _can_read_keyboard(),
            "evdev readable (udev ACL)",
            "run scripts/setup.sh (udev rule) or join the input group",
        )
    )

    checks.append(
        Check(
            "Xvfb display",
            shutil.which("Xvfb") is not None and _display_alive(cfg.browser.display),
            f"{cfg.browser.display} running",
            f"install xvfb; {cfg.browser.display} starts with the first dictation",
        )
    )

    profile = Path(cfg.browser.profile)
    chrome_ok = Path(cfg.browser.chrome).exists() or shutil.which("google-chrome") is not None
    checks.append(
        Check(
            "Chrome profile",
            chrome_ok and profile.exists(),
            str(profile),
            f"chrome: {cfg.browser.chrome}; profile is created by `benedict login`",
        )
    )

    checks.append(
        Check(
            "ChatGPT session",
            _session_cookie(profile),
            "logged in",
            "run: benedict login --import",
        )
    )

    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    socket_path = Path(runtime, ".ydotool_socket") if runtime else Path("/nonexistent")
    checks.append(
        Check(
            "ydotool",
            shutil.which("ydotool") is not None and socket_path.exists(),
            str(socket_path),
            "systemctl --user enable --now ydotoold",
        )
    )

    checks.append(
        Check(
            "clipboard",
            shutil.which("wl-copy") is not None and shutil.which("wl-paste") is not None,
            "wl-copy, wl-paste",
            "apt install wl-clipboard",
        )
    )

    checks.append(
        Check(
            "focus tracking",
            FOCUS_FILE.exists(),
            "benedict-focus@benedict",
            "gnome-extensions enable benedict-focus@benedict",
        )
    )

    mic_name, mic_desc = default_source()
    checks.append(
        Check(
            "audio input",
            bool(mic_name),
            mic_desc or mic_name or "no default source",
            "set browser.mic to a PipeWire node.name from `wpctl status`",
        )
    )
    return checks


def render(checks: list[Check], color: bool = False, width: int | None = None) -> str:
    green, red, dim, reset = (GREEN, RED, DIM, RESET) if color else ("", "", "", "")
    name_width = max(len(check.name) for check in checks)
    lines: list[str] = []
    for check in checks:
        mark = green + "✓" + reset if check.ok else red + "✗" + reset
        tint = dim if check.ok else red
        detail = check.detail if check.ok else check.hint
        name = f"{check.name:<{name_width}}"
        visible = f"✓ {name}"
        line = f"{mark} {name}"
        if width and check.ok and width - len(visible) - len(detail) >= 1:
            line += " " * (width - len(visible) - len(detail)) + f"{tint}{detail}{reset}"
        else:
            line += f"  {tint}{detail}{reset}"
        lines.append(line.rstrip())
    passed = sum(check.ok for check in checks)
    total = len(checks)
    summary = (
        f"{passed} checks passed" if passed == total else f"{passed} of {total} checks passed"
    )
    lines.append("")
    lines.append(f"{(green if passed == total else red)}{summary}{reset}")
    return "\n".join(lines)
