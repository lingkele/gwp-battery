"""Read the battery state of a Logitech mouse over HID++ 2.0."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .hidpp import HidppError, Receiver, enumerate_endpoints

FEATURE_BATTERY_STATUS = 0x1000   # percent + status
FEATURE_BATTERY_VOLTAGE = 0x1001  # voltage in mV + flags
FEATURE_UNIFIED_BATTERY = 0x1004  # percent + level + status
FEATURE_DEVICE_NAME = 0x0005

# status byte shared by 0x1000 / 0x1004
CHARGING_STATES = {1, 2, 4}
FULL_STATE = 3

# Voltage -> percentage, the same curve Solaar uses for Logitech LiPo packs.
_VOLTAGE_CURVE = [
    (4186, 100), (4067, 90), (3989, 80), (3922, 70), (3859, 60), (3811, 50),
    (3778, 40), (3751, 30), (3717, 20), (3671, 10), (3646, 5), (3579, 2), (3500, 0),
]


def voltage_to_percent(mv: int) -> int:
    if mv >= _VOLTAGE_CURVE[0][0]:
        return 100
    if mv <= _VOLTAGE_CURVE[-1][0]:
        return 0
    for (v_hi, p_hi), (v_lo, p_lo) in zip(_VOLTAGE_CURVE, _VOLTAGE_CURVE[1:]):
        if v_lo <= mv <= v_hi:
            return round(p_lo + (p_hi - p_lo) * (mv - v_lo) / (v_hi - v_lo))
    return 0


@dataclass
class BatteryState:
    present: bool = False        # a mouse answers
    percent: int | None = None
    charging: bool = False
    full: bool = False
    voltage_mv: int | None = None
    name: str = ""
    detail: str = ""

    @property
    def status_text(self) -> str:
        if not self.present:
            return "鼠标未响应"
        if self.full:
            return "已充满"
        if self.charging:
            return "充电中"
        return "放电中"


class MouseBattery:
    """Resolves the mouse on a receiver once, then polls its battery."""

    def __init__(self):
        self._receiver: Receiver | None = None
        self._key: tuple | None = None
        self._device_index: int | None = None
        self._name: str = ""

    # -- connection ---------------------------------------------------------
    def _connect(self) -> Receiver | None:
        for endpoint in enumerate_endpoints():
            key = (endpoint["product_id"], endpoint["short"])
            if self._receiver is not None and key == self._key:
                return self._receiver
            try:
                self._receiver = Receiver(endpoint["short"], endpoint["long"],
                                          endpoint["product_id"], endpoint["product"])
            except OSError:
                self._receiver = None
                continue
            self._key = key
            self._device_index = None
            self._name = ""
            return self._receiver
        self._receiver = None
        self._key = None
        return None

    def _resolve_device(self, rx: Receiver) -> int | None:
        for dev in range(1, 7):
            if rx.ping(dev):
                return dev
        return None

    def _read_name(self, rx: Receiver, dev: int) -> str:
        index = rx.feature_index(FEATURE_DEVICE_NAME, dev)
        if not index:
            return ""
        head = rx.call(index, 0x00, dev=dev)
        if not head:
            return ""
        count = head[4]
        chars: list[int] = []
        while len(chars) < count:
            chunk = rx.call(index, 0x01, len(chars), dev=dev)
            if not chunk:
                break
            data = chunk[4:20]
            chars.extend(c for c in data if c)
            if not any(data):
                break
        return bytes(chars[:count]).decode("utf-8", errors="ignore").strip()

    # -- public -------------------------------------------------------------
    def read(self) -> BatteryState:
        try:
            rx = self._connect()
        except OSError:
            rx = None
        if rx is None:
            return BatteryState(detail="未找到罗技接收器")

        state = BatteryState(detail="接收器在线，鼠标未响应")
        for attempt in range(2):
            try:
                if self._device_index is None:
                    self._device_index = self._resolve_device(rx)
                    if self._device_index is None:
                        return state
                state = self._read_battery(rx, self._device_index)
            except HidppError:
                self._drop()
                return BatteryState(detail="与接收器通信失败")
            if state.percent is not None or not state.present:
                return state
            if attempt == 0:
                # the mouse may have dozed off: dropping the index forces a
                # fresh ping, which wakes it up
                self._device_index = None
                time.sleep(0.25)
        return state

    def _read_battery(self, rx: Receiver, dev: int) -> BatteryState:
        if not self._name:
            self._name = self._read_name(rx, dev)

        index = rx.feature_index(FEATURE_UNIFIED_BATTERY, dev)
        if index:
            reply = rx.call(index, 0x01, dev=dev)
            if reply and len(reply) >= 7:
                percent, status = reply[4], reply[6]
                return BatteryState(present=True, percent=min(100, percent),
                                    charging=status in CHARGING_STATES,
                                    full=status == FULL_STATE, name=self._name,
                                    detail="HID++ 0x1004")

        index = rx.feature_index(FEATURE_BATTERY_STATUS, dev)
        if index:
            reply = rx.call(index, 0x00, dev=dev)
            if reply and len(reply) >= 7:
                percent, status = reply[4], reply[6]
                return BatteryState(present=True, percent=min(100, percent),
                                    charging=status in CHARGING_STATES,
                                    full=status == FULL_STATE, name=self._name,
                                    detail="HID++ 0x1000")

        index = rx.feature_index(FEATURE_BATTERY_VOLTAGE, dev)
        if index:
            reply = rx.call(index, 0x00, dev=dev)
            if reply and len(reply) >= 6:
                voltage = (reply[4] << 8) | reply[5]   # big-endian mV
                flags = reply[6] if len(reply) > 6 else 0
                if 2500 <= voltage <= 4600:
                    return BatteryState(present=True, percent=voltage_to_percent(voltage),
                                        charging=bool(flags & 0x80),
                                        voltage_mv=voltage, name=self._name,
                                        detail="HID++ 0x1001")

        # The mouse answered the ping but exposes no battery feature, or it fell
        # asleep between the ping and the feature calls.
        return BatteryState(present=True, name=self._name, percent=None,
                            detail="电量读取失败（鼠标可能休眠）")

    def _drop(self):
        if self._receiver is not None:
            self._receiver.close()
        self._receiver = None
        self._key = None
        self._device_index = None
        self._name = ""

    def close(self):
        self._drop()
