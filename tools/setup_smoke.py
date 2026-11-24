"""Drive the installer window end to end without a human clicking.

Runs the real ``SetupWindow`` in this process: it presses 安装 shortly after the
window appears, waits for the queued "done" event to flip ``win.done``, and
reports what the status label said.  Catches the class of bug where the install
thread dies silently and the button stays disabled forever.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import installer  # noqa: E402


def main() -> int:
    win = installer.SetupWindow()
    win.root.after(80, win._drain)          # the same polling loop run() installs
    win.root.after(300, win._on_install)

    deadline = time.time() + 120
    while time.time() < deadline and not win.done:
        win.root.update()
        time.sleep(0.05)

    status = win.status.cget("text")
    button = win.install_button.cget("text")
    state = str(win.install_button.state())
    win.root.destroy()

    ok = win.done and button == "运行" and "安装完成" in status
    print(f"{'ok ' if ok else 'BAD'} done={win.done} button={button} state={state}")
    print(f"    status={status}")
    exe = installer.install_dir() / "GProBattery.exe"
    print(f"{'ok ' if exe.exists() else 'BAD'} {exe} ({exe.stat().st_size if exe.exists() else 0} bytes)")
    return 0 if ok and exe.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
