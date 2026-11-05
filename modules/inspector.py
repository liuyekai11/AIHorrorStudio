"""镜头属性面板：显示/编辑选中镜头的时长、运镜、过渡、字幕。

所有修改都通过回调交给 main_window 持久化，本模块不改 project.json。
"""
import tkinter as tk

from theme import Palette, FONT_UI, FONT_MONO
from modules.project_manager import (
    MIN_DURATION, MAX_DURATION, format_time,
    MOTION_MODES, MOTION_LABELS, TRANSITION_MODES, TRANSITION_LABELS, ZOOM_TO_MOTION)
from modules.timeline import parse_time_text

_UI = FONT_UI


class ShotInspector(tk.Frame):
    def __init__(self, master, on_change=None, on_duration=None):
        super().__init__(master, bg=Palette.PANEL)
        self.on_change = on_change or (lambda changes: None)
        self.on_duration = on_duration or (lambda value: None)
        self.shot = None
        self.index = -1
        self.total = 0
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        tk.Label(self, text="镜头属性", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(_UI, 9, "bold")).pack(anchor="w", padx=12, pady=(10, 8))

        self.empty_label = tk.Label(self, text="在时间轴上选择一个镜头",
                                    bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                                    font=(_UI, 9), wraplength=230, justify="left")
        self.empty_label.pack(anchor="w", padx=12, pady=4)

        body = tk.Frame(self, bg=Palette.PANEL)
        self.body = body
        body.pack(fill="x", padx=12)

        self.title = tk.Label(body, text="", bg=Palette.PANEL, fg=Palette.BONE,
                              font=(_UI, 11, "bold"), anchor="w")
        self.title.pack(fill="x", pady=(0, 6))

        self.file_label = tk.Label(body, text="", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                                   font=(FONT_MONO, 8), anchor="w", wraplength=230,
                                   justify="left")
        self.file_label.pack(fill="x", pady=(0, 8))

        self._row_time(body)
        self._row_duration(body)
        self._row_combo(body, "运镜", "motion",
                        [(MOTION_LABELS[m], m) for m in MOTION_MODES])
        self._row_combo(body, "过渡", "transition",
                        [(TRANSITION_LABELS[t], t) for t in TRANSITION_MODES])

        self.readonly_note = tk.Label(body, text="", bg=Palette.PANEL,
                                      fg=Palette.TEXT_FAINT, font=(_UI, 8),
                                      wraplength=230, justify="left")
        self.readonly_note.pack(fill="x", pady=(10, 0))

    def _row_time(self, parent):
        row = tk.Frame(parent, bg=Palette.PANEL)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="起止", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(_UI, 9), width=6, anchor="w").pack(side="left")
        self.time_value = tk.Label(row, text="—", bg=Palette.PANEL, fg=Palette.TEXT,
                                   font=(FONT_MONO, 9))
        self.time_value.pack(side="right")

    def _row_duration(self, parent):
        row = tk.Frame(parent, bg=Palette.PANEL)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="时长", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(_UI, 9), width=6, anchor="w").pack(side="left")
        self.duration_var = tk.StringVar(value="")
        self.duration_entry = tk.Entry(row, textvariable=self.duration_var, width=9,
                                       bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                                       insertbackground=Palette.TEXT, relief="flat",
                                       font=(FONT_MONO, 10), justify="right",
                                       highlightthickness=1,
                                       highlightbackground=Palette.BORDER,
                                       highlightcolor=Palette.BLOOD)
        self.duration_entry.pack(side="right")
        tk.Label(row, text="秒", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                 font=(_UI, 8)).pack(side="right", padx=4)
        self.duration_entry.bind("<Return>", self._apply_duration)
        self.duration_entry.bind("<FocusOut>", self._apply_duration)
        self.duration_entry.bind("<Up>", lambda e: self._nudge(0.1) or "break")
        self.duration_entry.bind("<Down>", lambda e: self._nudge(-0.1) or "break")

        buttons = tk.Frame(parent, bg=Palette.PANEL)
        buttons.pack(fill="x", pady=(2, 4))
        for text, delta in [("−0.5s", -0.5), ("−0.1s", -0.1), ("+0.1s", 0.1), ("+0.5s", 0.5)]:
            tk.Button(buttons, text=text, command=lambda d=delta: self._nudge(d),
                      bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                      activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                      relief="flat", bd=0, padx=4, pady=2,
                      font=(FONT_MONO, 8), cursor="hand2").pack(side="left", padx=(0, 3))
        self._nudge_enabled = True

    def _row_combo(self, parent, label, key, options):
        row = tk.Frame(parent, bg=Palette.PANEL)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(_UI, 9), width=6, anchor="w").pack(side="left")
        reverse = {v: k for k, v in options}
        var = tk.StringVar(value=options[0][0])
        combo = tk.OptionMenu(row, var, *[k for k, _ in options],
                              command=lambda choice, k=key, rev=reverse: self._on_combo(k, rev[choice]))
        combo.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat", bd=0,
                     activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                     highlightthickness=0, font=(_UI, 9), width=12)
        combo["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                             activebackground=Palette.BLOOD, activeforeground="#ffffff")
        combo.pack(side="right")
        setattr(self, f"{key}_var", var)
        setattr(self, f"{key}_reverse", reverse)
        setattr(self, f"{key}_options", options)

    # ------------------------------------------------------------------
    def set_shot(self, shot, index, total=0):
        self.shot = shot
        self.index = index
        if shot is None:
            self.empty_label.pack(anchor="w", padx=12, pady=4, before=self.body)
            self.title.config(text="—")
            self.file_label.config(text="")
            self.time_value.config(text="—")
            self.duration_var.set("")
            self.readonly_note.config(text="")
            return
        self.empty_label.pack_forget()
        start = float(shot.get("start", 0))
        dur = float(shot.get("duration", 0))
        self.title.config(text=f"镜头 #{index + 1}")
        self.file_label.config(text=shot.get("image", ""))
        self.time_value.config(text=f"{format_time(start)} → {format_time(start + dur)}")
        self.duration_var.set(f"{dur:.2f}")
        for key in ("motion", "transition"):
            options = getattr(self, f"{key}_options")
            reverse = getattr(self, f"{key}_reverse")
            value = shot.get(key)
            if key == "motion" and value not in MOTION_MODES:
                # 老项目只有 zoom 字段，映射成新的运镜名
                value = ZOOM_TO_MOTION.get(shot.get("zoom"), "static")
            if value not in reverse:
                value = options[0][1]
            var = getattr(self, f"{key}_var")
            var.set(reverse.get(value, options[0][0]))

    # ------------------------------------------------------------------
    def _read_duration(self):
        raw = self.duration_var.get().strip()
        try:
            value = parse_time_text(raw)
        except Exception:
            self.duration_var.set(f"{float(self.shot.get('duration', 0)):.2f}")
            return None
        return min(MAX_DURATION, max(MIN_DURATION, value))

    def _apply_duration(self, event=None):
        if not self.shot:
            return
        value = self._read_duration()
        if value is None:
            return
        if abs(value - float(self.shot.get("duration", 0))) < 1e-6:
            return
        self.on_duration(value)

    def _nudge(self, delta):
        if not self.shot:
            return
        current = float(self.shot.get("duration", 0))
        new_value = min(MAX_DURATION, max(MIN_DURATION, round(current + delta, 3)))
        self.duration_var.set(f"{new_value:.2f}")
        self.on_duration(new_value)

    def _on_combo(self, key, value):
        if not self.shot:
            return
        if self.shot.get(key) == value:
            return
        self.on_change({key: value})
