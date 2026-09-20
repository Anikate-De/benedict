from __future__ import annotations

import contextlib
import json
import logging
import shutil
import subprocess
import threading
import time

from evdev import ecodes

from benedict.config import STATE_DIR, InsertCfg, is_terminal
from benedict.status import FOCUS_FILE

MODIFIERS = {"ctrl": 29, "shift": 42, "alt": 56, "meta": 125}
SHIFT_ENTER = "\x01"
log = logging.getLogger("benedict")


class InsertError(RuntimeError):
    pass


def normalize_newlines(text: str, mode: str) -> str:
    if mode == "literal":
        return text
    if mode == "shift+enter":
        return text.replace("\n", SHIFT_ENTER)
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _split_top(text: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    quote = False
    start = 0
    for i, char in enumerate(text):
        if quote:
            quote = char != "'"
        elif char == "'":
            quote = True
        elif char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        elif char == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def parse_focused_class(output: str) -> str | None:
    body = output.strip()
    if body.startswith("("):
        body = body[1:]
    if body.endswith(")"):
        body = body[:-1]
    body = body.strip().rstrip(",").strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    for entry in _split_top(body):
        _, _, value = entry.partition(":")
        value = value.strip()
        if not value.startswith("{"):
            continue
        props: dict[str, str] = {}
        for item in _split_top(value.strip("{}")):
            key, _, prop = item.partition(":")
            props[key.strip().strip("'")] = prop.strip()
        if props.get("has-focus") == "<true>":
            return props.get("wm-class", "").strip().strip("<>").strip("'")
    return None


def _read_focus_file() -> str | None:
    with contextlib.suppress(OSError):
        return FOCUS_FILE.read_text().strip() or None
    return None


def _gnome_focused_class() -> str | None:
    if shutil.which("gdbus") is None:
        return None
    try:
        proc = subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell.Introspect",
                "--object-path",
                "/org/gnome/Shell/Introspect",
                "--method",
                "org.gnome.Shell.Introspect.GetWindows",
            ],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return parse_focused_class(proc.stdout)


class Inserter:
    def __init__(self, cfg: InsertCfg):
        self.cfg = cfg
        self._focus_cache: tuple[float, str | None] = (0.0, None)
        self._restore_timer: threading.Timer | None = None

    def insert(self, text: str) -> str:
        text = normalize_newlines(text.strip(), self.cfg.newline)
        if not text:
            raise InsertError("empty transcript")
        if self.cfg.method == "type":
            self._type(text)
            method = "type"
        else:
            method = self._paste(text)
        self._save_last(text)
        return method

    def _paste(self, text: str) -> str:
        previous = self._read_clipboard()
        self._write_clipboard(text)
        wm_class = self._focused_wm_class()
        combo = self._combo_for(wm_class)
        log.info("pasting via %s (focused: %s)", combo, wm_class or "unknown")
        self._send_combo(combo)
        if self.cfg.restore_clipboard and previous is not None:
            self._schedule_restore(previous, text)
        return combo

    def _combo_for(self, wm_class: str | None) -> str:
        if wm_class is None:
            return self.cfg.universal_combo
        if is_terminal(wm_class, self.cfg.terminals):
            return self.cfg.terminal_combo
        return self.cfg.paste_combo

    def _type(self, text: str) -> None:
        chunks = text.split(SHIFT_ENTER)
        for index, chunk in enumerate(chunks):
            if chunk:
                self._run(["ydotool", "type", "--", chunk])
            if index < len(chunks) - 1:
                self._send_combo("shift+enter")

    def _send_combo(self, combo: str) -> None:
        codes = []
        for part in combo.split("+"):
            name = part.strip().lower()
            code = MODIFIERS.get(name, ecodes.ecodes.get(f"KEY_{name.upper()}"))
            if code is None:
                raise InsertError(f"unknown key in combo: {part}")
            codes.append(code)
        sequence = [f"{code}:1" for code in codes] + [f"{code}:0" for code in reversed(codes)]
        self._run(["ydotool", "key", "--key-delay", "25", *sequence])

    def _run(self, cmd: list[str]) -> None:
        if shutil.which(cmd[0]) is None:
            raise InsertError(f"{cmd[0]} not found; run scripts/setup.sh")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise InsertError(str(exc)) from exc
        if proc.returncode != 0:
            raise InsertError(proc.stderr.strip() or f"{cmd[0]} failed")

    def _read_clipboard(self) -> str | None:
        if shutil.which("wl-paste") is None:
            return None
        try:
            proc = subprocess.run(
                ["wl-paste", "-n", "--type", "text"],
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout.decode(errors="replace") if proc.returncode == 0 else None

    def _write_clipboard(self, text: str) -> None:
        if shutil.which("wl-copy") is None:
            raise InsertError("wl-copy not found (install wl-clipboard)")
        for _ in range(20):
            try:
                proc = subprocess.run(
                    ["wl-copy"],
                    input=text.encode(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except subprocess.TimeoutExpired as exc:
                raise InsertError("wl-copy timed out") from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise InsertError(str(exc)) from exc
            if proc.returncode == 0 and self._read_clipboard() == text:
                return
            time.sleep(0.05)
        raise InsertError("clipboard did not update")

    def _schedule_restore(self, previous: str, expected: str) -> None:
        if self._restore_timer is not None:
            self._restore_timer.cancel()
        self._restore_timer = threading.Timer(
            1.5, self._restore_clipboard, args=(previous, expected)
        )
        self._restore_timer.daemon = True
        self._restore_timer.start()

    def _restore_clipboard(self, previous: str, expected: str) -> None:
        if self._read_clipboard() != expected:
            return
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["wl-copy"],
                input=previous.encode(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )

    def _focused_wm_class(self) -> str | None:
        now = time.monotonic()
        if now - self._focus_cache[0] > 0.3:
            self._focus_cache = (now, _read_focus_file() or _gnome_focused_class())
        return self._focus_cache[1]

    def _save_last(self, text: str) -> None:
        with contextlib.suppress(OSError):
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            (STATE_DIR / "last.txt").write_text(text + "\n")
            with (STATE_DIR / "history.jsonl").open("a") as handle:
                record = {"ts": int(time.time()), "text": text}
                handle.write(json.dumps(record) + "\n")


def read_last() -> str:
    with contextlib.suppress(OSError):
        return (STATE_DIR / "last.txt").read_text().strip()
    return ""
