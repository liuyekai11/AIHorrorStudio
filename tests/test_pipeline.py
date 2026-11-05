"""V1.3 流水线测试：AI 画面 / 配音记录 → 拼接旁白音轨 → 真实渲染成片。

渲染与音轨拼接用真实 FFmpeg；找不到 FFmpeg 时跳过这部分。
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.ffmpeg_locator import find_ffmpeg, find_ffprobe  # noqa: E402
from modules.project_manager import ProjectManager  # noqa: E402
from modules import media_tools  # noqa: E402
from modules.render_engine import RenderEngine  # noqa: E402

FFMPEG = find_ffmpeg()


def _make_png(path: Path, color: str, size="360x640"):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"color=c={color}:s={size}:d=1",
                    "-frames:v", "1", str(path)], check=True)


def _probe_duration(path: Path) -> float:
    ffprobe = find_ffprobe(FFMPEG)
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


class AiFieldsTest(unittest.TestCase):
    """project_manager 的 V1.3 字段：不依赖 FFmpeg。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_v13_"))
        self.pm = ProjectManager()
        self.project = self.pm.create_project(self.tmp, "v13")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _story_shots(self):
        return self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 2.0, "scene": "灵堂", "narration": "它看着我。"},
            {"image": None, "duration": 3.0, "scene": "走廊", "narration": "它更近了。"},
        ])

    def _touch(self, rel: str) -> Path:
        path = self.project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def test_new_shots_have_ai_fields(self):
        shots = self._story_shots()
        self.assertIsNone(shots[0]["ai_image"])
        self.assertIsNone(shots[0]["voice"])
        self.assertIsNone(shots[0]["voice_ms"])
        # 重新加载后字段仍在（落盘未丢）
        reloaded = self.pm.load(self.project)["shots"]
        self.assertIsNone(reloaded[1]["ai_image"])

    def test_set_ai_image_sets_both_fields(self):
        shots = self._story_shots()
        self._touch("images/ai_a.png")
        rel = self.pm.set_ai_image(self.project, shots[0]["id"], self.project / "images/ai_a.png")
        self.assertEqual(rel, "images/ai_a.png")
        shot = self.pm.find_shot(self.pm.load(self.project), shots[0]["id"])
        self.assertEqual(shot["image"], "images/ai_a.png")
        self.assertEqual(shot["ai_image"], "images/ai_a.png")

    def test_set_voice_and_segments(self):
        shots = self._story_shots()
        self._touch("audio/voice_a.wav")
        self.pm.set_voice(self.project, shots[0]["id"], self.project / "audio/voice_a.wav", 1800)
        data = self.pm.load(self.project)
        shot = self.pm.find_shot(data, shots[0]["id"])
        self.assertEqual(shot["voice_ms"], 1800)
        self._touch("audio/voice_b.wav")
        self.pm.set_voice(self.project, shots[1]["id"], self.project / "audio/voice_b.wav", 2500)
        segments = self.pm.voice_segments(self.pm.load(self.project))
        self.assertEqual([s[0] for s in segments],
                         ["audio/voice_a.wav", "audio/voice_b.wav"])
        self.assertAlmostEqual(segments[1][1], 2.0)   # 第二镜起点
        self.assertAlmostEqual(segments[1][2], 3.0)   # 第二镜时长

    def test_voice_segments_skip_unvoiced(self):
        shots = self._story_shots()
        self._touch("audio/voice_b.wav")
        self.pm.set_voice(self.project, shots[1]["id"], self.project / "audio/voice_b.wav", 900)
        self.assertEqual(len(self.pm.voice_segments(self.pm.load(self.project))), 1)

    def test_clear_voices(self):
        shots = self._story_shots()
        self._touch("audio/v.wav")
        self.pm.set_voice(self.project, shots[0]["id"], self.project / "audio/v.wav", 500)
        self.pm.clear_voices(self.project)
        shot = self.pm.find_shot(self.pm.load(self.project), shots[0]["id"])
        self.assertIsNone(shot["voice"])
        self.assertIsNone(shot["voice_ms"])

    def test_set_narration_clears_shot_voices(self):
        shots = self._story_shots()
        self._touch("audio/v.wav")
        self.pm.set_voice(self.project, shots[0]["id"], self.project / "audio/v.wav", 500)
        self._touch("audio/full.wav")
        self.pm.set_narration(self.project, self.project / "audio/full.wav")
        data = self.pm.load(self.project)
        self.assertEqual(data["narration"], "audio/full.wav")
        self.assertTrue(all(s.get("voice") is None for s in data["shots"]))

    def test_cleared_ai_images_keeps_manual_images(self):
        shots = self._story_shots()
        self._touch("images/ai_a.png")
        self.pm.set_ai_image(self.project, shots[0]["id"], self.project / "images/ai_a.png")
        self._touch("images/manual.png")
        self.pm.update_shot(self.project, shots[1]["id"], {"image": "images/manual.png"})
        removed = self.pm.cleared_ai_images(self.project, [s["id"] for s in shots])
        self.assertEqual(removed, ["images/ai_a.png"])
        data = self.pm.load(self.project)
        a = self.pm.find_shot(data, shots[0]["id"])
        b = self.pm.find_shot(data, shots[1]["id"])
        self.assertIsNone(a["image"])
        self.assertIsNone(a["ai_image"])
        self.assertEqual(b["image"], "images/manual.png")   # 手动配图不受影响

    def test_pending_ai_shots(self):
        self._story_shots()
        self.assertEqual(len(self.pm.pending_ai_shots(self.pm.load(self.project))), 2)
        shots = self.pm.load(self.project)["shots"]
        self._touch("images/a.png")
        self.pm.set_ai_image(self.project, shots[0]["id"], self.project / "images/a.png")
        self.assertEqual(len(self.pm.pending_ai_shots(self.pm.load(self.project))), 1)


