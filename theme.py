"""AI Horror Studio - 暗黑主题定义。

所有颜色、字体、ttk 样式集中在这里，其它模块只引用常量或 Theme 方法，
不要在模块里写死颜色，方便以后整体换肤。
"""
import tkinter as tk
from tkinter import ttk


class Palette:
    """暗黑恐怖风配色。"""

    BG = "#0b0c10"            # 主背景
    BG_ALT = "#0f1117"        # 次级背景
    PANEL = "#161922"         # 面板
    PANEL_ALT = "#1d212c"     # 面板内次级区块
    PANEL_HOVER = "#262b38"   # 悬停高亮
    BORDER = "#2a3040"        # 分割线 / 边框
    BORDER_STRONG = "#3a4256"

    TEXT = "#e6e3ea"          # 主文字
    TEXT_DIM = "#8d93a3"      # 次要文字
    TEXT_FAINT = "#5c6272"    # 最弱文字 / 占位

    BLOOD = "#b3122b"         # 主强调色：血红
    BLOOD_HOVER = "#d4183a"
    BLOOD_DEEP = "#6e0a1a"

    RUST = "#c0663a"          # 辅助强调
    BONE = "#cfc7b6"          # 文字强调（骨白）
    AMBER = "#d9a441"         # 警告 / 选中
    SUCCESS = "#4f9d69"
    ERROR = "#d94a4a"

    TRACK = "#101218"         # 时间轴轨道底
    TRACK_ALT = "#13161e"
    RULER = "#0d0f14"


FONT_UI = "Microsoft YaHei UI"
FONT_MONO = "Cascadia Mono"


