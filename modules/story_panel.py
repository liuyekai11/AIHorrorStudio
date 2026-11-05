"""「故事」页签：输入题材 → DeepSeek 生成分镜脚本 → 审阅 → 导入时间轴。

职责边界
--------
* 只负责界面与交互；网络请求通过注入的 `generate(keywords, count, style, extra)`
  回调执行（由 main_window 放到后台线程、写入队列后再回调进来），
  这样面板本身不持有线程，也方便在测试里替换。
* 所有持久化动作（保存 story、导入 shots、导出 SRT）通过注入的回调完成，
  面板不直接读写 project.json。

回调
----
  generate(keywords, count, style, extra) -> dict     生成故事（同步，阻塞）
  on_import(story, replace) -> None                    导入时间轴
  on_save(story) -> None                               保存脚本到项目
  on_export_srt(story) -> None                         导出旁白 SRT
  on_open_settings() -> None                           打开 AI 设置
  on_status(text) -> None                              状态栏提示

V2.2 五阶段（可选回调，没注入时回退到一步式 generate）
  on_concepts(keywords, style, extra) -> (list[创意], list[运行日志])   创意候选
  on_plan(keywords, style, extra, count, concept) -> (story, 日志)      按选定创意完整创作
"""
import tkinter as tk

from theme import Palette, FONT_UI, FONT_MONO
from modules import ai_config
from modules.story_engine import MAX_SHOTS, MIN_SHOTS, to_srt  # noqa: F401  (to_srt 供外部复用)
from modules import story_schema as ss
from modules import pacing

SCENE_PREVIEW_CHARS = 36
# 手动编辑后重算时长：单镜时长允许的浮点误差（秒）
DURATION_FIT_EPS = 1e-6


def repace_story(story: dict) -> bool:
    """镜头被增 / 删 / 改之后，按当前镜头列表重新计算时长（原地修改 story）。

    - 目标时长取 story["pacing"]["target_seconds"]；旧数据没有时按现有时长之和。
    - 总时长必须等于目标（误差 ≤ pacing.TOTAL_TOLERANCE），每镜 1.5~6 秒。
    - 镜头数超出可行性时，不擅自删镜头：按镜头数能实现的最长总长分配并更新目标。
    返回是否真的重算了；无法重算（空镜头 / 坏数据）时返回 False，故事保持不变。
    """
    if not isinstance(story, dict):
        return False
    shots = [s for s in (story.get("shots") or []) if isinstance(s, dict)]
    if not shots:
        return False
    block = story.get("pacing") if isinstance(story.get("pacing"), dict) else {}
    target = None
    for value in (block.get("target_seconds"), block.get("total_seconds")):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            target = number
            break
    if target is None:
        target = round(sum(float(s.get("duration") or 0) for s in shots), 2) or None
    if not target:
        return False
    # 已经达标（每镜都有合法时长且总和 = 目标）就不重算，避免每次打开故事打乱用户手调的节奏
    current = []
    for shot in shots:
        try:
            current.append(float(shot.get("duration")))
        except (TypeError, ValueError):
            current = None
            break
    if (current is not None and len(current) == len(shots)
            and abs(sum(current) - target) <= DURATION_FIT_EPS
            and all(pacing.MIN_SECONDS - 1e-9 <= d <= pacing.MAX_SECONDS + 1e-9
                    for d in current)):
        return False
    try:
        result = pacing.plan_durations(shots, target, allow_resize=False)
    except pacing.PacingError:
        return False
    durations = result.get("durations") or []
    if len(durations) != len(shots):
        return False
    kept = result.get("kept_shot_ids")
    if kept is not None:
        by_key = {(s.get("shot_id") if s.get("shot_id") is not None else i): s
                  for i, s in enumerate(shots)}
        pairs = [(by_key.get(key), d) for key, d in zip(kept, durations)]
        if any(shot is None for shot, _ in pairs):
            return False
        for shot, duration in pairs:
            shot["duration"] = duration
    else:
        for shot, duration in zip(shots, durations):
            shot["duration"] = duration
    total = round(sum(float(s["duration"]) for s in shots), 2)
    story["pacing"] = {**block,
                       "target_seconds": round(float(result.get("target") or target), 2),
                       "total_seconds": total,
                       "error": result.get("error"),
                       "shot_count": len(shots),
                       "kept_count": len(shots),
                       "min_seconds": pacing.MIN_SECONDS,
                       "max_seconds": pacing.MAX_SECONDS,
                       "adjusted": True}
    story["total_duration"] = total
    return True


GRADE_LABELS = {"excellent": "优秀", "pass": "合格", "regenerate": "建议重写"}
STAGE_LABELS = {"hook": "钩子", "setup": "铺垫", "escalation": "升级",
                "reversal": "反转", "aftertaste": "余味"}
