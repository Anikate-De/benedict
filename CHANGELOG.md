# Changelog

All notable changes to Benedict are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/Anikate-De/benedict/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Anikate-De/benedict/releases/tag/v0.1.0
