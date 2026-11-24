"""Render the real panel with real device data and save a PNG of each page.

Usage: python tools/panel_preview.py detail out.png
       python tools/panel_preview.py devices out.png

The window is moved below the visible desktop before it is captured, so the
screenshot does not steal focus or cover whatever the user is doing.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gwp.devices import DeviceMonitor, pick  # noqa: E402
from gwp.panel import Panel  # noqa: E402
from tools import capture  # noqa: E402


class LiveApp:
    """The bits of TrayApp the panel talks to, backed by real hardware."""

    def __init__(self) -> None:
        self.monitor = DeviceMonitor()
        self.devices = self.monitor.poll()
        self.current = pick(self.devices, None)
        self.notify_low = True
        self.autostart = False
        self.updated = time.time()

    def snapshot(self) -> dict:
        state = self.current
        return {
            "state": state,
            "devices": self.devices,
            "current": state.id,
            "history": [(self.updated - 60 * i, min(100, (state.percent or 50) + i % 4))
                        for i in range(40, 0, -1)],
            "updated": self.updated,
            "detail": state.detail,
            "accent": state.accent,
            "notify_low": self.notify_low,
            "autostart": self.autostart,
        }

    def render_icon(self):
        from PIL import Image

        return Image.new("RGBA", (64, 64), (0, 0, 0, 0))

    def select_device(self, device_id):
        self.current = pick(self.devices, device_id)

    def refresh_now(self):
        pass

    def show_help(self):
        pass

    def quit_app(self):
        pass

    def set_notify_low(self, value):
        self.notify_low = bool(value)

    def set_autostart(self, value):
        self.autostart = bool(value)


def main() -> int:
    page = sys.argv[1] if len(sys.argv) > 1 else "detail"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else f"panel-{page}.png")
    app = LiveApp()
    panel = Panel(app)

    def driver() -> None:
        try:
            time.sleep(0.8)
            panel.push(app.snapshot())
            panel.open(page=page)
            time.sleep(1.6)
            handles = capture.find_windows("设备电量")
            if not handles:
                print("no window")
                return
            hwnd = max(handles, key=lambda h: capture.window_size(h)[0])
            capture.user32.SetWindowPos(hwnd, None, 100, 1500, 0, 0,
                                        capture.SWP_NOSIZE | capture.SWP_NOZORDER)
            time.sleep(0.5)
            image = capture.capture(hwnd)
            image.save(out)
            print(f"captured {image.size[0]}x{image.size[1]} -> {out}")
        except Exception as exc:  # noqa: BLE001 - a preview must never hang
            print(f"preview failed: {type(exc).__name__}: {exc}")
        finally:
            panel.stop()

    threading.Thread(target=driver, daemon=True).start()
    panel.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
