"""Windows desktop and taskbar integration layer."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

APP_ID = "Community.AIUsageTaskbar.1"
TITLE = "AI & PC 모니터"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "AIUsageTaskbar"
BASE = Path(__file__).resolve().parent


def pythonw():
    path = Path(sys.executable).with_name("pythonw.exe")
    if not path.is_file():
        raise OSError("콘솔 없는 실행에 필요한 pythonw.exe를 찾을 수 없습니다.")
    return path


def command(background=False):
    args = [str(pythonw()), str(BASE / "widget.py")]
    if background:
        args.append("--background")
    return subprocess.list2cmdline(args)


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return value == command(True)
    except OSError:
        return False


def set_autostart(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command(True))
        else:
            try:
                value, _ = winreg.QueryValueEx(key, RUN_NAME)
                if value == command(True):
                    winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def prepare_app():
    attach_to_interactive_desktop()
    C.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    try:
        C.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


class Instance:
    def __init__(self, namespace=APP_ID):
        self.k = C.WinDLL("kernel32", use_last_error=True)
        for name, args, result in [
            ("CreateMutexW", [C.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE),
            ("CreateEventW", [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR], W.HANDLE),
            ("WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD),
            ("SetEvent", [W.HANDLE], W.BOOL),
            ("CloseHandle", [W.HANDLE], W.BOOL),
        ]:
            fn = getattr(self.k, name)
            fn.argtypes = args
            fn.restype = result
        suffix = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
        name = "Local\\" + namespace + "." + suffix
        self.mutex = self.k.CreateMutexW(None, False, name)
        if not self.mutex:
            raise C.WinError(C.get_last_error())
        self.owner = C.get_last_error() != 183
        self.events = {}
        try:
            for action in ("toggle", "show", "quit"):
                handle = self.k.CreateEventW(None, False, False, name + "." + action)
                if not handle:
                    raise C.WinError(C.get_last_error())
                self.events[action] = handle
        except Exception:
            self.close()
            raise

    def signal(self, action):
        C.windll.user32.AllowSetForegroundWindow(W.DWORD(-1))
        if not self.k.SetEvent(self.events[action]):
            raise C.WinError(C.get_last_error())

    def pending(self):
        return [
            action
            for action, handle in self.events.items()
            if self.k.WaitForSingleObject(handle, 0) == 0
        ]

    def close(self):
        for handle in self.events.values():
            self.k.CloseHandle(handle)
        self.events.clear()
        if self.mutex:
            self.k.CloseHandle(self.mutex)
            self.mutex = None


class GUID(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    @classmethod
    def make(cls, value):
        return cls((C.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


class PROPERTYKEY(C.Structure):
    _fields_ = [("fmtid", GUID), ("pid", W.DWORD)]


class PROPVARIANT(C.Structure):
    _fields_ = [
        ("vt", C.c_ushort),
        ("r1", C.c_ushort),
        ("r2", C.c_ushort),
        ("r3", C.c_ushort),
        ("value", C.c_void_p),
        ("padding", C.c_void_p),
    ]


def check(hr):
    if hr < 0:
        raise OSError(f"Windows COM 오류: 0x{hr & 0xFFFFFFFF:08X}")


def com(obj, index, restype, argtypes, *args):
    table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(restype, C.c_void_p, *argtypes)(table[index])(obj, *args)


def interface(obj, iid):
    out = C.c_void_p()
    check(
        com(
            obj,
            0,
            C.c_long,
            [C.POINTER(GUID), C.POINTER(C.c_void_p)],
            C.byref(GUID.make(iid)),
            C.byref(out),
        )
    )
    return out


def release(obj):
    if obj:
        com(obj, 2, W.ULONG, [])


def set_property(store, pid, text):
    buffer = C.create_unicode_buffer(text)
    value = PROPVARIANT()
    value.vt = 31  # VT_LPWSTR
    value.value = C.cast(buffer, C.c_void_p)
    key = PROPERTYKEY(GUID.make("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid)
    check(
        com(
            store,
            6,
            C.c_long,
            [C.POINTER(PROPERTYKEY), C.POINTER(PROPVARIANT)],
            C.byref(key),
            C.byref(value),
        )
    )


def create_shortcut(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ole = C.OleDLL("ole32")
    ole.CoInitialize(None)
    link = C.c_void_p()
    persist = store = None
    try:
        clsid = GUID.make("00021401-0000-0000-C000-000000000046")
        iid = GUID.make("000214F9-0000-0000-C000-000000000046")
        check(ole.CoCreateInstance(C.byref(clsid), None, 1, C.byref(iid), C.byref(link)))
        for index, text in [
            (20, str(pythonw())),
            (11, subprocess.list2cmdline([str(BASE / "widget.py")])),
            (9, str(BASE)),
            (7, "AI 사용량 & PC 모니터"),
        ]:
            check(com(link, index, C.c_long, [W.LPCWSTR], text))
        ico_file = BASE / "assets" / "usage.ico"
        if ico_file.exists():
            check(com(link, 17, C.c_long, [W.LPCWSTR, C.c_int], str(ico_file), 0))
        store = interface(link, "886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
        set_property(store, 5, APP_ID)
        check(com(store, 7, C.c_long, []))
        persist = interface(link, "0000010B-0000-0000-C000-000000000046")
        check(com(persist, 6, C.c_long, [W.LPCWSTR, W.BOOL], str(path), True))
    finally:
        release(persist)
        release(store)
        release(link)
        ole.CoUninitialize()


def style_window(root):
    root.update_idletasks()
    user = C.windll.user32
    user.GetParent.argtypes = [W.HWND]
    user.GetParent.restype = W.HWND
    hwnd = user.GetParent(root.winfo_id())
    enabled = C.c_int(1)
    try:
        C.windll.dwmapi.DwmSetWindowAttribute(W.HWND(hwnd), 20, C.byref(enabled), 4)
    except (AttributeError, OSError):
        pass

    ole = C.OleDLL("ole32")
    ole.CoInitialize(None)
    store = C.c_void_p()
    try:
        iid = GUID.make("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
        check(
            C.windll.shell32.SHGetPropertyStoreForWindow(
                W.HWND(hwnd), C.byref(iid), C.byref(store)
            )
        )
        for pid, text in [
            (2, command()),
            (3, str(BASE / "assets" / "usage.ico") + ",0"),
            (4, TITLE),
            (5, APP_ID),
        ]:
            set_property(store, pid, text)
        check(com(store, 7, C.c_long, []))
    except Exception:
        pass
    finally:
        release(store)
        ole.CoUninitialize()


def work_area(root):
    class RECT(C.Structure):
        _fields_ = [
            ("left", C.c_long),
            ("top", C.c_long),
            ("right", C.c_long),
            ("bottom", C.c_long),
        ]

    class MONITORINFO(C.Structure):
        _fields_ = [
            ("size", W.DWORD),
            ("monitor", RECT),
            ("work", RECT),
            ("flags", W.DWORD),
        ]

    user = C.windll.user32
    user.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
    user.MonitorFromWindow.restype = W.HANDLE
    info = MONITORINFO()
    info.size = C.sizeof(info)
    monitor = user.MonitorFromWindow(root.winfo_id(), 2)
    if user.GetMonitorInfoW(W.HANDLE(monitor), C.byref(info)):
        r = info.work
        return r.left, r.top, r.right, r.bottom
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def foreground(root):
    root.deiconify()
    root.lift()
    root.focus_force()
    try:
        user = C.windll.user32
        user.GetParent.argtypes = [W.HWND]
        user.GetParent.restype = W.HWND
        hwnd = root.winfo_id()
        parent = user.GetParent(hwnd)
        target = parent if parent else hwnd
        user.ShowWindow(W.HWND(target), 9)
        user.SetForegroundWindow(W.HWND(target))
    except Exception:
        pass


def attach_to_interactive_desktop():
    user = C.windll.user32
    try:
        hwinsta = user.OpenWindowStationW("WinSta0", False, 0x0000037F)
        if hwinsta:
            user.SetProcessWindowStation(hwinsta)
        hdesk = user.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            user.SetThreadDesktop(hdesk)
    except Exception:
        pass


def get_tray_info():
    attach_to_interactive_desktop()
    user = C.windll.user32
    hTray = user.FindWindowW("Shell_TrayWnd", None)
    if not hTray:
        return None
    hNotify = user.FindWindowExW(hTray, 0, "TrayNotifyWnd", None)

    class RECT(C.Structure):
        _fields_ = [("l", C.c_long), ("t", C.c_long), ("r", C.c_long), ("b", C.c_long)]
    class POINT(C.Structure):
        _fields_ = [("x", C.c_long), ("y", C.c_long)]

    rTray = RECT()
    user.GetWindowRect(hTray, C.byref(rTray))
    tray_h = rTray.b - rTray.t
    tray_w = rTray.r - rTray.l

    notify_screen_l = rTray.r - 200
    notify_client_x = tray_w - 200
    if hNotify:
        rNotify = RECT()
        user.GetWindowRect(hNotify, C.byref(rNotify))
        notify_screen_l = rNotify.l
        pt = POINT(rNotify.l, rNotify.t)
        user.ScreenToClient(hTray, C.byref(pt))
        notify_client_x = pt.x

    tray_start_screen_l = notify_screen_l

    return {
        "hTray": hTray,
        "hNotify": hNotify,
        "tray_rect": (rTray.l, rTray.t, rTray.r, rTray.b),
        "tray_w": tray_w,
        "tray_h": tray_h,
        "notify_screen_l": notify_screen_l,
        "tray_start_screen_l": tray_start_screen_l,
        "notify_client_x": notify_client_x,
    }


def position_window(root_hwnd, x, y, width, height, topmost=True, show=True):
    user = C.windll.user32
    user.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
    user.SetWindowPos.restype = W.BOOL
    parent = user.GetParent(W.HWND(root_hwnd))
    target_hwnd = parent if parent else root_hwnd
    insert_after = W.HWND(-1) if topmost else W.HWND(0)
    flags = 0x0010  # SWP_NOACTIVATE
    if show:
        flags |= 0x0040  # SWP_SHOWWINDOW
    return user.SetWindowPos(W.HWND(target_hwnd), insert_after, int(x), int(y), int(width), int(height), flags)


def get_cursor_pos():
    user = C.windll.user32
    pt = W.POINT()
    user.GetCursorPos(C.byref(pt))
    return pt.x, pt.y


def get_window_rect(root_hwnd):
    user = C.windll.user32
    parent = user.GetParent(W.HWND(root_hwnd))
    target_hwnd = parent if parent else root_hwnd
    r = W.RECT()
    user.GetWindowRect(W.HWND(target_hwnd), C.byref(r))
    return r.left, r.top, r.right, r.bottom


def dock_to_taskbar(root_hwnd, width=238, height=30):
    info = get_tray_info()
    if not info:
        return False, 0, 0, width, height
    user = C.windll.user32
    tray_rect = info["tray_rect"]
    tray_t = tray_rect[1]
    tray_h = info["tray_h"]
    tray_start_l = info.get("tray_start_screen_l", info["notify_screen_l"])

    # Snap tightly right next to the chevron button with a safe 4px margin (no overlap)
    x = max(10, tray_start_l - width - 4)
    y = tray_t + max(2, (tray_h - height) // 2)

    # Resolve top-level window handle
    parent = user.GetParent(W.HWND(root_hwnd))
    target_hwnd = parent if parent else root_hwnd

    GWL_EXSTYLE = -20
    user.GetWindowLongW.argtypes = [W.HWND, C.c_int]
    user.GetWindowLongW.restype = C.c_long
    user.SetWindowLongW.argtypes = [W.HWND, C.c_int, C.c_long]
    user.SetWindowLongW.restype = C.c_long
    user.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
    user.SetWindowPos.restype = W.BOOL

    ex_style = user.GetWindowLongW(W.HWND(target_hwnd), GWL_EXSTYLE)
    # WS_EX_TOOLWINDOW (0x80) | WS_EX_TOPMOST (0x08) | WS_EX_NOACTIVATE (0x08000000)
    target_ex = (ex_style | 0x00000080 | 0x00000008 | 0x08000000) & ~0x00040000
    if ex_style != target_ex:
        user.SetWindowLongW(W.HWND(target_hwnd), GWL_EXSTYLE, C.c_long(target_ex).value)

    HWND_TOPMOST = W.HWND(-1)
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040
    user.SetWindowPos(
        W.HWND(target_hwnd),
        HWND_TOPMOST,
        x, y, width, height,
        SWP_NOACTIVATE | SWP_SHOWWINDOW
    )
    return True, x, y, width, height


def get_secondary_tray_info():
    attach_to_interactive_desktop()
    user = C.windll.user32
    hSec = user.FindWindowW("Shell_SecondaryTrayWnd", None)
    if not hSec:
        return None

    class RECT(C.Structure):
        _fields_ = [("l", C.c_long), ("t", C.c_long), ("r", C.c_long), ("b", C.c_long)]

    rSec = RECT()
    user.GetWindowRect(hSec, C.byref(rSec))
    sec_w = rSec.r - rSec.l
    sec_h = rSec.b - rSec.t
    if sec_w <= 0 or sec_h <= 0:
        return None

    return {
        "hSec": hSec,
        "rect": (rSec.l, rSec.t, rSec.r, rSec.b),
        "w": sec_w,
        "h": sec_h,
    }


def dock_to_secondary_taskbar(root_hwnd, width=238, height=30):
    info = get_secondary_tray_info()
    if not info:
        return False, 0, 0, width, height
    user = C.windll.user32
    rSec = info["rect"]
    # Snap closely next to the secondary monitor clock area (~103px from right edge)
    clock_margin = 103
    x = rSec[2] - width - clock_margin
    y = rSec[1] + max(2, (info["h"] - height) // 2)

    parent = user.GetParent(W.HWND(root_hwnd))
    target_hwnd = parent if parent else root_hwnd

    GWL_EXSTYLE = -20
    user.GetWindowLongW.argtypes = [W.HWND, C.c_int]
    user.GetWindowLongW.restype = C.c_long
    user.SetWindowLongW.argtypes = [W.HWND, C.c_int, C.c_long]
    user.SetWindowLongW.restype = C.c_long
    user.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
    user.SetWindowPos.restype = W.BOOL

    ex_style = user.GetWindowLongW(W.HWND(target_hwnd), GWL_EXSTYLE)
    target_ex = (ex_style | 0x00000080 | 0x00000008 | 0x08000000) & ~0x00040000
    if ex_style != target_ex:
        user.SetWindowLongW(W.HWND(target_hwnd), GWL_EXSTYLE, C.c_long(target_ex).value)

    HWND_TOPMOST = W.HWND(-1)
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040
    user.SetWindowPos(
        W.HWND(target_hwnd),
        HWND_TOPMOST,
        x, y, width, height,
        SWP_NOACTIVATE | SWP_SHOWWINDOW
    )
    return True, x, y, width, height


def undock_from_taskbar(root_hwnd):
    pass

