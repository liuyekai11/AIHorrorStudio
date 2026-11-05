"""「批量」页签：一次排 N 个项目，后台自动跑完整条流水线。

职责边界（与 ai_studio / story_panel 一致）
------------------------------------------
* 只负责界面与进度展示。真正干活的是 modules/batch.py 的 BatchRunner，
  它把进度通过事件回调上报；主窗口把事件转成 `post(kind, payload)`：
      post("batch_event", event)      BatchRunner 的事件 dict
      post("batch_done", results)     整批结束，results 是 BatchResult 列表
      post("batch_error", text)       启动前校验失败等
  面板只消费这些消息，不碰线程。
* 任务清单存在用户目录 ~/.ai_horror_studio_batch.json（不放项目目录，
  避免随项目分享泄漏），下次打开自动恢复。

回调
----
  on_start(jobs, workspace, settings) -> None   开始批量生产
  on_stop() -> None                             请求停止（当前项目跑完后停）
  on_pick_workspace() -> str | None             选择输出根目录
  on_open(path) -> None                         打开某个成片 / 目录
  on_status(text) -> None                       状态栏提示
"""
import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from theme import Palette, FONT_UI, FONT_MONO
from modules.batch import BatchJob

import tkinter.ttk as ttk

JOBS_FILE = Path.home() / ".ai_horror_studio_batch.json"

# 出片尺寸预设：批量出小样时可以缩小渲染，快很多
RENDER_PRESETS = [
    ("项目默认", None),
    ("360x640（竖屏小样·快）", (360, 640)),
    ("720x1280（竖屏标清）", (720, 1280)),
    ("1080x1920（竖屏高清）", (1080, 1920)),
]

STATUS_TEXT = {"pending": "等待", "running": "进行中", "ok": "✓ 完成", "error": "✗ 失败"}


