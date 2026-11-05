"""AI 设置对话框：填写 / 测试 / 保存两路 API Key。

* DeepSeek（故事生成）       → ~/.ai_horror_studio/ai.json
* 硅基流动（出图 + 配音）    → ~/.ai_horror_studio/siliconflow.json

两个 Key 分开保存，互不覆盖；界面只显示掩码。
“测试连接”会在后台线程发极小请求，结果通过队列回到界面。
"""
import queue
import threading
import tkinter as tk

from theme import Palette, FONT_UI, FONT_MONO
from modules import ai_config, sf_config
from modules.story_engine import StoryEngine
from modules.voice_engine import VoiceEngine

# 配音语气预设：auto = 按剧本题材自动选（story_engine.infer_style）
VOICE_STYLE_CHOICES = {
    "auto": "自动（按题材）",
    "default": "通用恐怖旁白",
    "folk": "民俗恐怖",
    "urban": "都市怪谈",
    "cosmic": "克苏鲁",
    "psych": "心理惊悚",
}
_VOICE_STYLE_BY_LABEL = {v: k for k, v in VOICE_STYLE_CHOICES.items()}


class AISettingsDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("AI 设置")
        self.configure(bg=Palette.PANEL)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.result = None
        self._queue: queue.Queue = queue.Queue()
        self._testing = False
        self._build()
        self._load()
        self._poll()
        self.grab_set()
        self.focus_force()

    # ------------------------------------------------------------------
    def _build(self):
        body = tk.Frame(self, bg=Palette.PANEL)
        body.pack(fill="both", expand=True, padx=22, pady=18)

        # -- DeepSeek --------------------------------------------------
        self._heading(body, "① DeepSeek · 故事生成", top=(0, 2))
        tk.Label(body, text="获取地址：platform.deepseek.com → API keys",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8),
                 anchor="w").pack(fill="x", pady=(0, 4))
        self.ds_key_var, self.ds_entry = self._key_row(body)
        self.ds_show = tk.BooleanVar(value=False)
        self._show_check(body, self.ds_show, self.ds_entry, "显示 DeepSeek Key")
        self.ds_env = tk.Label(body, text="", bg=Palette.PANEL, fg=Palette.AMBER,
                               font=(FONT_UI, 8), anchor="w", justify="left",
                               wraplength=460)
        self.ds_env.pack(fill="x")
        model_row = tk.Frame(body, bg=Palette.PANEL)
        model_row.pack(fill="x", pady=(6, 0))
        tk.Label(model_row, text="模型", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        self.ds_model_var = tk.StringVar(value=ai_config.DEFAULT_MODEL)
        self._option(model_row, self.ds_model_var, ai_config.AVAILABLE_MODELS,
                     width=18).pack(side="right")
        self.ds_status = self._status_label(body)
        self._button(body, "测试 DeepSeek", lambda: self._test("deepseek")).pack(anchor="w")

        self._divider(body)

        # -- 硅基流动 --------------------------------------------------
        self._heading(body, "② 硅基流动 · AI 出图 + AI 配音", top=(6, 2))
        tk.Label(body, text="获取地址：cloud.siliconflow.cn → API 密钥",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8),
                 anchor="w").pack(fill="x", pady=(0, 4))
        self.sf_key_var, self.sf_entry = self._key_row(body)
        self.sf_show = tk.BooleanVar(value=False)
        self._show_check(body, self.sf_show, self.sf_entry, "显示硅基流动 Key")
        self.sf_env = tk.Label(body, text="", bg=Palette.PANEL, fg=Palette.AMBER,
                               font=(FONT_UI, 8), anchor="w", justify="left",
                               wraplength=460)
        self.sf_env.pack(fill="x")

        img_row = tk.Frame(body, bg=Palette.PANEL)
        img_row.pack(fill="x", pady=(6, 0))
        tk.Label(img_row, text="出图模型", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        self.img_model_var = tk.StringVar(
            value=dict((m, f"{m} · {d}") for m, d in sf_config.IMAGE_MODELS)
            .get(sf_config.DEFAULT_IMAGE_MODEL, sf_config.DEFAULT_IMAGE_MODEL))
        self._option(img_row, self.img_model_var,
                     [f"{m} · {d}" for m, d in sf_config.IMAGE_MODELS],
                     width=34).pack(side="right")

        voice_row = tk.Frame(body, bg=Palette.PANEL)
        voice_row.pack(fill="x", pady=(4, 0))
        tk.Label(voice_row, text="配音音色", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        self.voice_var = tk.StringVar(value=sf_config.DEFAULT_VOICE)
        self._option(voice_row, self.voice_var,
                     [f"{n} · {d}" for n, d in sf_config.VOICES], width=18).pack(side="right")

        speed_row = tk.Frame(body, bg=Palette.PANEL)
        speed_row.pack(fill="x", pady=(4, 0))
        tk.Label(speed_row, text="配音语速", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        self.speed_var = tk.StringVar(value=sf_config.speed_label(sf_config.DEFAULT_VOICE_SPEED))
        self._option(speed_row, self.speed_var,
                     [sf_config.speed_label(v) for v, _ in sf_config.VOICE_SPEEDS],
                     width=18).pack(side="right")

        style_row = tk.Frame(body, bg=Palette.PANEL)
        style_row.pack(fill="x", pady=(4, 0))
        tk.Label(style_row, text="配音语气", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left")
        self.voice_style_var = tk.StringVar(value=VOICE_STYLE_CHOICES["auto"])
        self._option(style_row, self.voice_style_var,
                     list(VOICE_STYLE_CHOICES.values()), width=18).pack(side="right")

        self.sf_status = self._status_label(body)
        self._button(body, "测试硅基流动（出图 + 配音）",
                     lambda: self._test("siliconflow")).pack(anchor="w")

        self._divider(body)

        row = tk.Frame(body, bg=Palette.PANEL)
        row.pack(fill="x")
        self._button(row, "取消", self.destroy, small=True).pack(side="right")
        self._button(row, "保存", self._save, accent=True).pack(side="right", padx=6)
        tk.Label(row, text="Key 保存在本机用户目录，不会写入项目文件。",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8)).pack(side="left")

    # -- 小部件 ----------------------------------------------------------
    def _heading(self, parent, text, top=(12, 4)):
        tk.Label(parent, text=text, bg=Palette.PANEL, fg=Palette.BONE,
                 font=(FONT_UI, 11, "bold"), anchor="w").pack(fill="x", pady=top)

    def _key_row(self, parent):
        var = tk.StringVar()
        entry = tk.Entry(parent, textvariable=var, width=58, show="•",
                         bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                         insertbackground=Palette.TEXT, relief="flat",
                         font=(FONT_MONO, 9), highlightthickness=1,
                         highlightbackground=Palette.BORDER,
                         highlightcolor=Palette.BLOOD)
        entry.pack(fill="x", ipady=4, pady=(0, 3))
        return var, entry

    def _show_check(self, parent, var, entry, text):
        tk.Checkbutton(parent, text=text, variable=var,
                       command=lambda v=var, e=entry: e.config(
                           show="" if v.get() else "•"),
                       bg=Palette.PANEL, fg=Palette.TEXT_DIM, selectcolor=Palette.PANEL_ALT,
                       activebackground=Palette.PANEL, activeforeground=Palette.TEXT,
                       font=(FONT_UI, 8), bd=0, highlightthickness=0).pack(anchor="w")

    def _option(self, parent, var, values, width=18):
        menu = tk.OptionMenu(parent, var, *values)
        menu.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat", bd=0,
                    activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                    highlightthickness=0, font=(FONT_UI, 9), anchor="w", width=width)
        menu["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                            activebackground=Palette.BLOOD, activeforeground="#ffffff")
        return menu

    def _status_label(self, parent):
        label = tk.Label(parent, text="", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                         font=(FONT_UI, 8), wraplength=470, justify="left", anchor="w")
        label.pack(fill="x", pady=(4, 4))
        return label

    def _divider(self, parent):
        tk.Frame(parent, bg=Palette.BORDER, height=1).pack(fill="x", pady=12)

    def _button(self, parent, text, cmd, accent=False, small=False):
        return tk.Button(parent, text=text, command=cmd,
                         bg=Palette.BLOOD if accent else Palette.PANEL_ALT,
                         fg="#ffffff" if accent else Palette.TEXT,
                         activebackground=Palette.BLOOD_HOVER if accent else Palette.PANEL_HOVER,
                         activeforeground="#ffffff" if accent else Palette.TEXT,
                         relief="flat", bd=0, padx=16 if not small else 10,
                         pady=6 if not small else 4,
                         font=(FONT_UI, 9, "bold" if accent else "normal"), cursor="hand2")

    # ------------------------------------------------------------------
    def _load(self):
        ds = ai_config.load_config()
        self.ds_key_var.set(ds.get("api_key", ""))
        self.ds_model_var.set(ds.get("model", ai_config.DEFAULT_MODEL))
        if ds.get("_from_env"):
            self.ds_env.config(text=f"⚠ 检测到环境变量 {ai_config.ENV_KEY}，"
                                    f"它优先于这里填写的内容。")

        sf = sf_config.load_config()
        self.sf_key_var.set(sf.get("api_key", ""))
        model = sf.get("image_model", sf_config.DEFAULT_IMAGE_MODEL)
        label = next((f"{m} · {d}" for m, d in sf_config.IMAGE_MODELS if m == model), model)
        self.img_model_var.set(label)
        self.voice_var.set(sf.get("voice", sf_config.DEFAULT_VOICE))
        self.speed_var.set(sf_config.speed_label(
            sf.get("voice_speed", sf_config.DEFAULT_VOICE_SPEED)))
        self.voice_style_var.set(VOICE_STYLE_CHOICES.get(
            sf.get("voice_style") or "auto", VOICE_STYLE_CHOICES["auto"]))
        if sf.get("_from_env"):
            self.sf_env.config(text=f"⚠ 检测到环境变量 {sf_config.ENV_KEY}，"
                                    f"它优先于这里填写的内容。")

    def _deepseek_config(self) -> dict:
        return {"api_key": self.ds_key_var.get().strip(),
                "base_url": ai_config.DEFAULT_BASE_URL,
                "model": self.ds_model_var.get()}

    def _siliconflow_config(self) -> dict:
        label = self.img_model_var.get()
        model = next((m for m, _ in sf_config.IMAGE_MODELS if label.startswith(m)),
                     sf_config.DEFAULT_IMAGE_MODEL)
        return {"api_key": self.sf_key_var.get().strip(),
                "image_model": model,
                "voice": self.voice_var.get().split(" · ")[0].strip(),
                "voice_speed": sf_config.parse_speed(self.speed_var.get()),
                "voice_style": _VOICE_STYLE_BY_LABEL.get(self.voice_style_var.get(),
                                                         "auto")}

    def _save(self):
        try:
            if self._deepseek_config()["api_key"]:
                ai_config.save_config(**self._deepseek_config())
            sf_cfg = self._siliconflow_config()
            if sf_cfg["api_key"] or sf_config.CONFIG_FILE.exists():
                sf_config.save_config(**sf_cfg)
        except OSError as exc:
            self.sf_status.config(text=f"保存失败：{exc}", fg=Palette.ERROR)
            return
        self.result = {"deepseek": self._deepseek_config(),
                       "siliconflow": sf_cfg}
        self.destroy()

    # ------------------------------------------------------------------
    def _test(self, which: str):
        if self._testing:
            return
        if which == "deepseek":
            cfg = self._deepseek_config()
            if not cfg["api_key"]:
                self.ds_status.config(text="请先填写 DeepSeek API Key。", fg=Palette.ERROR)
                return
            self.ds_status.config(text="正在连接 DeepSeek…", fg=Palette.AMBER)

            def worker():
                try:
                    msg = StoryEngine(config=cfg, timeout=30).test_connection()
                    self._queue.put(("ok", "deepseek", msg))
                except Exception as exc:  # noqa: BLE001
                    self._queue.put(("err", "deepseek", str(exc)))
        else:
            cfg = self._siliconflow_config()
            if not cfg["api_key"]:
                self.sf_status.config(text="请先填写硅基流动 API Key。", fg=Palette.ERROR)
                return
            self.sf_status.config(text="正在测试出图与配音（会产生极少量调用）…",
                                  fg=Palette.AMBER)

            def worker():
                try:
                    from modules.image_engine import ImageEngine
                    engine = ImageEngine(config=cfg, timeout=60)
                    urls = engine.generate("a dark corridor, horror film still",
                                           size="1024x1024", steps=4)
                    voice_msg = VoiceEngine(config=cfg, timeout=60).test_connection()
                    self._queue.put(("ok", "siliconflow",
                                     f"出图 OK（返回 {len(urls)} 张）；{voice_msg}"))
                except Exception as exc:  # noqa: BLE001
                    self._queue.put(("err", "siliconflow", str(exc)))

        self._testing = True
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            kind, which, message = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return
        self._testing = False
        label = self.ds_status if which == "deepseek" else self.sf_status
        label.config(text=message, fg=Palette.SUCCESS if kind == "ok" else Palette.ERROR)
        self.after(100, self._poll)
