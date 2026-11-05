"""渲染引擎测试：先生成测试图片，再用真实 FFmpeg 渲染并校验时长。

如果本机找不到 FFmpeg，渲染用例会跳过（skipped），命令构造用例始终运行。
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.ffmpeg_locator import find_ffmpeg, find_ffprobe  # noqa: E402
from modules.project_manager import ProjectManager  # noqa: E402
from modules.render_engine import RenderEngine, RenderError  # noqa: E402

FFMPEG = find_ffmpeg()


def _make_png(path: Path, color: str, size="320x240"):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"color=c={color}:s={size}:d=1",
                    "-frames:v", "1", str(path)], check=True)


def _make_wav(path: Path, seconds=2):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    str(path)], check=True)


def _probe_duration(path: Path) -> float:
    ffprobe = find_ffprobe(FFMPEG)
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


@unittest.skipUnless(FFMPEG, "本机未找到 FFmpeg，跳过渲染测试")
class RenderEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_render_"))
        self.pm = ProjectManager()
        self.project = self.pm.create_project(self.tmp, "render_test")
        self.engine = RenderEngine()
        self.settings = dict(self.pm.load(self.project)["settings"],
                             width=320, height=240, fps=24)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed(self, durations, zoom="none", transition="cut"):
        images = []
        for i, color in enumerate(["red", "green", "blue"][:len(durations)]):
            p = self.tmp / f"{color}.png"
            _make_png(p, color)
            images.append(p)
        shots = self.pm.add_images(self.project, images, durations[0])
        for shot, dur in zip(shots, durations):
            self.pm.update_shot(self.project, shot["id"], {
                "duration": dur, "zoom": zoom, "transition": transition})
        self.data = self.pm.load(self.project)
        self.settings = dict(self.data["settings"], width=320, height=240, fps=24)
        return self.data

    def test_build_command_contains_all_shots(self):
        data = self._seed([1.0, 2.0, 0.5])
        out = self.project / "output" / "x.mp4"
        cmd = self.engine.build_command(data, self.settings, out)
        self.assertIn("-filter_complex", cmd)
        filt = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("concat=n=3", filt)
        self.assertIn("[v0]", filt)

    def test_render_uneven_durations(self):
        data = self._seed([1.0, 2.0, 1.5])
        out = self.project / "output" / "a.mp4"
        self.engine.render(data, self.settings, out)
        self.assertTrue(out.exists())
        duration = _probe_duration(out)
        self.assertAlmostEqual(duration, 4.5, delta=0.25)

    def test_render_zoom_and_fade(self):
        data = self._seed([1.0, 1.0], zoom="in", transition="fade")
        out = self.project / "output" / "b.mp4"
        self.engine.render(data, self.settings, out)
        self.assertAlmostEqual(_probe_duration(out), 2.0, delta=0.25)

    def test_render_with_narration_music_subtitle(self):
        data = self._seed([1.0, 1.0])
        wav = self.tmp / "voice.wav"
        _make_wav(wav, 1.5)
        music = self.tmp / "bgm.wav"
        _make_wav(music, 5)
        srt = self.tmp / "sub.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,500\n第一句\n\n"
                       "2\n00:00:01,500 --> 00:00:02,000\n第二句\n",
                       encoding="utf-8")
        self.pm.set_media(self.project, "narration", wav)
        self.pm.set_media(self.project, "music", music)
        self.pm.set_media(self.project, "subtitle", srt)
        data = self.pm.load(self.project)
        out = self.project / "output" / "c.mp4"
        self.engine.render(data, self.settings, out)
        self.assertAlmostEqual(_probe_duration(out), 2.0, delta=0.3)

    def test_empty_timeline_raises(self):
        data = self.pm.load(self.project)
        with self.assertRaises(RenderError):
            self.engine.build_command(data, self.settings,
                                      self.project / "output" / "e.mp4")

    def test_missing_image_raises(self):
        data = self._seed([1.0])
        (self.project / data["shots"][0]["image"]).unlink()
        with self.assertRaises(RenderError):
            self.engine.build_command(data, self.settings,
                                      self.project / "output" / "m.mp4")

    # -- V1.2：故事导入的无图镜头 --------------------------------------
    def test_unillustrated_shot_renders_black(self):
        """没有图片的镜头渲染为黑场，时长照常占用。"""
        data = self._seed([1.0])
        data["shots"].append({"id": "story1", "image": None, "duration": 1.5,
                              "zoom": "none", "transition": "cut", "subtitle": None,
                              "narration": "它比昨天更近了。", "scene": "走廊"})
        cmd = self.engine.build_command(data, self.settings,
                                        self.project / "output" / "s.mp4")
        filt = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("color=c=black", " ".join(cmd))
        out = self.project / "output" / "story.mp4"
        self.engine.render(data, self.settings, out)
        self.assertAlmostEqual(_probe_duration(out), 2.5, delta=0.25)

    # -- V2.1：质感 / 运镜 / 转场 -----------------------------------------
    def _filter_of(self, data, settings=None):
        cmd = self.engine.build_command(data, settings or self.settings,
                                        self.project / "output" / "f.mp4")
        return cmd, cmd[cmd.index("-filter_complex") + 1]

    def test_post_grade_filters_present(self):
        data = self._seed([1.0])
        _, filt = self._filter_of(data)
        for token in ("eq=contrast", "colorbalance", "noise=c0s=3:c0f=t+u",
                      "vignette=PI/4.5", "unsharp=5:5:0.5"):
            self.assertIn(token, filt)
        # 滤镜顺序：颗粒必须在调色之后、format 之前
        self.assertLess(filt.index("eq=contrast"), filt.index("noise="))
        self.assertLess(filt.index("noise="), filt.index("format=yuv420p"))

    def test_grade_and_grain_settings_respected(self):
        data = self._seed([1.0])
        warm = dict(self.settings, grade="warm", grain=0, vignette=False)
        _, filt = self._filter_of(data, warm)
        self.assertIn("colorbalance=rs=", filt)
        self.assertNotIn("noise=", filt)
        self.assertNotIn("vignette=", filt)

    def test_motion_expressions(self):
        data = self._seed([2.0])
        expectations = {
            "push-in": "min(zoom+",
            "pull-out": "max(zoom-",
            "pan-left": "(iw-iw/zoom)*(47-on)/47",
            "pan-right": "(iw-iw/zoom)*(on/",
            "diag-in": "(ih-ih/zoom)*(on/",
        }
        for motion, needle in expectations.items():
            data["shots"][0]["motion"] = motion
            _, filt = self._filter_of(data)
            self.assertIn("zoompan=", filt, motion)
            self.assertIn(needle, filt, motion)
        data["shots"][0]["motion"] = "diag-in"
        _, filt = self._filter_of(data)
        self.assertIn("min(zoom+", filt)
        self.assertIn("(iw-iw/zoom)*(on/", filt)
        data["shots"][0]["motion"] = "static"
        _, filt = self._filter_of(data)
        self.assertNotIn("zoompan=", filt)

    def test_legacy_zoom_used_when_motion_missing(self):
        data = self._seed([1.0])
        data["shots"][0].pop("motion", None)
        data["shots"][0]["zoom"] = "out"
        self.assertEqual(self.engine.shot_motion(data["shots"][0]), "pull-out")

    def test_dissolve_and_flash_transitions(self):
        data = self._seed([1.0])
        data["shots"][0]["transition"] = "dissolve"
        _, filt = self._filter_of(data)
        self.assertIn("fade=t=in:st=0:d=0.200", filt)
        self.assertIn("fade=t=out:st=0.800:d=0.200", filt)
        data["shots"][0]["transition"] = "flash"
        _, filt = self._filter_of(data)
        self.assertIn("fade=t=in:st=0:d=0.070:color=white", filt)
        self.assertNotIn("fade=t=out", filt)

    def test_subtitle_font_scales_with_height(self):
        small = RenderEngine.subtitle_style(1920)
        wide = RenderEngine.subtitle_style(1080)   # 横屏 1080 高
        tiny = RenderEngine.subtitle_style(640)
        self.assertIn("FontSize=40", small)   # 1080 宽：一行约 13 字，上限 40
        self.assertIn("Outline=2", small)
        self.assertIn("BackColour=&H60000000", small)
        self.assertIn("BorderStyle=3", small)
        self.assertIn("MarginV=105", small)   # 1920 * 0.055
        self.assertIn("WrapStyle=0", small)
        self.assertIn("FontSize=26", wide)
        self.assertIn("MarginV=59", wide)
        self.assertIn("FontSize=26", tiny)    # 下限 26
        self.assertIn("MarginV=44", tiny)

    def test_voice_and_music_sidechain_ducking(self):
        data = self._seed([1.0, 1.0])
        voice = self.tmp / "voice.wav"
        _make_wav(voice, 1.5)
        music = self.tmp / "bgm.wav"
        _make_wav(music, 5)
        data["narration"] = str(voice)
        data["music"] = str(music)
        _, filt = self._filter_of(data)
        self.assertIn("sidechaincompress", filt)
        self.assertIn("asplit=2[nmix][nsc]", filt)
        self.assertIn("normalize=0", filt)
        self.assertIn("loudnorm=I=-16:TP=-1.5:LRA=11", filt)
        self.assertNotIn("drone", filt)   # 有 BGM 就不垫 drone

    def test_drone_bed_without_music(self):
        data = self._seed([1.0])
        voice = self.tmp / "voice.wav"
        _make_wav(voice, 1.5)
        data["narration"] = str(voice)
        cmd, filt = self._filter_of(data)
        self.assertIn("sine=frequency=55", " ".join(cmd))
        self.assertIn("sine=frequency=110", " ".join(cmd))
        self.assertIn("[drone]", filt)
        off = dict(self.settings, bed_drone=False)
        cmd, _ = self._filter_of(data, off)
        self.assertNotIn("sine=frequency=55", " ".join(cmd))

    def test_render_with_drift_pan(self):
        """平移运镜真实渲染：时长正确、可解码。"""
        data = self._seed([1.5])
        data["shots"][0]["motion"] = "pan-right"
        data["shots"][0]["transition"] = "dissolve"
        out = self.project / "output" / "pan.mp4"
        self.engine.render(data, self.settings, out)
        self.assertAlmostEqual(_probe_duration(out), 1.5, delta=0.2)


if __name__ == "__main__":
    unittest.main()
