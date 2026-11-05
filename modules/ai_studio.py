"""「AI 制作」页签：把分镜批量出图 / 批量配音，然后一键出片。

职责边界（与 story_panel 一致）
------------------------------
* 只负责界面与进度展示；真正的网络调用、文件落盘由注入的回调完成，
  这样面板可以在不联网、没有 API Key 的情况下被测试。
* 所有耗时任务都由 main_window 放到后台线程，通过 `post(kind, text)` 回报进度：
      post("ai_progress", "画面 3/8 …")
      post("ai_done", "完成")
      post("ai_error", "错误信息")
  面板只消费这些消息，不直接操作线程。

回调
----
  on_images(start, count, force) -> None   批量出图（start 为起始镜头序号，从 0 起）
  on_voices(force) -> None                 批量配音
  on_build_voice_track() -> None           把配音片段拼成旁白音轨
  on_render() -> None                      渲染成片
  on_clear_voices() -> None                清除配音
  on_rebalance() -> None                   按剧本画面时长重排节奏
  on_open_settings() -> None               打开 AI 设置
  on_open_output() -> None                 打开输出目录
  on_status(text) -> None                  状态栏提示
"""
import tkinter as tk

from theme import Palette, FONT_UI, FONT_MONO
from modules import ai_config, sf_config


