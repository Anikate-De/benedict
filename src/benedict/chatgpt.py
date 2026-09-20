from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable

from playwright.sync_api import Locator, Page

COMPOSER_SELECTORS = (
    "#prompt-textarea",
    "div[contenteditable='true']",
    "textarea",
)
MIC_SELECTORS = (
    "button[aria-label*='start dictation' i]",
    "button[aria-label*='dictation' i]",
)
STOP_SELECTORS = (
    "button[aria-label*='stop dictation' i]",
    "button[aria-label*='stop recording' i]",
    "button[aria-label*='cancel dictation' i]",
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

    def has_composer(self) -> bool:
        return self.composer() is not None

    def is_logged_in(self, timeout_ms: int = 10000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            try:
                profile = self.page.locator("[data-testid='accounts-profile-button']").first
                if profile.count() and profile.is_visible():
                    return True
            except Exception:
                pass
            if time.monotonic() >= deadline:
                return False
            with contextlib.suppress(Exception):
                self.page.wait_for_timeout(250)

    def mic_button(self) -> Locator | None:
        for selector in MIC_SELECTORS:
            try:
                locator = self.page.locator(selector).first
                if locator.count() and locator.is_visible():
                    label = (locator.get_attribute("aria-label") or "").lower()
                    if "dictation" in label and "voice" not in label:
                        return locator
            except Exception:
                continue
        return None

    def stop_button(self) -> Locator | None:
        for selector in STOP_SELECTORS:
            try:
                locator = self.page.locator(selector).first
                if locator.count() and locator.is_visible():
                    return locator
            except Exception:
                continue
        return None

    def transcript(self) -> str:
        composer = self.composer()
        if composer is None:
            return ""
        try:
            if composer.evaluate("e => e.tagName.toLowerCase()") == "textarea":
                return (composer.input_value() or "").strip()
            return composer.inner_text().strip()
        except Exception:
            return ""

    def is_recording(self) -> bool:
        if self.stop_button() is not None:
            return True
        mic = self.mic_button()
        if mic is None:
            return False
        try:
            label = (mic.get_attribute("aria-label") or "").lower()
        except Exception:
            return False
        return "stop" in label or "recording" in label

    def start(self, cancelled: Callable[[], bool], timeout_s: float = 8) -> bool:
        if self.composer() is None:
            raise DictationUnavailable("chat composer not found (logged out?)")
        mic = self.mic_button()
        if mic is None:
            raise DictationUnavailable("dictation button not found; run `benedict probe`")
        mic.click()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if cancelled():
                self.abort()
                return False
            if self.is_recording() or self.transcript():
                return True
            self.page.wait_for_timeout(120)
        if self._login_prompt_visible():
            raise DictationUnavailable(
                "ChatGPT requires login for dictation — run `benedict login`"
            )
        raise DictationFailed("recording did not start")

    def _login_prompt_visible(self) -> bool:
        try:
            return self.page.get_by_role(
                "button", name=re.compile("log in|sign up", re.I)
            ).first.is_visible(timeout=500)
        except Exception:
            return False

    def stop(self) -> None:
        stop = self.stop_button()
        if stop is not None:
            with contextlib.suppress(Exception):
                stop.click()
                return
        mic = self.mic_button()
        if mic is not None:
            with contextlib.suppress(Exception):
                mic.click()
                return
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
                if composer.evaluate("e => e.tagName.toLowerCase()") == "textarea":
                    composer.fill("")
                else:
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
