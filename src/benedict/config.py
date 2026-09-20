from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".config" / "benedict" / "config.toml"
STATE_DIR = Path.home() / ".local" / "state" / "benedict"
PILL_POSITIONS = ("bottom-center", "bottom-right", "top-center", "top-right")
DEFAULT_TOML = """\
[hotkey]
mode = "hold"              # reserved; hold-to-talk
key = "f24"                # key emitted by keyd
hint = "RightCtrl+Space"   # shown in notifications
max_duration_sec = 600

[browser]
chrome = "/usr/bin/google-chrome"
profile = "~/.local/share/benedict/chrome"
start_url = "https://chatgpt.com/"
display = ":99"            # Xvfb display
idle_shutdown_minutes = 30 # 0 keeps Chrome alive forever
prewarm = true             # start the hidden browser at daemon startup
mic = "default"            # or a PipeWire node.name

[insert]
method = "paste"           # paste | type
paste_combo = "ctrl+v"
terminal_combo = "ctrl+shift+v"
universal_combo = "shift+insert"  # used when the focused app is unknown
newline = "space"          # space | shift+enter | literal
restore_clipboard = true

[ui]
notifications = true
sounds = true
pill = true                # floating status pill (GNOME extension)
pill_position = "bottom-center"  # bottom-center | bottom-right | top-center | top-right
pill_margin = 48           # px from screen edges (bottom placements also clear the dock)
notify_while_pill = true   # also send desktop notifications while the pill is visible
"""
DEFAULT_TERMINALS = [
    "org.gnome.Terminal",
    "org.gnome.Ptyxis",
    "org.gnome.Console",
    "gnome-terminal",
    "kgx",
    "kitty",
    "Alacritty",
    "com.mitchellh.ghostty",
    "org.wezfurlong.wezterm",
    "konsole",
    "xterm",
    "urxvt",
]
TERMINAL_KEYWORDS = (
    "terminal",
    "console",
    "ptyxis",
    "alacritty",
    "kitty",
    "ghostty",
    "wezterm",
    "konsole",
    "xterm",
    "urxvt",
)


def is_terminal(wm_class: str, configured: list[str]) -> bool:
    if wm_class in configured:
        return True
    lowered = wm_class.lower()
    return any(keyword in lowered for keyword in TERMINAL_KEYWORDS)


@dataclass
class HotkeyCfg:
    mode: str = "hold"
    key: str = "f24"
    hint: str = "RightCtrl+Space"
    max_duration_sec: int = 600


@dataclass
class BrowserCfg:
    chrome: str = "/usr/bin/google-chrome"
    profile: str = "~/.local/share/benedict/chrome"
    start_url: str = "https://chatgpt.com/"
    display: str = ":99"
    idle_shutdown_minutes: int = 30
    prewarm: bool = True
    mic: str = "default"


@dataclass
class InsertCfg:
    method: str = "paste"
    paste_combo: str = "ctrl+v"
    terminal_combo: str = "ctrl+shift+v"
    universal_combo: str = "shift+insert"
    terminals: list[str] = field(default_factory=lambda: list(DEFAULT_TERMINALS))
    newline: str = "space"
    restore_clipboard: bool = True


@dataclass
class UICfg:
    notifications: bool = True
    sounds: bool = True
    pill: bool = True
    pill_position: str = "bottom-center"
    pill_margin: int = 48
    notify_while_pill: bool = True


@dataclass
class Config:
    hotkey: HotkeyCfg = field(default_factory=HotkeyCfg)
    browser: BrowserCfg = field(default_factory=BrowserCfg)
    insert: InsertCfg = field(default_factory=InsertCfg)
    ui: UICfg = field(default_factory=UICfg)


def _fill(target: Any, data: dict[str, Any]) -> None:
    valid = {f.name for f in fields(target)}
    for key, value in data.items():
        if key in valid:
            setattr(target, key, value)


def load(path: Path = CONFIG_PATH) -> Config:
    cfg = Config()
    raw: dict[str, Any] = {}
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        pass
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise SystemExit(f"invalid config {path}: {exc}") from exc
    for name, section in (
        ("hotkey", cfg.hotkey),
        ("browser", cfg.browser),
        ("insert", cfg.insert),
        ("ui", cfg.ui),
    ):
        _fill(section, raw.get(name, {}))
    cfg.browser.profile = str(Path(cfg.browser.profile).expanduser())
    cfg.browser.chrome = str(Path(cfg.browser.chrome).expanduser())
    if cfg.ui.pill_position not in PILL_POSITIONS:
        cfg.ui.pill_position = "bottom-center"
    try:
        cfg.ui.pill_margin = max(0, min(400, int(cfg.ui.pill_margin)))
    except (TypeError, ValueError):
        cfg.ui.pill_margin = 48
    return cfg
