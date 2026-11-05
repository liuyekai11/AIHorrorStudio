"""批量生产器测试：任务校验、流水线串联、单项目失败隔离、事件流、断点数据。

全部使用假引擎与假渲染，不联网、不调用 FFmpeg。
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import batch  # noqa: E402
from modules import image_engine as ie  # noqa: E402
from modules.project_manager import ProjectManager  # noqa: E402


def make_story(keywords, shot_count=2):
    return {
        "title": f"故事-{keywords}", "logline": "一句狠话", "keywords": keywords,
        "model": "fake",
        "shots": [{"index": i + 1, "scene": f"场景{i + 1} {keywords}",
                   "narration": f"旁白{i + 1}。", "duration": 2.0}
                  for i in range(shot_count)],
    }


class FakeStory:
    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = set(fail_on)

    def generate(self, keywords, shot_count=8, style="", extra=""):
        self.calls.append(keywords)
        if keywords in self.fail_on:
            raise RuntimeError(f"故事生成失败：{keywords}")
        return make_story(keywords, shot_count)


class FakeImage:
    def __init__(self, fail_scenes=()):
        self.calls = []
        self.fail_scenes = fail_scenes

    def generate_to_file(self, scene, target, size=None, style=""):
        self.calls.append(scene)
        if any(s in scene for s in self.fail_scenes):
            raise RuntimeError("出图失败")
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(b"png")
        return str(target)


class FakeVoice:
    def __init__(self, fail_texts=()):
        self.calls = []
        self.fail_texts = fail_texts

    def synthesize_to_file(self, text, target, speed=None, fmt="wav"):
        import wave
        self.calls.append(text)
        if any(t in text for t in self.fail_texts):
            raise RuntimeError("配音失败")
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(b"\x00\x10" * 8000)   # 1 秒
        return Path(target)


class BatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_batch_"))
        self.workspace = self.tmp / "out"
        self.events = []
        self._gap = batch.GAP_SECONDS
        batch.GAP_SECONDS = 0          # 测试不真等
        # 假出图写的是占位字节，真实 FFmpeg 归一化会失败 → 换成空实现
        self.normalized = []
        def noop_normalize(path, width, height):
            self.normalized.append((Path(path).name, width, height))

        self._noop_normalize = noop_normalize

    def tearDown(self):
        batch.GAP_SECONDS = self._gap
        shutil.rmtree(self.tmp, ignore_errors=True)

    def report(self, event, **info):
        self.events.append((event, info))

    def make_runner(self, jobs, story=None, image=None, voice=None,
                    render=None, pm=None, normalizer=None):
        return batch.BatchRunner(
            self.workspace, jobs,
            story_engine=story or FakeStory(),
            image_engine=image or FakeImage(),
            voice_engine=voice or FakeVoice(),
            pm=pm or ProjectManager(),
            render=render or (lambda data, settings, output: (
                Path(output).parent.mkdir(parents=True, exist_ok=True),
                Path(output).write_bytes(b"mp4"), output)[-1]),
            normalizer=normalizer or self._noop_normalize)

    def jobs(self, n=2, shot_count=2):
        return [batch.BatchJob(f"项目{i + 1}", f"关键词{i + 1}", shot_count)
                for i in range(n)]

    # ------------------------------------------------------------------
    def test_validate(self):
        runner = self.make_runner([batch.BatchJob("a", ""), batch.BatchJob("a", "x")])
        errors = runner.validate()
        self.assertTrue(any("关键词" in e for e in errors))
        self.assertTrue(any("重复" in e for e in errors))
        self.assertTrue(self.make_runner([]).validate())

    def test_validate_raises_on_run(self):
        runner = self.make_runner([batch.BatchJob("a", "")])
        with self.assertRaises(batch.BatchError):
            runner.run(self.report)

    def test_happy_path(self):
        story, image, voice = FakeStory(), FakeImage(), FakeVoice()
        results = self.make_runner(self.jobs(), story, image, voice).run(self.report)
        self.assertEqual([r.status for r in results], ["ok", "ok"])
        self.assertEqual(story.calls, ["关键词1", "关键词2"])
        self.assertEqual(len(image.calls), 4)     # 2 项目 × 2 镜
        self.assertEqual(len(voice.calls), 4)
        for r in results:
            self.assertTrue((self.workspace / r.output).exists())
            data = ProjectManager().load(self.workspace / r.name)
            self.assertTrue(all(s["ai_image"] for s in data["shots"]))
            self.assertTrue(all(s["voice"] for s in data["shots"]))
            self.assertTrue(data.get("voice_track"))
            self.assertTrue(data.get("subtitle"))
            self.assertEqual(data["story"]["title"],
                             f"故事-{r.name.replace('项目', '关键词')}")
        # 归一化在每张出图后都应被调用，尺寸取自项目 settings
        self.assertEqual(len(self.normalized), 4)     # 2 项目 × 2 镜
        self.assertTrue(all(w == 1080 and h == 1920
                            for _, w, h in self.normalized))

    def test_events_order(self):
        self.make_runner(self.jobs(2)).run(self.report)
        kinds = [e for e, _ in self.events]
        self.assertEqual(kinds[0], "batch_start")
        self.assertEqual(kinds[-1], "batch_done")
        self.assertEqual(kinds.count("project_start"), 2)
        self.assertEqual(kinds.count("project_done"), 2)
        done = [i for i, k in enumerate(kinds) if k == "project_done"]
        self.assertEqual(self.events[done[0]][1]["index"], 1)
        self.assertEqual(self.events[done[1]][1]["index"], 2)
        self.assertEqual(self.events[-1][1], {"total": 2, "ok": 2})

    def test_story_failure_isolated(self):
        story = FakeStory(fail_on={"关键词1"})
        results = self.make_runner(self.jobs(2), story=story).run(self.report)
        self.assertEqual(results[0].status, "error")
        self.assertIn("故事生成失败", results[0].detail)
        self.assertEqual(results[1].status, "ok")   # 第二个项目照常完成
        self.assertEqual(self.events[-1][1]["ok"], 1)

    def test_one_shot_image_failure_still_renders(self):
        image = FakeImage(fail_scenes=("场景1",))
        results = self.make_runner(self.jobs(1), image=image).run(self.report)
        self.assertEqual(results[0].status, "ok")
        self.assertIn("出图失败", results[0].detail)
        data = ProjectManager().load(self.workspace / results[0].name)
        self.assertIsNone(data["shots"][0]["ai_image"])
        self.assertTrue(data["shots"][1]["ai_image"])

    def test_voice_failure_still_renders(self):
        voice = FakeVoice(fail_texts=("旁白1",))
        results = self.make_runner(self.jobs(1), voice=voice).run(self.report)
        self.assertEqual(results[0].status, "ok")
        self.assertTrue(results[0].detail)

    def test_duplicate_name_creates_error_not_crash(self):
        # 同名目录已存在 → 第二个项目建项目失败，但整批不中断
        self.make_runner([batch.BatchJob("同名", "a")]).run(self.report)
        results = self.make_runner([batch.BatchJob("同名", "a")]).run(self.report)
        self.assertEqual(results[0].status, "error")
        self.assertIn("建项目失败", results[0].detail)

    def test_normalize_failure_marks_shot_not_batch(self):
        # 归一化（FFmpeg）失败只影响该镜，项目仍出片
        def boom(path, w, h):
            raise RuntimeError("图片尺寸调整失败")

        results = self.make_runner(self.jobs(1), normalizer=boom).run(self.report)
        self.assertEqual(results[0].status, "ok")
        self.assertIn("出图失败", results[0].detail)
        data = ProjectManager().load(self.workspace / results[0].name)
        self.assertTrue(all(s["ai_image"] is None for s in data["shots"]))

    def test_cancel_stops_after_current_project(self):
        # 第 1 个项目跑完就请求停止 → 第 2 个不运行，但结果列表长度不变
        calls = {"n": 0}

        def cancel():
            calls["n"] += 1
            return calls["n"] >= 1

        story = FakeStory()
        runner = batch.BatchRunner(
            self.workspace, self.jobs(3), story_engine=story,
            image_engine=FakeImage(), voice_engine=FakeVoice(),
            render=lambda d, s, o: (Path(o).parent.mkdir(parents=True, exist_ok=True),
                                    Path(o).write_bytes(b"mp4"), o)[-1],
            normalizer=self._noop_normalize, cancel=cancel)
        results = runner.run(self.report)
        self.assertEqual(len(results), 3)
        self.assertEqual([r.status for r in results], ["ok", "error", "error"])
        self.assertIn("已停止", results[1].detail)
        self.assertEqual(len(story.calls), 1)
        kinds = [e for e, _ in self.events]
        self.assertIn("batch_stop", kinds)
        self.assertEqual(kinds[-1], "batch_done")
        self.assertEqual(self.events[-1][1], {"total": 3, "ok": 1})

    def test_render_settings_override(self):
        seen = {}

        def fake_render(data, settings, output):
            seen["settings"] = settings
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(b"mp4")
            return Path(output)

        runner = batch.BatchRunner(
            self.workspace, self.jobs(1), story_engine=FakeStory(),
            image_engine=FakeImage(), voice_engine=FakeVoice(),
            render=fake_render, normalizer=self._noop_normalize)
        runner.settings = {"width": 360, "height": 640, "fps": 24}
        runner.run(self.report)
        self.assertEqual(seen["settings"]["width"], 360)

    # -- V2.1 ------------------------------------------------------------
    def test_consistency_hint_sent_to_image_engine(self):
        """角色卡 / 场景卡要跟着每个镜头一起给到出图引擎。"""
        story = FakeStory()
        original = story.generate

        def generate_with_cards(keywords, shot_count=8, style="", extra=""):
            data = original(keywords, shot_count, style, extra)
            data["characters"] = [{"character_id": "ch_阿芸", "name": "阿芸",
                                   "look": "齐肩黑发"}]
            data["scenes"] = [{"scene_id": "sc_灵堂", "name": "灵堂",
                               "look": "白蜡烛"}]
            # V2.2：卡片按镜头引用过滤，分镜要写明引用了谁 / 哪个场景
            for shot in data["shots"]:
                shot["shot_id"] = f"s{shot['index']:03d}"
                shot["scene_id"] = "sc_灵堂"
                shot["character_ids"] = ["ch_阿芸"]
            return data
        story.generate = generate_with_cards
        hints = []

        class HintImage(FakeImage):
            def generate_to_file(self, scene, target, size=None, style="", extra=""):
                hints.append((style, extra))
                return super().generate_to_file(scene, target, size=size)
        self.make_runner(self.jobs(1), story=story, image=HintImage()).run(self.report)
        self.assertEqual(len(hints), 2)
        for style, hint in hints:
            # V2.2：画风走统一预设，角色卡 / 场景卡放在 extra
            self.assertIn(style, ie.STYLE_PRESETS)
            self.assertIn("阿芸", hint)
            self.assertIn("白蜡烛", hint)

    def test_voice_style_from_keywords(self):
        """auto 模式下按题材关键词选配音预设。"""
        applied = []

        class StyleVoice(FakeVoice):
            def __init__(self):
                super().__init__()
                self.config = {"voice_style": "auto"}

            def synthesize_to_file(self, text, target, speed=None, fmt="wav"):
                applied.append(self.config.get("voice_style"))
                return super().synthesize_to_file(text, target, speed, fmt)

        from modules.project_manager import ProjectManager as PM
        jobs = [batch.BatchJob("民俗", "纸人、灵堂", 2), batch.BatchJob("都市", "地铁站", 2)]
        voice = StyleVoice()
        self.make_runner(jobs, voice=voice).run(self.report)
        self.assertIn("folk", applied)
        self.assertIn("urban", applied)
        self.assertEqual(voice.config["voice_style"], "auto")   # 用完换回
        self.assertTrue(PM)  # 保持导入一致

    def test_durations_follow_voice_and_srt_reexported(self):
        """配音对齐后 SRT 要跟着新时长重导。"""
        runner = self.make_runner(self.jobs(1))
        results = runner.run(self.report)
        data = ProjectManager().load(self.workspace / results[0].name)
        srt = (self.workspace / results[0].name / data["subtitle"]).read_text(encoding="utf-8")
        # 假配音 1 秒 + 留白 0.08 + 0.3 尾巴 → 字幕结束在 1.38 秒
        self.assertIn("00:00:00,080 --> 00:00:01,380", srt)
        # 第二句：上一镜 2.0 秒（画面时长 2.0s 放得下 1.08s 旁白）
        self.assertIn("00:00:02,080 --> 00:00:03,380", srt)


if __name__ == "__main__":
    unittest.main()
