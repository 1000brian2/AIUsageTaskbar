"""Zero-dependency Windows native system monitor via ctypes."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import threading
import time


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class MIB_IF_ROW2(ctypes.Structure):
    _fields_ = [
        ("InterfaceLuid", ctypes.c_uint64),
        ("InterfaceIndex", wintypes.ULONG),
        ("InterfaceGuid", ctypes.c_byte * 16),
        ("Alias", wintypes.WCHAR * 257),
        ("Description", wintypes.WCHAR * 257),
        ("PhysicalAddressLength", wintypes.ULONG),
        ("PhysicalAddress", ctypes.c_byte * 32),
        ("PermanentPhysicalAddress", ctypes.c_byte * 32),
        ("Mtu", wintypes.ULONG),
        ("Type", wintypes.ULONG),
        ("TunnelType", ctypes.c_int),
        ("MediaType", ctypes.c_int),
        ("PhysicalMediumType", ctypes.c_int),
        ("AccessType", ctypes.c_int),
        ("DirectionType", ctypes.c_int),
        ("InterfaceAndOperStatusFlags", ctypes.c_byte),
        ("OperStatus", ctypes.c_int),
        ("AdminStatus", ctypes.c_int),
        ("MediaConnectState", ctypes.c_int),
        ("NetworkGuid", ctypes.c_byte * 16),
        ("ConnectionType", ctypes.c_int),
        ("TransmitLinkSpeed", ctypes.c_uint64),
        ("ReceiveLinkSpeed", ctypes.c_uint64),
        ("InOctets", ctypes.c_uint64),
        ("InUcastPkts", ctypes.c_uint64),
        ("InNUcastPkts", ctypes.c_uint64),
        ("InDiscards", ctypes.c_uint64),
        ("InErrors", ctypes.c_uint64),
        ("InUnknownProtos", ctypes.c_uint64),
        ("InUcastOctets", ctypes.c_uint64),
        ("InMulticastOctets", ctypes.c_uint64),
        ("InBroadcastOctets", ctypes.c_uint64),
        ("OutOctets", ctypes.c_uint64),
        ("OutUcastPkts", ctypes.c_uint64),
        ("OutNUcastPkts", ctypes.c_uint64),
        ("OutDiscards", ctypes.c_uint64),
        ("OutErrors", ctypes.c_uint64),
        ("OutUcastOctets", ctypes.c_uint64),
        ("OutMulticastOctets", ctypes.c_uint64),
        ("OutBroadcastOctets", ctypes.c_uint64),
        ("OutQLen", ctypes.c_uint64),
    ]


class MIB_IF_TABLE2(ctypes.Structure):
    _fields_ = [
        ("NumEntries", wintypes.ULONG),
        ("Table", MIB_IF_ROW2 * 1),
    ]


@dataclass(frozen=True)
class SystemSnapshot:
    ram_percent: int
    ram_used_gb: float
    ram_total_gb: float
    cpu_percent: float
    rx_speed_str: str
    tx_speed_str: str
    temperature_c: float | None
    timestamp: float


def _filetime_to_int(ft: FILETIME) -> int:
    return (ft.dwHighDateTime << 32) + ft.dwLowDateTime


class NativeSystemMonitor:
    def __init__(self):
        self._prev_idle = 0
        self._prev_kernel = 0
        self._prev_user = 0
        self._prev_net_in = 0
        self._prev_net_out = 0
        self._prev_time = time.monotonic()
        self._cached_temp: float | None = None
        self._last_temp_check = 0.0
        self._init_baselines()

    def _init_baselines(self):
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        self._prev_idle = _filetime_to_int(idle)
        self._prev_kernel = _filetime_to_int(kernel)
        self._prev_user = _filetime_to_int(user)
        self._prev_net_in, self._prev_net_out = self._get_raw_net_octets()

    def get_ram(self) -> tuple[int, float, float]:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total_gb = stat.ullTotalPhys / (1024 ** 3)
        avail_gb = stat.ullAvailPhys / (1024 ** 3)
        used_gb = total_gb - avail_gb
        return int(stat.dwMemoryLoad), round(used_gb, 1), round(total_gb, 1)

    def _get_raw_net_octets(self) -> tuple[int, int]:
        table_ptr = ctypes.POINTER(MIB_IF_TABLE2)()
        res = ctypes.windll.iphlpapi.GetIfTable2(ctypes.byref(table_ptr))
        if res != 0 or not table_ptr:
            return 0, 0
        total_in, total_out = 0, 0
        try:
            entries = table_ptr.contents.NumEntries
            p_row = ctypes.cast(ctypes.addressof(table_ptr.contents.Table), ctypes.POINTER(MIB_IF_ROW2))
            for i in range(entries):
                row = p_row[i]
                if row.OperStatus == 1 and (row.Type == 6 or "Ethernet" in row.Alias or "Realtek" in row.Description):
                    total_in += row.InOctets
                    total_out += row.OutOctets
        finally:
            ctypes.windll.iphlpapi.FreeMibTable(table_ptr)
        return total_in, total_out

    def _format_speed(self, bytes_per_sec: float) -> str:
        if bytes_per_sec < 1024:
            return f"{int(bytes_per_sec)} B/s"
        elif bytes_per_sec < 1024 * 1024:
            return f"{bytes_per_sec / 1024:.1f} KB/s"
        else:
            return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"

    def read_temperature(self) -> float | None:
        now = time.monotonic()
        if now - self._last_temp_check < 5.0 and self._cached_temp is not None:
            return self._cached_temp
        self._last_temp_check = now
        try:
            # Query WMI ThermalZoneInformation via lightweight PowerShell one-liner or registry
            import subprocess
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation -ErrorAction SilentlyContinue | Select-Object -First 1).Temperature"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=2.0
            ).decode("utf-8").strip()
            if out.isdigit():
                kelvin = float(out)
                celsius = round(kelvin - 273.15, 1)
                self._cached_temp = celsius
                return celsius
        except Exception:
            pass
        return self._cached_temp

    def sample(self) -> SystemSnapshot:
        now = time.monotonic()
        dt = max(0.1, now - self._prev_time)
        self._prev_time = now

        # 1. RAM
        ram_pct, ram_used, ram_tot = self.get_ram()

        # 2. CPU
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        cur_idle = _filetime_to_int(idle)
        cur_kernel = _filetime_to_int(kernel)
        cur_user = _filetime_to_int(user)

        idle_delta = cur_idle - self._prev_idle
        kernel_delta = cur_kernel - self._prev_kernel
        user_delta = cur_user - self._prev_user
        total_delta = kernel_delta + user_delta

        self._prev_idle = cur_idle
        self._prev_kernel = cur_kernel
        self._prev_user = cur_user

        if total_delta > 0:
            cpu_pct = round(max(0.0, min(100.0, 100.0 * (1.0 - (idle_delta / total_delta)))), 1)
        else:
            cpu_pct = 0.0

        # 3. Network
        cur_in, cur_out = self._get_raw_net_octets()
        in_delta = max(0, cur_in - self._prev_net_in)
        out_delta = max(0, cur_out - self._prev_net_out)
        self._prev_net_in = cur_in
        self._prev_net_out = cur_out

        rx_speed = in_delta / dt
        tx_speed = out_delta / dt

        temp = self.read_temperature()

        return SystemSnapshot(
            ram_percent=ram_pct,
            ram_used_gb=ram_used,
            ram_total_gb=ram_tot,
            cpu_percent=cpu_pct,
            rx_speed_str=self._format_speed(rx_speed),
            tx_speed_str=self._format_speed(tx_speed),
            temperature_c=temp,
            timestamp=now,
        )


if __name__ == "__main__":
    mon = NativeSystemMonitor()
    time.sleep(1)
    s = mon.sample()
    print("Snapshot:", s)
