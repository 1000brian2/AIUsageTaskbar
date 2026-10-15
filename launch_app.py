"""Launch AIUsageTaskbar on the interactive user desktop."""
import ctypes as C
from ctypes import wintypes as W
import sys
from pathlib import Path

kernel = C.windll.kernel32

class STARTUPINFO(C.Structure):
    _fields_ = [
        ('cb', W.DWORD), ('lpReserved', W.LPWSTR), ('lpDesktop', W.LPWSTR), ('lpTitle', W.LPWSTR),
        ('dwX', W.DWORD), ('dwY', W.DWORD), ('dwXSize', W.DWORD), ('dwYSize', W.DWORD),
        ('dwXCountChars', W.DWORD), ('dwYCountChars', W.DWORD), ('dwFillAttribute', W.DWORD),
        ('dwFlags', W.DWORD), ('wShowWindow', W.WORD), ('cbReserved2', W.WORD),
        ('lpReserved2', C.c_void_p), ('hStdInput', W.HANDLE), ('hStdOutput', W.HANDLE), ('hStdError', W.HANDLE)
    ]

class PROCESS_INFORMATION(C.Structure):
    _fields_ = [
        ('hProcess', W.HANDLE), ('hThread', W.HANDLE),
        ('dwProcessId', W.DWORD), ('dwThreadId', W.DWORD)
    ]

def launch():
    si = STARTUPINFO()
    si.cb = C.sizeof(STARTUPINFO)
    si.lpDesktop = 'WinSta0\\Default'
    pi = PROCESS_INFORMATION()

    import os
    import shutil
    pythonw = str(Path(sys.executable).with_name("pythonw.exe"))
    if not Path(pythonw).is_file():
        found = shutil.which("pythonw")
        if found:
            pythonw = found
        else:
            local = os.environ.get("LOCALAPPDATA", "")
            cand = Path(local) / "Microsoft" / "WindowsApps" / "pythonw.exe"
            if cand.is_file():
                pythonw = str(cand)
            else:
                pythonw = sys.executable
    base = Path(__file__).resolve().parent
    cmdline = f'"{pythonw}" "{base / "widget.py"}"'
    res = kernel.CreateProcessW(
        None, cmdline, None, None, False,
        0x00000008,  # DETACHED_PROCESS
        None, str(base), C.byref(si), C.byref(pi)
    )
    if not res:
        err = C.get_last_error()
        print("CreateProcessW failed with error code:", err)
        return False, 0
    print("Successfully launched widget on WinSta0\\Default! PID:", pi.dwProcessId)
    kernel.CloseHandle(pi.hProcess)
    kernel.CloseHandle(pi.hThread)
    return True, pi.dwProcessId

if __name__ == "__main__":
    launch()
