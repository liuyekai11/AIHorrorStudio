"""GUI 冒烟测试：真实创建主窗口，自动建项目、导入图片、操作时间轴并截图。

用法（需要真实桌面环境）：
    python tests/gui_smoke.py [--shot out.png] [--keep 秒数]

它会在临时目录建一个项目，导入 3 张由 FFmpeg 生成的不同颜色图片，
然后依次：选择镜头、改时长、拖动时间轴播放头、切换运镜、截图。
任何异常都会以非 0 退出码结束，用于 CI / 回归。
"""
import argparse
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tkinter as tk  # noqa: E402

from modules.ffmpeg_locator import find_ffmpeg, find_ffprobe  # noqa: E402
from modules.main_window import HorrorStudioApp  # noqa: E402


def make_images(folder: Path, colors=("red", "green", "blue")):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise SystemExit("GUI 冒烟测试需要 FFmpeg 生成测试图片")
    paths = []
    for color in colors:
        p = folder / f"{color}.png"
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"color=c={color}:s=720x1280:d=1",
                        "-frames:v", "1", str(p)], check=True)
        paths.append(p)
    return paths


def capture(root: tk.Tk, path: Path):
    """用 FFmpeg gdigrab 截取窗口（按窗口位置）。"""
    ffmpeg = find_ffmpeg()
    # gdigrab 抓的是屏幕像素：必须把窗口提到最前并刷新，否则会抓到被遮挡的桌面
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    root.after(250, lambda: None)
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "gdigrab", "-offset_x", str(x), "-offset_y", str(y),
                    "-video_size", f"{w}x{h}", "-i", "desktop",
                    "-frames:v", "1", str(path)], check=True)
    root.attributes("-topmost", False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", default=None, help="编辑页截图保存路径")
    parser.add_argument("--story-shot", default=None, help="故事页截图保存路径")
    parser.add_argument("--ai-shot", default=None, help="AI 制作页截图保存路径")
    parser.add_argument("--batch-shot", default=None, help="批量页截图保存路径")
    parser.add_argument("--no-render", action="store_true", help="跳过成片渲染")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="ahs_gui_"))
    images = make_images(tmp)

    # 无人值守：所有确认框一律选“是”，避免冒烟测试卡在弹窗上
    import modules.main_window as mw
    mw.messagebox.askyesno = lambda *a, **k: True
    mw.messagebox.showwarning = lambda *a, **k: None
    mw.messagebox.showinfo = lambda *a, **k: None

    root = tk.Tk()
    root.update_idletasks()
    app = HorrorStudioApp(root)
    project = app.pm.create_project(tmp / "projects", "GUI Smoke")
    app._open(project)
    root.update()

    # 导入图片
    app.pm.add_images(project, images, 2.0)
    app._persist(reload=True)
    app.timeline.fit()
    root.update()
    assert len(app.data["shots"]) == 3, "导入后应有 3 个镜头"

    # 选择、改时长
    first = app.data["shots"][0]["id"]
    app._set_selection([first])
    root.update()
    app.apply_shot_duration(3.25)
    root.update()
    assert abs(app.data["shots"][1]["start"] - 3.25) < 1e-6, "改时长后应 reflow"

    # 运镜 / 过渡
    app.apply_shot_changes({"zoom": "in", "transition": "fade"})
    root.update()
    assert app.data["shots"][0]["zoom"] == "in"

    # 播放头 / 播放
    app.seek(1.5)
    root.update()
    app.start_play(fps=10)
    root.after(300, app.stop_play)
    for _ in range(5):
        root.update()
        root.after(60)
    app.stop_play()

    # 时间轴选中回调
    app.timeline.set_selection([app.data["shots"][1]["id"]], notify=True)
    root.update()

    # 截图
    if args.shot:
        try:
            capture(root, Path(args.shot))
            print(f"screenshot: {args.shot}")
        except Exception as exc:
            print(f"screenshot failed: {exc}")

    # 渲染
    if not args.no_render:
        from modules.render_engine import RenderEngine
        data = app.data
        settings = dict(data["settings"], width=360, height=640, fps=24)
        out = project / "output" / "smoke.mp4"
        RenderEngine().render(data, settings, out)
        assert out.exists() and out.stat().st_size > 0
        print(f"render ok: {out} ({out.stat().st_size} bytes)")

    # V1.2：故事页签 + 无图分镜导入 + 黑场渲染（不联网，注入假生成结果）
    app.show_tab("story")
    root.update()
    assert app.current_tab == "story", "应切换到故事页签"
    fake_story = {
        "title": "冒烟故事", "logline": "测试用", "keywords": "测试",
        "model": "fake", "shots": [
            {"index": 1, "scene": "灵堂", "narration": "它看着我。", "duration": 1.0},
            {"index": 2, "scene": "走廊", "narration": "它更近了。", "duration": 1.2},
        ],
    }
    app.story_panel.set_story(fake_story, keywords="测试")
    root.update()
    assert len(app.story_panel.tree.get_children()) == 2, "故事表格应有 2 行"
    if args.story_shot:
        try:
            capture(root, Path(args.story_shot))
            print(f"story screenshot: {args.story_shot}")
        except Exception as exc:
            print(f"story screenshot failed: {exc}")
    app.import_story(fake_story, replace=True)
    root.update()
    assert app.current_tab == "editor", "导入后应回到编辑页签"
    assert len(app.data["shots"]) == 2, "导入后应有 2 个分镜"
    assert app.data["shots"][0]["image"] is None, "故事分镜应为待配图"
    assert app.pm.get_story(app.data)["title"] == "冒烟故事", "story 应已保存"
    assert app.data.get("subtitle"), "旁白应已自动生成 SRT 字幕"
    cues = app._load_cues()
    assert cues and "它看着我" in cues[0][2], f"字幕应可解析：{cues[:1]}"
    if not args.no_render:
        from modules.render_engine import RenderEngine
        settings = dict(app.data["settings"], width=360, height=640, fps=24)
        story_out = project / "output" / "story.mp4"
        RenderEngine().render(app.data, settings, story_out)
        assert story_out.exists() and story_out.stat().st_size > 0
        print(f"story render ok: {story_out} ({story_out.stat().st_size} bytes)")
    app.show_tab("editor")
    root.update()

    # V1.3：AI 制作页签（假传输层，不联网、不花钱）
    ai_checks(root, app, project, tmp, args)

    # V2.2：五阶段故事流程（创意候选 → 选一个 → 完整剧本 → 评分 / 版本 / 恢复）
    story_flow_checks(root, app, project, args)

    # V2.0：批量页签（假引擎 + 后台线程 + 消息队列，不联网）
    batch_checks(root, app, tmp, args)

    root.destroy()
    print("GUI smoke OK")
    return 0


