"""Capture a top-level window to PNG without disturbing the desktop.

Used while iterating on the panel layout: the window is moved off-screen and
rendered with PrintWindow, so whatever the user is doing on screen is untouched.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# Without this the rects and bitmaps come back virtualised at 96 dpi, which
# makes a 125% scaled window look like it is missing rows.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
PW_RENDERFULLCONTENT = 2
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004


def find_windows(prefix: str, max_width: int = 600) -> list[int]:
    found: list[int] = []

    def callback(hwnd, _param):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value.startswith(prefix):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            if max_width <= 0 or width < max_width:
                found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def window_size(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def capture(hwnd: int) -> Image.Image:
    width, height = window_size(hwnd)
    hdc_screen = user32.GetDC(None)
    hdc = gdi32.CreateCompatibleDC(hdc_screen)
    bitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    gdi32.SelectObject(hdc, bitmap)
    ok = user32.PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(hdc, bitmap, 0, height, buffer, ctypes.byref(header), 0)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(None, hdc_screen)

    image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    return image.convert("RGB") if not ok else image.convert("RGB")


def main() -> int:
    title = sys.argv[1] if len(sys.argv) > 1 else "罗技鼠标电量"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "panel-win.png")
    park = "-park" in sys.argv
    import time

    handles = find_windows(title)
    if not handles:
        print("no window")
        return 1
    hwnd = max(handles, key=lambda h: window_size(h)[0])
    # a Tk window is briefly mapped at its default size; wait for it to settle
    last = None
    for _ in range(40):
        size = window_size(hwnd)
        if size == last and size[0] > 200 and size[1] > 200:
            break
        last = size
        time.sleep(0.1)
    if park:
        # push it below the visible desktop instead of another monitor, so the
        # window keeps the DPI of the screen it was created on
        user32.SetWindowPos(hwnd, None, 100, 1500, 0, 0, SWP_NOSIZE | SWP_NOZORDER)
        time.sleep(0.4)
    image = capture(hwnd)
    image.save(out)
    width, height = image.size
    print(f"captured hwnd={hwnd} {width}x{height} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