@unittest.skipUnless(FFMPEG, "本机未找到 FFmpeg，跳过流水线测试")
class VoiceFitTest(unittest.TestCase):
    """配音驱动时长：对齐后旁白完整放下，不再截断。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_fit_"))
        self.pm = ProjectManager()
        self.project = self.pm.create_project(self.tmp, "fit")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wav(self, name: str, seconds: float, freq=440) -> Path:
        path = self.project / "audio" / name
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                        str(path)], check=True)
        return path

    def test_fit_durations_to_voice(self):
        """画面优先：旁白（1.2s）塞得进画面时长 2.0s → 保持 2.0；
        旁白 2.4s + 留白 0.08s 超过 2.0s → 延长到 2.48，并记入 extended。"""
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 2.0, "scene": "a", "narration": "一"},
            {"image": None, "duration": 2.0, "scene": "b", "narration": "二"},
        ])
        self.pm.set_voice(self.project, shots[0]["id"], self._wav("v1.wav", 1.2), 1200)
        self.pm.set_voice(self.project, shots[1]["id"], self._wav("v2.wav", 2.4), 2400)
        changed, extended = self.pm.fit_durations_to_voice(self.project)
        self.assertEqual(len(changed), 1)
        self.assertEqual([item[0] for item in extended], [shots[1]["id"]])
        data = self.pm.load(self.project)
        offset = self.pm.voice_offset_ms(data) / 1000.0
        self.assertAlmostEqual(data["shots"][0]["duration"], 2.0, delta=0.01)
        self.assertAlmostEqual(data["shots"][1]["duration"], offset + 2.4, delta=0.01)
        # 起点 reflow 正确：第二镜起点 = 第一镜新时长
        self.assertAlmostEqual(data["shots"][1]["start"],
                               data["shots"][0]["duration"], delta=0.01)
        # 幂等：再次对齐不再变化
        again, _ = self.pm.fit_durations_to_voice(self.project)
        self.assertEqual(again, [])

    def test_fit_short_voice_keeps_picture_pacing(self):
        """旁白明显短于画面时长时，镜头不会被缩短（节奏以画面为准）。"""
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 3.0, "scene": "a", "narration": "一"},
        ])
        self.pm.set_voice(self.project, shots[0]["id"], self._wav("s.wav", 1.0), 1000)
        changed, extended = self.pm.fit_durations_to_voice(self.project)
        self.assertEqual(changed, [])
        self.assertEqual(extended, [])
        data = self.pm.load(self.project)
        self.assertAlmostEqual(data["shots"][0]["duration"], 3.0, delta=0.01)

    def test_voice_pacing_mode_keeps_old_behaviour(self):
        """pacing == voice（旁白优先）时，时长仍按「留白 + 配音」走。"""
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 3.0, "scene": "a", "narration": "一"},
        ])
        self.pm.set_voice(self.project, shots[0]["id"], self._wav("w.wav", 1.0), 1000)
        self.pm.update_settings(self.project, dict(self.pm.load(self.project)["settings"],
                                                   pacing="voice"))
        changed, extended = self.pm.fit_durations_to_voice(self.project)
        self.assertEqual(len(changed), 1)
        self.assertEqual(extended, [])
        data = self.pm.load(self.project)
        self.assertAlmostEqual(data["shots"][0]["duration"],
                               self.pm.voice_offset_ms(data) / 1000.0 + 1.0, delta=0.01)

    def test_fit_only_voiced_shots(self):
        """无配音的镜头保持原时长；有配音的镜头被延长到放得下旁白。

        画面时长 1.0s 低于画面节奏下限 1.5s，会被钳到 1.5s；
        旁白 1.0s + 留白仍放得下，所以镜头停在 1.5s。
        """
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 1.0, "scene": "a", "narration": "一"},
            {"image": None, "duration": 4.0, "scene": "b", "narration": "二"},
        ])
        self.pm.set_voice(self.project, shots[0]["id"], self._wav("v.wav", 1.0), 1000)
        self.pm.fit_durations_to_voice(self.project)
        data = self.pm.load(self.project)
        self.assertAlmostEqual(data["shots"][1]["duration"], 4.0)
        self.assertAlmostEqual(data["shots"][0]["duration"], 1.5, delta=0.01)

    def test_no_fit_keeps_durations(self):
        """不调用 fit 时，镜头时长保持故事建议值（用户可关闭自动对齐）。"""
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 2.0, "scene": "a", "narration": "一"},
        ])
        self.pm.set_voice(self.project, shots[0]["id"], self._wav("n.wav", 3.0), 3000)
        data = self.pm.load(self.project)
        self.assertAlmostEqual(data["shots"][0]["duration"], 2.0)

    def test_track_after_fit_no_truncation(self):
        """端到端：对齐后拼出的音轨里，配音完整（无 atrim 截断）。"""
        from modules import media_tools
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 0.5, "scene": "a", "narration": "一"},
            {"image": None, "duration": 0.5, "scene": "b", "narration": "二"},
        ])
        # 配音故意比镜头长得多（0.5s vs 1.5s）——旧模型会截断
        self.pm.set_voice(self.project, shots[0]["id"], self._wav("f1.wav", 1.5, 440), 1500)
        self.pm.set_voice(self.project, shots[1]["id"], self._wav("f2.wav", 1.5, 660), 1500)
        self.pm.fit_durations_to_voice(self.project)
        data = self.pm.load(self.project)
        offset = self.pm.voice_offset_ms(data) / 1000.0
        self.assertAlmostEqual(data["shots"][0]["duration"], offset + 1.5, delta=0.01)

        segments = self.pm.voice_segments(data)
        track = self.project / "audio" / "track.wav"
        media_tools.concat_audio(
            [(self.project / rel, start, dur) for rel, start, dur in segments],
            track, self.pm.total_duration(data),
            offset_ms=self.pm.voice_offset_ms(data))
        self.assertAlmostEqual(media_tools.audio_duration(track),
                               self.pm.total_duration(data), delta=0.1)

        # 验证配音真的被完整保留：测音轨能量，找出第二段配音的起点，
        # 应等于「镜头1新时长 + 镜头内留白」，即镜头2起点 + offset。
        raw = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(track), "-f", "s16le",
             "-ac", "1", "-ar", "8000", "-"],
            capture_output=True).stdout
        samples = memoryview(raw).cast("h") if raw else []
        rate = 8000
        # 逐 20ms 窗判断是否有声（正弦波幅度约 1/4 满量程）
        loud = []
        win = int(rate * 0.02)
        for i in range(0, len(samples) - win, win):
            chunk = samples[i:i + win]
            peak = max(abs(int(v)) for v in chunk)
            loud.append(peak > 2000)
        d1 = data["shots"][0]["duration"]
        d2 = data["shots"][1]["duration"]
        # 第一镜：旁白应在 offset 附近开始
        first_on = next((j for j, v in enumerate(loud) if v), None)
        self.assertIsNotNone(first_on, "音轨应有声音")
        self.assertAlmostEqual(first_on * 0.02, offset, delta=0.12)
        # 第一段旁白长度应为 1.5s（完整，没被截断）
        on1 = [j for j, v in enumerate(loud) if v and j * 0.02 < d1]
        self.assertAlmostEqual((on1[-1] - on1[0]) * 0.02, 1.5, delta=0.12)
        # 第二镜：起点 = d1 + offset
        on2 = [j for j, v in enumerate(loud) if v and j * 0.02 >= d1]
        self.assertTrue(on2, "第二镜配音应存在")
        self.assertAlmostEqual(on2[0] * 0.02, d1 + offset, delta=0.12)
        self.assertAlmostEqual((on2[-1] - on2[0]) * 0.02, 1.5, delta=0.15)
        self.assertAlmostEqual(media_tools.audio_duration(track), d1 + d2, delta=0.1)


@unittest.skipUnless(FFMPEG, "本机未找到 FFmpeg，跳过流水线测试")
class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_pipe_"))
        self.pm = ProjectManager()
        self.project = self.pm.create_project(self.tmp, "pipe")
        self.settings = dict(self.pm.load(self.project)["settings"],
                             width=320, height=480, fps=24)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wav(self, name: str, seconds: float, freq=440) -> Path:
        path = self.project / "audio" / name
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                        str(path)], check=True)
        return path

    def test_voice_track_alignment(self):
        """两镜配音分别 1s / 2s，第二镜在 2s 处开始 → 音轨应为全片 4s。"""
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 2.0, "scene": "a", "narration": "一号"},
            {"image": None, "duration": 2.0, "scene": "b", "narration": "二号"},
        ])
        self.pm.set_voice(self.project, shots[0]["id"], self._wav("v1.wav", 1.0), 1000)
        self.pm.set_voice(self.project, shots[1]["id"], self._wav("v2.wav", 2.0), 2000)
        data = self.pm.load(self.project)
        segments = self.pm.voice_segments(data)
        target = self.project / "audio" / "track.wav"
        media_tools.concat_audio(
            [(self.project / rel, start, dur) for rel, start, dur in segments],
            target, self.pm.total_duration(data))
        self.assertAlmostEqual(media_tools.audio_duration(target), 4.0, delta=0.1)

    def test_render_uses_ai_images_and_voice_track(self):
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 1.5, "scene": "灵堂", "narration": "它看着我。"},
            {"image": None, "duration": 1.5, "scene": "走廊", "narration": "它更近了。"},
        ])
        for i, color in enumerate(("red", "blue")):
            png = self.tmp / f"{color}.png"
            _make_png(png, color)
            target = self.project / "images" / f"ai_{i}.png"
            shutil.copy2(png, target)
            self.pm.set_ai_image(self.project, shots[i]["id"], target)
        # 拼接配音音轨
        self.pm.set_voice(self.project, shots[0]["id"], self._wav("x1.wav", 1.2), 1200)
        self.pm.set_voice(self.project, shots[1]["id"], self._wav("x2.wav", 1.0, 330), 1000)
        data = self.pm.load(self.project)
        segments = self.pm.voice_segments(data)
        track = self.project / "audio" / "voice_track.wav"
        media_tools.concat_audio(
            [(self.project / rel, start, dur) for rel, start, dur in segments],
            track, self.pm.total_duration(data))
        data["narration"] = "audio/voice_track.wav"
        data["voice_track"] = data["narration"]
        self.pm.save(self.project, data)

        data = self.pm.load(self.project)
        out = self.project / "output" / "final.mp4"
        RenderEngine().render(data, self.settings, out)
        self.assertAlmostEqual(_probe_duration(out), 3.0, delta=0.3)

        # 成片带音轨
        ffprobe = find_ffprobe(FFMPEG)
        streams = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", str(out)],
            capture_output=True, text=True).stdout
        self.assertIn("audio", streams)

    def test_render_voice_track_field_when_narration_empty(self):
        """只有 voice_track 字段（没有 narration）时也能带声音渲染。"""
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 1.5, "scene": "a", "narration": "一"},
        ])
        png = self.tmp / "g.png"
        _make_png(png, "green")
        target = self.project / "images" / "g.png"
        shutil.copy2(png, target)
        self.pm.set_ai_image(self.project, shots[0]["id"], target)
        wav = self._wav("only.wav", 1.2)
        track = self.project / "audio" / "voice_track.wav"
        shutil.copy2(wav, track)
        data = self.pm.load(self.project)
        data["voice_track"] = "audio/voice_track.wav"
        self.pm.save(self.project, data)
        cmd = RenderEngine().build_command(self.pm.load(self.project), self.settings,
                                           self.project / "output" / "v.mp4")
        self.assertIn(str(track), " ".join(cmd))

    def test_normalize_image_in_place(self):
        """出图路径就是目标路径（source == target）时也应成功。"""
        png = self.project / "images" / "inplace.png"
        _make_png(png, "orange", size="640x360")
        media_tools.normalize_image(png, png, 320, 480)
        ffprobe = find_ffprobe(FFMPEG)
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(png)],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "320,480")
        leftovers = [p.name for p in png.parent.glob(".*_norm*")]
        self.assertEqual(leftovers, [], "不应残留临时文件")

    def test_normalize_image_matches_project_size(self):
        png = self.tmp / "wide.png"
        _make_png(png, "white", size="640x360")
        target = self.project / "images" / "n.png"
        media_tools.normalize_image(png, target, 320, 480)
        ffprobe = find_ffprobe(FFMPEG)
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(target)],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "320,480")

    def test_normalize_cover_small_source(self):
        """源图比画幅小：cover 不放大，居中放置、边缘补黑（不再硬拉糊）。"""
        png = self.project / "images" / "small.png"
        _make_png(png, "blue", size="200x120")
        media_tools.normalize_image(png, png, 320, 480, fit="cover")
        ffprobe = find_ffprobe(FFMPEG)
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(png)],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "320,480")

    def test_normalize_cover_tall_source(self):
        """源图比画幅高（同竖屏比例）：cover 裁切成精确尺寸。"""
        png = self.project / "images" / "tall.png"
        _make_png(png, "green", size="500x1300")
        media_tools.normalize_image(png, png, 320, 480, fit="cover")
        ffprobe = find_ffprobe(FFMPEG)
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(png)],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "320,480")


# ----------------------------------------------------------------------
@unittest.skipUnless(FFMPEG, "本机未找到 FFmpeg，跳过音频测试")
class AudioPolishTest(unittest.TestCase):
    """V2.1 声音：首尾静音裁剪、响度归一。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_audio_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _tone_with_silence(self, path: Path, lead=1.0, tone=0.8, tail=1.5):
        # 1s 静音 + 0.8s 440Hz + 1.5s 静音，模拟 TTS 句首/句尾的长静音
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"sine=frequency=440:duration={tone}",
                        "-af", (f"adelay=delays={int(lead * 1000)}:all=1,"
                                f"apad=whole_dur={lead + tone + tail}"),
                        str(path)], check=True)

    def test_trim_silence_strips_head_and_tail(self):
        src = self.tmp / "v.wav"
        self._tone_with_silence(src)
        self.assertAlmostEqual(media_tools.audio_duration(src), 3.3, delta=0.05)
        media_tools.trim_silence(src)
        # 只剩 0.8s 语音（首尾各留 <0.1s 气口）
        self.assertLess(media_tools.audio_duration(src), 1.0)
        self.assertGreater(media_tools.audio_duration(src), 0.7)

    def test_trim_silence_out_of_place(self):
        src = self.tmp / "a.wav"
        dst = self.tmp / "b.wav"
        self._tone_with_silence(src)
        media_tools.trim_silence(src, dst)
        self.assertGreater(media_tools.audio_duration(src), 3.0)   # 源文件不动
        self.assertLess(media_tools.audio_duration(dst), 1.0)

    def test_concat_audio_is_loudness_normalized(self):
        seg = self.tmp / "seg.wav"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
                        "-af", "volume=0.05", str(seg)], check=True)   # 很轻
        out = self.tmp / "track.wav"
        media_tools.concat_audio([(seg, 0.0, 2.0)], out, 2.0)
        ffmpeg = FFMPEG
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(out), "-af", "ebur128",
             "-f", "null", "-"], capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        values = [float(m) for m in __import__("re").findall(r"I:\s*(-?\d+\.\d+) LUFS", result.stderr)]
        self.assertTrue(values, result.stderr[-500:])
        self.assertAlmostEqual(values[-1], -16.0, delta=1.0)

    def test_loudnorm_filter_string(self):
        self.assertEqual(media_tools.loudnorm_filter(), "loudnorm=I=-16:TP=-1.5:LRA=11")


if __name__ == "__main__":
    unittest.main()
