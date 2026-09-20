# Benedict

Push-to-talk dictation for Linux using ChatGPT's web dictation as the speech-to-text engine.

Hold `RightCtrl+Space` anywhere, speak, release. Benedict drives a hidden Chrome instance
(Xvfb) that is logged into `chatgpt.com`, starts ChatGPT's dictation, and when you release it
pastes the transcript at your cursor. A notification shows the state and the active microphone.

## How it works

```
RightCtrl+Space (hold)
      │  keyd maps the chord to F24 and swallows it
      ▼
benedictd (systemd --user)
  ├── notifications + sound cues       (notify-send, pw-play)
  ├── Xvfb :99 ─ Chrome ─ ChatGPT web  (Playwright, dedicated profile)
  └── wl-copy + ydotool paste          (Ctrl+V, or Ctrl+Shift+V in terminals)
```

A small GNOME Shell extension (`benedict-focus@benedict`) publishes the focused window class
to `$XDG_RUNTIME_DIR/benedict-focus` so Benedict can choose `Ctrl+V` vs the terminal paste
combo. If the extension is unavailable, it falls back to `Shift+Insert`, which pastes in both
terminals and GUI apps.

Nothing is ever sent as a chat message; the dictation text is read from the composer and the
composer is cleared after each use. Transcripts are stored in
`~/.local/state/benedict/last.txt` and `history.jsonl`.

## Requirements

- Ubuntu GNOME on Wayland (GNOME 4x/5x) with PipeWire
- Google Chrome
- A ChatGPT account, logged in once via `benedict login`

## Install

```bash
git clone <this-repo> ~/dev/benedict
cd ~/dev/benedict
sudo ./scripts/setup.sh
```

The script installs `xvfb`, `keyd`, `wl-clipboard`, `libnotify-bin`, installs the keyd chord
config, grants uinput access, adds you to the `input` group, and installs the `ydotoold` and
`benedict` user services.

Then:

```bash
# log out and back in (input group + udev rule), then:
benedict doctor                # verify everything
benedict login                 # log in to ChatGPT once, close the window
systemctl --user enable --now ydotoold benedict
benedict test-hotkey           # hold RightCtrl+Space, expect press/release events
```

## Usage

| Action | Result |
|---|---|
| Hold `RightCtrl+Space`, speak, release | Transcript is pasted at the cursor |
| `benedict doctor` | Diagnose missing pieces |
| `benedict probe` | Dump ChatGPT page controls (when OpenAI changes the UI) |
| `benedict last` | Print the last transcript |
| `journalctl --user -u benedict -f` | Follow logs |

## Configuration

`~/.config/benedict/config.toml` (all keys optional):

```toml
[hotkey]
mode = "hold"              # reserved; hold-to-talk
key = "f24"                # key emitted by the keyd chord
max_duration_sec = 600

[browser]
chrome = "/usr/bin/google-chrome"
profile = "~/.local/share/benedict/chrome"
start_url = "https://chatgpt.com/"
display = ":99"            # Xvfb display
idle_shutdown_minutes = 30 # 0 keeps Chrome alive forever
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
```

Change the hotkey chord in `/etc/keyd/default.conf`, for example to `f10+space = f24`.
If `keyd check` rejects a modifier chord, use `f10+space`. Run `sudo keyd reload` afterwards.

## Troubleshooting

- **`benedict doctor` fails on `keyboard access`** — you must log out and back in after being
  added to the `input` group.
- **Hotkey does nothing** — check `benedict test-hotkey`; if no events, run `sudo keyd check`,
  `sudo systemctl status keyd`, and confirm the chord in `/etc/keyd/default.conf`.
- **VS Code inline suggestions** — VS Code cannot distinguish left and right Ctrl, and
  `Ctrl+Space` opens suggestions. Since keyd swallows the chord only when both keys land
  within 60 ms, a slow press can still reach VS Code. Rebind or remove `Ctrl+Space` in VS Code
  (`Preferences: Open Keyboard Shortcuts`, search `triggerSuggest`).
- **"not logged in" notification** — run `benedict login` (stop the daemon first:
  `systemctl --user stop benedict`).
- **Dictation button not found** — OpenAI changed the UI. Run `benedict probe` and update
  `MIC_SELECTORS`/`STOP_SELECTORS` in `src/benedict/chatgpt.py`, then reinstall:
  `uv tool install --editable .`
- **No mic audio** — verify the mic shown in the notification; set `browser.mic` to a
  PipeWire `node.name` from `wpctl status`.
- **Pasting does nothing or pastes the wrong thing** — check the `[warn] focus tracking`
  line from `benedict doctor`; enable the extension with
  `gnome-extensions enable benedict-focus@benedict`, or set `insert.method = "type"` to type
  the transcript instead of pasting.
- **ydotool errors** — `systemctl --user status ydotoold`; the socket is
  `$XDG_RUNTIME_DIR/.ydotool_socket`.

## Uninstall

```bash
systemctl --user disable --now benedict ydotoold
uv tool uninstall benedict
sudo rm /etc/keyd/default.conf /etc/udev/rules.d/99-benedict-uinput.rules \
        /etc/systemd/user/ydotoold.service
rm -rf ~/.local/share/benedict ~/.local/state/benedict
gnome-extensions disable benedict-focus@benedict
rm -rf ~/.local/share/gnome-shell/extensions/benedict-focus@benedict
```

## Notes and limitations

- This automates your own logged-in ChatGPT session for personal use. It is not affiliated
  with OpenAI, may break when the web UI or usage limits change, and is subject to OpenAI's
  terms.
- First dictation after idle shutdown takes 3–5 seconds while Chrome starts.
- The browser runs under Xvfb and captures the system default microphone; audio never leaves
  your machine except as part of the ChatGPT dictation session.
