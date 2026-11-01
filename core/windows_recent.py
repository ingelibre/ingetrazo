# SPDX-License-Identifier: GPL-3.0-or-later
"""Native Windows taskbar recents, with Windows-owned pinning and removal.

Use shell links so an imported SKP always reopens in IngeTrazo, even when
another program is the default handler. No third-party COM package is needed.
Nothing touches the shell until initialize() is called by the GUI entry point.
"""
from __future__ import annotations

import ctypes as C
import logging
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

# Stable across upgrades; must match the installer's shortcut/ProgID properties.
APP_ID = "IngeTrazo.IngeTrazo"
_active_app_id: str | None = None
_log = logging.getLogger(__name__)


class _GUID(C.Structure):
    _fields_ = [("data1", C.c_uint32), ("data2", C.c_uint16),
                ("data3", C.c_uint16), ("data4", C.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(UUID(value).bytes_le)


class _PropertyKey(C.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", C.c_uint32)]


class _VariantData(C.Union):
    _fields_ = [("text", C.c_wchar_p), ("padding", C.c_void_p * 2)]


class _PropVariant(C.Structure):
    _fields_ = [("vt", C.c_ushort), ("reserved1", C.c_ushort),
                ("reserved2", C.c_ushort), ("reserved3", C.c_ushort),
                ("value", _VariantData)]


class _AppIdLink(C.Structure):
    _fields_ = [("link", C.c_void_p), ("app_id", C.c_wchar_p)]


_CLSID_SHELL_LINK = _GUID.parse("00021401-0000-0000-c000-000000000046")
_IID_SHELL_LINK = _GUID.parse("000214f9-0000-0000-c000-000000000046")
_IID_PROPERTY_STORE = _GUID.parse("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")
_TITLE = _PropertyKey(_GUID.parse("f29f85e0-4ff9-1068-ab91-08002b27b3d9"), 2)


def _check(result):
    if result < 0:
        raise OSError(f"Windows shell HRESULT 0x{result & 0xffffffff:08x}")


def _method(pointer, index, result, *arguments):
    vtable = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(result, C.c_void_p, *arguments)(vtable[index])


def _invoke(pointer, index, *arguments):
    """Invoke one HRESULT-returning COM method with explicit ABI types."""
    types, values = zip(*arguments) if arguments else ((), ())
    _check(_method(pointer, index, C.c_long, *types)(pointer, *values))


@contextmanager
def _com():
    ole32 = C.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = (C.c_void_p, C.c_uint32)
    ole32.CoInitializeEx.restype = C.c_long
    result = ole32.CoInitializeEx(None, 2)  # apartment threaded, like Qt's GUI
    # A caller may already own an MTA. It is initialized; do not uninitialize it.
    if result != -2147417850:  # RPC_E_CHANGED_MODE
        _check(result)
    try:
        yield ole32
    finally:
        if result >= 0:
            ole32.CoUninitialize()


@contextmanager
def _shell_link(ole32):
    pointer = C.c_void_p()
    create = ole32.CoCreateInstance
    create.argtypes = (C.POINTER(_GUID), C.c_void_p, C.c_uint32,
                       C.POINTER(_GUID), C.POINTER(C.c_void_p))
    create.restype = C.c_long
    _check(create(C.byref(_CLSID_SHELL_LINK), None, 1,
                  C.byref(_IID_SHELL_LINK), C.byref(pointer)))
    try:
        yield pointer
    finally:
        _method(pointer, 2, C.c_ulong)(pointer)  # IUnknown::Release


@contextmanager
def _interface(pointer, iid):
    other = C.c_void_p()
    _invoke(pointer, 0, (C.POINTER(_GUID), C.byref(iid)),
            (C.POINTER(C.c_void_p), C.byref(other)))
    try:
        yield other
    finally:
        _method(other, 2, C.c_ulong)(other)


def _set_string(pointer, key, text):
    with _interface(pointer, _IID_PROPERTY_STORE) as store:
        # IPropertyStore::SetValue copies the string. The borrowed Python
        # buffer stays alive through the call; it must not be PropVariantClear'd.
        value = _PropVariant()
        value.vt = 31  # VT_LPWSTR
        value.value.text = text
        _invoke(store, 6, (C.POINTER(_PropertyKey), C.byref(key)),
                (C.POINTER(_PropVariant), C.byref(value)))
        _invoke(store, 7)  # Commit


def initialize(app_id: str = APP_ID) -> bool:
    """Identify the process before Qt creates windows or a file dialog."""
    global _active_app_id
    if sys.platform != "win32":
        return False
    try:
        set_id = C.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = (C.c_wchar_p,)
        set_id.restype = C.c_long
        _check(set_id(app_id))
        _active_app_id = app_id
        return True
    except (OSError, AttributeError):
        _log.warning("Could not initialize taskbar recents", exc_info=True)
        return False


def _launch_command(path: Path) -> tuple[str, str]:
    # A Jump List opens a model in its own window, like SketchUp. In
    # particular, importing a pinned SKP must not append it to the model
    # currently being edited or replace an unsaved document via IPC.
    args = ["--new-window", str(path)]
    if not getattr(sys, "frozen", False):
        args.insert(0, str(Path(__file__).resolve().parents[1] / "main.py"))
    return sys.executable, subprocess.list2cmdline(args)


def add_recent_document(path) -> bool:
    """Report a successful open/save/import; Windows manages pins and history.

    Only native documents and SKP imports are reported. Failed/missing files
    and all non-Windows callers are harmless no-ops. Shell failures must never
    turn a successful model operation into an error.
    """
    if sys.platform != "win32" or _active_app_id is None or path is None:
        return False
    try:
        document = Path(path).resolve()
        if document.suffix.lower() not in {".igz", ".skp"} or not document.is_file():
            return False
        executable, arguments = _launch_command(document)
        with _com() as ole32, _shell_link(ole32) as link:
            _invoke(link, 20, (C.c_wchar_p, executable))  # SetPath
            _invoke(link, 11, (C.c_wchar_p, arguments))  # SetArguments
            _invoke(link, 17, (C.c_wchar_p, executable), (C.c_int, 0))  # icon
            _invoke(link, 7, (C.c_wchar_p, str(document)))  # tooltip
            _set_string(link, _TITLE, document.name)
            info = _AppIdLink(link, _active_app_id)
            add = C.WinDLL("shell32").SHAddToRecentDocs
            add.argtypes = (C.c_uint, C.c_void_p)
            add.restype = None
            add(0x00000007, C.byref(info))  # SHARD_APPIDINFOLINK
        return True
    except (OSError, AttributeError, ValueError):
        _log.warning("Could not update taskbar recents", exc_info=True)
        return False
