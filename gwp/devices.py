"""One list of every Logitech / Bluetooth peripheral with a battery level.

Two sources are merged here:

* HID++ 2.0 (Logitech receivers, and mice or keyboards wired straight to USB),
  which also reports charging state and voltage;
* the BLE battery service Windows polls for any Bluetooth peripheral, so
  keyboards from other brands show up too.
"""
from __future__ import annotations

from dataclasses import dataclass

from .battery import BatteryState, MouseBattery
from .bluetooth import bluetooth_batteries
from .theme import level_color

KEYBOARD_HINTS = ("keyboard", "keys", "k380", "k400", "k480", "k780", "k850",
                  "craft", "g915", "g815", "g713", "g715", "g613", "g413",
                  "mx mechanical", "pop keys", "pebble", "键盘",
                  "keychron", "varmilo", "ducky", "filco", "hhkb", "akko",
                  "nuphy", "royal kludge", "rkgk")
MOUSE_HINTS = ("mouse", "m185", "m325", "m585", "m720", "mx master", "mx anywhere",
               "g304", "g305", "g403", "g502", "g pro", "g703", "g903", "lift",
               "superlight", "鼠标")


def classify(name: str) -> str:
    """Best-effort device kind from its reported name."""
    lowered = (name or "").lower()
    if any(hint in lowered for hint in KEYBOARD_HINTS):
        return "keyboard"
    if any(hint in lowered for hint in MOUSE_HINTS):
        return "mouse"
    return "device"


@dataclass
class DeviceState:
    id: str
    name: str = ""
    kind: str = "device"
    percent: int | None = None
    charging: bool = False
    full: bool = False
    voltage_mv: int | None = None
    present: bool = True
    transport: str = ""
    detail: str = ""

    @property
    def status_text(self) -> str:
        if not self.present:
            return "未响应"
        if self.full:
            return "已充满"
        if self.charging:
            return "充电中"
        if self.percent is None:
            return "电量未知"
        return "放电中"

    @property
    def label(self) -> str:
        return self.name or {"mouse": "罗技鼠标", "keyboard": "键盘"}.get(self.kind, "设备")

    @property
    def kind_text(self) -> str:
        return {"mouse": "鼠标", "keyboard": "键盘"}.get(self.kind, "设备")

    @property
    def accent(self) -> str:
        return level_color(self.percent)


def _from_hidpp(state: BatteryState, index: int) -> DeviceState:
    return DeviceState(
        id=f"hidpp:{state.key or index}",
        name=state.name,
        kind=classify(state.name),
        percent=state.percent,
        charging=state.charging,
        full=state.full,
        voltage_mv=state.voltage_mv,
        present=state.present,
        transport=state.transport,
        detail=state.detail,
    )


def _from_bt(item: dict) -> DeviceState:
    return DeviceState(
        id=f"bt:{item['instance_id']}",
        name=item["name"],
        kind=classify(item["name"]),
        percent=item["percent"],
        transport="bluetooth",
        detail="蓝牙 · Windows 电池服务",
    )


class DeviceMonitor:
    """Polls both transports and returns one flat device list."""

    def __init__(self):
        self._hidpp = MouseBattery()

    def poll(self) -> list[DeviceState]:
        devices: list[DeviceState] = []
        try:
            for index, state in enumerate(self._hidpp.read_all()):
                devices.append(_from_hidpp(state, index))
        except Exception:  # noqa: BLE001 - a dead receiver must not kill polling
            devices.append(DeviceState(id="hidpp:none", detail="HID++ 读取失败",
                                       present=False, transport="receiver"))
        try:
            for item in bluetooth_batteries():
                devices.append(_from_bt(item))
        except Exception:  # noqa: BLE001
            pass
        devices.sort(key=lambda d: (d.kind != "mouse", d.name))
        return devices

    def close(self):
        self._hidpp.close()


def pick(devices: list[DeviceState], selected: str | None) -> DeviceState | None:
    """The device to show: the chosen one, else the one needing attention most."""
    if not devices:
        return None
    if selected:
        for device in devices:
            if device.id == selected:
                return device
    known = [d for d in devices if d.percent is not None]
    if known:
        return min(known, key=lambda d: d.percent)
    return devices[0]
