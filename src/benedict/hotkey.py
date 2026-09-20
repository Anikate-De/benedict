from __future__ import annotations

import select
import threading
import time
from collections.abc import Callable

from evdev import InputDevice, ecodes, list_devices


class HotkeyError(RuntimeError):
    pass


class HotkeyListener(threading.Thread):
    def __init__(self, key_name: str, on_press: Callable[[], None], on_release: Callable[[], None]):
        super().__init__(daemon=True, name="hotkey")
        self.keycode = ecodes.ecodes.get(f"KEY_{key_name.upper()}")
        if self.keycode is None:
            raise HotkeyError(f"unknown key: {key_name}")
        self.on_press = on_press
        self.on_release = on_release
        self._stop = threading.Event()
        self._devices: list[InputDevice] = []
        self._held = False

    def _scan(self) -> None:
        for path in list_devices():
            try:
                device = InputDevice(path)
            except (PermissionError, OSError):
                continue
            keys = device.capabilities(absinfo=False).get(ecodes.EV_KEY, [])
            if self.keycode in keys:
                self._devices.append(device)

    def start(self) -> None:
        self._scan()
        if not self._devices:
            raise HotkeyError(
                "no readable keyboard found; add yourself to the input group "
                "(sudo usermod -aG input $USER) and log back in"
            )
        super().start()

    def run(self) -> None:
        while not self._stop.is_set():
            if not self._devices:
                time.sleep(1.0)
                self._scan()
                continue
            try:
                ready, _, _ = select.select(self._devices, [], [], 0.2)
            except (OSError, ValueError):
                self._devices = []
                continue
            for device in ready:
                try:
                    events = device.read()
                except OSError:
                    self._devices.remove(device)
                    device.close()
                    continue
                for event in events:
                    if event.type != ecodes.EV_KEY or event.code != self.keycode:
                        continue
                    if event.value == 1 and not self._held:
                        self._held = True
                        self.on_press()
                    elif event.value == 0 and self._held:
                        self._held = False
                        self.on_release()

    def stop(self) -> None:
        self._stop.set()
        for device in self._devices:
            device.close()
        self._devices = []
