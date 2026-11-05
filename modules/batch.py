"""批量生产器（V2.0）：一次跑 N 个项目，从故事到成片全自动。

流程（每个项目一条流水线）：
    建项目 → 生成故事 → 导入分镜 → AI 出图 → AI 配音(含对齐) → 渲染成片

设计
----
* 纯逻辑模块：不 import tkinter，不弹窗。进度用回调 `report(event, **info)`
  上报，界面层（batch_panel）只消费事件。这样整个批量引擎可以脱离 GUI 测试。
* 每个项目完全隔离：一个项目任何一步失败，记录后继续下一个项目，
  不中断整批；项目内部单镜失败也不中断该项目（和单项目版一致）。
* 所有网络调用经由注入的引擎（story_engine / image_engine / voice_engine），
  测试时注入假引擎，不联网、不花钱。渲染函数也可注入。
"""
import time
from pathlib import Path

from modules.project_manager import ProjectManager, ProjectError, material_name_for
from modules.story_engine import to_project_shots

# 每个项目之间的间隔秒数（给限流留余量）；测试时置 0
GAP_SECONDS = 1.0


class BatchError(Exception):
    """批量任务配置错误（启动前就能发现的）。"""


class BatchJob:
    """一个待生产的项目。"""

    def __init__(self, name: str, keywords: str, shot_count: int = 8,
                 style: str = "", extra: str = ""):
        self.name = (name or "").strip() or "未命名"
        self.keywords = (keywords or "").strip()
        self.shot_count = int(shot_count)
        self.style = (style or "").strip()
        self.extra = (extra or "").strip()

    def validate(self) -> str | None:
        if not self.keywords:
            return f"「{self.name}」缺少题材关键词"
        return None


