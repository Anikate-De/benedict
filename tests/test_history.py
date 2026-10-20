import json

import pytest

from benedict import insert, status
from benedict.chatgpt import CloudflareChallenge
from benedict.config import Config
from benedict.daemon import Daemon
from benedict.insert import HISTORY_LIMIT, read_history, save_transcript


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(insert, "STATE_DIR", tmp_path)
    monkeypatch.setattr(status, "STATE_FILE", tmp_path / "benedict-state.json")
    monkeypatch.setattr(status, "HEALTH_FILE", tmp_path / "benedict-health.json")
    monkeypatch.setattr("benedict.daemon.FOCUS_FILE", tmp_path / "benedict-focus")


def test_history_keeps_last_ten(tmp_path):
    for n in range(HISTORY_LIMIT + 5):
        save_transcript(f"note {n}")
    lines = (tmp_path / "history.jsonl").read_text().splitlines()
    assert len(lines) == HISTORY_LIMIT
    assert [item["text"] for item in read_history()][:2] == ["note 14", "note 13"]
    assert (tmp_path / "last.txt").read_text() == "note 14\n"


def test_history_trims_oversized_file_and_skips_bad_lines(tmp_path):
    rows = [json.dumps({"ts": n, "text": f"old {n}"}) for n in range(50)]
    (tmp_path / "history.jsonl").write_text("\n".join([*rows, "not json"]) + "\n")
    assert read_history()[0]["text"] == "old 49"
    save_transcript("fresh")
    assert len((tmp_path / "history.jsonl").read_text().splitlines()) == HISTORY_LIMIT
    assert read_history()[0]["text"] == "fresh"


class RecordingInserter:
    def __init__(self):
        self.calls = []

    def insert(self, text, remember=True):
        self.calls.append((text, remember))
        return "ctrl+v"


class Notes:
    def __init__(self, clickable=True):
        self.actions = []
        self.done_calls = []
        self.clickable = clickable

    def action(self, summary, body, label, callback):
        self.actions.append((summary, label, callback))
        return self.clickable

    def done(self, *args):
        self.done_calls.append(args)

    def error(self, *args):
        pass

    def status(self, *args):
        pass

    def play(self, name):
        pass

    def close(self):
        pass


def make(browser=None, notifier=None):
    inserter = RecordingInserter()
    daemon = Daemon(Config(), browser=browser or object(), inserter=inserter, notifier=notifier)
    return daemon, inserter


def test_history_opens_picker_when_pill_active(tmp_path):
    save_transcript("first")
    save_transcript("second")
    (tmp_path / "benedict-focus").write_text("code")
    daemon, inserter = make()
    daemon._show_history()
    data = status.read()
    assert data["state"] == "history"
    assert [item["text"] for item in data["items"]] == ["second", "first"]
    assert inserter.calls == []


def test_history_pastes_newest_without_extension():
    save_transcript("first")
    save_transcript("second")
    daemon, inserter = make()
    daemon._show_history()
    assert inserter.calls == [("second", False)]
    assert len(read_history()) == 2


def test_history_empty():
    daemon, inserter = make()
    daemon._show_history()
    assert status.read()["message"] == "No transcripts yet"


class StuckListener:
    held = False


def test_tap_during_finalize_does_not_start_phantom_session(monkeypatch):
    daemon, _ = make()
    daemon._listener = StuckListener()
    sessions = []

    def session():
        sessions.append(1)
        daemon._press.set()  # tapped again while the transcript was finalizing
        daemon._release.set()

    monkeypatch.setattr(daemon, "_session", session)
    daemon._dictate()
    assert not daemon._press.is_set()
    assert not daemon._release.is_set()


def test_held_key_after_session_starts_next(monkeypatch):
    daemon, _ = make()
    listener = StuckListener()
    listener.held = True
    daemon._listener = listener
    monkeypatch.setattr(daemon, "_session", lambda: daemon._press.set())
    daemon._dictate()
    assert daemon._press.is_set()


class LoginBrowser:
    def __init__(self, logged_in=True, fail=None):
        self.logged_in = logged_in
        self.fail = fail
        self.windows = 0

    def ready_chat(self, on_repair=None):
        if self.fail:
            raise self.fail
        return self

    def mic_button(self):
        return object()

    def is_logged_in(self):
        return self.logged_in

    def open_login_window(self):
        self.windows += 1
        return 0


def test_prewarm_challenge_offers_login_button():
    notes = Notes()
    browser = LoginBrowser(fail=CloudflareChallenge("Cloudflare is blocking the hidden browser"))
    daemon, _ = make(browser, notes)
    daemon._prewarm()
    assert status.read_health()["ok"] is False
    summary, label, callback = notes.actions[0]
    assert label == "Log in"
    callback()
    assert daemon._login.is_set() and daemon._wake.is_set()


def test_interactive_login_success():
    notes = Notes()
    browser = LoginBrowser(logged_in=True)
    daemon, _ = make(browser, notes)
    daemon._press.set()
    daemon._interactive_login()
    assert browser.windows == 1
    assert status.read_health()["ok"] is True
    assert notes.done_calls[0][0] == "Logged in to ChatGPT"
    assert not daemon._press.is_set()


def test_interactive_login_still_logged_out_asks_again():
    notes = Notes(clickable=False)
    daemon, _ = make(LoginBrowser(logged_in=False), notes)
    daemon._interactive_login()
    assert status.read_health()["ok"] is False
    assert "benedict login" in status.read()["message"]
