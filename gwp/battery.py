"""Read the battery state of every Logitech mouse that answers HID++ 2.0."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .hidpp import DIRECT_DEVICE, HidppError, Receiver, enumerate_endpoints

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
    transport: str = ""          # "receiver" or "usb"
    key: str = ""                # stable identity: receiver pid + device index

    @property
    def status_text(self) -> str:
        if not self.present:
            return "未响应"
        if self.full:
            return "已充满"
        if self.charging:
            return "充电中"
        return "放电中"

    @property
    def label(self) -> str:
        return self.name or ("罗技鼠标" if self.present else "未发现罗技鼠标")


@dataclass
class _Slot:
    """A device index that answered on one HID++ endpoint."""
    key: tuple
    endpoint: dict
    dev: int
    receiver: Receiver
    name: str = ""
    transport: str = "receiver"
    notes: list[str] = field(default_factory=list)


class MouseBattery:
    """Finds every Logitech mouse that answers, then polls their batteries.

    A mouse can sit on a receiver slot (device index 1..6) or be wired straight
    into USB, where it answers on its own address (0xFF). Both are discovered on
    the first read and cached; a rescan only happens when nothing answers.
    """

    def __init__(self):
        self._receivers: dict[tuple, Receiver] = {}
        self._slots: list[_Slot] | None = None
        self._names: dict[tuple, str] = {}

    # -- connection ---------------------------------------------------------
    def _receiver_for(self, endpoint: dict) -> Receiver | None:
        key = (endpoint["product_id"], endpoint["short"])
        rx = self._receivers.get(key)
        if rx is not None:
            return rx
        try:
            rx = Receiver(endpoint["short"], endpoint["long"],
                          endpoint["product_id"], endpoint["product"])
        except OSError:
            return None
        self._receivers[key] = rx
        return rx

    def _drop_receiver(self, key: tuple):
        rx = self._receivers.pop(key, None)
        if rx is not None:
            rx.close()

    def _has_battery(self, rx: Receiver, dev: int) -> bool:
        for feature in (FEATURE_UNIFIED_BATTERY, FEATURE_BATTERY_STATUS, FEATURE_BATTERY_VOLTAGE):
            if rx.feature_index(feature, dev):
                return True
        return False

    def _scan(self) -> list[_Slot]:
        """Ask every endpoint and address who is alive and has a battery."""
        slots: list[_Slot] = []
        try:
            endpoints = enumerate_endpoints()
        except OSError:
            return slots
        for endpoint in endpoints:
            rx = self._receiver_for(endpoint)
            if rx is None:
                continue
            key = (endpoint["product_id"], endpoint["short"])
            try:
                direct = rx.ping(DIRECT_DEVICE)
            except HidppError:
                self._drop_receiver(key)
                continue
            if direct and self._has_battery(rx, DIRECT_DEVICE):
                slots.append(_Slot(key, endpoint, DIRECT_DEVICE, rx, transport="usb"))
                continue      # a wired mouse owns the whole endpoint
            for dev in range(1, 7):
                try:
                    if rx.ping(dev) and self._has_battery(rx, dev):
                        slots.append(_Slot(key, endpoint, dev, rx))
                except HidppError:
                    self._drop_receiver(key)
                    break
        return slots

    def _read_name(self, rx: Receiver, dev: int) -> str:
        key = (rx.product_id, dev)
        cached = self._names.get(key)
        if cached:
            return cached
        name = ""
        index = rx.feature_index(FEATURE_DEVICE_NAME, dev)
        if index:
            head = rx.call(index, 0x00, dev=dev)
            if head:
                count = head[4]
                chars: list[int] = []
                chunk_index = 0
                while len(chars) < count and chunk_index < 4:
                    # byte 0 = (chunk << 4) | offset, one chunk is 16 bytes
                    chunk = rx.call(index, 0x01, chunk_index << 4, dev=dev)
                    chunk_index += 1
                    if not chunk:
                        break
                    data = [c for c in chunk[4:20] if c]
                    if not data:
                        break
                    chars.extend(data)
                name = bytes(chars[:count]).decode("utf-8", errors="ignore").strip()
        if name:            # an empty answer is a hiccup, not a nameless device
            self._names[key] = name
        return name

    def _where(self, slot: _Slot) -> str:
        if slot.transport == "usb":
            return "USB 直连"
        return f"接收器 {slot.dev} 号位"

    # -- public -------------------------------------------------------------
    def read_all(self) -> list[BatteryState]:
        """Battery of every mouse currently answering."""
        if not self._slots:
            self._slots = self._scan()
        if not self._slots:
            # the first sweep often lands while the device is still waking up
            time.sleep(0.25)
            self._slots = self._scan()
        if not self._slots:
            return [BatteryState(detail="未找到罗技鼠标（接收器与 USB 直连都没有响应）")]

        states = [state for state in (self._poll(slot) for slot in self._slots) if state]
        if not states:
            # everything went quiet: re-pair / re-plug may have changed the map
            self._slots = self._scan()
            states = [state for state in (self._poll(slot) for slot in self._slots) if state]
        if not states:
            return [BatteryState(detail="罗技鼠标没有响应（可能已休眠或断开）")]
        return states

    def read(self) -> BatteryState:
        """The mouse worth showing: lowest charge wins, so it warns first."""
        states = self.read_all()
        known = [s for s in states if s.percent is not None]
        if known:
            return min(known, key=lambda s: s.percent)
        present = [s for s in states if s.present]
        return present[0] if present else states[0]

    def _poll(self, slot: _Slot) -> BatteryState | None:
        rx = slot.receiver
        state: BatteryState | None = None
        for attempt in range(2):
            try:
                if not slot.name:
                    slot.name = self._read_name(rx, slot.dev)
                state = self._read_battery(rx, slot)
            except HidppError:
                self._drop_slot(slot)
                return None
            if state.percent is not None:
                return state
            if attempt == 0:
                # the mouse may have dozed off: a fresh ping usually wakes it
                rx.forget(slot.dev)
                try:
                    if not rx.ping(slot.dev):
                        break
                except HidppError:
                    self._drop_slot(slot)
                    return None
                time.sleep(0.2)
        return state

    def _drop_slot(self, slot: _Slot):
        key = slot.key
        self._receivers.pop(key, None)
        rx = slot.receiver
        try:
            rx.close()
        except Exception:
            pass
        self._slots = None

    def _read_battery(self, rx: Receiver, slot: _Slot) -> BatteryState:
        dev = slot.dev
        where = self._where(slot)
        key = f"{slot.endpoint['product_id']}:{dev:02x}"
        common = {"present": True, "name": slot.name, "transport": slot.transport, "key": key}

        index = rx.feature_index(FEATURE_UNIFIED_BATTERY, dev)
        if index:
            reply = rx.call(index, 0x01, dev=dev)
            if reply and len(reply) >= 7:
                percent, status = reply[4], reply[6]
                return BatteryState(percent=min(100, percent),
                                    charging=status in CHARGING_STATES,
                                    full=status == FULL_STATE,
                                    detail=f"{where} · HID++ 0x1004", **common)

        index = rx.feature_index(FEATURE_BATTERY_STATUS, dev)
        if index:
            reply = rx.call(index, 0x00, dev=dev)
            if reply and len(reply) >= 7:
                percent, status = reply[4], reply[6]
                return BatteryState(percent=min(100, percent),
                                    charging=status in CHARGING_STATES,
                                    full=status == FULL_STATE,
                                    detail=f"{where} · HID++ 0x1000", **common)

        index = rx.feature_index(FEATURE_BATTERY_VOLTAGE, dev)
        if index:
            reply = rx.call(index, 0x00, dev=dev)
            if reply and len(reply) >= 6:
                voltage = (reply[4] << 8) | reply[5]   # big-endian mV
                flags = reply[6] if len(reply) > 6 else 0
                if 2500 <= voltage <= 4600:
                    return BatteryState(percent=voltage_to_percent(voltage),
                                        charging=bool(flags & 0x80),
                                        voltage_mv=voltage,
                                        detail=f"{where} · HID++ 0x1001", **common)

        # `__init__` ran without a name yet on the very first poll
        return BatteryState(name=slot.name, transport=slot.transport, present=True, key=key,
                            detail=f"{where} · 电量读取失败（鼠标可能休眠）")

    def close(self):
        self._slots = None
        for key in list(self._receivers):
            self._drop_receiver(key)
