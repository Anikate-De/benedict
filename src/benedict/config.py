from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".config" / "benedict" / "config.toml"
STATE_DIR = Path.home() / ".local" / "state" / "benedict"
DEFAULT_TERMINALS = [
    "org.gnome.Terminal",
    "gnome-terminal",
    "kitty",
    "Alacritty",
    "com.mitchellh.ghostty",
    "org.wezfurlong.wezterm",
    "xterm",
]


@dataclass
class HotkeyCfg:
    mode: str = "hold"
    key: str = "f24"
    max_duration_sec: int = 600


@dataclass
class BrowserCfg:
    chrome: str = "/usr/bin/google-chrome"
    profile: str = "~/.local/share/benedict/chrome"
    start_url: str = "https://chatgpt.com/"
    display: str = ":99"
    idle_shutdown_minutes: int = 30
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
    return cfg
