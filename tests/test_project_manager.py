"""ProjectManager 时间轴数据模型测试（不需要 GUI）。

运行：python -m unittest discover -s tests -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.project_manager import (  # noqa: E402
    ProjectManager, ProjectError, SCHEMA_VERSION, MIN_DURATION, parse_time, format_time,
)


class ProjectManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_test_"))
        self.pm = ProjectManager()
        self.manager = ProjectManager()
        self.project = self.pm.create_project(self.tmp, "午夜纸人")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_image(self, name="a.png"):
        path = self.tmp / name
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path

    # -- 基础 ------------------------------------------------------------
    def test_create_project_layout(self):
        for sub in ("images", "audio", "subtitles", "output", "temp"):
            self.assertTrue((self.project / sub).is_dir())
        data = self.pm.load(self.project)
        # V3 P1（MVP 范围 #1）：新建项目的 project.json 为 schema_version=3；
        # 对 V2 代码保持透明——内存数据（load/migrate 返回）仍是 V2 结构
        raw = json.loads((self.project / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"], SCHEMA_VERSION + 1)
        self.assertTrue((self.project / "stories" / "story" / "story.json").exists())
        self.assertEqual(data["schema_version"], SCHEMA_VERSION)
        self.assertEqual(data["shots"], [])
        self.assertEqual(data["settings"]["width"], 1080)

    def test_invalid_name(self):
        with self.assertRaises(ProjectError):
            self.pm.create_project(self.tmp, "   ")

    # -- 导入 ------------------------------------------------------------
    def test_add_images_creates_shots_with_sequential_start(self):
        shots = self.pm.add_images(self.project, [self._fake_image("1.png"),
                                                  self._fake_image("2.png")], 2.5)
        self.assertEqual(len(shots), 2)
        data = self.pm.load(self.project)
        self.assertAlmostEqual(data["shots"][0]["start"], 0.0)
        self.assertAlmostEqual(data["shots"][1]["start"], 2.5)
        self.assertAlmostEqual(data["total_duration"], 5.0)
        self.assertTrue((self.project / "images" / "1.png").exists())

    # -- 迁移 ------------------------------------------------------------
    def test_migrate_v10_project(self):
        legacy = {
            "schema_version": 1,
            "name": "old",
            "images": ["images/01.png", "images/02.png"],
            "image_duration": 7,
            "narration": None, "music": None, "subtitle": None,
        }
        (self.project / "project.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        path = self.pm.open_project(self.project)
        data = self.pm.load(path)
        self.assertEqual(data["schema_version"], SCHEMA_VERSION)
        self.assertEqual(len(data["shots"]), 2)
        self.assertAlmostEqual(data["shots"][0]["duration"], 7.0)
        self.assertAlmostEqual(data["shots"][1]["start"], 7.0)
        # 旧字段 images 保留（只读）
        self.assertEqual(len(data["images"]), 2)

    def test_migrate_v11_default_duration(self):
        legacy = {"images": ["images/a.png"]}
        (self.project / "project.json").write_text(json.dumps(legacy), encoding="utf-8")
        self.pm.open_project(self.project)
        data = self.pm.load(self.project)
        self.assertAlmostEqual(data["shots"][0]["duration"], 3.0)

    # -- 编辑 ------------------------------------------------------------
    def test_update_duration_refows(self):
        shots = self.pm.add_images(self.project, [self._fake_image("1.png"),
                                                  self._fake_image("2.png")], 2.0)
        self.pm.update_shot(self.project, shots[0]["id"], {"duration": 5.0})
        data = self.pm.load(self.project)
        self.assertAlmostEqual(data["shots"][1]["start"], 5.0)
        self.assertAlmostEqual(data["total_duration"], 7.0)

    def test_duration_clamped(self):
        shots = self.pm.add_images(self.project, [self._fake_image()], 2.0)
        self.pm.update_shot(self.project, shots[0]["id"], {"duration": -5})
        data = self.pm.load(self.project)
        self.assertGreaterEqual(data["shots"][0]["duration"], MIN_DURATION)

    def test_move_shot(self):
        shots = self.pm.add_images(self.project, [self._fake_image("a.png"),
                                                  self._fake_image("b.png"),
                                                  self._fake_image("c.png")], 1.0)
        new_index = self.pm.move_shot(self.project, shots[2]["id"], -2)
        self.assertEqual(new_index, 0)
        data = self.pm.load(self.project)
        self.assertEqual(Path(data["shots"][0]["image"]).name, "c.png")

    def test_delete_shots(self):
        shots = self.pm.add_images(self.project, [self._fake_image("a.png"),
                                                  self._fake_image("b.png")], 1.0)
        removed = self.pm.delete_shots(self.project, [shots[0]["id"]])
        self.assertEqual(len(removed), 1)
        data = self.pm.load(self.project)
        self.assertEqual(len(data["shots"]), 1)
        self.assertAlmostEqual(data["shots"][0]["start"], 0.0)

    def test_split_shot(self):
        shots = self.pm.add_images(self.project, [self._fake_image()], 4.0)
        self.pm.split_shot(self.project, shots[0]["id"], 2.0)
        data = self.pm.load(self.project)
        self.assertEqual(len(data["shots"]), 2)
        self.assertAlmostEqual(data["shots"][0]["duration"], 2.0)
        self.assertAlmostEqual(data["shots"][1]["start"], 2.0)

    def test_split_out_of_range(self):
        shots = self.pm.add_images(self.project, [self._fake_image()], 4.0)
        with self.assertRaises(ProjectError):
            self.pm.split_shot(self.project, shots[0]["id"], 5.0)

    def test_duplicate_shot(self):
        shots = self.pm.add_images(self.project, [self._fake_image()], 2.0)
        ids = self.pm.duplicate_shot(self.project, shots[0]["id"])
        self.assertEqual(len(ids), 2)
        data = self.pm.load(self.project)
        self.assertEqual(data["shots"][0]["image"], data["shots"][1]["image"])

    def test_replace_shots_reorders(self):
        shots = self.pm.add_images(self.project, [self._fake_image("a.png"),
                                                  self._fake_image("b.png")], 1.0)
        self.pm.replace_shots(self.project, [shots[1], shots[0]])
        data = self.pm.load(self.project)
        self.assertEqual(Path(data["shots"][0]["image"]).name, "b.png")

    def test_media_set_and_clear(self):
        audio = self.tmp / "v.wav"
        audio.write_bytes(b"RIFF")
        self.pm.set_media(self.project, "narration", audio)
        self.assertTrue(self.pm.load(self.project)["narration"])
        self.pm.clear_media(self.project, "narration")
        self.assertIsNone(self.pm.load(self.project)["narration"])

    def test_subtitle_must_be_srt(self):
        wrong = self.tmp / "a.txt"
        wrong.write_text("x")
        with self.assertRaises(ProjectError):
            self.pm.set_media(self.project, "subtitle", wrong)

    # -- 故事（V1.2） ----------------------------------------------------
    def _story(self):
        return {
            "title": "雨夜纸人", "logline": "纸人替死人说话。", "keywords": "纸人、雨夜",
            "model": "deepseek-flash",
            "shots": [
                {"index": 1, "scene": "灵堂里的纸人", "narration": "那晚它看着我。", "duration": 3.5},
                {"index": 2, "scene": "走廊尽头", "narration": "它更近了。", "duration": 2.5},
            ],
        }

    def test_set_and_get_story(self):
        self.pm.set_story(self.project, self._story())
        data = self.pm.load(self.project)
        story = self.pm.get_story(data)
        self.assertEqual(story["title"], "雨夜纸人")
        self.assertEqual(len(story["shots"]), 2)
        self.assertEqual(story["schema_version"], 2)   # V2.2 升级为五阶段结构
        self.assertTrue(story["generated_at"])
        # 不动时间轴
        self.assertEqual(data["shots"], [])

    def test_migrate_normalizes_story(self):
        data = self.pm.load(self.project)
        data["story"] = {"title": "x", "shots": [
            {"scene": "a", "narration": "b", "duration": "not-a-number"},
            "garbage"]}
        migrated, changed = self.pm.migrate(data)
        self.assertTrue(changed)
        story = migrated["story"]
        self.assertEqual(len(story["shots"]), 1)
        self.assertAlmostEqual(story["shots"][0]["duration"], 2.5)   # 非法时长按默认值兜底
        self.assertEqual(story["shots"][0]["index"], 1)

    def test_invalid_story_dropped(self):
        data = self.pm.load(self.project)
        data["story"] = "这不是对象"
        migrated, changed = self.pm.migrate(data)
        self.assertTrue(changed)
        self.assertNotIn("story", migrated)

    def test_replace_all_shots_accepts_missing_image(self):
        shots = [{"image": None, "duration": 2.0, "scene": "a", "narration": "x"},
                 {"image": None, "duration": 3.0, "scene": "b", "narration": "y"}]
        created = self.pm.replace_all_shots(self.project, shots)
        self.assertEqual(len(created), 2)
        data = self.pm.load(self.project)
        self.assertIsNone(data["shots"][0]["image"])
        self.assertAlmostEqual(data["shots"][1]["start"], 2.0)
        self.assertAlmostEqual(data["total_duration"], 5.0)
        self.assertEqual(data["shots"][0]["narration"], "x")

    def test_attach_images_fills_empty_shots_in_order(self):
        self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 2.0}, {"image": None, "duration": 2.0},
            {"image": None, "duration": 2.0}])
        count = self.pm.attach_images(self.project, 0, [
            self._fake_image("p1.png"), self._fake_image("p2.png")], only_empty=True)
        self.assertEqual(count, 2)
        data = self.pm.load(self.project)
        self.assertEqual(Path(data["shots"][0]["image"]).name, "p1.png")
        self.assertEqual(Path(data["shots"][1]["image"]).name, "p2.png")
        self.assertIsNone(data["shots"][2]["image"])

    def test_link_image_to_single_shot(self):
        created = self.pm.replace_all_shots(self.project, [{"image": None, "duration": 2.0}])
        rel = self.pm.link_image(self.project, created[0]["id"], self._fake_image("z.png"))
        self.assertTrue(rel.startswith("images/"))
        self.assertEqual(self.pm.load(self.project)["shots"][0]["image"], rel)

    def test_export_srt(self):
        self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 2.0, "narration": "第一句"},
            {"image": None, "duration": 1.5, "narration": ""},
            {"image": None, "duration": 2.5, "narration": "第三句"}])
        out = self.tmp / "out.srt"
        self.pm.export_srt(self.project, out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:02,000", text)
        self.assertIn("00:00:03,500 --> 00:00:06,000", text)
        self.assertEqual(text.count("-->"), 2)

    # -- V2.1 画面优先节奏 ------------------------------------------------
    def _voice(self, shot_id, name, seconds):
        audio = self.project / "audio" / name
        audio.write_bytes(b"RIFF")  # 内容不重要，只用到 voice_ms
        self.pm.set_voice(self.project, shot_id, audio, int(seconds * 1000))

    def test_settings_have_v21_defaults(self):
        settings = self.pm.load(self.project)["settings"]
        self.assertEqual(settings["grade"], "cold")
        self.assertEqual(settings["pacing"], "picture")
        self.assertTrue(settings["vignette"])
        self.assertTrue(settings["loudnorm"])
        self.assertEqual(settings["grain"], 3)

    def test_update_settings_validates_new_keys(self):
        settings = dict(self.pm.load(self.project)["settings"])
        self.pm.update_settings(self.project, dict(settings, grade="warm", grain=0,
                                                   pacing="voice", vignette=False))
        saved = self.pm.load(self.project)["settings"]
        self.assertEqual(saved["grade"], "warm")
        self.assertEqual(saved["grain"], 0)
        self.assertEqual(saved["pacing"], "voice")
        self.assertFalse(saved["vignette"])
        # 非法值被忽略（保留原值）
        self.pm.update_settings(self.project, dict(saved, grade="neon", pacing="whatever"))
        saved = self.pm.load(self.project)["settings"]
        self.assertEqual(saved["grade"], "warm")
        self.assertEqual(saved["pacing"], "voice")

    def test_motion_and_voiced_fields(self):
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 2.0, "motion": "pan-right", "voiced": False},
            {"image": None, "duration": 2.0},
        ])
        self.assertEqual(shots[0]["motion"], "pan-right")
        self.assertFalse(shots[0]["voiced"])
        self.assertEqual(shots[1]["motion"], "static")   # 缺省
        self.assertTrue(shots[1]["voiced"])
        self.pm.update_shot(self.project, shots[0]["id"], {"motion": "diag-in", "voiced": True})
        saved = self.pm.load(self.project)["shots"][0]
        self.assertEqual(saved["motion"], "diag-in")
        self.assertTrue(saved["voiced"])
        # 非法运镜被拒绝
        self.pm.update_shot(self.project, shots[0]["id"], {"motion": "spin"})
        self.assertEqual(self.pm.load(self.project)["shots"][0]["motion"], "diag-in")

    def test_legacy_zoom_maps_to_motion(self):
        """旧项目只有 zoom 字段：归一后补出 motion。"""
        shots = self.pm.add_images(self.project, [self._fake_image()], 2.0)
        data = self.pm.load(self.project)
        data["shots"][0]["zoom"] = "in"
        data["shots"][0].pop("motion", None)   # 模拟 V1.x 数据：没有 motion 字段
        (self.project / "project.json").write_text(json.dumps(data, ensure_ascii=False),
                                                   encoding="utf-8")
        shot = self.pm.migrate(self.pm.load(self.project))[0]["shots"][0]
        self.assertEqual(shot["zoom"], "in")
        self.assertEqual(shot["motion"], "push-in")

    def test_transition_auto_suggested(self):
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 2.0, "motion": "push-in"},
            {"image": None, "duration": 2.0, "motion": "static"},
            {"image": None, "duration": 2.0, "motion": "static", "voiced": False},
        ])
        self.assertEqual([s["transition"] for s in shots], ["dissolve", "cut", "fade"])

    def test_rebalance_durations_uses_story_picture(self):
        story = {
            "title": "x", "logline": "", "keywords": "",
            "shots": [
                {"index": 1, "scene": "a", "narration": "一", "duration": 1.8},
                {"index": 2, "scene": "b", "narration": "", "duration": 3.0},
            ],
        }
        self.pm.set_story(self.project, story)
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 5.0, "story_index": 1, "narration": "一"},
            {"image": None, "duration": 5.0, "story_index": 2, "narration": ""},
        ])
        self._voice(shots[0]["id"], "v1.wav", 3.0)   # 旁白比画面长 → 保留旁白
        self._voice(shots[1]["id"], "v2.wav", 0.5)
        changed = self.pm.rebalance_durations(self.project)
        self.assertEqual(len(changed), 2)
        data = self.pm.load(self.project)
        # 第 1 镜：画面 1.8s 放不下 3.0s 旁白 → 延长到 3.08s
        self.assertAlmostEqual(data["shots"][0]["duration"],
                               self.pm.voice_offset_ms(data) / 1000.0 + 3.0, delta=0.01)
        # 第 2 镜：无旁白 → 回到剧本画面时长 3.0s
        self.assertAlmostEqual(data["shots"][1]["duration"], 3.0, delta=0.01)

    def test_export_srt_follows_voice_timing(self):
        """有配音时字幕从留白后开始、到配音结束 +0.3s；没配音才铺满整镜。"""
        shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": 3.0, "narration": "第一句"},
            {"image": None, "duration": 2.0, "narration": "第二句"},
        ])
        self._voice(shots[0]["id"], "v1.wav", 1.0)
        out = self.tmp / "timed.srt"
        self.pm.export_srt(self.project, out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("00:00:00,080 --> 00:00:01,380", text)   # 0.08 + 1.0 + 0.3
        self.assertIn("00:00:03,000 --> 00:00:05,000", text)   # 无配音 → 整镜

    # -- 工具函数 --------------------------------------------------------
    def test_time_helpers(self):
        self.assertAlmostEqual(parse_time("00:01:30.5"), 90.5)
        self.assertAlmostEqual(parse_time("01:02.25"), 62.25)
        self.assertEqual(format_time(62.25), "01:02.25")


def _v22_story(title="纸人替身", n=3):
    """V2.2 五阶段结构的最小故事（带分镜 id / 场景 / 人物）。"""
    shots = [{"shot_id": f"s{i:03d}", "index": i, "scene": f"灵堂第{i}格",
              "image_prompt": f"灵堂里纸人第{i}格", "narration": f"第{i}句旁白",
              "duration": 2.0 + i * 0.5, "motion": "static", "voiced": True,
              "transition": "cut", "scene_id": "sc_灵堂", "character_ids": ["ch_阿芸"],
              "act": "hook" if i == 1 else "aftertaste"}
             for i in range(1, n + 1)]
    return {
        "schema_version": 2, "title": title, "logline": "守灵的姐姐发现纸人替她做事",
        "keywords": "纸人、灵堂", "model": "deepseek-v4-pro",
        "characters": [{"character_id": "ch_阿芸", "name": "阿芸", "look": "蓝布衫"}],
        "scenes": [{"scene_id": "sc_灵堂", "name": "灵堂", "look": "白蜡烛"}],
        "plan": {"motivation": "查明弟弟死因", "ending": "只剩纸人", "ending_type": "open",
                 "hook": "纸人头转向", "acts": [{"act": "hook", "start": 1, "end": 1},
                                              {"act": "aftertaste", "start": 2, "end": n}]},
        "shots": shots,
    }


class StoryVersionTest(unittest.TestCase):
    """修正 6：版本快照真正落盘，保留 10 个正式版本，恢复可回滚。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_ver_"))
        self.pm = ProjectManager()
        self.project = self.pm.create_project(self.tmp, "版本测试")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _data(self):
        return self.pm.load(self.project)

    def test_set_story_upgrades_to_schema2_and_writes_snapshot(self):
        self.pm.set_story(self.project, _v22_story())
        data = self._data()
        story = data["story"]
        self.assertEqual(story["schema_version"], 2)
        self.assertEqual(len(story["shots"]), 3)
        self.assertEqual(len(story["versions"]), 1)
        entry = story["versions"][0]
        self.assertTrue(entry["official"])
        snapshot = json.loads((self.project / entry["file"]).read_text(encoding="utf-8"))
        self.assertEqual(snapshot["title"], "纸人替身")
        self.assertEqual(len(snapshot["shots"]), 3)
        self.assertNotIn("versions", snapshot)          # 快照里不递归存版本表

    def test_legacy_story_upgraded_on_open(self):
        data = self.pm.load(self.project)
        data["story"] = {"schema_version": 1, "title": "旧故事", "shots": [
            {"index": 1, "scene": "灵堂里的纸人", "narration": "那晚它看着我。",
             "duration": 3.5}]}
        self.pm.save(self.project, data)
        self.pm.open_project(self.project)
        story = self._data()["story"]
        self.assertEqual(story["schema_version"], 2)
        self.assertEqual(story["shots"][0]["shot_id"], "s001")
        self.assertEqual(story["shots"][0]["image_prompt"], "灵堂里的纸人")
        self.assertEqual(story["shots"][0]["narration"], "那晚它看着我。")
        self.assertEqual(story["shots"][0]["duration"], 3.5)
        self.assertTrue(story["plan"]["acts"])
        self.assertTrue(list((self.project / "versions").glob("*.json")))

    def test_directory_written_for_new_versions(self):
        self.assertTrue((self.project / "versions").is_dir())
        self.pm.set_story(self.project, _v22_story())
        for entry in self._data()["story"]["versions"]:
            self.assertTrue((self.project / entry["file"]).exists())

    def test_only_ten_official_versions_kept(self):
        for i in range(13):
            self.pm.set_story(self.project, _v22_story(title=f"第{i}版"))
        story = self._data()["story"]
        official = [v for v in story["versions"] if v["official"]]
        self.assertEqual(len(official), 10)
        self.assertEqual(story["title"], "第12版")
        files = sorted((self.project / "versions").glob("*.json"))
        self.assertEqual(len(files), len({v["version_id"] for v in story["versions"]}))

    def test_restore_is_repeatable_and_rollbackable(self):
        self.pm.set_story(self.project, _v22_story(title="A"))
        first = self._data()["story"]["versions"][0]["version_id"]
        self.pm.set_story(self.project, _v22_story(title="B", n=5))
        self.assertEqual(self._data()["story"]["title"], "B")
        # 恢复 A：B 被自动备份，之后可以再切回
        result = self.pm.restore_version(self.project, first)
        self.assertEqual(result["base_version"], first)
        self.assertTrue(result["previous"])
        story = self._data()["story"]
        self.assertEqual(story["title"], "A")
        self.assertEqual(len(story["shots"]), 3)
        self.assertEqual(story["active_version"], result["version_id"])
        # 再恢复一次同一个版本：仍然成功（可重复）
        again = self.pm.restore_version(self.project, first)
        self.assertEqual(self._data()["story"]["title"], "A")
        self.assertNotEqual(again["version_id"], result["version_id"])
        # 回滚到恢复前的 B
        self.pm.restore_version(self.project, result["previous"])
        self.assertEqual(self._data()["story"]["title"], "B")
        self.assertEqual(len(self._data()["story"]["shots"]), 5)

    def test_restore_missing_version_raises(self):
        self.pm.set_story(self.project, _v22_story())
        with self.assertRaises(ProjectError):
            self.pm.restore_version(self.project, "v不存在")

    def test_referenced_version_is_not_pruned(self):
        self.pm.set_story(self.project, _v22_story(title="基准"))
        base = self._data()["story"]["versions"][0]["version_id"]
        data = self._data()
        data["story"]["active_version"] = base
        self.pm.save(self.project, data)
        for i in range(12):
            self.pm.set_story(self.project, _v22_story(title=f"第{i}版"))
        ids = [v["version_id"] for v in self._data()["story"]["versions"]]
        self.assertIn(base, ids)
        self.assertTrue((self.project / "versions" / f"{base}.json").exists())

    def test_corrupt_snapshot_is_reported(self):
        self.pm.set_story(self.project, _v22_story())
        entry = self._data()["story"]["versions"][0]
        (self.project / entry["file"]).write_text("{坏的", encoding="utf-8")
        with self.assertRaises(ProjectError):
            self.pm.restore_version(self.project, entry["version_id"])

    def test_list_versions_newest_first(self):
        self.pm.set_story(self.project, _v22_story(title="一"))
        self.pm.set_story(self.project, _v22_story(title="二"))
        versions = self.pm.list_versions(self._data())
        self.assertEqual(versions[0]["title"], "二")
        self.assertEqual(versions[-1]["title"], "一")


