from __future__ import annotations

import contextlib
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

APP = "Benedict"
SOUND_DIR = Path.home() / ".local" / "share" / "benedict" / "sounds"
PLAYERS = ("pw-play", "paplay", "aplay")
TONES = (("start", 880, 90), ("stop", 660, 90), ("error", 330, 220))


def write_tone(path: Path, freq: int, ms: int, rate: int = 44100) -> None:
    total = int(rate * ms / 1000)
    fade = max(1, total // 8)
    frames = bytearray()
    for i in range(total):
        amp = 0.35
        if i < fade:
            amp *= i / fade
        elif i > total - fade:
            amp *= (total - i) / fade
        frames += struct.pack("<h", int(32767 * amp * math.sin(2 * math.pi * freq * i / rate)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


class Notifier:
    def __init__(self, enabled: bool = True, sounds: bool = True):
        self.enabled = enabled
        self.sounds = sounds
        self._id: int | None = None
        self._player = next((p for p in PLAYERS if shutil.which(p)), None)
        if sounds:
            self._prepare()

    def _prepare(self) -> None:
        for name, freq, ms in TONES:
            path = SOUND_DIR / f"{name}.wav"
            if path.exists():
                continue
            with contextlib.suppress(OSError):
                write_tone(path, freq, ms)

    def show(
        self,
        summary: str,
        body: str = "",
        icon: str = "audio-input-microphone",
        timeout: int = 0,
    ) -> None:
        if not self.enabled or shutil.which("notify-send") is None:
            return
        args = ["notify-send", "-a", APP, "-i", icon, "-t", str(timeout)]
        if self._id is not None:
            args += ["-r", str(self._id)]
        args.append(summary)
        if body:
            args.append(body)
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return
        out = proc.stdout.strip()
        if out.isdigit():
            self._id = int(out)

    def status(self, summary: str, body: str = "") -> None:
        self.show(summary, body, timeout=0)

    def done(self, summary: str, body: str = "") -> None:
        self.show(summary, body, "dialog-information", timeout=4000)

    def error(self, summary: str, body: str = "") -> None:
        self.show(summary, body, "dialog-error", timeout=8000)

    def close(self) -> None:
        if self._id is None:
            return
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.freedesktop.Notifications",
                    "--object-path",
                    "/org/freedesktop/Notifications",
                    "--method",
                    "org.freedesktop.Notifications.CloseNotification",
                    str(self._id),
                ],
                capture_output=True,
                timeout=5,
            )
        self._id = None

    def play(self, name: str) -> None:
        if not self.sounds or not self._player:
            return
        path = SOUND_DIR / f"{name}.wav"
        if not path.exists():
            return
        with contextlib.suppress(OSError):
            subprocess.Popen(
                [self._player, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
