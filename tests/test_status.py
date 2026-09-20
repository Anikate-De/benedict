from benedict import status


def test_write_read(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "STATE_FILE", tmp_path / "benedict-state.json")
    status.write("recording", mic="Digital Microphone", transcript="hello")
    data = status.read()
    assert data["state"] == "recording"
    assert data["mic"] == "Digital Microphone"
    assert data["transcript"] == "hello"
    assert data["ts"] > 0
    assert not list(tmp_path.glob("*.tmp"))


def test_read_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "STATE_FILE", tmp_path / "missing.json")
    assert status.read() == {}


def test_read_corrupt(tmp_path, monkeypatch):
    path = tmp_path / "benedict-state.json"
    path.write_text("{not json")
    monkeypatch.setattr(status, "STATE_FILE", path)
    assert status.read() == {}
