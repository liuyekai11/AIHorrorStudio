"""时间轴视图（Tk Canvas 实现）。

职责：把 shots 可视化为轨道 + 标尺 + 播放头，处理鼠标交互。
不做持久化：所有修改都通过回调通知界面层，由界面层调用 ProjectManager，
再把最新数据推回 render()。

回调：
  on_select(shot_ids: list[str])
  on_duration_change(shot_id: str, new_duration: float)   # 拖动/输入结束
  on_seek(time: float)                                    # 点击/拖动标尺或轨道
  on_reorder(shot_ids: list[str])                         # 拖拽排序结束后的新 id 顺序
"""
import tkinter as tk
from pathlib import Path

from theme import Palette, FONT_UI, FONT_MONO
from modules.project_manager import (
    MIN_DURATION, MAX_DURATION, format_time,
)
from modules.thumbnails import make_thumbnail


PADDING_LEFT = 12
TRACK_TOP = 26
TRACK_HEIGHT = 64
THUMB_H = 34
HANDLE_W = 6
MIN_PX_PER_SEC = 4.0
MAX_PX_PER_SEC = 240.0


def parse_time_text(text: str) -> float:
    """'mm:ss.xx' / 纯秒数 → float 秒。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("时间不能为空")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"无法解析时间：{text}")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return max(0.0, round(total, 3))


class TimelineView(tk.Frame):
    def __init__(self, master, app_font, mono_font, on_select=None,
                 on_duration_change=None, on_seek=None, on_reorder=None):
        super().__init__(master, bg=Palette.PANEL, highlightthickness=0)
        self.app_font = app_font
        self.mono_font = mono_font
        self.on_select = on_select or (lambda ids: None)
        self.on_duration_change = on_duration_change or (lambda sid, d: None)
        self.on_seek = on_seek or (lambda t: None)
        self.on_reorder = on_reorder or (lambda ids: None)

        self.shots: list[dict] = []
        self.selected: set[str] = set()
        self.playhead = 0.0
        self.px_per_sec = 40.0
        self.view_start = 0.0

        self._thumb_cache: dict[str, tk.PhotoImage | None] = {}

        self._drag_mode = None      # "edge" | "move" | "seek"
        self._drag_shot = None
        self._drag_edge = None
        self._drag_origin_x = 0
        self._drag_origin_vs = 0.0
        self._drag_origin_val = 0.0
        self._panning = False
        self._pan_start = 0

        self._build()
        self._bind_events()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build(self):
        bar = tk.Frame(self, bg=Palette.PANEL)
        bar.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(bar, text="时间轴", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9, "bold")).pack(side="left")
        self.time_label = tk.Label(bar, text="00:00.00 / 00:00.00", bg=Palette.PANEL,
                                   fg=Palette.BLOOD, font=self.mono_font)
        self.time_label.pack(side="left", padx=14)
        self.info_label = tk.Label(bar, text="", bg=Palette.PANEL,
                                   fg=Palette.TEXT_FAINT, font=(FONT_UI, 9))
        self.info_label.pack(side="left")

        for text, cmd, side in [
            ("+", lambda: self.zoom_by(1.3), "right"),
            ("-", lambda: self.zoom_by(1 / 1.3), "right"),
            ("适应", self.fit, "right"),
        ]:
            tk.Button(bar, text=text, command=cmd, bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                      activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                      relief="flat", bd=0, padx=8, pady=2, font=(FONT_UI, 9),
                      cursor="hand2").pack(side=side, padx=2)

        # 横向滚动交给鼠标滚轮 / 中键拖动，不需要占位滚动条
        self.canvas = tk.Canvas(self, bg=Palette.TRACK, highlightthickness=0,
                                height=TRACK_TOP + TRACK_HEIGHT + 18, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=(0, 2))

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def set_shots(self, shots: list[dict], preserve_selection=True):
        self.shots = shots or []
        valid_ids = {s.get("id") for s in self.shots}
        self.selected &= valid_ids
        if not preserve_selection:
            self.selected.clear()
        self.redraw()

    def set_selection(self, shot_ids: list[str], notify=False):
        self.selected = {sid for sid in shot_ids if sid}
        self.redraw()
        if notify:
            self.on_select(list(self.selected))

    def set_active(self, shot_id_or_time):
        """设置“当前编辑”镜头（与多选高亮区分）。可传镜头 id 或时间（秒）。"""
        value = shot_id_or_time
        if isinstance(value, (int, float)):
            value = self._shot_id_at(float(value))
        if getattr(self, "_active", None) == value:
            return
        self._active = value
        self.redraw()

    def set_playhead(self, t: float, redraw=True):
        total = self.total()
        self.playhead = max(0.0, min(float(t), total))
        active = self._shot_id_at(self.playhead)
        if active != getattr(self, "_active", None):
            self._active = active
        if redraw:
            self.redraw()
        self._update_time_label()

    def _shot_id_at(self, t: float):
        for shot in self.shots:
            start = float(shot.get("start", 0))
            if start <= t < start + float(shot.get("duration", 0)):
                return shot.get("id")
        if self.shots:
            return self.shots[-1].get("id")
        return None

    def total(self) -> float:
        return round(sum(float(s.get("duration", 0)) for s in self.shots), 3)

    def zoom_by(self, factor: float):
        center = self.view_start + self._view_width() / 2 / self.px_per_sec
        self.px_per_sec = min(MAX_PX_PER_SEC, max(MIN_PX_PER_SEC, self.px_per_sec * factor))
        self.view_start = max(0.0, center - self._view_width() / 2 / self.px_per_sec)
        self._clamp_view()
        self.redraw()

    def fit(self):
        total = max(self.total(), 1.0)
        width = self._view_width() - PADDING_LEFT - 20
        self.px_per_sec = min(MAX_PX_PER_SEC, max(MIN_PX_PER_SEC, width / total))
        self.view_start = 0.0
        self.redraw()

    # ------------------------------------------------------------------
    # 坐标换算
    # ------------------------------------------------------------------
    def _view_width(self):
        return max(1, self.canvas.winfo_width())

    def x_to_time(self, x: float) -> float:
        return max(0.0, self.view_start + (x - PADDING_LEFT) / self.px_per_sec)

    def time_to_x(self, t: float) -> float:
        return PADDING_LEFT + (t - self.view_start) * self.px_per_sec

    def _clamp_view(self):
        total = self.total()
        visible = self._view_width() / self.px_per_sec
        max_start = max(0.0, total + 2 - visible)
        self.view_start = min(max(0.0, self.view_start), max_start)

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def redraw(self):
        c = self.canvas
        c.delete("all")
        self._clamp_view()
        self._draw_ruler()
        self._draw_tracks()
        self._draw_playhead()
        self._update_time_label()
        if self.shots:
            sel = len(self.selected)
            self.info_label.config(text=f"{len(self.shots)} 个镜头" + (f" · 选中 {sel}" if sel else ""))
        else:
            self.info_label.config(text="还没有镜头 · 点击左侧「＋ 导入图片」开始")

    def _draw_ruler(self):
        c = self.canvas
        c.create_rectangle(0, 0, self._view_width(), TRACK_TOP, fill=Palette.RULER, outline="")
        total = self.total() + 2
        # 选一个让标签间距 >= 70px 的时间步长
        steps = (0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600)
        # 标签是 "hh:mm:ss.xx"，约 92px 宽，留足间距避免重叠
        step = next((s for s in steps if s * self.px_per_sec >= 96), steps[-1])
        minor = step / 5 if step / 5 * self.px_per_sec >= 7 else None
        t = (int(self.view_start / step)) * step
        end = self.view_start + self._view_width() / self.px_per_sec
        while t <= end:
            x = self.time_to_x(t)
            if self.view_start - 1 <= t <= total:
                c.create_line(x, TRACK_TOP - 9, x, TRACK_TOP, fill=Palette.TEXT_DIM)
                label = format_time(t)
                c.create_text(x + 4, 6, text=label, anchor="nw",
                              fill=Palette.TEXT_DIM, font=self.mono_font)
            if minor:
                mt = t + minor
                while mt < t + step and mt <= end:
                    mx = self.time_to_x(mt)
                    c.create_line(mx, TRACK_TOP - 4, mx, TRACK_TOP, fill=Palette.BORDER_STRONG)
                    mt += minor
            t += step

    def _draw_tracks(self):
        c = self.canvas
        width = self._view_width()
        top = TRACK_TOP
        total = self.total()
        c.create_rectangle(0, top, width, top + TRACK_HEIGHT, fill=Palette.TRACK_ALT, outline="")
        end_x = self.time_to_x(total) if total else PADDING_LEFT
        # 已用区间之外压暗
        if end_x < width:
            c.create_rectangle(end_x, top, width, top + TRACK_HEIGHT,
                               fill=Palette.TRACK, outline="")

        for i, shot in enumerate(self.shots):
            sid = shot.get("id")
            start = float(shot.get("start", 0.0))
            dur = float(shot.get("duration", 0))
            x1 = self.time_to_x(start)
            x2 = self.time_to_x(start + dur)
            if x2 < -10 or x1 > width + 10:
                continue
            selected = sid in self.selected
            is_active = sid == getattr(self, "_active", None)
            if selected:
                fill, outline = Palette.BLOOD_DEEP, Palette.BLOOD
            elif is_active:
                fill, outline = Palette.PANEL_HOVER, Palette.AMBER
            else:
                fill, outline = Palette.PANEL_ALT, Palette.BORDER_STRONG
            c.create_rectangle(x1 + 1, top + 4, x2 - 1, top + TRACK_HEIGHT - 4,
                               fill=fill, outline=outline, tags=("shot", sid, f"shot:{sid}"))

            # 缩略图
            thumb = None
            if x2 - x1 >= 60 and shot.get("image"):
                thumb = self.thumbnail(shot.get("image"))
                if thumb is not None:
                    c.create_image(x1 + 8, top + 10, image=thumb, anchor="nw", tags=("shot", sid))

            # 文字
            text_x = x1 + (88 if (x2 - x1 >= 100 and thumb is not None) else 8)
            c.create_text(text_x, top + 9, anchor="nw", fill=Palette.BONE,
                          font=(FONT_UI, 9, "bold"),
                          text=f"#{i + 1}", tags=("shot", sid))
            c.create_text(text_x, top + 26, anchor="nw", fill=Palette.TEXT_DIM,
                          font=self.mono_font, text=f"{dur:.2f}s",
                          tags=("shot", sid))
            if not shot.get("image"):
                # V1.2：故事导入但还没有画面
                label, color = ("AI 生成中" if shot.get("ai_pending") else "待配图"), Palette.AMBER
                if shot.get("ai_pending"):
                    color = Palette.RUST
                c.create_text(text_x, top + 40, anchor="nw", fill=color,
                              font=(FONT_UI, 8), text=label, tags=("shot", sid))
            elif shot.get("ai_image"):
                c.create_text(text_x, top + 40, anchor="nw", fill=Palette.SUCCESS,
                              font=(FONT_UI, 8), text="AI 画面", tags=("shot", sid))
            if shot.get("motion") not in (None, "", "static"):
                c.create_text(x2 - 8, top + TRACK_HEIGHT - 10, anchor="se",
                              fill=Palette.AMBER, font=(FONT_UI, 8),
                              text=f"{shot['motion']}", tags=("shot", sid))

            # 拖拽手柄
            handle_fill = Palette.BLOOD if selected else Palette.BORDER_STRONG
            c.create_rectangle(x1 + 1, top + 4, x1 + 1 + HANDLE_W, top + TRACK_HEIGHT - 4,
                               fill=handle_fill, outline="", tags=("handle_l", sid))
            c.create_rectangle(x2 - 1 - HANDLE_W, top + 4, x2 - 1, top + TRACK_HEIGHT - 4,
                               fill=handle_fill, outline="", tags=("handle_r", sid))

    def _draw_playhead(self):
        c = self.canvas
        if self.shots or self.playhead > 0:
            x = self.time_to_x(self.playhead)
            if -4 <= x <= self._view_width() + 4:
                c.create_line(x, 0, x, TRACK_TOP + TRACK_HEIGHT + 8,
                              fill=Palette.BLOOD_HOVER, width=2)
                c.create_polygon(x - 6, 0, x + 6, 0, x, 9,
                                 fill=Palette.BLOOD_HOVER, outline="")

    def _update_time_label(self):
        self.time_label.config(text=f"{format_time(self.playhead)} / {format_time(self.total())}")

    # ------------------------------------------------------------------
    # 缩略图
    # ------------------------------------------------------------------
    def thumbnail(self, rel_image: str | None):
        if not rel_image:
            return None
        if rel_image in self._thumb_cache:
            return self._thumb_cache[rel_image]
        thumb = None
        project_dir = getattr(self, "project_dir", None)
        if project_dir:
            thumb = make_thumbnail(Path(project_dir) / rel_image, THUMB_H, self)
        self._thumb_cache[rel_image] = thumb
        return thumb

    def set_project_dir(self, project_dir):
        self.project_dir = project_dir
        self._thumb_cache.clear()

    def clear_thumbnail_cache(self):
        self._thumb_cache.clear()
        self.redraw()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _bind_events(self):
        c = self.canvas
        c.bind("<Configure>", lambda e: self.redraw())
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_motion)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Button-2>", self._on_middle_press)
        c.bind("<B2-Motion>", self._on_middle_move)
        c.bind("<Button-3>", self._on_middle_press)
        c.bind("<B3-Motion>", self._on_middle_move)
        c.bind("<Double-Button-1>", self._on_double_click)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Shift-MouseWheel>", self._on_wheel)
        c.bind("<Control-MouseWheel>", self._on_ctrl_wheel)

    def _event_time(self, x):
        return self.x_to_time(x)

    def _hit_shot(self, x, y):
        if y < TRACK_TOP or y > TRACK_TOP + TRACK_HEIGHT:
            return None, None
        t = self._event_time(x)
        for shot in self.shots:
            s = float(shot.get("start", 0))
            e = s + float(shot.get("duration", 0))
            if s <= t < e:
                edge = None
                if abs(x - self.time_to_x(s)) <= HANDLE_W + 3:
                    edge = "left"
                elif abs(x - self.time_to_x(e)) <= HANDLE_W + 3:
                    edge = "right"
                return shot.get("id"), edge
        return None, None

    def _on_press(self, event):
        c = self.canvas
        c.focus_set()
        if event.y < TRACK_TOP:
            self._drag_mode = "seek"
            self.on_seek(self._event_time(event.x))
            return
        sid, edge = self._hit_shot(event.x, event.y)
        shift = bool(event.state & 0x0001)
        if sid is None:
            self.selected.clear()
            self.redraw()
            self.on_select([])
            self._drag_mode = "seek"
            self._pending_reorder = False
            self.on_seek(self._event_time(event.x))
            return
        self._pending_reorder = False

        if shift:
            self.selected ^= {sid}
        elif sid not in self.selected:
            self.selected = {sid}
        self.redraw()
        self.on_select(list(self.selected))

        shot = next(s for s in self.shots if s.get("id") == sid)
        if edge:
            self._drag_mode = "edge"
            self._drag_shot = sid
            self._drag_edge = edge
            self._drag_origin_x = event.x
            self._drag_origin_val = float(shot.get("duration", 0)) if edge == "right" else float(shot.get("start", 0))
        else:
            # 拖动镜头中间：松手时按落点排序
            self._drag_mode = "move"
            self._drag_shot = sid
            self._drag_origin_x = event.x
            self._drag_origin_vs = self.view_start

    def _on_motion(self, event):
        if self._drag_mode == "seek":
            self.on_seek(self._event_time(event.x))
            return
        if self._drag_mode == "move":
            if abs(event.x - self._drag_origin_x) > 4:
                self._pending_reorder = True
            self.redraw()
            return
        if self._drag_mode == "edge" and self._drag_shot:
            shot = next((s for s in self.shots if s.get("id") == self._drag_shot), None)
            if shot is None:
                return
            delta = (event.x - self._drag_origin_x) / self.px_per_sec
            if self._drag_edge == "right":
                new_dur = self._drag_origin_val + delta
            else:
                new_dur = float(shot["duration"]) - delta
            new_dur = max(MIN_DURATION, min(MAX_DURATION, round(new_dur, 3)))
            if abs(new_dur - float(shot["duration"])) > 1e-6:
                shot["duration"] = new_dur
                self._reflow_preview()
                self.redraw()

    def _reflow_preview(self):
        cursor = 0.0
        for s in self.shots:
            s["start"] = round(cursor, 3)
            cursor += float(s.get("duration", 0))

    def _on_release(self, event):
        mode, sid = self._drag_mode, self._drag_shot
        self._drag_mode = None
        self._drag_shot = None
        if mode == "edge" and sid:
            shot = next((s for s in self.shots if s.get("id") == sid), None)
            if shot is not None:
                self.on_duration_change(sid, float(shot["duration"]))
        elif mode == "move" and getattr(self, "_pending_reorder", False):
            self._pending_reorder = False
            self._maybe_reorder(event)
        self.redraw()

    def _maybe_reorder(self, event):
        """按鼠标落点相对其它镜头中心的位置决定新下标。"""
        if not self._drag_shot:
            return
        # 用按下时的镜头顺序决定相对位置；拖动中已实时 reflow 过，用固定顺序重算
        ids = [s.get("id") for s in self.shots]
        if self._drag_shot not in ids:
            return
        current = ids.index(self._drag_shot)
        target_t = self._event_time(event.x)
        new_index = 0
        for i, s in enumerate(self.shots):
            if s.get("id") == self._drag_shot:
                continue
            mid = float(s["start"]) + float(s["duration"]) / 2
            if target_t > mid:
                new_index += 1
        if new_index == current:
            return
        ids.pop(current)
        ids.insert(new_index, self._drag_shot)
        self.on_reorder(ids)

    def _on_middle_press(self, event):
        self._panning = True
        self._pan_start = (event.x, self.view_start)

    def _on_middle_move(self, event):
        if not self._panning:
            return
        dx = event.x - self._pan_start[0]
        self.view_start = self._pan_start[1] - dx / self.px_per_sec
        self._clamp_view()
        self.redraw()

    def _on_double_click(self, event):
        if event.y < TRACK_TOP:
            return
        sid, _ = self._hit_shot(event.x, event.y)
        if sid is None:
            return
        shot = next(s for s in self.shots if s.get("id") == sid)
        # 双击镜头中间：把播放头移到镜头起点
        self.on_seek(float(shot.get("start", 0)))

    def _on_wheel(self, event):
        self.view_start -= event.delta / 120 * 0.5 / self.px_per_sec * 10
        self._clamp_view()
        self.redraw()

    def _on_ctrl_wheel(self, event):
        self.zoom_by(1.15 if event.delta > 0 else 1 / 1.15)
