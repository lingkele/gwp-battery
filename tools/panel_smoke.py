"""Smoke test for the panel lifecycle: open, hide, reopen, stop.

Runs the real Panel on the main thread with a stub app, so it exercises the
queue, the show/hide pump and the shutdown path without touching hardware.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gwp.battery import BatteryState  # noqa: E402
from gwp.panel import Panel  # noqa: E402


class StubApp:
    def __init__(self) -> None:
        self.state = BatteryState(present=True, percent=62, charging=False,
                                  voltage_mv=3870, name="G Pro Wireless Gaming Mouse",
                                  detail="HID++ 0x1001")
        self.notify_low = True
        self.autostart = False
        self.calls: list[str] = []

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "history": [(time.time() - 60 * i, 60 + i % 5) for i in range(30)],
            "updated": time.time(),
            "detail": self.state.detail,
            "accent": "#3DDC84",
            "notify_low": self.notify_low,
            "autostart": self.autostart,
        }

    def render_icon(self):
        from PIL import Image

        return Image.new("RGBA", (64, 64), (0, 0, 0, 0))

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

    ok = all(passed for _, passed in results) and len(results) == 3 and elapsed < 15
    for name, passed in results:
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    print(f"{'ok  ' if elapsed < 15 else 'FAIL'} stopped after {elapsed:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
