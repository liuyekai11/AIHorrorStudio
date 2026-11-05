"""V2.2 故事页 UI 辅助逻辑测试（不需要 GUI）。

story_panel 是 tkinter 面板，CI 机器上可能没有显示；这里只测纯逻辑部分
（score_text 摘要），以及在没有注入五阶段回调时 _on_generate 的回退路径
（需要 Tk，显示不可用时跳过）。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.story_panel import score_text, GRADE_LABELS  # noqa: E402


class ScoreTextTest(unittest.TestCase):
    def test_empty_without_quality(self):
        self.assertEqual(score_text(None), "")
        self.assertEqual(score_text({}), "")
        self.assertEqual(score_text({"title": "x", "quality": {}}), "")

    def test_basic_score_and_grade(self):
        text = score_text({
            "quality": {"score": 82, "grade": "excellent",
                        "scores": {}, "vetoes": []}})
        self.assertIn("82", text)
        self.assertIn(GRADE_LABELS["excellent"], text)

    def test_per_dimension_scores(self):
        text = score_text({
            "quality": {"score": 60, "grade": "pass",
                        "scores": {"story_completeness": 18, "logic": 15,
                                   "suspense": 10, "horror_atmosphere": 9,
                                   "characterization": 6, "reversal": 5,
                                   "dialogue_narration": 4, "shot_design": 3},
                        "vetoes": []}})
        self.assertIn("剧情完整性 18/20", text)
        self.assertIn("逻辑合理性 15/20", text)
        self.assertIn("分镜表现力 3/5", text)

    def test_vetoes_listed(self):
        text = score_text({
            "quality": {"score": 95, "grade": "regenerate",
                        "scores": {},
                        "vetoes": [{"code": "missing_motivation", "message": ""}]}})
        self.assertIn("人物动机缺失", text)

    def test_veto_message_falls_back_to_code_label(self):
        text = score_text({
            "quality": {"score": 50, "grade": "regenerate", "scores": {},
                        "vetoes": [{"code": "missing_motivation"}]}})
        self.assertIn("人物动机缺失", text)

    def test_non_numeric_values_ignored(self):
        text = score_text({
            "quality": {"score": "abc", "grade": "pass",
                        "scores": {"logic": "n/a"}, "vetoes": []}})
        self.assertIn("0", text)
        self.assertNotIn("n/a", text)


if __name__ == "__main__":
    unittest.main()


class RepaceStoryTest(unittest.TestCase):
    """镜头增 / 删 / 改后必须按当前镜头列表重算时长，总时长仍等于目标。"""

    @staticmethod
    def _story(n, target):
        from modules import pacing
        block = {"target_seconds": target, "total_seconds": target}
        shots = [{"shot_id": f"s{i:03d}", "beat": "setup",
                  "narration": "雨" * (i % 7), "duration": round(target / n, 2)}
                 for i in range(1, n + 1)]
        return {"shots": shots, "pacing": dict(block),
                "total_duration": round(sum(s["duration"] for s in shots), 2)}, pacing

    def _assert_ok(self, story, target):
        from modules import pacing
        durations = [s["duration"] for s in story["shots"]]
        self.assertEqual(len(durations), len(story["shots"]))
        self.assertTrue(all(pacing.MIN_SECONDS - 1e-9 <= d <= pacing.MAX_SECONDS + 1e-9
                            for d in durations))
        self.assertLessEqual(abs(sum(durations) - target), pacing.TOTAL_TOLERANCE)
        self.assertEqual(story["pacing"]["shot_count"], len(story["shots"]))
        self.assertEqual(story["total_duration"], round(sum(durations), 2))

    def test_insert_recomputes(self):
        from modules.story_panel import repace_story
        story, _ = self._story(10, 40.0)
        story["shots"].insert(5, {"scene": "新镜", "narration": "", "duration": 3.5})
        self.assertTrue(repace_story(story))
        self._assert_ok(story, 40.0)

    def test_delete_recomputes(self):
        from modules.story_panel import repace_story
        story, _ = self._story(10, 40.0)
        story["shots"].pop(3)
        self.assertTrue(repace_story(story))
        self._assert_ok(story, 40.0)

    def test_edit_recomputes(self):
        from modules.story_panel import repace_story
        story, _ = self._story(8, 32.0)
        story["shots"][0]["duration"] = 6.0
        story["shots"][1]["duration"] = 1.5
        self.assertTrue(repace_story(story))
        self._assert_ok(story, 32.0)

    def test_inconsistent_sum_is_fixed_on_open(self):
        from modules.story_panel import repace_story
        story, _ = self._story(10, 40.0)
        for shot in story["shots"]:
            shot["duration"] = 2.0          # 总和 20 ≠ 目标 40
        self.assertTrue(repace_story(story))
        self._assert_ok(story, 40.0)

    def test_consistent_story_is_left_alone(self):
        from modules.story_panel import repace_story
        story, _ = self._story(10, 40.0)
        before = [s["duration"] for s in story["shots"]]
        self.assertFalse(repace_story(story))
        self.assertEqual([s["duration"] for s in story["shots"]], before)

    def test_corrupt_story_is_not_modified(self):
        from modules.story_panel import repace_story
        self.assertFalse(repace_story(None))
        self.assertFalse(repace_story({}))
        self.assertFalse(repace_story({"shots": []}))
        story = {"shots": [{"duration": "abc"}, {}], "pacing": {"target_seconds": 10}}
        # 类型不对的时长可以按目标补正（这是修复而不是破坏），但不得改镜头数量
        repace_story(story)
        self.assertEqual(len(story["shots"]), 2)
        self.assertTrue(all(isinstance(s.get("duration"), float) for s in story["shots"]))
        # 完全无法分配（空镜头 / 坏结构）时原样返回，不抛异常、不改数据
        self.assertFalse(repace_story({"shots": [], "pacing": {"target_seconds": 10}}))
        bad = {"shots": "坏数据", "pacing": {"target_seconds": 10}}
        self.assertFalse(repace_story(bad))
        self.assertEqual(bad["shots"], "坏数据")
