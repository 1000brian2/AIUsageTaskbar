"""Internationalization (i18n) module for AI & PC Monitor."""
from __future__ import annotations
import locale
import os

TRANSLATIONS: dict[str, dict[str, str]] = {
    "app_title": {
        "ko": "AI & PC 모니터",
        "en": "AI & PC Monitor",
    },
    "settings_title": {
        "ko": "AI & PC 모니터 설정",
        "en": "AI & PC Monitor Settings",
    },
    "general_settings": {
        "ko": "기본 설정",
        "en": "General Settings",
    },
    "language": {
        "ko": "언어 (Language)",
        "en": "Language",
    },
    "theme": {
        "ko": "테마 모드 (Theme)",
        "en": "Theme Mode",
    },
    "theme_system": {
        "ko": "시스템 설정 따르기 (Windows 기본값)",
        "en": "Follow System (Windows Default)",
    },
    "theme_dark": {
        "ko": "다크 모드 (Dark)",
        "en": "Dark Mode",
    },
    "theme_light": {
        "ko": "화이트 / 라이트 모드 (Light)",
        "en": "Light Mode",
    },
    "refresh_interval": {
        "ko": "AI 사용량 갱신 주기",
        "en": "AI Usage Refresh Interval",
    },
    "min_unit": {
        "ko": "분",
        "en": "min",
    },
    "display_items": {
        "ko": "작업 표시줄 표시 항목 선택",
        "en": "Taskbar Display Items",
    },
    "item_gpt": {
        "ko": "OpenAI Codex / GPT 배터리",
        "en": "OpenAI Codex / GPT Battery",
    },
    "item_gem": {
        "ko": "Google Gemini 배터리",
        "en": "Google Gemini Battery",
    },
    "item_claude": {
        "ko": "Anthropic Claude 배터리",
        "en": "Anthropic Claude Battery",
    },
    "item_ram": {
        "ko": "내 컴퓨터 RAM 사용률",
        "en": "PC RAM Usage",
    },
    "on_close_action": {
        "ko": "창 닫기 [X] 버튼 동작",
        "en": "Window Close [X] Action",
    },
    "ask_every_time": {
        "ko": "매번 묻기 (추천)",
        "en": "Ask Every Time (Recommended)",
    },
    "minimize_to_taskbar": {
        "ko": "작업 표시줄에 계속 켜두기 (최소화)",
        "en": "Keep in Taskbar (Minimize)",
    },
    "quit_program": {
        "ko": "프로그램 완전 종료",
        "en": "Quit Application Completely",
    },
    "autostart": {
        "ko": "Windows 시작 시 자동 실행",
        "en": "Launch on Windows Startup",
    },
    "save": {
        "ko": "저장",
        "en": "Save",
    },
    "cancel": {
        "ko": "취소",
        "en": "Cancel",
    },
    "refresh_now": {
        "ko": "🔄  AI 사용량 새로고침",
        "en": "🔄  Refresh AI Usage",
    },
    "open_card": {
        "ko": "📊  AI & PC 모니터 창 열기",
        "en": "📊  Open Monitor Dashboard",
    },
    "settings_menu": {
        "ko": "⚙️  설정",
        "en": "⚙️  Settings",
    },
    "quit_menu": {
        "ko": "❌  프로그램 종료",
        "en": "❌  Quit Program",
    },
    "hover_title": {
        "ko": "AI 사용량 & 소진 예측 요약",
        "en": "AI Usage & Burn Rate Summary",
    },
    "hover_subtitle": {
        "ko": "마우스를 올리면 표시되며, 클릭 시 전체 상세 창이 열립니다.",
        "en": "Hover to view summary, click to toggle full dashboard.",
    },
    "live_monitor": {
        "ko": "실시간 관측",
        "en": "Live Monitor",
    },
    "speed_stable": {
        "ko": "⚡ 소비 속도: 안정적 / 여유로움",
        "en": "⚡ Burn Rate: Normal / Safe",
    },
    "speed_measuring": {
        "ko": "⚡ 소비 속도 측정 중 (안정)",
        "en": "⚡ Calculating burn rate (Normal)",
    },
    "speed_fast": {
        "ko": "⚡ 소비 속도: 매우 빠름 ({rate:.1f}%/h) 🔥",
        "en": "⚡ Burn Rate: Very Fast ({rate:.1f}%/h) 🔥",
    },
    "forecast_safe": {
        "ko": "현재 속도 유지 시 초기화 전 소진 위험 없음",
        "en": "No depletion risk before reset at current rate.",
    },
    "forecast_warning": {
        "ko": "경고: 빠른 소비로 약 {hours:.1f}시간 내 소진 예상",
        "en": "Warning: Fast burn, depletion expected in ~{hours:.1f}h",
    },
    "pc_title": {
        "ko": "💻 내 컴퓨터 성능",
        "en": "💻 My PC Performance",
    },
    "reset_no_info": {
        "ko": "초기화 정보 없음",
        "en": "No reset info",
    },
    "reset_complete": {
        "ko": "초기화 완료됨",
        "en": "Reset completed",
    },
    "reset_in_days": {
        "ko": "↻ {days}일 {hours}시간 남음",
        "en": "↻ {days}d {hours}h remaining",
    },
    "reset_in_hours": {
        "ko": "↻ {hours}시간 {mins}분 남음",
        "en": "↻ {hours}h {mins}m remaining",
    },
    "reset_in_mins": {
        "ko": "↻ {mins}분 남음",
        "en": "↻ {mins}m remaining",
    },
    "remaining": {
        "ko": "남음",
        "en": "Rem",
    },
    "used": {
        "ko": "사용",
        "en": "Used",
    },
    "close_prompt_title": {
        "ko": "창을 닫을 때 어떻게 처리할까요?",
        "en": "How would you like to handle closing the window?",
    },
    "close_prompt_desc": {
        "ko": "작업 표시줄에 켜두시면 실시간 사용량을 계속 확인하실 수 있습니다.",
        "en": "Keeping it in the taskbar allows continuous real-time monitoring.",
    },
    "remember_choice": {
        "ko": "다음부터 묻지 않고 이 동작으로 실행",
        "en": "Do not ask again (remember my choice)",
    },
}


def detect_system_lang() -> str:
    """Detect if system default language is Korean, otherwise default to English."""
    try:
        lang, _ = locale.getdefaultlocale()
        if lang and lang.lower().startswith("ko"):
            return "ko"
    except Exception:
        pass
    return "ko"  # Default to Korean for this setup, or fallback to English


def t(key: str, lang: str = "ko", **kwargs) -> str:
    """Translate key into target language with optional formatting kwargs."""
    entry = TRANSLATIONS.get(key, {})
    template = entry.get(lang) or entry.get("ko") or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template
