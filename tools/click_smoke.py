"""Click test for the devices page: clicking another row must select it.

Everything Tk-related happens on the Tk thread (the real Panel on the main
thread, driven by root.after), because generating events from a worker thread
is not safe. The click itself is a genuine <Button-1> dispatched to the widget
that actually sits under the pointer, so it exercises the same bindings a real
mouse press does.
"""
from __future__ import annotations

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
                        present=True, transport="receiver",
                        detail="receiver slot 1 - HID++ 0x1001"),
            DeviceState(id="bt:BTHLE\\DEV_F1551F37BD9A", name="Varmilo VD-1",
                        kind="keyboard", percent=100, charging=False,
                        present=True, transport="bluetooth",
                        detail="bluetooth - Windows battery service"),
        ]
        self.current = self.devices[0]
        self.notify_low = True
        self.autostart = False
        self.calls: list[str] = []
        self.panel: Panel | None = None

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
        # The real TrayApp pushes a fresh snapshot here, and the panel then has
        # to show it immediately instead of waiting for the next poll.
        if self.panel is not None:
            self.panel.push(self.snapshot())

    def refresh_now(self) -> None:
        self.calls.append("refresh")

    def show_help(self) -> None:
        self.calls.append("help")

    def quit_app(self) -> None:
        self.calls.append("quit")

    def set_notify_low(self, value: bool) -> None:
        self.notify_low = value

    def set_autostart(self, value: bool) -> None:
        self.autostart = value


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def find_text(root, text: str):
    for widget in walk(root):
        try:
            if widget.cget("text") == text:
                return widget
        except tk.TclError:
            continue
    return None


def _texts(root) -> list[str]:
    out: list[str] = []
    for widget in walk(root):
        try:
            out.append(str(widget.cget("text")))
        except tk.TclError:
            continue
    return out


def main() -> int:
    app = StubApp()
    panel = Panel(app)
    app.panel = panel
    results: list[tuple[str, bool]] = []

    def click_row() -> None:
        if not panel._visible or panel._page != "devices":
            results.append(("devices page before click", False))
            panel.stop()
            return
        label = find_text(panel._pages["devices"], "Varmilo VD-1")
        if label is None:
            results.append(("found the second row", False))
            panel.stop()
            return
        results.append(("found the second row", True))
        # A real press lands on the widget under the cursor; children of the row
        # are exactly what the pointer hits, so dispatch there.
        x = max(1, label.winfo_width() // 2)
        y = max(1, label.winfo_height() // 2)
        label.event_generate("<Button-1>", x=x, y=y, when="now")
        panel._root.after(400, check)

    def check() -> None:
        results.append(("select_device called", any(
            call == "select=bt:BTHLE\\DEV_F1551F37BD9A" for call in app.calls)))
        results.append(("current is the keyboard", app.current.id.startswith("bt:")))
        results.append(("switched to detail page", panel._page == "detail"))
        results.append(("detail shows the new device", any(
            call == "Varmilo VD-1"
            for call in _texts(panel._pages["detail"]))))
        panel._root.after(200, finish)

    def finish() -> None:
        panel.stop()

    def schedule(root) -> None:
        def step_open() -> None:
            panel.push(app.snapshot())
            panel.open(page="devices")

        root.after(300, step_open)
        root.after(1200, click_row)

    original_build = panel._build

    def build(root) -> None:
        original_build(root)
        schedule(root)

    panel._build = build  # type: ignore[method-assign]

    started = time.time()
    panel.run()
    elapsed = time.time() - started

    ok = len(results) == 5 and all(passed for _, passed in results) and elapsed < 15
    for name, passed in results:
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    print(f"{'ok  ' if elapsed < 15 else 'FAIL'} finished in {elapsed:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