def story_flow_checks(root, app, project, args):
    """V2.2 故事页：创意候选 → 选定创意跑完整流水线 → 评分/版本展示 → 恢复版本。

    StoryEngine 的 5 个网络阶段换成假实现（不联网）；其余走真实的
    StoryPanel 回调、后台线程、project_manager 版本快照与恢复。
    """
    import time

    from modules import story_engine as se
    import modules.main_window as mw
    import modules.story_panel as sp

    def pump_until(predicate, timeout=60):
        deadline = time.monotonic() + timeout

        def check():
            if predicate() or time.monotonic() > deadline:
                root.quit()
            else:
                root.after(60, check)

        root.after(60, check)
        root.mainloop()
        return predicate()

    def concept(i):
        return {"concept_id": f"c{i}", "title": f"创意{i}", "logline": "一句话",
                "core_conflict": f"冲突{i}", "reversal_type": "identity",
                "horror_device": "纸人", "hook": f"钩子{i}",
                "ending_type": "closed", "duration_tier": "standard",
                "ruleset": "chinese_folk", "score_hint": ""}

    def fake_concepts(self, keywords, style="", extra="", duration_tier="standard",
                      count=3):
        self._notify("创意候选", "正在构思创意……")
        return [concept(i) for i in range(1, count + 1)]

    def fake_pipeline(self, concept_, keywords="", style="", extra="",
                      shot_count=None, use_model_review=True):
        self._notify("故事策划", "正在写故事策划……")
        self._notify("完整剧本", "正在写完整剧本……")
        # 注意：人物 / 场景目录留空，所以 character_ids / scene_id 必须也为空，
        # 否则导入分镜时会被判定为「引用了不存在的对象」而触发硬性否决。
        shots = [{"shot_id": f"s{i:03d}", "scene_id": "", "character_ids": [],
                  "image_prompt": f"画面{i}", "scene": f"画面{i}",
                  "narration": f"旁白{i}。", "duration": 2.0, "motion": "static",
                  "content_hash": f"h{i}"} for i in range(1, (shot_count or 3) + 1)]
        return {"schema_version": 2, "title": f"故事-{concept_['title']}",
                "logline": "梗概", "keywords": keywords, "style": style,
                "generated_at": "2026-11-04T00:00:00", "model": "fake",
                "characters": [], "scenes": [], "plan": {}, "script": [],
                "shots": shots,
                "quality": {"score": 88, "grade": "excellent",
                            "scores": {"logic": 18, "story_completeness": 19},
                            "vetoes": [], "issues": [], "passed": True}}

    originals = (se.StoryEngine.generate_concepts, se.StoryEngine.pipeline)
    se.StoryEngine.generate_concepts = fake_concepts
    se.StoryEngine.pipeline = fake_pipeline
    try:
        app.show_tab("story")
        root.update()
        panel = app.story_panel
        panel.keywords_text.delete("1.0", "end")
        panel.keywords_text.insert("1.0", "废弃医院、纸人")
        panel.count_scale.set(4)
        panel.count_var.set(6)   # 固定 6 镜：Scale.set 的精度取决于滑块像素，不可靠

        # 1. 生成创意候选
        panel._on_generate()
        root.update()
        assert len(panel.concepts) == 3, f"应有 3 个创意：{panel.concepts}"
        rows = panel.concept_tree.get_children()
        assert len(rows) == 3, "创意表格应有 3 行"
        panel.concept_tree.selection_set(rows[1])
        root.update()
        assert str(panel.use_concept_btn.cget("state")) == "normal", \
            "选定创意后「写完整剧本」应可用"
        if args.story_shot:
            # 截图时多看一张：创意候选视图
            try:
                capture(root, Path(args.story_shot).with_name("story_concepts.png"))
            except Exception as exc:
                print(f"concept screenshot failed: {exc}")

        # 2. 选第二个创意 → 跑完整流水线
        panel._use_concept()
        root.update()
        assert panel.story and panel.story["title"] == "故事-创意2", \
            f"应按选定创意创作：{panel.story and panel.story.get('title')}"
        assert len(panel.tree.get_children()) == 6, "分镜表应有 6 行"
        assert "88" in panel.score_label.cget("text"), "应显示质量分"
        assert panel.last_log, "应记录阶段日志"

        # 3. 保存 → 版本入库
        app.save_story(panel.story)
        root.update()
        versions = app._story_versions()
        assert versions, "保存后应有版本记录"

        # 4. 改一版并保存，再恢复到第一版
        first_id = versions[0]["version_id"]
        panel.story["shots"] = panel.story["shots"][:2]
        panel.story["title"] = "故事-剪短版"
        app.save_story(panel.story)
        root.update()
        assert len(app._story_versions()) > 1
        panel.set_versions(app._story_versions())
        app.restore_story_version(first_id)
        root.update()
        restored = app.pm.get_story(app.data)
        assert restored["title"] == "故事-创意2", f"恢复后标题：{restored['title']}"
        assert len(restored["shots"]) == 6, "恢复后应回到 6 镜"
        assert len(panel.tree.get_children()) == 6, "面板应刷新为恢复后的分镜"
        print("story flow ok:", [v["version_id"] for v in app._story_versions()])
    finally:
        se.StoryEngine.generate_concepts = originals[0]
        se.StoryEngine.pipeline = originals[1]
        assert sp is not None and mw is not None


