"""AI & PC Performance Monitor - Integrated Taskbar Dock & Dashboard Card."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import app_support as support
from claude_usage import query_claude_usage, ClaudeSnapshot
from codex_usage import query_usage as query_codex, UsageSnapshot
from gemini_usage import query_gemini_usage, GeminiSnapshot
from i18n import t
from system_monitor import NativeSystemMonitor, SystemSnapshot
import windows_integration as win


class AIUsageWidget:
    def __init__(self, root: tk.Tk, instance: win.Instance, background: bool = False):
        self.root = root
        self.instance = instance
        self.settings = support.load_settings()
        self.monitor = NativeSystemMonitor()
        self.tracker = support.ConsumptionTracker()

        self.lang = self.settings.get("language", "ko")
        self.theme_mode = self.settings.get("theme", "system")
        self.theme = support.get_dock_theme(self.theme_mode)

        self.show_gpt = self.settings.get("show_gpt", True)
        self.show_gem = self.settings.get("show_gem", True)
        self.show_claude = self.settings.get("show_claude", False)
        self.show_ram = self.settings.get("show_ram", True)

        self.codex_snapshot: UsageSnapshot | None = None
        self.gemini_snapshot: GeminiSnapshot | None = None
        self.claude_snapshot: ClaudeSnapshot | None = None
        self.sys_snapshot: SystemSnapshot | None = None

        self.busy = False
        self.closing = False
        self.next_ai_refresh = time.monotonic()
        self.ai_results = queue.Queue()
        self.settings_window: tk.Toplevel | None = None
        self.prompt_dialog: tk.Toplevel | None = None

        # Hover state & debounce timers
        self._dock_hovered = False
        self._sec_dock_hovered = False
        self._card_hovered = False
        self._show_timer = None
        self._hide_timer = None
        self.sec_dock: tk.Toplevel | None = None

        self.dock_width = self._compute_dock_width()
        self.dock_height = 30

        # ---------------------------------------------------------
        # 1. Root Window = Taskbar Embedded Dock Strip (Photo 3/4)
        # ---------------------------------------------------------
        root.title("AIUsageTaskbarDock")
        root.configure(bg=self.theme["bg"])
        root.overrideredirect(True)
        init_x, init_y = 0, 0
        info = win.get_tray_info()
        if info:
            tray_t = info["tray_rect"][1]
            tray_h = info["tray_h"]
            tray_start_l = info.get("tray_start_screen_l", info["notify_screen_l"])
            init_x = max(10, tray_start_l - self.dock_width - 4)
            init_y = tray_t + max(2, (tray_h - self.dock_height) // 2)
        root.geometry(f"{self.dock_width}x{self.dock_height}+{init_x}+{init_y}")
        root.protocol("WM_DELETE_WINDOW", self.quit_app)

        self._build_taskbar_dock()
        self._build_secondary_taskbar_dock()

        # ---------------------------------------------------------
        # 2. Hover Card Window = Sleek Pop-up Card (Photo 2)
        # ---------------------------------------------------------
        self._build_hover_card()

        # ---------------------------------------------------------
        # 3. Card Window = Full Rich Detail Window (Photo 1)
        # ---------------------------------------------------------
        self._build_card_window()

        # Embed root into Windows Taskbar
        self.root.update_idletasks()
        self._dock_to_taskbar()

        # Handle launch display
        if background:
            self.card_window.withdraw()
        else:
            self.show_card()

        # Periodic updates
        root.after(100, self._tick)
        self.refresh_ai()

    def _compute_dock_width(self) -> int:
        items = []
        if self.show_gpt:
            items.append(72)
        if self.show_gem:
            items.append(72)
        if self.show_claude:
            items.append(72)
        if self.show_ram:
            items.append(58)
        if not items:
            return 80
        total = sum(items) + max(0, len(items) - 1) * 8 + 12
        return max(80, total)

    def _label(self, parent, text, color=support.COLOR_TEXT, size=9, bold=False, **kw):
        return tk.Label(
            parent,
            text=text,
            fg=color,
            bg=parent.cget("bg"),
            font=("맑은 고딕", size, "bold" if bold else "normal"),
            **kw,
        )

    def _button(self, parent, text, fn, accent=False, pad_x=10, pad_y=5):
        return tk.Button(
            parent,
            text=text,
            command=fn,
            bg="#2A483D" if accent else support.COLOR_CARD,
            fg=support.COLOR_TEXT,
            activebackground=support.COLOR_TRACK,
            activeforeground=support.COLOR_TEXT,
            relief="flat",
            bd=0,
            padx=pad_x,
            pady=pad_y,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=support.COLOR_TRACK,
        )

    # -------------------------------------------------------------
    # Taskbar Dock Widget (Embedded into Shell_TrayWnd, Photo 3/4)
    # -------------------------------------------------------------
    def _build_taskbar_dock(self):
        self.dock_frame = tk.Frame(
            self.root,
            bg=self.theme["bg"],
            padx=5,
            pady=2,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            cursor="hand2",
        )
        self.dock_frame.pack(fill="both", expand=True)

        self.context_menu = tk.Menu(self.dock_frame, tearoff=0)
        self.context_menu.add_command(label=t("refresh_now", lang=self.lang), command=self.refresh_ai)
        self.context_menu.add_command(label=t("open_card", lang=self.lang), command=self.show_card)
        self.context_menu.add_command(label=t("settings_menu", lang=self.lang), command=self.open_settings)
        self.context_menu.add_separator()
        self.context_menu.add_command(label=t("quit_menu", lang=self.lang), command=self.quit_app)

        self._populate_dock_items(self.dock_frame, is_secondary=False)

    def _popup_menu(self, event):
        try:
            self._hide_hover_card_now()
            menu_y = max(10, event.y_root - 145)
            self.context_menu.tk_popup(event.x_root, menu_y)
        finally:
            self.context_menu.grab_release()

    def _populate_dock_items(self, parent_frame, is_secondary=False):
        row = tk.Frame(parent_frame, bg=self.theme["bg"])
        row.pack(fill="both", expand=True)

        added = False
        # GPT
        if self.show_gpt:
            canvas = tk.Canvas(row, width=20, height=11, bg=self.theme["bg"], bd=0, highlightthickness=0)
            canvas.pack(side="left", padx=(0, 2))
            lbl = self._label(row, "GPT —%", color=self.theme["gpt_color"], size=8, bold=True)
            lbl.pack(side="left", padx=(0, 3))
            if is_secondary:
                self.sec_tb_gpt_canvas = canvas
                self.sec_tb_gpt_lbl = lbl
            else:
                self.tb_gpt_canvas = canvas
                self.tb_gpt_lbl = lbl
            added = True
        else:
            if is_secondary:
                self.sec_tb_gpt_canvas = None
                self.sec_tb_gpt_lbl = None
            else:
                self.tb_gpt_canvas = None
                self.tb_gpt_lbl = None

        # GEM
        if self.show_gem:
            if added:
                div = tk.Frame(row, bg=self.theme["divider"], width=1, height=12)
                div.pack(side="left", padx=(0, 3))
            canvas = tk.Canvas(row, width=20, height=11, bg=self.theme["bg"], bd=0, highlightthickness=0)
            canvas.pack(side="left", padx=(0, 2))
            lbl = self._label(row, "GEM —%", color=self.theme["gem_color"], size=8, bold=True)
            lbl.pack(side="left", padx=(0, 3))
            if is_secondary:
                self.sec_tb_gem_canvas = canvas
                self.sec_tb_gem_lbl = lbl
            else:
                self.tb_gem_canvas = canvas
                self.tb_gem_lbl = lbl
            added = True
        else:
            if is_secondary:
                self.sec_tb_gem_canvas = None
                self.sec_tb_gem_lbl = None
            else:
                self.tb_gem_canvas = None
                self.tb_gem_lbl = None

        # Claude
        if self.show_claude:
            if added:
                div = tk.Frame(row, bg=self.theme["divider"], width=1, height=12)
                div.pack(side="left", padx=(0, 3))
            canvas = tk.Canvas(row, width=20, height=11, bg=self.theme["bg"], bd=0, highlightthickness=0)
            canvas.pack(side="left", padx=(0, 2))
            lbl = self._label(row, "CLD —%", color=self.theme["claude_color"], size=8, bold=True)
            lbl.pack(side="left", padx=(0, 3))
            if is_secondary:
                self.sec_tb_claude_canvas = canvas
                self.sec_tb_claude_lbl = lbl
            else:
                self.tb_claude_canvas = canvas
                self.tb_claude_lbl = lbl
            added = True
        else:
            if is_secondary:
                self.sec_tb_claude_canvas = None
                self.sec_tb_claude_lbl = None
            else:
                self.tb_claude_canvas = None
                self.tb_claude_lbl = None

        # RAM
        if self.show_ram:
            if added:
                div = tk.Frame(row, bg=self.theme["divider"], width=1, height=12)
                div.pack(side="left", padx=(0, 3))
            lbl = self._label(row, "RAM —%", color=self.theme["ram_color"], size=8)
            lbl.pack(side="left")
            if is_secondary:
                self.sec_tb_ram_lbl = lbl
            else:
                self.tb_ram_lbl = lbl
        else:
            if is_secondary:
                self.sec_tb_ram_lbl = None
            else:
                self.tb_ram_lbl = None

        if not is_secondary:
            self._bind_dock_recursive(parent_frame, self._popup_menu)
        else:
            self._bind_sec_dock_recursive(parent_frame, self._popup_menu)

    def _bind_dock_recursive(self, widget, popup_menu):
        widget.bind("<Button-1>", self._on_dock_click, add="+")
        widget.bind("<Button-3>", popup_menu, add="+")
        widget.bind("<Enter>", self._on_dock_enter, add="+")
        widget.bind("<Leave>", self._on_dock_leave, add="+")
        for child in widget.winfo_children():
            self._bind_dock_recursive(child, popup_menu)

    def _set_dock_visual_hover(self, hover: bool):
        bg = self.theme["bg_hover"] if hover else self.theme["bg"]
        border = self.theme["border_hover"] if hover else self.theme["border"]
        try:
            self.dock_frame.configure(bg=bg, highlightbackground=border)
            for widget in self.dock_frame.winfo_children():
                widget.configure(bg=bg)
                for sub in widget.winfo_children():
                    if isinstance(sub, (tk.Canvas, tk.Label)):
                        sub.configure(bg=bg)
        except tk.TclError:
            pass

    def _is_pointer_inside(self, widget):
        try:
            if not widget.winfo_exists() or not widget.winfo_viewable():
                return False
            top = widget.winfo_toplevel()
            hwnd = None
            try:
                frame_str = top.wm_frame()
                if frame_str:
                    hwnd = int(frame_str, 16)
            except Exception:
                pass
            if not hwnd:
                hwnd = win.C.windll.user32.GetParent(top.winfo_id()) or top.winfo_id()
            left, top_y, right, bottom = win.get_window_rect(hwnd)
            mx, my = win.get_cursor_pos()
            return (left <= mx < right) and (top_y <= my < bottom)
        except Exception:
            return False

    def _on_dock_enter(self, event=None):
        self._dock_hovered = True
        if self._hide_timer:
            self.root.after_cancel(self._hide_timer)
            self._hide_timer = None
        if not self.hover_card.winfo_viewable() and not self._show_timer:
            self._show_timer = self.root.after(140, self._show_hover_card)
        self._set_dock_visual_hover(True)

    def _on_dock_leave(self, event=None):
        if self._is_pointer_inside(self.dock_frame):
            return
        self._dock_hovered = False
        if self._show_timer:
            self.root.after_cancel(self._show_timer)
            self._show_timer = None
        if not self._hide_timer:
            self._hide_timer = self.root.after(250, self._check_and_hide_hover_card)
        self._set_dock_visual_hover(False)

    def _on_hover_card_enter(self, event=None):
        self._card_hovered = True
        if self._hide_timer:
            self.root.after_cancel(self._hide_timer)
            self._hide_timer = None

    def _on_hover_card_leave(self, event=None):
        if self._is_pointer_inside(self.hover_outer):
            return
        self._card_hovered = False
        if not self._hide_timer:
            self._hide_timer = self.root.after(250, self._check_and_hide_hover_card)

    def _check_and_hide_hover_card(self):
        self._hide_timer = None
        is_sec = self.sec_dock and self._is_pointer_inside(self.sec_dock_frame)
        if self._is_pointer_inside(self.dock_frame) or is_sec or self._is_pointer_inside(self.hover_outer):
            return
        self._dock_hovered = False
        self._sec_dock_hovered = False
        self._card_hovered = False
        if self.hover_card.winfo_viewable():
            self.hover_card.withdraw()

    def _hide_hover_card_now(self):
        if self._show_timer:
            self.root.after_cancel(self._show_timer)
            self._show_timer = None
        if self._hide_timer:
            self.root.after_cancel(self._hide_timer)
            self._hide_timer = None
        self._dock_hovered = False
        self._sec_dock_hovered = False
        self._card_hovered = False
        if self.hover_card.winfo_viewable():
            self.hover_card.withdraw()

    def _show_hover_card(self):
        self._show_timer = None
        is_dock_in = self._dock_hovered or self._is_pointer_inside(self.dock_frame)
        is_sec_in = self._sec_dock_hovered or (self.sec_dock and self._is_pointer_inside(self.sec_dock_frame))
        if not is_dock_in and not is_sec_in:
            return

        self.hover_card.update_idletasks()
        hover_w = 340
        hover_h = max(420, self.hover_card.winfo_reqheight())

        if is_sec_in and self.sec_dock:
            sec_info = win.get_secondary_tray_info()
            if sec_info:
                rSec = sec_info["rect"]
                dock_right = rSec[2] - 103
                hover_x = max(rSec[0] + 10, dock_right - hover_w)
                hover_y = max(10, rSec[1] - hover_h - 6)
            else:
                rx, ry, _, _ = win.get_window_rect(self.sec_dock.winfo_id())
                hover_x = rx
                hover_y = max(10, ry - hover_h - 6)
        else:
            info = win.get_tray_info()
            if info:
                tray_t = info["tray_rect"][1]
                tray_start_l = info.get("tray_start_screen_l", info["notify_screen_l"])
                dock_right = tray_start_l - 4
                hover_x = max(10, dock_right - hover_w)
                hover_y = max(10, tray_t - hover_h - 6)
            else:
                rx, ry, _, _ = win.get_window_rect(self.root.winfo_id())
                hover_x = rx
                hover_y = max(10, ry - hover_h - 6)

        hwnd = None
        try:
            frame_str = self.hover_card.wm_frame()
            if frame_str:
                hwnd = int(frame_str, 16)
        except Exception:
            pass
        if not hwnd:
            hwnd = win.C.windll.user32.GetParent(self.hover_card.winfo_id()) or self.hover_card.winfo_id()

        self.hover_card.deiconify()
        self.hover_card.lift()
        self.hover_card.attributes("-topmost", True)
        win.position_window(hwnd, hover_x, hover_y, hover_w, hover_h, topmost=True, show=True)

    def _on_dock_click(self, event=None):
        self._hide_hover_card_now()
        self.toggle_card()

    def _on_hover_card_click(self, event=None):
        self._hide_hover_card_now()
        self.show_card()

    def _dock_to_taskbar(self):
        info = win.get_tray_info()
        if not info:
            return
        width = self.dock_width
        height = self.dock_height
        tray_t = info["tray_rect"][1]
        tray_h = info["tray_h"]
        tray_start_l = info.get("tray_start_screen_l", info["notify_screen_l"])
        # Snap tightly next to the chevron button with a safe 4px margin (no overlap)
        x = max(10, tray_start_l - width - 4)
        y = tray_t + max(2, (tray_h - height) // 2)

        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.lift()
        self.root.attributes("-topmost", True)

        hwnd = None
        try:
            frame_str = self.root.wm_frame()
            if frame_str:
                hwnd = int(frame_str, 16)
        except Exception:
            pass
        if not hwnd:
            hwnd = win.C.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        win.dock_to_taskbar(hwnd, width=width, height=height)

        if self.sec_dock:
            self._dock_secondary_taskbar()

    def _build_secondary_taskbar_dock(self):
        sec_info = win.get_secondary_tray_info()
        if not sec_info:
            return

        self.sec_dock = tk.Toplevel(self.root)
        self.sec_dock.title("AIUsageSecondaryTaskbarDock")
        self.sec_dock.configure(bg=self.theme["bg"])
        self.sec_dock.overrideredirect(True)
        rSec = sec_info["rect"]
        clock_margin = 103
        sec_x = rSec[2] - self.dock_width - clock_margin
        sec_y = rSec[1] + max(2, (sec_info["h"] - self.dock_height) // 2)
        self.sec_dock.geometry(f"{self.dock_width}x{self.dock_height}+{sec_x}+{sec_y}")

        self.sec_dock_frame = tk.Frame(
            self.sec_dock,
            bg=self.theme["bg"],
            padx=5,
            pady=2,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            cursor="hand2",
        )
        self.sec_dock_frame.pack(fill="both", expand=True)

        self._populate_dock_items(self.sec_dock_frame, is_secondary=True)

    def _rebuild_dock(self):
        self.dock_width = self._compute_dock_width()
        for child in self.dock_frame.winfo_children():
            child.destroy()
        self._populate_dock_items(self.dock_frame, is_secondary=False)

        if self.sec_dock:
            for child in self.sec_dock_frame.winfo_children():
                child.destroy()
            self._populate_dock_items(self.sec_dock_frame, is_secondary=True)

        self._update_ui()
        self._dock_to_taskbar()

    def _bind_sec_dock_recursive(self, widget, popup_menu):
        widget.bind("<Button-1>", self._on_dock_click, add="+")
        widget.bind("<Button-3>", popup_menu, add="+")
        widget.bind("<Enter>", self._on_sec_dock_enter, add="+")
        widget.bind("<Leave>", self._on_sec_dock_leave, add="+")
        for child in widget.winfo_children():
            self._bind_sec_dock_recursive(child, popup_menu)

    def _on_sec_dock_enter(self, event=None):
        self._sec_dock_hovered = True
        if self._hide_timer:
            self.root.after_cancel(self._hide_timer)
            self._hide_timer = None
        if not self.hover_card.winfo_viewable() and not self._show_timer:
            self._show_timer = self.root.after(140, self._show_hover_card)
        self._set_sec_dock_visual_hover(True)

    def _on_sec_dock_leave(self, event=None):
        if self.sec_dock and self._is_pointer_inside(self.sec_dock_frame):
            return
        self._sec_dock_hovered = False
        if self._show_timer:
            self.root.after_cancel(self._show_timer)
            self._show_timer = None
        if not self._hide_timer:
            self._hide_timer = self.root.after(250, self._check_and_hide_hover_card)
        self._set_sec_dock_visual_hover(False)

    def _set_sec_dock_visual_hover(self, hover: bool):
        if not self.sec_dock:
            return
        bg = self.theme["bg_hover"] if hover else self.theme["bg"]
        border = self.theme["border_hover"] if hover else self.theme["border"]
        try:
            self.sec_dock_frame.configure(bg=bg, highlightbackground=border)
            for widget in self.sec_dock_frame.winfo_children():
                widget.configure(bg=bg)
                for sub in widget.winfo_children():
                    if isinstance(sub, (tk.Canvas, tk.Label)):
                        sub.configure(bg=bg)
        except tk.TclError:
            pass

    def _dock_secondary_taskbar(self):
        sec_info = win.get_secondary_tray_info()
        if not sec_info or not self.sec_dock:
            return
        rSec = sec_info["rect"]
        clock_margin = 103
        x = rSec[2] - self.dock_width - clock_margin
        y = rSec[1] + max(2, (sec_info["h"] - self.dock_height) // 2)

        self.sec_dock.lift()
        self.sec_dock.attributes("-topmost", True)

        hwnd = None
        try:
            frame_str = self.sec_dock.wm_frame()
            if frame_str:
                hwnd = int(frame_str, 16)
        except Exception:
            pass
        if not hwnd:
            hwnd = win.C.windll.user32.GetParent(self.sec_dock.winfo_id()) or self.sec_dock.winfo_id()
        win.dock_to_secondary_taskbar(hwnd, width=self.dock_width, height=self.dock_height)

    # -------------------------------------------------------------
    # Hover Card Window (Photo 2 Reference)
    # -------------------------------------------------------------
    def _build_hover_card(self):
        self.hover_card = tk.Toplevel(self.root)
        self.hover_card.title("AIUsageHoverCard")
        self.hover_card.configure(bg=self.theme["bg"])
        self.hover_card.overrideredirect(True)
        self.hover_card.resizable(False, False)
        self.hover_card.withdraw()

        self.hover_outer = tk.Frame(
            self.hover_card,
            bg=self.theme["bg"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=14,
            pady=10,
            cursor="hand2",
        )
        self.hover_outer.pack(fill="both", expand=True)

        # 1. Header
        header = tk.Frame(self.hover_outer, bg=self.theme["bg"])
        header.pack(fill="x", pady=(0, 4))

        h_top = tk.Frame(header, bg=self.theme["bg"])
        h_top.pack(fill="x")
        self._label(h_top, t("hover_title", lang=self.lang), color=self.theme["text"], size=10, bold=True).pack(side="left")

        self.hover_refresh_tag = self._label(h_top, t("live_monitor", lang=self.lang), color=self.theme["text_muted"], size=8)
        self.hover_refresh_tag.pack(side="right")

        self._label(header, t("hover_subtitle", lang=self.lang), color=self.theme["text_muted"], size=8).pack(anchor="w", pady=(1, 0))

        tk.Frame(self.hover_outer, bg=self.theme["divider"], height=1).pack(fill="x", pady=(4, 6))

        def create_hover_quota(parent, label_text):
            f = tk.Frame(parent, bg=self.theme["box_bg"])
            f.pack(fill="x", pady=(1, 2))
            top = tk.Frame(f, bg=self.theme["box_bg"])
            top.pack(fill="x")
            self._label(top, label_text, color=self.theme["text"], size=8, bold=True).pack(side="left")
            pct = self._label(top, "조회 중", color=self.theme["text_muted"], size=8)
            pct.pack(side="right")
            bar = tk.Canvas(f, width=308, height=4, bg=self.theme["bar_bg"], bd=0, highlightthickness=0)
            bar.pack(fill="x", pady=(2, 1))
            reset = self._label(f, "초기화: 대기 중", color=self.theme["text_muted"], size=7)
            reset.pack(anchor="w")
            return {"pct": pct, "bar": bar, "reset": reset}

        # 2. Codex / GPT Section
        gpt_box = tk.Frame(self.hover_outer, bg=self.theme["box_bg"], padx=10, pady=6, highlightthickness=1, highlightbackground=self.theme["box_border"])
        gpt_box.pack(fill="x", pady=(0, 5))

        gpt_top = tk.Frame(gpt_box, bg=self.theme["box_bg"])
        gpt_top.pack(fill="x", pady=(0, 2))
        self._label(gpt_top, "● Codex / GPT", color=self.theme["gpt_color"], size=9, bold=True).pack(side="left")
        self.hover_gpt_plan = self._label(gpt_top, "Plus", color=self.theme["text_muted"], size=8)
        self.hover_gpt_plan.pack(side="right")

        self.hover_gpt_5h = create_hover_quota(gpt_box, "5시간 (5H)")
        self.hover_gpt_wk = create_hover_quota(gpt_box, "주간 (WK)")

        gpt_pred_box = tk.Frame(gpt_box, bg=self.theme["bg"], padx=8, pady=3, highlightthickness=1, highlightbackground=self.theme["box_border"])
        gpt_pred_box.pack(fill="x", pady=(3, 0))
        self.hover_gpt_speed_lbl = self._label(gpt_pred_box, "⚡ 소비 속도 측정 중 (안정)", color=self.theme["battery_green"], size=8, bold=True)
        self.hover_gpt_speed_lbl.pack(anchor="w")
        self.hover_gpt_forecast_lbl = self._label(gpt_pred_box, "소진 위험 없음 · 초기화 시각까지 충분", color=self.theme["text_muted"], size=8)
        self.hover_gpt_forecast_lbl.pack(anchor="w")

        # 3. Gemini Section
        gem_box = tk.Frame(self.hover_outer, bg=self.theme["box_bg"], padx=10, pady=6, highlightthickness=1, highlightbackground=self.theme["box_border"])
        gem_box.pack(fill="x", pady=(0, 5))

        gem_top = tk.Frame(gem_box, bg=self.theme["box_bg"])
        gem_top.pack(fill="x", pady=(0, 2))
        self._label(gem_top, "● Gemini", color=self.theme["gem_color"], size=9, bold=True).pack(side="left")
        self.hover_gem_plan = self._label(gem_top, "Google AI Pro", color=self.theme["text_muted"], size=8)
        self.hover_gem_plan.pack(side="right")

        self.hover_gem_5h = create_hover_quota(gem_box, "5시간 (5H)")
        self.hover_gem_wk = create_hover_quota(gem_box, "주간 (WK)")

        gem_pred_box = tk.Frame(gem_box, bg=self.theme["bg"], padx=8, pady=3, highlightthickness=1, highlightbackground=self.theme["box_border"])
        gem_pred_box.pack(fill="x", pady=(3, 0))
        self.hover_gem_speed_lbl = self._label(gem_pred_box, "⚡ 소비 속도 측정 중 (안정)", color=self.theme["battery_green"], size=8, bold=True)
        self.hover_gem_speed_lbl.pack(anchor="w")
        self.hover_gem_forecast_lbl = self._label(gem_pred_box, "소진 위험 없음 · 초기화 시각까지 충분", color=self.theme["text_muted"], size=8)
        self.hover_gem_forecast_lbl.pack(anchor="w")

        # 4. Anthropic Claude Section (Optional / Extensible)
        claude_box = tk.Frame(self.hover_outer, bg=self.theme["box_bg"], padx=10, pady=6, highlightthickness=1, highlightbackground=self.theme["box_border"])
        self.hover_claude_box = claude_box
        if self.show_claude:
            claude_box.pack(fill="x", pady=(0, 5))

        claude_top = tk.Frame(claude_box, bg=self.theme["box_bg"])
        claude_top.pack(fill="x", pady=(0, 2))
        self._label(claude_top, "● Anthropic Claude", color=self.theme["claude_color"], size=9, bold=True).pack(side="left")
        self.hover_claude_plan = self._label(claude_top, "Claude Pro", color=self.theme["text_muted"], size=8)
        self.hover_claude_plan.pack(side="right")

        self.hover_claude_5h = create_hover_quota(claude_box, "세션 / 5시간 (5H)")
        self.hover_claude_wk = create_hover_quota(claude_box, "주간 / 일일 (Quota)")

        claude_pred_box = tk.Frame(claude_box, bg=self.theme["bg"], padx=8, pady=3, highlightthickness=1, highlightbackground=self.theme["box_border"])
        claude_pred_box.pack(fill="x", pady=(3, 0))
        self.hover_claude_speed_lbl = self._label(claude_pred_box, "⚡ 소비 속도 측정 중 (안정)", color=self.theme["battery_green"], size=8, bold=True)
        self.hover_claude_speed_lbl.pack(anchor="w")
        self.hover_claude_forecast_lbl = self._label(claude_pred_box, "소진 위험 없음 · 초기화 시각까지 충분", color=self.theme["text_muted"], size=8)
        self.hover_claude_forecast_lbl.pack(anchor="w")

        # 4. PC Performance Section
        pc_box = tk.Frame(self.hover_outer, bg=self.theme["box_bg"], padx=10, pady=5, highlightthickness=1, highlightbackground=self.theme["box_border"])
        pc_box.pack(fill="x", pady=(0, 4))

        pc_top = tk.Frame(pc_box, bg=self.theme["box_bg"])
        pc_top.pack(fill="x")
        self._label(pc_top, "💻 내 컴퓨터 성능", color=self.theme["text"], size=8, bold=True).pack(side="left")
        self.hover_ram_lbl = self._label(pc_top, "RAM —%", color=self.theme["text_muted"], size=8)
        self.hover_ram_lbl.pack(side="right")

        self.hover_ram_bar = tk.Canvas(pc_box, width=308, height=3, bg=self.theme["bar_bg"], bd=0, highlightthickness=0)
        self.hover_ram_bar.pack(fill="x", pady=(2, 2))

        self.hover_pc_sub_lbl = self._label(pc_box, "CPU: —% · 온도: —°C · 이더넷: ↓ — · ↑ —", color=self.theme["text_muted"], size=7)
        self.hover_pc_sub_lbl.pack(anchor="w")

        self._bind_hover_card_recursive(self.hover_outer)

    def _bind_hover_card_recursive(self, widget):
        widget.bind("<Enter>", self._on_hover_card_enter, add="+")
        widget.bind("<Leave>", self._on_hover_card_leave, add="+")
        widget.bind("<Button-1>", self._on_hover_card_click, add="+")
        for child in widget.winfo_children():
            self._bind_hover_card_recursive(child)

    # -------------------------------------------------------------
    # Full Card Window (Photo 1 Rich detail card)
    # -------------------------------------------------------------
    def _build_card_window(self):
        self.card_window = tk.Toplevel(self.root)
        self.card_window.title("AI & PC 모니터")
        self.card_window.configure(bg=support.COLOR_BG)
        self.card_window.resizable(False, False)
        self.card_window.protocol("WM_DELETE_WINDOW", self.on_close_requested)

        icon_path = win.BASE / "assets" / "usage.ico"
        if icon_path.exists():
            self.card_window.iconbitmap(str(icon_path))

        card_frame = tk.Frame(self.card_window, bg=support.COLOR_BG, padx=16, pady=14)
        card_frame.pack(fill="both", expand=True)

        # 1. Header with Battery Summary
        top_bar = tk.Frame(card_frame, bg=support.COLOR_BG)
        top_bar.pack(fill="x", pady=(0, 10))

        title_lbl = self._label(top_bar, "AI & PC 모니터", size=13, bold=True)
        title_lbl.pack(side="left")

        battery_frame = tk.Frame(top_bar, bg=support.COLOR_CARD, padx=8, pady=4)
        battery_frame.pack(side="right")

        self.gpt_batt_canvas = tk.Canvas(battery_frame, width=28, height=13, bg=support.COLOR_CARD, bd=0, highlightthickness=0)
        self.gpt_batt_canvas.pack(side="left", padx=(0, 4))
        self.gpt_batt_lbl = self._label(battery_frame, "GPT —%", size=9, bold=True)
        self.gpt_batt_lbl.pack(side="left", padx=(0, 8))

        self.gem_batt_canvas = tk.Canvas(battery_frame, width=28, height=13, bg=support.COLOR_CARD, bd=0, highlightthickness=0)
        self.gem_batt_canvas.pack(side="left", padx=(0, 4))
        self.gem_batt_lbl = self._label(battery_frame, "GEM —%", size=9, bold=True)
        self.gem_batt_lbl.pack(side="left", padx=(0, 8 if self.show_claude else 0))

        self.claude_batt_canvas = tk.Canvas(battery_frame, width=28, height=13, bg=support.COLOR_CARD, bd=0, highlightthickness=0)
        self.claude_batt_lbl = self._label(battery_frame, "CLD —%", size=9, bold=True)
        if self.show_claude:
            self.claude_batt_canvas.pack(side="left", padx=(0, 4))
            self.claude_batt_lbl.pack(side="left")

        # 2. Codex / GPT Card
        gpt_card = tk.Frame(card_frame, bg=support.COLOR_CARD, padx=12, pady=10)
        gpt_card.pack(fill="x", pady=(0, 8))
        gpt_head = tk.Frame(gpt_card, bg=support.COLOR_CARD)
        gpt_head.pack(fill="x")
        self._label(gpt_head, "Codex / GPT (ChatGPT Work 공유)", size=10, bold=True).pack(side="left")
        self.gpt_plan_lbl = self._label(gpt_head, "Plus", support.COLOR_MUTED, size=8)
        self.gpt_plan_lbl.pack(side="right")

        self.gpt_5h_row = self._create_quota_row(gpt_card, "5시간 (5H)")
        self.gpt_wk_row = self._create_quota_row(gpt_card, "주간 (WK)")

        # 3. Gemini Card
        gem_card = tk.Frame(card_frame, bg=support.COLOR_CARD, padx=12, pady=10)
        gem_card.pack(fill="x", pady=(0, 8))
        gem_head = tk.Frame(gem_card, bg=support.COLOR_CARD)
        gem_head.pack(fill="x")
        self._label(gem_head, "Gemini (Google AI Models)", size=10, bold=True).pack(side="left")
        self.gem_plan_lbl = self._label(gem_head, "Google AI Pro", support.COLOR_MUTED, size=8)
        self.gem_plan_lbl.pack(side="right")

        self.gem_5h_row = self._create_quota_row(gem_card, "5시간 (5H)")
        self.gem_wk_row = self._create_quota_row(gem_card, "주간 (WK)")

        # 3.5. Anthropic Claude Card (Modular / Extensible)
        claude_card = tk.Frame(card_frame, bg=support.COLOR_CARD, padx=12, pady=10)
        self.claude_card = claude_card
        claude_head = tk.Frame(claude_card, bg=support.COLOR_CARD)
        claude_head.pack(fill="x")
        self._label(claude_head, "Anthropic Claude (Web / API / Code)", size=10, bold=True).pack(side="left")
        self.claude_plan_lbl = self._label(claude_head, "Claude Pro", support.COLOR_MUTED, size=8)
        self.claude_plan_lbl.pack(side="right")

        self.claude_5h_row = self._create_quota_row(claude_card, "세션 / 5시간 (5H)")
        self.claude_wk_row = self._create_quota_row(claude_card, "주간 / 일일 (Quota)")
        if self.show_claude:
            claude_card.pack(fill="x", pady=(0, 8))

        # 4. PC Performance Card
        pc_card = tk.Frame(card_frame, bg=support.COLOR_CARD, padx=12, pady=9)
        pc_card.pack(fill="x", pady=(0, 8))
        pc_head = tk.Frame(pc_card, bg=support.COLOR_CARD)
        pc_head.pack(fill="x", pady=(0, 4))
        self._label(pc_head, "내 컴퓨터 성능 (실시간)", size=10, bold=True).pack(side="left")
        self.pc_temp_lbl = self._label(pc_head, "온도 —°C", support.COLOR_MUTED, size=8)
        self.pc_temp_lbl.pack(side="right")

        ram_row = tk.Frame(pc_card, bg=support.COLOR_CARD)
        ram_row.pack(fill="x", pady=1)
        self._label(ram_row, "RAM 메모리", size=9, bold=True).pack(side="left")
        self.ram_detail_lbl = self._label(ram_row, "— / — GB (—%)", support.COLOR_TEXT, size=9)
        self.ram_detail_lbl.pack(side="right")

        self.ram_bar = tk.Canvas(pc_card, width=280, height=5, bg=support.COLOR_TRACK, bd=0, highlightthickness=0)
        self.ram_bar.pack(fill="x", pady=(2, 6))

        sys_sub = tk.Frame(pc_card, bg=support.COLOR_CARD)
        sys_sub.pack(fill="x")
        self.cpu_lbl = self._label(sys_sub, "CPU: —%", support.COLOR_MUTED, size=9)
        self.cpu_lbl.pack(side="left")
        self.net_lbl = self._label(sys_sub, "이더넷: ↓ — · ↑ —", support.COLOR_MUTED, size=9)
        self.net_lbl.pack(side="right")

        # 5. Status & Actions
        self.status_lbl = self._label(card_frame, "연결 준비 중…", support.COLOR_MUTED, size=8)
        self.status_lbl.pack(anchor="w", pady=(2, 6))

        actions = tk.Frame(card_frame, bg=support.COLOR_BG)
        actions.pack(fill="x")
        self.refresh_btn = self._button(actions, "새로고침", self.refresh_ai, accent=True)
        self.refresh_btn.pack(side="left")
        self._button(actions, "설정", self.open_settings).pack(side="left", padx=5)
        self._button(actions, "최소화", self.card_window.withdraw).pack(side="right")

        self._label(card_frame, "작업 표시줄 위젯을 클릭하여 창을 열고 닫을 수 있습니다.", support.COLOR_MUTED, size=8).pack(pady=(8, 0))

        win.style_window(self.card_window)

    def _create_quota_row(self, parent, title: str):
        row = tk.Frame(parent, bg=support.COLOR_CARD)
        row.pack(fill="x", pady=(3, 1))

        top = tk.Frame(row, bg=support.COLOR_CARD)
        top.pack(fill="x")
        self._label(top, title, size=9).pack(side="left")
        pct_lbl = self._label(top, "조회 중", support.COLOR_MUTED, size=9)
        pct_lbl.pack(side="right")

        bar = tk.Canvas(row, width=280, height=5, bg=support.COLOR_TRACK, bd=0, highlightthickness=0)
        bar.pack(fill="x", pady=(2, 2))

        reset_lbl = self._label(row, "초기화: 대기 중", support.COLOR_MUTED, size=8)
        reset_lbl.pack(anchor="w")
        return {"pct": pct_lbl, "bar": bar, "reset": reset_lbl}

    # -------------------------------------------------------------
    # Window Actions & Close Prompt Dialog
    # -------------------------------------------------------------
    def show_card(self):
        self.card_window.update_idletasks()
        w = max(360, self.card_window.winfo_reqwidth())
        h = max(560, self.card_window.winfo_reqheight())

        mx, my = win.get_cursor_pos()
        sec_info = win.get_secondary_tray_info()
        if mx < 0 and sec_info:
            rSec = sec_info["rect"]
            x = max(rSec[0] + 10, rSec[2] - w - 103)
            y = max(10, rSec[1] - h - 16)
        else:
            info = win.get_tray_info()
            if info:
                x = max(10, info["notify_screen_l"] - w - 8)
                y = max(10, info["tray_rect"][1] - h - 48)
            else:
                left, top, right, bottom = win.work_area(self.root)
                x = max(10, right - w - 16)
                y = max(10, bottom - h - 48)

        hwnd = None
        try:
            frame_str = self.card_window.wm_frame()
            if frame_str:
                hwnd = int(frame_str, 16)
        except Exception:
            pass
        if not hwnd:
            hwnd = win.C.windll.user32.GetParent(self.card_window.winfo_id()) or self.card_window.winfo_id()

        self.card_window.deiconify()
        self.card_window.lift()
        self.card_window.focus_force()
        win.position_window(hwnd, x, y, w, h, topmost=False, show=True)
        win.foreground(self.card_window)

    def toggle_card(self):
        if self.card_window.winfo_viewable():
            self.card_window.withdraw()
        else:
            self.show_card()

    def on_close_requested(self):
        action = self.settings.get("on_close_action", "ask")
        if action == "minimize":
            self.card_window.withdraw()
            return
        elif action == "quit":
            self.quit_app()
            return

        # Show prompt dialog: ask whether to minimize to taskbar or quit completely
        if self.prompt_dialog and self.prompt_dialog.winfo_exists():
            win.foreground(self.prompt_dialog)
            return

        dlg = tk.Toplevel(self.card_window)
        self.prompt_dialog = dlg
        dlg.title("AI & PC 모니터")
        dlg.configure(bg="#191C23")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)

        f = tk.Frame(dlg, bg="#191C23", padx=24, pady=20)
        f.pack()

        self._label(f, "창을 닫을 때 어떻게 처리할까요?", size=11, bold=True).pack(anchor="w", pady=(0, 6))
        self._label(f, "작업 표시줄에 켜두시면 실시간 사용량을 계속 확인하실 수 있습니다.", support.COLOR_MUTED, size=9).pack(anchor="w", pady=(0, 16))

        btn_box = tk.Frame(f, bg="#191C23")
        btn_box.pack(fill="x", pady=(0, 14))

        var_remember = tk.BooleanVar(value=False)

        def choose_minimize():
            if var_remember.get():
                self.settings["on_close_action"] = "minimize"
                support.save_settings(self.settings)
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()
            self.card_window.withdraw()

        def choose_quit():
            if var_remember.get():
                self.settings["on_close_action"] = "quit"
                support.save_settings(self.settings)
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()
            self.quit_app()

        def choose_cancel():
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", choose_cancel)

        b_min = tk.Button(
            btn_box,
            text="작업 표시줄에 켜두기 (최소화)",
            command=choose_minimize,
            bg="#2A483D",
            fg=support.COLOR_TEXT,
            activebackground=support.COLOR_TRACK,
            activeforeground=support.COLOR_TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
            font=("맑은 고딕", 9, "bold"),
            cursor="hand2",
        )
        b_min.pack(side="left", padx=(0, 8))

        b_quit = tk.Button(
            btn_box,
            text="프로그램 완전 종료",
            command=choose_quit,
            bg=support.COLOR_CARD,
            fg=support.COLOR_TEXT,
            activebackground=support.COLOR_TRACK,
            activeforeground=support.COLOR_TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            font=("맑은 고딕", 9),
            cursor="hand2",
        )
        b_quit.pack(side="left", padx=(0, 8))

        b_cancel = tk.Button(
            btn_box,
            text="취소",
            command=choose_cancel,
            bg="#191C23",
            fg=support.COLOR_MUTED,
            activebackground=support.COLOR_CARD,
            activeforeground=support.COLOR_TEXT,
            relief="flat",
            bd=0,
            padx=8,
            pady=6,
            font=("맑은 고딕", 9),
            cursor="hand2",
        )
        b_cancel.pack(side="left")

        chk = tk.Checkbutton(
            f,
            text="다음부터 묻지 않고 이 동작으로 실행",
            variable=var_remember,
            bg="#191C23",
            fg=support.COLOR_MUTED,
            selectcolor=support.COLOR_CARD,
            activebackground="#191C23",
            activeforeground=support.COLOR_TEXT,
            font=("맑은 고딕", 8),
        )
        chk.pack(anchor="w")

        dlg.update_idletasks()
        # Center dialog over card window
        cx = self.card_window.winfo_x() + (self.card_window.winfo_width() - dlg.winfo_reqwidth()) // 2
        cy = self.card_window.winfo_y() + (self.card_window.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry(f"+{max(10, cx)}+{max(10, cy)}")
        win.foreground(dlg)

    def quit_app(self):
        self.closing = True
        if self.sec_dock:
            try:
                self.sec_dock.destroy()
            except Exception:
                pass
        try:
            self.card_window.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # -------------------------------------------------------------
    # AI Query & Update Loop
    # -------------------------------------------------------------
    def refresh_ai(self):
        if self.busy or self.closing:
            return
        self.busy = True
        self.refresh_btn.configure(state="disabled")
        self.status_lbl.configure(text="AI 사용량을 조회하고 있습니다…", fg=support.COLOR_MUTED)

        def worker():
            codex_res = None
            gemini_res = None
            claude_res = None
            codex_err = None
            gemini_err = None
            claude_err = None
            try:
                codex_res = query_codex(timeout=10)
            except Exception as e:
                codex_err = str(e)

            try:
                gemini_res = query_gemini_usage(timeout=5)
            except Exception as e:
                gemini_err = str(e)

            if self.show_claude:
                try:
                    claude_res = query_claude_usage(timeout=5)
                except Exception as e:
                    claude_err = str(e)

            self.ai_results.put((codex_res, gemini_res, claude_res, codex_err, gemini_err, claude_err))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _render_bar(self, canvas: tk.Canvas, percent: float | None):
        canvas.delete("all")
        if percent is None:
            return
        w = canvas.winfo_width()
        if w <= 1:
            w = 280
        h = canvas.winfo_height()
        if h <= 1:
            h = 5
        color = support.battery_color(percent)
        fill_w = max(0, int(w * (min(100.0, percent) / 100.0)))
        canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline="")

    def _render_custom_bar(self, canvas: tk.Canvas, percent: float | None, fill_color: str):
        canvas.delete("all")
        if percent is None:
            return
        w = canvas.winfo_width()
        if w <= 1:
            w = canvas.winfo_reqwidth()
            if w <= 1:
                w = 308
        h = canvas.winfo_height()
        if h <= 1:
            h = canvas.winfo_reqheight()
            if h <= 1:
                h = 4
        fill_w = max(0, int(w * (min(100.0, percent) / 100.0)))
        canvas.create_rectangle(0, 0, fill_w, h, fill=fill_color, outline="")

    def _update_ui(self):
        rem_gpt = None
        rem_gem = None
        rem_claude = None

        # 1. Update Codex / GPT
        if self.codex_snapshot and self.codex_snapshot.primary:
            rem = self.codex_snapshot.primary.remaining_percent
            used = self.codex_snapshot.primary.used_percent
            rem_gpt = rem
            self.gpt_5h_row["pct"].configure(
                text=f"남음 {int(rem)}% · 사용 {int(used)}%",
                fg=support.battery_color(rem),
            )
            self._render_bar(self.gpt_5h_row["bar"], rem)
            self.gpt_5h_row["reset"].configure(text=support.format_reset_time(self.codex_snapshot.primary.resets_at, lang=self.lang))

            support.draw_battery(self.gpt_batt_canvas, rem)
            self.gpt_batt_lbl.configure(text=f"GPT {int(rem)}%", fg=support.battery_color(rem))

            # Hover card Codex 5H
            self.hover_gpt_5h["pct"].configure(text=f"남음 {int(rem)}% (사용 {int(used)}%)", fg=self.theme["gpt_color"])
            self._render_custom_bar(self.hover_gpt_5h["bar"], rem, self.theme["gpt_color"])
            self.hover_gpt_5h["reset"].configure(text=support.format_reset_time(self.codex_snapshot.primary.resets_at, lang=self.lang))

        if self.codex_snapshot and self.codex_snapshot.secondary:
            rem = self.codex_snapshot.secondary.remaining_percent
            used = self.codex_snapshot.secondary.used_percent
            self.gpt_wk_row["pct"].configure(
                text=f"남음 {int(rem)}% · 사용 {int(used)}%",
                fg=support.battery_color(rem),
            )
            self._render_bar(self.gpt_wk_row["bar"], rem)
            self.gpt_wk_row["reset"].configure(text=support.format_reset_time(self.codex_snapshot.secondary.resets_at, lang=self.lang))

            # Hover card Codex WK
            self.hover_gpt_wk["pct"].configure(text=f"남음 {int(rem)}% (사용 {int(used)}%)", fg=self.theme["gpt_color"])
            self._render_custom_bar(self.hover_gpt_wk["bar"], rem, self.theme["gpt_color"])
            self.hover_gpt_wk["reset"].configure(text=support.format_reset_time(self.codex_snapshot.secondary.resets_at, lang=self.lang))

        if self.codex_snapshot:
            plan_str = self.codex_snapshot.plan.capitalize() if self.codex_snapshot.plan else "Plus"
            self.gpt_plan_lbl.configure(text=plan_str)
            self.hover_gpt_plan.configure(text=plan_str)

        # 2. Update Gemini
        if self.gemini_snapshot and self.gemini_snapshot.five_hour:
            rem = self.gemini_snapshot.five_hour.remaining_percent
            used = self.gemini_snapshot.five_hour.used_percent
            rem_gem = rem
            self.gem_5h_row["pct"].configure(
                text=f"남음 {int(rem)}% · 사용 {int(used)}%",
                fg=support.battery_color(rem),
            )
            self._render_bar(self.gem_5h_row["bar"], rem)
            self.gem_5h_row["reset"].configure(text=support.format_reset_time(self.gemini_snapshot.five_hour.resets_at_ts, lang=self.lang))

            support.draw_battery(self.gem_batt_canvas, rem)
            self.gem_batt_lbl.configure(text=f"GEM {int(rem)}%", fg=support.battery_color(rem))

            # Hover card Gemini 5H
            self.hover_gem_5h["pct"].configure(text=f"남음 {int(rem)}% (사용 {int(used)}%)", fg=self.theme["gem_color"])
            self._render_custom_bar(self.hover_gem_5h["bar"], rem, self.theme["gem_color"])
            self.hover_gem_5h["reset"].configure(text=support.format_reset_time(self.gemini_snapshot.five_hour.resets_at_ts, lang=self.lang))

        if self.gemini_snapshot and self.gemini_snapshot.weekly:
            rem = self.gemini_snapshot.weekly.remaining_percent
            used = self.gemini_snapshot.weekly.used_percent
            self.gem_wk_row["pct"].configure(
                text=f"남음 {int(rem)}% · 사용 {int(used)}%",
                fg=support.battery_color(rem),
            )
            self._render_bar(self.gem_wk_row["bar"], rem)
            self.gem_wk_row["reset"].configure(text=support.format_reset_time(self.gemini_snapshot.weekly.resets_at_ts, lang=self.lang))

            # Hover card Gemini WK
            self.hover_gem_wk["pct"].configure(text=f"남음 {int(rem)}% (사용 {int(used)}%)", fg=self.theme["gem_color"])
            self._render_custom_bar(self.hover_gem_wk["bar"], rem, self.theme["gem_color"])
            self.hover_gem_wk["reset"].configure(text=support.format_reset_time(self.gemini_snapshot.weekly.resets_at_ts, lang=self.lang))

        if self.gemini_snapshot:
            plan_str = self.gemini_snapshot.plan or "Google AI Pro"
            self.gem_plan_lbl.configure(text=plan_str)
            self.hover_gem_plan.configure(text=plan_str)

        # 2.5. Update Anthropic Claude
        if self.claude_snapshot and self.claude_snapshot.five_hour:
            rem = self.claude_snapshot.five_hour.remaining_percent
            used = self.claude_snapshot.five_hour.used_percent
            rem_claude = rem
            self.claude_5h_row["pct"].configure(
                text=f"남음 {int(rem)}% · 사용 {int(used)}%",
                fg=support.battery_color(rem),
            )
            self._render_bar(self.claude_5h_row["bar"], rem)
            self.claude_5h_row["reset"].configure(text=support.format_reset_time(self.claude_snapshot.five_hour.resets_at_ts, lang=self.lang))

            if self.show_claude:
                support.draw_battery(self.claude_batt_canvas, rem)
                self.claude_batt_lbl.configure(text=f"CLD {int(rem)}%", fg=support.battery_color(rem))

            # Hover card Claude 5H
            self.hover_claude_5h["pct"].configure(text=f"남음 {int(rem)}% (사용 {int(used)}%)", fg=self.theme["claude_color"])
            self._render_custom_bar(self.hover_claude_5h["bar"], rem, self.theme["claude_color"])
            self.hover_claude_5h["reset"].configure(text=support.format_reset_time(self.claude_snapshot.five_hour.resets_at_ts, lang=self.lang))

        if self.claude_snapshot and self.claude_snapshot.weekly:
            rem = self.claude_snapshot.weekly.remaining_percent
            used = self.claude_snapshot.weekly.used_percent
            self.claude_wk_row["pct"].configure(
                text=f"남음 {int(rem)}% · 사용 {int(used)}%",
                fg=support.battery_color(rem),
            )
            self._render_bar(self.claude_wk_row["bar"], rem)
            self.claude_wk_row["reset"].configure(text=support.format_reset_time(self.claude_snapshot.weekly.resets_at_ts, lang=self.lang))

            # Hover card Claude WK
            self.hover_claude_wk["pct"].configure(text=f"남음 {int(rem)}% (사용 {int(used)}%)", fg=self.theme["claude_color"])
            self._render_custom_bar(self.hover_claude_wk["bar"], rem, self.theme["claude_color"])
            self.hover_claude_wk["reset"].configure(text=support.format_reset_time(self.claude_snapshot.weekly.resets_at_ts, lang=self.lang))

        if self.claude_snapshot:
            plan_str = self.claude_snapshot.plan or "Claude Pro"
            self.claude_plan_lbl.configure(text=plan_str)
            self.hover_claude_plan.configure(text=plan_str)

        # 3. Consumption Tracker (Burn Rate & Forecast)
        self.tracker.record(rem_gpt, rem_gem, rem_claude)
        gpt_m = self.tracker.get_metrics("gpt")
        gem_m = self.tracker.get_metrics("gemini")
        cld_m = self.tracker.get_metrics("claude")

        self.hover_gpt_speed_lbl.configure(text=f"⚡ {gpt_m['speed_label']}", fg=gpt_m["speed_color"])
        self.hover_gpt_forecast_lbl.configure(text=gpt_m["forecast_label"])

        self.hover_gem_speed_lbl.configure(text=f"⚡ {gem_m['speed_label']}", fg=gem_m["speed_color"])
        self.hover_gem_forecast_lbl.configure(text=gem_m["forecast_label"])

        self.hover_claude_speed_lbl.configure(text=f"⚡ {cld_m['speed_label']}", fg=cld_m["speed_color"])
        self.hover_claude_forecast_lbl.configure(text=cld_m["forecast_label"])

        # 4. Update PC Performance
        if self.sys_snapshot:
            r_pct = self.sys_snapshot.ram_percent
            r_used = self.sys_snapshot.ram_used_gb
            r_tot = self.sys_snapshot.ram_total_gb
            self.ram_detail_lbl.configure(text=f"{r_used:.1f} GB / {r_tot:.1f} GB ({r_pct}%)")

            ram_col = support.COLOR_RED if r_pct >= 85 else (support.COLOR_YELLOW if r_pct >= 70 else support.COLOR_GREEN)
            self.ram_bar.delete("all")
            fill_w = max(0, int(self.ram_bar.winfo_width() * (r_pct / 100.0)))
            self.ram_bar.create_rectangle(0, 0, fill_w, 5, fill=ram_col, outline="")

            self.cpu_lbl.configure(text=f"CPU: {self.sys_snapshot.cpu_percent:.1f}%")
            self.net_lbl.configure(text=f"이더넷: ↓ {self.sys_snapshot.rx_speed_str} · ↑ {self.sys_snapshot.tx_speed_str}")

            if self.sys_snapshot.temperature_c is not None:
                self.pc_temp_lbl.configure(text=f"온도: {self.sys_snapshot.temperature_c:.1f}°C")

            # Hover card PC
            self.hover_ram_lbl.configure(text=f"RAM {r_pct}% ({r_used:.1f}/{r_tot:.1f} GB)")
            self._render_custom_bar(self.hover_ram_bar, r_pct, ram_col)
            temp_str = f" · 온도 {self.sys_snapshot.temperature_c:.0f}°C" if self.sys_snapshot.temperature_c is not None else ""
            self.hover_pc_sub_lbl.configure(
                text=f"CPU {self.sys_snapshot.cpu_percent:.0f}%{temp_str} · ↓ {self.sys_snapshot.rx_speed_str} · ↑ {self.sys_snapshot.tx_speed_str}"
            )

        # 5. Update Taskbar Dock Widget (Simplified, distinct brand colors)
        if rem_gpt is not None and self.tb_gpt_canvas:
            support.draw_battery(
                self.tb_gpt_canvas,
                rem_gpt,
                width=20,
                height=11,
                outline_color=self.theme["gpt_color"],
                green_color=self.theme["gpt_color"],
                yellow_color=self.theme["battery_yellow"],
                red_color=self.theme["battery_red"],
            )
            self.tb_gpt_lbl.configure(text=f"GPT {int(rem_gpt)}%", fg=self.theme["gpt_color"])
            if self.sec_dock and self.sec_tb_gpt_canvas:
                support.draw_battery(
                    self.sec_tb_gpt_canvas,
                    rem_gpt,
                    width=20,
                    height=11,
                    outline_color=self.theme["gpt_color"],
                    green_color=self.theme["gpt_color"],
                    yellow_color=self.theme["battery_yellow"],
                    red_color=self.theme["battery_red"],
                )
                self.sec_tb_gpt_lbl.configure(text=f"GPT {int(rem_gpt)}%", fg=self.theme["gpt_color"])

        if rem_gem is not None and self.tb_gem_canvas:
            support.draw_battery(
                self.tb_gem_canvas,
                rem_gem,
                width=20,
                height=11,
                outline_color=self.theme["gem_color"],
                green_color=self.theme["gem_color"],
                yellow_color=self.theme["battery_yellow"],
                red_color=self.theme["battery_red"],
            )
            self.tb_gem_lbl.configure(text=f"GEM {int(rem_gem)}%", fg=self.theme["gem_color"])
            if self.sec_dock and self.sec_tb_gem_canvas:
                support.draw_battery(
                    self.sec_tb_gem_canvas,
                    rem_gem,
                    width=20,
                    height=11,
                    outline_color=self.theme["gem_color"],
                    green_color=self.theme["gem_color"],
                    yellow_color=self.theme["battery_yellow"],
                    red_color=self.theme["battery_red"],
                )
                self.sec_tb_gem_lbl.configure(text=f"GEM {int(rem_gem)}%", fg=self.theme["gem_color"])

        if rem_claude is not None and self.tb_claude_canvas:
            support.draw_battery(
                self.tb_claude_canvas,
                rem_claude,
                width=20,
                height=11,
                outline_color=self.theme["claude_color"],
                green_color=self.theme["claude_color"],
                yellow_color=self.theme["battery_yellow"],
                red_color=self.theme["battery_red"],
            )
            self.tb_claude_lbl.configure(text=f"CLD {int(rem_claude)}%", fg=self.theme["claude_color"])
            if self.sec_dock and self.sec_tb_claude_canvas:
                support.draw_battery(
                    self.sec_tb_claude_canvas,
                    rem_claude,
                    width=20,
                    height=11,
                    outline_color=self.theme["claude_color"],
                    green_color=self.theme["claude_color"],
                    yellow_color=self.theme["battery_yellow"],
                    red_color=self.theme["battery_red"],
                )
                self.sec_tb_claude_lbl.configure(text=f"CLD {int(rem_claude)}%", fg=self.theme["claude_color"])

        if self.sys_snapshot and self.tb_ram_lbl:
            self.tb_ram_lbl.configure(text=f"RAM {self.sys_snapshot.ram_percent}%", fg=self.theme["ram_color"])
            if self.sec_dock and self.sec_tb_ram_lbl:
                self.sec_tb_ram_lbl.configure(text=f"RAM {self.sys_snapshot.ram_percent}%", fg=self.theme["ram_color"])

    def _tick(self):
        # 1. IPC events
        for act in self.instance.pending():
            if act == "quit":
                self.quit_app()
                return
            elif act == "show":
                self.show_card()
            elif act == "toggle":
                self.toggle_card()

        # 2. Maintain Taskbar Dock alignment
        self._dock_to_taskbar()

        # 3. Consume AI response queue
        try:
            codex_res, gemini_res, claude_res, c_err, g_err, cl_err = self.ai_results.get_nowait()
            self.busy = False
            self.refresh_btn.configure(state="normal")
            if codex_res:
                self.codex_snapshot = codex_res
            if gemini_res:
                self.gemini_snapshot = gemini_res
            if claude_res:
                self.claude_snapshot = claude_res

            now_str = datetime.now().strftime("%H:%M:%S")
            errs = [e for e in (c_err, g_err, cl_err if self.show_claude else None) if e]
            if len(errs) >= 2:
                self.status_lbl.configure(text=f"일부 AI 조회 오류 · {now_str}", fg=support.COLOR_YELLOW)
            elif errs:
                self.status_lbl.configure(text=f"연결 주의 · {now_str}", fg=support.COLOR_YELLOW)
            else:
                mins = self.settings.get("refresh_minutes", 5)
                self.status_lbl.configure(text=f"연결 정상 · {mins}분마다 갱신 ({now_str})", fg=support.COLOR_GREEN)
            self._update_ui()
        except queue.Empty:
            pass

        # 4. Sample PC Performance (every ~1.5 sec)
        try:
            self.sys_snapshot = self.monitor.sample()
            self._update_ui()
        except Exception:
            pass

        # 5. Schedule periodic AI refresh
        interval_secs = self.settings.get("refresh_minutes", 5) * 60
        if time.monotonic() >= self.next_ai_refresh and not self.busy:
            self.next_ai_refresh = time.monotonic() + interval_secs
            self.refresh_ai()

        self.root.after(1500, self._tick)

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            win.foreground(self.settings_window)
            return

        w = tk.Toplevel(self.card_window)
        self.settings_window = w
        w.title(t("settings_title", lang=self.lang))
        w.configure(bg=self.theme["bg"])
        w.resizable(False, False)
        w.attributes("-topmost", True)

        frame = tk.Frame(w, bg=self.theme["bg"], padx=20, pady=16)
        frame.pack(fill="both", expand=True)

        self._label(frame, t("settings_title", lang=self.lang), color=self.theme["text"], size=12, bold=True).pack(anchor="w", pady=(0, 12))

        # --- Section 1: General (Language & Theme & Refresh) ---
        gen_frame = tk.LabelFrame(
            frame,
            text=f"  {t('general_settings', lang=self.lang)}  ",
            bg=self.theme["bg"],
            fg=self.theme["text_muted"],
            font=("맑은 고딕", 9, "bold"),
            padx=12,
            pady=8,
        )
        gen_frame.pack(fill="x", pady=(0, 10))

        # Language
        row_lang = tk.Frame(gen_frame, bg=self.theme["bg"])
        row_lang.pack(fill="x", pady=2)
        self._label(row_lang, t("language", lang=self.lang), color=self.theme["text"], size=9).pack(side="left")
        lang_map = {"한국어": "ko", "English": "en"}
        lang_rev = {"ko": "한국어", "en": "English"}
        var_lang_str = tk.StringVar(value=lang_rev.get(self.lang, "한국어"))
        cb_lang = ttk.Combobox(
            row_lang,
            textvariable=var_lang_str,
            values=["한국어", "English"],
            state="readonly",
            width=14,
        )
        cb_lang.pack(side="right")

        # Theme
        row_theme = tk.Frame(gen_frame, bg=self.theme["bg"])
        row_theme.pack(fill="x", pady=4)
        self._label(row_theme, t("theme", lang=self.lang), color=self.theme["text"], size=9).pack(side="left")
        theme_map = {
            "시스템 설정 따름 (System)": "system",
            "다크 모드 (Dark)": "dark",
            "라이트 모드 (Light)": "light",
        }
        theme_rev = {
            "system": "시스템 설정 따름 (System)",
            "dark": "다크 모드 (Dark)",
            "light": "라이트 모드 (Light)",
        }
        var_theme_str = tk.StringVar(value=theme_rev.get(self.theme_mode, "시스템 설정 따름 (System)"))
        cb_theme = ttk.Combobox(
            row_theme,
            textvariable=var_theme_str,
            values=list(theme_map.keys()),
            state="readonly",
            width=22,
        )
        cb_theme.pack(side="right")

        # Refresh Interval
        row_int = tk.Frame(gen_frame, bg=self.theme["bg"])
        row_int.pack(fill="x", pady=2)
        self._label(row_int, t("refresh_interval", lang=self.lang), color=self.theme["text"], size=9).pack(side="left")
        var_interval = tk.StringVar(value=str(self.settings.get("refresh_minutes", 5)))
        cb_interval = ttk.Combobox(
            row_int,
            textvariable=var_interval,
            values=[str(i) for i in support.INTERVALS],
            state="readonly",
            width=10,
        )
        cb_interval.pack(side="right")

        # --- Section 2: Display Items (Dock Customization) ---
        items_frame = tk.LabelFrame(
            frame,
            text=f"  {t('display_items', lang=self.lang)}  ",
            bg=self.theme["bg"],
            fg=self.theme["text_muted"],
            font=("맑은 고딕", 9, "bold"),
            padx=12,
            pady=8,
        )
        items_frame.pack(fill="x", pady=(0, 10))

        var_show_gpt = tk.BooleanVar(value=self.show_gpt)
        var_show_gem = tk.BooleanVar(value=self.show_gem)
        var_show_claude = tk.BooleanVar(value=self.show_claude)
        var_show_ram = tk.BooleanVar(value=self.show_ram)

        def make_chk(parent, text, var, color):
            return tk.Checkbutton(
                parent,
                text=text,
                variable=var,
                bg=self.theme["bg"],
                fg=color,
                selectcolor=self.theme["box_bg"],
                activebackground=self.theme["bg"],
                activeforeground=color,
                font=("맑은 고딕", 9),
            )

        make_chk(items_frame, f"● {t('item_gpt', lang=self.lang)}", var_show_gpt, self.theme["gpt_color"]).pack(anchor="w", pady=1)
        make_chk(items_frame, f"● {t('item_gem', lang=self.lang)}", var_show_gem, self.theme["gem_color"]).pack(anchor="w", pady=1)
        make_chk(items_frame, f"● {t('item_claude', lang=self.lang)}", var_show_claude, self.theme["claude_color"]).pack(anchor="w", pady=1)
        make_chk(items_frame, f"● {t('item_ram', lang=self.lang)}", var_show_ram, self.theme["ram_color"]).pack(anchor="w", pady=1)

        # --- Section 3: On Close & Autostart ---
        misc_frame = tk.LabelFrame(
            frame,
            text=f"  {t('on_close_action', lang=self.lang)}  ",
            bg=self.theme["bg"],
            fg=self.theme["text_muted"],
            font=("맑은 고딕", 9, "bold"),
            padx=12,
            pady=8,
        )
        misc_frame.pack(fill="x", pady=(0, 10))

        var_close = tk.StringVar(value=self.settings.get("on_close_action", "ask"))
        tk.Radiobutton(
            misc_frame,
            text=t("ask_every_time", lang=self.lang),
            variable=var_close,
            value="ask",
            bg=self.theme["bg"],
            fg=self.theme["text"],
            selectcolor=self.theme["box_bg"],
            activebackground=self.theme["bg"],
            activeforeground=self.theme["text"],
            font=("맑은 고딕", 9),
        ).pack(anchor="w", pady=1)
        tk.Radiobutton(
            misc_frame,
            text=t("minimize_to_taskbar", lang=self.lang),
            variable=var_close,
            value="minimize",
            bg=self.theme["bg"],
            fg=self.theme["text"],
            selectcolor=self.theme["box_bg"],
            activebackground=self.theme["bg"],
            activeforeground=self.theme["text"],
            font=("맑은 고딕", 9),
        ).pack(anchor="w", pady=1)
        tk.Radiobutton(
            misc_frame,
            text=t("quit_program", lang=self.lang),
            variable=var_close,
            value="quit",
            bg=self.theme["bg"],
            fg=self.theme["text"],
            selectcolor=self.theme["box_bg"],
            activebackground=self.theme["bg"],
            activeforeground=self.theme["text"],
            font=("맑은 고딕", 9),
        ).pack(anchor="w", pady=1)

        var_autostart = tk.BooleanVar(value=win.autostart_enabled())
        chk_auto = tk.Checkbutton(
            frame,
            text=t("autostart", lang=self.lang),
            variable=var_autostart,
            bg=self.theme["bg"],
            fg=self.theme["text"],
            selectcolor=self.theme["box_bg"],
            activebackground=self.theme["bg"],
            activeforeground=self.theme["text"],
            font=("맑은 고딕", 9),
        )
        chk_auto.pack(anchor="w", pady=(0, 14))

        def save():
            new_lang = lang_map.get(var_lang_str.get(), "ko")
            new_theme = theme_map.get(var_theme_str.get(), "system")
            new_interval = int(var_interval.get())
            new_show_gpt = var_show_gpt.get()
            new_show_gem = var_show_gem.get()
            new_show_claude = var_show_claude.get()
            new_show_ram = var_show_ram.get()

            # Ensure at least one item is checked
            if not (new_show_gpt or new_show_gem or new_show_claude or new_show_ram):
                new_show_gpt = True

            self.settings["language"] = new_lang
            self.settings["theme"] = new_theme
            self.settings["refresh_minutes"] = new_interval
            self.settings["show_gpt"] = new_show_gpt
            self.settings["show_gem"] = new_show_gem
            self.settings["show_claude"] = new_show_claude
            self.settings["show_ram"] = new_show_ram
            self.settings["on_close_action"] = var_close.get()

            support.save_settings(self.settings)
            win.set_autostart(var_autostart.get())

            self.lang = new_lang
            self.theme_mode = new_theme
            self.theme = support.get_dock_theme(self.theme_mode)
            self.show_gpt = new_show_gpt
            self.show_gem = new_show_gem
            self.show_claude = new_show_claude
            self.show_ram = new_show_ram

            # Update Claude card visibility
            if self.show_claude:
                self.claude_batt_canvas.pack(side="left", padx=(0, 4))
                self.claude_batt_lbl.pack(side="left")
                self.claude_card.pack(fill="x", pady=(0, 8))
                self.hover_claude_box.pack(fill="x", pady=(0, 5))
            else:
                self.claude_batt_canvas.pack_forget()
                self.claude_batt_lbl.pack_forget()
                self.claude_card.pack_forget()
                self.hover_claude_box.pack_forget()

            # Live dynamic rebuild of Taskbar dock
            self._rebuild_dock()

            # Re-query AI if claude was just enabled and not yet queried
            if self.show_claude and not self.claude_snapshot:
                self.refresh_ai()

            w.destroy()

        btn_box = tk.Frame(frame, bg=self.theme["bg"])
        btn_box.pack(fill="x")
        self._button(btn_box, t("save", lang=self.lang), save, accent=True).pack(side="left")
        self._button(btn_box, t("cancel", lang=self.lang), w.destroy).pack(side="right")


def main():
    try:
        parser = argparse.ArgumentParser(description="AI & PC Monitor")
        parser.add_argument("--background", action="store_true", help="Start minimized in taskbar")
        parser.add_argument("--toggle", action="store_true", help="Toggle window display")
        parser.add_argument("--show", action="store_true", help="Show and foreground window")
        parser.add_argument("--quit", action="store_true", help="Terminate running instance")
        args = parser.parse_args()

        win.prepare_app()
        instance = win.Instance()
        if not instance.owner:
            if args.quit:
                instance.signal("quit")
            elif args.toggle:
                instance.signal("toggle")
            else:
                instance.signal("show")
            return

        if args.quit:
            return

        root = tk.Tk()
        app = AIUsageWidget(root, instance, background=args.background)
        root.mainloop()
    except Exception as e:
        try:
            import traceback
            err_log = win.BASE / "error.log"
            err_log.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
