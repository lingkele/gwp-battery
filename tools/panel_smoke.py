"""Smoke test for the panel lifecycle: open, hide, reopen, devices page, stop.

Runs the real Panel on the main thread with a stub app, so it exercises the
queue, the show/hide pump, the page switch and the shutdown path without
touching hardware.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gwp.devices import DeviceState  # noqa: E402
from gwp.panel import Panel  # noqa: E402


class StubApp:
    def __init__(self) -> None:
        self.devices = [
            DeviceState(id="hidpp:50489:01", name="G Pro Wireless Gaming Mouse",
                        kind="mouse", percent=62, charging=False, voltage_mv=3870,
                        present=True, transport="receiver",
                        detail="接收器 1 号位 · HID++ 0x1001"),
            DeviceState(id="bt:BTHLE\\DEV_F1551F37BD9A", name="Varmilo VD-1",
                        kind="keyboard", percent=100, charging=False,
                        present=True, transport="bluetooth",
                        detail="蓝牙 · Windows 电池服务"),
        ]
        self.current = self.devices[0]
        self.notify_low = True
        self.autostart = False
        self.calls: list[str] = []

    def snapshot(self) -> dict:
        state = self.current
        return {
            "state": state,
            "devices": self.devices,
            "current": state.id,
            "history": [(time.time() - 60 * i, 60 + i % 5) for i in range(30)],
            "updated": time.time(),
            "detail": state.detail,
            "accent": state.accent,
            "notify_low": self.notify_low,
            "autostart": self.autostart,
        }

    def render_icon(self):
        from PIL import Image

        return Image.new("RGBA", (64, 64), (0, 0, 0, 0))

    def select_device(self, device_id: str | None) -> None:
        for device in self.devices:
            if device.id == device_id:
                self.current = device
        self.calls.append(f"select={device_id}")

    def refresh_now(self) -> None:
        self.calls.append("refresh")

    def show_help(self) -> None:
        self.calls.append("help")

    def quit_app(self) -> None:
        self.calls.append("quit")

    def set_notify_low(self, value: bool) -> None:
        self.notify_low = value
        self.calls.append(f"notify_low={value}")

    def set_autostart(self, value: bool) -> None:
        self.autostart = value
        self.calls.append(f"autostart={value}")


def main() -> int:
    app = StubApp()
    panel = Panel(app)
    results: list[tuple[str, bool]] = []

    def driver() -> None:
        time.sleep(1.0)
        panel.push(app.snapshot())
        time.sleep(0.5)
        panel.open()
        time.sleep(1.2)
        results.append(("opened", panel._visible))
        results.append(("detail page", panel._page == "detail"))

        panel.open(page="devices")
        time.sleep(1.0)
        results.append(("devices page", panel._page == "devices" and panel._visible))

        panel.close()
        time.sleep(0.8)
        results.append(("hidden", not panel._visible))
        panel.open()
        time.sleep(1.0)
        results.append(("reopened", panel._visible))
        panel.close()
        time.sleep(0.6)
        panel.stop()

    threading.Thread(target=driver, daemon=True).start()
    started = time.time()
    panel.run()
    elapsed = time.time() - started

    ok = all(passed for _, passed in results) and len(results) == 5 and elapsed < 20
    for name, passed in results:
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    print(f"{'ok  ' if elapsed < 20 else 'FAIL'} stopped after {elapsed:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
