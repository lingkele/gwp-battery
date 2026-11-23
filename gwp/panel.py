"""Desktop panel (Tkinter) for the Logitech mouse battery tray app.

Tkinter owns the main thread's event loop; the pystray icon runs in a worker
thread and only talks to the window through a queue, so nothing here touches
Tk from another thread.  Closing the window just hides it -- the tray icon and
the polling thread keep running.
"""
from __future__ import annotations

import ctypes
import os
import queue
import time
import time
import tkinter as tk
from typing import Any

BG = "#15171C"
CARD = "#1E2128"
CARD_HI = "#272B35"
FG = "#F3F5F9"
MUTED = "#98A0AC"
TRACK = "#2C313B"
HINT = "#6F7885"
COLOR_ACCENT = "#3DDC84"

UI_FONT = "Microsoft YaHei UI"
NUM_FONT = "Segoe UI Semibold"


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    """Blend two ``#rrggbb`` colours; ratio 0 keeps a, 1 gives b."""
    ratio = max(0.0, min(1.0, ratio))
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * ratio):02x}" for x, y in zip(a, b))


class Toggle(tk.Canvas):
    """A small on/off switch drawn on a canvas, so it matches the dark panel."""

    def __init__(self, master, text: str, value: bool, command, *, width: int,
                 height: int, font, fg: str, bg: str, accent: str) -> None:
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._value = bool(value)
        self._command = command
        self._size = (width, height)
        self._accent = accent
        self._label = tk.Label(master, text=text, bg=bg, fg=fg, font=font,
                               anchor="w", cursor="hand2")
        self._label.bind("<Button-1>", self._on_click)
        self.bind("<Button-1>", self._on_click)
        self._redraw()

    def label(self) -> tk.Label:
        return self._label

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        value = bool(value)
        if value != self._value:
            self._value = value
            self._redraw()

    def _on_click(self, _event=None) -> None:
        self._value = not self._value
        self._redraw()
        try:
            self._command(self._value)
        except Exception:
            pass

    def _redraw(self) -> None:
        self.delete("all")
        width, height = self._size
        pad = 2
        track = self._accent if self._value else TRACK
        radius = height / 2
        self.create_oval(pad, pad, pad + height - 2 * pad, height - pad,
                         fill=track, outline=track)
        self.create_oval(width - height + pad, pad, width - pad, height - pad,
                         fill=track, outline=track)
        self.create_rectangle(radius, pad, width - radius, height - pad,
                              fill=track, outline=track)
        knob = height - 2 * pad - 2
        cy = height / 2
        cx = (width - pad - radius) if self._value else (pad + radius)
        self.create_oval(cx - knob / 2, cy - knob / 2, cx + knob / 2, cy + knob / 2,
                         fill="#FFFFFF" if self._value else "#C6CCD6", outline="")


