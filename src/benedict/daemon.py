from __future__ import annotations

import contextlib
import logging
import threading
import time

from benedict import status
from benedict.browser import BrowserWorker
from benedict.chatgpt import DictationFailed, DictationUnavailable
from benedict.config import Config
from benedict.hotkey import HotkeyListener
from benedict.insert import Inserter
from benedict.notify import Notifier
from benedict.state import State
from benedict.status import FOCUS_FILE

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
        self._generation = 0

    def run(self) -> None:
        self._listener = HotkeyListener(self.cfg.hotkey.key, self._press.set, self._release.set)
        self._listener.start()
        log.info("listening for %s", self.cfg.hotkey.key)
        if self._pill_active():
            self._transient_state("ready", 2.0, hint=self.cfg.hotkey.hint)
        else:
            self.notifier.done("Benedict ready", f"hold {self.cfg.hotkey.hint} to dictate")
        if self.cfg.browser.prewarm:
            try:
                chat = self.browser.chat()
                chat.mic_button()
                log.info("browser prewarmed")
            except Exception as exc:
                log.warning("prewarm failed: %s", exc)
        try:
            while True:
                if self._press.wait(timeout=5):
                    self._press.clear()
                    self._session()
                    self._release.clear()
                else:
                    self._idle_shutdown()
        finally:
            self._set_state("idle")
            self._listener.stop()
            self.browser.stop()
            self.notifier.close()

    def _pill_active(self) -> bool:
        return FOCUS_FILE.exists()

    def _set_state(self, state: str, **extra) -> None:
        self._generation += 1
        status.write(state, **extra)

    def _transient_state(self, state: str, delay: float, **extra) -> None:
        self._generation += 1
        generation = self._generation
        status.write(state, **extra)

        def reset() -> None:
            if self._generation == generation:
                status.write("idle")

        threading.Timer(delay, reset).start()

    def _session(self) -> None:
        self.state = State.STARTING
        self._last_use = time.monotonic()
        pill = self._pill_active()
        self._set_state("starting")
        self.notifier.play("press")
        if not pill:
            self.notifier.status("Starting dictation…")
        log.info("session start")
        try:
            chat = self.browser.chat()
            if not chat.has_composer():
                raise DictationUnavailable("chat composer not found — run `benedict login`")
            if not chat.start(self._release.is_set):
                chat.clear()
                self._set_state("idle")
                if not pill:
                    self.notifier.done("Dictation cancelled")
                log.info("dictation cancelled before recording")
                return
            self.state = State.RECORDING
            mic = self.browser.mic_display()
            self._set_state("recording", mic=mic, transcript="")
            if not pill:
                self.notifier.status("Listening…", f"mic: {mic}")
            self.notifier.play("start")
            log.info("recording")
            started = time.monotonic()
            partial = ""
            while not self._release.wait(timeout=0.4):
                if time.monotonic() - started >= self.cfg.hotkey.max_duration_sec:
                    break
                try:
                    current = chat.transcript()
                except Exception:
                    current = partial
                if current != partial:
                    partial = current
                    self._set_state("recording", mic=mic, transcript=partial)
            self.state = State.FINALIZING
            self._set_state("finalizing")
            if not pill:
                self.notifier.status("Transcribing…")
            log.info("finalizing")
            chat.stop()
            text = chat.wait_transcript()
            if not text:
                raise DictationFailed("no speech detected")
            self.state = State.INSERTING
            self._set_state("inserting")
            self.inserter.insert(text)
            chat.clear()
            self.notifier.play("stop")
            words = len(text.split())
            self._transient_state("inserted", 1.5, words=words, text=text)
            if not pill:
                self.notifier.done(f"Inserted {words} word{'s' if words != 1 else ''}")
            log.info("inserted %d words", words)
        except Exception as exc:
            self.state = State.ERROR
            log.warning("session failed: %s", exc)
            self._transient_state("error", 4.0, message=str(exc)[:200])
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
