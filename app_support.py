"""Helper functions, styling, battery rendering and settings for AI & PC Taskbar."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time
from typing import Any

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AIUsageTaskbar"
SETTINGS_FILE = DATA_DIR / "settings.json"
INTERVALS = (1, 3, 5, 10, 15, 30)

COLOR_GREEN = "#38D39F"
COLOR_YELLOW = "#FFBA49"
COLOR_RED = "#FF6B6B"
COLOR_MUTED = "#8B949E"
COLOR_BG = "#191C23"
COLOR_CARD = "#242832"
COLOR_CARD_HOVER = "#2A303C"
COLOR_TEXT = "#F3F5F9"
COLOR_TRACK = "#353C4A"
COLOR_GPT = "#10A37F"
COLOR_GEM = "#2563EB"
COLOR_CLAUDE = "#D97706"
COLOR_RAM = "#475569"


def load_settings() -> dict[str, Any]:
    defaults = {
        "refresh_minutes": 5,
        "on_close_action": "ask",
        "theme": "system",
        "language": "ko",
        "show_gpt": True,
        "show_gem": True,
        "show_claude": False,
        "show_ram": True,
    }
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
        return data
    except (OSError, ValueError):
        return defaults


def save_settings(settings: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


def battery_color(percent: float | None) -> str:
    if percent is None:
        return COLOR_MUTED
    if percent >= 50.0:
        return COLOR_GREEN
    elif percent >= 20.0:
        return COLOR_YELLOW
    else:
        return COLOR_RED


def format_reset_time(timestamp: float | None, lang: str = "ko") -> str:
    from i18n import t
    if timestamp is None:
        return t("reset_no_info", lang=lang)
    seconds = max(0, int(timestamp - time.time()))
    if seconds == 0:
        return t("reset_complete", lang=lang)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins = max(1, rem // 60)
    if days > 0:
        return t("reset_in_days", lang=lang, days=days, hours=hours)
    elif hours > 0:
        return t("reset_in_hours", lang=lang, hours=hours, mins=mins)
    else:
        return t("reset_in_mins", lang=lang, mins=mins)


def is_light_theme() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            val, _ = winreg.QueryValueEx(k, "SystemUsesLightTheme")
            return val == 1
    except Exception:
        return False


def get_dock_theme(theme_mode: str = "system") -> dict[str, str]:
    if theme_mode == "light":
        light = True
    elif theme_mode == "dark":
        light = False
    else:
        light = is_light_theme()

    if light:
        return {
            "mode": "light",
            "bg": "#EEF4FA",
            "bg_hover": "#E1ECF6",
            "border": "#BACDDF",
            "border_hover": "#7CA2C8",
            "box_bg": "#E2EAF2",
            "box_border": "#CAD8E6",
            "text": "#1A202C",
            "text_muted": "#556477",
            "divider": "#CBD7E4",
            "bar_bg": "#D0DCE7",
            "battery_outline": "#6B7C93",
            "battery_green": "#10B981",
            "battery_yellow": "#F59E0B",
            "battery_red": "#EF4444",
            "gpt_color": "#0E8A6B",
            "gem_color": "#1D4ED8",
            "claude_color": "#D97706",
            "ram_color": "#334155",
        }
    else:
        return {
            "mode": "dark",
            "bg": "#1F232B",
            "bg_hover": "#282E39",
            "border": "#353C4A",
            "border_hover": "#4E586C",
            "box_bg": "#171A21",
            "box_border": "#2E3646",
            "text": "#F3F5F9",
            "text_muted": "#8B949E",
            "divider": "#353C4A",
            "bar_bg": "#353C4A",
            "battery_outline": "#5B6475",
            "battery_green": "#38D39F",
            "battery_yellow": "#FFBA49",
            "battery_red": "#FF6B6B",
            "gpt_color": "#10B981",
            "gem_color": "#3B82F6",
            "claude_color": "#F59E0B",
            "ram_color": "#94A3B8",
        }


def draw_battery(
    canvas,
    percent: float | None,
    width: int = 28,
    height: int = 13,
    outline_color: str | None = None,
    green_color: str | None = None,
    yellow_color: str | None = None,
    red_color: str | None = None,
):
    """Draw a clean battery icon onto a Tkinter canvas."""
    canvas.delete("all")
    ol = outline_color or "#5B6475"
    body_w = width - 4
    # Outer body
    canvas.create_rectangle(1, 1, body_w, height - 1, outline=ol, width=1)
    # Terminal cap on right
    canvas.create_rectangle(body_w, (height // 2) - 2, width - 1, (height // 2) + 3, fill=ol, outline="")

    if percent is not None and percent > 0:
        if percent >= 50.0:
            color = green_color or COLOR_GREEN
        elif percent >= 20.0:
            color = yellow_color or COLOR_YELLOW
        else:
            color = red_color or COLOR_RED

        max_fill_w = body_w - 4
        fill_w = max(2, int(max_fill_w * (min(100.0, percent) / 100.0)))
        canvas.create_rectangle(3, 3, 3 + fill_w, height - 3, fill=color, outline="")


class ConsumptionTracker:
    def __init__(self):
        self.samples: list[tuple[float, float | None, float | None, float | None]] = []

    def record(self, gpt_rem: float | None, gem_rem: float | None, claude_rem: float | None = None):
        now = time.time()
        self.samples.append((now, gpt_rem, gem_rem, claude_rem))
        cutoff = now - 3600
        self.samples = [s for s in self.samples if s[0] >= cutoff]

    def get_metrics(self, model: str = "gpt") -> dict[str, Any]:
        """Return burn rate (%/h), speed label, speed color, and burn forecast."""
        if model == "gpt":
            idx = 1
        elif model == "gemini":
            idx = 2
        else:
            idx = 3
        valid = [s for s in self.samples if len(s) > idx and s[idx] is not None]
        if len(valid) < 2:
            return {
                "burn_rate": 0.0,
                "burn_rate_str": "측정 중",
                "speed_label": "소비 속도 측정 중 (안정)",
                "speed_color": "#10B981",
                "forecast_label": "데이터 수집 중 · 소진 위험 없음",
                "is_fast": False,
            }

        first_time, first_rem = valid[0][0], valid[0][idx]
        last_time, last_rem = valid[-1][0], valid[-1][idx]
        dt_hours = (last_time - first_time) / 3600.0

        if dt_hours < (20.0 / 3600.0):
            return {
                "burn_rate": 0.0,
                "burn_rate_str": "0.0%/h",
                "speed_label": "소비 속도: 안정적 (최저 소비)",
                "speed_color": "#10B981",
                "forecast_label": "초기화 시각까지 충분 (소진 위험 없음)",
                "is_fast": False,
            }

        consumed = max(0.0, first_rem - last_rem)
        burn_rate = consumed / dt_hours

        if burn_rate <= 1.0:
            speed_label = "소비 속도: 안정적 / 여유로움"
            speed_color = "#10B981"
            forecast_label = "현재 속도 유지 시 초기화 전 소진 위험 없음"
            is_fast = False
        elif burn_rate <= 6.0:
            speed_label = f"소비 속도: 보통 ({burn_rate:.1f}%/h)"
            speed_color = "#10B981"
            hours_left = last_rem / burn_rate if burn_rate > 0 else 999
            forecast_label = f"현재 소비 속도 기준 약 {hours_left:.1f}시간 사용 가능"
            is_fast = False
        elif burn_rate <= 15.0:
            speed_label = f"소비 속도: 다소 빠름 ({burn_rate:.1f}%/h) ⚡"
            speed_color = "#F59E0B"
            hours_left = last_rem / burn_rate if burn_rate > 0 else 999
            forecast_label = f"주의: 약 {hours_left:.1f}시간 내 소진될 수 있음"
            is_fast = True
        else:
            speed_label = f"소비 속도: 매우 빠름 ({burn_rate:.1f}%/h) 🔥"
            speed_color = "#EF4444"
            hours_left = last_rem / burn_rate if burn_rate > 0 else 999
            forecast_label = f"경고: 빠른 소비로 약 {hours_left:.1f}시간 내 소진 예상"
            is_fast = True

        return {
            "burn_rate": burn_rate,
            "burn_rate_str": f"{burn_rate:.1f}%/h",
            "speed_label": speed_label,
            "speed_color": speed_color,
            "forecast_label": forecast_label,
            "is_fast": is_fast,
        }


