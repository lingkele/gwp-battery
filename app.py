"""Logitech wireless mouse battery indicator for the Windows system tray."""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

from gwp.battery import BatteryState, MouseBattery
from gwp.panel import Panel

APP_NAME = "GProBattery"
APP_TITLE = "罗技鼠标电量"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "settings.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
HISTORY_KEEP_SECONDS = 2 * 24 * 3600

COLOR_GOOD = "#3DDC84"
COLOR_MID = "#FFB020"
COLOR_LOW = "#FF5A5A"
COLOR_IDLE = "#9AA0A6"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
]

HELP_TEXT = (
    "左键单击托盘图标（或双击）打开面板，右键打开菜单。\n\n"
    "· 面板里有大号电量表盘、最近一小时的电量曲线，以及低电量提醒、\n"
    "  开机自启两个开关；关掉窗口后程序仍在托盘运行。\n"
    "· 图标在任务栏右下角；如果看不到，点任务栏的 ∧ 打开隐藏图标区，\n"
    "  把它拖到任务栏上即可常驻显示。\n"
    "· 「开机自动启动」会写入当前用户的启动项，无需管理员权限。\n"
    "· 直接读取接收器，无需安装 Logitech G HUB。\n\n"
    "支持通过 Lightspeed / Bolt / Unifying 接收器连接的罗技鼠标，\n"
    "也支持用 USB 线直连的型号。"
)


def load_settings() -> dict:
    defaults = {"style": "percent", "notify_low": True, "poll": 60, "first_run_done": False}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            defaults.update({k: v for k, v in data.items() if k in defaults})
    except (OSError, ValueError):
        pass
    return defaults


