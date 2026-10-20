import time

import pytest

from benedict import status
from benedict.browser import BrowserWorker
from benedict.chatgpt import CloudflareChallenge, DictationUnavailable
from benedict.config import BrowserCfg, Config
from benedict.daemon import RESUME_JUMP_SEC, Daemon


class FakePage:
    url = "https://chatgpt.com/"

    def __init__(self):
        self.gotos = 0

    def goto(self, *args, **kwargs):
        self.gotos += 1


class FakeChat:
    def __init__(self, ready: list[bool], challenged: bool = False, login: bool = False):
        self.page = FakePage()
        self._ready = ready
        self._challenged = challenged
        self._login = login

    def wait_ready(self):
        return self._ready.pop(0)

    def challenged(self):
        return self._challenged

    def login_prompt_visible(self):
        return self._login

    def mic_button(self):
        return object()


class FakeWorker(BrowserWorker):
    def __init__(self, chat: FakeChat, heals_challenge: bool = True):
        super().__init__(BrowserCfg())
        self._fake = chat
        self.heals = 0
        self.heals_challenge = heals_challenge

    def chat(self):
        return self._fake

    def refresh_clearance(self):
        self.heals += 1
        if self.heals_challenge:
            self._fake._challenged = False


def test_ready_chat_fast_path():
    worker = FakeWorker(FakeChat([True]))
    assert worker.ready_chat() is worker._fake
    assert worker.heals == 0


def test_ready_chat_heals_cloudflare_challenge():
    repairs = []
    worker = FakeWorker(FakeChat([False, True], challenged=True))
    assert worker.ready_chat(on_repair=repairs.append) is worker._fake
    assert worker.heals == 1
    assert repairs == ["Reconnecting to ChatGPT…"]


def test_ready_chat_reloads_when_not_challenged():
    worker = FakeWorker(FakeChat([False, True]))
    worker.ready_chat()
    assert worker.heals == 0
    assert worker._fake.page.gotos == 1


def test_ready_chat_reports_persistent_challenge():
    worker = FakeWorker(FakeChat([False, False], challenged=True), heals_challenge=False)
    with pytest.raises(CloudflareChallenge, match="Cloudflare"):
        worker.ready_chat()


def test_ready_chat_reports_logout():
    worker = FakeWorker(FakeChat([False, False], login=True))
    with pytest.raises(DictationUnavailable, match="logged out"):
        worker.ready_chat()


def test_ready_chat_reports_offline():
    worker = FakeWorker(FakeChat([False, False]))
    with pytest.raises(DictationUnavailable, match="offline"):
        worker.ready_chat()


class ResumeBrowser:
    def __init__(self):
        self.stops = 0
        self.warms = 0
        self.running = True

    def stop(self):
        self.stops += 1

    def ready_chat(self, on_repair=None):
        self.warms += 1
        return FakeChat([True])


def test_resume_restarts_browser_and_rewarms(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(status, "HEALTH_FILE", tmp_path / "health.json")
    browser = ResumeBrowser()
    daemon = Daemon(Config(), browser=browser, inserter=object(), notifier=object())
    daemon._check_resume()
    assert browser.stops == 0

    daemon._clock_offset -= RESUME_JUMP_SEC + 1
    daemon._check_resume()
    assert browser.stops == 1
    assert browser.warms == 0

    daemon._warm_at = time.monotonic()
    daemon._check_resume()
    assert browser.warms == 1
    assert daemon._warm_at is None