def ai_checks(root, app, project, tmp, args):
    """在「AI 制作」页签里跑一遍出图 → 配音 → 音轨 → 出片，全程假网络。

    网络调用全部替换成 FFmpeg 生成的假素材：出图 = 色块 PNG，配音 = 正弦波 WAV。
    后台线程与消息队列走真实路径，验证整条流水线的串联。
    """
    import time
    import subprocess as sp
    from modules import image_engine, voice_engine, sf_config
    import modules.main_window as mw

    ffmpeg = find_ffmpeg()

    # 构造 2 镜带旁白的故事分镜
    app.show_tab("ai")
    fake_story = {
        "title": "AI 流水线", "logline": "测试用", "keywords": "测试", "model": "fake",
        "shots": [
            {"index": 1, "scene": "雨夜的灵堂，纸人立在棺旁", "narration": "它看着我。", "duration": 1.5},
            {"index": 2, "scene": "漆黑的走廊尽头有影子", "narration": "它更近了。", "duration": 1.5},
        ],
    }
    app.import_story(fake_story, replace=True)
    root.update()

    def pump_until(predicate, timeout=120):
        """在 Tk 事件循环里等待异步任务结束（渲染 / AI 都通过 after 定时器排队）。"""
        deadline = time.monotonic() + timeout

        def check():
            if predicate() or time.monotonic() > deadline:
                root.quit()
            else:
                root.after(80, check)

        root.after(80, check)
        root.mainloop()
        return predicate()

    def wait_idle(timeout=120):
        """等 AI 任务结束：ai_busy 由后台线程回报的消息清零。"""
        ok = pump_until(lambda: not app.ai_busy, timeout)
        assert ok, "AI 任务超时（后台线程未回报完成）"
        return ok

    # 假配置：通过「未配置 Key」检查
    fake_cfg = {"api_key": "sk-fake-for-smoke", "_from_env": False,
                "image_model": "Kwai-Kolors/Kolors", "voice": "claire"}
    real_load = sf_config.load_config
    sf_config.load_config = lambda: dict(fake_cfg)
    mw.sf_config.load_config = sf_config.load_config

    # 假出图 / 假配音：网络换成 FFmpeg 生成
    def gen(self, scene, target, size=None, style="", extra=""):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        color = "red" if "灵堂" in (scene or "") else "green"
        sp.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=720x1280:d=1",
                "-frames:v", "1", str(target)], check=True)
        return str(target)

    def tts(self, text, target, speed=None, fmt="wav"):
        # 用不同的频率编码语速，验证面板上的语速真的传到了引擎
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        freq = 440 if not speed else int(round(440 / float(speed)))
        sp.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=0.9",
                str(target)], check=True)
        return Path(target)

    originals = (image_engine.ImageEngine.generate_to_file,
                 voice_engine.VoiceEngine.synthesize_to_file)
    image_engine.ImageEngine.generate_to_file = gen
    voice_engine.VoiceEngine.synthesize_to_file = tts
    try:
        app.show_tab("ai")
        root.update()
        assert app.current_tab == "ai", "应切换到 AI 制作页签"
        app.ai_panel.set_shots(app.data["shots"], project)
        root.update()
        if args.ai_shot:
            try:
                capture(root, Path(args.ai_shot))
                print(f"ai screenshot: {args.ai_shot}")
            except Exception as exc:
                print(f"ai screenshot failed: {exc}")

        # -- 出图 ------------------------------------------------------
        app.generate_all_images(force=False)
        wait_idle()
        root.update()
        assert all(s.get("ai_image") for s in app.data["shots"]), "出图后每镜都应有 AI 画面"
        assert all(s.get("image") for s in app.data["shots"]), "AI 画面应同时设为镜头画面"
        print("ai images ok:", [s["ai_image"] for s in app.data["shots"]])

        # -- 配音 + 自动拼音轨 ------------------------------------------
        from modules import sf_config as _sfc
        app.ai_panel.speed_var.set(_sfc.speed_label(0.75))
        self_speed = app.ai_panel.voice_speed()
        assert abs(self_speed - 0.75) < 1e-6, f"面板语速应为 0.75：{self_speed}"
        app.generate_all_voices(force=False)
        wait_idle()
        root.update()
        assert all(s.get("voice") for s in app.data["shots"]), "配音后每镜都应有 voice"
        assert all((s.get("voice_ms") or 0) > 0 for s in app.data["shots"]), \
            "配音应记录时长（voice_ms）"
        assert app.data.get("voice_track"), "配音后应自动拼出旁白音轨"
        track = project / app.data["voice_track"]
        assert track.exists() and track.stat().st_size > 0, "旁白音轨文件应存在"
        # 自动对齐：0.9s 配音 + 留白 → 每镜时长应长于配音本身
        offset = app.pm.voice_offset_ms(app.data) / 1000.0
        for s in app.data["shots"]:
            assert s["duration"] >= offset + (s["voice_ms"] or 0) / 1000.0 - 0.01, \
                f"镜头时长应对齐配音：{s['duration']} vs {s['voice_ms']}ms"
        print(f"ai voices ok: {app.data['voice_track']} "
              f"(durations={[s['duration'] for s in app.data['shots']]})")

        # 语速确实传到了引擎：假 TTS 把语速编码成音高（0.75x → 587Hz）
        wav = project / app.data["shots"][0]["voice"]
        raw = sp.run([ffmpeg, "-v", "error", "-i", str(wav), "-ac", "1",
                      "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
        samples = [int(v) for v in memoryview(raw).cast("h")]
        crossings = sum(1 for a, b in zip(samples, samples[1:]) if a < 0 <= b)
        freq = crossings / 0.9
        assert abs(freq - 587) < 45, f"0.75x 语速应产生约 587Hz，实际 {freq:.0f}Hz"
        print(f"ai speed ok: {freq:.0f}Hz for 0.75x")

        # -- 直接出片 ----------------------------------------------------
        app.render_ai()
        assert pump_until(lambda: not app.rendering), "渲染超时"
        root.update()
        out = project / "output" / f"{app.data.get('name', 'project')}_final.mp4"
        assert out.exists() and out.stat().st_size > 0, f"成片未生成：{out}"
        streams = sp.run([find_ffprobe(ffmpeg),
                          "-v", "error", "-show_entries", "stream=codec_type",
                          "-of", "csv=p=0", str(out)],
                         capture_output=True, text=True).stdout
        assert "audio" in streams and "video" in streams, f"成片应有音视频流：{streams}"
        print(f"ai render ok: {out} ({out.stat().st_size} bytes, "
              f"streams={streams.split()})")

        # -- 清除配音 ----------------------------------------------------
        app.ai_panel.set_shots(app.data["shots"], project)
        app.clear_voices()
        root.update()
        assert not any(s.get("voice") for s in app.data["shots"]), "清除配音后应无 voice"
        print("ai clear voices ok")
    finally:
        image_engine.ImageEngine.generate_to_file = originals[0]
        voice_engine.VoiceEngine.synthesize_to_file = originals[1]
        mw.sf_config.load_config = real_load
        sf_config.load_config = real_load


def batch_checks(root, app, tmp, args):
    """在「批量」页签里跑两个项目的完整批量（假引擎、假渲染，不联网）。

    覆盖：任务清单编辑、批量页签 UI、后台线程 + 消息队列 + 进度事件、
    成片落盘。网络调用全部换成 FFmpeg 生成：出图 = 色块，配音 = 正弦波。
    """
    import json as _json
    import subprocess as sp
    import time

    from modules import batch as batch_mod
    from modules import sf_config
    import modules.main_window as mw
    from modules.batch_panel import JOBS_FILE

    # 冒烟测试不碰用户的真实任务清单（结束时还原）
    real_jobs_file = JOBS_FILE
    real_jobs_content = real_jobs_file.read_text(encoding="utf-8") \
        if real_jobs_file.exists() else None

    ffmpeg = find_ffmpeg()
    workspace = tmp / "batch_out"

    def pump_until(predicate, timeout=180):
        deadline = time.monotonic() + timeout

        def check():
            if predicate() or time.monotonic() > deadline:
                root.quit()
            else:
                root.after(80, check)

        root.after(80, check)
        root.mainloop()
        return predicate()

    app.show_tab("batch")
    root.update()
    assert app.current_tab == "batch", "应切换到批量页签"

    # 任务清单：面板真实编辑 + 持久化
    panel = app.batch_panel
    panel.workspace_var.set(str(workspace))
    panel.preset_var.set("360x640（竖屏小样·快）")
    panel.fill_editor("批量冒烟A", "雨夜 旗袍 纸人", 2, "中式恐怖", "")
    panel.add_or_update()
    panel.fill_editor("批量冒烟B", "电梯 午夜 无人", 2, "", "结尾留悬念")
    panel.add_or_update()
    root.update()
    assert len(panel.tree.get_children()) == 2, "任务清单应有 2 行"
    data = _json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    assert data["workspace"] == str(workspace), f"输出目录应持久化：{data.get('workspace')}"
    assert [j["name"] for j in data["jobs"]] == ["批量冒烟A", "批量冒烟B"]

    if args.batch_shot:
        try:
            capture(root, Path(args.batch_shot))
            print(f"batch screenshot: {args.batch_shot}")
        except Exception as exc:
            print(f"batch screenshot failed: {exc}")

    # 假引擎：网络换成 FFmpeg 生成（与 ai_checks 一致的做法）
    def gen(self, scene, target, size=None, style="", extra=""):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        color = "red" if "雨夜" in (scene or "") else "green"
        sp.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=720x1280:d=1",
                "-frames:v", "1", str(target)], check=True)
        return str(target)

    def tts(self, text, target, speed=None, fmt="wav"):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        sp.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=0.9",
                str(target)], check=True)
        return Path(target)

    import modules.image_engine as ie
    import modules.voice_engine as ve
    import modules.story_engine as se
    originals = (ie.ImageEngine.generate_to_file,
                 ve.VoiceEngine.synthesize_to_file,
                 se.StoryEngine.generate)

    def fake_generate(self, keywords, shot_count=8, style="", extra=""):
        return {
            "title": f"批量-{keywords}", "logline": f"{keywords} 的一句话梗概",
            "keywords": keywords, "model": "fake",
            "shots": [{"index": i + 1, "scene": f"{keywords} 场景{i + 1}",
                       "narration": f"{keywords}，第{i + 1}句旁白。", "duration": 2.0}
                      for i in range(shot_count)],
        }

    def fake_render(data, settings, output):
        # 真渲染太慢：验证 settings 覆盖后写一个占位成片
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_bytes(b"mp4")
        assert settings.get("width") == 360, f"批量应使用小样尺寸：{settings}"
        return Path(output)

    ie.ImageEngine.generate_to_file = gen
    ve.VoiceEngine.synthesize_to_file = tts
    se.StoryEngine.generate = fake_generate
    orig_render = batch_mod.BatchRunner._default_render
    batch_mod.BatchRunner._default_render = staticmethod(fake_render)
    # 冒烟环境下批量用的配置也指向假 Key
    real_sf_load = sf_config.load_config
    real_ds_load = mw.ai_config.load_config
    sf_config.load_config = lambda: {
        "api_key": "sk-fake-for-smoke", "image_model": "Kwai-Kolors/Kolors",
        "voice": "claire", "voice_speed": 1.0}
    mw.sf_config.load_config = sf_config.load_config
    mw.ai_config.load_config = lambda: {"api_key": "sk-fake-ds"}
    # 确认框自动点「是」
    import modules.batch_panel as bp
    bp.messagebox.askyesno = lambda *a, **k: True
    bp.messagebox.showwarning = lambda *a, **k: None
    bp.messagebox.showinfo = lambda *a, **k: None
    mw.messagebox.askyesno = lambda *a, **k: True
    try:
        panel.start()
        root.update()
        assert panel.busy, "开始后应进入 busy 状态"
        assert pump_until(lambda: not panel.busy), "批量任务超时"
        root.update()
        # 结果：2 个项目都成功，成片落盘
        rows = panel._rows
        assert [r["status"] for r in rows] == ["ok", "ok"], \
            f"两个项目都应成功：{[(r['name'], r['status'], r['detail']) for r in rows]}"
        for name in ("批量冒烟A", "批量冒烟B"):
            out = workspace / name / "output" / f"{name}_final.mp4"
            assert out.exists() and out.stat().st_size > 0, f"成片应存在：{out}"
            data = app.pm.load(workspace / name)
            assert all(s.get("ai_image") for s in data["shots"]), f"{name} 出图缺失"
            assert all(s.get("voice") for s in data["shots"]), f"{name} 配音缺失"
            assert data.get("voice_track"), f"{name} 应有旁白音轨"
            assert data.get("subtitle"), f"{name} 应有字幕"
        print("batch panel ok:", [(r["name"], r["status"]) for r in rows])
        assert "成功" in panel.progress_label.cget("text"), \
            f"完成提示：{panel.progress_label.cget('text')}"
        # 停止按钮在空闲时应不可用
        assert str(panel.stop_btn.cget("state")) == "disabled"
    finally:
        ie.ImageEngine.generate_to_file = originals[0]
        ve.VoiceEngine.synthesize_to_file = originals[1]
        se.StoryEngine.generate = originals[2]
        batch_mod.BatchRunner._default_render = orig_render
        sf_config.load_config = real_sf_load
        mw.sf_config.load_config = real_sf_load
        mw.ai_config.load_config = real_ds_load
        if real_jobs_content is not None:
            real_jobs_file.write_text(real_jobs_content, encoding="utf-8")
        else:
            real_jobs_file.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
