#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "run with sudo: sudo ./scripts/setup.sh" >&2
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_GID="$(id -g "$TARGET_USER")"
TARGET_ID="$TARGET_UID:$TARGET_GID"

echo "==> installing system packages"
apt-get update -qq
apt-get install -y xvfb keyd wl-clipboard libnotify-bin libsecret-tools

echo "==> granting input access via udev uaccess ACLs"
modprobe uinput || true
install -m 644 "$REPO/udev/70-benedict-input.rules" /etc/udev/rules.d/70-benedict-input.rules
install -m 644 "$REPO/udev/99-benedict-uinput.rules" /etc/udev/rules.d/99-benedict-uinput.rules
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=input
udevadm trigger --action=change --name-match=uinput || true

echo "==> adding $TARGET_USER to the input group as a fallback"
usermod -aG input "$TARGET_USER"

echo "==> installing GNOME Shell focus extension"
EXT_DIR="$TARGET_HOME/.local/share/gnome-shell/extensions/benedict-focus@benedict"
install -d -o "$TARGET_UID" -g "$TARGET_GID" "$EXT_DIR"
install -m 644 -o "$TARGET_UID" -g "$TARGET_GID" "$REPO/gnome-extension/metadata.json" \
  "$REPO/gnome-extension/extension.js" "$EXT_DIR/"
runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$TARGET_UID/bus" \
  gnome-extensions enable benedict-focus@benedict 2>/dev/null || true
chown -R "$TARGET_ID" "$TARGET_HOME/.local/share/gnome-shell" 2>/dev/null || true

echo "==> installing keyd chord config"
install -d /etc/keyd
if [[ -f /etc/keyd/default.conf ]]; then
  cp /etc/keyd/default.conf "/etc/keyd/default.conf.bak.$(date +%s)"
fi
install -m 644 "$REPO/keyd/default.conf" /etc/keyd/default.conf
KEYD_BIN="$(command -v keyd.rvaiya || command -v keyd || true)"
systemctl enable --now keyd
if [[ -n "$KEYD_BIN" ]]; then
  "$KEYD_BIN" reload || true
else
  echo "WARNING: keyd binary not found" >&2
fi
if ! systemctl is-active --quiet keyd; then
  echo "WARNING: keyd is not running, see: journalctl -u keyd -n 20" >&2
fi

echo "==> installing ydotoold user service"
YDOTOOLD="$(command -v ydotoold || true)"
if [[ -z "$YDOTOOLD" && -x /usr/local/bin/ydotoold ]]; then
  YDOTOOLD=/usr/local/bin/ydotoold
fi
if [[ -z "$YDOTOOLD" && -x /usr/bin/ydotoold ]]; then
  YDOTOOLD=/usr/bin/ydotoold
fi
if [[ -z "$YDOTOOLD" ]]; then
  echo "ydotoold not found; install ydotool first" >&2
  exit 1
fi
install -d -o "$TARGET_UID" -g "$TARGET_GID" "$TARGET_HOME/.config/systemd/user"
sed "s|@YDOTOOLD@|$YDOTOOLD|" "$REPO/systemd/ydotoold.service" \
  > "$TARGET_HOME/.config/systemd/user/ydotoold.service"
chown "$TARGET_ID" "$TARGET_HOME/.config/systemd/user/ydotoold.service"

echo "==> installing benedict"
UV="$(command -v uv || true)"
if [[ -z "$UV" && -x "$TARGET_HOME/.local/bin/uv" ]]; then
  UV="$TARGET_HOME/.local/bin/uv"
fi
if [[ -z "$UV" ]]; then
  echo "uv not found; install it first: https://docs.astral.sh/uv/" >&2
  exit 1
fi
runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" "$UV" tool install --editable "$REPO"

install -m 644 -o "$TARGET_UID" -g "$TARGET_GID" "$REPO/systemd/benedict.service" \
  "$TARGET_HOME/.config/systemd/user/benedict.service"

cat <<EOF

Setup complete. Next steps:
  1. benedict doctor
  2. benedict login        # log in to ChatGPT once, then close the window
  3. systemctl --user enable --now ydotoold benedict
  4. benedict test-hotkey  # hold RightCtrl+Space, expect press/release events

Input access is granted live through udev uaccess ACLs, so no re-login is needed.
The GNOME focus extension loads on your next login; until then paste falls back to
Shift+Insert, which works in both terminals and GUI apps.
EOF
