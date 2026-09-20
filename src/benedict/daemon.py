from __future__ import annotations

import contextlib
import logging
import threading
import time

from benedict.browser import BrowserWorker
from benedict.chatgpt import DictationFailed, DictationUnavailable
from benedict.config import Config
from benedict.hotkey import HotkeyListener
from benedict.insert import Inserter
from benedict.notify import Notifier
from benedict.state import State

log = logging.getLogger("benedict")


class Daemon:
    def __init__(
        self,
        cfg: Config,
        browser: BrowserWorker | None = None,
        inserter: Inserter | None = None,
        notifier: Notifier | None = None,
    ):
        self.cfg = cfg
        self.browser = browser or BrowserWorker(cfg.browser)
        self.inserter = inserter or Inserter(cfg.insert)
        self.notifier = notifier or Notifier(cfg.ui.notifications, cfg.ui.sounds)
        self.state = State.IDLE
        self._press = threading.Event()
        self._release = threading.Event()
        self._last_use = time.monotonic()
        self._listener: HotkeyListener | None = None

    def run(self) -> None:
        self._listener = HotkeyListener(self.cfg.hotkey.key, self._press.set, self._release.set)
        self._listener.start()
        log.info("listening for %s", self.cfg.hotkey.key)
        try:
            while True:
                if self._press.wait(timeout=5):
                    self._press.clear()
                    self._release.clear()
                    self._session()
                else:
                    self._idle_shutdown()
        finally:
            self._listener.stop()
            self.browser.stop()
            self.notifier.close()

    def _session(self) -> None:
        self.state = State.STARTING
        self._last_use = time.monotonic()
        self.notifier.status("Starting dictation…")
        try:
            chat = self.browser.chat()
            if not chat.is_logged_in():
                raise DictationUnavailable("not logged in — run `benedict login`")
            if not chat.start(self._release.is_set):
                chat.clear()
                self.notifier.done("Dictation cancelled")
                return
            self.state = State.RECORDING
            self.notifier.status("Listening…", f"mic: {self.browser.mic_display()}")
            self.notifier.play("start")
            started = time.monotonic()
            while not self._release.wait(timeout=1):
                if time.monotonic() - started >= self.cfg.hotkey.max_duration_sec:
                    break
            self.state = State.FINALIZING
            self.notifier.status("Transcribing…")
            chat.stop()
            text = chat.wait_transcript()
            if not text:
                raise DictationFailed("no speech detected")
            self.state = State.INSERTING
            self.inserter.insert(text)
            chat.clear()
            self.notifier.play("stop")
            words = len(text.split())
            self.notifier.done(f"Inserted {words} word{'s' if words != 1 else ''}")
            log.info("inserted %d words", words)
        except Exception as exc:
            self.state = State.ERROR
            log.warning("session failed: %s", exc)
            self.notifier.error("Dictation failed", str(exc)[:200])
            self.notifier.play("error")
            with contextlib.suppress(Exception):
                self.browser.chat().clear()
        finally:
            self.state = State.IDLE
            self._last_use = time.monotonic()

    def _idle_shutdown(self) -> None:
        minutes = self.cfg.browser.idle_shutdown_minutes
        if minutes <= 0 or not self.browser.running:
            return
        if time.monotonic() - self._last_use >= minutes * 60:
            log.info("idle shutdown")
            self.browser.stop()
            self._last_use = time.monotonic()
