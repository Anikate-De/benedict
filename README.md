<p align="center">
  <img src="assets/logo.svg" width="128" alt="Benedict" />
</p>

# Benedict

[![CI](https://github.com/Anikate-De/benedict/actions/workflows/ci.yml/badge.svg)](https://github.com/Anikate-De/benedict/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Anikate-De/benedict?label=version&sort=semver)](https://github.com/Anikate-De/benedict/releases)
[![Coverage](https://raw.githubusercontent.com/Anikate-De/benedict/badges/coverage.svg)](https://github.com/Anikate-De/benedict/actions/workflows/ci.yml)
[![Tests](https://raw.githubusercontent.com/Anikate-De/benedict/badges/tests.svg)](https://github.com/Anikate-De/benedict/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Platform](https://img.shields.io/badge/platform-Linux%20%C2%B7%20GNOME-lightgrey)](#requirements)

Push-to-talk dictation for Linux using ChatGPT's web dictation as the speech-to-text engine.

Hold `RightCtrl+Space` anywhere, speak, release. Benedict drives a hidden Chrome instance (Xvfb) that is logged into `chatgpt.com`, starts ChatGPT's dictation, and when you release it pastes the transcript at your cursor. A floating status pill shows the live state, the active microphone, and the transcript as it forms — and a notification mirrors the same.

## Motivation

ChatGPT's web dictation is superb — better than any other speech-to-text I could find today — and it costs nothing extra. But using it meant opening a browser tab, dictating, copying the text, and pasting it back into whatever you were working on. Benedict removes that friction: hold a hotkey anywhere and the transcript lands at your cursor. No API credits, just the ChatGPT session you already use.

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

A small GNOME Shell extension (`benedict-focus@benedict`) publishes the focused window class to `$XDG_RUNTIME_DIR/benedict-focus` so Benedict can choose `Ctrl+V` vs the terminal paste combo, and draws the floating pill: a green dot with `Listening`, the active microphone on the right, and the streaming transcript underneath with a blinking caret. Other states read `Starting dictation…`, `Transcribing…`, `Inserting…`, `Pasted N words`, or the error message. Its position, edge margin, and visibility come from `[ui]` in the config. If the extension is unavailable, Benedict falls back to `Shift+Insert` and desktop notifications.

Nothing is ever sent as a chat message; the dictation text is read from the composer and the composer is cleared after each use. Transcripts are stored in `~/.local/state/benedict/last.txt` and `history.jsonl`.

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

The script installs `xvfb`, `keyd`, `wl-clipboard`, `libnotify-bin`, installs the keyd chord config, grants live input access via udev `uaccess` ACLs (`input` group is added only as a fallback), and installs the `ydotoold` and `benedict` user services.

Then:

```bash
benedict doctor                # verify everything
benedict login --import        # copy your ChatGPT session from Brave/Chrome (recommended)
# or, if you prefer a fresh sign-in:
#   benedict login            # use email + password, not Google
systemctl --user enable --now ydotoold benedict
benedict test-hotkey           # hold RightCtrl+Space, expect press/release events
```

Input access needs no re-login (the udev ACLs apply live). The GNOME extension itself loads on your next login, and after any extension update GNOME Shell only picks up the new code in a new session — until then paste uses the `Shift+Insert` fallback and the pill may be stale or missing.

## Usage

| Action | Result |
|---|---|
| Hold `RightCtrl+Space`, speak, release | Transcript is pasted at the cursor |
| `benedict doctor` | Diagnose missing pieces with a 9-point checklist |
| `benedict status` | Print the daemon's current state as JSON |
| `benedict config` | Show effective settings (`--edit` opens the config file) |
| `benedict pill` | Play a short demo of the status pill |
| `benedict probe` | Dump ChatGPT page controls (when OpenAI changes the UI) |
| `benedict last` | Print the last transcript |
| `man benedict` | Read the manual page |
| `journalctl --user -u benedict -f` | Follow logs |

## Configuration

`~/.config/benedict/config.toml` (all keys optional):

```toml
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
notifications = true       # desktop notifications
sounds = true
pill = true                # floating status pill (GNOME extension)
pill_position = "bottom-center"  # bottom-center | bottom-right | top-center | top-right
pill_margin = 48           # px from screen edges (bottom placements also clear the dock)
notify_while_pill = true   # keep notifications while the pill is visible
```

Change the hotkey in `/etc/keyd/default.conf`. The default uses a layer instead of a chord, so there is no timing window and RightCtrl keeps working as Ctrl:

```
[main]
rightcontrol = layer(dictation)

[dictation:C]
space = f24
```

On Ubuntu the binary is `keyd.rvaiya`: apply changes with `sudo keyd.rvaiya reload` and inspect errors with `journalctl -u keyd -n 20`. After changing the chord, update `hotkey.hint` in the Benedict config.

## Troubleshooting

- **`benedict doctor` fails on `keyboard access`** — the udev ACLs are missing; run `sudo ./scripts/setup.sh` again. As a fallback, adding yourself to the `input` group and logging back in also works.
- **`keyd` ignores the chord** — restart keyd (`sudo systemctl restart keyd`) so it recreates its virtual keyboard with ACLs, or re-run setup.
- **Hotkey does nothing** — check `benedict test-hotkey`; if no events, run `journalctl -u keyd -n 20` and confirm the chord in `/etc/keyd/default.conf`, then `sudo keyd.rvaiya reload`.
- **VS Code inline suggestions** — VS Code cannot distinguish left and right Ctrl, and `Ctrl+Space` opens suggestions. Since keyd swallows the chord only when both keys land within 60 ms, a slow press can still reach VS Code. Rebind or remove `Ctrl+Space` in VS Code (`Preferences: Open Keyboard Shortcuts`, search `triggerSuggest`).
- **"not logged in" notification** — run `benedict login` (stop the daemon first: `systemctl --user stop benedict`).
- **Google sign-in says "This browser or app may not be secure"** — Google refuses OAuth in the dedicated Benedict profile. Copy the session from a browser where you are already logged in: `benedict login --import` (stop the daemon first). Alternatively sign in with email + password; if the account was created through Google, use "Forgot password" once to set a password.
- **Dictation button not found** — OpenAI changed the UI. Run `benedict probe` and update `MIC_SELECTORS`/`STOP_SELECTORS` in `src/benedict/chatgpt.py`, then reinstall: `uv tool install --editable .`
- **No mic audio** — verify the mic shown in the notification; set `browser.mic` to a PipeWire `node.name` from `wpctl status`.
- **Pasting does nothing or pastes the wrong thing** — check the `focus tracking` row in `benedict doctor`; enable the extension with `gnome-extensions enable benedict-focus@benedict`, or set `insert.method = "type"` to type the transcript instead of pasting.
- **No pill, or it sits in the top-left corner** — the extension is outdated or not loaded. Reinstall it with `sudo ./scripts/setup.sh`, then log out and back in (GNOME Shell only reloads extension code on a new session). Verify with `benedict doctor` and preview it with `benedict pill`.
- **ydotool errors** — `systemctl --user status ydotoold`; the socket is `$XDG_RUNTIME_DIR/.ydotool_socket`.

## Uninstall

```bash
systemctl --user disable --now benedict ydotoold
uv tool uninstall benedict
sudo rm /etc/keyd/default.conf /etc/udev/rules.d/70-benedict-input.rules \
        /etc/udev/rules.d/99-benedict-uinput.rules \
        /usr/share/man/man1/benedict.1 \
        "$HOME/.config/systemd/user/ydotoold.service" \
        "$HOME/.config/systemd/user/benedict.service"
rm -rf ~/.local/share/benedict ~/.local/state/benedict
gnome-extensions disable benedict-focus@benedict
rm -rf ~/.local/share/gnome-shell/extensions/benedict-focus@benedict
```

## Version history

See [CHANGELOG.md](CHANGELOG.md) for the full history.

- **v0.2.1** — project logo in the README and on the website, and a `benedict(1)` man page so `man benedict` explains the CLI.
- **v0.2** — floating status pill with live state, the active microphone, and the streaming transcript with a blinking caret; configurable position; notifications mirror the pill (`Listening` + microphone, `Pasted N words` + paste method); `benedict doctor` is now a colored 9-point checklist; new `[ui]` settings, `benedict config`, and `benedict pill`; fixed the pill rendering in the top-left corner on GNOME 50.
- **v0.1** — first release: hold-to-talk via keyd, hidden Chrome + ChatGPT dictation, focus-aware paste (`Ctrl+V`, `Ctrl+Shift+V`, `Shift+Insert`), clipboard restore, transcript history, sound cues, and notifications.

## Notes and limitations

- This automates your own logged-in ChatGPT session for personal use. It is not affiliated with OpenAI, may break when the web UI or usage limits change, and is subject to OpenAI's terms.
- First dictation after idle shutdown takes 3–5 seconds while Chrome starts.
- The browser runs under Xvfb and captures the system default microphone; audio never leaves your machine except as part of the ChatGPT dictation session.
