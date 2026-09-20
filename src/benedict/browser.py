from __future__ import annotations

import contextlib
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from benedict.audio import default_source
from benedict.chatgpt import ChatGPT
from benedict.config import BrowserCfg

CHROME_ARGS = [
    "--ozone-platform=x11",
    "--no-first-run",
    "--no-default-browser-check",
    "--use-fake-ui-for-media-stream",
    "--mute-audio",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion,Translate",
    "--disable-dev-shm-usage",
    "--window-size=1280,860",
]


class BrowserError(RuntimeError):
    pass


class BrowserWorker:
    def __init__(self, cfg: BrowserCfg):
        self.cfg = cfg
        self._xvfb: subprocess.Popen | None = None
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._chat: ChatGPT | None = None

    @property
    def running(self) -> bool:
        return self._page is not None

    def chat(self) -> ChatGPT:
        if self._page is not None and self._chat is not None:
            try:
                if not self._page.is_closed():
                    return self._chat
            except Exception:
                pass
        self._shutdown_browser()
        self._start_display()
        self._start_browser()
        assert self._chat is not None
        return self._chat

    def mic_display(self) -> str:
        if self.cfg.mic != "default":
            return self.cfg.mic
        _, description = default_source()
        return description or "system default"

    def add_cookies(self, cookies: list[dict]) -> list[tuple[dict, str]]:
        if self._context is None:
            raise BrowserError("browser is not running")
        failures: list[tuple[dict, str]] = []
        for cookie in cookies:
            try:
                self._context.add_cookies([cookie])
            except Exception as exc:
                failures.append((cookie, str(exc)))
        return failures

    def stop(self) -> None:
        self._shutdown_browser()
        self._shutdown_display()

    def _display_alive(self) -> bool:
        path = f"/tmp/.X11-unix/X{self.cfg.display.lstrip(':')}"
        if not Path(path).exists():
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                sock.connect(path)
            return True
        except OSError:
            return False

    def _start_display(self) -> None:
        if self._display_alive():
            return
        number = self.cfg.display.lstrip(":")
        with contextlib.suppress(OSError):
            Path(f"/tmp/.X11-unix/X{number}").unlink()
        with contextlib.suppress(OSError):
            Path(f"/tmp/.X{number}-lock").unlink()
        if shutil.which("Xvfb") is None:
            raise BrowserError("Xvfb not installed; run scripts/setup.sh")
        self._xvfb = subprocess.Popen(
            ["Xvfb", self.cfg.display, "-screen", "0", "1440x900x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self._display_alive():
                return
            if self._xvfb.poll() is not None:
                raise BrowserError("Xvfb failed to start")
            time.sleep(0.1)
        raise BrowserError("Xvfb did not become ready")

    def _start_browser(self) -> None:
        if not Path(self.cfg.chrome).exists() and shutil.which("google-chrome") is None:
            raise BrowserError(f"chrome not found at {self.cfg.chrome}")
        profile = Path(self.cfg.profile).resolve()
        profile.mkdir(parents=True, exist_ok=True)
        self._clear_singleton(profile)
        env = os.environ.copy()
        env["DISPLAY"] = self.cfg.display
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("WAYLAND_SOCKET", None)
        if self.cfg.mic != "default":
            env["PULSE_SOURCE"] = self.cfg.mic
        try:
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile),
                executable_path=self.cfg.chrome,
                headless=False,
                env=env,
                args=CHROME_ARGS,
                viewport={"width": 1280, "height": 860},
                timeout=45000,
            )
        except Exception as exc:
            self._shutdown_browser()
            self._kill_leftover_chrome(profile)
            raise BrowserError(f"chrome failed to start: {exc}") from exc
        self._context.set_default_timeout(15000)
        self._context.set_default_navigation_timeout(30000)
        with contextlib.suppress(Exception):
            self._context.grant_permissions(["microphone"], origin="https://chatgpt.com")
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        if "chatgpt.com" not in self._page.url:
            self._page.goto(self.cfg.start_url, wait_until="domcontentloaded", timeout=30000)
        self._chat = ChatGPT(self._page)

    def _profile_processes(self, profile: Path) -> list[int]:
        marker = f"--user-data-dir={profile}"
        found: list[int] = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                raw = (proc / "cmdline").read_bytes()
                cmdline = raw.replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if marker in cmdline and "chrome" in cmdline.lower():
                found.append(int(proc.name))
        return found

    def _clear_singleton(self, profile: Path) -> None:
        if self._profile_processes(profile):
            raise BrowserError("another Chrome is using the Benedict profile; close it first")
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            with contextlib.suppress(OSError):
                (profile / name).unlink()

    def _kill_leftover_chrome(self, profile: Path) -> None:
        for pid in self._profile_processes(profile):
            with contextlib.suppress(OSError, ProcessLookupError):
                os.kill(pid, signal.SIGTERM)

    def _shutdown_browser(self) -> None:
        if self._context is not None:
            with contextlib.suppress(Exception):
                self._context.close()
            self._context = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                self._playwright.stop()
            self._playwright = None
        if self.cfg.profile:
            self._kill_leftover_chrome(Path(self.cfg.profile).resolve())
        self._page = None
        self._chat = None

    def _shutdown_display(self) -> None:
        if self._xvfb is not None:
            with contextlib.suppress(Exception):
                self._xvfb.terminate()
                self._xvfb.wait(timeout=5)
            self._xvfb = None
