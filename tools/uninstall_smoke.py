"""Drive the uninstaller window without a human clicking.

Mirrors ``setup_smoke.py``: press 卸载, wait for the queued "done" event, and
check the window reached its finished state instead of freezing on a disabled
button.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uninstaller  # noqa: E402


def main() -> int:
    # point the uninstaller at a throwaway folder: the point of this test is the
    # threading plumbing, and deleting the real install from here would be rude
    sandbox = Path(tempfile.mkdtemp(prefix="gpb-uninstall-"))
    (sandbox / "GProBattery.exe").write_bytes(b"x")
    uninstaller.install_dir = lambda: sandbox
    uninstaller.start_menu_shortcut = lambda: sandbox / "menu.lnk"
    uninstaller.desktop_shortcut = lambda: sandbox / "desk.lnk"
    uninstaller.config_dir = lambda: sandbox / "cfg"
    uninstaller.remove_registry = lambda: None

    win = uninstaller.UninstallWindow()
    win.root.after(80, win._drain)
    win.root.after(300, win._on_uninstall)

    deadline = time.time() + 120
    status = ""
    while time.time() < deadline:
        win.root.update()
        status = win.status.cget("text")
        if "已卸载" in status or "失败" in status:
            break
        time.sleep(0.05)

    ok = "已卸载" in status
    print(f"{'ok ' if ok else 'BAD'} status={status}")
    win.root.destroy()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
