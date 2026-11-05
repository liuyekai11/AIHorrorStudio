"""动态时长规划器测试（纯逻辑，不联网）。

对应用户 2026-11-04 批准的修正 1：
  单镜 1.5~6 秒；超出上下限的剩余时长重新分配给有剩余容量的镜头；
  无法满足目标时长时自动调整镜头数量或提示错误；总时长误差不超过 1 秒。
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import pacing  # noqa: E402
from modules.pacing import (MIN_SECONDS, MAX_SECONDS, PacingError,  # noqa: E402
                            TOTAL_TOLERANCE)


def _shots(n, beat_cycle=True):
    beats = ("hook", "setup", "escalation", "reversal", "aftertaste")
    out = []
    for i in range(n):
        out.append({
            "beat": beats[i % 5] if beat_cycle else "setup",
            "narration": "" if i % 4 == 2 else "雨落在灵堂的纸人身上，它在看我。"[: 3 + (i * 7) % 18],
            "voiced": i % 4 != 2,
        })
    return out


def _is_fallback(result):
    """无法满足目标时返回的兜底结果（自带提示文字）。"""
    return bool(result.get("message"))


class FeasibleRangeTests(unittest.TestCase):
    def test_range(self):
        self.assertEqual(pacing.feasible_range(3), (4.5, 18.0))

    def test_adjust_shot_count_keeps_feasible_count(self):
        self.assertEqual(pacing.adjust_shot_count(120, 36), 36)

    def test_adjust_shot_count_clamps_into_math_range(self):
        # 208 秒：至少 35 个镜头（35×6=210）
        n = pacing.adjust_shot_count(208)
        self.assertGreaterEqual(n, 35)
        self.assertLessEqual(n, 138)

    def test_adjust_shot_count_rejects_non_positive(self):
        with self.assertRaises(PacingError):
            pacing.adjust_shot_count(0)


class ReadingTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(pacing.reading_seconds(""), 0.0)

    def test_longer_text_reads_longer(self):
        self.assertLess(pacing.reading_seconds("雨"), pacing.reading_seconds("雨一直下" * 6))


class AllocateTests(unittest.TestCase):
    def test_bounds_hold(self):
        for n in (1, 2, 5, 30, 50):
            for target in (n * MIN_SECONDS, n * 2.2, n * 4.0, n * MAX_SECONDS):
                out = pacing.allocate(target, [1.0] * n)
                self.assertEqual(len(out), n)
                for d in out:
                    self.assertGreaterEqual(d, MIN_SECONDS - 1e-9)
                    self.assertLessEqual(d, MAX_SECONDS + 1e-9)
                self.assertAlmostEqual(sum(out), target, delta=1e-6)

    def test_high_weight_shot_gets_more_time(self):
        out = pacing.allocate(30.0, [4.0, 0.5, 0.5, 0.5, 0.5, 0.5])
        self.assertGreater(out[0], out[1])
        self.assertAlmostEqual(sum(out), 30.0, delta=1e-6)

    def test_extreme_weight_is_capped_and_rest_redistributed(self):
        # 权重 1000 的镜头最多 6 秒，其余时长必须分给别的镜头
        out = pacing.allocate(40.0, [1000.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        self.assertLessEqual(out[0], MAX_SECONDS + 1e-9)
        self.assertAlmostEqual(sum(out), 40.0, delta=1e-6)

    def test_infeasible_target_raises(self):
        with self.assertRaises(PacingError):
            pacing.allocate(20.0, [1.0, 1.0])       # 2 镜最多 12 秒
        with self.assertRaises(PacingError):
            pacing.allocate(2.0, [1.0, 1.0])        # 2 镜最少 3 秒

    def test_exact_bounds_are_reachable(self):
        out = pacing.allocate(12.0, [1.0, 1.0])
        self.assertAlmostEqual(sum(out), 12.0, delta=1e-6)
        self.assertTrue(all(abs(d - 6.0) < 1e-6 for d in out))
        out = pacing.allocate(3.0, [1.0, 1.0])
        self.assertAlmostEqual(sum(out), 3.0, delta=1e-6)

    def test_empty_raises(self):
        with self.assertRaises(PacingError):
            pacing.allocate(10.0, [])


class PlanDurationsTests(unittest.TestCase):
    def test_feasible_targets_within_one_second(self):
        cases = [(30, 120.0), (30, 180.0), (36, 200.0), (40, 240.0), (50, 300.0), (12, 40.0)]
        for n, target in cases:
            with self.subTest(n=n, target=target):
                result = pacing.plan_durations(_shots(n), target)
                self.assertEqual(result["shot_count"], n)
                self.assertLessEqual(abs(result["total"] - target), TOTAL_TOLERANCE)
                for d in result["durations"]:
                    self.assertGreaterEqual(d, MIN_SECONDS)
                    self.assertLessEqual(d, MAX_SECONDS)
                self.assertEqual(result["error"], round(result["total"] - target, 2))

    def test_feasible_bound_targets_hit_exactly(self):
        # 35 镜要 210 秒：只能每镜 6 秒（数学上刚好可行），总长必须正好 210；
        # 35 镜要 52.5 秒：只能每镜 1.5 秒
        result = pacing.plan_durations(_shots(35), 210.0)
        self.assertEqual(result["total"], 210.0)
        self.assertTrue(all(d == MAX_SECONDS for d in result["durations"]))
        result = pacing.plan_durations(_shots(30), 45.0)
        self.assertEqual(result["total"], 45.0)
        self.assertTrue(all(d == MIN_SECONDS for d in result["durations"]))

    def test_weights_follow_beats(self):
        result = pacing.plan_durations(_shots(10), 40.0)
        beats = [p["beat"] for p in result["per_shot"]]
        self.assertIn("hook", beats)
        self.assertIn("aftertaste", beats)
        # 余味权重 > 反转权重：权重表应从 pacing.DEFAULT_WEIGHTS 读取
        self.assertEqual(result["weights"]["aftertaste"], pacing.DEFAULT_WEIGHTS["aftertaste"])

    def test_no_target_keeps_hints_clamped(self):
        shots = [{"beat": "hook", "narration": "一"}, {"beat": "setup", "npm": "", "duration": 99},
                 {"beat": "aftertaste", "duration": 0.2}]
        result = pacing.plan_durations(shots, None)
        self.assertIsNone(result["target"])
        self.assertEqual(len(result["durations"]), 3)
        for d in result["durations"]:
            self.assertGreaterEqual(d, MIN_SECONDS)
            self.assertLessEqual(d, MAX_SECONDS)

    def test_too_many_shots_for_target_falls_back_with_message(self):
        # 50 镜最少 75 秒，目标只有 40 秒且不允许改镜数 → 提示并给出可行结果
        result = pacing.plan_durations(_shots(50), 40.0, allow_resize=False)
        self.assertTrue(result["message"])
        self.assertIn("40", result["message"])
        for d in result["durations"]:
            self.assertGreaterEqual(d, MIN_SECONDS)
            self.assertLessEqual(d, MAX_SECONDS)

    def test_too_few_shots_for_target_falls_back_with_message(self):
        # 10 镜最多 60 秒，目标 180 秒 → 提示加镜头，并给出最大可行总长
        result = pacing.plan_durations(_shots(10), 180.0, allow_resize=False)
        self.assertTrue(result["message"])
        self.assertAlmostEqual(result["total"], 60.0, delta=TOTAL_TOLERANCE)
        for d in result["durations"]:
            self.assertLessEqual(d, MAX_SECONDS)

    def test_fallback_suggests_reachable_shot_count(self):
        result = pacing.plan_durations(_shots(10), 180.0)
        self.assertIn("30", result["message"])       # ceil(180/6) = 30

    def test_allow_resize_trims_excess_shots(self):
        result = pacing.plan_durations(_shots(50), 40.0, allow_resize=True)
        self.assertTrue(result["resized"])
        self.assertEqual(result["shot_count"], pacing.adjust_shot_count(40))
        self.assertLessEqual(abs(result["total"] - 40.0), TOTAL_TOLERANCE)

    def test_allow_resize_reports_when_shots_are_too_few(self):
        result = pacing.plan_durations(_shots(10), 180.0, allow_resize=True)
        self.assertTrue(result["message"])

    def test_empty_shots_raise(self):
        with self.assertRaises(PacingError):
            pacing.plan_durations([], 60.0)

    def test_randomized_property(self):
        """随机 5000 组：可行目标必须落在 1 秒误差内且每镜在 1.5~6 秒。"""
        rng = random.Random(20261104)
        bad = 0
        for _ in range(5000):
            n = rng.randint(1, 60)
            target = rng.uniform(n * MIN_SECONDS, n * MAX_SECONDS)
            shots = _shots(n)
            for s in shots:
                s["beat"] = rng.choice(("hook", "setup", "escalation", "reversal", "aftertaste"))
                s["narration"] = "雨" * rng.randint(0, 40)
                s["voiced"] = rng.random() > 0.2
            result = pacing.plan_durations(shots, target)
            if _is_fallback(result):
                bad += 1
                continue
            if any(d < MIN_SECONDS - 1e-9 or d > MAX_SECONDS + 1e-9 for d in result["durations"]):
                bad += 1
            elif abs(result["total"] - target) > TOTAL_TOLERANCE + 1e-9:
                bad += 1
        self.assertEqual(bad, 0)

    def test_rounded_to_cent(self):
        result = pacing.plan_durations(_shots(24), 100.0)
        for d in result["durations"]:
            self.assertEqual(round(d, 2), d)

    def test_duration_error_helper(self):
        self.assertAlmostEqual(pacing.duration_error(100.4, 100.0), 0.4)
        self.assertTrue(pacing.within_tolerance(100.9, 100.0))
        self.assertFalse(pacing.within_tolerance(101.5, 100.0))


if __name__ == "__main__":
    unittest.main()


class ShotCountCoverageTests(unittest.TestCase):
    """每个镜头都必须拿到独立时长，数量与输入一致（用户 2026-11-05 的 8 条报告）。"""

    def test_each_shot_count_gets_matching_durations(self):
        for n in (1, 8, 10, 20):
            for target in (n * 2.0, n * 3.5, n * 5.0):
                with self.subTest(n=n, target=target):
                    shots = _shots(n)
                    result = pacing.plan_durations(shots, target)
                    self.assertEqual(result["shot_count"], n)
                    self.assertEqual(len(result["durations"]), n)
                    self.assertEqual(result["kept_count"], n)
                    self.assertEqual(result["kept_shot_ids"], list(range(n)))
                    self.assertEqual(len(result["per_shot"]), n)
                    self.assertTrue(all(isinstance(d, float) for d in result["durations"]))
                    self.assertAlmostEqual(sum(result["durations"]), target, delta=TOTAL_TOLERANCE)
                    self.assertIsNone(result["trimmed_index"])

    def test_trimmed_result_maps_durations_to_kept_shots(self):
        # 50 镜塞 40 秒：必须截断，并把「哪些镜头拿到了时长」告诉调用方
        shots = [dict(s, shot_id=f"s{i + 1:03d}") for i, s in enumerate(_shots(50))]
        result = pacing.plan_durations(shots, 40.0, allow_resize=True)
        self.assertTrue(result["resized"])
        self.assertEqual(result["kept_count"], len(result["durations"]))
        self.assertEqual(result["shot_count"], len(result["durations"]))
        self.assertEqual(result["kept_shot_ids"], [s["shot_id"] for s in shots[:result["kept_count"]]])
        self.assertEqual(result["trimmed_index"], list(range(result["kept_count"], 50)))

    def test_abnormal_shots_do_not_break_count(self):
        # 空旁白 / 空 beat / 空字符串时长 / None 时长：仍然每镜一条
        shots = [
            {"beat": "", "narration": "", "duration": ""},
            {"beat": "setup", "narration": "", "duration": None},
            {"beat": "hook", "narration": "雨夜五。", "duration": "abc"},
            {"beat": "reversal", "narration": "     "},
            {"beat": "aftertaste", "narration": "回到镜子前。", "duration": 99},
        ]
        result = pacing.plan_durations(shots, 20.0)
        self.assertEqual(len(result["durations"]), 5)
        self.assertTrue(all(pacing.MIN_SECONDS <= d <= pacing.MAX_SECONDS
                            for d in result["durations"]))
        self.assertAlmostEqual(result["total"], 20.0, delta=TOTAL_TOLERANCE)

    def test_empty_corrupt_inputs_raise_instead_of_returning_partial(self):
        cases = ([], None, "不是列表", 0, {"a": 1})
        for bad in cases:
            with self.subTest(bad=bad):
                with self.assertRaises(pacing.PacingError):
                    pacing.plan_durations(bad, 10.0)

    def test_invalid_target_raises(self):
        for bad in ("", None if False else "abc", float("nan"), float("inf"), -1):
            with self.subTest(bad=bad):
                with self.assertRaises((pacing.PacingError, ValueError)):
                    pacing.plan_durations(_shots(4), bad)


class CheckDurationsTests(unittest.TestCase):
    def test_check_catches_mismatch_and_bad_values(self):
        pacing.check_durations([2.0, 3.0], 2, 5.0, 5.0)
        with self.assertRaises(pacing.PacingError):
            pacing.check_durations([2.0], 2, 2.0, 5.0)
        with self.assertRaises(pacing.PacingError):
            pacing.check_durations([2.0, None], 2, 2.0, 2.0)
        with self.assertRaises(pacing.PacingError):
            pacing.check_durations([True, 2.0], 2, 3.0, 3.0)
        with self.assertRaises(pacing.PacingError):
            pacing.check_durations([0.5, 4.5], 2, 5.0, 5.0)
        with self.assertRaises(pacing.PacingError):
            pacing.check_durations([2.0, 2.0], 2, 4.0, 8.0)


class DuplicateIdTests(unittest.TestCase):
    def test_duplicate_shot_ids_are_made_unique(self):
        from modules import story_schema as ss
        shots = [ss.StoryboardShot.from_dict({"shot_id": x, "image_prompt": "a"} if x is None
                                             else {"shot_id": x, "image_prompt": "a"})
                 for x in ("s001", None, None, "s001", "s003")]
        ss.allocate_shot_ids(shots)
        ids = [s.shot_id for s in shots]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "s001")
        self.assertEqual(ids[4], "s003")
        self.assertEqual(ids[1:3], ["s002", "s004"])
