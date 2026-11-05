"""V1.3 出图 / 配音引擎测试：请求构造、错误分类、文件落盘。全部假传输层，不联网。

运行：python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import image_engine as ie  # noqa: E402
from modules import sf_config  # noqa: E402
from modules import voice_engine as ve  # noqa: E402
from modules.sf_http import SFError, friendly_http_error, _error_detail  # noqa: E402

API_KEY = "sk-sf-abcdefghijklmnop"


def _cfg(**kw):
    base = {"api_key": API_KEY, "image_model": "Kwai-Kolors/Kolors", "voice": "claire"}
    base.update(kw)
    return base


class FakeJson:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, url, headers, payload, timeout, api_key=""):
        self.calls.append({"url": url, "headers": headers, "payload": payload,
                           "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


class FakeDownloader:
    def __init__(self, data=b"\x89PNG fake bytes", error=None):
        self.data = data
        self.error = error
        self.calls = []

    def __call__(self, url, target, timeout=120):
        self.calls.append(url)
        if self.error:
            raise self.error
        Path(target).write_bytes(self.data)
        return self.data


class FakeBytes:
    def __init__(self, data=b"ID3 fake mp3", error=None):
        self.data = data
        self.error = error
        self.calls = []

    def __call__(self, url, headers, payload, timeout, api_key=""):
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        if self.error:
            raise self.error
        return self.data


# ----------------------------------------------------------------------
class PromptTest(unittest.TestCase):
    def test_build_prompt_puts_style_first(self):
        """V2.2 顺序：画风 → 一致性卡片 → 画面描述。"""
        prompt = ie.build_prompt("雨夜的灵堂，纸人立在棺旁。", "低饱和青灰",
                                 "角色（阿芸）：齐肩黑发")
        i_style = prompt.index("低饱和青灰")
        i_hint = prompt.index("阿芸")
        i_scene = prompt.index("雨夜的灵堂")
        self.assertLess(i_style, i_hint)
        self.assertLess(i_hint, i_scene)
        self.assertNotIn("。。", prompt)

    def test_build_prompt_expands_style_preset(self):
        prompt = ie.build_prompt("雨夜的灵堂", "comic_dark")
        self.assertTrue(prompt.startswith(ie.STYLE_PRESETS["comic_dark"]))
        self.assertIn("雨夜的灵堂", prompt)

    def test_build_prompt_default_style_is_comic(self):
        prompt = ie.build_prompt("雨夜的灵堂")
        self.assertTrue(prompt.startswith(ie.STYLE_PRESETS[ie.DEFAULT_STYLE]))
        self.assertEqual(ie.DEFAULT_STYLE, "comic_dark")

    def test_style_presets_are_comic_by_default(self):
        self.assertIn("comic_dark", ie.STYLE_PRESETS)
        self.assertIn("照片写实", ie.NEGATIVE_PROMPT)

    def test_empty_scene_raises(self):
        with self.assertRaises(SFError):
            ie.build_prompt("   ")

    def test_pick_size_by_aspect(self):
        self.assertEqual(ie.pick_size(1080, 1920, "Kwai-Kolors/Kolors"), "720x1280")
        self.assertEqual(ie.pick_size(1080, 1920, "Tongyi-MAI/Z-Image-Turbo"), "928x1664")
        self.assertEqual(ie.pick_size(1080, 1080, "Kwai-Kolors/Kolors"), "1024x1024")
        self.assertEqual(ie.pick_size(1920, 1080, "Kwai-Kolors/Kolors"), "1280x720")
        # 不传模型时按默认模型（Z-Image-Turbo）给竖屏尺寸
        self.assertEqual(ie.pick_size(1080, 1920), "928x1664")
        self.assertEqual(ie.pick_size(1920, 1080), "1664x928")
        self.assertEqual(ie.pick_size(1080, 1080), "1328x1328")

    def test_style_suffix_has_no_double_desaturation(self):
        """调色交给渲染端，提示词里不再重复「低饱和」，否则画面发灰。"""
        prompt = ie.build_prompt("灵堂里的纸人", "中式民俗恐怖")
        self.assertIn("灵堂里的纸人", prompt)
        self.assertIn("中式民俗恐怖", prompt)
        self.assertNotIn("低饱和", prompt)

    def test_consistency_hint_from_story_cards(self):
        story = {"characters": [{"name": "阿芸", "look": "齐肩黑发"}],
                 "scenes": [{"name": "灵堂", "look": "白蜡烛，青砖地"}]}
        hint = ie.build_consistency_hint(story, "阿芸站在灵堂")
        self.assertIn("齐肩黑发", hint)
        self.assertIn("白蜡烛", hint)
        self.assertEqual(ie.build_consistency_hint(None), "")
        self.assertEqual(ie.build_consistency_hint({}), "")

    def test_generate_to_file_passes_size_and_seed(self):
        transport = FakeJson({"images": [{"url": "https://x/1.png"}]})
        engine = ie.ImageEngine(config={"api_key": "sk-1234567890abcdef", "image_model": "m"},
                                json_transport=transport,
                                downloader=FakeDownloader())
        import tempfile
        target = __import__("pathlib").Path(tempfile.mkdtemp()) / "a.png"
        engine.generate_to_file("灵堂", target, size="928x1664", seed=42)
        payload = transport.calls[0]["payload"]
        self.assertEqual(payload["image_size"], "928x1664")
        self.assertEqual(payload["seed"], 42)


class ParseImagesTest(unittest.TestCase):
    def test_images_field(self):
        urls = ie.parse_images({"images": [{"url": "https://x/1.png"}], "seed": 1})
        self.assertEqual(urls, ["https://x/1.png"])

    def test_openai_style_data_field(self):
        urls = ie.parse_images({"data": [{"url": "https://x/2.png"}]})
        self.assertEqual(urls, ["https://x/2.png"])

    def test_empty_raises(self):
        with self.assertRaises(SFError):
            ie.parse_images({"images": []})

    def test_bad_shape_raises(self):
        with self.assertRaises(SFError):
            ie.parse_images("not a dict")


class ImageEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_img_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_request_shape(self):
        transport = FakeJson({"images": [{"url": "https://x/a.png"}]})
        engine = ie.ImageEngine(config=_cfg(), json_transport=transport)
        urls = engine.generate("雨夜灵堂，纸人")
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.siliconflow.cn/v1/images/generations")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {API_KEY}")
        payload = call["payload"]
        self.assertEqual(payload["model"], "Kwai-Kolors/Kolors")
        self.assertEqual(payload["negative_prompt"], ie.NEGATIVE_PROMPT)
        self.assertIn("x", payload["image_size"])
        self.assertGreater(payload["num_inference_steps"], 0)
        self.assertEqual(urls, ["https://x/a.png"])

    def test_missing_key_raises(self):
        transport = FakeJson({"images": []})
        engine = ie.ImageEngine(config=_cfg(api_key=""), json_transport=transport)
        with self.assertRaises(SFError) as ctx:
            engine.generate("x")
        self.assertIn("硅基流动", str(ctx.exception))
        self.assertEqual(transport.calls, [])

    def test_generate_to_file_downloads_immediately(self):
        transport = FakeJson({"images": [{"url": "https://x/b.png"}]})
        downloader = FakeDownloader(b"\x89PNG data")
        engine = ie.ImageEngine(config=_cfg(), json_transport=transport,
                                downloader=downloader)
        target = self.tmp / "images" / "ai_1.png"
        engine.generate_to_file("灵堂", target)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_bytes(), b"\x89PNG data")
        self.assertEqual(downloader.calls, ["https://x/b.png"])

    def test_no_retry_on_auth_error(self):
        transport = FakeJson(error=SFError("API Key 无效或已失效"))
        engine = ie.ImageEngine(config=_cfg(), json_transport=transport)
        with self.assertRaises(SFError):
            engine.generate("x")
        self.assertEqual(len(transport.calls), 1)

    def test_retries_on_busy_then_succeeds(self):
        calls = {"n": 0}

        def flaky(url, headers, payload, timeout, api_key=""):
            calls["n"] += 1
            if calls["n"] == 1:
                raise SFError("模型服务繁忙（HTTP 503）")
            return {"images": [{"url": "https://x/c.png"}]}

        engine = ie.ImageEngine(config=_cfg(), json_transport=flaky)
        original = ie.time.sleep
        ie.time.sleep = lambda s: None
        try:
            urls = engine.generate("x")
        finally:
            ie.time.sleep = original
        self.assertEqual(urls, ["https://x/c.png"])
        self.assertEqual(calls["n"], 2)

    def test_gives_up_after_retries(self):
        transport = FakeJson(error=SFError("模型服务繁忙（HTTP 503）"))
        engine = ie.ImageEngine(config=_cfg(), json_transport=transport)
        original = ie.time.sleep
        ie.time.sleep = lambda s: None
        try:
            with self.assertRaises(SFError):
                engine.generate("x")
        finally:
            ie.time.sleep = original
        self.assertEqual(len(transport.calls), ie.MAX_RETRIES)


# ----------------------------------------------------------------------
class VoiceInputTest(unittest.TestCase):
    def test_style_prefix(self):
        text = ve.build_input("它比我昨天看到的更近了。")
        self.assertIn("<|endofprompt|>", text)
        self.assertTrue(text.endswith("它比我昨天看到的更近了。"))

    def test_no_style(self):
        self.assertEqual(ve.build_input("灯灭了。", style=""), "灯灭了。")

    def test_empty_raises(self):
        with self.assertRaises(SFError):
            ve.build_input("  ")

    def test_too_long_raises(self):
        with self.assertRaises(SFError):
            ve.build_input("啊" * (ve.MAX_CHARS + 1))

    def test_voice_id_prefix(self):
        self.assertEqual(ve.voice_id("FunAudioLLM/CosyVoice2-0.5B", "claire"),
                         "FunAudioLLM/CosyVoice2-0.5B:claire")
        already = "FunAudioLLM/CosyVoice2-0.5B:alex"
        self.assertEqual(ve.voice_id("FunAudioLLM/CosyVoice2-0.5B", already), already)


class SpeedTest(unittest.TestCase):
    """配音语速：解析、边界、持久化、请求透传。"""

    def test_label_roundtrip(self):
        for value in (0.5, 0.75, 1.0, 1.25, 1.5):
            label = sf_config.speed_label(value)
            self.assertIn("x", label)
            self.assertAlmostEqual(sf_config.parse_speed(label), value)

    def test_parse_plain_number(self):
        self.assertAlmostEqual(sf_config.parse_speed("1.4"), 1.4)
        self.assertAlmostEqual(sf_config.parse_speed("1.4x"), 1.4)

    def test_parse_garbage_falls_back(self):
        self.assertAlmostEqual(sf_config.parse_speed("快速"), 1.0)
        self.assertAlmostEqual(sf_config.parse_speed(None), 1.0)

    def test_clamped_range(self):
        self.assertAlmostEqual(sf_config.parse_speed("0.1x"), 0.25)
        self.assertAlmostEqual(sf_config.parse_speed("9x"), 4.0)

    def test_speed_sent_in_request(self):
        transport = FakeBytes(b"RIFF")
        engine = ve.VoiceEngine(config=_cfg(), bytes_transport=transport)
        engine.synthesize("旁白", speed=0.75)
        self.assertAlmostEqual(transport.calls[0]["payload"]["speed"], 0.75)

    def test_config_speed_used_as_default(self):
        transport = FakeBytes(b"RIFF")
        engine = ve.VoiceEngine(config=_cfg(voice_speed=1.25), bytes_transport=transport)
        engine.synthesize_to_file("旁白", Path(tempfile.mkdtemp()) / "a.wav")
        self.assertAlmostEqual(transport.calls[0]["payload"]["speed"], 1.25)

    def test_explicit_speed_overrides_config(self):
        transport = FakeBytes(b"RIFF")
        engine = ve.VoiceEngine(config=_cfg(voice_speed=1.25), bytes_transport=transport)
        engine.synthesize("旁白", speed=0.5)
        self.assertAlmostEqual(transport.calls[0]["payload"]["speed"], 0.5)

    def test_save_and_load_speed(self):
        tmp = Path(tempfile.mkdtemp(prefix="ahs_cfg_"))
        original = sf_config.CONFIG_FILE
        sf_config.CONFIG_FILE = tmp / "siliconflow.json"
        env = os.environ.pop("SILICONFLOW_API_KEY", None)
        try:
            sf_config.save_config("sk-test", voice_speed=0.8)
            cfg = sf_config.load_config()
            self.assertAlmostEqual(cfg["voice_speed"], 0.8)
            self.assertEqual(cfg["voice"], sf_config.DEFAULT_VOICE)
            # 旧配置文件（没有 voice_speed）应回落到默认 1.0
            sf_config.CONFIG_FILE.write_text('{"api_key": "sk-old", "voice": "alex"}',
                                             encoding="utf-8")
            self.assertAlmostEqual(sf_config.load_config()["voice_speed"], 1.0)
        finally:
            sf_config.CONFIG_FILE = original
            if env is not None:
                os.environ["SILICONFLOW_API_KEY"] = env
            shutil.rmtree(tmp, ignore_errors=True)


class VoiceEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_voice_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_request_shape(self):
        transport = FakeBytes(b"RIFF fake wav")
        engine = ve.VoiceEngine(config=_cfg(), bytes_transport=transport)
        engine.synthesize("它看着我。", fmt="wav")
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.siliconflow.cn/v1/audio/speech")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {API_KEY}")
        payload = call["payload"]
        self.assertEqual(payload["model"], "FunAudioLLM/CosyVoice2-0.5B")
        self.assertEqual(payload["voice"], "FunAudioLLM/CosyVoice2-0.5B:claire")
        self.assertEqual(payload["response_format"], "wav")
        self.assertIn("它看着我。", payload["input"])

    def test_synthesize_to_file(self):
        transport = FakeBytes(b"RIFF1234")
        engine = ve.VoiceEngine(config=_cfg(), bytes_transport=transport)
        target = self.tmp / "audio" / "voice_x.wav"
        engine.synthesize_to_file("旁白", target)
        self.assertEqual(target.read_bytes(), b"RIFF1234")

    def test_empty_audio_raises(self):
        transport = FakeBytes(b"")
        engine = ve.VoiceEngine(config=_cfg(), bytes_transport=transport)
        with self.assertRaises(SFError):
            engine.synthesize("旁白")

    def test_missing_key_raises(self):
        transport = FakeBytes(b"x")
        engine = ve.VoiceEngine(config=_cfg(api_key=""), bytes_transport=transport)
        with self.assertRaises(SFError):
            engine.synthesize("旁白")
        self.assertEqual(transport.calls, [])


# ----------------------------------------------------------------------
class HttpErrorTest(unittest.TestCase):
    def test_friendly_messages(self):
        self.assertIn("Key", friendly_http_error(401, ""))
        self.assertIn("余额", friendly_http_error(402, ""))
        self.assertIn("繁忙", friendly_http_error(503, ""))

    def test_key_scrubbed_from_detail(self):
        msg = friendly_http_error(400, f"bad key {API_KEY}", api_key=API_KEY)
        self.assertNotIn(API_KEY, msg)

    def test_error_detail_json(self):
        raw = json.dumps({"code": 20012, "message": "invalid image_size"}).encode()
        self.assertEqual(_error_detail(raw), "invalid image_size")

    def test_error_detail_plain_string(self):
        self.assertEqual(_error_detail(b"Invalid token"), "Invalid token")

    def test_error_detail_nested(self):
        raw = json.dumps({"error": {"message": "quota exceeded"}}).encode()
        self.assertEqual(_error_detail(raw), "quota exceeded")

# ----------------------------------------------------------------------
class ShotCardFilterTest(unittest.TestCase):
    """V2.2：一致性卡片按这一镜的 character_ids / scene_id 过滤。"""

    STORY = {
        "characters": [
            {"character_id": "ch_阿芸", "name": "阿芸", "look": "齐肩黑发，蓝布衫"},
            {"character_id": "ch_老陈", "name": "老陈", "look": "秃顶，油污工装"},
        ],
        "scenes": [
            {"scene_id": "sc_灵堂", "name": "灵堂", "look": "白蜡烛，青砖地"},
            {"scene_id": "sc_走廊", "name": "走廊", "look": "剥落的墙皮，绿荧光灯"},
        ],
    }

    def test_only_referenced_characters_are_included(self):
        shot = {"shot_id": "s001", "scene_id": "sc_灵堂", "character_ids": ["ch_阿芸"]}
        hint = ie.build_consistency_hint(self.STORY, "灵堂里站着一个人", shot)
        self.assertIn("阿芸", hint)
        self.assertIn("白蜡烛", hint)
        self.assertNotIn("老陈", hint)          # 不在这一镜里
        self.assertNotIn("荧光灯", hint)        # 不在这一镜的场景里

    def test_shot_with_no_characters_gets_empty_character_card(self):
        shot = {"shot_id": "s002", "scene_id": "sc_走廊", "character_ids": []}
        hint = ie.build_consistency_hint(self.STORY, "", shot)
        self.assertIn("荧光灯", hint)
        self.assertNotIn("阿芸", hint)

    def test_allows_multiple_characters(self):
        shot = {"scene_id": "sc_灵堂", "character_ids": ["ch_阿芸", "ch_老陈"]}
        hint = ie.build_consistency_hint(self.STORY, "", shot)
        self.assertIn("阿芸", hint)
        self.assertIn("老陈", hint)

    def test_unknown_ids_fall_back_to_cards(self):
        shot = {"scene_id": "sc_不存在", "character_ids": ["ch_不存在"]}
        hint = ie.build_consistency_hint(self.STORY, "", shot)
        self.assertIn("阿芸", hint)             # 引用不存在时不至于全空

    def test_without_shot_uses_old_behaviour(self):
        hint = ie.build_consistency_hint(self.STORY, "老陈在灵堂里")
        self.assertIn("老陈", hint)
        self.assertIn("白蜡烛", hint)


if __name__ == "__main__":
    unittest.main()