class Panel:
    """The dark window with the gauge, the sparkline and the two switches."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._queue: queue.Queue[dict] = queue.Queue()
        self._root: tk.Tk | None = None
        self._visible = False
        self._wanted_open = False
        self._stopping = False
        self._scale = 1.0
        self._payload: dict = {}
        self._w: dict[str, Any] = {}
        self._placed = False

    # -- called from the tray thread ---------------------------------------
    def push(self, payload: dict) -> None:
        self._queue.put(payload)

    def open(self) -> None:
        self._log("open()")
        self._wanted_open = True
        self.push({})

    def close(self) -> None:
        self._log("close()")
        self._wanted_open = False
        self.push({})

    def toggle(self) -> None:
        if self._visible:
            self.close()
        else:
            self.open()

    def stop(self) -> None:
        self._stopping = True
        self.push({})

    def show_help(self, text: str) -> None:
        self._queue.put({"help": text})

    # -- main thread -------------------------------------------------------
    def run(self) -> None:
        root = tk.Tk()
        self._root = root
        root.withdraw()
        self._build(root)
        root.after(120, self._pump)
        try:
            root.mainloop()
        finally:
            self._root = None

    def _pump(self) -> None:
        root = self._root
        if root is None:
            return
        if self._stopping:
            try:
                root.destroy()
            except Exception:
                pass
            return

        payload = None
        while True:
            try:
                payload = self._queue.get_nowait()
            except queue.Empty:
                break
        if payload:
            if "help" in payload:
                self._show_help(str(payload["help"]))
            else:
                try:
                    self._apply(payload)
                except Exception:
                    pass

        if self._wanted_open and not self._visible:
            self._show()
        elif not self._wanted_open and self._visible:
            self._hide()

        try:
            root.after(150, self._pump)
        except Exception:
            pass

    def _log(self, message: str) -> None:
        if not os.environ.get("GWP_DEBUG"):
            return
        try:
            with open("panel.log", "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} {message}\n")
        except Exception:
            pass

    def _show(self) -> None:
        self._log("_show()")
        root = self._root
        if root is None:
            return
        self._visible = True
        root.deiconify()
        root.update_idletasks()
        if not self._placed:
            # Tk only reports a trustworthy size once the window is mapped,
            # so let it size itself and just park the window in place.
            self._placed = True
            root.geometry("")
            root.update_idletasks()
            width = root.winfo_reqwidth()
            height = root.winfo_reqheight()
            x = max(0, (root.winfo_screenwidth() - width) // 2)
            y = max(0, (root.winfo_screenheight() - height) // 3)
            root.geometry(f"+{x}+{y}")
            root.update_idletasks()
            self._dark_title_bar(root)
            if os.environ.get("GWP_DEBUG"):
                with open("layout.txt", "a", encoding="utf-8") as fh:
                    fh.write(f"mapped={root.winfo_width()}x{root.winfo_height()}"
                             f" req={root.winfo_reqwidth()}x{root.winfo_reqheight()}"
                             f" geom={root.winfo_geometry()}\n")
        root.lift()
        try:
            root.attributes("-topmost", True)
            root.after(600, lambda: root.attributes("-topmost", False))
        except Exception:
            pass

    def _dark_title_bar(self, root: tk.Tk) -> None:
        """Ask DWM for a dark caption so the frame matches the panel."""
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
            dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
            dwm.DwmSetWindowAttribute.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
            value = ctypes.c_int(1)
            for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
                if dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),
                                             attribute, ctypes.byref(value),
                                             ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            pass

    def _hide(self) -> None:
        self._log("_hide()")
        root = self._root
        if root is None:
            return
        self._visible = False
        root.withdraw()

    # -- layout ------------------------------------------------------------
    def _build(self, root: tk.Tk) -> None:
        self._scale = self._system_scale()
        s = self._scale

        def px(value: float) -> int:
            return int(round(value * s))

        def fs(value: float) -> int:
            return max(8, int(round(value * s)))

        self._px, self._fs = px, fs

        root.title("罗技鼠标电量")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        try:
            root.iconphoto(True, self._window_image(root))
        except Exception:
            pass

        pad = px(20)
        tk.Frame(root, bg=BG, width=px(360), height=1).pack()  # stable width

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=pad, pady=(px(16), 0))
        name = tk.Label(head, text="罗技无线鼠标", bg=BG, fg=FG, anchor="w",
                        font=(UI_FONT, -fs(13)), justify="left", wraplength=px(320))
        name.pack(fill="x")
        sub = tk.Label(head, text="正在读取…", bg=BG, fg=MUTED, anchor="w",
                       font=(UI_FONT, -fs(9)))
        sub.pack(fill="x", pady=(px(3), 0))
        self._w["name"] = name
        self._w["sub"] = sub

        gauge = tk.Canvas(root, width=px(210), height=px(196), bg=BG,
                          highlightthickness=0, bd=0)
        gauge.pack(pady=(px(4), 0))
        self._w["gauge"] = gauge

        status = tk.Label(root, text="", bg=BG, fg=MUTED, font=(UI_FONT, -fs(10)))
        status.pack()
        self._w["status"] = status

        detail = tk.Label(root, text="", bg=BG, fg=HINT, font=(UI_FONT, -fs(9)))
        detail.pack(pady=(px(2), 0))
        self._w["detail"] = detail

        card = tk.Frame(root, bg=CARD)
        card.pack(fill="x", padx=pad, pady=(px(12), 0))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=px(12), pady=px(10))
        tk.Label(inner, text="最近一小时电量", bg=CARD, fg=MUTED, anchor="w",
                 font=(UI_FONT, -fs(9))).pack(fill="x")
        chart = tk.Canvas(inner, width=px(296), height=px(84), bg=CARD,
                          highlightthickness=0, bd=0)
        chart.pack(fill="x", pady=(px(6), 0))
        self._w["chart"] = chart

        opts = tk.Frame(root, bg=BG)
        opts.pack(fill="x", padx=pad, pady=(px(14), 0))
        self._toggles: dict[str, Toggle] = {}
        for key, text, value, command in (
            ("low", "低电量提醒（≤15%）", True, self._on_low),
            ("auto", "开机自动启动", False, self._on_autostart),
        ):
            row = tk.Frame(opts, bg=BG)
            row.pack(fill="x", pady=px(3))
            toggle = Toggle(row, text, value, command, width=px(38), height=px(22),
                            font=(UI_FONT, -fs(10)), fg=FG, bg=BG,
                            accent=COLOR_ACCENT)
            toggle.pack(side="left")
            toggle.label().pack(side="left", padx=(px(10), 0), fill="x", expand=True)
            self._toggles[key] = toggle

        buttons = tk.Frame(root, bg=BG)
        buttons.pack(fill="x", padx=pad, pady=(px(12), px(4)))
        tk.Button(buttons, text="立即刷新", command=self._on_refresh,
                  bg=CARD_HI, fg=FG, activebackground=TRACK, activeforeground=FG,
                  bd=0, relief="flat", highlightthickness=0, cursor="hand2",
                  font=(UI_FONT, -fs(10)), padx=px(16), pady=px(6)).pack(side="left")
        tk.Button(buttons, text="使用说明", command=self._on_help,
                  bg=BG, fg=MUTED, activebackground=BG, activeforeground=FG,
                  bd=0, relief="flat", highlightthickness=0, cursor="hand2",
                  font=(UI_FONT, -fs(10)), padx=px(8), pady=px(6)).pack(side="left")
        tk.Button(buttons, text="退出", command=self._on_quit,
                  bg=BG, fg=MUTED, activebackground=BG, activeforeground=FG,
                  bd=0, relief="flat", highlightthickness=0, cursor="hand2",
                  font=(UI_FONT, -fs(10)), padx=px(8), pady=px(6)).pack(side="right")

        tk.Label(root, text="关闭窗口后仍在托盘运行", bg=BG, fg=HINT,
                 font=(UI_FONT, -fs(8))).pack(pady=(0, px(10)))

        self._apply(self.app.snapshot())
        root.update_idletasks()
        self._placed = False
        if os.environ.get("GWP_DEBUG"):
            with open("layout.txt", "w", encoding="utf-8") as fh:
                fh.write(f"scale={self._scale} root={root.winfo_width()}x{root.winfo_height()}"
                         f" req={root.winfo_reqwidth()}x{root.winfo_reqheight()}\n")

                def dump(widget, depth=0):
                    fh.write("  " * depth + f"{widget.winfo_class():12s}"
                             f" {widget.winfo_width()}x{widget.winfo_height()}"
                             f" req {widget.winfo_reqwidth()}x{widget.winfo_reqheight()}\n")
                    for child in widget.winfo_children():
                        dump(child, depth + 1)

                dump(root)

    def _window_image(self, root: tk.Tk):
        from PIL import ImageTk

        photo = ImageTk.PhotoImage(self.app.render_icon())
        self._w["photo"] = photo  # keep a reference alive
        return photo

    # -- updates -----------------------------------------------------------
    def _apply(self, payload: dict) -> None:
        if not payload:
            return
        self._payload = payload
        root = self._root
        px, fs = self._px, self._fs
        state = payload["state"]
        percent = state.percent
        accent = payload.get("accent") or MUTED

        self._w["name"].configure(text=state.name or "罗技无线鼠标")
        self._w["sub"].configure(text=payload.get("detail") or "HID++")
        if root is not None:
            root.title(f"罗技鼠标电量 · {percent}%" if percent is not None
                       else "罗技鼠标电量")

        self._w["status"].configure(text=state.status_text,
                                    fg=accent if state.present else MUTED)
        bits = []
        if state.voltage_mv:
            bits.append(f"{state.voltage_mv} mV")
        if payload.get("updated"):
            bits.append("更新于 " + time.strftime("%H:%M:%S",
                                                time.localtime(payload["updated"])))
        if not state.present and state.detail:
            bits.append(state.detail)
        self._w["detail"].configure(text=" · ".join(bits))

        self._draw_gauge(percent, state.charging, state.present, accent)
        self._draw_chart(payload.get("history") or [], accent)

        self._toggles["low"].set(payload.get("notify_low", True))
        self._toggles["auto"].set(payload.get("autostart", False))
    def _draw_gauge(self, percent, charging: bool, present: bool, accent: str) -> None:
        canvas: tk.Canvas = self._w["gauge"]
        canvas.delete("all")
        px, fs = self._px, self._fs
        size = px(196)
        edge = px(14)
        box = (edge, edge, size - edge, size - edge)
        width = px(13)

        canvas.create_arc(*box, start=90, extent=-359.9, style="arc",
                          outline=TRACK, width=width)
        if percent is not None:
            extent = -359.9 * max(0, min(100, percent)) / 100
            if extent < -0.5:
                canvas.create_arc(*box, start=90, extent=extent, style="arc",
                                  outline=accent, width=width)

        cx = cy = size / 2
        if percent is None:
            canvas.create_text(cx, cy - px(6), text="—", fill=MUTED,
                               font=(NUM_FONT, -fs(32)))
            canvas.create_text(cx, cy + px(24), text="未知" if present else "未连接",
                               fill=MUTED, font=(UI_FONT, -fs(9)))
            return

        canvas.create_text(cx, cy - px(10), text=f"{percent}", fill=accent,
                           font=(NUM_FONT, -fs(40)))
        canvas.create_text(cx, cy + px(20), text="%", fill=MUTED,
                           font=(UI_FONT, -fs(10)))
        if charging:
            bx, by = cx + px(34), cy + px(16)
            canvas.create_polygon(
                bx + px(5), by - px(11), bx - px(6), by + px(1), bx - px(1), by + px(1),
                bx - px(5), by + px(11), bx + px(7), by - px(2), bx + px(2), by - px(2),
                fill="#FFD54A", outline="")

    def _draw_chart(self, history: list, accent: str) -> None:
        canvas: tk.Canvas = self._w["chart"]
        canvas.delete("all")
        px, fs = self._px, self._fs
        w = int(canvas.winfo_reqwidth())
        h = int(canvas.winfo_reqheight())
        now = time.time()
        pts = [(ts, pct) for ts, pct in history if pct is not None and now - ts <= 3600]
        if len(pts) < 2:
            canvas.create_text(w / 2, h / 2, text="正在收集数据…", fill=HINT,
                               font=(UI_FONT, -fs(9)))
            return
        left, right = px(2), w - px(2)
        top, bottom = px(10), h - px(14)
        for level in (25, 50, 75):
            y = bottom - (bottom - top) * level / 100
            canvas.create_line(left, y, right, y, fill=TRACK,
                               dash=(px(1), px(4)) if level != 50 else None)
        canvas.create_text(right, bottom + px(9), text="现在", fill=HINT,
                           font=(UI_FONT, -fs(8)), anchor="e")
        canvas.create_text(left, bottom + px(9), text="60 分钟前", fill=HINT,
                           font=(UI_FONT, -fs(8)), anchor="w")

        span = max(120.0, now - pts[0][0])

        def coords(ts: float, pct: float) -> tuple[float, float]:
            x = left + (right - left) * max(0.0, 1 - (now - ts) / span)
            y = bottom - (bottom - top) * max(0, min(100, pct)) / 100
            return x, y

        points = [coords(ts, pct) for ts, pct in pts]
        flat: list[float] = []
        for x, y in points:
            flat.extend((x, y))
        canvas.create_polygon(points[0][0], bottom, *flat, points[-1][0], bottom,
                              fill=_mix(accent, CARD, 0.9), outline="")
        canvas.create_line(*flat, fill=accent, width=px(2), smooth=True,
                           capstyle="round", joinstyle="round")
        x, y = points[-1]
        canvas.create_oval(x - px(3), y - px(3), x + px(3), y + px(3),
                           fill=accent, outline=CARD)

    # -- actions -----------------------------------------------------------
    def _on_refresh(self) -> None:
        self.app.refresh_now()

    def _on_help(self) -> None:
        self.app.show_help()

    def _on_quit(self) -> None:
        self.app.quit_app()

    def _on_low(self, value: bool) -> None:
        self.app.set_notify_low(bool(value))

    def _on_autostart(self, value: bool) -> None:
        self.app.set_autostart(bool(value))

    def _show_help(self, text: str) -> None:
        ctypes.windll.user32.MessageBoxW(None, text, "罗技鼠标电量 · 使用说明", 0x40)

    # -- dpi ---------------------------------------------------------------
    @staticmethod
    def _system_scale() -> float:
        """Windows DPI scale for the primary display."""
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32.GetDpiForSystem.restype = ctypes.c_uint
        gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdi32.GetDeviceCaps.restype = ctypes.c_int
        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.GetDC.restype = ctypes.c_void_p
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        try:
            dpi = user32.GetDpiForSystem()
            if dpi:
                return dpi / 96.0
        except Exception:
            pass
        try:
            hdc = user32.GetDC(None)
            dpi = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            user32.ReleaseDC(None, hdc)
            if dpi:
                return dpi / 96.0
        except Exception:
            pass
        return 1.0
