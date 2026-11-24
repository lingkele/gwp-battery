"""Battery levels of Bluetooth (BLE) peripherals, read from Windows PnP.

Windows itself polls the standard BLE Battery Service (0x180F) and caches the
result on the device node, which is what the Settings app shows. Reading that
cached value avoids a GATT connection (and avoids waking the keyboard), and it
works for any BLE peripheral, Logitech or not.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_CM_GETIDLIST_FILTER_ENUMERATOR = 0x00000001
_CM_GETIDLIST_FILTER_PRESENT = 0x00000100
_CR_SUCCESS = 0x00000000
_DEVPROP_TYPE_BYTE = 0x00000003
_DEVPROP_TYPE_STRING = 0x00000012


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.ULONG)]


def _guid(text: str) -> _GUID:
    parts = text.strip("{}").split("-")
    data1, data2, data3 = int(parts[0], 16), int(parts[1], 16), int(parts[2], 16)
    tail = bytes.fromhex(parts[3] + parts[4])
    return _GUID(data1, data2, data3, (ctypes.c_ubyte * 8)(*tail))


# {104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2 == DEVPKEY_Bluetooth_Battery
_PKEY_BATTERY = _DEVPROPKEY(_guid("104EA319-6EE2-4701-BD47-8DDBF425BBE5"), 2)
# {A45C254E-DF1C-4EFD-8020-67D146A850E0} 14 == DEVPKEY_Device_FriendlyName
_PKEY_NAME = _DEVPROPKEY(_guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)

_cfgmgr = ctypes.WinDLL("cfgmgr32", use_last_error=True)
_cfgmgr.CM_Get_Device_ID_List_SizeW.argtypes = [ctypes.POINTER(wintypes.ULONG),
                                                wintypes.LPCWSTR, wintypes.ULONG]
_cfgmgr.CM_Get_Device_ID_List_SizeW.restype = wintypes.ULONG
_cfgmgr.CM_Get_Device_ID_ListW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                                           wintypes.ULONG, wintypes.ULONG]
_cfgmgr.CM_Get_Device_ID_ListW.restype = wintypes.ULONG
_cfgmgr.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR,
                                       wintypes.ULONG]
_cfgmgr.CM_Locate_DevNodeW.restype = wintypes.ULONG
_cfgmgr.CM_Get_DevNode_PropertyW.argtypes = [wintypes.DWORD, ctypes.POINTER(_DEVPROPKEY),
                                             ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p,
                                             ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
_cfgmgr.CM_Get_DevNode_PropertyW.restype = wintypes.ULONG


def _instance_ids(enumerator: str) -> list[str]:
    """Device instance ids of one enumerator (e.g. ``BTHLE``) that are present."""
    flags = _CM_GETIDLIST_FILTER_ENUMERATOR | _CM_GETIDLIST_FILTER_PRESENT
    size = wintypes.ULONG(0)
    if _cfgmgr.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), enumerator, flags) != _CR_SUCCESS:
        return []
    buffer = ctypes.create_unicode_buffer(size.value)
    if _cfgmgr.CM_Get_Device_ID_ListW(enumerator, buffer, size.value, flags) != _CR_SUCCESS:
        return []
    raw = ctypes.string_at(ctypes.addressof(buffer), size.value * ctypes.sizeof(ctypes.c_wchar))
    return [part for part in raw.decode("utf-16-le", errors="ignore").split("\0") if part]


def _property(devinst: int, key: _DEVPROPKEY):
    """Raw property value, or None when the node has no such property."""
    prop_type = wintypes.ULONG(0)
    size = wintypes.ULONG(0)
    _cfgmgr.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(key), ctypes.byref(prop_type),
                                     None, ctypes.byref(size), 0)
    if size.value == 0:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    status = _cfgmgr.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(key), ctypes.byref(prop_type),
                                              buffer, ctypes.byref(size), 0)
    if status != _CR_SUCCESS:
        return None
    if prop_type.value == _DEVPROP_TYPE_BYTE:
        return int.from_bytes(buffer.raw[:1], "little")
    if prop_type.value == _DEVPROP_TYPE_STRING:
        return buffer.raw[:size.value].decode("utf-16-le", errors="ignore").rstrip("\0")
    return None


def bluetooth_batteries() -> list[dict]:
    """Every present BLE peripheral Windows knows a battery level for."""
    found: list[dict] = []
    for instance_id in _instance_ids("BTHLE"):
        devinst = wintypes.DWORD(0)
        if _cfgmgr.CM_Locate_DevNodeW(ctypes.byref(devinst), instance_id, 0) != _CR_SUCCESS:
            continue
        level = _property(devinst.value, _PKEY_BATTERY)
        if not isinstance(level, int) or not 0 <= level <= 100:
            continue
        name = _property(devinst.value, _PKEY_NAME)
        found.append({
            "instance_id": instance_id,
            "name": name if isinstance(name, str) else "",
            "percent": level,
        })
    return found
