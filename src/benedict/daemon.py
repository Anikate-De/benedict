from __future__ import annotations

import contextlib
import logging
import threading
import time

from benedict import status
from benedict.browser import BrowserWorker
from benedict.chatgpt import DictationFailed, DictationUnavailable, LoginRequired
from benedict.config import Config
from benedict.hotkey import HotkeyListener
from benedict.insert import Inserter, read_history
from benedict.notify import Notifier
from benedict.state import State
from benedict.status import FOCUS_FILE

log = logging.getLogger("benedict")
# The monotonic clock stops during suspend while wall time keeps running.
RESUME_JUMP_SEC = 60
RESUME_WARM_DELAY_SEC = 15


def combo_label(method: str) -> str:
    if method == "type":
        return "Typed"
    return "+".join(part.capitalize() for part in method.split("+"))


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
        self._history = threading.Event()
        self._login = threading.Event()
        self._wake = threading.Event()
        self._last_use = time.monotonic()
        self._listener: HotkeyListener | None = None
        self._history_listener: HotkeyListener | None = None
        self._generation = 0
        self._clock_offset = time.time() - time.monotonic()
        self._warm_at: float | None = None

    def run(self) -> None:
        self._listener = HotkeyListener(self.cfg.hotkey.key, self._on_press, self._release.set)
        self._listener.start()
        log.info("listening for %s", self.cfg.hotkey.key)
        try:
            self._history_listener = HotkeyListener(
                self.cfg.hotkey.history_key, self._on_history, lambda: None
            )
            self._history_listener.start()
            log.info("history picker on %s", self.cfg.hotkey.history_key)
        except Exception as exc:
            self._history_listener = None
            log.warning("history hotkey unavailable: %s", exc)
        if self._pill_active():
            self._transient_state("ready", 2.0, hint=self.cfg.hotkey.hint)
        else:
            self.notifier.done("Benedict ready", f"hold {self.cfg.hotkey.hint} to dictate")
        if self.cfg.browser.prewarm:
            self._prewarm()
        try:
            while True:
                woke = self._wake.wait(timeout=5)
                self._wake.clear()
                if self._press.is_set():
                    self._dictate()
                if self._history.is_set():
                    self._history.clear()
                    self._show_history()
                if self._login.is_set():
                    self._login.clear()
                    self._interactive_login()
                if not woke:
                    self._check_resume()
                    self._idle_shutdown()
        finally:
            self._set_state("idle")
            self._listener.stop()
            if self._history_listener is not None:
                self._history_listener.stop()
            self.browser.stop()
            self.notifier.close()

    def _on_press(self) -> None:
        self._press.set()
        self._wake.set()

    def _on_history(self) -> None:
        self._history.set()
        self._wake.set()

    def _request_login(self) -> None:
        self._login.set()
        self._wake.set()

    def _dictate(self) -> None:
        self._press.clear()
        self._session()
        self._release.clear()
        # A tap during finalizing leaves _press set after its release was consumed;
        # only start another session if the key is still down.
        if self._listener is None or not self._listener.held:
            self._press.clear()

    def _prewarm(self) -> None:
        try:
            self.browser.ready_chat().mic_button()
            status.write_health(True, "connected")
            log.info("browser prewarmed")
        except Exception as exc:
            log.warning("prewarm failed: %s", exc)
            if isinstance(exc, DictationUnavailable):
                status.write_health(False, str(exc))
            if isinstance(exc, LoginRequired):
                self._ask_login(str(exc))
        self._last_use = time.monotonic()

    def _ask_login(self, reason: str) -> str:
        if self.notifier.action(
            "ChatGPT needs a login",
            f"{reason}. Click Log in to fix it.",
            "Log in",
            self._request_login,
        ):
            return f"{reason} — use Log in on the notification"
        return f"{reason} — run `benedict login`"

    def _interactive_login(self) -> None:
        log.info("opening login window")
        self._set_state("starting", message="Log in to ChatGPT, then close the window")
        try:
            self.browser.open_login_window()
            logged_in = self.browser.ready_chat().is_logged_in()
        except Exception as exc:
            log.warning("login failed: %s", exc)
            logged_in = False
        self._press.clear()
        self._release.clear()
        self._last_use = time.monotonic()
        if logged_in:
            log.info("logged in")
            status.write_health(True, "connected")
            self._transient_state("ready", 2.0, hint=self.cfg.hotkey.hint)
            self.notifier.done("Logged in to ChatGPT", f"hold {self.cfg.hotkey.hint} to dictate")
            return
        status.write_health(False, "still not logged in to ChatGPT")
        message = self._ask_login("Still not logged in to ChatGPT")
        self._transient_state("error", 4.0, message=message)

    def _show_history(self) -> None:
        items = read_history()
        if not items:
            self._transient_state("error", 2.0, message="No transcripts yet")
            return
        if self._pill_active():
            log.info("history picker (%d items)", len(items))
            self._set_state("history", items=items)
            return
        self.paste_history(1)

    def paste_history(self, index: int) -> None:
        items = read_history()
        if not 1 <= index <= len(items):
            self._transient_state("error", 2.0, message=f"No transcript #{index}")
            return
        text = items[index - 1]["text"]
        try:
            method = self.inserter.insert(text, remember=False) or "paste"
        except Exception as exc:
            log.warning("re-paste failed: %s", exc)
            self._transient_state("error", 4.0, message=str(exc)[:200])
            return
        words = len(text.split())
        log.info("re-pasted #%d (%d words) via %s", index, words, method)
        self._transient_state("inserted", 1.5, words=words, method=method)

    def _check_resume(self) -> None:
        offset = time.time() - time.monotonic()
        if offset - self._clock_offset > RESUME_JUMP_SEC:
            log.info("resumed from sleep")
            self.browser.stop()
            if self.cfg.browser.prewarm:
                self._warm_at = time.monotonic() + RESUME_WARM_DELAY_SEC
        self._clock_offset = offset
        if self._warm_at is not None and time.monotonic() >= self._warm_at:
            self._warm_at = None
            self._prewarm()

    def _pill_active(self) -> bool:
        return self.cfg.ui.pill and FOCUS_FILE.exists()

    def _notify(self, pill: bool) -> bool:
        return self.cfg.ui.notify_while_pill or not pill

    def _ui_payload(self) -> dict:
        return {
            "pill": self.cfg.ui.pill,
            "position": self.cfg.ui.pill_position,
            "margin": self.cfg.ui.pill_margin,
        }

    def _set_state(self, state: str, **extra) -> None:
        self._generation += 1
        status.write(state, ui=self._ui_payload(), **extra)

    def _transient_state(self, state: str, delay: float, **extra) -> None:
        self._generation += 1
        generation = self._generation
        status.write(state, ui=self._ui_payload(), **extra)

        def reset() -> None:
            if self._generation == generation:
                status.write("idle")

        threading.Timer(delay, reset).start()

    def _session(self) -> None:
        self.state = State.STARTING
        self._last_use = time.monotonic()
        pill = self._pill_active()
        notify = self._notify(pill)
        self._set_state("starting")
        self.notifier.play("press")
        if notify:
            self.notifier.status("Starting dictation…")
        log.info("session start")
        try:
            chat = self.browser.ready_chat(
                on_repair=lambda message: self._set_state("starting", message=message)
            )
            status.write_health(True, "connected")
            if not chat.start(self._release.is_set):
                chat.clear()
                self._set_state("idle")
                if notify:
                    self.notifier.done("Dictation cancelled")
                log.info("dictation cancelled before recording")
                return
            self.state = State.RECORDING
            mic = self.browser.mic_display()
            self._set_state("recording", mic=mic, transcript="")
            if notify:
                self.notifier.status("Listening", f"Microphone: {mic}")
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
            self._set_state("finalizing", transcript=partial)
            if notify:
                self.notifier.status("Transcribing…", f"Microphone: {mic}")
            log.info("finalizing")
            chat.stop()
            text = chat.wait_transcript()
            if not text:
                raise DictationFailed("no speech detected")
            self.state = State.INSERTING
            self._set_state("inserting", transcript=text)
            if notify:
                self.notifier.status("Inserting…")
            method = self.inserter.insert(text) or "paste"
            chat.clear()
            self.notifier.play("stop")
            words = len(text.split())
            self._transient_state("inserted", 1.5, words=words, text=text, method=method)
            if notify:
                self.notifier.done(
                    f"Pasted {words} word{'s' if words != 1 else ''}",
                    f"{combo_label(method)} at the focused window",
                )
            log.info("inserted %d words via %s", words, method)
        except Exception as exc:
            self.state = State.ERROR
            log.warning("session failed: %s", exc)
            message = str(exc)
            if isinstance(exc, DictationUnavailable):
                status.write_health(False, message)
            if isinstance(exc, LoginRequired):
                self.notifier.close()
                message = self._ask_login(message)
            else:
                self.notifier.error("Dictation failed", message[:200])
            self._transient_state("error", 4.0, message=message[:200])
            self.notifier.play("error")
            if not isinstance(exc, LoginRequired):
                with contextlib.suppress(Exception):
                    self.browser.chat().clear()
        finally:
            self.state = State.IDLE
            self._last_use = time.monotonic()
            self._warm_at = None

    def _idle_shutdown(self) -> None:
        minutes = self.cfg.browser.idle_shutdown_minutes
        if minutes <= 0 or not self.browser.running:
            return
        if time.monotonic() - self._last_use >= minutes * 60:
            log.info("idle shutdown")
            self.browser.stop()
            self._last_use = time.monotonic()
