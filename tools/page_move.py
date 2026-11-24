"""Regression test: switching pages must not move the window.

Tk reports the client area through winfo_rootx/y while wm geometry speaks in
frame coordinates, so feeding the former back into "+x+y" used to walk the
window down and right on every page change.
"""
from __future__ import annotations

import re
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gwp.devices import DeviceState  # noqa: E402
from gwp.panel import Panel  # noqa: E402


class StubApp:
    def __init__(self) -> None:
        self.devices = [
            DeviceState(id="hidpp:50489:01", name="G Pro Wireless Gaming Mouse",
                        kind="mouse", percent=62, charging=False, voltage_mv=3870,
                        present=True, transport="receiver", detail="receiver slot 1"),
            DeviceState(id="bt:BTHLE", name="Varmilo VD-1", kind="keyboard",
                        percent=100, charging=False, present=True,
                        transport="bluetooth", detail="bluetooth"),
        ]
        self.current = self.devices[0]
        self.notify_low = True
        self.autostart = False

    def snapshot(self) -> dict:
        state = self.current
        return {
            "state": state, "devices": self.devices, "current": state.id,
            "history": [(time.time() - 60 * i, 60 + i % 5) for i in range(30)],
            "updated": time.time(), "detail": state.detail, "accent": state.accent,
            "notify_low": self.notify_low, "autostart": self.autostart,
        }

    def render_icon(self):
        from PIL import Image
        return Image.new("RGBA", (64, 64), (0, 0, 0, 0))

    def select_device(self, device_id):
        pass

    def refresh_now(self):
        pass

    def show_help(self):
        pass

    def quit_app(self):
        pass

    def set_notify_low(self, value):
        pass

    def set_autostart(self, value):
        pass


def main() -> int:
    app = StubApp()
    panel = Panel(app)
    rows: list[str] = []

    def note(tag: str) -> None:
        root = panel._root
        rows.append(f"{tag:14s} geometry={root.winfo_geometry():12s}"
                    f" rooty={root.winfo_rooty():5d} h={root.winfo_height():4d}"
                    f" page={panel._page}")

    def schedule(root) -> None:
        def start() -> None:
            panel.push(app.snapshot())
            panel.open(page="devices")

        def after_open() -> None:
            note("opened/devices")
            panel.open(page="detail")
            root.after(500, after_detail)

        def after_detail() -> None:
            note("switch->detail")
            panel.open(page="devices")
            root.after(500, after_devices)

        def after_devices() -> None:
            note("switch->devices")
            panel.open(page="detail")
            root.after(500, after_detail2)

        def after_detail2() -> None:
            note("switch->detail")
            root.after(200, panel.stop)

        root.after(300, start)
        root.after(1300, after_open)

    original_build = panel._build

    def build(root) -> None:
        original_build(root)
        schedule(root)

    panel._build = build  # type: ignore[method-assign]
    panel.run()

    for row in rows:
        print(row)

    corners = []
    for row in rows:
        match = re.search(r"geometry=\S*?([+-]\d+)([+-]\d+)", row)
        if match:
            corners.append((int(match.group(1)), int(match.group(2))))
    stable = len(corners) == len(rows) and len(set(corners)) == 1
    print(f"{'ok  ' if stable else 'FAIL'} corner kept at {sorted(set(corners))}")
    return 0 if stable else 1


if __name__ == "__main__":
    sys.exit(main())