ENDING_LABELS = {"closed": "完整结局", "open": "开放式", "series": "系列悬念"}
REVERSAL_LABELS = {"identity": "身份", "time": "时间", "space": "空间",
                   "motivation": "动机", "perception": "认知", "none": "无反转"}
# 质量审核里最重要的几项（分数面板按这个顺序展示）
SCORE_LABELS = tuple(
    (key, ss.SCORE_LABELS[key], ss.SCORE_WEIGHTS[key]) for key in ss.SCORE_WEIGHTS)


class StoryPanel(tk.Frame):
    def __init__(self, master, generate=None, on_import=None, on_save=None,
                 on_export_srt=None, on_open_settings=None, on_status=None,
                 on_reveal_shot=None, on_concepts=None, on_plan=None):
        super().__init__(master, bg=Palette.PANEL)
        self.generate_cb = generate or (lambda *a: {})
        self.on_import = on_import or (lambda story, replace: None)
        self.on_save = on_save or (lambda story: None)
        self.on_export_srt = on_export_srt or (lambda story: None)
        self.on_open_settings = on_open_settings or (lambda: None)
        self.on_status = on_status or (lambda text: None)
        self.on_reveal_shot = on_reveal_shot or (lambda index: None)
        # V2.2 五阶段：创意候选 / 重新策划（可选回调，没注入就退回一步式生成）
        self.concepts_cb = on_concepts
        self.plan_cb = on_plan

        self.story: dict | None = None
        self.busy = False
        self.concepts: list[dict] = []
        self.versions: list[dict] = []
        self._restore_cb = None
        self._version_by_label: dict[str, dict] = {}
        self.last_log: list = []
        # 编辑中的行：(项 id) -> 原始 shot dict
        self._rows: dict[str, dict] = {}

        self._build()

    # ==================================================================
    # 构建
    # ==================================================================
    def _build(self):
        outer = tk.Frame(self, bg=Palette.PANEL)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        top = tk.Frame(outer, bg=Palette.PANEL)
        top.pack(side="left", fill="y", padx=(0, 14))
        top.pack_propagate(False)
        top.configure(width=300)
        self._build_form(top)

        right = tk.Frame(outer, bg=Palette.BG_ALT)
        right.pack(side="left", fill="both", expand=True)
        self._build_result(right)

    def _label(self, parent, text, top_pad=(10, 4), **kw):
        tk.Label(parent, text=text, bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold"), anchor="w").pack(
            fill="x", pady=top_pad, **kw)

    def _entry(self, parent, var, height=None):
        if height:
            widget = tk.Text(parent, height=height, wrap="word", bg=Palette.PANEL_ALT,
                             fg=Palette.TEXT, insertbackground=Palette.TEXT, relief="flat",
                             font=(FONT_UI, 9), padx=8, pady=6,
                             highlightthickness=1, highlightbackground=Palette.BORDER,
                             highlightcolor=Palette.BLOOD)
            widget.insert("1.0", var)
            return widget
        return tk.Entry(parent, textvariable=var, bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                        insertbackground=Palette.TEXT, relief="flat", font=(FONT_UI, 9),
                        highlightthickness=1, highlightbackground=Palette.BORDER,
                        highlightcolor=Palette.BLOOD)

    def _build_form(self, parent):
        self._label(parent, "题材关键词", top_pad=(0, 4))
        self.keywords_text = self._entry(
            parent, "废弃医院、纸人、雨夜", height=3)
        self.keywords_text.pack(fill="x")
        tk.Label(parent, text="用顿号或逗号分隔多个关键词；越具体越可控",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8),
                 anchor="w", wraplength=286, justify="left").pack(fill="x", pady=(3, 0))

        self._label(parent, "氛围 / 风格")
        self.style_var = tk.StringVar(value="中式民俗恐怖")
        style_row = tk.Frame(parent, bg=Palette.PANEL)
        style_row.pack(fill="x")
        style_menu = tk.OptionMenu(style_row, self.style_var,
                                   "中式民俗恐怖", "日式都市怪谈", "克苏鲁式未知恐惧",
                                   "心理惊悚", "血腥直给", "细思极恐（无超自然）")
        style_menu.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat", bd=0,
                          activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                          highlightthickness=0, font=(FONT_UI, 9), anchor="w", width=20)
        style_menu["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                                  activebackground=Palette.BLOOD, activeforeground="#ffffff")
        style_menu.pack(fill="x")

        self._label(parent, "分镜数量")
        count_row = tk.Frame(parent, bg=Palette.PANEL)
        count_row.pack(fill="x")
        self.count_var = tk.IntVar(value=8)
        self.count_label = tk.Label(count_row, text="8 镜", bg=Palette.PANEL,
                                    fg=Palette.TEXT, font=(FONT_MONO, 10), width=6,
                                    anchor="e")
        self.count_label.pack(side="right")
        self.count_scale = tk.Scale(
            count_row, from_=MIN_SHOTS, to=MAX_SHOTS, orient="horizontal",
            variable=self.count_var, showvalue=False, command=self._on_count,
            bg=Palette.PANEL, fg=Palette.BONE, highlightthickness=1,
            highlightbackground=Palette.BORDER, bd=1, relief="flat",
            troughcolor=Palette.BORDER_STRONG, activebackground=Palette.BLOOD,
            sliderrelief="raised", sliderlength=20, width=14, length=140)
        self.count_scale.pack(side="left", fill="x", expand=True)

        self._label(parent, "额外要求（可选）")
        self.extra_var = tk.StringVar(value="")
        extra = tk.Entry(parent, textvariable=self.extra_var, bg=Palette.PANEL_ALT,
                         fg=Palette.TEXT, insertbackground=Palette.TEXT, relief="flat",
                         font=(FONT_UI, 9), highlightthickness=1,
                         highlightbackground=Palette.BORDER, highlightcolor=Palette.BLOOD)
        extra.pack(fill="x", ipady=4)
        extra.insert(0, "")

        self._label(parent, "API 状态", top_pad=(14, 2))
        self.key_label = tk.Label(parent, text="", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                                  font=(FONT_UI, 8), anchor="w", wraplength=286,
                                  justify="left")
        self.key_label.pack(fill="x")
        btn_row = tk.Frame(parent, bg=Palette.PANEL)
        btn_row.pack(fill="x", pady=(4, 0))
        self._small_button(btn_row, "AI 设置…", self.on_open_settings).pack(side="left")
        self._small_button(btn_row, "刷新状态", self.refresh_key_label).pack(side="left", padx=6)

        tk.Frame(parent, bg=Palette.PANEL).pack(fill="both", expand=True)

        self.gen_btn = tk.Button(
            parent, text="✦  生成故事分镜", command=self._on_generate,
            bg=Palette.BLOOD, fg="#ffffff", activebackground=Palette.BLOOD_HOVER,
            activeforeground="#ffffff", relief="flat", bd=0, pady=10,
            font=(FONT_UI, 10, "bold"), cursor="hand2")
        self.gen_btn.pack(fill="x", pady=(8, 4))
        self.gen_status = tk.Label(parent, text="", bg=Palette.PANEL, fg=Palette.AMBER,
                                   font=(FONT_UI, 8), anchor="w", wraplength=286,
                                   justify="left")
        self.gen_status.pack(fill="x", pady=(2, 6))
        self.refresh_key_label()

    def _small_button(self, parent, text, cmd):
        btn = tk.Button(parent, text=text, command=cmd, bg=Palette.PANEL_ALT,
                        fg=Palette.TEXT, activebackground=Palette.PANEL_HOVER,
                        activeforeground=Palette.TEXT, relief="flat", bd=0,
                        padx=10, pady=3, font=(FONT_UI, 9), cursor="hand2")
        btn.bind("<Enter>", lambda e: btn.config(bg=Palette.PANEL_HOVER))
        btn.bind("<Leave>", lambda e: btn.config(bg=Palette.PANEL_ALT))
        return btn

    def _build_result(self, parent):
        head = tk.Frame(parent, bg=Palette.BG_ALT)
        head.pack(fill="x", padx=14, pady=(12, 6))
        self.title_label = tk.Label(head, text="还没有生成故事", bg=Palette.BG_ALT,
                                    fg=Palette.BONE, font=(FONT_UI, 13, "bold"),
                                    anchor="w")
        self.title_label.pack(side="left")
        self.meta_label = tk.Label(head, text="", bg=Palette.BG_ALT,
                                   fg=Palette.TEXT_FAINT, font=(FONT_MONO, 9))
        self.meta_label.pack(side="right")
        self.logline_label = tk.Label(parent, text="", bg=Palette.BG_ALT,
                                      fg=Palette.TEXT_DIM, font=(FONT_UI, 9),
                                      anchor="w", justify="left", wraplength=760)
        self.logline_label.pack(fill="x", padx=14)
        # 质量评分 + 版本行（V2.2）
        info_row = tk.Frame(parent, bg=Palette.BG_ALT)
        info_row.pack(fill="x", padx=14, pady=(4, 0))
        self.score_label = tk.Label(info_row, text="", bg=Palette.BG_ALT,
                                    fg=Palette.TEXT_DIM, font=(FONT_UI, 9),
                                    anchor="w", justify="left", wraplength=520)
        self.score_label.pack(side="left")
        self.version_var = tk.StringVar(value="")
        self.version_menu = tk.OptionMenu(info_row, self.version_var, "（暂无版本）")
        self.version_menu.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat",
                                 bd=0, highlightthickness=0, font=(FONT_UI, 9),
                                 activebackground=Palette.PANEL_HOVER,
                                 activeforeground=Palette.TEXT, width=32)
        self.version_menu["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                                         activebackground=Palette.BLOOD,
                                         activeforeground="#ffffff")
        self._small_button(info_row, "恢复此版本", self._restore_version).pack(
            side="right", padx=(4, 0))
        self.version_menu.pack(side="right", padx=(8, 0))

        body = tk.Frame(parent, bg=Palette.BG_ALT)
        body.pack(fill="both", expand=True)
        # 创意候选视图：用户选一个再创作（V2.2 五阶段）
        self.concept_frame = tk.Frame(body, bg=Palette.BG_ALT)
        self.concept_hint = tk.Label(
            self.concept_frame, bg=Palette.BG_ALT, fg=Palette.TEXT_DIM,
            font=(FONT_UI, 9), anchor="w", justify="left", wraplength=760,
            text="左边填好题材和分镜数，点「生成故事分镜」——先出 3 个创意，选一个再写完整剧本。")
        self.concept_hint.pack(fill="x", padx=14, pady=(8, 4))
        concept_list = tk.Frame(self.concept_frame, bg=Palette.BG_ALT)
        concept_list.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        import tkinter.ttk as ttk
        self.concept_tree = ttk.Treeview(
            concept_list, columns=("title", "conflict", "hook", "ending"),
            show="headings", selectmode="browse")
        for col, text, width in (("title", "创意", 150), ("conflict", "核心冲突", 230),
                                 ("hook", "前 3 秒钩子", 250), ("ending", "结局", 80)):
            self.concept_tree.heading(col, text=text)
            self.concept_tree.column(col, width=width, anchor="w",
                                     stretch=col in ("conflict", "hook"))
        c_scroll = ttk.Scrollbar(concept_list, orient="vertical",
                                 command=self.concept_tree.yview)
        self.concept_tree.configure(yscrollcommand=c_scroll.set)
        c_scroll.pack(side="right", fill="y")
        self.concept_tree.pack(side="left", fill="both", expand=True)
        self.concept_tree.bind("<<TreeviewSelect>>", self._on_concept_select)
        c_actions = tk.Frame(self.concept_frame, bg=Palette.BG_ALT)
        c_actions.pack(fill="x", padx=14, pady=(0, 10))
        self.use_concept_btn = tk.Button(
            c_actions, text="✎  用这个创意写完整剧本", command=self._use_concept,
            bg=Palette.BLOOD, fg="#ffffff", activebackground=Palette.BLOOD_HOVER,
            activeforeground="#ffffff", relief="flat", bd=0, padx=14, pady=8,
            font=(FONT_UI, 9, "bold"), cursor="hand2", state="disabled")
        self.use_concept_btn.pack(side="left")
        self._small_button(c_actions, "重新出创意",
                           lambda: self._on_generate(concepts_only=True)).pack(
            side="left", padx=6)

        self.shot_frame = tk.Frame(body, bg=Palette.BG_ALT)
        self.shot_frame.pack(fill="both", expand=True)
        table_wrap = tk.Frame(self.shot_frame, bg=Palette.BG_ALT)
        table_wrap.pack(fill="both", expand=True, padx=14, pady=(8, 6))
        cols = ("index", "scene", "narration", "duration")
        self.tree = ttk.Treeview(table_wrap, columns=cols, show="headings",
                                 selectmode="browse")
        for col, text, width in (("index", "#", 40), ("scene", "画面描述", 420),
                                 ("narration", "旁白", 300), ("duration", "时长", 64)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="center" if col != "scene" else "w",
                             stretch=col in ("scene", "narration"))
        scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-Button-1>", self._on_tree_double)
        self.tree.bind("<Return>", self._on_tree_double)

        editor = tk.Frame(parent, bg=Palette.BG_ALT)
        editor.pack(fill="x", padx=14, pady=(0, 6))
        edit_row = tk.Frame(editor, bg=Palette.BG_ALT)
        edit_row.pack(fill="x")
        tk.Label(edit_row, text="画面", bg=Palette.BG_ALT, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left", anchor="n", pady=4)
        self.scene_edit = tk.Text(edit_row, height=2, wrap="word", bg=Palette.PANEL_ALT,
                                  fg=Palette.TEXT, insertbackground=Palette.TEXT,
                                  relief="flat", font=(FONT_UI, 9), padx=6, pady=4,
                                  highlightthickness=1, highlightbackground=Palette.BORDER,
                                  highlightcolor=Palette.BLOOD)
        self.scene_edit.pack(side="left", fill="x", expand=True, padx=6)
        tk.Label(edit_row, text="旁白", bg=Palette.BG_ALT, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left", anchor="n", pady=4)
        self.narration_edit = tk.Text(edit_row, height=2, wrap="word", bg=Palette.PANEL_ALT,
                                      fg=Palette.TEXT, insertbackground=Palette.TEXT,
                                      relief="flat", font=(FONT_UI, 9), padx=6, pady=4,
                                      width=22,
                                      highlightthickness=1, highlightbackground=Palette.BORDER,
                                      highlightcolor=Palette.BLOOD)
        self.narration_edit.pack(side="left", padx=(0, 6))
        tail = tk.Frame(edit_row, bg=Palette.BG_ALT)
        tail.pack(side="left", anchor="n")
        dur_row = tk.Frame(tail, bg=Palette.BG_ALT)
        dur_row.pack(anchor="w")
        self.duration_var = tk.StringVar(value="")
        tk.Entry(dur_row, textvariable=self.duration_var, width=5, bg=Palette.PANEL_ALT,
                 fg=Palette.TEXT, insertbackground=Palette.TEXT, relief="flat",
                 font=(FONT_MONO, 9), justify="right",
                 highlightthickness=1, highlightbackground=Palette.BORDER,
                 highlightcolor=Palette.BLOOD).pack(side="left")
        tk.Label(dur_row, text="秒", bg=Palette.BG_ALT, fg=Palette.TEXT_FAINT,
                 font=(FONT_UI, 8)).pack(side="left", padx=3)
        self._small_button(dur_row, "应用修改", self._apply_edit).pack(side="left", padx=2)
        btn_row = tk.Frame(tail, bg=Palette.BG_ALT)
        btn_row.pack(anchor="w", pady=(3, 0))
        self._small_button(btn_row, "在此后插入", self._insert_after).pack(side="left")
        self._small_button(btn_row, "删除此镜", self._delete_selected).pack(
            side="left", padx=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        actions = tk.Frame(parent, bg=Palette.BG_ALT)
        actions.pack(fill="x", padx=14, pady=(0, 12))
        self.import_btn = tk.Button(
            actions, text="⇩  导入时间轴（替换现有分镜）", command=lambda: self._import(True),
            bg=Palette.BLOOD, fg="#ffffff", activebackground=Palette.BLOOD_HOVER,
            activeforeground="#ffffff", relief="flat", bd=0, padx=14, pady=8,
            font=(FONT_UI, 9, "bold"), cursor="hand2")
        self.import_btn.pack(side="left")
        for text, cmd in (("追加到时间轴", lambda: self._import(False)),
                          ("保存脚本", self._save),
                          ("导出旁白 SRT", self._export_srt)):
            self._small_button(actions, text, cmd).pack(side="left", padx=6)

    # ==================================================================
    # 状态
    # ==================================================================
    def _on_count(self, _value=None):
        self.count_label.config(text=f"{int(self.count_var.get())} 镜")

    def refresh_key_label(self):
        cfg = ai_config.load_config()
        if cfg.get("api_key"):
            source = "环境变量" if cfg.get("_from_env") else "本地配置"
            self.key_label.config(
                text=f"✓ 已配置 {ai_config.mask_key(cfg['api_key'])}（{source}）\n"
                     f"模型：{cfg.get('model', ai_config.DEFAULT_MODEL)}",
                fg=Palette.SUCCESS)
        else:
            self.key_label.config(
                text="✗ 未配置 API Key。到 platform.deepseek.com 创建后填入「AI 设置」，"
                     "或设置环境变量 DEEPSEEK_API_KEY。",
                fg=Palette.AMBER)

    def set_busy(self, busy: bool, text: str = ""):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.gen_btn.config(state=state, text="生成中…（请稍候）" if busy else "✦  生成故事分镜")
        if busy:
            self.gen_status.config(text=text, fg=Palette.AMBER)
        self._refresh_actions()

    def show_error(self, text: str):
        self.set_busy(False)
        self.gen_status.config(text=text, fg=Palette.ERROR)

    # ==================================================================
    # 生成（V2.2：创意候选 → 选一个 → 完整五阶段）
    # ==================================================================
    def _form(self):
        return (self.keywords_text.get("1.0", "end").strip(),
                int(self.count_var.get()), self.style_var.get(),
                self.extra_var.get().strip())

    def _on_generate(self, concepts_only: bool = False, concept: dict | None = None):
        """concepts_only=True → 只出创意；concept 给定 → 直接按该创意写完整剧本。"""
        if self.busy:
            return
        keywords, count, style, extra = self._form()
        if concepts_only and self.concepts_cb:
            if not keywords:
                self.show_error("请先输入题材关键词。")
                return
            self.set_busy(True, "正在构思创意……")
            self.on_status("正在向 DeepSeek 请求 3 个故事创意……")
            try:
                concepts, log = self.concepts_cb(keywords, style, extra)
            except Exception as exc:  # noqa: BLE001 - 错误统一展示在面板
                self.show_error(str(exc))
                self.on_status("创意生成失败")
                return
            # 先重置状态再切视图：candidates 视图里按钮可用性按 busy 刷新
            self.last_log = list(log or [])
            self.set_busy(False)
            self.set_concepts(concepts, keywords=keywords)
            self._show_log(log)
            self.on_status(f"已生成 {len(concepts)} 个创意，请选一个")
            return
        if concept is not None and self.plan_cb:
            self.set_busy(True, f"正在按创意《{concept.get('title') or ''}》创作 {count} 个分镜……")
            self.on_status(f"正在创作：{concept.get('title') or ''}")
            try:
                story, log = self.plan_cb(keywords, style, extra, count, concept)
            except Exception as exc:  # noqa: BLE001
                self.show_error(str(exc))
                self.on_status("故事生成失败")
                return
            self.last_log = list(log or [])
            self.set_story(story, keywords=keywords)
            self.set_busy(False)
            self._show_log(log)
            self.on_status(f"故事已生成：{story.get('title', '')}")
            return
        if self.concepts_cb:
            self._on_generate(concepts_only=True)
            return
        # 没注入五阶段回调：退回 V2.1 一步式生成
        if not keywords:
            self.show_error("请先输入题材关键词。")
            return
        self.gen_status.config(text="", fg=Palette.AMBER)
        self.on_status(f"正在向 DeepSeek 请求 {count} 个分镜的故事……")
        try:
            story = self.generate_cb(keywords, count, style, extra)
        except Exception as exc:  # noqa: BLE001 - 错误统一展示在面板
            self.show_error(str(exc))
            self.on_status("故事生成失败")
            return
        self.set_story(story, keywords=keywords)
        self.set_busy(False)
        self.on_status(f"故事已生成：{story.get('title', '')}")

    def set_concepts(self, concepts: list[dict], keywords: str = "") -> None:
        self.concepts = [c for c in (concepts or []) if isinstance(c, dict)]
        self.concept_tree.delete(*self.concept_tree.get_children())
        for i, concept in enumerate(self.concepts):
            self.concept_tree.insert("", "end", iid=f"c{i}", values=(
                concept.get("title") or "未命名",
                concept.get("core_conflict") or "",
                concept.get("hook") or "",
                ENDING_LABELS.get(concept.get("ending_type") or "closed", "完整结局")))
        if self.concepts:
            self.concept_hint.config(
                text=f"为「{keywords or '当前题材'}」生成了 {len(self.concepts)} 个创意。"
                     "选一个（双击直接开始），再写完整剧本。")
            first = self.concept_tree.get_children()[0]
            self.concept_tree.selection_set(first)
            self.concept_tree.focus(first)
            self.concept_tree.bind("<Double-Button-1>", lambda e: self._use_concept())
        else:
            self.concept_hint.config(text="这次没有拿到合格创意，点「重新出创意」再试。")
        self._show_view("concepts")
        self._refresh_actions()

    def _selected_concept(self) -> dict | None:
        sel = self.concept_tree.selection()
        if not sel:
            return None
        try:
            return self.concepts[int(sel[0][1:])]
        except (ValueError, IndexError):
            return None

    def _on_concept_select(self, _event=None):
        self._refresh_actions()

    def _use_concept(self):
        concept = self._selected_concept()
        if concept is None:
            self.show_error("请先选一个创意。")
            return
        self._on_generate(concept=concept)

    def _show_view(self, name: str):
        """切换右侧视图：concepts（创意候选）/ shots（分镜表）。"""
        if name == "concepts":
            # 候选阶段还没有新故事：收起上一版的故事摘要，避免和候选混淆
            self.shot_frame.pack_forget()
            self.title_label.config(text="选择一个故事创意")
            self.logline_label.config(text="")
            self.meta_label.config(text="")
            self.score_label.config(text="")
            self.concept_frame.pack(fill="both", expand=True)
        elif name == "shots":
            self.concept_frame.pack_forget()
            self.shot_frame.pack(fill="both", expand=True)
        self._refresh_actions()

    def _refresh_actions(self):
        try:
            set_state = lambda w, on: w.config(state="normal" if on else "disabled")  # noqa: E731
            set_state(self.use_concept_btn,
                      not self.busy and self._selected_concept() is not None)
            set_state(self.import_btn,
                      not self.busy and bool(self.story and self.story.get("shots")))
            set_state(self.version_menu,
                      not self.busy and bool(self._restore_cb) and len(self.versions) > 1)
        except tk.TclError:       # 面板已销毁（测试拆窗口时）
            pass

    def set_restore_callback(self, callback):
        """版本恢复回调 callback(version_id)，由 main_window 注入。"""
        self._restore_cb = callback
        self._refresh_actions()

    def set_versions(self, versions: list[dict]) -> None:
        self.versions = [v for v in (versions or []) if isinstance(v, dict)]
        menu = self.version_menu["menu"]
        menu.delete(0, "end")
        if not self.versions:
            self.version_var.set("（暂无版本）")
            return
        labels = {}
        for v in self.versions:
            note = v.get("note") or ""
            label = f"{v.get('version_id')} · {note}" if note else str(v.get("version_id"))
            if v.get("official") is False:
                label += "（备份）"
            labels[label] = v
        self._version_by_label = labels
        for label in labels:
            menu.add_command(label=label, command=lambda lb=label: self.version_var.set(lb))
        active = next((v for v in self.versions
                       if v.get("version_id") == self._active_version()), None)
        if active:
            for label, v in labels.items():
                if v is active:
                    self.version_var.set(label)
                    break
        else:
            self.version_var.set(next(iter(labels)))
        self._refresh_actions()

    def _active_version(self) -> str:
        return str((self.story or {}).get("active_version") or "")

    def _restore_version(self):
        if not self._restore_cb:
            self.on_status("版本恢复只在打开项目后可用")
            return
        version = getattr(self, "_version_by_label", {}).get(self.version_var.get())
        if not version:
            self.show_error("请先选择一个版本。")
            return
        version_id = str(version.get("version_id") or "")
        if not version_id:
            return
        self._restore_cb(version_id)

    def _show_log(self, log) -> None:
        if log:
            self.last_log = list(log)
        if not getattr(self, "last_log", None):
            return
        tail = " → ".join(str(x) for x in self.last_log[-3:])
        self.gen_status.config(text=f"已完成：{tail}", fg=Palette.TEXT_FAINT)

    def apply_restored(self, entry: dict | None, story: dict | None,
                       note: str = "") -> None:
        """恢复版本后由 main_window 调用：刷新分镜表与版本列表。"""
        self.set_busy(False)
        if story:
            self.set_story(story, keywords=str(story.get("keywords") or ""))
        self.gen_status.config(text=note or "", fg=Palette.AMBER)
        self.on_status(note or "版本已恢复")

    def set_story(self, story: dict | None, keywords: str = ""):
        self.story = story
        if story:
            story.setdefault("keywords", keywords)
            # 没有审核结果时，用本地规则做一次评分（不联网），保证 UI 始终有质量分；
            # 审核通过的 story 已经带 quality，这里不会覆盖。
            if not story.get("quality"):
                try:
                    from modules import story_quality
                    report = story_quality.local_review(ss.upgrade_story(story)[0])
                    story["quality"] = ss.normalize_quality(report) or {}
                except Exception:  # noqa: BLE001 - 评分只是辅助信息
                    pass
            # 打开的故事若时长与目标对不上（旧数据 / 外部改过镜头），按镜头列表重算一次
            repace_story(story)
        self._refresh_result()

    def _refresh_result(self):
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        story = self.story
        if not story or not story.get("shots"):
            self.title_label.config(text="还没有生成故事")
            self.logline_label.config(text="")
            self.meta_label.config(text="")
            self.score_label.config(text="")
            self._clear_editor()
            self.set_versions(story.get("versions") if story else [])
            self._refresh_actions()
            return
        self.title_label.config(text=story.get("title") or "未命名故事")
        self.logline_label.config(text=story.get("logline") or "")
        total = sum(float(s.get("duration", 0)) for s in story["shots"])
        meta = f"{len(story['shots'])} 镜 · {_fmt(total)}"
        if story.get("model"):
            meta += f" · {story['model']}"
        self.meta_label.config(text=meta)
        self.score_label.config(text=score_text(story))
        for i, shot in enumerate(story["shots"]):
            iid = f"row{i}"
            self._rows[iid] = shot
            scene = (shot.get("scene") or "").replace("\n", " ")
            if len(scene) > SCENE_PREVIEW_CHARS:
                scene = scene[:SCENE_PREVIEW_CHARS] + "…"
            self.tree.insert("", "end", iid=iid, values=(
                i + 1, scene,
                (shot.get("narration") or "").replace("\n", " "),
                f"{float(shot.get('duration', 0)):.1f}s"))
        self._show_view("shots")
        self._clear_editor()
        self.set_versions(story.get("versions") or [])
        if self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
        self._refresh_actions()

    # ==================================================================
    # 编辑单条分镜
    # ==================================================================
    def _selected_shot(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._rows.get(sel[0])

    def _on_select(self, _event=None):
        shot = self._selected_shot()
        if shot is None:
            self._clear_editor()
            return
        self.scene_edit.delete("1.0", "end")
        self.scene_edit.insert("1.0", shot.get("scene", ""))
        self.narration_edit.delete("1.0", "end")
        self.narration_edit.insert("1.0", shot.get("narration", ""))
        self.duration_var.set(f"{float(shot.get('duration', 0)):.1f}")

    def _clear_editor(self):
        for widget in (self.scene_edit, self.narration_edit):
            widget.delete("1.0", "end")
        self.duration_var.set("")

    def _apply_edit(self):
        shot = self._selected_shot()
        if shot is None or not self.story:
            self.show_error("请先在右侧表格中选择一个分镜。")
            return
        shot["scene"] = self.scene_edit.get("1.0", "end").strip()
        shot["narration"] = self.narration_edit.get("1.0", "end").strip()
        try:
            shot["duration"] = round(max(0.5, float(self.duration_var.get().rstrip("s"))), 2)
        except ValueError:
            self.show_error("时长必须是数字，例如 3.5")
            return
        # 单镜改时长后按当前镜头列表重新分配，保证总时长仍等于目标
        repace_story(self.story)
        self.gen_status.config(text="")
        self._refresh_result()

    def _insert_after(self):
        if not self.story:
            return
        sel = self.tree.selection()
        index = self.tree.index(sel[0]) if sel else len(self.story["shots"]) - 1
        self.story["shots"].insert(index + 1, {
            "index": 0, "scene": "（新分镜的画面描述）", "narration": "", "duration": 3.5})
        self._renumber()
        repace_story(self.story)
        self._refresh_result()
        children = self.tree.get_children()
        if index + 1 < len(children):
            self.tree.selection_set(children[index + 1])

    def _delete_selected(self):
        shot = self._selected_shot()
        if not self.story or shot is None:
            return
        if len(self.story["shots"]) <= 1:
            self.show_error("至少保留一个分镜。")
            return
        self.story["shots"].remove(shot)
        self._renumber()
        repace_story(self.story)
        self._refresh_result()

    def _renumber(self):
        for i, shot in enumerate(self.story["shots"]):
            shot["index"] = i + 1

    def _on_tree_double(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.on_reveal_shot(self.tree.index(sel[0]))

    # ==================================================================
    # 动作
    # ==================================================================
    def _import(self, replace: bool):
        if not self.story or not self.story.get("shots"):
            self.show_error("还没有可导入的分镜，请先生成故事。")
            return
        self.on_import(self.story, replace)

    def _save(self):
        if not self.story:
            self.show_error("还没有可保存的故事。")
            return
        self.on_save(self.story)

    def _export_srt(self):
        if not self.story:
            self.show_error("还没有可导出的故事。")
            return
        self.on_export_srt(self.story)


def _fmt(seconds: float) -> str:
    m, s = divmod(float(seconds), 60)
    return f"{int(m)} 分 {s:04.1f} 秒" if m else f"{s:.1f} 秒"


def score_text(story: dict | None) -> str:
    """质量审核摘要：总分 / 等级 / 逐项分 / 否决项。没有审核结果就返回空串。"""
    if not isinstance(story, dict):
        return ""
    quality = story.get("quality")
    if not isinstance(quality, dict) or not quality:
        return ""
    try:
        score = float(quality.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    grade = GRADE_LABELS.get(quality.get("grade"), quality.get("grade") or "")
    parts = [f"质量 {score:.0f} 分（{grade}）"]
    scores = quality.get("scores") or {}
    if isinstance(scores, dict) and scores:
        details = []
        for key, label, weight in SCORE_LABELS:
            value = scores.get(key)
            if value is None:
                continue
            try:
                details.append(f"{label} {float(value):.0f}/{weight}")
            except (TypeError, ValueError):
                continue
        if details:
            parts.append("  ".join(details))
    vetoes = [v for v in (quality.get("vetoes") or []) if isinstance(v, dict)]
    for veto in vetoes:
        message = (veto.get("message")
                   or ss.VETO_CODES.get(veto.get("code") or "") or "硬性否决")
        parts.append(f"⚠ {message}")
    return "\n".join(parts)
