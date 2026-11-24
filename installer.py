"""Per-user installer for the battery tray app.

Ships as one ``GProBattery-Setup.exe`` that carries the application and its
uninstaller inside.  Nothing here needs administrator rights: the app lands in
``%LOCALAPPDATA%\\Programs\\GProBattery``, shortcuts go to the current user's
Start menu and desktop, and the uninstall entry lives under ``HKCU``.

Run with ``--silent`` to install without a window (used when re-installing from
an unattended script); ``--uninstall`` is handled by the bundled uninstaller.
"""
from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import ttk

APP_NAME = "GProBattery"
APP_TITLE = "设备电量"
APP_VERSION = "1.2.2"
APP_DESC = "罗技无线鼠标和键盘的电量，常驻托盘并带一个电量面板。"
PAYLOAD_FILES = ("GProBattery.exe", "GProBatteryUninstall.exe")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"


# -- locations -------------------------------------------------------------
def install_dir() -> Path:
    base = Path.home() / "AppData" / "Local"
    return Path(_local_appdata()) / "Programs" / APP_NAME


def _local_appdata() -> str:
    import os

    return os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")


def payload_dir() -> Path:
    """Where the bundled exes live (inside the onefile extraction dir)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "payload"
    return Path(__file__).resolve().parent / "dist"


def start_menu_shortcut() -> Path:
    import os

    programs = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(programs) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_TITLE}.lnk"


def desktop_shortcut() -> Path:
    desktop = Path.home() / "Desktop"
    return desktop / f"{APP_TITLE}.lnk"


# -- helpers ---------------------------------------------------------------
def kill_running() -> None:
    """An update cannot overwrite an exe that is still loaded."""
    try:
        subprocess.run(["taskkill", "/IM", "GProBattery.exe", "/F"],
                       capture_output=True, creationflags=0x08000000, check=False)
    except OSError:
        pass


def make_shortcut(link: Path, target: Path) -> bool:
    """Create a .lnk through the WScript shell (no extra dependencies)."""
    link.parent.mkdir(parents=True, exist_ok=True)
    script = f'''
Set sh = CreateObject("WScript.Shell")
Set lnk = sh.CreateShortcut("{link}")
lnk.TargetPath = "{target}"
lnk.WorkingDirectory = "{target.parent}"
lnk.IconLocation = "{target}"
lnk.Description = "{APP_TITLE}"
lnk.Save
'''
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False,
                                        encoding="utf-16", newline="\r\n") as fh:
            fh.write(script)
            path = fh.name
        subprocess.run(["cscript", "//nologo", path], capture_output=True,
                       creationflags=0x08000000, check=False)
        Path(path).unlink(missing_ok=True)
        return link.exists()
    except OSError:
        return False


def remove_shortcut(link: Path) -> None:
    try:
        link.unlink()
    except OSError:
        pass


def set_autostart(enabled: bool, exe: Path) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def estimated_size(path: Path) -> int:
    total = 0
    for item in path.glob("*"):
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total // 1024          # registry wants KiB


def write_uninstall_entry(target: Path) -> None:
    uninstaller = target / "GProBatteryUninstall.exe"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, f"{APP_TITLE} ({APP_NAME})")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(target / "GProBattery.exe"))
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "lingkele")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(target))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller}"')
        winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ,
                          f'"{uninstaller}" --silent')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, estimated_size(target))


# -- the install itself ----------------------------------------------------
def install(with_autostart: bool, with_desktop: bool, report=lambda text: None) -> str:
    source = payload_dir()
    missing = [name for name in PAYLOAD_FILES if not (source / name).exists()]
    if missing:
        raise RuntimeError("安装包不完整：" + "、".join(missing))

    target = install_dir()
    report("正在关闭正在运行的旧版本…")
    kill_running()
    target.mkdir(parents=True, exist_ok=True)

    for name in PAYLOAD_FILES:
        report(f"正在复制 {name}…")
        shutil.copy2(source / name, target / name)

    exe = target / "GProBattery.exe"
    report("正在登记卸载信息…")
    write_uninstall_entry(target)

    report("正在创建开始菜单快捷方式…")
    make_shortcut(start_menu_shortcut(), exe)
    if with_desktop:
        report("正在创建桌面快捷方式…")
        make_shortcut(desktop_shortcut(), exe)
    else:
        remove_shortcut(desktop_shortcut())

    report("正在设置开机启动…")
    set_autostart(with_autostart, exe)
    return str(target)


# -- window ----------------------------------------------------------------
class SetupWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"{APP_TITLE} {APP_VERSION} 安装向导")
        self.root.resizable(False, False)
        self.root.configure(bg="#f4f5f7")
        self.busy = False
        self.done = False
        self._events: queue.Queue = queue.Queue()
        self._build()

    def _build(self) -> None:
        wrap = tk.Frame(self.root, bg="#f4f5f7", padx=24, pady=20)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text=f"{APP_TITLE} {APP_VERSION}", bg="#f4f5f7", fg="#15171c",
                 font=("Microsoft YaHei UI", 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(wrap, text=APP_DESC, bg="#f4f5f7", fg="#5d6470", justify="left",
                 wraplength=430, anchor="w",
                 font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(6, 12))

        box = tk.Frame(wrap, bg="#ffffff", highlightbackground="#dfe2e8",
                       highlightthickness=1)
        box.pack(fill="x")
        inside = tk.Frame(box, bg="#ffffff", padx=14, pady=12)
        inside.pack(fill="x")
        tk.Label(inside, text="安装位置", bg="#ffffff", fg="#7b8290", anchor="w",
                 font=("Microsoft YaHei UI", 9)).pack(fill="x")
        tk.Label(inside, text=str(install_dir()), bg="#ffffff", fg="#15171c",
                 anchor="w", wraplength=400, justify="left",
                 font=("Consolas", 9)).pack(fill="x", pady=(2, 0))

        self.desktop = tk.BooleanVar(value=True)
        self.autostart = tk.BooleanVar(value=True)
        opts = tk.Frame(wrap, bg="#f4f5f7")
        opts.pack(fill="x", pady=(12, 0))
        for text, var in (("创建桌面快捷方式", self.desktop),
                          ("开机自动启动", self.autostart)):
            ttk.Checkbutton(opts, text=text, variable=var).pack(anchor="w", pady=1)

        self.status = tk.Label(wrap, text="无需管理员权限，装给当前用户。",
                               bg="#f4f5f7", fg="#5d6470", anchor="w",
                               font=("Microsoft YaHei UI", 9))
        self.status.pack(fill="x", pady=(14, 0))

        buttons = tk.Frame(wrap, bg="#f4f5f7")
        buttons.pack(fill="x", pady=(12, 0))
        self.install_button = ttk.Button(buttons, text="安装", command=self._on_install,
                                         width=12)
        self.install_button.pack(side="right")
        self.close_button = ttk.Button(buttons, text="关闭", command=self._on_close,
                                       width=8)
        self.close_button.pack(side="right", padx=(0, 8))

        self.root.bind("<Return>", lambda _event: self._on_install())

    def _report(self, text: str) -> None:
        """Called from the install thread — only touches the queue."""
        self._events.put(("status", text))

    def _drain(self) -> None:
        """Main-thread only: apply queued events, then reschedule."""
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "status":
                    self.status.configure(text=payload)
                elif kind == "done":
                    self._done(payload)
                elif kind == "error":
                    self._failed(payload)
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _on_install(self) -> None:
        if self.busy or self.done:
            return
        self.busy = True
        self.install_button.state(["disabled"])
        self.close_button.configure(text="隐藏")
        # read the checkboxes here: Tk variables must not be read off-thread
        autostart = bool(self.autostart.get())
        desktop = bool(self.desktop.get())

        def work() -> None:
            try:
                target = install(autostart, desktop, self._report)
            except Exception as exc:            # noqa: BLE001 - show it, never crash
                self._events.put(("error", str(exc)))
                return
            self._events.put(("done", Path(target)))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, folder: Path) -> None:
        self.busy = False
        self.done = True
        self.status.configure(text=f"安装完成，已放到 {folder}")
        self.install_button.configure(text="运行",
                                      command=lambda: self._launch(folder / "GProBattery.exe"))
        self.install_button.state(["!disabled"])
        self.close_button.configure(text="关闭")

    def _failed(self, message: str) -> None:
        self.busy = False
        self.status.configure(text=f"安装失败：{message}")
        self.install_button.state(["!disabled"])
        self.close_button.configure(text="关闭")

    def _launch(self, exe: Path) -> None:
        try:
            subprocess.Popen([str(exe)], creationflags=0x00000008,  # DETACHED_PROCESS
                             cwd=str(exe.parent))
        except OSError as exc:
            self.status.configure(text=f"启动失败：{exc}")
            return
        self.root.after(600, self._on_close)

    def _on_close(self) -> None:
        self.root.destroy()

    def run(self) -> int:
        self.root.after(80, self._drain)
        self.root.mainloop()
        return 0


def main() -> int:
    silent = "--silent" in sys.argv
    if silent:
        try:
            install(True, True, lambda text: None)
        except Exception:              # noqa: BLE001 - quiet mode must not pop up
            return 1
        return 0
    return SetupWindow().run()


if __name__ == "__main__":
    sys.exit(main())
