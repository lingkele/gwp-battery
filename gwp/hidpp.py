"""HID++ 2.0 transport over Logitech receivers and direct USB mice (hidapi)."""
from __future__ import annotations

import time

import hid

SHORT_REPORT = 0x10
SW_ID = 0x01
ROOT_FEATURE = 0x00
ERROR_MARKER = 0xFF
PING_MARKER = 0xAA
DIRECT_DEVICE = 0xFF   # HID++ address of a device wired straight to USB


class HidppError(Exception):
    pass


class Receiver:
    """Short + long HID collections of one HID++ endpoint.

    On Windows the two report sizes live in separate collections: a 7-byte
    short request is written to the usage-0x01 handle, a 20-byte long request to
    the usage-0x02 handle, while replies may arrive on either. Directly attached
    mice often expose the short collection only, so ``long_path`` is optional.
    """

    def __init__(self, short_path, long_path=None, product_id=None, product_name=""):
        self.short = hid.device()
        self.long = hid.device()
        self.short.open_path(short_path)
        if long_path:
            self.long.open_path(long_path)
            self._shared = False
        else:
            self.long = self.short
            self._shared = True
        self.short.set_nonblocking(1)
        if not self._shared:
            self.long.set_nonblocking(1)
        self.product_id = product_id
        self.product_name = product_name or ""
        self._feature_cache: dict[tuple[int, int], int | None] = {}

    @property
    def is_direct(self) -> bool:
        return "receiver" not in self.product_name.lower()

    def close(self):
        handles = [self.short] if self._shared else [self.short, self.long]
        for handle in handles:
            try:
                handle.close()
            except Exception:
                pass

    def _drain(self):
        handles = [self.short] if self._shared else [self.short, self.long]
        for handle in handles:
            while handle.read(64):
                pass

    def call(self, feature: int, function: int, *params, dev: int = 1, timeout: float = 0.5):
        """One HID++ short request; returns the reply report or None."""
        payload = [*params, 0, 0, 0][:3]
        request = [SHORT_REPORT, dev, feature, (function << 4) | SW_ID, *payload]
        try:
            self._drain()
            self.short.write(request)
        except OSError as exc:
            raise HidppError(str(exc)) from exc

        deadline = time.monotonic() + timeout
        handles = [self.short] if self._shared else [self.short, self.long]
        while time.monotonic() < deadline:
            for handle in handles:
                try:
                    reply = handle.read(32)
                except OSError as exc:
                    raise HidppError(str(exc)) from exc
                if not reply or len(reply) < 4 or reply[1] != dev:
                    continue
                if reply[2] == ERROR_MARKER and reply[3] == feature:
                    return None
                if reply[2] == feature and reply[3] == request[3]:
                    return list(reply)
            time.sleep(0.004)
        return None

    def feature_index(self, feature_id: int, dev: int = 1) -> int | None:
        key = (feature_id, dev)
        if key in self._feature_cache:
            return self._feature_cache[key] or None
        for attempt in range(2):
            reply = self.call(ROOT_FEATURE, 0x00,
                              (feature_id >> 8) & 0xFF, feature_id & 0xFF, dev=dev)
            if reply is not None:
                index = reply[4]          # 0 means "feature not supported"
                self._feature_cache[key] = index   # only cache a real answer
                return index or None
            if attempt == 0:
                time.sleep(0.05)          # the first request after a wake-up is lost
        return None                       # a timeout must never be cached

    def forget(self, dev: int):
        for key in [k for k in self._feature_cache if k[1] == dev]:
            del self._feature_cache[key]

    def ping(self, dev: int) -> bool:
        # The very first request after the handle is opened is regularly lost,
        # so a negative answer is only trusted after a second try.
        for attempt in range(2):
            reply = self.call(ROOT_FEATURE, 0x01, 0, 0, PING_MARKER,
                              dev=dev, timeout=0.35)
            if reply and len(reply) > 6 and reply[6] == PING_MARKER:
                return True
            if attempt == 0:
                time.sleep(0.05)
        return False


def enumerate_endpoints(vid: int = 0x046D) -> list[dict]:
    """Find HID++ (usage page 0xFF00) endpoints, as short/long handle pairs.

    Receivers expose both a short and a long collection; mice plugged straight
    into USB often expose the short one only, which is why ``long`` may be None.
    """
    pairs: dict[tuple[int, int], dict] = {}
    for info in hid.enumerate(vid, 0):
        if info["usage_page"] != 0xFF00:
            continue
        if info["usage"] not in (0x0001, 0x0002):
            continue
        key = (info["product_id"], info["interface_number"])
        entry = pairs.setdefault(key, {"product_id": info["product_id"],
                                       "product": info.get("product_string") or "",
                                       "short": None, "long": None})
        if info["usage"] == 0x0001 and entry["short"] is None:
            entry["short"] = info["path"]
        elif info["usage"] == 0x0002 and entry["long"] is None:
            entry["long"] = info["path"]
    return [p for p in pairs.values() if p["short"]]
