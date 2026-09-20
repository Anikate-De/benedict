from benedict.config import InsertCfg
from benedict.insert import SHIFT_ENTER, Inserter, normalize_newlines, parse_focused_class


class FakeInserter(Inserter):
    def __init__(self, cfg: InsertCfg, wm_class: str | None = None):
        super().__init__(cfg)
        self.commands: list[list[str]] = []
        self.writes: list[str] = []
        self.wm_class = wm_class
        self.saved: str | None = None

    def _run(self, cmd):
        self.commands.append(cmd)

    def _focused_wm_class(self):
        return self.wm_class

    def _read_clipboard(self):
        return "previous"

    def _write_clipboard(self, text):
        self.writes.append(text)

    def _save_last(self, text):
        self.saved = text


def test_normalize_space():
    assert normalize_newlines("hello\nworld\n\nfoo ", "space") == "hello world foo"


def test_normalize_literal():
    assert normalize_newlines("a\nb", "literal") == "a\nb"


def test_normalize_shift_enter():
    assert normalize_newlines("a\nb", "shift+enter") == f"a{SHIFT_ENTER}b"


def test_paste_uses_ctrl_v():
    cfg = InsertCfg(restore_clipboard=False)
    inserter = FakeInserter(cfg, wm_class="code")
    inserter.insert("hello")
    assert inserter.writes == ["hello"]
    assert inserter.commands == [
        ["ydotool", "key", "--key-delay", "25", "29:1", "47:1", "47:0", "29:0"]
    ]
    assert inserter.saved == "hello"


def test_paste_uses_terminal_combo():
    cfg = InsertCfg(restore_clipboard=False)
    inserter = FakeInserter(cfg, wm_class="org.gnome.Terminal")
    inserter.insert("hello")
    assert inserter.commands == [
        ["ydotool", "key", "--key-delay", "25", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
    ]


def test_ptyxis_detected_as_terminal():
    cfg = InsertCfg(restore_clipboard=False)
    inserter = FakeInserter(cfg, wm_class="org.gnome.Ptyxis")
    inserter.insert("hello")
    assert inserter.commands == [
        ["ydotool", "key", "--key-delay", "25", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
    ]


def test_paste_uses_universal_combo_when_focus_unknown():
    cfg = InsertCfg(restore_clipboard=False)
    inserter = FakeInserter(cfg, wm_class=None)
    inserter.insert("hello")
    assert inserter.commands == [
        ["ydotool", "key", "--key-delay", "25", "42:1", "110:1", "110:0", "42:0"]
    ]


def test_type_method_chunks_on_shift_enter():
    cfg = InsertCfg(method="type", newline="shift+enter", restore_clipboard=False)
    inserter = FakeInserter(cfg)
    inserter.insert("one\ntwo")
    assert inserter.commands[0] == ["ydotool", "type", "--", "one"]
    assert inserter.commands[1][0:2] == ["ydotool", "key"]
    assert inserter.commands[2] == ["ydotool", "type", "--", "two"]


def test_parse_focused_class():
    sample = (
        "({'0x1': {'app-id': <'org.gnome.Terminal.desktop'>, 'has-focus': <true>, "
        "'wm-class': <'org.gnome.Terminal'>}, '0x2': {'app-id': <'code.desktop'>, "
        "'has-focus': <false>, 'wm-class': <'code'>}},)"
    )
    assert parse_focused_class(sample) == "org.gnome.Terminal"


def test_parse_focused_class_none():
    assert parse_focused_class("(nothing here)") is None
