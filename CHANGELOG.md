# Changelog

All notable changes to Benedict are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-10-21

### Added

- `RightCtrl+H` opens a picker of the last 10 transcripts in the GNOME extension; `Enter` pastes the newest, `1`–`9`/`0` or the arrow keys pick another, `Esc` closes. Without the extension it pastes the newest directly. Configurable with `hotkey.history_key` / `hotkey.history_hint`; keyd maps `h = f23` in the dictation layer.
- `benedict history` lists the saved transcripts and `benedict paste [N]` pastes one without saving it again.
- When ChatGPT needs a login, a notification with a **Log in** button opens the login window and reconnects afterwards, with no terminal needed.
- `benedict doctor` checks the ChatGPT connection (from the running daemon, or live when it is stopped) and the history chord.

### Fixed

- Tapping the hotkey while a transcript was still being processed started a recording that ignored the release and kept listening for up to `max_duration_sec`.

- Dictation failing with "chat composer not found" after a reboot or a long sleep. The cause was Cloudflare re-checking the hidden browser, which Playwright marked as automated (`navigator.webdriver`). The hidden Chrome now launches without the automation flag, waits for ChatGPT to become ready, and when a Cloudflare check sticks, loads ChatGPT once in a plain hidden Chrome to renew the clearance, the same thing `benedict login` used to fix by hand.
- Pages that fail to load (for example when the network is not up yet) are reloaded instead of failing every press until a restart.
- `benedict login` reported "Not logged in" on a logged-in session because ChatGPT removed the profile button it looked for; login is now checked through `/api/auth/session`.
- Error messages now say what went wrong (Cloudflare, logged out, or offline) instead of always suggesting `benedict login`.

### Changed

- The transcript history keeps only the last 10 entries.
- After resuming from sleep, Benedict drops the stale browser and warms a fresh one in the background.
- `benedict login` pauses and restarts the `benedict` service itself, so stopping it first is no longer needed.
- The status pill shows "Reconnecting to ChatGPT…" while the clearance is renewed.

## [0.2.1] - 2026-09-21

### Added

- Project logo (`assets/logo.svg`), shown in the README and used as the favicon on the website.
- `benedict(1)` man page, installed by `scripts/setup.sh`, so `man benedict` works.

## [0.2.0] - 2026-09-21

### Added

- Status pill now shows the active microphone and the streaming transcript with a blinking caret, with configurable position (`bottom-center`, `bottom-right`, `top-center`, `top-right`) and edge margin.
- `benedict config` prints the effective settings; `--edit` opens the config file in `$EDITOR` (creating it from the defaults if missing).
- `benedict pill` plays a demo of every pill state, with `--position` and `--force`.
- `benedict doctor` is now a colored checklist with per-check hints, right-aligned details, and a pass/fail summary (`--no-color` to disable color).
- CI workflow running Ruff and Pytest with coverage, and status badges in the README.

### Changed

- Desktop notifications mirror the pill: `Listening` with the microphone, and `Pasted N words` with the paste method used.
- New `[ui]` settings: `pill`, `pill_position`, `pill_margin`, and `notify_while_pill`. Invalid positions fall back to `bottom-center`, and margins are clamped to `0`–`400`.
- Insertion reports the combo used (`Ctrl+V`, `Ctrl+Shift+V`, `Shift+Insert`, or `Typed`) instead of a generic message.
- Pill position, margin, and visibility are driven live by the daemon state payload.

### Fixed

- Status pill rendering in the top-left corner on GNOME 50; positioning now accounts for the top panel and the dock.
- Transcript now persists in the pill through the `finalizing` and `inserting` states.

### Tests

- Added coverage for doctor rendering and session-cookie detection, UI config overrides and margin clamping, the daemon UI payload, and combo labels.

## [0.1.0] - 2026-09-20

### Added

- Hold-to-talk dictation: keyd maps `RightCtrl+Space` to `F24` through a timing-independent layer.
- Hidden Chrome under Xvfb driving ChatGPT's web dictation via Playwright.
- Focus-aware insertion: `Ctrl+V`, `Ctrl+Shift+V` in terminals, and a `Shift+Insert` fallback, with clipboard restore.
- `ydotoold` and `benedict` systemd user services, udev `uaccess` rules, and `scripts/setup.sh`.
- `benedict` CLI: `doctor`, `login` (`--import` copies an existing browser session), `probe`, `last`, `status`, and `test-hotkey`.
- Desktop notifications and sound cues, with transcript history in `~/.local/state/benedict`.
- GNOME Shell extension publishing the focused window class and a basic status pill.

[0.3.0]: https://github.com/Anikate-De/benedict/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Anikate-De/benedict/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Anikate-De/benedict/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Anikate-De/benedict/releases/tag/v0.1.0
