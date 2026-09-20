import sqlite3

from benedict.doctor import Check, _session_cookie, render


def test_render_all_ok():
    checks = [
        Check("keyd chord", True, "f24 via layer(dictation)"),
        Check("audio input", True, "Built-in Audio Analog Stereo"),
    ]
    text = render(checks)
    assert "✓ keyd chord" in text
    assert "✓ audio input" in text
    assert "2 checks passed" in text
    assert "\x1b[" not in text


def test_render_failure_shows_hint():
    checks = [
        Check("keyd chord", True, "f24 via layer(dictation)"),
        Check("ydotool", False, "not found", "systemctl --user enable --now ydotoold"),
    ]
    text = render(checks)
    assert "✗ ydotool" in text
    assert "systemctl --user enable --now ydotoold" in text
    assert "1 of 2 checks passed" in text


def test_render_color():
    text = render([Check("keyd chord", True, "f24")], color=True)
    assert "\x1b[32m" in text
    assert "\x1b[0m" in text


def test_render_right_aligns_detail():
    checks = [Check("clipboard", True, "wl-copy, wl-paste")]
    text = render(checks, width=40)
    assert text.splitlines()[0].endswith("wl-copy, wl-paste")
    assert text.splitlines()[0].index("wl-copy") > 10


def test_session_cookie_present(tmp_path):
    default = tmp_path / "Default"
    default.mkdir()
    db = default / "Cookies"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
        con.execute(
            "INSERT INTO cookies VALUES ('chatgpt.com', '__Secure-next-auth.session-token')"
        )
    assert _session_cookie(tmp_path)


def test_session_cookie_absent(tmp_path):
    assert not _session_cookie(tmp_path)
    default = tmp_path / "Default"
    default.mkdir()
    db = default / "Cookies"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
        con.execute("INSERT INTO cookies VALUES ('example.com', 'sid')")
    assert not _session_cookie(tmp_path)
