"""Uninstaller for the battery tray app.

Removes the program files, both shortcuts, the ``HKCU`` uninstall entry and the
autostart value.  Settings and battery history are kept unless the user ticks
the box, because losing the history for no reason is annoying.

Ships inside the installation folder; deletes itself last through a detached
``cmd`` so Windows can stop loading the file first.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import ttk

APP_NAME = "GProBattery"
APP_TITLE = "设备电量"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
DETACHED = 0x00000008


def install_dir() -> Path:
    # installed next to the app itself, so "my own folder" is the answer
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def start_menu_shortcut() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_TITLE}.lnk"


def desktop_shortcut() -> Path:
    return Path.home() / "Desktop" / f"{APP_TITLE}.lnk"


def kill_running() -> None:
    try:
        subprocess.run(["taskkill", "/IM", "GProBattery.exe", "/F"],
                       capture_output=True, creationflags=0x08000000, check=False)
    except OSError:
        pass


def remove_registry() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except OSError:
        pass


def schedule_delete(folder: Path) -> None:
    """Delete the folder after this process exits."""
    try:
        subprocess.Popen(
            ["cmd", "/c", "ping", "-n", "3", "127.0.0.1", ">nul",
             "&", "rmdir", "/s", "/q", str(folder)],
            creationflags=DETACHED, close_fds=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def uninstall(keep_settings: bool, report=lambda text: None) -> None:
    folder = install_dir()
    if not getattr(sys, "frozen", False) and (folder / "app.py").exists():
        # running from the source tree: deleting it would destroy the checkout
        raise RuntimeError("源码目录里不执行卸载，请用安装目录中的卸载程序")
    report("正在关闭程序…")
    kill_running()
    report("正在删除快捷方式…")
    for link in (start_menu_shortcut(), desktop_shortcut()):
        try:
            link.unlink()
        except OSError:
            pass
    report("正在清理注册表…")
    remove_registry()
    if not keep_settings:
        report("正在删除设置与历史…")
        shutil.rmtree(config_dir(), ignore_errors=True)
    report("正在删除程序文件…")
    schedule_delete(folder)


class UninstallWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"卸载 {APP_TITLE}")
        self.root.resizable(False, False)
        self.root.configure(bg="#f4f5f7")
        self.busy = False
        self._events: queue.Queue = queue.Queue()
        self._build()

    def _build(self) -> None:
        wrap = tk.Frame(self.root, bg="#f4f5f7", padx=24, pady=20)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text=f"卸载 {APP_TITLE}", bg="#f4f5f7", fg="#15171c",
                 font=("Microsoft YaHei UI", 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(wrap, text=f"将从 {install_dir()} 移除程序和快捷方式。",
                 bg="#f4f5f7", fg="#5d6470", justify="left", wraplength=430,
                 anchor="w", font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(6, 12))

        self.keep = tk.BooleanVar(value=True)
        ttk.Checkbutton(wrap, text="保留设置与电量历史（下次安装还在）",
                        variable=self.keep).pack(anchor="w")

        self.status = tk.Label(wrap, text="", bg="#f4f5f7", fg="#5d6470", anchor="w",
                               font=("Microsoft YaHei UI", 9))
        self.status.pack(fill="x", pady=(14, 0))

        buttons = tk.Frame(wrap, bg="#f4f5f7")
        buttons.pack(fill="x", pady=(12, 0))
        self.go = ttk.Button(buttons, text="卸载", command=self._on_uninstall, width=12)
        self.go.pack(side="right")
        ttk.Button(buttons, text="取消", command=self.root.destroy,
                   width=8).pack(side="right", padx=(0, 8))

    def _report(self, text: str) -> None:
        """Called from the worker thread — only touches the queue."""
        self._events.put(("status", text))

    def _drain(self) -> None:
        """Main-thread only: apply queued events, then reschedule."""
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "status":
                    self.status.configure(text=payload)
                elif kind == "error":
                    self._failed(payload)
                elif kind == "done":
                    self._finish()
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _on_uninstall(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.go.state(["disabled"])
        keep = bool(self.keep.get())      # read the Tk variable on the main thread

        def work() -> None:
            try:
                uninstall(keep, self._report)
            except Exception as exc:      # noqa: BLE001
                self._events.put(("error", str(exc)))
                return
            self._events.put(("done", None))

        threading.Thread(target=work, daemon=True).start()

    def _failed(self, message: str) -> None:
        self.status.configure(text=f"卸载失败：{message}")
        self.go.state(["!disabled"])

    def _finish(self) -> None:
        self.status.configure(text="已卸载，剩余文件会在几秒内删除。")
        self.root.after(1200, self.root.destroy)

    def run(self) -> int:
        self.root.after(80, self._drain)
        self.root.mainloop()
        return 0


def main() -> int:
    if "--silent" in sys.argv:
        uninstall(keep_settings=True)
        return 0
    return UninstallWindow().run()


if __name__ == "__main__":
    sys.exit(main())
