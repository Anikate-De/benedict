from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from benedict import __version__
from benedict.audio import default_source
from benedict.config import CONFIG_PATH, STATE_DIR, load
from benedict.hotkey import HotkeyError
from benedict.insert import FOCUS_FILE, read_last


def _setup_logging() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(STATE_DIR / "benedict.log"),
        ],
    )


def _lock_handle():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return open(STATE_DIR / "run.lock", "w")


def cmd_run(_args: argparse.Namespace) -> int:
    from benedict.daemon import Daemon

    _setup_logging()
    handle = _lock_handle()
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("benedict is already running", file=sys.stderr)
        return 1
    with contextlib.suppress(KeyboardInterrupt):
        Daemon(load()).run()
    return 0


def cmd_login(_args: argparse.Namespace) -> int:
    cfg = load()
    handle = _lock_handle()
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)
    except BlockingIOError:
        print("stop benedict first: systemctl --user stop benedict", file=sys.stderr)
        return 1
    Path(cfg.browser.profile).mkdir(parents=True, exist_ok=True)
    print("A Chrome window will open. Complete the ChatGPT login there.")
    print("Once you can see the message box where prompts are typed, close the window.")
    subprocess.call(
        [
            cfg.browser.chrome,
            f"--user-data-dir={cfg.browser.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            cfg.browser.start_url,
        ]
    )
    return _verify_login(cfg)


def _verify_login(cfg) -> int:
    from benedict.browser import BrowserWorker

    print("Verifying login…")
    worker = BrowserWorker(cfg.browser)
    try:
        for attempt in (1, 2):
            try:
                chat = worker.chat()
                break
            except Exception:
                if attempt == 2:
                    raise
                worker.stop()
                time.sleep(2)
        if chat.is_logged_in():
            print("[ok] Logged in to ChatGPT.")
            return 0
        shot = STATE_DIR / "login-failed.png"
        with contextlib.suppress(Exception):
            chat.page.screenshot(path=str(shot))
        page_text = ""
        with contextlib.suppress(Exception):
            page_text = chat.page.inner_text("body").lower()
        print("❌ Not logged in — no ChatGPT profile menu found.", file=sys.stderr)
        if "may not be secure" in page_text:
            print(
                "\n".join(
                    [
                        '   Google refused the sign-in ("This browser or app may not be secure").',
                        "   Use email + password instead: on the ChatGPT login page choose",
                        '   "Continue with email" / "Log in with password". If your account was',
                        '   created with Google, use "Forgot password" once to set a password,',
                        "   then retry `benedict login`.",
                    ]
                ),
                file=sys.stderr,
            )
        print(f"   Screenshot: {shot}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"❌ Verification failed: {exc}", file=sys.stderr)
        return 1
    finally:
        worker.stop()


def cmd_probe(_args: argparse.Namespace) -> int:
    from benedict.browser import BrowserWorker

    cfg = load()
    worker = BrowserWorker(cfg.browser)
    try:
        print(json.dumps(worker.chat().probe(), indent=2))
    finally:
        worker.stop()
    return 0


def cmd_last(_args: argparse.Namespace) -> int:
    text = read_last()
    if not text:
        print("no transcripts yet", file=sys.stderr)
        return 1
    print(text)
    return 0


def cmd_test_hotkey(args: argparse.Namespace) -> int:
    from benedict.hotkey import HotkeyListener

    cfg = load()
    events: list[tuple[str, float]] = []
    listener = HotkeyListener(
        cfg.hotkey.key,
        lambda: events.append(("press", time.monotonic())),
        lambda: events.append(("release", time.monotonic())),
    )
    try:
        listener.start()
    except HotkeyError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return 1
    print(f"Hold the chord for {args.seconds}s… (key: {cfg.hotkey.key})")
    time.sleep(args.seconds)
    listener.stop()
    if not events:
        print(f"[fail] no {cfg.hotkey.key} events received; check keyd config")
        return 1
    for name, when in events:
        print(f"[ok]   {name} at {when:.2f}")
    return 0


def _service_active(name: str) -> bool:
    scopes = [["systemctl", "is-active", name]]
    if name == "ydotoold":
        scopes = [["systemctl", "--user", "is-active", name]]
    for cmd in scopes:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.stdout.strip() == "active":
            return True
    return False


def _ydotoold_socket() -> bool:
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    return bool(runtime) and Path(runtime, ".ydotool_socket").exists()


def _keyd_chord(key: str) -> bool:
    try:
        return f"= {key}" in Path("/etc/keyd/default.conf").read_text()
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
            if keys:
                device.close()
                return True
    except Exception:
        return False
    return False


def cmd_doctor(_args: argparse.Namespace) -> int:
    cfg = load()
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        checks.append((name, bool(ok), hint))

    check("chrome", Path(cfg.browser.chrome).exists(), f"{cfg.browser.chrome} missing")
    check("Xvfb", shutil.which("Xvfb") is not None, "run scripts/setup.sh")
    check(
        "wl-copy/wl-paste",
        shutil.which("wl-copy") and shutil.which("wl-paste"),
        "apt install wl-clipboard",
    )
    check("notify-send", shutil.which("notify-send") is not None, "apt install libnotify-bin")
    check("sound player", any(shutil.which(p) for p in ("pw-play", "paplay", "aplay")))
    check("ydotool", shutil.which("ydotool") is not None, "run scripts/setup.sh")
    check(
        "ydotoold",
        _service_active("ydotoold") or _ydotoold_socket(),
        "systemctl --user enable --now ydotoold",
    )
    check("keyd", _service_active("keyd"), "run scripts/setup.sh")
    check(
        "keyd chord",
        _keyd_chord(cfg.hotkey.key),
        "install /etc/keyd/default.conf via scripts/setup.sh",
    )
    check("keyboard access", _can_read_keyboard(), "run scripts/setup.sh (udev rule)")
    mic_name, mic_desc = default_source()
    check("microphone", bool(mic_name), "no default source from wpctl")
    check("chatgpt profile", Path(cfg.browser.profile).exists(), "run: benedict login")

    for name, ok, hint in checks:
        line = f"[{'ok  ' if ok else 'fail'}] {name}"
        if not ok and hint:
            line += f" — {hint}"
        print(line)
    if not FOCUS_FILE.exists():
        print(
            "[warn] focus tracking inactive — using Shift+Insert fallback for paste; enable with: "
            "gnome-extensions enable benedict-focus@benedict"
        )
    if mic_name:
        print(f"       mic: {mic_desc or mic_name}")
    print(f"       config: {CONFIG_PATH}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benedict", description="Push-to-talk ChatGPT dictation")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the daemon in the foreground")
    sub.add_parser("login", help="open a visible browser to log in to ChatGPT")
    sub.add_parser("probe", help="dump ChatGPT page controls for selector debugging")
    sub.add_parser("doctor", help="check system prerequisites")
    sub.add_parser("last", help="print the last transcript")
    test = sub.add_parser("test-hotkey", help="wait for the hotkey chord and report events")
    test.add_argument("--seconds", type=int, default=10)

    args = parser.parse_args(argv)
    handlers = {
        "run": cmd_run,
        "login": cmd_login,
        "probe": cmd_probe,
        "doctor": cmd_doctor,
        "last": cmd_last,
        "test-hotkey": cmd_test_hotkey,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
