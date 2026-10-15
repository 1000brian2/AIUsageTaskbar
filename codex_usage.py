"""Read ChatGPT Work/Codex allowance data from the local Codex app server."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class UsageError(RuntimeError):
    """Raised when the local Codex app server cannot return usage data."""


@dataclass(frozen=True)
class UsageWindow:
    used_percent: float
    duration_minutes: int | None
    resets_at: int | None

    @property
    def remaining_percent(self) -> float:
        return max(0, min(100, 100 - self.used_percent))


@dataclass(frozen=True)
class UsageSnapshot:
    plan: str
    primary: UsageWindow | None
    secondary: UsageWindow | None
    credit_balance: Decimal | None
    unlimited_credits: bool
    reached_type: str | None
    fetched_at: float
    limit_id: str = "codex"


def _window(value: Any) -> UsageWindow | None:
    if not isinstance(value, dict) or value.get("usedPercent") is None:
        return None
    try:
        number = Decimal(str(value["usedPercent"]))
        if not number.is_finite():
            raise ValueError("non-finite percentage")
        used_percent = float(number)
        duration = value.get("windowDurationMins")
        resets_at = value.get("resetsAt")
        return UsageWindow(
            used_percent=max(0, min(100, used_percent)),
            duration_minutes=int(duration) if duration is not None else None,
            resets_at=int(resets_at) if resets_at is not None else None,
        )
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        raise UsageError("Codex 사용량 응답의 숫자 형식이 잘못되었습니다.") from exc


def _pick_rate_limits(result: dict[str, Any]) -> dict[str, Any] | None:
    """Prefer the Codex bucket while tolerating future bucket identifiers."""
    buckets = result.get("rateLimitsByLimitId")
    if isinstance(buckets, dict):
        codex = buckets.get("codex")
        if isinstance(codex, dict):
            return codex

        # Never silently present a model-specific bucket as the shared account limit.
        for value in buckets.values():
            if isinstance(value, dict) and value.get("limitId") == "codex":
                return value

    legacy = result.get("rateLimits")
    if isinstance(legacy, dict) and legacy.get("limitId") in (None, "codex"):
        return legacy
    return None


def parse_rate_limits(result: dict[str, Any]) -> UsageSnapshot:
    """Convert an account/rateLimits/read result into a small stable model."""
    rate_limits = _pick_rate_limits(result)
    if rate_limits is None:
        raise UsageError("Codex 응답에 사용량 한도가 없습니다.")

    credits = rate_limits.get("credits")
    balance = None
    unlimited = False
    if isinstance(credits, dict):
        unlimited = bool(credits.get("unlimited", False))
        raw_balance = credits.get("balance")
        if raw_balance is not None:
            try:
                balance = Decimal(str(raw_balance))
                if not balance.is_finite():
                    balance = None
            except InvalidOperation:
                balance = None

    primary = _window(rate_limits.get("primary"))
    secondary = _window(rate_limits.get("secondary"))
    if primary is None and secondary is None:
        raise UsageError("Codex가 사용량 구간을 제공하지 않았습니다.")

    return UsageSnapshot(
        plan=str(rate_limits.get("planType") or result.get("planType") or "unknown"),
        primary=primary,
        secondary=secondary,
        credit_balance=balance,
        unlimited_credits=unlimited,
        reached_type=rate_limits.get("rateLimitReachedType"),
        fetched_at=time.time(),
        limit_id=str(rate_limits.get("limitId") or "codex"),
    )


class _LineReader:
    def __init__(self, stream: Any) -> None:
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self.thread.start()

    def _read(self, stream: Any) -> None:
        try:
            for line in stream:
                self.lines.put(line)
        finally:
            self.lines.put(None)

    def get(self, timeout: float) -> str:
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise UsageError("Codex 응답 시간이 초과되었습니다.") from exc
        if line is None:
            raise UsageError("Codex 연결이 종료되었습니다.")
        return line


def _send(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise UsageError("Codex 요청 채널을 열 수 없습니다.")
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _wait_for_id(reader: _LineReader, request_id: int, deadline: float) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UsageError("Codex 응답 시간이 초과되었습니다.")
        raw = reader.get(remaining)
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict) or message.get("id") != request_id:
            continue
        if "error" in message:
            detail = message["error"]
            if isinstance(detail, dict):
                detail = detail.get("message") or detail
            # Do not display or persist raw server messages that may contain identifiers.
            code = message["error"].get("code") if isinstance(message["error"], dict) else None
            text = str(detail).lower()
            if any(word in text for word in ("auth", "token", "401", "unauthor")):
                raise UsageError("Codex 인증 오류(401): Codex CLI 로그인 상태를 확인하세요.")
            raise UsageError(f"Codex 조회 오류 (코드 {code}). 네트워크와 로그인 상태를 확인하세요.")
        result = message.get("result")
        if not isinstance(result, dict):
            raise UsageError("Codex 응답 형식이 잘못되었습니다.")
        return result


def find_codex_executables() -> list[str]:
    """Find Codex even when a long-running widget has a stale Windows PATH."""
    candidates: list[Path] = []
    override = os.environ.get("CODEX_USAGE_WIDGET_CODEX")
    if override:
        candidates.append(Path(override).expanduser())

    for command in ("codex", "codex.exe"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        local = Path(local_app_data)
        candidates.extend(
            (
                local / "OpenAI" / "Codex" / "codex.exe",
                local / "Programs" / "Codex" / "codex.exe",
                local / "Microsoft" / "WindowsApps" / "codex.exe",
            )
        )
        versioned_bin = local / "OpenAI" / "Codex" / "bin"
        try:
            candidates.extend(
                sorted(
                    versioned_bin.glob("*/codex.exe"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
            )
        except OSError:
            pass

    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "OpenAI" / "Codex" / "codex.exe")

    # npm's .cmd wrapper would launch an intermediate console process. Locate
    # the package's native CLI instead, preserving CLI-managed authentication.
    npm_roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        npm_roots.append(Path(appdata) / "npm" / "node_modules" / "@openai" / "codex")
    for candidate in list(candidates):
        if candidate.suffix.lower() in (".cmd", ".ps1"):
            npm_roots.append(candidate.parent / "node_modules" / "@openai" / "codex")
    native = []
    for root in npm_roots:
        for pattern in ("node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe",
                        "vendor/*/codex/codex.exe", "vendor/*/bin/codex.exe"):
            native.extend(sorted(root.glob(pattern)))
    candidates = native + candidates
    available: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if os.name == "nt" and candidate.suffix.lower() != ".exe":
            continue
        try:
            resolved = str(candidate.resolve(strict=True))
        except OSError:
            continue
        key = os.path.normcase(resolved)
        if key not in seen:
            seen.add(key)
            available.append(resolved)
    return available


def _query_with_executable(executable: str, timeout: float) -> UsageSnapshot:
    """Fetch one snapshot from one concrete Codex executable."""

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            [executable, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise UsageError(f"Codex 실행 실패: {exc}") from exc
    if process.stdout is None:
        process.kill()
        raise UsageError("Codex 응답 채널을 열 수 없습니다.")

    reader = _LineReader(process.stdout)
    deadline = time.monotonic() + timeout
    try:
        _send(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "codex-usage-taskbar", "version": "2.0.0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        _wait_for_id(reader, 1, deadline)
        _send(process, {"method": "initialized"})
        _send(process, {"id": 2, "method": "account/rateLimits/read"})
        try:
            result = _wait_for_id(reader, 2, deadline)
        except UsageError as exc:
            error_text = str(exc).lower()
            if not any(word in error_text for word in ("auth", "token", "401", "unauthor")):
                raise
            _send(
                process,
                {"id": 3, "method": "account/read", "params": {"refreshToken": True}},
            )
            _wait_for_id(reader, 3, deadline)
            _send(process, {"id": 4, "method": "account/rateLimits/read"})
            result = _wait_for_id(reader, 4, deadline)
        return parse_rate_limits(result)
    except OSError as exc:
        raise UsageError(f"Codex 호출 실패: {exc}") from exc
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.stdout:
            reader.thread.join(timeout=2)
            process.stdout.close()


def query_usage(timeout: float = 15.0) -> UsageSnapshot:
    """Fetch a snapshot, falling back across current and newly installed Codex builds."""
    executables = find_codex_executables()
    if not executables:
        raise UsageError("Codex CLI 실행 파일을 찾을 수 없습니다. Codex CLI 설치를 확인하세요.")

    errors: list[str] = []
    deadline = time.monotonic() + timeout
    for executable in executables:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            return _query_with_executable(executable, remaining)
        except UsageError as exc:
            errors.append(str(exc))

    detail = errors[-1] if errors else "알 수 없는 오류"
    raise UsageError(f"Codex 연결 실패: {detail}")
