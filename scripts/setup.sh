#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "run with sudo: sudo ./scripts/setup.sh" >&2
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_ID="$(id -u "$TARGET_USER"):$(id -g "$TARGET_USER")"

echo "==> installing system packages"
apt-get update -qq
apt-get install -y xvfb keyd wl-clipboard libnotify-bin

echo "==> granting uinput access to the input group"
modprobe uinput || true
install -m 644 "$REPO/udev/99-benedict-uinput.rules" /etc/udev/rules.d/99-benedict-uinput.rules
udevadm control --reload-rules
udevadm trigger --name-match=uinput || true

echo "==> adding $TARGET_USER to the input group"
usermod -aG input "$TARGET_USER"

echo "==> installing GNOME Shell focus extension"
EXT_DIR="$TARGET_HOME/.local/share/gnome-shell/extensions/benedict-focus@benedict"
install -d -o "$TARGET_ID" "$EXT_DIR"
install -m 644 -o "$TARGET_ID" "$REPO/gnome-extension/metadata.json" \
  "$REPO/gnome-extension/extension.js" "$EXT_DIR/"
runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${TARGET_ID%%:*}/bus" \
  gnome-extensions enable benedict-focus@benedict 2>/dev/null || true

echo "==> installing keyd chord config"
install -d /etc/keyd
if [[ -f /etc/keyd/default.conf ]]; then
  cp /etc/keyd/default.conf "/etc/keyd/default.conf.bak.$(date +%s)"
fi
install -m 644 "$REPO/keyd/default.conf" /etc/keyd/default.conf
if keyd check >/dev/null 2>&1; then
  systemctl enable --now keyd
  keyd reload || true
else
  echo "WARNING: keyd rejected the config, inspect with: sudo keyd check" >&2
fi

echo "==> installing ydotoold user service"
YDOTOOLD="$(command -v ydotoold || true)"
[[ -z "$YDOTOOLD" && -x /usr/local/bin/ydotoold ]] && YDOTOOLD=/usr/local/bin/ydotoold
[[ -z "$YDOTOOLD" && -x /usr/bin/ydotoold ]] && YDOTOOLD=/usr/bin/ydotoold
if [[ -z "$YDOTOOLD" ]]; then
  echo "ydotoold not found; install ydotool first" >&2
  exit 1
fi
install -d -o "$TARGET_ID" "$TARGET_HOME/.config/systemd/user"
sed "s|@YDOTOOLD@|$YDOTOOLD|" "$REPO/systemd/ydotoold.service" \
  > "$TARGET_HOME/.config/systemd/user/ydotoold.service"
chown "$TARGET_ID" "$TARGET_HOME/.config/systemd/user/ydotoold.service"

echo "==> installing benedict"
UV="$(command -v uv || true)"
[[ -z "$UV" ]] && UV="$TARGET_HOME/.local/bin/uv"
runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" "$UV" tool install --editable "$REPO"

install -m 644 -o "$TARGET_ID" "$REPO/systemd/benedict.service" \
  "$TARGET_HOME/.config/systemd/user/benedict.service"

cat <<EOF

Setup complete. Next steps:
  1. Log out and back in (input group + udev rule + shell extension).
  2. benedict doctor
  3. benedict login        # log in to ChatGPT once, then close the window
  4. systemctl --user enable --now ydotoold benedict
  5. benedict test-hotkey  # hold RightCtrl+Space, expect press/release events

If the focus extension did not activate, enable it after logging back in:
  gnome-extensions enable benedict-focus@benedict
EOF