class AIStudioPanel(tk.Frame):
    def __init__(self, master, on_images=None, on_voices=None,
                 on_build_voice_track=None, on_render=None, on_clear_voices=None,
                 on_rebalance=None,
                 on_open_settings=None, on_open_output=None, on_status=None):
        super().__init__(master, bg=Palette.BG)
        self.on_images = on_images or (lambda **kw: None)
        self.on_voices = on_voices or (lambda **kw: None)
        self.on_build_voice_track = on_build_voice_track or (lambda: None)
        self.on_render = on_render or (lambda: None)
        self.on_clear_voices = on_clear_voices or (lambda: None)
        self.on_rebalance = on_rebalance or (lambda: None)
        self.on_open_settings = on_open_settings or (lambda: None)
        self.on_open_output = on_open_output or (lambda: None)
        self.on_status = on_status or (lambda text: None)

        self.busy = False
        self._build()

    # ==================================================================
    # 构建
    # ==================================================================
    def _build(self):
        outer = tk.Frame(self, bg=Palette.BG)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        left = tk.Frame(outer, bg=Palette.PANEL)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        left.configure(width=330)
        self._build_controls(left)

        right = tk.Frame(outer, bg=Palette.PANEL)
        right.pack(side="left", fill="both", expand=True)
        self._build_summary(right)

    def _section(self, parent, text, top=(14, 6)):
        tk.Label(parent, text=text, bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold"), anchor="w").pack(fill="x", pady=top)

    def _button(self, parent, text, cmd, accent=False, small=False):
        btn = tk.Button(parent, text=text, command=cmd,
                        bg=Palette.BLOOD if accent else Palette.PANEL_ALT,
                        fg="#ffffff" if accent else Palette.TEXT,
                        activebackground=Palette.BLOOD_HOVER if accent else Palette.PANEL_HOVER,
                        activeforeground="#ffffff" if accent else Palette.TEXT,
                        relief="flat", bd=0, padx=16 if not small else 10,
                        pady=8 if not small else 4,
                        font=(FONT_UI, 9, "bold" if accent else "normal"),
                        cursor="hand2")
        if not accent:
            btn.bind("<Enter>", lambda e: btn.config(bg=Palette.PANEL_HOVER))
            btn.bind("<Leave>", lambda e: btn.config(bg=Palette.PANEL_ALT))
        return btn

    def _build_controls(self, parent):
        inner = tk.Frame(parent, bg=Palette.PANEL)
        inner.pack(fill="both", expand=True, padx=16, pady=14)

        tk.Label(inner, text="AI 制作流水线", bg=Palette.PANEL, fg=Palette.BONE,
                 font=(FONT_UI, 13, "bold"), anchor="w").pack(fill="x")
        tk.Label(inner, text="依次补齐画面 → 配音 → 成片。已有画面的镜头跳过。",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8),
                 anchor="w", wraplength=290, justify="left").pack(fill="x", pady=(2, 6))

        # -- 出图 ------------------------------------------------------
        self._section(inner, "① 画面", top=(10, 4))
        row = tk.Frame(inner, bg=Palette.PANEL)
        row.pack(fill="x")
        tk.Label(row, text="出图模型", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        self.model_var = tk.StringVar(value=sf_config.DEFAULT_IMAGE_MODEL)
        self.model_label = tk.Label(row, text="", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                                    font=(FONT_UI, 8))
        self.model_label.pack(side="right")
        menu = tk.OptionMenu(inner, self.model_var,
                             *[m[0] for m in sf_config.IMAGE_MODELS], command=self._on_model)
        menu.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat", bd=0,
                    activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                    highlightthickness=0, font=(FONT_MONO, 8), anchor="w")
        menu["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                            activebackground=Palette.BLOOD, activeforeground="#ffffff")
        menu.pack(fill="x", pady=(2, 4))

        self.force_images = tk.BooleanVar(value=False)
        tk.Checkbutton(inner, text="重新生成已有 AI 画面", variable=self.force_images,
                       bg=Palette.PANEL, fg=Palette.TEXT_DIM, selectcolor=Palette.PANEL_ALT,
                       activebackground=Palette.PANEL, activeforeground=Palette.TEXT,
                       font=(FONT_UI, 8), bd=0, highlightthickness=0,
                       anchor="w").pack(fill="x", pady=(0, 4))
        self._button(inner, "✦  生成全部画面", self._on_images).pack(fill="x")

        # -- 配音 ------------------------------------------------------
        self._section(inner, "② 配音")
        voice_row = tk.Frame(inner, bg=Palette.PANEL)
        voice_row.pack(fill="x")
        tk.Label(voice_row, text="音色", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        self.voice_var = tk.StringVar(value=sf_config.DEFAULT_VOICE)
        voices = [f"{name} · {desc}" for name, desc in sf_config.VOICES]
        voice_menu = tk.OptionMenu(voice_row, self.voice_var, *voices)
        voice_menu.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat", bd=0,
                          activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                          highlightthickness=0, font=(FONT_UI, 9), width=16, anchor="w")
        voice_menu["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                                  activebackground=Palette.BLOOD, activeforeground="#ffffff")
        voice_menu.pack(side="right")

        speed_row = tk.Frame(inner, bg=Palette.PANEL)
        speed_row.pack(fill="x", pady=(4, 0))
        tk.Label(speed_row, text="语速", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        self.speed_var = tk.StringVar(value=sf_config.speed_label(
            sf_config.load_config().get("voice_speed", sf_config.DEFAULT_VOICE_SPEED)))
        speeds = [sf_config.speed_label(v) for v, _name in sf_config.VOICE_SPEEDS]
        speed_menu = tk.OptionMenu(speed_row, self.speed_var, *speeds)
        speed_menu.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat", bd=0,
                          activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                          highlightthickness=0, font=(FONT_UI, 9), width=16, anchor="w")
        speed_menu["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                                  activebackground=Palette.BLOOD, activeforeground="#ffffff")
        speed_menu.pack(side="right")

        self.force_voices = tk.BooleanVar(value=False)
        tk.Checkbutton(inner, text="重新生成已有配音", variable=self.force_voices,
                       bg=Palette.PANEL, fg=Palette.TEXT_DIM, selectcolor=Palette.PANEL_ALT,
                       activebackground=Palette.PANEL, activeforeground=Palette.TEXT,
                       font=(FONT_UI, 8), bd=0, highlightthickness=0,
                       anchor="w").pack(fill="x", pady=(4, 4))
        self.auto_fit = tk.BooleanVar(value=True)
        tk.Checkbutton(inner, text="自动按配音长度对齐镜头时长", variable=self.auto_fit,
                       bg=Palette.PANEL, fg=Palette.TEXT, selectcolor=Palette.PANEL_ALT,
                       activebackground=Palette.PANEL, activeforeground=Palette.TEXT,
                       font=(FONT_UI, 8), bd=0, highlightthickness=0,
                       anchor="w").pack(fill="x", pady=(0, 4))
        self._button(inner, "♪  生成全部旁白配音", self._on_voices).pack(fill="x")
        sub = tk.Frame(inner, bg=Palette.PANEL)
        sub.pack(fill="x", pady=(4, 0))
        self._button(sub, "拼成旁白音轨", self.on_build_voice_track,
                     small=True).pack(side="left")
        self._button(sub, "清除配音", self.on_clear_voices, small=True).pack(
            side="left", padx=6)
        self._button(inner, "⏱  节奏重排（按剧本画面时长）", self.on_rebalance,
                     small=True).pack(fill="x", pady=(4, 0))

        # -- 成片 ------------------------------------------------------
        self._section(inner, "③ 成片")
        self._button(inner, "▶  直接出片（不配音）", self.on_render, accent=True).pack(fill="x")
        self._button(inner, "打开输出目录", self.on_open_output, small=True).pack(
            side="left", pady=(8, 0))

        tk.Frame(inner, bg=Palette.PANEL).pack(fill="both", expand=True)

        self._section(inner, "API 状态")
        self.key_label = tk.Label(inner, text="", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                                  font=(FONT_UI, 8), anchor="w", wraplength=290,
                                  justify="left")
        self.key_label.pack(fill="x")
        btn_row = tk.Frame(inner, bg=Palette.PANEL)
        btn_row.pack(fill="x", pady=(4, 0))
        self._button(btn_row, "AI 设置…", self.on_open_settings, small=True).pack(side="left")
        self._button(btn_row, "刷新状态", self.refresh_key_label, small=True).pack(
            side="left", padx=6)

        self.status_label = tk.Label(inner, text="", bg=Palette.PANEL, fg=Palette.AMBER,
                                     font=(FONT_UI, 9), anchor="w", wraplength=290,
                                     justify="left")
        self.status_label.pack(fill="x", pady=(10, 0))
        self.refresh_key_label()

    def _build_summary(self, parent):
        head = tk.Frame(parent, bg=Palette.PANEL)
        head.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(head, text="制作进度", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold")).pack(side="left")
        self.summary_label = tk.Label(head, text="", bg=Palette.PANEL,
                                      fg=Palette.TEXT_FAINT, font=(FONT_MONO, 9))
        self.summary_label.pack(side="right")

        self.summary = tk.Text(parent, height=10, wrap="word", bg=Palette.PANEL_ALT,
                               fg=Palette.TEXT, insertbackground=Palette.TEXT,
                               relief="flat", font=(FONT_MONO, 9), padx=10, pady=8,
                               highlightthickness=1, highlightbackground=Palette.BORDER,
                               state="disabled")
        self.summary.pack(fill="x", padx=16, pady=(0, 10))

        tk.Label(parent, text="配音时间轴预览", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold"), anchor="w").pack(fill="x", padx=16)
        tk.Frame(parent, bg=Palette.BORDER, height=1).pack(fill="x", padx=16, pady=4)
        self.voice_canvas = tk.Canvas(parent, bg=Palette.PANEL, highlightthickness=0,
                                      height=260)
        self.voice_canvas.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.voice_canvas.bind("<Configure>", lambda e: self._draw_voice_rows())

        self.hint = tk.Label(
            parent,
            text="· 出图按「画面描述」生成，每镜约 5~15 秒；Z-Image 出图更快，Kolors 免费\n"
                 "· 配音按「旁白」逐镜生成；勾选自动对齐时，镜头时长保持剧本的画面节奏，\n"
                 "   旁白塞不下才自动延长（界面会提示哪几镜偏长）\n"
                 "· 「拼成旁白音轨」后渲染时自动使用；手动导入的旁白音频优先级更高",
            bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8),
            anchor="w", justify="left")
        self.hint.pack(fill="x", padx=16, pady=(0, 12))

        self._rows: list[dict] = []

    # ==================================================================
    # 状态
    # ==================================================================
    def _on_model(self, _value=None):
        self._sync_model_hint()

    def _sync_model_hint(self):
        current = self.model_var.get()
        for model, note in sf_config.IMAGE_MODELS:
            if current.startswith(model) or model == current:
                self.model_label.config(text=note)
                return
        self.model_label.config(text="")

    def model_id(self) -> str:
        """OptionMenu 的值可能是 '模型 · 说明'，这里取出纯模型 ID。"""
        value = self.model_var.get()
        for model, _ in sf_config.IMAGE_MODELS:
            if value.startswith(model):
                return model
        return sf_config.DEFAULT_IMAGE_MODEL

    def voice_id(self) -> str:
        return self.voice_var.get().split(" · ")[0].strip()

    def voice_speed(self) -> float:
        return sf_config.parse_speed(self.speed_var.get())

    def sync_voice_settings(self):
        """从本地配置同步音色与语速（在「AI 设置」里改完后调用）。"""
        cfg = sf_config.load_config()
        self.speed_var.set(sf_config.speed_label(
            cfg.get("voice_speed", sf_config.DEFAULT_VOICE_SPEED)))
        voice = cfg.get("voice", sf_config.DEFAULT_VOICE)
        if not self.voice_var.get().startswith(voice + " "):
            self.voice_var.set(voice)

    def refresh_key_label(self):
        sf = sf_config.load_config()
        ds = ai_config.load_config()
        lines = []
        if sf.get("api_key"):
            source = "环境变量" if sf.get("_from_env") else "本地配置"
            lines.append(f"✓ 硅基流动 {ai_config.mask_key(sf['api_key'])}（{source}）")
        else:
            lines.append("✗ 未配置硅基流动 Key（出图 / 配音需要）")
        if ds.get("api_key"):
            lines.append("✓ DeepSeek 已配置（故事生成）")
        else:
            lines.append("· DeepSeek 未配置（「故事」页签需要，可选）")
        self.key_label.config(
            text="\n".join(lines),
            fg=Palette.SUCCESS if sf.get("api_key") else Palette.AMBER)

    def set_busy(self, busy: bool, text: str = ""):
        self.busy = busy
        self.status_label.config(text=text, fg=Palette.AMBER if busy else Palette.SUCCESS)

    def set_status(self, text: str, error: bool = False):
        self.status_label.config(text=text, fg=Palette.ERROR if error else Palette.TEXT_DIM)

    # ==================================================================
    # 回调
    # ==================================================================
    def _on_images(self):
        if self.busy:
            return
        self.on_images(force=self.force_images.get())

    def _on_voices(self):
        if self.busy:
            return
        self.on_voices(force=self.force_voices.get())

    # ==================================================================
    # 数据展示
    # ==================================================================
    def set_shots(self, shots: list[dict], project_dir=None):
        self._rows = list(shots or [])
        self._project_dir = project_dir
        total = len(self._rows)
        with_image = sum(1 for s in self._rows if s.get("image"))
        ai_image = sum(1 for s in self._rows if s.get("ai_image"))
        with_voice = sum(1 for s in self._rows if s.get("voice"))
        narration = any((s.get("narration") or "").strip() for s in self._rows)
        self.summary_label.config(
            text=f"{total} 镜 · 画面 {with_image}/{total}（AI {ai_image}）"
                 f" · 配音 {with_voice}/{total}")
        lines = []
        for i, shot in enumerate(self._rows):
            mark = "✓" if shot.get("image") else "·"
            voice = "✓" if shot.get("voice") else ("·" if narration else "—")
            lines.append(f"{mark} #{i + 1:02d}  {_short(shot.get('scene') or '（无画面描述）', 22)}"
                         f"   画面{f' AI' if shot.get('ai_image') else ''}   配音 {voice}")
        self._set_text("\n".join(lines) if lines else "时间轴上还没有镜头。")
        self._draw_voice_rows()

    def _set_text(self, text: str):
        self.summary.config(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", text)
        self.summary.config(state="disabled")

    def _draw_voice_rows(self):
        c = self.voice_canvas
        c.delete("all")
        width = max(60, c.winfo_width() - 20)
        if not self._rows:
            c.create_text(width // 2, 40, text="导入故事并配音后，这里显示每镜的配音长度",
                          fill=Palette.TEXT_FAINT, font=(FONT_UI, 9))
            return
        total = sum(float(s.get("duration", 0)) for s in self._rows) or 1.0
        scale = width / total
        y = 10
        for i, shot in enumerate(self._rows):
            dur = float(shot.get("duration", 0))
            bar_w = max(2, int(dur * scale))
            c.create_rectangle(10, y, 10 + bar_w, y + 18,
                               fill=Palette.TRACK_ALT, outline=Palette.BORDER)
            voice = shot.get("voice")
            if voice:
                voice_ms = shot.get("voice_ms") or 0
                if not voice_ms:
                    voice_ms = int(dur * 1000 * 0.8)
                ratio = min(1.0, voice_ms / 1000 / max(dur, 0.01))
                c.create_rectangle(10, y, 10 + max(2, int(bar_w * ratio)), y + 18,
                                   fill=Palette.SUCCESS, outline="")
                if voice_ms / 1000 > dur + 0.05:
                    # 画面优先下对齐后仍超长的镜（上限 8s 截止）才显示
                    c.create_text(12 + bar_w, y + 9, anchor="w", fill=Palette.AMBER,
                                  font=(FONT_UI, 8), text="配音超长·建议精简旁白")
            c.create_text(10 + bar_w + 6, y + 9, anchor="w", fill=Palette.TEXT_DIM,
                          font=(FONT_MONO, 8),
                          text=f"#{i + 1} {dur:.1f}s" + ("" if voice else "  未配音"))
            y += 24
            if y > int(c.winfo_height()) - 20:
                break


def _short(text: str, limit: int = 24) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")
