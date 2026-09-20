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

from benedict import __version__, status
from benedict.config import CONFIG_PATH, DEFAULT_TOML, PILL_POSITIONS, STATE_DIR, load
from benedict.hotkey import HotkeyError
from benedict.insert import read_last


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


def _ensure_stopped() -> bool:
    handle = _lock_handle()
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)
    except BlockingIOError:
        print("stop benedict first: systemctl --user stop benedict", file=sys.stderr)
        return False
    return True


def cmd_login(args: argparse.Namespace) -> int:
    cfg = load()
    if not _ensure_stopped():
        return 1
    if args.import_cookies or args.browser:
        return cmd_import(cfg, args.browser)
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
            "--password-store=basic",
            cfg.browser.start_url,
        ]
    )
    return _verify_login(cfg)


def cmd_import(cfg, browser: str | None) -> int:
    from benedict.browser import BrowserWorker
    from benedict.cookieimport import find_sources, has_session, load_cookies

    sources = find_sources(browser)
    if not sources:
        print("no Chrome, Brave, Chromium, Edge or Vivaldi profile found", file=sys.stderr)
        return 1
    best: tuple[str, Path, list] | None = None
    for name, base in sources:
        cookies = load_cookies(base, name)
        print(f"[..] {name} ({base.parent.name}): {len(cookies)} chatgpt/openai cookies")
        if has_session(cookies):
            best = (name, base, cookies)
            break
        if best is None and cookies:
            best = (name, base, cookies)
    if best is None:
        print("no ChatGPT session found; log in to ChatGPT in that browser first", file=sys.stderr)
        return 1
    name, _, cookies = best
    print(f"    importing {len(cookies)} cookies from {name}…")
    worker = BrowserWorker(cfg.browser)
    try:
        chat = worker.chat()
        failures = worker.add_cookies([c.to_playwright() for c in cookies])
        if failures:
            print(f"    {len(failures)} cookies rejected, e.g. {failures[0][0]['name']}")
        chat.page.reload(wait_until="domcontentloaded")
        if chat.is_logged_in():
            print(f"[ok] Logged in to ChatGPT using the session from {name}.")
            return 0
        shot = STATE_DIR / "login-failed.png"
        with contextlib.suppress(Exception):
            chat.page.screenshot(path=str(shot))
        print("❌ Cookies imported, but ChatGPT still shows logged out.", file=sys.stderr)
        print(f"   Screenshot: {shot}", file=sys.stderr)
        return 1
    finally:
        worker.stop()


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
                        "   Easiest fix — copy the session from your everyday browser:",
                        "      benedict login --import",
                        "   Or use email + password on the ChatGPT login page. If the account was",
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


