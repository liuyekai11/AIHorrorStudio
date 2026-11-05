"""主窗口：布局、状态、事件编排。

结构：
  Header   —— 品牌、当前项目、新建/打开/保存
  Body
    ├─ 左栏 Navigator  导入素材、输出设置、渲染
    ├─ 中栏 Stage      预览 + 时间轴
    └─ 右栏 Inspector  镜头属性
  Footer   —— 状态栏 + 进度条
"""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from theme import Palette, Theme, FONT_UI, FONT_MONO
from modules import project_manager as pm_mod
from modules.project_manager import (
    ProjectManager, ProjectError, DEFAULT_SETTINGS, DEFAULT_DURATION,
    format_time, read_srt_cues,
    GRADE_LABELS, PACING_LABELS, MOTION_LABELS, TRANSITION_LABELS,
)
from modules.render_engine import RenderEngine, RenderError
from modules.ffmpeg_locator import find_ffmpeg
from modules.preview import PreviewPanel
from modules.timeline import TimelineView
from modules.inspector import ShotInspector
from modules.story_panel import StoryPanel
from modules import story_engine
from modules.story_engine import StoryEngine, StoryError, to_project_shots
from modules.ai_studio import AIStudioPanel
from modules.batch import BatchRunner
from modules.batch_panel import BatchPanel
from modules.image_engine import ImageEngine, build_consistency_hint, pick_size
from modules.voice_engine import VoiceEngine
from modules import ai_config, sf_config
from modules import media_tools
from modules.ai_settings import AISettingsDialog

APP_NAME = "AI Horror Studio"
APP_VERSION = "2.1"
WINDOW_TITLE = f"{APP_NAME}  ·  V{APP_VERSION}"
GEOMETRY = "1440x900"
MIN_SIZE = (1200, 760)
APP_CONFIG = Path.home() / ".ai_horror_studio.json"

RESOLUTIONS = ["1080x1920", "720x1280", "1080x1080", "1920x1080"]
FPS_OPTIONS = ["24", "25", "30"]


class HorrorStudioApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry(GEOMETRY)
        self.root.minsize(*MIN_SIZE)
        self.root.configure(bg=Palette.BG)
        self.theme = Theme(root)

        self.pm = ProjectManager()
        self.project: Path | None = None
        self.data: dict = {}
        self.selected: list[str] = []
        self.main_photo = None

        self.msg_queue: queue.Queue = queue.Queue()
        self.rendering = False
        self.generating = False
        self.ai_busy = False
        self.play_frames: list[str] = []
        self.playing = False
        self._play_after = None
        self._play_start_ms = 0
        self._play_start_t = 0.0
        self._dirty = False
        self._suppress_settings = False

        self._build_header()
        self._build_body()
        self._build_footer()
        self._bind_global_keys()
        self._load_last_project()
        self._poll_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    # ==================================================================
    # 布局
    # ==================================================================
    def _build_header(self):
        bar = tk.Frame(self.root, bg=Palette.BG_ALT, height=64)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        left = tk.Frame(bar, bg=Palette.BG_ALT)
        left.pack(side="left", padx=18, pady=10)
        tk.Label(left, text="AI HORROR STUDIO", bg=Palette.BG_ALT, fg=Palette.TEXT,
                 font=(FONT_UI, 15, "bold")).pack(side="left")
        tk.Label(left, text=f"V{APP_VERSION}", bg=Palette.BG_ALT, fg=Palette.BLOOD,
                 font=(FONT_MONO, 9, "bold")).pack(side="left", padx=(8, 0), pady=(4, 0))
        tk.Label(left, text="故事 + 时间轴 + AI 制作", bg=Palette.BG_ALT, fg=Palette.TEXT_FAINT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(8, 0), pady=(5, 0))

        right = tk.Frame(bar, bg=Palette.BG_ALT)
        right.pack(side="right", padx=14, pady=10)
        self._hbutton(right, "打开项目", self.open_project)
        self._hbutton(right, "新建项目", self.new_project, accent=True)
        self._hbutton(right, "AI 设置", self.open_ai_settings)

        mid = tk.Frame(bar, bg=Palette.BG_ALT)
        mid.pack(side="left", padx=30, pady=14)
        self.project_label = tk.Label(mid, text="未打开项目", bg=Palette.BG_ALT,
                                      fg=Palette.TEXT_DIM, font=(FONT_UI, 10),
                                      anchor="w")
        self.project_label.pack(side="left")
        self.dirty_label = tk.Label(mid, text="", bg=Palette.BG_ALT, fg=Palette.AMBER,
                                    font=(FONT_UI, 9))
        self.dirty_label.pack(side="left", padx=8)

        tk.Frame(self.root, bg=Palette.BORDER, height=1).pack(fill="x")

    def _hbutton(self, parent, text, cmd, accent=False):
        bg = Palette.BLOOD if accent else Palette.PANEL_ALT
        fg = "#ffffff" if accent else Palette.TEXT
        hover = Palette.BLOOD_HOVER if accent else Palette.PANEL_HOVER
        btn = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                        activebackground=hover, activeforeground=fg, relief="flat",
                        bd=0, padx=16, pady=7, font=(FONT_UI, 9, "bold" if accent else "normal"),
                        cursor="hand2")
        btn.pack(side="right", padx=5)
        btn.bind("<Enter>", lambda e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def _build_body(self):
        body = tk.Frame(self.root, bg=Palette.BG, height=48)
        body.pack(fill="x")
        body.pack_propagate(False)
        self.tabs = tk.Frame(body, bg=Palette.BG)
        self.tabs.pack(fill="x", padx=14, pady=(8, 0))
        self._tab_buttons = {}
        for key, text in (("editor", "编辑"), ("story", "故事（AI）"), ("ai", "AI 制作"),
                          ("batch", "批量（AI）")):
            btn = tk.Button(self.tabs, text=text, command=lambda k=key: self.show_tab(k),
                            bg=Palette.BG, fg=Palette.TEXT_DIM, relief="flat", bd=0,
                            padx=18, pady=6, font=(FONT_UI, 10), cursor="hand2",
                            activebackground=Palette.PANEL, activeforeground=Palette.BONE)
            btn.pack(side="left", padx=(0, 4))
            self._tab_buttons[key] = btn

        self.pages = {}
        self.workspace = tk.Frame(self.root, bg=Palette.BG)
        self.workspace.pack(fill="both", expand=True)

        editor_page = tk.Frame(self.workspace, bg=Palette.BG)
        self.pages["editor"] = editor_page
        self._build_editor_page(editor_page)

        story_page = tk.Frame(self.workspace, bg=Palette.PANEL)
        self.pages["story"] = story_page
        self.story_panel = StoryPanel(
            story_page,
            generate=self._generate_story_sync,
            on_import=self.import_story,
            on_save=self.save_story,
            on_export_srt=self.export_story_srt,
            on_open_settings=self.open_ai_settings,
            on_status=self._set_status,
            on_reveal_shot=self.reveal_story_shot,
            on_concepts=self._generate_story_concepts,
            on_plan=self._generate_story_plan)
        self.story_panel.pack(fill="both", expand=True)
        self.story_panel.set_restore_callback(self.restore_story_version)
        self.story_panel.set_versions(self._story_versions())

        ai_page = tk.Frame(self.workspace, bg=Palette.BG)
        self.pages["ai"] = ai_page
        self.ai_panel = AIStudioPanel(
            ai_page,
            on_images=self.generate_all_images,
            on_voices=self.generate_all_voices,
            on_build_voice_track=self.build_voice_track,
            on_render=self.render_ai,
            on_clear_voices=self.clear_voices,
            on_rebalance=self.rebalance_pacing,
            on_open_settings=self.open_ai_settings,
            on_open_output=self.open_output,
            on_status=self._set_status)
        self.ai_panel.pack(fill="both", expand=True)

        batch_page = tk.Frame(self.workspace, bg=Palette.BG)
        self.pages["batch"] = batch_page
        self.batch_panel = BatchPanel(
            batch_page,
            on_start=self.start_batch,
            on_pick_workspace=self.pick_batch_workspace,
            on_open=self._open_path,
            on_status=self._set_status)
        self.batch_panel.pack(fill="both", expand=True)

        self.current_tab = "editor"
        self.show_tab("editor")
        self.root.bind("<Control-1>", lambda e: self.show_tab("editor"))
        self.root.bind("<Control-2>", lambda e: self.show_tab("story"))
        self.root.bind("<Control-3>", lambda e: self.show_tab("ai"))
        self.root.bind("<Control-4>", lambda e: self.show_tab("batch"))

    def show_tab(self, key: str):
        if key not in self.pages:
            return
        if self.playing:
            self.stop_play()
        for name, page in self.pages.items():
            page.pack_forget()
            btn = self._tab_buttons[name]
            btn.config(bg=Palette.PANEL if name == key else Palette.BG,
                       fg=Palette.BONE if name == key else Palette.TEXT_DIM,
                       font=(FONT_UI, 10, "bold" if name == key else "normal"))
        self.pages[key].pack(fill="both", expand=True)
        self.current_tab = key
        if key == "story":
            self.story_panel.refresh_key_label()
        elif key == "ai":
            self.ai_panel.refresh_key_label()
            self.ai_panel.sync_voice_settings()
            self.ai_panel.set_shots(self.data.get("shots", []), self.project)
            self.ai_panel.set_status("")
    def _build_editor_page(self, body):
        # 左栏
        self.left = tk.Frame(body, bg=Palette.PANEL, width=252)
        self.left.pack(side="left", fill="y")
        self.left.pack_propagate(False)
        self._build_navigator(self.left)

        tk.Frame(body, bg=Palette.BORDER, width=1).pack(side="left", fill="y")

        # 右栏
        self.right = tk.Frame(body, bg=Palette.PANEL, width=268)
        self.right.pack(side="right", fill="y")
        self.right.pack_propagate(False)
        self._build_inspector_panel(self.right)

        tk.Frame(body, bg=Palette.BORDER, width=1).pack(side="right", fill="y")

        # 中栏
        self.center = tk.Frame(body, bg=Palette.BG)
        self.center.pack(side="left", fill="both", expand=True)
        self._build_stage(self.center)

    # ------------------------------------------------------------------
    def _build_navigator(self, parent):
        tk.Label(parent, text="素材导入", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        for text, cmd in [
            ("＋  导入漫画图片", self.add_images),
            ("＋  导入旁白音频", self.add_narration),
            ("＋  导入背景音乐", self.add_music),
            ("＋  导入 SRT 字幕", self.add_subtitle),
        ]:
            self._side_button(parent, text, cmd)

        self.media_label = tk.Label(parent, text="", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                                    font=(FONT_UI, 8), anchor="w", justify="left",
                                    wraplength=220)
        self.media_label.pack(fill="x", padx=16, pady=(6, 0))

        tk.Frame(parent, bg=Palette.BORDER, height=1).pack(fill="x", padx=14, pady=12)

        tk.Label(parent, text="输出设置", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=16, pady=(0, 6))
        self.res_var = tk.StringVar(value="1080x1920")
        self.fps_var = tk.StringVar(value="30")
        self.fit_var = tk.StringVar(value="contain")
        self.default_dur_var = tk.StringVar(value=f"{DEFAULT_DURATION:.1f}")
        self._side_combo(parent, "输出分辨率", self.res_var, RESOLUTIONS, self._on_resolution)
        self._side_combo(parent, "帧率", self.fps_var, FPS_OPTIONS, self._on_fps)
        self._side_combo(parent, "图片适配", self.fit_var, ["contain", "cover"], self._on_fit)
        self._side_entry(parent, "新导入图片默认时长", self.default_dur_var, "秒")

        # V2.1 成片质感 / 节奏
        self.grade_var = tk.StringVar(value=GRADE_LABELS["cold"])
        self.pacing_var = tk.StringVar(value=PACING_LABELS["picture"])
        self.vignette_var = tk.BooleanVar(value=True)
        self.grain_var = tk.BooleanVar(value=True)
        self._grade_reverse = {v: k for k, v in GRADE_LABELS.items()}
        self._pacing_reverse = {v: k for k, v in PACING_LABELS.items()}
        self._side_combo(parent, "胶片风格", self.grade_var,
                         list(GRADE_LABELS.values()), self._on_grade)
        self._side_combo(parent, "节奏模式", self.pacing_var,
                         list(PACING_LABELS.values()), self._on_pacing)
        self._side_check(parent, "暗角", self.vignette_var, self._on_vignette)
        self._side_check(parent, "胶片颗粒", self.grain_var, self._on_grain)

        tk.Frame(parent, bg=Palette.BG).pack(fill="both", expand=True)

        self.render_btn = tk.Button(parent, text="▶  开始成片渲染", command=self.render,
                                    bg=Palette.BLOOD, fg="#ffffff",
                                    activebackground=Palette.BLOOD_HOVER,
                                    activeforeground="#ffffff", relief="flat", bd=0,
                                    pady=10, font=(FONT_UI, 10, "bold"), cursor="hand2")
        self.render_btn.pack(fill="x", padx=14, pady=(8, 4))
        self._side_button(parent, "打开输出目录", self.open_output, subtle=True)
        self.ffmpeg_label = tk.Label(parent, text="", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                                     font=(FONT_UI, 8), anchor="w")
        self.ffmpeg_label.pack(fill="x", padx=16, pady=(4, 12))

    def _side_button(self, parent, text, cmd, subtle=False):
        bg = Palette.PANEL if subtle else Palette.PANEL_ALT
        btn = tk.Button(parent, text=text, command=cmd, bg=bg, fg=Palette.TEXT,
                        activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                        relief="flat", bd=0, anchor="w", padx=12, pady=7,
                        font=(FONT_UI, 9), cursor="hand2")
        btn.pack(fill="x", padx=8, pady=2)
        btn.bind("<Enter>", lambda e: btn.config(bg=Palette.PANEL_HOVER))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def _side_combo(self, parent, label, var, values, callback):
        row = tk.Frame(parent, bg=Palette.PANEL)
        row.pack(fill="x", padx=16, pady=3)
        tk.Label(row, text=label, bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        menu = tk.OptionMenu(row, var, *values,
                             command=lambda v: callback(v))
        menu.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat", bd=0,
                    activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                    highlightthickness=0, font=(FONT_MONO, 9), width=10)
        menu["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                            activebackground=Palette.BLOOD, activeforeground="#ffffff")
        menu.pack(side="right")

    def _side_check(self, parent, label, var, callback):
        tk.Checkbutton(parent, text=label, variable=var, command=callback,
                       bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                       activebackground=Palette.PANEL, activeforeground=Palette.TEXT,
                       selectcolor=Palette.PANEL_ALT, relief="flat", bd=0,
                       highlightthickness=0, font=(FONT_UI, 9), anchor="w"
                       ).pack(fill="x", padx=16, pady=1)

    def _side_entry(self, parent, label, var, suffix):
        row = tk.Frame(parent, bg=Palette.PANEL)
        row.pack(fill="x", padx=16, pady=3)
        tk.Label(row, text=label, bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        tk.Label(row, text=suffix, bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                 font=(FONT_UI, 8)).pack(side="right", padx=(2, 0))
        entry = tk.Entry(row, textvariable=var, width=6, bg=Palette.PANEL_ALT,
                         fg=Palette.TEXT, insertbackground=Palette.TEXT, relief="flat",
                         justify="right", font=(FONT_MONO, 9),
                         highlightthickness=1, highlightbackground=Palette.BORDER,
                         highlightcolor=Palette.BLOOD)
        entry.pack(side="right")

    # ------------------------------------------------------------------
    def _build_stage(self, parent):
        top = tk.Frame(parent, bg=Palette.BG)
        top.pack(fill="both", expand=True, padx=(14, 14), pady=(14, 0))

        preview_wrap = tk.Frame(top, bg=Palette.PANEL, width=330)
        preview_wrap.pack(side="left", fill="y", padx=(0, 12))
        preview_wrap.pack_propagate(False)
        self.preview = PreviewPanel(preview_wrap,
                                    on_play_toggle=self.toggle_play,
                                    on_prev_shot=lambda: self.step_shot(-1),
                                    on_next_shot=lambda: self.step_shot(1))
        self.preview.pack(fill="both", expand=True)

        table_wrap = tk.Frame(top, bg=Palette.PANEL)
        table_wrap.pack(side="left", fill="both", expand=True)
        head = tk.Frame(table_wrap, bg=Palette.PANEL)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text="分镜列表", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold")).pack(side="left")
        self.count_label = tk.Label(head, text="0 个镜头", bg=Palette.PANEL,
                                    fg=Palette.TEXT_FAINT, font=(FONT_MONO, 9))
        self.count_label.pack(side="right")
        self.total_label = tk.Label(head, text="", bg=Palette.PANEL, fg=Palette.BLOOD,
                                    font=(FONT_MONO, 9))
        self.total_label.pack(side="right", padx=12)

        tk.Frame(table_wrap, bg=Palette.BORDER, height=1).pack(fill="x", padx=12)
        cols = ("index", "file", "start", "duration", "zoom", "transition")
        self.tree = ttk.Treeview(table_wrap, columns=cols, show="headings",
                                    selectmode="extended")
        headings = {"index": ("#", 44), "file": ("文件", 240), "start": ("起点", 84),
                    "duration": ("时长", 70), "zoom": ("运镜", 62),
                    "transition": ("过渡", 62)}
        for col, (text, width) in headings.items():
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="center" if col != "file" else "w",
                             stretch=(col == "file"))
        scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 6), pady=(4, 0))
        self.tree.pack(fill="both", expand=True, padx=(12, 0), pady=(4, 0))
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Double-Button-1>", lambda e: self.seek_to_selected())

        tools = tk.Frame(table_wrap, bg=Palette.PANEL)
        tools.pack(fill="x", padx=12, pady=8)
        for text, cmd in [("◀ 上移", lambda: self.move_selected(-1)),
                          ("下移 ▶", lambda: self.move_selected(1)),
                          ("复制", self.duplicate_selected),
                          ("拆分", self.split_selected),
                          ("批量配图", self.attach_images),
                          ("删除", self.delete_selected)]:
            tk.Button(tools, text=text, command=cmd, bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                      activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                      relief="flat", bd=0, padx=10, pady=4, font=(FONT_UI, 9),
                      cursor="hand2").pack(side="left", padx=(0, 5))
        tk.Button(tools, text="跳到选中", command=self.seek_to_selected,
                  bg=Palette.PANEL_ALT, fg=Palette.TEXT_DIM,
                  activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                  relief="flat", bd=0, padx=10, pady=4, font=(FONT_UI, 9),
                  cursor="hand2").pack(side="right")

        # 时间轴
        bottom = tk.Frame(parent, bg=Palette.PANEL)
        bottom.pack(fill="x", padx=14, pady=12)
        self.timeline = TimelineView(bottom, (FONT_UI, 10), (FONT_MONO, 9),
                                     on_select=self._on_timeline_select,
                                     on_duration_change=self._on_timeline_duration,
                                     on_seek=self._on_timeline_seek,
                                     on_reorder=self._on_timeline_reorder)
        self.timeline.pack(fill="both", expand=True, pady=(0, 6))
        tk.Label(bottom, text="拖动镜头边缘调时长 · 拖动镜头中间调顺序 / 平移视图 · "
                              "Ctrl+滚轮缩放时间轴 · 空格播放 · 双击时间轴跳转",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8)).pack(anchor="w", padx=10)

    def _build_inspector_panel(self, parent):
        self.inspector = ShotInspector(parent, on_change=self.apply_shot_changes,
                                       on_duration=self.apply_shot_duration)
        self.inspector.pack(fill="x")
        tk.Frame(parent, bg=Palette.BORDER, height=1).pack(fill="x", padx=14, pady=12)
        tk.Label(parent, text="提示", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=16)
        tk.Label(parent,
                 text="· 时长框支持 3.5 或 00:03.50\n"
                      "· 上下方向键微调 0.1 秒\n"
                      "· 运镜在成片中生效\n"
                      "· 预览为近似效果",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 9),
                 justify="left", anchor="w", wraplength=232).pack(
            fill="x", padx=16, pady=6)

    def _build_footer(self):
        tk.Frame(self.root, bg=Palette.BORDER, height=1).pack(fill="x")
        footer = tk.Frame(self.root, bg=Palette.BG_ALT)
        footer.pack(fill="x")
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(footer, textvariable=self.status_var, bg=Palette.BG_ALT,
                 fg=Palette.TEXT_DIM, font=(FONT_UI, 9), anchor="w").pack(
            side="left", fill="x", expand=True, padx=16, pady=8)
        self.progress = ttk.Progressbar(footer, mode="determinate", length=140)
        self.progress.pack(side="right", padx=(8, 16), pady=8)
        self.version_label = tk.Label(footer, text=f"V{APP_VERSION}", bg=Palette.BG_ALT,
                                      fg=Palette.TEXT_FAINT, font=(FONT_MONO, 8))
        self.version_label.pack(side="right", padx=4)

    # ==================================================================
    # 快捷键
    # ==================================================================
    def _bind_global_keys(self):
        r = self.root
        r.bind("<space>", lambda e: self._space_action())
        r.bind("<Delete>", lambda e: self.delete_selected())
        r.bind("<BackSpace>", lambda e: self.delete_selected())
        r.bind("<Control-s>", lambda e: self.save())
        r.bind("<Control-a>", lambda e: self.select_all())
        r.bind("<Control-o>", lambda e: self.open_project())
        r.bind("<Control-n>", lambda e: self.new_project())
        r.bind("<Left>", lambda e: self.nudge_playhead(-0.1))
        r.bind("<Right>", lambda e: self.nudge_playhead(0.1))
        r.bind("<Shift-Left>", lambda e: self.step_shot(-1))
        r.bind("<Shift-Right>", lambda e: self.step_shot(1))
        r.bind("<Home>", lambda e: self.seek(0.0))

    def _space_action(self):
        focus = self.root.focus_get()
        if isinstance(focus, tk.Entry):
            return
        self.toggle_play()

    # ==================================================================
    # 项目
    # ==================================================================
    def _load_last_project(self):
        ffmpeg = find_ffmpeg()
        self.ffmpeg_label.config(
            text="FFmpeg 已就绪" if ffmpeg else "⚠ 未找到 FFmpeg，无法渲染")
        self.ffmpeg_label.config(fg=Palette.TEXT_FAINT if ffmpeg else Palette.ERROR)
        try:
            cfg = json.loads(APP_CONFIG.read_text(encoding="utf-8"))
            last = cfg.get("last_project")
            if last and (Path(last) / "project.json").exists():
                self._open(Path(last))
        except Exception:
            pass

    def _remember_project(self):
        try:
            APP_CONFIG.write_text(json.dumps({"last_project": str(self.project)},
                                             ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def new_project(self):
        if not self._confirm_discard():
            return
        parent = filedialog.askdirectory(title="选择项目保存位置")
        if not parent:
            return
        name = simpledialog.askstring("新建项目", "请输入项目名称：",
                                      initialvalue="午夜纸人", parent=self.root)
        if not name:
            return
        try:
            project = self.pm.create_project(Path(parent), name)
        except Exception as exc:
            messagebox.showerror("创建失败", str(exc), parent=self.root)
            return
        self._open(project)
        self.status_var.set(f"项目已创建：{project}")

    def open_project(self):
        if not self._confirm_discard():
            return
        folder = filedialog.askdirectory(title="选择包含 project.json 的项目文件夹")
        if not folder:
            return
        self._open(Path(folder))

    def _open(self, folder: Path):
        try:
            self.project = self.pm.open_project(Path(folder))
            self.data = self.pm.migrate(self.pm.load(self.project))[0]
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc), parent=self.root)
            return
        self.selected = []
        self.preview.set_project(self.project, self.data["shots"],
                                 self.data["settings"],
                                 self._load_cues())
        self.timeline.set_project_dir(self.project)
        self._sync_settings_widgets()
        self.story_panel.set_story(self.pm.get_story(self.data))
        self._full_refresh()
        self.seek(0.0)
        self._remember_project()
        self.root.title(f"{WINDOW_TITLE}  —  {self.data.get('name', '')}")
        self.status_var.set(f"已打开：{self.project}")

    def save(self):
        if not self.project:
            return
        self.pm.save(self.project, self.data)
        self._set_dirty(False)
        self.status_var.set("已保存")

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        self.dirty_label.config(text="● 未保存" if dirty else "")

    def _persist(self, reload=False):
        """保存并刷新界面；reload=True 时从磁盘重新读取（管理类操作后）。"""
        if not self.project:
            return
        if reload:
            self.data = self.pm.migrate(self.pm.load(self.project))[0]
        else:
            self.pm.reflow(self.data)
            self.pm.save(self.project, self.data)
        self._full_refresh()

    # ==================================================================
    # 刷新
    # ==================================================================
    def _full_refresh(self):
        shots = self.data.get("shots", [])
        settings = self.data.get("settings", DEFAULT_SETTINGS)
        self.project_label.config(
            text=f"{self.data.get('name', '未命名')}  ·  {self.project}" if self.project else "未打开项目")
        self.count_label.config(text=f"{len(shots)} 个镜头")
        total = round(sum(float(s.get("duration", 0)) for s in shots), 3)
        self.total_label.config(text=f"总时长 {format_time(total)}")

        self.tree.delete(*self.tree.get_children())
        for i, shot in enumerate(shots):
            image = shot.get("image")
            if image:
                file_text = Path(image).name
            elif shot.get("scene"):
                file_text = f"待配图 · {(shot.get('scene') or '')[:16]}"
            else:
                file_text = "待配图"
            self.tree.insert("", "end", iid=shot["id"], values=(
                i + 1, file_text,
                format_time(float(shot.get("start", 0))),
                f"{float(shot.get('duration', 0)):.2f}s",
                MOTION_LABELS.get(shot.get("motion"), "静止"),
                TRANSITION_LABELS.get(shot.get("transition"), "硬切"),
            ))
        # 镜头列表可能被整体替换（故事导入），先清掉失效的选中项
        valid = {s["id"] for s in shots}
        self.selected = [sid for sid in self.selected if sid in valid]
        self.tree.selection_set(self.selected)
        self.timeline.set_shots(shots)
        self.timeline.set_selection(self.selected)
        self.timeline.set_active(self.timeline.playhead)
        self.preview.set_project(self.project, shots, settings)

        narration = Path(self.data["narration"]).name if self.data.get("narration") else "—"
        music = Path(self.data["music"]).name if self.data.get("music") else "—"
        subtitle = Path(self.data["subtitle"]).name if self.data.get("subtitle") else "—"
        self.media_label.config(text=f"旁白：{narration}\n音乐：{music}\n字幕：{subtitle}")
        if self.current_tab == "ai":
            self.ai_panel.set_shots(shots, self.project)
        self._update_inspector()

    def _sync_settings_widgets(self):
        settings = self.data.get("settings", DEFAULT_SETTINGS)
        self._suppress_settings = True
        try:
            self.res_var.set(f"{settings['width']}x{settings['height']}")
            self.fps_var.set(str(settings["fps"]))
            self.fit_var.set(settings.get("fit", "contain"))
            self.grade_var.set(GRADE_LABELS.get(settings.get("grade", "cold"),
                                                GRADE_LABELS["cold"]))
            self.pacing_var.set(PACING_LABELS.get(settings.get("pacing", "picture"),
                                                  PACING_LABELS["picture"]))
            self.vignette_var.set(bool(settings.get("vignette", True)))
            self.grain_var.set(int(settings.get("grain", 3) or 0) > 0)
        finally:
            self._suppress_settings = False

    def _load_cues(self):
        if self.data.get("subtitle"):
            return read_srt_cues(self.project / self.data["subtitle"])
        return []

    def _update_inspector(self):
        shot = None
        if len(self.selected) == 1:
            shot = next((s for s in self.data.get("shots", [])
                         if s["id"] == self.selected[0]), None)
        index = self.data["shots"].index(shot) if shot in self.data.get("shots", []) else -1
        self.inspector.set_shot(shot, index)

    # ==================================================================
    # 选择 / 播放头
    # ==================================================================
    def _set_selection(self, shot_ids, sync_tree=True, sync_timeline=True):
        self.selected = [sid for sid in shot_ids if sid]
        if sync_tree:
            self.tree.selection_set(self.selected)
            if self.selected:
                self.tree.see(self.selected[0])
        if sync_timeline:
            self.timeline.set_selection(self.selected)
        self._update_inspector()

    def _on_tree_select(self, _event=None):
        ids = list(self.tree.selection())
        if ids != self.selected:
            self._set_selection(ids, sync_tree=False)

    def _on_timeline_select(self, ids):
        self._set_selection(ids)

    def seek(self, t: float):
        total = self.pm.total_duration(self.data) if self.data else 0.0
        t = max(0.0, min(float(t), total))
        self.timeline.set_playhead(t)
        self.timeline.set_active(t)
        self.preview.refresh(force=True, time=t)

    def _on_timeline_seek(self, t):
        if self.playing:
            self.stop_play()
        self.seek(t)

    def nudge_playhead(self, delta):
        self.seek(self.timeline.playhead + delta)

    def step_shot(self, delta):
        shots = self.data.get("shots", [])
        if not shots:
            return
        current = 0
        for i, s in enumerate(shots):
            if float(s["start"]) <= self.timeline.playhead < float(s["start"]) + float(s["duration"]):
                current = i
                break
        target = max(0, min(len(shots) - 1, current + delta))
        self.seek(float(shots[target]["start"]))
        self._set_selection([shots[target]["id"]])

    def seek_to_selected(self):
        if len(self.selected) != 1:
            return
        shot = next((s for s in self.data.get("shots", []) if s["id"] == self.selected[0]), None)
        if shot:
            self.seek(float(shot["start"]))

    def select_all(self):
        ids = [s["id"] for s in self.data.get("shots", [])]
        self._set_selection(ids)

    # ==================================================================
    # 播放
    # ==================================================================
    def toggle_play(self):
        if self.playing:
            self.stop_play()
        else:
            self.start_play()

    def start_play(self, fps=12):
        total = self.pm.total_duration(self.data)
        if total <= 0:
            return
        if self.timeline.playhead >= total - 0.01:
            self.seek(0.0)
        self.playing = True
        self.preview.set_playing(True)
        self._play_start_ms = self.root.tk.call("clock", "milliseconds")
        self._play_start_t = self.timeline.playhead
        self._play_fps = fps
        self._tick_play()

    def _tick_play(self):
        if not self.playing:
            return
        now = self.root.tk.call("clock", "milliseconds")
        t = self._play_start_t + (now - self._play_start_ms) / 1000.0
        total = self.pm.total_duration(self.data)
        if t >= total:
            self.seek(total)
            self.stop_play()
            return
        self.timeline.set_playhead(t, redraw=True)
        self.preview.refresh(time=t)
        self._play_after = self.root.after(int(1000 / self._play_fps), self._tick_play)

    def stop_play(self):
        self.playing = False
        self.preview.set_playing(False)
        if self._play_after:
            self.root.after_cancel(self._play_after)
            self._play_after = None

    # ==================================================================
    # 素材导入
    # ==================================================================
    def _require_project(self):
        if not self.project:
            messagebox.showinfo("提示", "请先新建或打开一个项目。", parent=self.root)
            return False
        return True

    def add_images(self):
        if not self._require_project():
            return
        paths = filedialog.askopenfilenames(
            title="选择漫画图片（可多选）", parent=self.root,
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"), ("所有文件", "*.*")])
        if not paths:
            return
        try:
            duration = float(self.default_dur_var.get())
        except ValueError:
            duration = DEFAULT_DURATION
        try:
            empty = [i for i, s in enumerate(self.data.get("shots", []))
                     if not s.get("image")]
            if empty:
                # 存在待配图镜头时，优先按顺序补齐，而不是追加成新镜头
                count = self.pm.attach_images(self.project, empty[0],
                                              [Path(p) for p in paths], only_empty=True)
                added = []
            else:
                count = 0
                added = self.pm.add_images(self.project, [Path(p) for p in paths], duration)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self.root)
            return
        self._persist(reload=True)
        self.timeline.clear_thumbnail_cache()
        if added:
            self._set_selection([added[0]["id"]])
            self.timeline.fit()
            self.status_var.set(f"已导入 {len(added)} 张图片")
        elif count:
            self.status_var.set(f"已按顺序为 {count} 个待配图镜头补上画面")
        else:
            self.status_var.set("没有可配图的镜头")

    def attach_images(self):
        """「批量配图」：从选中镜头开始，按顺序贴到待配图的镜头上。"""
        if not self._require_project():
            return
        if len(self.selected) != 1:
            messagebox.showinfo("提示", "请先在时间轴上选择一个起始镜头。",
                                parent=self.root)
            return
        paths = filedialog.askopenfilenames(
            title="选择图片（从选中镜头起，依次贴到待配图镜头）", parent=self.root,
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"), ("所有文件", "*.*")])
        if not paths:
            return
        index = next((i for i, s in enumerate(self.data.get("shots", []))
                      if s.get("id") == self.selected[0]), -1)
        if index < 0:
            return
        try:
            count = self.pm.attach_images(self.project, index,
                                          [Path(p) for p in paths], only_empty=True)
        except Exception as exc:
            messagebox.showerror("配图失败", str(exc), parent=self.root)
            return
        self._persist(reload=True)
        self.timeline.clear_thumbnail_cache()
        self.status_var.set(f"已为 {count} 个镜头配图" if count else "选中镜头均已有画面")

    def _add_media(self, kind, title, filetypes):
        if not self._require_project():
            return
        path = filedialog.askopenfilename(title=title, filetypes=filetypes, parent=self.root)
        if not path:
            return
        try:
            self.pm.set_media(self.project, kind, Path(path))
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self.root)
            return
        self._persist(reload=True)
        self.preview.cues = self._load_cues()
        self.preview.refresh(force=True)
        self.status_var.set(f"{title}完成")

    def add_narration(self):
        self._add_media("narration", "选择旁白音频",
                        [("音频", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg"), ("所有文件", "*.*")])

    def add_music(self):
        self._add_media("music", "选择背景音乐",
                        [("音频", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg"), ("所有文件", "*.*")])

    def add_subtitle(self):
        self._add_media("subtitle", "选择 SRT 字幕", [("SRT 字幕", "*.srt")])

    # ==================================================================
    # 设置
    # ==================================================================
    def _apply_settings(self, **changes):
        if self._suppress_settings or not self.project:
            return
        settings = dict(self.data.get("settings", DEFAULT_SETTINGS))
        settings.update(changes)
        self.data["settings"] = settings
        self.pm.update_settings(self.project, settings)
        self.preview.set_project(self.project, self.data["shots"], settings,
                                 self._load_cues())
        self.preview.refresh(force=True)

    def _on_resolution(self, value):
        try:
            w, h = [int(x) for x in value.split("x")]
        except Exception:
            return
        self._apply_settings(width=w, height=h)

    def _on_fps(self, value):
        self._apply_settings(fps=int(value))

    def _on_fit(self, value):
        self._apply_settings(fit=value)

    def _on_grade(self, value):
        self._apply_settings(grade=self._grade_reverse.get(value, "cold"))

    def _on_pacing(self, value):
        self._apply_settings(pacing=self._pacing_reverse.get(value, "picture"))

    def _on_vignette(self):
        self._apply_settings(vignette=bool(self.vignette_var.get()))

    def _on_grain(self):
        self._apply_settings(grain=3 if self.grain_var.get() else 0)

    # ==================================================================
    # 镜头编辑
    # ==================================================================
    def _on_timeline_duration(self, shot_id, duration):
        if not self.project:
            return
        self.pm.update_shot(self.project, shot_id, {"duration": duration})
        self.data = self.pm.migrate(self.pm.load(self.project))[0]
        self._full_refresh()
        self.seek(self.timeline.playhead)

    def _on_timeline_reorder(self, ordered_ids):
        if not self.project or not ordered_ids:
            return
        by_id = {s["id"]: s for s in self.data.get("shots", [])}
        shots = [by_id[sid] for sid in ordered_ids if sid in by_id]
        self.pm.replace_shots(self.project, shots)
        self.data = self.pm.migrate(self.pm.load(self.project))[0]
        self._full_refresh()

    def apply_shot_changes(self, changes: dict):
        if not self.project or len(self.selected) != 1:
            return
        self.pm.update_shot(self.project, self.selected[0], changes)
        self._persist(reload=True)
        self.seek(self.timeline.playhead)

    def apply_shot_duration(self, value: float):
        if not self.project or len(self.selected) != 1:
            return
        self.pm.update_shot(self.project, self.selected[0], {"duration": value})
        self._persist(reload=True)
        self.seek(min(self.timeline.playhead, self.pm.total_duration(self.data)))

    def move_selected(self, delta):
        if not self.project or not self.selected:
            return
        index = None
        for sid in self.selected:
            index = self.pm.move_shot(self.project, sid, delta)
        self._persist(reload=True)
        if index is not None:
            shot = self.data["shots"][index]
            self._set_selection([shot["id"]])

    def duplicate_selected(self):
        if not self.project:
            return
        ids = []
        for sid in list(self.selected):
            ids.extend(self.pm.duplicate_shot(self.project, sid))
        self._persist(reload=True)
        self.status_var.set(f"已复制 {len(self.selected)} 个镜头")
        self._set_selection([])

    def split_selected(self):
        if not self.project or len(self.selected) != 1:
            messagebox.showinfo("提示", "请只选择一个镜头再拆分。", parent=self.root)
            return
        shot = next((s for s in self.data["shots"] if s["id"] == self.selected[0]), None)
        if not shot:
            return
        start = float(shot["start"])
        duration = float(shot["duration"])
        default = self.timeline.playhead
        if not (start + 0.1 <= default <= start + duration - 0.1):
            default = start + duration / 2
        text = simpledialog.askstring(
            "拆分镜头", f"在该镜头的第几秒处拆分？\n范围 {start + 0.1:.2f} ~ {start + duration - 0.1:.2f}",
            initialvalue=f"{default:.2f}", parent=self.root)
        if not text:
            return
        try:
            at = float(text)
            self.pm.split_shot(self.project, shot["id"], at)
        except Exception as exc:
            messagebox.showerror("拆分失败", str(exc), parent=self.root)
            return
        self._persist(reload=True)

    def delete_selected(self):
        if not self.project or not self.selected:
            return
        ids = list(self.selected)
        if not messagebox.askyesno("删除镜头", f"删除选中的 {len(ids)} 个镜头？",
                                   parent=self.root):
            return
        candidate_files = self.pm.delete_shots(self.project, ids)
        self._persist(reload=True)
        self._set_selection([])
        self.seek(self.timeline.playhead)
        self._offer_cleanup(candidate_files)
        self.status_var.set(f"已删除 {len(ids)} 个镜头")

    def _offer_cleanup(self, rel_paths):
        """删除镜头后，询问是否清理已不再被引用的图片文件。"""
        orphans = []
        for rel in set(rel_paths):
            if self.pm.image_usage(self.data, rel) == 0:
                path = self.project / rel
                if path.exists():
                    orphans.append(path)
        if not orphans:
            return
        if messagebox.askyesno("清理图片", f"有 {len(orphans)} 张图片已不在时间轴中使用，"
                                           f"是否从项目 images 目录删除？", parent=self.root):
            for path in orphans:
                try:
                    path.unlink()
                except OSError:
                    pass
            self.timeline.clear_thumbnail_cache()
            for path in orphans:
                self.preview.loader.release(path)

    # ==================================================================
    # 故事（AI 生成 / 导入 / 导出）
    # ==================================================================
    def open_ai_settings(self):
        dialog = AISettingsDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result:
            self._set_status("AI 设置已保存")
        self.story_panel.refresh_key_label()

    def _generate_story_sync(self, keywords, count, style, extra):
        """V2.1 兼容入口：一步式生成（创意 + 完整流水线）。"""
        def run(engine, report):
            return engine.generate(keywords, count, style, extra)
        return self._run_story_job(run, f"正在生成 {count} 个分镜……",
                                   f"正在向 DeepSeek 请求故事（{count} 镜）……")

    def _generate_story_concepts(self, keywords, style, extra):
        """V2.2 阶段 0：先生成 3 个创意候选，返回 (concepts, 日志)。"""
        def run(engine, report):
            return engine.generate_concepts(keywords, style, extra)

        concepts = self._run_story_job(run, "正在构思创意……",
                                       "正在向 DeepSeek 请求 3 个故事创意……")
        return concepts or [], self.story_panel.last_log

    def _generate_story_plan(self, keywords, style, extra, count, concept):
        """V2.2 阶段 1~5：按用户选定的创意跑完整流水线，返回 (story, 日志)。"""
        def run(engine, report):
            return engine.pipeline(concept, keywords, style, extra,
                                   shot_count=count)

        story = self._run_story_job(
            run, f"正在按创意《{concept.get('title') or ''}》创作 {count} 个分镜……",
            f"正在创作《{concept.get('title') or ''}》……")
        story["keywords"] = keywords
        return story, self.story_panel.last_log

    def _run_story_job(self, run, busy_text, status_text):
        """后台线程跑 run(engine, report)，主线程 pump 事件；阶段进度进面板与日志。"""
        if self.generating:
            raise StoryError("正在生成中，请稍候。")
        cfg = ai_config.load_config()
        if not cfg.get("api_key"):
            raise StoryError("还没有配置 DeepSeek API Key。请先点「AI 设置」填写，"
                             "或设置环境变量 DEEPSEEK_API_KEY。")
        box = {}
        log: list[str] = []

        def report(stage, text):
            log.append(f"{stage}：{text}")

        def worker():
            engine = StoryEngine(config=cfg, on_stage=report)
            try:
                box["result"] = run(engine, report)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        self.generating = True
        self.story_panel.set_busy(True, busy_text)
        self.status_var.set(status_text)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        shown = -1
        try:
            while thread.is_alive():
                while shown + 1 < len(log):
                    shown += 1
                    self.story_panel.set_busy(True, log[shown])
                    self.status_var.set(log[shown])
                self.root.update()
                thread.join(0.05)
        finally:
            self.generating = False
            self.story_panel.last_log = log
            self.story_panel.set_busy(False)
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _story_versions(self):
        """当前项目的故事版本列表（没打开项目就只取面板里已加载的故事）。"""
        if self.project:
            try:
                data = self.pm.load(self.project)
            except Exception:  # noqa: BLE001 - 版本列表只是辅助信息
                data = None
            if data:
                return self.pm.list_versions(data)
        return list((self.story_panel.story or {}).get("versions") or [])

    def restore_story_version(self, version_id):
        """把项目故事恢复到指定版本（时间轴镜头同步、已有素材保留）。"""
        if not self._require_project():
            return
        try:
            result = self.pm.restore_version(self.project, version_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("恢复失败", str(exc), parent=self.root)
            return
        self.data = self.pm.load(self.project)
        self.story_panel.apply_restored(
            result.get("entry"), self.pm.get_story(self.data),
            f"已恢复到 {version_id}，可选择更早或「恢复前自动备份」回滚。")
        self.story_panel.set_versions(self._story_versions())
        self.preview.set_project(self.project, self.data["shots"], self.data["settings"],
                                 self._load_cues())
        self.timeline.clear_thumbnail_cache()
        self._full_refresh()

    def _set_status(self, text):
        self.status_var.set(text)

    def save_story(self, story):
        if not self._require_project():
            return
        try:
            self.pm.set_story(self.project, story)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return
        self.status_var.set(f"故事脚本已保存到 project.json：{story.get('title', '')}")

    def _write_story_subtitle(self, story, offset: float = 0.0) -> str | None:
        """把故事旁白写成项目内 SRT（追加导入时带 offset 偏移），返回相对路径。"""
        from modules.story_engine import to_srt
        srt_text = to_srt(story, offset=offset)
        if not srt_text.strip():
            return None
        safe_title = "".join(c for c in (story.get("title") or "story")
                             if c not in r'<>:"/\\|?*')[:24] or "story"
        target = self.project / "subtitles" / f"{safe_title}.srt"
        n = 1
        while target.exists():
            target = self.project / "subtitles" / f"{safe_title}_{n}.srt"
            n += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(srt_text, encoding="utf-8")
        return str(target.relative_to(self.project)).replace("\\", "/")

    def import_story(self, story, replace: bool):
        if not self._require_project():
            return
        shots = self.data.get("shots", [])
        if not replace and shots:
            # 追加模式：保留已有镜头，故事分镜接在后面
            pass
        elif replace and shots:
            if not messagebox.askyesno(
                    "替换分镜",
                    f"当前时间轴已有 {len(shots)} 个镜头，导入会全部替换。\n"
                    f"（图片文件仍保留在 images 目录，不会删除）\n\n继续？",
                    parent=self.root):
                return
        try:
            self.pm.set_story(self.project, story)
            new_shots = to_project_shots(story)
            for i, shot in enumerate(new_shots):
                shot["story_index"] = i + 1
            if replace:
                created = self.pm.replace_all_shots(self.project, new_shots)
            else:
                existing = self.data.get("shots", [])
                created = self.pm.replace_all_shots(self.project, existing + new_shots)
            # 旁白自动生成 SRT 字幕（含已有镜头的旁白，追加导入时一并导出）
            srt_rel = self._export_timeline_srt()
            if srt_rel:
                data = self.pm.load(self.project)
                data["subtitle"] = srt_rel
                self.pm.save(self.project, data)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self.root)
            return
        self._persist(reload=True)
        self.preview.cues = self._load_cues()
        self.timeline.clear_thumbnail_cache()
        self.timeline.fit()
        if created:
            self._set_selection([created[-1]["id"]])
        self.show_tab("editor")
        empty = sum(1 for s in self.data["shots"] if not s.get("image"))
        if empty:
            self.status_var.set(
                f"已导入 {len(new_shots)} 个故事分镜，其中 {empty} 个待配图；"
                f"旁白已生成字幕。可点「导入漫画图片」按顺序补齐画面。")
        else:
            self.status_var.set(f"已导入 {len(new_shots)} 个故事分镜，旁白已生成字幕。")

    def _export_timeline_srt(self) -> str | None:
        """把当前时间轴所有镜头的旁白导出为项目内 SRT，返回相对路径。"""
        data = self.pm.load(self.project)
        has_narration = any((s.get("narration") or "").strip() for s in data["shots"])
        if not has_narration:
            return None
        target = self.project / "subtitles" / "story_narration.srt"
        target.parent.mkdir(parents=True, exist_ok=True)
        self.pm.export_srt(self.project, target)
        return str(target.relative_to(self.project)).replace("\\", "/")

    def export_story_srt(self, story):
        if not self._require_project():
            return
        from modules.story_engine import to_srt
        path = filedialog.asksaveasfilename(
            title="导出旁白 SRT", defaultextension=".srt",
            initialfile=f"{story.get('title') or 'story'}.srt",
            filetypes=[("SRT 字幕", "*.srt")], parent=self.root)
        if not path:
            return
        try:
            from pathlib import Path as _P
            _P(path).write_text(to_srt(story), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return
        self.status_var.set(f"旁白 SRT 已导出：{path}")

    def reveal_story_shot(self, index: int):
        shots = self.data.get("shots", [])
        matches = [s for s in shots if s.get("story_index") == index + 1]
        if not matches:
            self.status_var.set("该分镜还没有导入时间轴")
            return
        self.show_tab("editor")
        self._set_selection([matches[0]["id"]])
        self.seek(float(matches[0]["start"]))

    # ==================================================================
    # AI 制作（V1.3：出图 / 配音 / 出片）
    # ==================================================================
    def _start_ai_task(self, worker, title: str):
        """在后台线程跑 worker(report)，report(text) 会出现在 AI 面板与状态栏。

        返回 True 表示已启动；错误由 _finish_ai_task 统一刷新界面。
        """
        if self.ai_busy:
            messagebox.showinfo("提示", "已有 AI 任务在进行中，请稍候。", parent=self.root)
            return False
        if not self.project:
            messagebox.showinfo("提示", "请先新建或打开一个项目。", parent=self.root)
            return False
        self.ai_busy = True
        self._set_busy_ui(True)
        self.ai_panel.set_busy(True, title)
        self.status_var.set(title)

        def report(text):
            self.msg_queue.put(("ai_progress", text))

        def run():
            try:
                summary = worker(report)
                self.msg_queue.put(("ai_done", summary or "完成"))
            except Exception as exc:  # noqa: BLE001 - 统一回传到界面
                self.msg_queue.put(("ai_error", str(exc)))

        threading.Thread(target=run, daemon=True).start()
        return True

    def _ai_config(self) -> dict:
        return sf_config.load_config()

    # -- 出图 ----------------------------------------------------------
    def generate_all_images(self, force: bool = False):
        if not self._require_project():
            return
        cfg = self._ai_config()
        if not cfg.get("api_key"):
            messagebox.showwarning(
                "未配置硅基流动 Key",
                "AI 出图需要硅基流动 API Key。\n请点「AI 设置」填写后重试。",
                parent=self.root)
            return
        shots = self.data.get("shots", [])
        if not shots:
            messagebox.showinfo("提示", "时间轴上还没有镜头，请先生成故事。",
                                parent=self.root)
            return
        targets = [s for s in shots if (force and (s.get("scene") or s.get("narration")))
                   or (not s.get("image") and (s.get("scene") or s.get("narration")))]
        if not targets:
            messagebox.showinfo("提示", "所有镜头都已经有画面了。\n"
                                         "勾选「重新生成已有 AI 画面」可强制重画。",
                                parent=self.root)
            return
        model = self.ai_panel.model_id()
        estimate = "（Kolors 免费）" if model.startswith("Kwai-Kolors") else "（按张计费）"
        if not messagebox.askyesno(
                "AI 出图",
                f"将为 {len(targets)} 个镜头生成画面。\n模型：{model} {estimate}\n\n"
                f"预计 1~3 分钟，过程中可以继续操作但不要关闭软件。",
                parent=self.root):
            return

        project = self.project
        settings = dict(self.data.get("settings", DEFAULT_SETTINGS))
        ids = [s["id"] for s in targets]
        exact_scene = {s["id"]: (s.get("scene") or s.get("narration") or "")
                       for s in targets}
        story = self.pm.get_story(self.data) or {}
        size = pick_size(settings["width"], settings["height"], model)
        # V2.2：画风由 AI 设置统一管理（默认暗黑漫画），不再每镜临时拼
        style_key = sf_config.load_config().get("image_style") or "comic_dark"
        story_shots = {s.get("shot_id"): s for s in (story.get("shots") or [])
                       if isinstance(s, dict)}

        def worker(report):
            engine = ImageEngine(config=dict(cfg, image_model=model))
            # 先清掉旧的 AI 画面，避免生成到一半时新旧混杂
            if force:
                self.pm.cleared_ai_images(project, ids)
            done, failed = 0, []
            by_id = {s["id"]: s for s in self.data.get("shots", [])}
            for i, shot_id in enumerate(ids, 1):
                scene = exact_scene[shot_id]
                report(f"画面 {i}/{len(ids)} · 正在生成…")
                # V2.2：文件名带版本号 + 指纹，重生成不覆盖旧素材
                shot_meta = by_id.get(shot_id) or {}
                target = project / "images" / pm_mod.material_name_for(
                    shot_meta, "image")
                try:
                    # V2.2：一致性卡片按这一镜的 character_ids / scene_id 过滤，
                    # 不在场的人物不进提示词（否则画面里会凭空多出人来）
                    story_shot = story_shots.get(shot_meta.get("shot_id")) or {}
                    hint = build_consistency_hint(story, scene, story_shot)
                    engine.generate_to_file(scene, target, style=style_key,
                                             extra=hint, size=size)
                    media_tools.normalize_image(target, target,
                                                settings["width"], settings["height"],
                                                fit=settings.get("fit", "cover"))
                    self.pm.set_ai_image(project, shot_id, target)
                    done += 1
                except Exception as exc:  # noqa: BLE001 - 单镜失败不影响其余
                    failed.append(f"#{i} {exc}")
                    report(f"画面 {i}/{len(ids)} 失败：{str(exc)[:60]}，继续下一镜…")
            if done == 0:
                raise RuntimeError("所有镜头出图都失败了。\n" + "\n".join(failed[:3]))
            msg = f"画面完成 {done}/{len(ids)}"
            if failed:
                msg += f"，{len(failed)} 个失败（{failed[0][:50]}）"
            return msg

        self._start_ai_task(worker, "准备生成画面…")

    # -- 配音 ----------------------------------------------------------
    def generate_all_voices(self, force: bool = False):
        if not self._require_project():
            return
        cfg = self._ai_config()
        if not cfg.get("api_key"):
            messagebox.showwarning(
                "未配置硅基流动 Key",
                "AI 配音需要硅基流动 API Key。\n请点「AI 设置」填写后重试。",
                parent=self.root)
            return
        shots = [s for s in self.data.get("shots", []) if (s.get("narration") or "").strip()]
        if not shots:
            messagebox.showinfo("提示", "时间轴上的镜头都没有旁白。\n"
                                         "请先在「故事」页签生成带旁白的分镜。",
                                parent=self.root)
            return
        targets = [s for s in shots if force or not s.get("voice")]
        if not targets:
            messagebox.showinfo("提示", "所有镜头都已经有配音了。\n"
                                         "勾选「重新生成已有配音」可重录。",
                                parent=self.root)
            return

        project = self.project
        voice_key = self.ai_panel.voice_id()
        speed = self.ai_panel.voice_speed()
        jobs = [(s["id"], (s.get("narration") or "").strip()) for s in targets]
        auto_fit = self.ai_panel.auto_fit.get()

        # V2.1：按题材选配音语气（AI 设置里可以固定成某个预设）
        story = self.pm.get_story(self.data) or {}
        preset = (sf_config.load_config().get("voice_style") or "auto")
        if preset == "auto":
            preset = story_engine.infer_style(story.get("keywords", ""), story.get("style", ""))
        cfg = dict(cfg, voice_style=preset)

        shot_meta = {s["id"]: s for s in targets}

        def worker(report):
            engine = VoiceEngine(config=dict(cfg, voice=voice_key, voice_speed=speed))
            done, failed = 0, []
            for i, (shot_id, text) in enumerate(jobs, 1):
                report(f"配音 {i}/{len(jobs)} · {speed:g}x · {text[:14]}…")
                # V2.2：配音文件名绑定镜头版本
                target = project / "audio" / pm_mod.material_name_for(
                    shot_meta.get(shot_id) or {}, "voice")
                try:
                    engine.synthesize_to_file(text, target, speed=speed, fmt="wav")
                    # 先裁掉首尾静音再测时长，否则 TTS 的句尾长静音会被算进镜头
                    media_tools.trim_silence(target)
                    ms = int(round(media_tools.audio_duration(target) * 1000))
                    self.pm.set_voice(project, shot_id, target, ms)
                    done += 1
                except Exception as exc:  # noqa: BLE001
                    failed.append(f"#{i} {exc}")
            if done == 0:
                raise RuntimeError("所有镜头配音都失败了。\n" + "\n".join(failed[:3]))
            fit_msg = ""
            if auto_fit:
                # 画面优先：时长为剧本的画面节奏，旁白塞不下才自动延长
                report("按画面节奏对齐镜头时长…")
                changed, extended = self.pm.fit_durations_to_voice(project)
                if changed:
                    fit_msg = f"，{len(changed)} 镜时长已对齐画面节奏"
                else:
                    fit_msg = "，时长原本已对齐"
                if extended:
                    fit_msg += f"，其中 {len(extended)} 镜旁白偏长已延长（建议精简）"
            # 配音完成后自动拼成旁白音轨，省一步操作
            report("配音完成，正在拼接旁白音轨…")
            try:
                track = self._build_voice_track_now()
                track_msg = f"，已拼成 {Path(track).name}" if track else ""
            except Exception as exc:  # noqa: BLE001
                track_msg = f"，但拼接失败：{str(exc)[:60]}"
            if auto_fit:
                self._sync_srt_after_retime()
            msg = f"配音完成 {done}/{len(jobs)}（语速 {speed:g}x）{fit_msg}{track_msg}"
            if failed:
                msg += f"，{len(failed)} 个失败（{failed[0][:40]}）"
            return msg

        self._start_ai_task(worker, "准备生成配音…")

    def rebalance_pacing(self):
        """按剧本的画面节奏重排时长（旁白偏长的镜头仍保留完整配音）。"""
        if not self._require_project():
            return
        try:
            changed = self.pm.rebalance_durations(self.project)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("节奏重排失败", str(exc), parent=self.root)
            return
        if not changed:
            messagebox.showinfo("节奏重排", "镜头时长已经符合剧本画面节奏，无需调整。\n"
                                            "（需要剧本里有每镜的时长）", parent=self.root)
            return
        self.data = self.pm.migrate(self.pm.load(self.project))[0]
        self._full_refresh()
        self._sync_srt_after_retime()
        # 时长变了，旁白音轨要按新起点重拼
        try:
            self._build_voice_track_now()
        except Exception:  # noqa: BLE001 - 拼音轨失败不阻断
            pass
        self.data = self.pm.migrate(self.pm.load(self.project))[0]
        self._full_refresh()
        self._set_status(f"节奏重排完成：{len(changed)} 镜已调整")

    def _sync_srt_after_retime(self):
        """按配音重排时长后，重导 SRT 字幕（字幕边界要跟新的镜头边界走）。"""
        try:
            srt_rel = self._export_timeline_srt()
            if srt_rel:
                data = self.pm.load(self.project)
                data["subtitle"] = srt_rel
                self.pm.save(self.project, data)
        except Exception:  # noqa: BLE001 - 字幕失败不阻断成片
            pass

    def _build_voice_track_now(self) -> str | None:
        """把逐镜头配音拼成一条旁白音轨并设为项目旁白。返回相对路径。"""
        data = self.pm.migrate(self.pm.load(self.project))[0]
        segments = self.pm.voice_segments(data)
        if not segments:
            return None
        total = self.pm.total_duration(data)
        audio_dir = self.project / "audio"
        target = audio_dir / "voice_track.wav"
        media_tools.concat_audio(
            [(self.project / rel, start, dur) for rel, start, dur in segments],
            target, total, offset_ms=self.pm.voice_offset_ms(data))
        # 直接写 narration 字段（不要用 set_narration，它会清掉逐镜头配音记录）
        data = self.pm.migrate(self.pm.load(self.project))[0]
        data["narration"] = str(target.relative_to(self.project)).replace("\\", "/")
        data["voice_track"] = data["narration"]
        self.pm.save(self.project, data)
        return data["narration"]

    def build_voice_track(self):
        if not self._require_project():
            return
        if not any(s.get("voice") for s in self.data.get("shots", [])):
            messagebox.showinfo("提示", "还没有任何配音片段。\n请先点「生成全部旁白配音」。",
                                parent=self.root)
            return
        try:
            rel = self._build_voice_track_now()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("拼接失败", str(exc), parent=self.root)
            return
        if not rel:
            return
        self._persist(reload=True)
        self.ai_panel.set_status(f"旁白音轨已生成：{Path(rel).name}")
        self.status_var.set(f"旁白音轨：{rel}")

    def clear_voices(self):
        if not self._require_project():
            return
        if not messagebox.askyesno("清除配音", "将清除所有镜头的配音记录（音频文件保留在 audio 目录）。\n"
                                             "确定继续？", parent=self.root):
            return
        self.pm.clear_voices(self.project)
        data = self.pm.load(self.project)
        data["voice_track"] = None
        self.pm.save(self.project, data)
        self._persist(reload=True)
        self.ai_panel.set_status("配音已清除")

    def render_ai(self):
        """「直接出片」：有配音时先拼音轨，再走常规渲染流程。"""
        if (any(s.get("voice") for s in self.data.get("shots", []))
                and not self.data.get("narration")):
            try:
                self._build_voice_track_now()
                self.data = self.pm.migrate(self.pm.load(self.project))[0]
            except Exception as exc:  # noqa: BLE001
                if not messagebox.askyesno(
                        "拼接配音失败", f"{exc}\n\n是否不带配音继续渲染？",
                        parent=self.root):
                    return
        self.render()

    # ==================================================================
    # 渲染
    # ==================================================================
    def render(self):
        if not self._require_project():
            return
        if self.rendering:
            messagebox.showinfo("提示", "正在渲染中，请稍候。", parent=self.root)
            return
        shots = self.data.get("shots", [])
        if not shots:
            messagebox.showwarning("缺少素材", "请先导入图片或从「故事」页签生成分镜。",
                                   parent=self.root)
            return
        missing = [s["image"] for s in shots
                   if s.get("image") and not (self.project / s["image"]).exists()]
        if missing:
            messagebox.showerror("素材缺失",
                                 "以下图片在项目目录中不存在：\n" + "\n".join(missing[:8]),
                                 parent=self.root)
            return
        empty = sum(1 for s in shots if not s.get("image"))
        if empty:
            if not messagebox.askyesno(
                    "有镜头未配图",
                    f"有 {empty} 个镜头还没有画面，将渲染为黑场 + 旁白字幕。\n继续渲染？",
                    parent=self.root):
                return
        try:
            RenderEngine()
        except RenderError as exc:
            messagebox.showerror("无法渲染", str(exc), parent=self.root)
            return

        self.pm.reflow(self.data)
        self.pm.save(self.project, self.data)
        total = self.pm.total_duration(self.data)
        output = self.project / "output" / f"{self.data.get('name', 'project')}_final.mp4"
        if output.exists() and not messagebox.askyesno(
                "覆盖确认", f"输出文件已存在：\n{output.name}\n是否覆盖？", parent=self.root):
            return

        self.rendering = True
        self.stop_play()
        self.render_btn.config(state="disabled", text="渲染中…")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.status_var.set(f"正在渲染 {len(shots)} 个镜头，总时长 {format_time(total)}……")
        thread = threading.Thread(target=self._render_worker,
                                  args=(self.data, dict(self.data["settings"]), output),
                                  daemon=True)
        thread.start()

    def _render_worker(self, data, settings, output):
        try:
            engine = RenderEngine()
            engine.render(data, settings, output)
            self.msg_queue.put(("render_ok", str(output)))
        except Exception as exc:
            self.msg_queue.put(("render_err", str(exc)))

    def _finish_ai_task(self, kind, value):
        if kind == "ai_progress":
            self.ai_panel.set_busy(True, value)
            self.status_var.set(value)
            return
        self.ai_busy = False
        self._set_busy_ui(False)
        if kind == "ai_error":
            self.ai_panel.set_busy(False, "")
            self.ai_panel.set_status(f"失败：{str(value)[:400]}", error=True)
            self.status_var.set("AI 任务失败")
        else:
            self.ai_panel.set_busy(False, value or "完成")
            self.status_var.set(value or "AI 任务完成")
        # 无论成功失败都刷新：部分成功的镜头也要立刻出现在时间轴上
        self._persist(reload=True)
        self.timeline.clear_thumbnail_cache()
        self.preview.loader.clear()
        self.preview.refresh(force=True)

    def _set_busy_ui(self, busy: bool):
        self.render_btn.config(state="disabled" if busy else "normal",
                               text="处理中…" if busy else "▶  开始成片渲染")
        if busy:
            if not self.rendering:
                self.progress.config(mode="indeterminate")
                self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)

    def _poll_queue(self):
        try:
            while True:
                kind, value = self.msg_queue.get_nowait()
                self._route_message(kind, value)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _route_message(self, kind, value):
        if kind.startswith("render_"):
            self._finish_render(kind, value)
        elif kind.startswith("batch_"):
            self._finish_batch(kind, value)
        elif kind.startswith("ai_"):
            self._finish_ai_task(kind, value)

    def _finish_render(self, kind, value):
        self.rendering = False
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self.render_btn.config(state="normal", text="▶  开始成片渲染")
        if kind == "render_ok":
            self.status_var.set(f"成片完成：{value}")
            self._ask_open(value)
        else:
            self.status_var.set("渲染失败")
            messagebox.showerror("渲染失败", value[-3000:], parent=self.root)

    def _ask_open(self, path):
        if messagebox.askyesno("渲染完成", f"视频已生成：\n{path}\n\n是否播放？", parent=self.root):
            try:
                os.startfile(path)
            except Exception as exc:
                messagebox.showerror("打开失败", str(exc), parent=self.root)

    def open_output(self):
        if not self._require_project():
            return
        folder = self.project / "output"
        folder.mkdir(exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(folder.resolve()))
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc), parent=self.root)

    # ==================================================================
    # 批量生产（V2.0）
    # ==================================================================
    def pick_batch_workspace(self):
        folder = filedialog.askdirectory(
            title="选择批量输出目录（每个项目一个子目录）", parent=self.root)
        return folder or None

    def start_batch(self, jobs, workspace, settings=None):
        """在后台线程跑 BatchRunner；进度事件经消息队列回到面板。"""
        if self.batch_panel.busy:
            return
        if self.ai_busy or self.rendering:
            messagebox.showinfo("提示", "当前有单项目任务在运行，请等它结束再开始批量。",
                                parent=self.root)
            return
        sf_cfg = sf_config.load_config()
        ds_cfg = ai_config.load_config()
        missing = []
        if not ds_cfg.get("api_key"):
            missing.append("DeepSeek（生成故事）")
        if not sf_cfg.get("api_key"):
            missing.append("硅基流动（出图 / 配音）")
        if missing:
            messagebox.showwarning(
                "缺少 API Key",
                "批量生产需要以下 Key：\n· " + "\n· ".join(missing)
                + "\n\n请点「AI 设置」填写后重试。", parent=self.root)
            return
        overwrite = [j.name for j in jobs
                     if (Path(workspace) / j.name / "project.json").exists()]
        if overwrite:
            # create_project 不会覆盖已有项目（重跑会直接报错），这里先明确告知
            if not messagebox.askyesno(
                    "项目已存在",
                    "以下项目在输出目录里已经存在，本次不会重新生成（会标记为失败）：\n"
                    + "\n".join(f"· {n}" for n in overwrite[:10])
                    + ("\n…" if len(overwrite) > 10 else "")
                    + "\n\n需要重跑请先改名，或把旧项目移到别的目录。仍要继续吗？",
                    parent=self.root):
                return
        if not messagebox.askyesno(
                "开始批量生产",
                f"将生产 {len(jobs)} 个项目，共 {sum(j.shot_count for j in jobs)} 个镜头。\n"
                f"输出目录：{workspace}\n\n"
                "会真实调用 DeepSeek 与硅基流动（按量计费），预计较长时间。\n"
                "过程中可以切到别的页签，但不要关闭软件。确定开始？",
                parent=self.root):
            return

        style_hint = ""
        speed = self.ai_panel.voice_speed()
        # V2.1：批量里每个项目按自己的题材自动选配音语气（voice_style=auto）
        render_settings = dict(settings or {}, voice_style="auto")

        def report(event, **info):
            payload = {"event": event}
            payload.update(info)
            self.msg_queue.put(("batch_event", payload))

        def worker():
            try:
                story_engine = StoryEngine(config=dict(ds_cfg))
                image_engine = ImageEngine(config=dict(sf_cfg))
                voice_engine = VoiceEngine(
                    config=dict(sf_cfg, voice=self.ai_panel.voice_id(), voice_speed=speed))
                runner = BatchRunner(
                    Path(workspace), jobs,
                    story_engine=story_engine, image_engine=image_engine,
                    voice_engine=voice_engine,
                    settings=render_settings or None,
                    cancel=self.batch_panel.stop_requested)
                result = runner.run(report)
                self.msg_queue.put(("batch_done", result))
            except Exception as exc:  # noqa: BLE001 - 统一回传到界面
                self.msg_queue.put(("batch_error", str(exc) or type(exc).__name__))

        self.batch_panel.set_busy(True, len(jobs))
        self.status_var.set(f"批量生产：{len(jobs)} 个项目")
        threading.Thread(target=worker, daemon=True).start()

    def _finish_batch(self, kind, value):
        if kind == "batch_event":
            self.batch_panel.handle_event(value)
            return
        if kind == "batch_error":
            self.batch_panel.handle_error(str(value))
            self.status_var.set("批量生产启动失败")
            return
        self.batch_panel.handle_results(value)
        ok = sum(1 for r in value if r.ok)
        self.status_var.set(f"批量完成：{ok}/{len(value)} 成功")
        # 批量里可能覆盖了当前打开的项目（同名），重读一次避免界面与磁盘不一致
        if self.project and (Path(self.project) / "project.json").exists():
            try:
                self._persist(reload=True)
                self.timeline.clear_thumbnail_cache()
                self.preview.loader.clear()
                self.preview.refresh(force=True)
            except Exception:  # noqa: BLE001 - 刷新失败不影响批量结果展示
                pass

    def _open_path(self, path):
        try:
            path = Path(path)
            if path.exists():
                os.startfile(str(path.resolve()))
            else:
                messagebox.showwarning("提示", f"文件不存在：{path}", parent=self.root)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开失败", str(exc), parent=self.root)

    # ==================================================================
    # 关闭
    # ==================================================================
    def _confirm_discard(self):
        if self.project and self._dirty:
            return messagebox.askyesno("未保存", "当前项目有未保存修改，是否放弃？",
                                       parent=self.root)
        return True

    def on_close(self):
        self.stop_play()
        if self.project:
            try:
                self.pm.reflow(self.data)
                self.pm.save(self.project, self.data)
            except Exception:
                pass
        self.root.destroy()


def run(app_dir: Path):
    root = tk.Tk()
    root.iconname(APP_NAME)
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass
    HorrorStudioApp(root)
    root.mainloop()


if __name__ == "__main__":
    run(Path(__file__).resolve().parent.parent)
