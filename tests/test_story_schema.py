"""故事数据结构测试（纯逻辑，不联网）。

覆盖用户 2026-11-04 批准的修正 4、5、6 里与数据结构有关的部分：
  * 角色可跨场景、镜头引用的人物 / 场景必须存在
  * shot_id 稳定 + revision / content_hash 用于素材版本关联
  * 旧 schema 1 故事零手工迁移到 schema 2，旧字段全部保留、升级可重复执行
  * 质量评分 8 项合计 100、等级、硬性否决
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import story_schema as ss  # noqa: E402


def _legacy_story():
    return {
        "title": "雨夜纸人",
        "logline": "葬礼后，纸人开始替死人说话。",
        "keywords": "废弃医院、纸人、雨夜",
        "characters": [{"name": "阿芸", "look": "黑长发，白孝衣"},
                       {"name": "老陈", "look": "灰棉袄，驼背"}],
        "scenes": [{"name": "灵堂", "look": "白蜡烛，棺材"}, {"name": "走廊", "look": "长长的走廊"}],
        "shots": [
            {"index": 1, "scene": "阿芸在灵堂点香，纸人在她背后", "narration": "它们在看我",
             "duration": 2.5, "motion": "push-in"},
            {"index": 2, "scene": "走廊尽头的门突然开了", "narration": "", "duration": 1.2,
             "voiced": False},
            {"index": 3, "scene": "老陈伸出手拉住阿芸", "narration": "别回头", "duration": 4},
            {"index": 4, "scene": "阿芸在走廊回头，看见另一个自己", "narration": "原来我一直站在这里",
             "duration": 3, "motion": "diag-in"},
            {"index": 5, "scene": "空荡的灵堂", "narration": "雨终于停了", "duration": 2},
        ],
    }


class IdTests(unittest.TestCase):
    def test_character_scene_ids_are_readable(self):
        chars = ss.normalize_characters([{"name": "阿芸", "look": "黑发"}])
        self.assertEqual(chars[0]["character_id"], "ch_阿芸")
        scenes = ss.normalize_scenes([{"name": "灵堂", "look": "蜡烛"}])
        self.assertEqual(scenes[0]["scene_id"], "sc_灵堂")

    def test_duplicate_names_get_unique_ids(self):
        chars = ss.normalize_characters([{"name": "阿芸", "look": "黑发"},
                                         {"name": "阿芸", "look": "白裙"}])
        self.assertEqual(len({c["character_id"] for c in chars}), 2)

    def test_empty_id_is_generated(self):
        concept = ss.StoryConcept.from_dict({"core_conflict": "c", "hook": "h"}).validate()
        self.assertTrue(concept.concept_id)


class ValidationTests(unittest.TestCase):
    def test_character_requires_look(self):
        with self.assertRaises(ss.SchemaError):
            ss.normalize_characters([{"name": "阿芸"}])

    def test_scene_requires_look(self):
        with self.assertRaises(ss.SchemaError):
            ss.normalize_scenes([{"name": "灵堂"}])

    def test_plan_requires_core_fields(self):
        with self.assertRaises(ss.SchemaError):
            ss.StoryPlan(theme="t", motivation="m", hook="h", ending="e").validate()

    def test_concept_requires_conflict_and_hook(self):
        with self.assertRaises(ss.SchemaError):
            ss.StoryConcept(title="t", core_conflict="c").validate()

    def test_unknown_ids_are_rejected(self):
        """修正 4：每个镜头实际引用的人物 / 场景必须存在。"""
        with self.assertRaises(ss.SchemaError):
            ss.normalize_shots([{"image_prompt": "x", "scene_id": "sc_不存在"}],
                               scene_ids=["sc_灵堂"])
        with self.assertRaises(ss.SchemaError):
            ss.normalize_shots([{"image_prompt": "x", "character_ids": ["ch_鬼"]}],
                               character_ids=["ch_阿芸"])

    def test_character_can_appear_in_several_scenes(self):
        """修正 4：不得限制角色只能属于一个场景。"""
        chars = ss.normalize_characters([
            {"name": "阿芸", "look": "黑发", "scene_ids": ["sc_灵堂", "sc_走廊"]}])
        self.assertEqual(chars[0]["scene_ids"], ["sc_灵堂", "sc_走廊"])
        shots = ss.normalize_shots([
            {"image_prompt": "阿芸在灵堂", "scene_id": "sc_灵堂", "character_ids": ["ch_阿芸"]},
            {"image_prompt": "阿芸在走廊", "scene_id": "sc_走廊", "character_ids": ["ch_阿芸"]},
        ], scene_ids=["sc_灵堂", "sc_走廊"], character_ids=["ch_阿芸"])
        self.assertEqual({s["scene_id"] for s in shots}, {"sc_灵堂", "sc_走廊"})
        self.assertTrue(all("ch_阿芸" in s["character_ids"] for s in shots))
        self.assertEqual([s["shot_id"] for s in shots], ["s001", "s002"])

    def test_shot_narration_cleared_when_not_voiced(self):
        shots = ss.normalize_shots([{"image_prompt": "x", "narration": "话", "voiced": False}])
        self.assertEqual(shots[0]["narration"], "")

    def test_shot_duration_clamped(self):
        shots = ss.normalize_shots([{"image_prompt": "a", "duration": 99},
                                    {"image_prompt": "b", "duration": 0.1}])
        self.assertEqual([s["duration"] for s in shots], [ss.MAX_SHOT_DURATION, ss.MIN_SHOT_DURATION])

    def test_shot_defaults(self):
        shot = ss.normalize_shots([{"image_prompt": "x", "motion": "圈圈转"}])[0]
        self.assertEqual(shot["motion"], "static")
        self.assertEqual(shot["transition"], "cut")
        self.assertEqual(shot["revision"], 0)

    def test_dialogue_normalized(self):
        script = ss.normalize_script([{
            "segment_id": "g1", "scene_id": "灵堂", "narration": "雨一直下",
            "dialogue": ["走吧", {"character_id": "ch_老陈", "text": "别回头", "emotion": "急促"}],
        }], scene_ids=["灵堂"], character_ids=["ch_老陈"])
        self.assertEqual([d["text"] for d in script[0]["dialogue"]], ["走吧", "别回头"])
        self.assertEqual(script[0]["dialogue"][1]["emotion"], "急促")

    def test_existing_shot_ids_are_kept(self):
        shots = ss.normalize_shots([{"shot_id": "s010", "image_prompt": "a"},
                                    {"image_prompt": "b"}])
        self.assertEqual(shots[0]["shot_id"], "s010")
        self.assertNotEqual(shots[1]["shot_id"], "s010")


class ContentHashTests(unittest.TestCase):
    """修正 5：素材要能绑定到明确的镜头版本。"""

    def test_hash_is_stable_and_short(self):
        shot = {"image_prompt": "雨夜", "narration": "它在看", "motion": "static", "duration": 3.0}
        h1 = ss.shot_content_hash(shot)
        h2 = ss.shot_content_hash(dict(shot))
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_hash_changes_with_content(self):
        base = {"image_prompt": "雨夜", "narration": "它在看", "motion": "static", "duration": 3.0}
        changed = dict(base, narration="它不在看")
        self.assertNotEqual(ss.shot_content_hash(base), ss.shot_content_hash(changed))
        changed = dict(base, duration=4.0)
        self.assertNotEqual(ss.shot_content_hash(base), ss.shot_content_hash(changed))

    def test_hash_does_not_change_with_metadata(self):
        base = {"image_prompt": "雨夜", "narration": "它在看", "motion": "static", "duration": 3.0}
        self.assertEqual(ss.shot_content_hash(base),
                         ss.shot_content_hash(dict(base, shot_id="s001", revision=4)))

    def test_hash_accepts_dataclass(self):
        shot = ss.StoryboardShot(image_prompt="雨夜", duration=3.0)
        self.assertEqual(len(ss.shot_content_hash(shot)), 16)


class QualityTests(unittest.TestCase):
    def test_score_weights_sum_to_100(self):
        self.assertEqual(sum(ss.SCORE_WEIGHTS.values()), 100)
        self.assertEqual(len(ss.SCORE_WEIGHTS), 8)

    def test_full_marks_pass(self):
        report = ss.QualityReport(scores=dict(ss.SCORE_WEIGHTS))
        self.assertEqual(report.compute_score(), 100.0)
        self.assertEqual(report.grade, "excellent")
        self.assertTrue(report.passed)

    def test_scores_are_capped_per_dimension(self):
        report = ss.QualityReport(scores={"story_completeness": 999})
        self.assertEqual(report.compute_score(), 20.0)

    def test_grades(self):
        self.assertEqual(ss.grade_for(85), "excellent")
        self.assertEqual(ss.grade_for(84.9), "pass")
        self.assertEqual(ss.grade_for(75), "pass")
        self.assertEqual(ss.grade_for(74.9), "needs_work")
        self.assertEqual(ss.grade_for(60), "needs_work")
        self.assertEqual(ss.grade_for(59.9), "regenerate")

    def test_veto_blocks_pass_regardless_of_score(self):
        report = ss.QualityReport(scores=dict(ss.SCORE_WEIGHTS), vetoes=[{"code": "weak_hook"}])
        report.compute_score()
        self.assertEqual(report.grade, "excellent")
        self.assertFalse(report.passed)
        self.assertEqual(report.veto_codes(), ["weak_hook"])

    def test_low_score_does_not_pass(self):
        report = ss.QualityReport(scores={"story_completeness": 10, "logic": 10})
        self.assertEqual(report.compute_score(), 20.0)
        self.assertEqual(report.grade, "regenerate")
        self.assertFalse(report.passed)

    def test_from_model_tolerates_chinese_keys_and_strings(self):
        report = ss.QualityReport.from_model({
            "scores": {"剧情完整性": 18, "logic": "9", "反转": 6},
            "vetoes": "结局意外中断",
            "issues": [{"stage": "storyboard", "shot_id": "s003", "severity": "error",
                        "message": "镜头引用的人物不存在", "suggestion": "改回阿芸"}],
        })
        self.assertEqual(report.scores["story_completeness"], 18)
        self.assertEqual(report.scores["logic"], 9)
        self.assertEqual(report.scores["reversal"], 6)
        self.assertEqual(report.score, 33.0)
        self.assertEqual(len(report.vetoes), 1)
        self.assertEqual(report.issues[0].shot_id, "s003")
        self.assertFalse(report.passed)

    def test_exact_score_does_not_drift(self):
        # V2.1 上线过的取整丢分问题：18+9+6 必须正好 33，而不是 33.00000001 → 32.9
        report = ss.QualityReport.from_model({"scores": {"story_completeness": 18,
                                                         "logic": 9, "reversal": 6}})
        self.assertEqual(report.score, 33.0)

    def test_issue_requires_message(self):
        with self.assertRaises(ss.SchemaError):
            ss.QualityIssue(stage="plan", severity="error").validate()

    def test_all_veto_codes_documented(self):
        for code in ("missing_motivation", "weak_hook", "abrupt_end",
                     "unknown_reference", "duration_mismatch", "unforeshadowed_reversal"):
            self.assertIn(code, ss.VETO_CODES)


class UpgradeTests(unittest.TestCase):
    def test_upgrade_preserves_legacy_fields(self):
        old = _legacy_story()
        new, changed = ss.upgrade_story(old)
        self.assertTrue(changed)
        self.assertEqual(new["schema_version"], ss.SCHEMA_VERSION)
        for a, b in zip(old["shots"], new["shots"]):
            for key in ("index", "scene", "narration", "duration", "motion", "voiced"):
                if key in a:
                    self.assertEqual(a[key], b.get(key), key)

    def test_upgrade_keeps_names_and_looks(self):
        new, _ = ss.upgrade_story(_legacy_story())
        self.assertEqual([c["name"] for c in new["characters"]], ["阿芸", "老陈"])
        self.assertEqual(new["characters"][0]["look"], "黑长发，白孝衣")
        self.assertEqual([s["name"] for s in new["scenes"]], ["灵堂", "走廊"])

    def test_upgrade_infers_scene_and_characters(self):
        new, _ = ss.upgrade_story(_legacy_story())
        shots = new["shots"]
        self.assertEqual(shots[0]["scene_id"], "sc_灵堂")
        self.assertIn("ch_阿芸", shots[0]["character_ids"])
        self.assertEqual(shots[1]["scene_id"], "sc_走廊")
        self.assertTrue(all(s["shot_id"] for s in shots))
        self.assertEqual(set(shots[2]["character_ids"]), {"ch_老陈", "ch_阿芸"})

    def test_upgrade_does_not_guess_ambiguous_scene(self):
        story = {"scenes": [{"name": "门", "look": "a"}, {"name": "红门", "look": "b"}],
                 "shots": [{"scene": "红门旁边还有一扇门", "narration": "x"}]}
        new, _ = ss.upgrade_story(story)
        self.assertIn(new["shots"][0]["scene_id"], ("", "sc_门", "sc_红门"))

    def test_upgrade_builds_plan_script_pacing(self):
        new, _ = ss.upgrade_story(_legacy_story())
        self.assertTrue(new["plan"]["acts"])
        self.assertEqual(sorted(new["plan"]["acts"][0]), ["act", "end", "start", "summary"])
        self.assertEqual(len(new["script"]), len(new["shots"]))
        self.assertEqual([s["script_segment_id"] for s in new["shots"]],
                         [seg["segment_id"] for seg in new["script"]])
        self.assertEqual(new["pacing"]["shot_count"], len(new["shots"]))
        self.assertGreater(new["pacing"]["target_seconds"], 0)
        self.assertEqual(new["versions"], [])
        self.assertEqual(new["stale"], {})

    def test_upgrade_act_ranges_are_monotonic(self):
        new, _ = ss.upgrade_story({"shots": [{"scene": f"画面{i}", "narration": ""}
                                             for i in range(12)]})
        acts = new["plan"]["acts"]
        self.assertTrue(acts)
        for act in acts:
            self.assertLessEqual(act["start"], act["end"])
        for prev, nxt in zip(acts, acts[1:]):
            self.assertLessEqual(prev["end"], nxt["start"])

    def test_upgrade_is_idempotent(self):
        once, _ = ss.upgrade_story(_legacy_story())
        twice, changed = ss.upgrade_story(once)
        self.assertFalse(changed)
        self.assertEqual(once, twice)

    def test_upgrade_keeps_existing_plan(self):
        story = _legacy_story()
        story["plan"] = {"core_conflict": "c", "motivation": "m", "hook": "h", "ending": "e",
                         "acts": [{"act": "hook", "start": 1, "end": 2}]}
        new, _ = ss.upgrade_story(story)
        self.assertEqual(new["plan"]["core_conflict"], "c")
        self.assertEqual(new["plan"]["acts"], [{"act": "hook", "start": 1, "end": 2}])

    def test_upgrade_golden_topic_kept(self):
        story = _legacy_story()
        story["golden_topic"] = "废弃医院、纸人、雨夜"
        new, _ = ss.upgrade_story(story)
        self.assertEqual(new["golden_topic"], "废弃医院、纸人、雨夜")

    def test_upgrade_rejects_non_dict(self):
        with self.assertRaises(ss.SchemaError):
            ss.upgrade_story([])

    def test_upgrade_empty_story(self):
        new, changed = ss.upgrade_story({})
        self.assertTrue(changed)
        self.assertEqual(new["shots"], [])
        self.assertEqual(new["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
