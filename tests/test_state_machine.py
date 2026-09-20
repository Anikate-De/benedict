import threading

import pytest

from benedict import status
from benedict.chatgpt import DictationUnavailable
from benedict.config import Config
from benedict.daemon import Daemon
from benedict.state import State


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "STATE_FILE", tmp_path / "benedict-state.json")


class FakeChat:
    def __init__(self, transcript: str = "hello world", fail_start: Exception | None = None):
        self.transcript_text = transcript
        self.fail_start = fail_start
        self.started = False
        self.stopped = False
        self.cleared = False

    def has_composer(self):
        return True

    def start(self, cancelled):
        if self.fail_start:
            raise self.fail_start
        if cancelled():
            return False
        self.started = True
        return True

    def stop(self):
        self.stopped = True

    def wait_transcript(self):
        return self.transcript_text

    def clear(self):
        self.cleared = True


class FakeBrowser:
    def __init__(self, chat: FakeChat):
        self._chat = chat
        self.running = False

    def chat(self):
        return self._chat

    def mic_display(self):
        return "test mic"

    def stop(self):
        self.running = False


class FakeInserter:
    def __init__(self):
        self.texts: list[str] = []

    def insert(self, text):
        self.texts.append(text)


class FakeNotifier:
    def __init__(self):
        self.events: list[tuple] = []

    def status(self, *args):
        self.events.append(("status", *args))

    def done(self, *args):
        self.events.append(("done", *args))

    def error(self, *args):
        self.events.append(("error", *args))

    def play(self, name):
        self.events.append(("play", name))

    def close(self):
        pass


def make_daemon(chat: FakeChat | None = None):
    chat = chat or FakeChat()
    inserter = FakeInserter()
    notifier = FakeNotifier()
    daemon = Daemon(Config(), browser=FakeBrowser(chat), inserter=inserter, notifier=notifier)
    return daemon, chat, inserter, notifier


def release_after(daemon, delay=0.05):
    threading.Timer(delay, daemon._release.set).start()


def test_successful_session():
    daemon, chat, inserter, notifier = make_daemon()
    release_after(daemon)
    daemon._session()
    assert daemon.state is State.IDLE
    assert chat.started and chat.stopped and chat.cleared
    assert inserter.texts == ["hello world"]
    assert ("done", "Inserted 2 words") in notifier.events
    assert ("play", "start") in notifier.events
    assert ("play", "stop") in notifier.events


def test_cancelled_session():
    daemon, chat, inserter, notifier = make_daemon()
    daemon._release.set()
    daemon._session()
    assert daemon.state is State.IDLE
    assert not chat.started
    assert inserter.texts == []
    assert ("done", "Dictation cancelled") in notifier.events


def test_unavailable_session():
    chat = FakeChat(fail_start=DictationUnavailable("not logged in"))
    daemon, _, inserter, notifier = make_daemon(chat)
    release_after(daemon)
    daemon._session()
    assert daemon.state is State.IDLE
    assert inserter.texts == []
    assert any(event[0] == "error" for event in notifier.events)
    assert ("play", "error") in notifier.events


def test_empty_transcript():
    daemon, chat, inserter, notifier = make_daemon(FakeChat(transcript=""))
    release_after(daemon)
    daemon._session()
    assert inserter.texts == []
    assert any(event[0] == "error" for event in notifier.events)
    assert chat.cleared


def test_max_duration_cap():
    daemon, chat, inserter, notifier = make_daemon()
    daemon.cfg.hotkey.max_duration_sec = 0
    daemon._session()
    assert chat.stopped
    assert inserter.texts == ["hello world"]
