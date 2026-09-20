from __future__ import annotations

import contextlib
import time
from collections.abc import Callable

from playwright.sync_api import Locator, Page

COMPOSER_SELECTORS = (
    "#prompt-textarea",
    "div[contenteditable='true']",
)
MIC_SELECTORS = (
    "[data-testid='composer-speech-button']",
    "button[aria-label*='dictate' i]",
    "button[aria-label*='dictation' i]",
    "button[aria-label*='voice input' i]",
)
STOP_SELECTORS = (
    "[data-testid='composer-speech-button'][aria-label*='stop' i]",
    "button[aria-label*='stop dictation' i]",
    "button[aria-label*='stop recording' i]",
)


class DictationUnavailable(RuntimeError):
    pass


class DictationFailed(RuntimeError):
    pass


class ChatGPT:
    def __init__(self, page: Page):
        self.page = page

    def _first(
        self,
        selectors: tuple[str, ...],
        timeout_ms: int = 2000,
        visible: bool = False,
    ) -> Locator | None:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            for selector in selectors:
                try:
                    locator = self.page.locator(selector).first
                    if locator.count() and (not visible or locator.is_visible()):
                        return locator
                except Exception:
                    continue
            if time.monotonic() >= deadline:
                return None
            self.page.wait_for_timeout(100)

    def composer(self) -> Locator | None:
        return self._first(COMPOSER_SELECTORS)

    def is_logged_in(self) -> bool:
        return self.composer() is not None

    def mic_button(self) -> Locator | None:
        return self._first(MIC_SELECTORS, timeout_ms=500, visible=True)

    def transcript(self) -> str:
        composer = self.composer()
        if composer is None:
            return ""
        try:
            return composer.inner_text().strip()
        except Exception:
            return ""

    def is_recording(self) -> bool:
        for selector in STOP_SELECTORS:
            try:
                if self.page.locator(selector).first.count():
                    return True
            except Exception:
                continue
        mic = self.mic_button()
        if mic is None:
            return False
        try:
            label = (mic.get_attribute("aria-label") or "").lower()
        except Exception:
            return False
        return "stop" in label or "recording" in label

    def start(self, cancelled: Callable[[], bool], optimistic_after_ms: int = 2500) -> bool:
        if self.composer() is None:
            raise DictationUnavailable("composer not found (logged out?)")
        mic = self.mic_button()
        if mic is None:
            raise DictationUnavailable("dictation button not found; run `benedict probe`")
        mic.click()
        started = time.monotonic()
        deadline = started + 6
        while time.monotonic() < deadline:
            if cancelled():
                self.abort()
                return False
            if self.is_recording() or self.transcript():
                return True
            if time.monotonic() - started >= optimistic_after_ms / 1000:
                return True
            self.page.wait_for_timeout(120)
        raise DictationFailed("recording did not start")

    def stop(self) -> None:
        mic = self.mic_button()
        if mic is not None:
            try:
                mic.click()
                return
            except Exception:
                pass
        for selector in STOP_SELECTORS:
            try:
                locator = self.page.locator(selector).first
                if locator.count():
                    locator.click()
                    return
            except Exception:
                continue
        with contextlib.suppress(Exception):
            self.page.keyboard.press("Escape")

    def abort(self) -> None:
        with contextlib.suppress(Exception):
            self.stop()

    def wait_transcript(self, timeout_s: float = 12, stable_ms: int = 700) -> str:
        deadline = time.monotonic() + timeout_s
        last = ""
        changed_at = time.monotonic()
        while time.monotonic() < deadline:
            text = self.transcript()
            if text != last:
                last, changed_at = text, time.monotonic()
            stable = (time.monotonic() - changed_at) * 1000 >= stable_ms
            if last and stable and not self.is_recording():
                return last
            self.page.wait_for_timeout(120)
        return last

    def clear(self) -> None:
        composer = self.composer()
        try:
            if composer is not None:
                composer.click()
                self.page.keyboard.press("Control+A")
                self.page.keyboard.press("Backspace")
                if self.transcript() in ("", "\n"):
                    return
        except Exception:
            pass
        with contextlib.suppress(Exception):
            self.page.reload(wait_until="domcontentloaded")

    def probe(self) -> dict:
        data: dict = {"url": self.page.url, "elements": []}
        try:
            nodes = self.page.locator("button, [role=button], [contenteditable=true]").all()
        except Exception:
            return data
        for node in nodes:
            try:
                data["elements"].append(
                    {
                        "tag": node.evaluate("e => e.tagName.toLowerCase()"),
                        "testid": node.get_attribute("data-testid"),
                        "aria": node.get_attribute("aria-label"),
                        "text": (node.inner_text() or "").strip()[:60],
                    }
                )
            except Exception:
                continue
        return data
