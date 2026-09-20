from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from benedict.audio import default_source
from benedict.chatgpt import ChatGPT
from benedict.config import BrowserCfg

CHROME_ARGS = [
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

    def stop(self) -> None:
        self._shutdown_browser()
        self._shutdown_display()

    def _start_display(self) -> None:
        number = self.cfg.display.lstrip(":")
        socket = Path(f"/tmp/.X11-unix/X{number}")
        if socket.exists():
            return
        if shutil.which("Xvfb") is None:
            raise BrowserError("Xvfb not installed; run scripts/setup.sh")
        self._xvfb = subprocess.Popen(
            ["Xvfb", self.cfg.display, "-screen", "0", "1440x900x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if socket.exists():
                return
            if self._xvfb.poll() is not None:
                raise BrowserError("Xvfb failed to start")
            time.sleep(0.1)
        raise BrowserError("Xvfb did not become ready")

    def _start_browser(self) -> None:
        if not Path(self.cfg.chrome).exists() and shutil.which("google-chrome") is None:
            raise BrowserError(f"chrome not found at {self.cfg.chrome}")
        Path(self.cfg.profile).mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["DISPLAY"] = self.cfg.display
        if self.cfg.mic != "default":
            env["PULSE_SOURCE"] = self.cfg.mic
        try:
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                self.cfg.profile,
                executable_path=self.cfg.chrome,
                headless=False,
                env=env,
                args=CHROME_ARGS,
                viewport={"width": 1280, "height": 860},
            )
        except Exception as exc:
            self._shutdown_browser()
            raise BrowserError(f"chrome failed to start: {exc}") from exc
        with contextlib.suppress(Exception):
            self._context.grant_permissions(["microphone"], origin="https://chatgpt.com")
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        if "chatgpt.com" not in self._page.url:
            self._page.goto(self.cfg.start_url, wait_until="domcontentloaded", timeout=30000)
        self._chat = ChatGPT(self._page)

    def _shutdown_browser(self) -> None:
        if self._context is not None:
            with contextlib.suppress(Exception):
                self._context.close()
            self._context = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                self._playwright.stop()
            self._playwright = None
        self._page = None
        self._chat = None

    def _shutdown_display(self) -> None:
        if self._xvfb is not None:
            with contextlib.suppress(Exception):
                self._xvfb.terminate()
                self._xvfb.wait(timeout=5)
            self._xvfb = None