class BatchResult:
    """一个项目跑完的结果（ok 或 error）。"""

    def __init__(self, name: str, status: str, detail: str = "", output: str = ""):
        self.name = name
        self.status = status          # "ok" / "error"
        self.detail = detail          # 错误摘要或部分失败说明（可展示）
        self.output = output          # 成片相对路径（相对 workspace）

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class BatchRunner:
    """批量执行器：一次跑完 jobs 里的所有项目。"""

    def __init__(self, workspace: Path, jobs: list[BatchJob],
                 story_engine=None, image_engine=None, voice_engine=None,
                 pm: ProjectManager | None = None,
                 render=None, settings: dict | None = None,
                 normalizer=None, cancel=None):
        self.workspace = Path(workspace)
        self.jobs = list(jobs)
        self.story_engine = story_engine
        self.image_engine = image_engine
        self.voice_engine = voice_engine
        self.pm = pm or ProjectManager()
        self.render = render or self._default_render
        # 出图后的尺寸归一化（真实调用 FFmpeg）；测试可注入空实现
        self.normalizer = normalizer or self._default_normalize
        # 返回 True 时在当前项目跑完后结束整批（不打断正在跑的项目）
        self.cancel = cancel or (lambda: False)
        # 显式 settings 覆盖项目默认（批量出竖屏小样时用小尺寸加快渲染）
        self.settings = dict(settings) if settings else None

    # ------------------------------------------------------------------
    @staticmethod
    def _default_render(data: dict, settings: dict, output: Path) -> Path:
        from modules.render_engine import RenderEngine
        return RenderEngine().render(data, settings, output)

    @staticmethod
    def _default_normalize(path: Path, width: int, height: int, fit: str = "cover"):
        from modules import media_tools
        media_tools.normalize_image(path, path, width, height, fit=fit)

    def validate(self) -> list[str]:
        errors = []
        if not self.jobs:
            errors.append("没有待生产的项目（至少 1 个）")
        names = [j.name for j in self.jobs]
        if len(names) != len(set(names)):
            errors.append("项目名称重复")
        for job in self.jobs:
            err = job.validate()
            if err:
                errors.append(err)
        return errors

    # ------------------------------------------------------------------
    def run(self, report=None) -> list[BatchResult]:
        """跑完整批。report(event, **info) 收事件；返回每个项目的结果。

        事件：batch_start / project_start / step / project_done /
              project_error / batch_done
        """
        report = report or (lambda *a, **k: None)
        errors = self.validate()
        if errors:
            raise BatchError("；".join(errors))
        self.workspace.mkdir(parents=True, exist_ok=True)

        report("batch_start", total=len(self.jobs))
        results: list[BatchResult] = []
        for index, job in enumerate(self.jobs, 1):
            report("project_start", name=job.name, keywords=job.keywords,
                   index=index, total=len(self.jobs))
            result = self._run_one(job, report)
            results.append(result)
            if result.ok:
                report("project_done", name=job.name, status=result.status,
                       detail=result.detail, output=result.output,
                       index=index, total=len(self.jobs))
            else:
                report("project_error", name=job.name, status=result.status,
                       detail=result.detail, index=index, total=len(self.jobs))
            if index < len(self.jobs) and GAP_SECONDS > 0:
                time.sleep(GAP_SECONDS)
            if self.cancel():
                skipped = len(self.jobs) - index
                if skipped:
                    results.extend(
                        BatchResult(j.name, "error", "已停止（未运行）")
                        for j in self.jobs[index:])
                report("batch_stop", stopped_at=index, skipped=skipped)
                break
        report("batch_done", total=len(results),
               ok=sum(1 for r in results if r.ok))
        return results

    # ------------------------------------------------------------------
    def _run_one(self, job: BatchJob, report) -> BatchResult:
        try:
            project = self.pm.create_project(self.workspace, job.name)
        except ProjectError as exc:
            return BatchResult(job.name, "error", f"建项目失败：{exc}")
        try:
            return self._pipeline(job, project, report)
        except Exception as exc:  # noqa: BLE001 - 单项目失败不中断整批
            detail = str(exc) or type(exc).__name__
            return BatchResult(job.name, "error", detail)

    # ------------------------------------------------------------------
    def _pipeline(self, job: BatchJob, project: Path, report) -> BatchResult:
        def step(text: str):
            report("step", name=job.name, text=text)

        # 1. 故事（V2.2：有 on_stage 就上报五阶段进度；假引擎没有这个属性就照常生成）
        step("生成故事…")
        can_report = hasattr(self.story_engine, "on_stage")
        if can_report:
            self.story_engine.on_stage = (
                lambda stage, text: step(f"故事 · {stage}：{text}"))
        try:
            story = self.story_engine.generate(
                job.keywords, job.shot_count, job.style, job.extra)
        finally:
            if can_report:
                try:
                    self.story_engine.on_stage = None
                except Exception:  # noqa: BLE001 - 属性只读时忽略
                    pass
        self.pm.set_story(project, story)
        style_hint = (story.get("logline") or "").strip()
        story["style"] = job.style
        story["keywords"] = job.keywords

        # 2. 导入分镜
        step("导入分镜…")
        new_shots = to_project_shots(story)
        for i, shot in enumerate(new_shots):
            shot["story_index"] = i + 1
        # 用返回值：这里才是带 id 的规范化镜头（入参 dict 没有 id）
        shots = self.pm.replace_all_shots(project, new_shots)

        # 3. 旁白字幕（先按建议时长导一版，配音对齐后会重导）
        self._export_srt(project)

        # 4. 出图
        step(f"AI 出图 {len(shots)} 镜…")
        image_failures = self._generate_images(project, shots, story, step)

        # 5. 配音 + 按配音对齐时长 + 拼音轨
        step(f"AI 配音 {len(shots)} 镜…")
        voice_failed = self._generate_voices(project, shots, story, step)

        # 6. 渲染
        step("渲染成片…")
        data = self.pm.load(project)
        output = project / "output" / f"{data['name']}_final.mp4"
        self.render(data, self.settings or data["settings"], output)

        notes = []
        if image_failures:
            notes.append(f"{len(image_failures)} 镜出图失败（渲染为黑场）")
        if voice_failed:
            notes.append(f"{voice_failed} 镜配音失败（跳过）")
        return BatchResult(job.name, "ok", "；".join(notes),
                           output=str(output.relative_to(self.workspace)))

    # ------------------------------------------------------------------
    def _export_srt(self, project: Path):
        srt = project / "subtitles" / "story_narration.srt"
        self.pm.export_srt(project, srt)
        data = self.pm.load(project)
        data["subtitle"] = str(srt.relative_to(project)).replace("\\", "/")
        self.pm.save(project, data)

    def _generate_images(self, project: Path, shots: list[dict],
                         story: dict, step) -> list[str]:
        from modules.image_engine import build_consistency_hint, pick_size
        settings = self.settings or self.pm.load(project)["settings"]
        model = getattr(self.image_engine, "model", "") or ""
        size = pick_size(settings["width"], settings["height"], model)
        style_key = self.image_style()
        story_shots = {s.get("shot_id"): s for s in (story.get("shots") or [])
                       if isinstance(s, dict)}
        failures = []
        for i, shot in enumerate(shots, 1):
            scene = (shot.get("scene") or shot.get("narration") or "").strip()
            if not scene:
                continue
            target = project / "images" / material_name_for(shot, "image")
            try:
                step(f"出图 {i}/{len(shots)}")
                # V2.2：只带这一镜实际出现的角色 / 场景卡，画风统一走漫画预设
                story_shot = story_shots.get(shot.get("shot_id")) or {}
                hint = build_consistency_hint(story, scene, story_shot)
                try:
                    self.image_engine.generate_to_file(scene, target, style=style_key,
                                                       extra=hint, size=size)
                except TypeError:
                    # 测试用的假引擎只接受 (scene, target, style=)
                    self.image_engine.generate_to_file(scene, target, style=style_key)
                self._normalize(target, settings)
                self.pm.set_ai_image(project, shot["id"], target)
            except Exception as exc:  # noqa: BLE001 - 单镜失败不中断
                failures.append(f"#{i} {exc}")
        return failures

    def _normalize(self, target: Path, settings: dict):
        """按项目 fit 适配画面；测试注入的 normalizer 只接收 3 个参数时回落。"""
        try:
            self.normalizer(target, settings["width"], settings["height"],
                            settings.get("fit", "cover"))
        except TypeError:
            self.normalizer(target, settings["width"], settings["height"])

    @staticmethod
    def image_style() -> str:
        """批量出图用的画风：AI 设置里的 image_style（默认暗黑漫画）。"""
        from modules import sf_config
        style = sf_config.load_config().get("image_style") or "comic_dark"
        from modules.image_engine import STYLE_PRESETS
        return style if style in STYLE_PRESETS else "comic_dark"

    def _voice_style(self, story: dict) -> str:
        """按故事题材挑配音预设（auto 时从关键词推断；用户手动选过就尊重设置）。"""
        from modules import sf_config, story_engine
        configured = sf_config.load_config().get("voice_style") or "auto"
        if configured != "auto":
            return configured
        return story_engine.infer_style(story.get("keywords", ""),
                                        story.get("style", ""))

    def _generate_voices(self, project: Path, shots: list[dict],
                         story: dict, step) -> int:
        from modules import media_tools
        failed = 0
        prev_style = None
        config = getattr(self.voice_engine, "config", None)
        if isinstance(config, dict):
            prev_style = config.get("voice_style")
            config["voice_style"] = self._voice_style(story)
        try:
            for i, shot in enumerate(shots, 1):
                text = (shot.get("narration") or "").strip()
                if not text:
                    continue
                target = project / "audio" / material_name_for(shot, "voice")
                try:
                    step(f"配音 {i}/{len(shots)}")
                    self.voice_engine.synthesize_to_file(text, target)
                    # 裁掉 TTS 首尾静音，否则句尾的 1 秒多死寂会被算进镜头
                    media_tools.trim_silence(target)
                    ms = int(round(media_tools.audio_duration(target) * 1000))
                    self.pm.set_voice(project, shot["id"], target, ms)
                except Exception as exc:  # noqa: BLE001 - 单镜失败不中断
                    failed += 1
        finally:
            if isinstance(config, dict) and config.get("voice_style") != prev_style:
                if prev_style is None:
                    config.pop("voice_style", None)
                else:
                    config["voice_style"] = prev_style
        data = self.pm.load(project)
        if any(s.get("voice") for s in data["shots"]):
            step("按画面节奏对齐时长并拼音轨…")
            self.pm.fit_durations_to_voice(project)
            data = self.pm.load(project)
            segments = self.pm.voice_segments(data)
            track = project / "audio" / "voice_track.wav"
            media_tools.concat_audio(
                [(project / rel, start, dur) for rel, start, dur in segments],
                track, self.pm.total_duration(data),
                offset_ms=self.pm.voice_offset_ms(data))
            data["narration"] = str(track.relative_to(project)).replace("\\", "/")
            data["voice_track"] = data["narration"]
            self.pm.save(project, data)
            # 时长变了，字幕边界重导
            self._export_srt(project)
        return failed
