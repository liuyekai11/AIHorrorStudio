"""恐怖题材规则库测试（纯逻辑，不联网）。

对应用户 2026-11-04 批准的修正 2、3、4：
  * 钩子看「前 3 秒」有没有悬念 / 异常 / 危险 / 强视觉，不要求第一镜是高潮画面
  * 结局允许完整 / 开放 / 系列悬念，但要能识别明确的叙事收束
  * 人物可跨场景出现（规则库不为场景生成限制）
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import horror_rules as hr  # noqa: E402


class RulesetTests(unittest.TestCase):
    def test_all_six_genres_exist(self):
        self.assertEqual(len(hr.RULE_KEYS), 6)
        self.assertEqual({r["key"] for r in hr.all_rulesets()}, set(hr.RULE_KEYS))

    def test_each_ruleset_has_full_fields(self):
        for rule in hr.all_rulesets():
            with self.subTest(rule=rule["key"]):
                for key in ("label", "must", "must_not", "horror_devices",
                            "narration", "dialogue", "ending", "voice_style", "structure"):
                    self.assertTrue(rule.get(key), f"{rule['key']} 缺少 {key}")
                self.assertTrue(rule["must"] and rule["must_not"])

    def test_detect_folk(self):
        self.assertEqual(hr.detect_ruleset("废弃医院、纸人、雨夜"), "folk")

    def test_detect_psych(self):
        self.assertEqual(hr.detect_ruleset("镜子里的另一个自己"), "psych")

    def test_detect_loop(self):
        self.assertEqual(hr.detect_ruleset("每次醒来都回到同一天的循环里"), "loop")
        # 「凌晨三点的电梯」只命中一个场景词，按都市怪谈处理（题材由用户/策划可改）
        self.assertEqual(hr.detect_ruleset("凌晨三点的电梯"), "urban")

    def test_unknown_falls_back_to_default(self):
        self.assertEqual(hr.detect_ruleset("天气不错"), hr.DEFAULT_RULESET)
        self.assertEqual(hr.get_ruleset("nope")["key"], hr.DEFAULT_RULESET)

    def test_prompt_contains_genre_and_rules(self):
        rule = hr.get_ruleset("psych")
        prompt = hr.ruleset_prompt(rule)
        self.assertIn(rule["label"], prompt)
        self.assertIn(rule["must"][0], prompt)
        self.assertIn(rule["must_not"][0], prompt)


class HookTests(unittest.TestCase):
    """修正 2：第一镜不要求高潮画面，前 3 秒有悬念 / 异常 / 危险 / 强视觉即可。"""

    def test_quiet_establishing_shot_can_still_hook(self):
        # 不是高潮画面，但有强视觉（特写 / 一只手 / 影子 / 回头）
        self.assertTrue(hr.has_hook("走廊尽头，一个穿寿衣的人站在原地"))
        self.assertTrue(hr.has_hook("他回头看了一眼"))
        self.assertTrue(hr.has_hook("门缝里透出一只手"))
        self.assertTrue(hr.has_hook("特写：熄灭的蜡烛"))

    def test_plain_description_without_device_is_not_a_hook(self):
        # 纯环境交代、无异常无危险无强视觉 → 交给模型 rubric 判弱钩子
        self.assertFalse(hr.has_hook("废弃医院的走廊，雨夜"))

    def test_danger_and_anomaly(self):
        self.assertTrue(hr.has_hook("血从天花板滴下来"))
        self.assertTrue(hr.has_hook("电梯的楼层又多了一个 13"))

    def test_question_is_a_hook(self):
        self.assertTrue(hr.has_hook("谁在敲墙"))
        self.assertTrue(hr.has_hook("为什么只有我一个人听见"))
        self.assertTrue(hr.has_hook("为什么？"))

    def test_flat_text_is_not_a_hook(self):
        self.assertFalse(hr.has_hook(""))
        self.assertFalse(hr.has_hook("   "))
        self.assertFalse(hr.has_hook("很平静的一天"))

    def test_whitespace_does_not_break_matching(self):
        self.assertTrue(hr.has_hook("他突然\n停住了"))


class MotivationTests(unittest.TestCase):
    def test_motivation_words(self):
        self.assertTrue(hr.has_motivation("她必须在天亮前找到妹妹"))
        self.assertTrue(hr.has_motivation("为了查明父亲的死因"))

    def test_missing_motivation(self):
        self.assertFalse(hr.has_motivation("她走进医院"))
        self.assertFalse(hr.has_motivation(""))


class ClosureTests(unittest.TestCase):
    """修正 3：完整 / 开放 / 系列悬念都接受，但必须能识别叙事收束。"""

    def test_closed_ending(self):
        self.assertTrue(hr.has_closure("最后，灯灭了，纸人安静下来。", "closed"))

    def test_open_ending(self):
        self.assertTrue(hr.has_closure("天亮以后，雨还在下，她再也没有走出那扇门。", "open"))

    def test_series_ending_accepts_next_time_hook(self):
        self.assertTrue(hr.has_closure("电梯门再次打开，里面站着下一个她。", "series"))
        # 没有收束词但系列提示词命中也算收束（不是意外中断）
        self.assertTrue(hr.has_closure("下一次，轮到谁了？", "series"))

    def test_interrupted_text_is_abrupt(self):
        self.assertFalse(hr.has_closure("她伸手去推门", "closed"))
        self.assertFalse(hr.has_closure("", "closed"))
        # 系列悬念只在 series 结局下接受「下一次」类收束
        self.assertFalse(hr.has_closure("下一次轮到你了", "closed"))


class CrossSceneTests(unittest.TestCase):
    """修正 4：规则库不能把角色限制在一个场景里。"""

    def test_ruleset_does_not_lock_characters_to_one_scene(self):
        joined = "".join("".join(ruleset["must"]) + "".join(ruleset["must_not"])
                         for ruleset in hr.all_rulesets())
        for phrase in ("只能出现在一个场景", "不能跨场景", "固定在一个场景"):
            self.assertNotIn(phrase, joined)


class CountWordsTests(unittest.TestCase):
    def test_order_preserved_and_deduped(self):
        hits = hr.count_words("血和影子", hr.DANGER_WORDS + hr.STRONG_VISUAL_WORDS)
        self.assertIn("血", hits)
        self.assertIn("影子", hits)
        self.assertLess(hits.index("血"), hits.index("影子"))


if __name__ == "__main__":
    unittest.main()
