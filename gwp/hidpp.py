"""HID++ 2.0 transport over a Logitech receiver (Windows / hidapi)."""
from __future__ import annotations

import time

import hid

SHORT_REPORT = 0x10
SW_ID = 0x01
ROOT_FEATURE = 0x00
ERROR_MARKER = 0xFF
PING_MARKER = 0xAA


class HidppError(Exception):
    pass


class Receiver:
    """Short + long HID collections of one HID++ endpoint.

    On Windows the two report sizes live in separate collections: a 7-byte
    short request is written to the usage-0x01 handle, a 20-byte long request to
    the usage-0x02 handle, while replies may arrive on either.
    """

    def __init__(self, short_path, long_path, product_id=None, product_name=""):
        self.short = hid.device()
        self.long = hid.device()
        self.short.open_path(short_path)
        self.long.open_path(long_path)
        self.short.set_nonblocking(1)
        self.long.set_nonblocking(1)
        self.product_id = product_id
        self.product_name = product_name
        self._feature_cache: dict[tuple[int, int], int | None] = {}

    def close(self):
        for handle in (self.short, self.long):
            try:
                handle.close()
            except Exception:
                pass

    def _drain(self):
        for handle in (self.short, self.long):
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
        while time.monotonic() < deadline:
            for handle in (self.short, self.long):
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
        if key not in self._feature_cache:
            reply = self.call(ROOT_FEATURE, 0x00, (feature_id >> 8) & 0xFF, feature_id & 0xFF, dev=dev)
            self._feature_cache[key] = (reply[4] or None) if reply else None
        return self._feature_cache[key]

    def ping(self, dev: int) -> bool:
        reply = self.call(ROOT_FEATURE, 0x01, 0, 0, PING_MARKER, dev=dev, timeout=0.35)
        return bool(reply and len(reply) > 6 and reply[6] == PING_MARKER)


def enumerate_endpoints(vid: int = 0x046D) -> list[dict]:
    """Find HID++ (interface 2, usage page 0xFF00) short/long pairs."""
    pairs: dict[tuple[int, int], dict] = {}
    for info in hid.enumerate(vid, 0):
        if info["usage_page"] != 0xFF00:
            continue
        key = (info["product_id"], info["interface_number"])
        entry = pairs.setdefault(key, {"product_id": info["product_id"],
                                       "product": info.get("product_string") or "",
                                       "short": None, "long": None})
        if info["usage"] == 0x0001:
            entry["short"] = info["path"]
        elif info["usage"] == 0x0002:
            entry["long"] = info["path"]
    return [p for p in pairs.values() if p["short"] and p["long"]]
