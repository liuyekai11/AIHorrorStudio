"""预览面板：按播放头时间显示当前镜头画面 + 字幕叠加，提供播放控制。

预览是近似效果（Pillow/Tk 合成），最终成片以 FFmpeg 渲染为准。
"""
import tkinter as tk

from theme import Palette, FONT_UI, FONT_MONO

_UI = FONT_UI
from modules.project_manager import format_time
from modules.thumbnails import ImageLoader, compose_frame

PREVIEW_MAX_W = 300
PREVIEW_MAX_H = 520


class PreviewPanel(tk.Frame):
    def __init__(self, master, on_play_toggle=None, on_prev_shot=None,
                 on_next_shot=None, on_seek=None):
        super().__init__(master, bg=Palette.PANEL)
        self.on_play_toggle = on_play_toggle or (lambda: None)
        self.on_prev_shot = on_prev_shot or (lambda: None)
        self.on_next_shot = on_next_shot or (lambda: None)
        self.on_seek = on_seek or (lambda t: None)

        self.loader = ImageLoader(self)
        self.shots: list[dict] = []
        self.project_dir = None
        self.settings = {"width": 1080, "height": 1920, "fit": "contain"}
        self.cues: list[tuple[float, float, str]] = []
        self._current_key = None
        self._photo = None
        self.playing = False

        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        header = tk.Frame(self, bg=Palette.PANEL)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(header, text="预览", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(_UI, 9, "bold")).pack(side="left")
        self.info = tk.Label(header, text="—", bg=Palette.PANEL, fg=Palette.TEXT_FAINT,
                             font=(FONT_MONO, 9))
        self.info.pack(side="right")

        stage = tk.Frame(self, bg=Palette.BG_ALT)
        stage.pack(fill="both", expand=True, padx=12, pady=4)
        self.canvas = tk.Canvas(stage, bg=Palette.BG_ALT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._schedule_refresh())

        ctrl = tk.Frame(self, bg=Palette.PANEL)
        ctrl.pack(fill="x", padx=12, pady=(6, 12))
        self.btn_prev = self._button(ctrl, "⏮", lambda: self.on_prev_shot())
        self.btn_prev.pack(side="left")
        self.btn_play = self._button(ctrl, "▶", lambda: self.on_play_toggle())
        self.btn_play.pack(side="left", padx=6)
        self.btn_next = self._button(ctrl, "⏭", lambda: self.on_next_shot())
        self.btn_next.pack(side="left")
        self.time_label = tk.Label(ctrl, text="00:00.00", bg=Palette.PANEL,
                                   fg=Palette.TEXT, font=(FONT_MONO, 10))
        self.time_label.pack(side="right")

        self._refresh_job = None

    def _button(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=Palette.PANEL_ALT,
                         fg=Palette.TEXT, activebackground=Palette.BLOOD,
                         activeforeground="#ffffff", relief="flat", bd=0,
                         width=3, pady=4, font=(_UI, 11), cursor="hand2")

    # ------------------------------------------------------------------
    def set_project(self, project_dir, shots, settings, cues=None):
        if str(project_dir) != str(self.project_dir):
            self.loader.clear()
            self._current_key = None
        self.project_dir = project_dir
        self.shots = shots or []
        self.settings = settings or self.settings
        if cues is not None:
            self.cues = cues
        self.refresh(force=True)

    def set_shots(self, shots):
        self.shots = shots or []
        self.refresh(force=True)

    def set_playing(self, playing: bool):
        self.playing = playing
        self.btn_play.config(text="⏸" if playing else "▶",
                             fg=Palette.BLOOD if playing else Palette.TEXT)

    def _schedule_refresh(self):
        if self._refresh_job:
            return
        self._refresh_job = self.after(80, self._do_refresh)

    def _do_refresh(self):
        self._refresh_job = None
        self.refresh()

    def _stage_size(self):
        w = max(120, self.canvas.winfo_width() - 8)
        h = max(120, self.canvas.winfo_height() - 8)
        ar = self.settings["width"] / self.settings["height"]
        if w / h > ar:
            w = int(h * ar)
        else:
            h = int(w / ar)
        return max(2, w), max(2, h)

    def shot_at(self, t: float) -> tuple[dict | None, int]:
        for i, shot in enumerate(self.shots):
            start = float(shot.get("start", 0))
            end = start + float(shot.get("duration", 0))
            if start <= t < end or (i == len(self.shots) - 1 and t == end):
                return shot, i
        return None, -1

    def refresh(self, force=False, time=None):
        total = round(sum(float(s.get("duration", 0)) for s in self.shots), 3)
        t = float(time) if time is not None else getattr(self, "_time", 0.0)
        self._time = t
        self.time_label.config(text=f"{format_time(t)} / {format_time(total)}")

        shot, index = self.shot_at(t) if self.shots else (None, -1)
        if shot is None:
            self.canvas.delete("all")
            self._photo = None
            self.info.config(text="—")
            if not self.shots:
                self.canvas.create_text(self.canvas.winfo_width() // 2,
                                        self.canvas.winfo_height() // 2,
                                        text="导入图片后在此预览",
                                        fill=Palette.TEXT_FAINT, font=(_UI, 10))
            return

        local = t - float(shot.get("start", 0))
        key = (shot.get("image"), index, round(local, 2), self._stage_size(),
               self.settings.get("fit"), shot.get("zoom"))
        if not force and key == self._current_key:
            return
        self._current_key = key
        self._render(shot, index, local)

    def _render(self, shot, index, local):
        self.canvas.delete("all")
        cw_canvas = self.canvas.winfo_width()
        ch_canvas = self.canvas.winfo_height()
        if cw_canvas < 10 or ch_canvas < 10:
            return
        sw, sh = self._stage_size()
        image_path = None
        if self.project_dir and shot.get("image"):
            image_path = self.project_dir / shot["image"]
        name = compose_frame(self.loader, image_path, sw, sh,
                             self.settings.get("fit", "contain")) if image_path else None
        x0 = (cw_canvas - sw) // 2
        y0 = (ch_canvas - sh) // 2
        if name is not None:
            self._photo = name
            self.canvas.create_image(x0, y0, image=name, anchor="nw")
        else:
            self.canvas.create_rectangle(x0, y0, x0 + sw, y0 + sh,
                                         fill="#0a0a0a", outline=Palette.BORDER)
            if shot.get("image"):
                self.canvas.create_text(x0 + sw // 2, y0 + sh // 2,
                                        text="图片无法解码\n(支持 PNG/BMP/GIF)",
                                        fill=Palette.TEXT_FAINT, font=(_UI, 9), justify="center")
            else:
                # V1.2：故事导入但还没生成 / 绑定画面
                self.canvas.create_text(x0 + sw // 2, y0 + sh // 2 - 10,
                                        text="待配图", fill=Palette.AMBER,
                                        font=(_UI, 13, "bold"))
                scene = (shot.get("scene") or "").strip()
                if scene:
                    self.canvas.create_text(
                        x0 + sw // 2, y0 + sh // 2 + 26,
                        text=scene[:60] + ("…" if len(scene) > 60 else ""),
                        fill=Palette.TEXT_FAINT, font=(_UI, 9),
                        width=sw - 24, justify="center")

        # 字幕叠加
        text = self._subtitle_at(self._time)
        if text:
            font_size = max(9, int(sh * 0.038))
            ty = y0 + sh - int(sh * 0.08)
            for line_i, line in enumerate(text.split("\n")[::-1]):
                self.canvas.create_text(x0 + sw // 2, ty - line_i * (font_size + 4),
                                        text=line, fill="#ffffff",
                                        font=(_UI, font_size, "bold"), anchor="s")

        dur = float(shot.get("duration", 0))
        self.info.config(text=f"#{index + 1}  {local:.2f}/{dur:.2f}s  "
                              f"zoom:{shot.get('zoom', 'none')}  "
                              f"{shot.get('transition', 'cut')}")

    def _subtitle_at(self, t):
        for start, end, text in self.cues:
            if start <= t <= end:
                return text
        return None