class Theme:
    """统一 ttk 样式注册。"""

    def __init__(self, root: tk.Misc):
        self.root = root
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._configure_tk_defaults()
        self._configure_styles()

    def _configure_tk_defaults(self):
        self.root.option_add("*Font", (FONT_UI, 10))
        self.root.option_add("*TCombobox*Listbox.background", Palette.PANEL_ALT)
        self.root.option_add("*TCombobox*Listbox.foreground", Palette.TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", Palette.BLOOD)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _configure_styles(self):
        s = self.style
        s.configure(".", background=Palette.BG, foreground=Palette.TEXT,
                    fieldbackground=Palette.PANEL_ALT, bordercolor=Palette.BORDER,
                    lightcolor=Palette.BORDER, darkcolor=Palette.BORDER,
                    focuscolor=Palette.BLOOD, font=(FONT_UI, 10))

        s.configure("TFrame", background=Palette.BG)
        s.configure("Panel.TFrame", background=Palette.PANEL)
        s.configure("Alt.TFrame", background=Palette.PANEL_ALT)

        s.configure("TLabel", background=Palette.BG, foreground=Palette.TEXT)
        s.configure("Panel.TLabel", background=Palette.PANEL, foreground=Palette.TEXT)
        s.configure("Dim.TLabel", background=Palette.PANEL, foreground=Palette.TEXT_DIM)
        s.configure("Section.TLabel", background=Palette.PANEL, foreground=Palette.TEXT_DIM,
                    font=(FONT_UI, 9, "bold"))
        s.configure("Title.TLabel", background=Palette.PANEL, foreground=Palette.BONE,
                    font=(FONT_UI, 15, "bold"))
        s.configure("Mono.TLabel", background=Palette.PANEL, foreground=Palette.TEXT_DIM,
                    font=(FONT_MONO, 9))

        # 普通按钮
        s.configure("TButton", background=Palette.PANEL_ALT, foreground=Palette.TEXT,
                    bordercolor=Palette.BORDER, relief="flat", padding=(10, 6),
                    font=(FONT_UI, 9))
        s.map("TButton",
              background=[("active", Palette.PANEL_HOVER), ("pressed", Palette.BORDER)],
              foreground=[("disabled", Palette.TEXT_FAINT)],
              bordercolor=[("active", Palette.BORDER_STRONG)])

        # 主操作按钮
        s.configure("Accent.TButton", background=Palette.BLOOD, foreground="#ffffff",
                    bordercolor=Palette.BLOOD, padding=(12, 8), font=(FONT_UI, 10, "bold"))
        s.map("Accent.TButton",
              background=[("active", Palette.BLOOD_HOVER), ("pressed", Palette.BLOOD_DEEP)],
              foreground=[("disabled", Palette.TEXT_FAINT)])

        # 小按钮
        s.configure("Small.TButton", padding=(6, 3), font=(FONT_UI, 9))

        # 输入框
        s.configure("TEntry", fieldbackground=Palette.PANEL_ALT, foreground=Palette.TEXT,
                    insertcolor=Palette.TEXT, bordercolor=Palette.BORDER, padding=4,
                    relief="flat")
        s.map("TEntry",
              fieldbackground=[("focus", Palette.PANEL_HOVER)],
              bordercolor=[("focus", Palette.BLOOD)])

        # 下拉框
        s.configure("TCombobox", fieldbackground=Palette.PANEL_ALT, background=Palette.PANEL_ALT,
                    foreground=Palette.TEXT, arrowcolor=Palette.TEXT_DIM,
                    bordercolor=Palette.BORDER, padding=4)
        s.map("TCombobox",
              fieldbackground=[("readonly", Palette.PANEL_ALT)],
              foreground=[("readonly", Palette.TEXT)],
              background=[("active", Palette.PANEL_HOVER)])

        # 分隔线
        s.configure("TSeparator", background=Palette.BORDER)

        # 进度条
        s.configure("Horizontal.TProgressbar",
                    troughcolor=Palette.TRACK, background=Palette.BLOOD,
                    bordercolor=Palette.BORDER, lightcolor=Palette.BLOOD,
                    darkcolor=Palette.BLOOD)

        # 滚动条
        s.configure("Vertical.TScrollbar", background=Palette.PANEL_ALT,
                    troughcolor=Palette.TRACK, bordercolor=Palette.BG,
                    arrowcolor=Palette.TEXT_DIM, relief="flat")
        s.map("Vertical.TScrollbar", background=[("active", Palette.PANEL_HOVER)])
        s.configure("Horizontal.TScrollbar", background=Palette.PANEL_ALT,
                    troughcolor=Palette.TRACK, bordercolor=Palette.BG,
                    arrowcolor=Palette.TEXT_DIM, relief="flat")
        s.map("Horizontal.TScrollbar", background=[("active", Palette.PANEL_HOVER)])

        # 列表
        s.configure("Treeview", background=Palette.PANEL, foreground=Palette.TEXT,
                    fieldbackground=Palette.PANEL, bordercolor=Palette.BORDER,
                    rowheight=26, relief="flat")
        s.map("Treeview", background=[("selected", Palette.BLOOD_DEEP)],
              foreground=[("selected", "#ffffff")])
        s.configure("Treeview.Heading", background=Palette.PANEL_ALT,
                    foreground=Palette.TEXT_DIM, relief="flat", padding=(6, 4),
                    font=(FONT_UI, 9, "bold"))
        s.map("Treeview.Heading", background=[("active", Palette.PANEL_HOVER)])

        # Notebook（预留：V1.2 故事/分镜页签会用）
        s.configure("TNotebook", background=Palette.BG, bordercolor=Palette.BORDER,
                    tabmargins=(0, 4, 0, 0))
        s.configure("TNotebook.Tab", background=Palette.PANEL, foreground=Palette.TEXT_DIM,
                    padding=(14, 7), font=(FONT_UI, 9))
        s.map("TNotebook.Tab",
              background=[("selected", Palette.PANEL_ALT)],
              foreground=[("selected", Palette.BONE)])

    def app_font(self, size=10, weight="normal"):
        return (FONT_UI, size, weight)

    def mono_font(self, size=9):
        return (FONT_MONO, size)