def save_settings(settings: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_history() -> list[tuple[float, int]]:
    """Read the stored ``[timestamp, percent]`` samples, dropping stale ones."""
    cutoff = time.time() - HISTORY_KEEP_SECONDS
    samples: list[tuple[float, int]] = []
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return samples
    if not isinstance(raw, list):
        return samples
    for item in raw:
        try:
            ts, pct = float(item[0]), int(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if ts >= cutoff and 0 <= pct <= 100:
            samples.append((ts, pct))
    samples.sort(key=lambda sample: sample[0])
    return samples


def save_history(samples: list[tuple[float, int]]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = [[round(ts, 1), pct] for ts, pct in samples[-2880:]]
        HISTORY_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    script = Path(__file__).resolve()
    return f'"{exe}" "{script}"'


def is_autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def level_color(percent: int | None) -> str:
    if percent is None:
        return COLOR_IDLE
    if percent <= 20:
        return COLOR_LOW
    if percent <= 50:
        return COLOR_MID
    return COLOR_GOOD


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_text_icon(percent: int | None, charging: bool) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    label = "--" if percent is None else str(percent)
    font_size = 46 if len(label) <= 2 else 36
    font = load_font(font_size)
    box = draw.textbbox((0, 0), label, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    pos = ((size - w) / 2 - box[0], (size - h) / 2 - box[1] - 2)
    color = level_color(percent)
    draw.text(pos, label, font=font, fill=color, stroke_width=3, stroke_fill="#101418")
    if charging:
        bx, by = 48, 44
        draw.polygon([(bx + 6, by), (bx - 2, by + 12), (bx + 4, by + 12),
                      (bx - 2, by + 24), (bx + 12, by + 8), (bx + 5, by + 8)],
                     fill="#FFD54A", outline="#101418")
    return img


def draw_battery_icon(percent: int | None, charging: bool) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = 5, 14, 52, 50
    # dark rim + white rim so the glyph works on light and dark taskbars
    draw.rounded_rectangle([left - 2, top - 2, right + 2, bottom + 2], radius=9, fill="#101418")
    draw.rounded_rectangle([left, top, right, bottom], radius=7, outline="white", width=3)
    draw.rounded_rectangle([right + 3, 24, right + 9, 40], radius=2, fill="#101418")
    draw.rounded_rectangle([right + 3, 24, right + 8, 40], radius=2, fill="white")
    if percent is None:
        draw.line([(left + 14, (top + bottom) / 2), (right - 14, (top + bottom) / 2)],
                  fill=COLOR_IDLE, width=4)
        return img
    inner_left, inner_right = left + 5, right - 5
    fill_width = int((inner_right - inner_left) * max(0, min(100, percent)) / 100)
    if fill_width > 0:
        draw.rounded_rectangle([inner_left, top + 5, inner_left + fill_width, bottom - 5],
                               radius=3, fill=level_color(percent))
    if charging:
        bx, by = 40, 22
        draw.polygon([(bx + 6, by), (bx - 3, by + 12), (bx + 3, by + 12),
                      (bx - 3, by + 24), (bx + 12, by + 8), (bx + 5, by + 8)],
                     fill="#FFD54A", outline="#101418")
    return img


class TrayApp:
    def __init__(self):
        self.settings = load_settings()
        self.state = BatteryState(detail="启动中")
        self.mouse = MouseBattery()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._ready = False
        self._low_notified = False
        self._was_full = False
        self.history = load_history()
        self.history_writes = 0
        self.updated_at = 0.0
        self.panel = Panel(self)
        self.icon = pystray.Icon(APP_NAME, self._render(), APP_TITLE, menu=self._build_menu())

    # -- shared view of the current reading ---------------------------------
    def render_icon(self) -> Image.Image:
        return self._render()

    def snapshot(self) -> dict:
        """Everything the panel needs, safe to read from another thread."""
        state = self.state
        return {
            "state": state,
            "history": list(self.history[-360:]),
            "updated": self.updated_at,
            "detail": state.detail or "HID++",
            "accent": level_color(state.percent),
            "notify_low": bool(self.settings.get("notify_low", True)),
            "autostart": is_autostart_enabled(),
        }

    def refresh_now(self) -> None:
        self._wake.set()

    def quit_app(self) -> None:
        self._stop.set()
        self._wake.set()
        save_history(self.history)
        try:
            self.mouse.close()
        except Exception:
            pass
        self.panel.stop()
        try:
            self.icon.stop()
        except Exception:
            pass

    def show_help(self) -> None:
        self.panel.show_help(HELP_TEXT)

    def set_notify_low(self, enabled: bool) -> None:
        self.settings["notify_low"] = bool(enabled)
        if enabled:
            self._low_notified = False
        save_settings(self.settings)
        self._refresh_menu()

    def set_autostart(self, enabled: bool) -> None:
        try:
            set_autostart(bool(enabled))
        except OSError:
            pass
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        try:
            self.icon.update_menu()
        except Exception:
            pass

    # -- rendering ----------------------------------------------------------
    def _render(self) -> Image.Image:
        if self.settings.get("style") == "battery":
            return draw_battery_icon(self.state.percent, self.state.charging)
        return draw_text_icon(self.state.percent, self.state.charging)

    def _tooltip(self) -> str:
        name = self.state.name or "罗技无线鼠标"
        if not self.state.present:
            return f"{name} · 未连接（{self.state.detail}）" if self.state.name else "罗技鼠标 · 未找到接收器"
        if self.state.percent is None:
            return f"{name} · 电量未知（{self.state.detail}）"
        parts = [name, f"{self.state.percent}%", self.state.status_text]
        if self.state.voltage_mv:
            parts.append(f"{self.state.voltage_mv} mV")
        return " · ".join(parts)

    def _status_line(self) -> str:
        if not self.state.present:
            return "状态：未连接"
        if self.state.percent is None:
            return "状态：电量未知"
        return f"电量：{self.state.percent}%  {self.state.status_text}"

    def _apply(self) -> None:
        if not self._ready:
            return
        try:
            self.icon.icon = self._render()
            self.icon.title = self._tooltip()
            self.icon.update_menu()
        except Exception:
            pass

    # -- polling ------------------------------------------------------------
    def _poll_forever(self):
        while not self._stop.is_set():
            try:
                state = self.mouse.read()
            except Exception as exc:  # never let the loop die
                state = BatteryState(detail=f"读取异常：{exc}")
            try:
                self._on_state(state)
            except Exception:
                self.state = state
            delay = self._delay()
            self._wake.wait(delay)
            self._wake.clear()

    def _delay(self) -> float:
        if not self.state.present or self.state.percent is None:
            return 5.0
        if self.state.charging:
            return 15.0
        return float(self.settings.get("poll", 60))

    def _on_state(self, state: BatteryState) -> None:
        self.state = state
        self.updated_at = time.time()
        self._record(state)
        self._apply()

        if state.present and state.percent is not None:
            if self.settings.get("notify_low", True):
                if state.percent <= 15 and not state.charging and not self._low_notified:
                    self._low_notified = True
                    self.notify(f"电量只剩 {state.percent}%，该充电了", state.name or APP_TITLE)
                elif state.percent > 20 or state.charging:
                    self._low_notified = False

            if state.full and not self._was_full:
                self.notify("电池已充满", state.name or APP_TITLE)
            self._was_full = state.full

        self.panel.push(self.snapshot())

    def _record(self, state: BatteryState) -> None:
        if not state.present or state.percent is None:
            return
        now = time.time()
        if self.history and now - self.history[-1][0] < 20:
            self.history[-1] = (now, state.percent)
        else:
            self.history.append((now, state.percent))
        cutoff = now - HISTORY_KEEP_SECONDS
        while self.history and self.history[0][0] < cutoff:
            self.history.pop(0)
        self.history_writes += 1
        if self.history_writes % 5 == 0:
            save_history(self.history)

    def notify(self, message: str, title: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    # -- menu actions -------------------------------------------------------
    def _refresh(self, icon=None, item=None):
        self._wake.set()

    def _set_style(self, style: str):
        self.settings["style"] = style
        save_settings(self.settings)
        self._apply()

    def _toggle_low(self, icon, item):
        self.set_notify_low(not self.settings.get("notify_low", True))

    def _toggle_autostart(self, icon, item):
        self.set_autostart(not is_autostart_enabled())

    def _open_panel(self, icon=None, item=None):
        self.panel.open()

    def _help(self, icon, item):
        self.show_help()

    def _quit(self, icon, item):
        self.quit_app()

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(lambda item: self._status_line(), None, enabled=False),
            pystray.MenuItem("打开面板", self._open_panel, default=True),
            pystray.MenuItem("立即刷新", self._refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示百分比", lambda i, it: self._set_style("percent"),
                             checked=lambda item: self.settings.get("style") == "percent", radio=True),
            pystray.MenuItem("显示电池图标", lambda i, it: self._set_style("battery"),
                             checked=lambda item: self.settings.get("style") == "battery", radio=True),
            pystray.MenuItem("低电量提醒（≤15%）", self._toggle_low,
                             checked=lambda item: bool(self.settings.get("notify_low", True))),
            pystray.MenuItem("开机自动启动", self._toggle_autostart,
                             checked=lambda item: is_autostart_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("使用说明", self._help),
            pystray.MenuItem("退出", self._quit),
        )

    def run(self):
        threading.Thread(target=self._poll_forever, daemon=True).start()
        self._wake.set()
        if not self.settings.get("first_run_done"):
            threading.Thread(target=self._first_run_hint, daemon=True).start()
        # Tk owns the main thread; pystray's own loop runs beside it.
        threading.Thread(
            target=self.icon.run, kwargs={"setup": self._on_icon_ready}, daemon=True
        ).start()
        self.panel.run()
        try:
            self.icon.stop()
        except Exception:
            pass

    def _on_icon_ready(self, icon):
        self._ready = True
        icon.visible = True
        self._apply()

    def _first_run_hint(self):
        time.sleep(2.0)
        self.notify("已在托盘运行。左键点击图标查看面板；看不到图标就点任务栏的 ∧ 把它拖出来。",
                    APP_TITLE)
        self.panel.open()
        self.settings["first_run_done"] = True
        save_settings(self.settings)


def single_instance() -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, "Local\\GProBatteryTray")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def enable_dpi_awareness() -> None:
    """Crisp Tk text on scaled displays; harmless when already set."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> int:
    if not single_instance():
        return 0
    enable_dpi_awareness()
    # Keep the startup entry pointing at wherever the app lives now.
    if is_autostart_enabled():
        try:
            set_autostart(True)
        except OSError:
            pass
    app = TrayApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