class BatchPanel(tk.Frame):
    def __init__(self, master, on_start=None, on_stop=None,
                 on_pick_workspace=None, on_open=None, on_status=None):
        super().__init__(master, bg=Palette.BG)
        self.on_start = on_start or (lambda **kw: None)
        self.on_stop = on_stop or (lambda: None)
        self.on_pick_workspace = on_pick_workspace or (lambda: None)
        self.on_open = on_open or (lambda path: None)
        self.on_status = on_status or (lambda text: None)

        self.busy = False
        self._stop_requested = False
        self._rows: list[dict] = []      # 表格行的状态（与 tree 行号对应）
        self._results: dict[str, object] = {}
        self._build()
        self.load_jobs()

    # ==================================================================
    # 构建
    # ==================================================================
    def _build(self):
        outer = tk.Frame(self, bg=Palette.BG)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        left = tk.Frame(outer, bg=Palette.PANEL)
        left.pack(side="left", fill="both", expand=True)
        self._build_list(left)

        right = tk.Frame(outer, bg=Palette.PANEL, width=340)
        right.pack(side="left", fill="y", padx=(14, 0))
        right.pack_propagate(False)
        self._build_side(right)

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

    def _entry(self, parent, textvariable, width=None):
        e = tk.Entry(parent, textvariable=textvariable, bg=Palette.PANEL_ALT,
                     fg=Palette.TEXT, insertbackground=Palette.TEXT, relief="flat",
                     bd=0, font=(FONT_UI, 9), width=width or 10,
                     highlightthickness=1, highlightbackground=Palette.BORDER,
                     highlightcolor=Palette.BLOOD)
        return e

    def _build_list(self, parent):
        head = tk.Frame(parent, bg=Palette.PANEL)
        head.pack(fill="x", padx=16, pady=(14, 0))
        tk.Label(head, text="待生产项目", bg=Palette.PANEL, fg=Palette.BONE,
                 font=(FONT_UI, 13, "bold"), anchor="w").pack(side="left")
        self.list_summary = tk.Label(head, text="", bg=Palette.PANEL,
                                     fg=Palette.TEXT_FAINT, font=(FONT_MONO, 9))
        self.list_summary.pack(side="right")

        tk.Label(parent,
                 text="每个项目独立跑：生成故事 → 导入分镜 → AI 出图 → AI 配音（自动对齐时长）"
                      " → 渲染成片。一个项目失败不会中断整批。",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8),
                 anchor="w", justify="left", wraplength=760).pack(fill="x", padx=16, pady=(2, 8))

        # 表格
        table = tk.Frame(parent, bg=Palette.PANEL)
        table.pack(fill="both", expand=True, padx=16)
        columns = ("name", "keywords", "shots", "status", "detail")
        self.tree = ttk.Treeview(table, columns=columns, show="headings",
                                 selectmode="browse")
        for col, text, width, anchor in (
                ("name", "项目名", 150, "w"), ("keywords", "题材关键词", 190, "w"),
                ("shots", "镜头数", 60, "center"), ("status", "状态", 80, "center"),
                ("detail", "说明", 300, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor,
                             stretch=(col == "detail"))
        style = ttk.Style()
        style.configure("Batch.Treeview", background=Palette.PANEL_ALT,
                        fieldbackground=Palette.PANEL_ALT, foreground=Palette.TEXT,
                        rowheight=26, font=(FONT_UI, 9), borderwidth=0)
        style.configure("Batch.Treeview.Heading", background=Palette.PANEL,
                        foreground=Palette.TEXT_DIM, relief="flat",
                        font=(FONT_UI, 9, "bold"))
        style.map("Batch.Treeview", background=[("selected", Palette.BLOOD_DEEP)],
                  foreground=[("selected", Palette.BONE)])
        self.tree.configure(style="Batch.Treeview")
        bar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_editor_from_selection())
        self.tree.bind("<Double-1>", lambda e: self._open_selected_result())

        # 编辑器
        editor = tk.Frame(parent, bg=Palette.PANEL)
        editor.pack(fill="x", padx=16, pady=(10, 6))
        self.ed_name = tk.StringVar()
        self.ed_keywords = tk.StringVar()
        self.ed_shots = tk.StringVar(value="8")
        self.ed_style = tk.StringVar()
        self.ed_extra = tk.StringVar()

        r1 = tk.Frame(editor, bg=Palette.PANEL)
        r1.pack(fill="x")
        tk.Label(r1, text="项目名", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9), width=7, anchor="w").pack(side="left")
        self._entry(r1, self.ed_name, 22).pack(side="left", padx=(0, 10))
        tk.Label(r1, text="镜头数", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9), anchor="w").pack(side="left")
        self._entry(r1, self.ed_shots, 5).pack(side="left", padx=(0, 10))
        tk.Label(r1, text="题材关键词（必填）", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9), anchor="w").pack(side="left")

        r2 = tk.Frame(editor, bg=Palette.PANEL)
        r2.pack(fill="x", pady=(6, 0))
        tk.Label(r2, text="风格", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9), width=7, anchor="w").pack(side="left")
        self._entry(r2, self.ed_style, 22).pack(side="left", padx=(0, 10))
        tk.Label(r2, text="补充要求", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9), anchor="w").pack(side="left")
        self._entry(r2, self.ed_extra).pack(side="left", fill="x", expand=True)

        r3 = tk.Frame(editor, bg=Palette.PANEL)
        r3.pack(fill="x", pady=(6, 0))
        tk.Label(r3, text="题材关键词", bg=Palette.PANEL, fg=Palette.TEXT_DIM,
                 font=(FONT_UI, 9), width=7, anchor="w").pack(side="left")
        self._entry(r3, self.ed_keywords).pack(side="left", fill="x", expand=True)

        actions = tk.Frame(parent, bg=Palette.PANEL)
        actions.pack(fill="x", padx=16, pady=(4, 14))
        self._button(actions, "＋ 添加/更新", self.add_or_update, small=True).pack(side="left")
        self._button(actions, "删除选中", self.delete_selected, small=True).pack(
            side="left", padx=6)
        self._button(actions, "上移", lambda: self.move(-1), small=True).pack(side="left")
        self._button(actions, "下移", lambda: self.move(1), small=True).pack(
            side="left", padx=6)
        self._button(actions, "清空", self.clear_jobs, small=True).pack(side="left")

    def _build_side(self, parent):
        inner = tk.Frame(parent, bg=Palette.PANEL)
        inner.pack(fill="both", expand=True, padx=16, pady=14)

        tk.Label(inner, text="批量生产", bg=Palette.PANEL, fg=Palette.BONE,
                 font=(FONT_UI, 13, "bold"), anchor="w").pack(fill="x")

        self._section(inner, "输出目录", top=(10, 4))
        self.workspace_var = tk.StringVar(value="")
        ws_row = tk.Frame(inner, bg=Palette.PANEL)
        ws_row.pack(fill="x")
        self.ws_label = tk.Label(ws_row, textvariable=self.workspace_var,
                                 bg=Palette.PANEL_ALT, fg=Palette.TEXT_DIM,
                                 font=(FONT_MONO, 8), anchor="w", justify="left",
                                 wraplength=300, padx=6, pady=6)
        self.ws_label.pack(fill="x")
        self._button(inner, "选择目录…", self._pick_workspace, small=True).pack(
            anchor="w", pady=(4, 0))

        self._section(inner, "出片尺寸")
        self.preset_var = tk.StringVar(value=RENDER_PRESETS[0][0])
        menu = tk.OptionMenu(inner, self.preset_var,
                             *[name for name, _ in RENDER_PRESETS])
        menu.config(bg=Palette.PANEL_ALT, fg=Palette.TEXT, relief="flat", bd=0,
                    activebackground=Palette.PANEL_HOVER, activeforeground=Palette.TEXT,
                    highlightthickness=0, font=(FONT_UI, 9), anchor="w")
        menu["menu"].config(bg=Palette.PANEL_ALT, fg=Palette.TEXT,
                            activebackground=Palette.BLOOD, activeforeground="#ffffff")
        menu.pack(fill="x", pady=(2, 0))

        self._section(inner, "运行")
        btn_row = tk.Frame(inner, bg=Palette.PANEL)
        btn_row.pack(fill="x")
        self.start_btn = self._button(btn_row, "▶  开始批量生产", self.start, accent=True)
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.stop_btn = self._button(btn_row, "停止", self.stop, small=True)
        self.stop_btn.pack(side="left", padx=(6, 0))

        self.progress_label = tk.Label(inner, text="", bg=Palette.PANEL, fg=Palette.AMBER,
                                       font=(FONT_UI, 9), anchor="w", justify="left",
                                       wraplength=300)
        self.progress_label.pack(fill="x", pady=(8, 0))

        self._section(inner, "日志")
        self.log = tk.Text(inner, height=14, wrap="word", bg=Palette.PANEL_ALT,
                           fg=Palette.TEXT, relief="flat", font=(FONT_MONO, 8),
                           padx=8, pady=6, highlightthickness=1,
                           highlightbackground=Palette.BORDER, state="disabled")
        self.log.pack(fill="both", expand=True, pady=(0, 6))
        log_bar = tk.Frame(inner, bg=Palette.PANEL)
        log_bar.pack(fill="x")
        self._button(log_bar, "打开选中成片", self._open_selected_result,
                     small=True).pack(side="left")
        self._button(log_bar, "清空日志", self.clear_log, small=True).pack(
            side="left", padx=6)

        tk.Label(inner,
                 text="· 批量会真实调用 DeepSeek 与硅基流动，按项目数计费\n"
                      "· 停止只会在「当前项目跑完」后生效，不会打断正在生成的素材",
                 bg=Palette.PANEL, fg=Palette.TEXT_FAINT, font=(FONT_UI, 8),
                 anchor="w", justify="left").pack(fill="x", pady=(8, 0))

    # ==================================================================
    # 任务清单
    # ==================================================================
    def jobs(self) -> list[BatchJob]:
        out = []
        for row in self._rows:
            try:
                shots = int(row.get("shots") or 8)
            except (TypeError, ValueError):
                shots = 8
            out.append(BatchJob(row.get("name", ""), row.get("keywords", ""),
                                shots, row.get("style", ""), row.get("extra", "")))
        return out

    def set_jobs(self, jobs: list[BatchJob]):
        self._rows = [{"name": j.name, "keywords": j.keywords, "shots": j.shot_count,
                       "style": j.style, "extra": j.extra, "status": "pending",
                       "detail": ""} for j in jobs]
        self._results = {}
        self._refresh_tree()
        self.save_jobs()

    def _refresh_tree(self):
        selected = self._selected_index()
        self.tree.delete(*self.tree.get_children())
        for row in self._rows:
            self.tree.insert("", "end", values=(
                row.get("name", ""), row.get("keywords", ""),
                row.get("shots", 8), STATUS_TEXT.get(row.get("status"), ""),
                row.get("detail", "")))
        if selected is not None and selected < len(self._rows):
            items = self.tree.get_children()
            self.tree.selection_set(items[selected])
        total_shots = sum(int(r.get("shots") or 0) for r in self._rows)
        self.list_summary.config(
            text=f"{len(self._rows)} 个项目 · {total_shots} 镜" if self._rows else "还没有项目")

    def _selected_index(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.index(sel[0])

    def _load_editor_from_selection(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self._rows):
            return
        row = self._rows[idx]
        self.ed_name.set(row.get("name", ""))
        self.ed_keywords.set(row.get("keywords", ""))
        self.ed_shots.set(str(row.get("shots", 8)))
        self.ed_style.set(row.get("style", ""))
        self.ed_extra.set(row.get("extra", ""))

    def fill_editor(self, name: str = "", keywords: str = "", shots=8,
                    style: str = "", extra: str = ""):
        """把一组参数填进编辑器（供测试与外部预设使用），不会自动入库。"""
        self.ed_name.set(name)
        self.ed_keywords.set(keywords)
        self.ed_shots.set(str(shots))
        self.ed_style.set(style)
        self.ed_extra.set(extra)

    def add_or_update(self):
        """按「项目名」判断：重名则更新，否则新增。"""
        name = self.ed_name.get().strip()
        keywords = self.ed_keywords.get().strip()
        if not name:
            messagebox.showinfo("提示", "请填写项目名。", parent=self)
            return
        if not keywords:
            messagebox.showinfo("提示", f"「{name}」缺少题材关键词。", parent=self)
            return
        try:
            shots = int(self.ed_shots.get() or 8)
        except ValueError:
            shots = 0
        if not 1 <= shots <= 30:
            messagebox.showinfo("提示", "镜头数需在 1~30 之间。", parent=self)
            return
        row = {"name": name, "keywords": keywords, "shots": shots,
               "style": self.ed_style.get().strip(),
               "extra": self.ed_extra.get().strip(),
               "status": "pending", "detail": ""}
        idx = self._selected_index()
        if idx is not None and idx < len(self._rows) and self._rows[idx]["name"] == name:
            row["status"] = self._rows[idx].get("status", "pending")
            self._rows[idx] = row
        elif any(r["name"] == name for r in self._rows):
            pos = next(i for i, r in enumerate(self._rows) if r["name"] == name)
            self._rows[pos] = row
        else:
            self._rows.append(row)
        self._refresh_tree()
        self.save_jobs()

    def delete_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        del self._rows[idx]
        self._refresh_tree()
        self.save_jobs()

    def move(self, delta: int):
        idx = self._selected_index()
        if idx is None:
            return
        target = idx + delta
        if not 0 <= target < len(self._rows):
            return
        self._rows[idx], self._rows[target] = self._rows[target], self._rows[idx]
        self._refresh_tree()
        items = self.tree.get_children()
        self.tree.selection_set(items[target])
        self.save_jobs()

    def clear_jobs(self):
        if not self._rows:
            return
        if not messagebox.askyesno("清空", "确定清空任务清单？（不影响已生成的项目）",
                                   parent=self):
            return
        self._rows = []
        self._results = {}
        self._refresh_tree()
        self.save_jobs()

    def load_jobs(self):
        try:
            raw = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        jobs = []
        for item in raw.get("jobs", []) or []:
            if not isinstance(item, dict):
                continue
            jobs.append(BatchJob(item.get("name", ""), item.get("keywords", ""),
                                 item.get("shots", 8), item.get("style", ""),
                                 item.get("extra", "")))
        self._rows = [{"name": j.name, "keywords": j.keywords, "shots": j.shot_count,
                       "style": j.style, "extra": j.extra, "status": "pending",
                       "detail": ""} for j in jobs]
        self._results = {}
        self.workspace_var.set(raw.get("workspace", "") or "（未选择）")
        self._refresh_tree()

    def save_jobs(self):
        payload = {
            "jobs": [{"name": r.get("name", ""), "keywords": r.get("keywords", ""),
                      "shots": int(r.get("shots") or 8), "style": r.get("style", ""),
                      "extra": r.get("extra", "")} for r in self._rows],
            "workspace": self.workspace_var.get()
            if self.workspace_var.get() not in ("", "（未选择）") else "",
        }
        try:
            JOBS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except OSError:
            pass

    # ==================================================================
    # 运行
    # ==================================================================
    def render_settings(self) -> dict | None:
        for name, values in RENDER_PRESETS:
            if name == self.preset_var.get() and values:
                width, height = values
                return {"width": width, "height": height}
        return None

    def workspace(self) -> str:
        value = self.workspace_var.get().strip()
        return "" if value in ("", "（未选择）") else value

    def _pick_workspace(self):
        path = self.on_pick_workspace()
        if path:
            self.workspace_var.set(str(path))
            self.save_jobs()

    def start(self):
        if self.busy:
            return
        errors = []
        for job in self.jobs():
            err = job.validate()
            if err:
                errors.append(err)
        names = [j.name for j in self.jobs()]
        if len(names) != len(set(names)):
            errors.append("项目名称重复")
        if not self._rows:
            errors.append("任务清单是空的")
        if not self.workspace():
            errors.append("还没有选择输出目录")
        if errors:
            messagebox.showwarning("无法开始", "\n".join(errors), parent=self)
            return
        self.save_jobs()
        for row in self._rows:
            row["status"] = "pending"
            row["detail"] = ""
        self._results = {}
        self._refresh_tree()
        self.clear_log()
        self.on_start(jobs=self.jobs(), workspace=Path(self.workspace()),
                      settings=self.render_settings())

    def stop(self):
        if not self.busy:
            return
        self._stop_requested = True
        self._append_log("… 已请求停止，当前项目跑完后结束")
        self.progress_label.config(text="正在停止（当前项目跑完）…", fg=Palette.AMBER)

    def set_busy(self, busy: bool, total: int = 0):
        self.busy = busy
        if busy:
            self._stop_requested = False
            self.progress_label.config(text=f"准备开始（{total} 个项目）…", fg=Palette.AMBER)
        else:
            self._stop_requested = False
        self.start_btn.config(state="disabled" if busy else "normal")
        self.stop_btn.config(state="normal" if busy else "disabled")

    def stop_requested(self) -> bool:
        return self._stop_requested

    # ==================================================================
    # 事件消费（主线程）
    # ==================================================================
    def handle_event(self, event: dict):
        kind = event.get("event")
        index = int(event.get("index") or 0)
        row = self._rows[index - 1] if 0 < index <= len(self._rows) else None
        if kind == "batch_start":
            self._append_log(f"开始批量生产：{event.get('total')} 个项目")
            self.progress_label.config(text=f"0/{event.get('total')} 完成",
                                       fg=Palette.AMBER)
        elif kind == "batch_stop":
            self._append_log(f"已按请求停止，{event.get('skipped')} 个项目未运行")
        elif kind == "project_start":
            if row:
                row["status"] = "running"
                row["detail"] = ""
                self._refresh_tree()
            self._append_log(f"[{index}/{event.get('total')}] {event.get('name')} …")
        elif kind == "step":
            if row:
                text = event.get("text", "")
                row["detail"] = text
                self._refresh_tree()
            self.progress_label.config(
                text=f"项目 {index}/{event.get('total')} · {event.get('name')}\n"
                     f"{event.get('text', '')}")
        elif kind in ("project_done", "project_error"):
            if row:
                row["status"] = event.get("status", "ok")
                row["detail"] = event.get("detail") or ("成片：" + event.get("output", "")
                                                        if event.get("output") else "")
                self._refresh_tree()
            ok = kind == "project_done"
            self._append_log(("✓ " if ok else "✗ ") + f"{event.get('name')}："
                             f"{event.get('detail') or '完成'}")
        elif kind == "batch_done":
            self.progress_label.config(
                text=f"全部结束：{event.get('ok')}/{event.get('total')} 成功",
                fg=Palette.SUCCESS if event.get("ok") == event.get("total") else Palette.AMBER)
            self._append_log(f"批量结束：{event.get('ok')}/{event.get('total')} 成功")
        self._notify_refresh()

    def handle_results(self, results):
        """整批结束：把 BatchResult 存起来以便打开成片。"""
        self._results = {r.name: r for r in results}
        self.set_busy(False)
        ok = sum(1 for r in results if r.ok)
        self.progress_label.config(
            text=f"全部结束：{ok}/{len(results)} 成功",
            fg=Palette.SUCCESS if ok == len(results) else Palette.AMBER)
        self._append_log(f"共 {len(results)} 个项目，成功 {ok}，失败 {len(results) - ok}")

    def handle_error(self, text: str):
        self.set_busy(False)
        self.progress_label.config(text="批量启动失败", fg=Palette.ERROR)
        self._append_log(f"启动失败：{text}")

    def _notify_refresh(self):
        self.on_status(self.progress_label.cget("text").replace("\n", " · "))

    def _open_selected_result(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self._rows):
            return
        name = self._rows[idx].get("name")
        result = self._results.get(name)
        if not result or not getattr(result, "output", ""):
            messagebox.showinfo("提示", f"「{name}」还没有成片。", parent=self)
            return
        self.on_open(Path(self.workspace()) / result.output)

    # ==================================================================
    # 日志
    # ==================================================================
    def _append_log(self, text: str):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