def cmd_status(_args: argparse.Namespace) -> int:
    data = status.read()
    if not data:
        print("no state yet (is the daemon running?)", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
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


def _use_color(disabled: bool) -> bool:
    return bool(sys.stdout.isatty()) and not disabled and not os.environ.get("NO_COLOR")


def cmd_doctor(args: argparse.Namespace) -> int:
    from benedict import doctor

    checks = doctor.run(load())
    color = _use_color(args.no_color)
    width = shutil.get_terminal_size().columns if color else None
    print(doctor.render(checks, color=color, width=width))
    return 0 if all(check.ok for check in checks) else 1


def cmd_config(args: argparse.Namespace) -> int:
    if args.edit:
        editor = os.environ.get("EDITOR")
        if not editor:
            editor = next((e for e in ("nano", "vi") if shutil.which(e)), None)
        if not editor:
            print("set $EDITOR to edit the config", file=sys.stderr)
            return 1
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not CONFIG_PATH.exists():
            CONFIG_PATH.write_text(DEFAULT_TOML)
        return subprocess.call([*editor.split(), str(CONFIG_PATH)])
    cfg = load()
    rows = [
        ("hotkey.key", cfg.hotkey.key),
        ("hotkey.hint", cfg.hotkey.hint),
        ("hotkey.max_duration_sec", cfg.hotkey.max_duration_sec),
        ("browser.chrome", cfg.browser.chrome),
        ("browser.profile", cfg.browser.profile),
        ("browser.display", cfg.browser.display),
        ("browser.idle_shutdown_minutes", cfg.browser.idle_shutdown_minutes),
        ("browser.prewarm", cfg.browser.prewarm),
        ("browser.mic", cfg.browser.mic),
        ("insert.method", cfg.insert.method),
        ("insert.paste_combo", cfg.insert.paste_combo),
        ("insert.terminal_combo", cfg.insert.terminal_combo),
        ("insert.universal_combo", cfg.insert.universal_combo),
        ("insert.newline", cfg.insert.newline),
        ("insert.restore_clipboard", cfg.insert.restore_clipboard),
        ("ui.notifications", cfg.ui.notifications),
        ("ui.sounds", cfg.ui.sounds),
        ("ui.pill", cfg.ui.pill),
        ("ui.pill_position", cfg.ui.pill_position),
        ("ui.pill_margin", cfg.ui.pill_margin),
        ("ui.notify_while_pill", cfg.ui.notify_while_pill),
    ]
    width = max(len(key) for key, _ in rows)
    suffix = "" if CONFIG_PATH.exists() else " (not created yet)"
    print(f"# {CONFIG_PATH}{suffix}")
    for key, value in rows:
        print(f"{key:<{width}}  {value}")
    return 0


PILL_DEMO = [
    ("ready", {"hint": "RightCtrl+Space"}, 0.0),
    ("starting", {}, 0.7),
    ("recording", {"mic": "Demo microphone", "transcript": ""}, 0.5),
    ("recording", {"mic": "Demo microphone", "transcript": "the quick"}, 0.5),
    ("recording", {"mic": "Demo microphone", "transcript": "the quick brown fox jumps"}, 0.5),
    (
        "recording",
        {"mic": "Demo microphone", "transcript": "the quick brown fox jumps over the lazy dog"},
        0.5,
    ),
    ("finalizing", {"transcript": "the quick brown fox jumps over the lazy dog"}, 0.8),
    ("inserting", {"transcript": "the quick brown fox jumps over the lazy dog"}, 0.6),
    ("inserted", {"words": 9, "method": "ctrl+v"}, 1.6),
]


def cmd_pill(args: argparse.Namespace) -> int:
    cfg = load()
    if args.position:
        cfg.ui.pill_position = args.position
    data = status.read()
    if data.get("state") not in (None, "idle") and not args.force:
        print("benedict looks busy; stop it or pass --force", file=sys.stderr)
        return 1
    ui = {"pill": True, "position": cfg.ui.pill_position}
    for state, extra, delay in PILL_DEMO:
        status.write(state, ui=ui, **extra)
        if delay:
            time.sleep(delay)
    status.write("idle", ui=ui)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benedict", description="Push-to-talk ChatGPT dictation")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the daemon in the foreground")
    login = sub.add_parser("login", help="open a visible browser to log in to ChatGPT")
    login.add_argument(
        "--import",
        dest="import_cookies",
        action="store_true",
        help="copy the ChatGPT session from your everyday browser",
    )
    login.add_argument(
        "--browser",
        choices=["brave", "chrome", "chromium", "edge", "vivaldi"],
        help="source browser for --import",
    )
    sub.add_parser("probe", help="dump ChatGPT page controls for selector debugging")
    doctor = sub.add_parser("doctor", help="check system prerequisites")
    doctor.add_argument("--no-color", action="store_true", help="disable colored output")
    sub.add_parser("config", help="show effective settings").add_argument(
        "--edit", action="store_true", help="open the config file in $EDITOR"
    )
    pill = sub.add_parser("pill", help="play a demo of the status pill")
    pill.add_argument("--position", choices=list(PILL_POSITIONS), help="override the pill position")
    pill.add_argument("--force", action="store_true", help="run even if the daemon looks busy")
    sub.add_parser("last", help="print the last transcript")
    sub.add_parser("status", help="print the daemon's current state")
    test = sub.add_parser("test-hotkey", help="wait for the hotkey chord and report events")
    test.add_argument("--seconds", type=int, default=10)

    args = parser.parse_args(argv)
    handlers = {
        "run": cmd_run,
        "login": cmd_login,
        "probe": cmd_probe,
        "doctor": cmd_doctor,
        "config": cmd_config,
        "pill": cmd_pill,
        "last": cmd_last,
        "status": cmd_status,
        "test-hotkey": cmd_test_hotkey,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