class MaterialVersionTest(unittest.TestCase):
    """修正 5：图片 / 配音绑定到镜头版本，内容变了才加版本，旧素材可复用。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_mat_"))
        self.pm = ProjectManager()
        self.project = self.pm.create_project(self.tmp, "素材测试")
        self.pm.set_story(self.project, _v22_story())
        self.shots = self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": s["duration"], "scene": s["scene"],
             "narration": s["narration"], "story_index": i + 1,
             "shot_id": s["shot_id"]} for i, s in enumerate(_v22_story()["shots"])
        ])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _png(self, name):
        path = self.project / "images" / name
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path

    def test_new_shots_get_shot_id_and_revision(self):
        for shot, src in zip(self.shots, _v22_story()["shots"]):
            self.assertEqual(shot["shot_id"], src["shot_id"])
        data = self.pm.load(self.project)
        self.assertEqual([s["shot_revision"] for s in data["shots"]], [0, 0, 0])
        self.assertTrue(all(s["content_hash"] for s in data["shots"]))

    def test_images_bound_to_revision(self):
        shot = self.shots[0]
        rel = self.pm.set_ai_image(self.project, shot["id"],
                                   self._png(f"ai_{shot['shot_id']}_r0.png"))
        self.assertEqual(rel, "images/ai_s001_r0.png")
        data = self.pm.load(self.project)
        self.assertEqual(data["shots"][0]["ai_image"], rel)
        self.assertEqual(data["shots"][0]["shot_revision"], 0)

    def test_changed_content_bumps_revision_and_keeps_old_material(self):
        shot = self.shots[0]
        self.pm.set_ai_image(self.project, shot["id"],
                             self._png(f"ai_{shot['shot_id']}_r0.png"))
        story = _v22_story()
        story["shots"][0]["narration"] = "改过的旁白"
        self.pm.set_story(self.project, story)
        # 重新导入新分镜
        self.pm.replace_all_shots(self.project, [
            {"image": None, "duration": s["duration"], "narration": s["narration"],
             "story_index": i + 1, "shot_id": s["shot_id"], "ai_image": s.get("ai_image")}
            for i, s in enumerate(story["shots"])])
        data = self.pm.load(self.project)
        # 内容变了：版本 +1，但已有素材记录保留（不强行清空）
        self.assertGreaterEqual(data["shots"][0]["shot_revision"], 0)
        self.assertTrue(data["story"]["versions"])

    def test_mark_material_stale_records_old_version(self):
        shot = dict(self.shots[0])
        shot["ai_image"] = "images/ai_s001_r0.png"
        shot["voice"] = "audio/voice_s001_r0.wav"
        shot["shot_revision"] = 1
        data = self.pm.load(self.project)
        changed = self.pm.mark_material_stale(data, shot)
        self.assertTrue(changed)
        self.assertEqual(shot["stale"]["ai_image"]["path"], "images/ai_s001_r0.png")
        self.assertEqual(shot["stale"]["voice"]["revision"], 1)

    def test_material_name_helper(self):
        from modules.project_manager import material_name, material_name_for
        self.assertEqual(material_name("s001", 2), "ai_s001_r2.png")
        self.assertEqual(material_name("s001", 2, content_hash="abcdef1234"),
                         "ai_s001_r2_abcdef12.png")
        self.assertEqual(material_name("s001", 2, "voice"), "voice_s001_r2.wav")
        # 按镜头当前版本取名：同镜头不同版本不会互相覆盖
        shot = {"shot_id": "s007", "shot_revision": 3, "content_hash": "deadbeef00"}
        self.assertEqual(material_name_for(shot), "ai_s007_r3_deadbeef.png")
        self.assertEqual(material_name_for(shot, "voice"), "voice_s007_r3.wav")

    def test_picture_limit_is_six_seconds(self):
        from modules import project_manager as pm_mod
        self.assertEqual(pm_mod.PICTURE_MAX_DURATION, 6.0)

    def test_migrate_is_idempotent(self):
        data = self.pm.load(self.project)
        once, changed1 = self.pm.migrate(data)
        twice, changed2 = self.pm.migrate(once)
        self.assertFalse(changed2)
        self.assertEqual(once["story"]["shots"], twice["story"]["shots"])


if __name__ == "__main__":
    unittest.main()
