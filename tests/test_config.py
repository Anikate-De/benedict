from pathlib import Path

from benedict import config
from benedict.config import DEFAULT_TERMINALS, is_terminal


def test_defaults():
    cfg = config.load(Path("/nonexistent/benedict/config.toml"))
    assert cfg.hotkey.key == "f24"
    assert cfg.hotkey.mode == "hold"
    assert cfg.browser.chrome == "/usr/bin/google-chrome"
    assert cfg.browser.display == ":99"
    assert cfg.insert.paste_combo == "ctrl+v"
    assert cfg.insert.terminal_combo == "ctrl+shift+v"
    assert cfg.insert.terminals
    assert cfg.ui.notifications is True
    assert cfg.ui.pill is True
    assert cfg.ui.pill_position == "bottom-center"
    assert cfg.ui.pill_margin == 48
    assert cfg.ui.notify_while_pill is True
    assert not cfg.browser.profile.startswith("~")


def test_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[hotkey]
key = "f13"

[insert]
method = "type"
terminals = ["kitty"]

[unknown]
ignored = 1
"""
    )
    cfg = config.load(path)
    assert cfg.hotkey.key == "f13"
    assert cfg.hotkey.max_duration_sec == 600
    assert cfg.insert.method == "type"
    assert cfg.insert.terminals == ["kitty"]
    assert cfg.browser.start_url == "https://chatgpt.com/"


def test_invalid_pill_position_falls_back(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[ui]
pill_position = "middle-of-nowhere"
"""
    )
    cfg = config.load(path)
    assert cfg.ui.pill_position == "bottom-center"


def test_ui_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[ui]
pill = false
pill_position = "top-right"
pill_margin = 12
notify_while_pill = false
"""
    )
    cfg = config.load(path)
    assert cfg.ui.pill is False
    assert cfg.ui.pill_position == "top-right"
    assert cfg.ui.pill_margin == 12
    assert cfg.ui.notify_while_pill is False


def test_pill_margin_is_clamped(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[ui]\npill_margin = 9999\n')
    assert config.load(path).ui.pill_margin == 400

    path.write_text('[ui]\npill_margin = -5\n')
    assert config.load(path).ui.pill_margin == 0

    path.write_text('[ui]\npill_margin = "wide"\n')
    assert config.load(path).ui.pill_margin == 48


def test_is_terminal():
    assert is_terminal("org.gnome.Ptyxis", DEFAULT_TERMINALS)
    assert is_terminal("org.gnome.Terminal", DEFAULT_TERMINALS)
    assert is_terminal("kgx", DEFAULT_TERMINALS)
    assert is_terminal("Some-Weird-Terminal", [])
    assert not is_terminal("code", DEFAULT_TERMINALS)
    assert not is_terminal("google-chrome", DEFAULT_TERMINALS)
