"""Read Gemini allowance and quota data from local Antigravity Language Server."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import ssl
import subprocess
import urllib.request
from typing import Any


class GeminiUsageError(RuntimeError):
    """Raised when Gemini quota data cannot be fetched."""


@dataclass(frozen=True)
class GeminiWindow:
    remaining_percent: float
    resets_at_str: str | None
    resets_at_ts: float | None

    @property
    def used_percent(self) -> float:
        return max(0.0, min(100.0, 100.0 - self.remaining_percent))


@dataclass(frozen=True)
class GeminiSnapshot:
    plan: str
    five_hour: GeminiWindow | None
    weekly: GeminiWindow | None
    fetched_at: float


def parse_iso_time(iso_str: str | None) -> float | None:
    if not iso_str:
        return None
    try:
        # e.g. 2026-10-15T08:47:30Z
        clean = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.timestamp()
    except Exception:
        return None


def find_antigravity_ls_info() -> tuple[int, str]:
    """Return (pid, csrf_token) from running language_server.exe process."""
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process -Filter \"Name = 'language_server.exe'\" | "
        "Select-Object ProcessId, CommandLine | ConvertTo-Json",
    ]
    try:
        out = subprocess.check_output(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(out.decode("utf-8", errors="replace"))
        if isinstance(data, list):
            data = data[0]
        pid = int(data["ProcessId"])
        cmd_str = data.get("CommandLine", "")
        token_m = re.search(r"--csrf_token\s+([a-f0-9\-]+)", cmd_str)
        if not token_m:
            raise GeminiUsageError("Antigravity 인증 토큰을 찾을 수 없습니다.")
        return pid, token_m.group(1)
    except Exception as exc:
        raise GeminiUsageError(f"Antigravity Language Server 프로세스 탐색 실패: {exc}") from exc


def get_listening_ports(pid: int) -> list[int]:
    """Find local TCP listening ports for given PID."""
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"Get-NetTCPConnection -OwningProcess {pid} -State Listen | "
        "Select-Object -ExpandProperty LocalPort",
    ]
    try:
        out = subprocess.check_output(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ports = [int(p) for p in out.decode("utf-8", errors="replace").strip().split() if p.isdigit()]
        return ports
    except Exception:
        return []


def query_gemini_usage(timeout: float = 5.0) -> GeminiSnapshot:
    """Fetch live Gemini quota snapshot from Antigravity."""
    pid, token = find_antigravity_ls_info()
    ports = get_listening_ports(pid)
    if not ports:
        raise GeminiUsageError("Antigravity 활성 포트를 찾을 수 없습니다.")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    quota_data = None
    for port in ports:
        url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Codeium-Csrf-Token": token,
            },
        )
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                quota_data = json.loads(resp.read().decode("utf-8"))
                break
        except Exception:
            continue

    if not quota_data or "response" not in quota_data:
        raise GeminiUsageError("Gemini 사용량 응답을 수신하지 못했습니다.")

    five_hour_win = None
    weekly_win = None

    groups = quota_data["response"].get("groups", [])
    for group in groups:
        if "Gemini" in group.get("displayName", ""):
            for bucket in group.get("buckets", []):
                window = bucket.get("window", "").lower()
                frac = bucket.get("remainingFraction", 1.0)
                reset_time_str = bucket.get("resetTime")
                reset_ts = parse_iso_time(reset_time_str)
                rem_pct = max(0.0, min(100.0, round(float(frac) * 100.0, 1)))

                win_obj = GeminiWindow(
                    remaining_percent=rem_pct,
                    resets_at_str=reset_time_str,
                    resets_at_ts=reset_ts,
                )
                if "5h" in window or "five" in bucket.get("displayName", "").lower():
                    five_hour_win = win_obj
                elif "weekly" in window or "week" in bucket.get("displayName", "").lower():
                    weekly_win = win_obj

    now = datetime.now(timezone.utc).timestamp()
    return GeminiSnapshot(
        plan="Google AI Pro",
        five_hour=five_hour_win,
        weekly=weekly_win,
        fetched_at=now,
    )


if __name__ == "__main__":
    snap = query_gemini_usage()
    print("Plan:", snap.plan)
    if snap.five_hour:
        print(f"5H Remaining: {snap.five_hour.remaining_percent}% (Resets at: {snap.five_hour.resets_at_str})")
    if snap.weekly:
        print(f"WK Remaining: {snap.weekly.remaining_percent}% (Resets at: {snap.weekly.resets_at_str})")
