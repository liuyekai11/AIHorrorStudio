"""StoryEngine 测试：解析容错、请求构造、错误分类。全部使用假 transport，不联网。

运行：python -m unittest discover -s tests -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import call_log  # noqa: E402
from modules import story_engine as se  # noqa: E402
from modules import story_schema as ss  # noqa: E402
from modules.story_engine import StoryEngine, StoryError, StageError, parse_story  # noqa: E402

GOOD_STORY = {
    "title": "雨夜纸人",
    "logline": "一场葬礼后，纸人开始替死人说话。",
    "shots": [
        {"index": 1, "scene": "雨夜的灵堂，纸人立在棺旁", "narration": "那晚，纸人一直在看着我。",
         "duration": 3.5},
        {"index": 2, "scene": "特写：纸人的眼睛被雨水打湿", "narration": "我没有给它画眼睛。",
         "duration": "4"},
        {"index": 3, "scene": "走廊尽头，纸人站在门口", "narration": "它比昨天更近了。",
         "duration": 2.6},
    ],
}

# ----------------------------------------------------------------------
# V2.2 五阶段假响应：创意 → 策划 → 剧本 → 分镜 → 出图提示词 → 审核
# ----------------------------------------------------------------------
V22_CONCEPT = {
    "concepts": [{
        "title": "纸人替身", "logline": "守灵的姐姐发现纸人在替她做事",
        "core_conflict": "阿芸想守住弟弟的灵 vs 纸人想换走她的位置",
        "reversal_type": "identity", "horror_device": "纸人替身",
        "hook": "灵堂里，纸人的头转向了阿芸",
        "ending_type": "open", "duration_tier": "short", "score_hint": "民俗+身份反转",
    }],
}
V22_PLAN = {
    "title": "纸人替身", "logline": "守灵的姐姐发现纸人在替她做事",
    "plan": {
        "theme": "中式民俗恐怖", "background": "南方老宅，头七夜",
        "core_conflict": "阿芸想守住弟弟的灵 vs 纸人想换走她的位置",
        "motivation": "为了查明弟弟的死因", "stakes": "全家都会被替换",
        "conflicts": [{"description": "阿芸 vs 纸人", "parties": ["阿芸", "纸人"], "escalates_at": 3}],
        "foreshadows": [{"setup": "第 2 镜纸人没有影子", "payoff": "第 7 镜镜子里的自己没有影子",
                         "setup_shot": "2", "payoff_shot": "7"}],
        "reversal": "阿芸自己就是纸人", "reversal_type": "identity",
        "hook": "灵堂里，纸人的头转向了阿芸",
        "ending": "天亮后灵堂空了，只剩两个纸人", "ending_type": "open",
        "acts": [{"act": "hook", "start": 1, "end": 2, "summary": ""},
                 {"act": "setup", "start": 3, "end": 4, "summary": ""},
                 {"act": "escalation", "start": 5, "end": 6, "summary": ""},
                 {"act": "reversal", "start": 7, "end": 7, "summary": ""},
                 {"act": "aftertaste", "start": 8, "end": 8, "summary": ""}],
    },
    "characters": [{"character_id": "ch_阿芸", "name": "阿芸", "role": "主角",
                    "look": "23 岁女性，齐肩黑直发，苍白皮肤，褪色蓝布衫",
                    "motivation": "为了查明弟弟的死因"}],
    "scenes": [{"scene_id": "sc_灵堂", "name": "灵堂",
                "look": "老宅堂屋，白蜡烛，青砖地",
                "lighting": "冷青顶光", "props": ["棺材", "纸人"]}],
}
V22_SCRIPT = {
    "script": [
        {"segment_id": "seg001", "scene_id": "sc_灵堂", "character_ids": ["ch_阿芸"],
         "visual": "阿芸跪在棺前，烛光摇曳", "narration": "头七夜，不能关灯。",
         "dialogue": [], "emotion": "压抑", "duration_hint": 2.0, "act": "hook"},
        {"segment_id": "seg002", "scene_id": "sc_灵堂", "character_ids": [],
         "visual": "纸人的头转向阿芸，脚下没有影子", "narration": "",
         "dialogue": [], "emotion": "", "duration_hint": 1.5, "act": "hook"},
        {"segment_id": "seg003", "scene_id": "sc_灵堂", "character_ids": ["ch_阿芸"],
         "visual": "阿芸举起蜡烛查看纸人", "narration": "我没有给它画眼睛。",
         "dialogue": [], "emotion": "紧张", "duration_hint": 2.5, "act": "setup"},
        {"segment_id": "seg004", "scene_id": "sc_灵堂", "character_ids": ["ch_阿芸"],
         "visual": "镜子里，阿芸的位置站着纸人", "narration": "原来我一直站在这里。",
         "dialogue": [], "emotion": "恐惧", "duration_hint": 3.0, "act": "reversal"},
    ],
}
V22_SHOTS = {
    "shots": [
        {"shot_id": "s001", "script_segment_id": "seg001", "scene_id": "sc_灵堂",
         "character_ids": ["ch_阿芸"], "image_prompt": "灵堂里，阿芸跪在棺前，烛光摇曳",
         "motion": "static", "duration": 2.0, "voiced": True, "narration": "头七夜，不能关灯。",
         "transition": "cut", "act": "hook", "beat": "hook"},
        {"shot_id": "s002", "script_segment_id": "seg002", "scene_id": "sc_灵堂",
         "character_ids": [], "image_prompt": "特写：纸人的头转向阿芸，脚下没有影子",
         "motion": "push-in", "duration": 1.5, "voiced": False, "narration": "",
         "transition": "cut", "act": "hook", "beat": "hook"},
        {"shot_id": "s003", "script_segment_id": "seg003", "scene_id": "sc_灵堂",
         "character_ids": ["ch_阿芸"], "image_prompt": "阿芸举起蜡烛，凑近纸人看它的脸",
         "motion": "push-in", "duration": 2.5, "voiced": True, "narration": "我没有给它画眼睛。",
         "transition": "cut", "act": "setup", "beat": "setup"},
        {"shot_id": "s004", "script_segment_id": "seg004", "scene_id": "sc_灵堂",
         "character_ids": ["ch_阿芸"], "image_prompt": "镜子里阿芸的位置站着纸人，回望她",
         "motion": "diag-in", "duration": 3.0, "voiced": True, "narration": "原来我一直站在这里。",
         "transition": "flash", "act": "reversal", "beat": "reversal"},
    ],
}
V22_PROMPTS = {
    "prompts": [
        {"shot_id": "s001", "prompt": "dim funeral hall, woman kneeling before coffin, candlelight flicker"},
        {"shot_id": "s002", "prompt": "paper effigy head turned toward camera, no shadow on floor"},
        {"shot_id": "s003", "prompt": "woman raising candle close to paper effigy face"},
        {"shot_id": "s004", "prompt": "mirror reflection shows paper effigy instead of woman"},
    ],
}
V22_QUALITY = {
    "scores": {"story_completeness": 17, "logic": 16, "suspense": 12,
               "horror_atmosphere": 12, "characterization": 8, "reversal": 8,
               "dialogue_narration": 4, "shot_design": 4},
    "vetoes": [], "issues": [], "notes": "结构完整，钩子有效。",
}


def _scaled_script(base, n):
    """把 4 段样稿扩到 n 段（样稿循环使用），用于撑满目标时长而不触发续写。"""
    return {"script": [dict(base[i % len(base)], segment_id=f"seg{i+1:03d}") for i in range(n)]}


def _scaled_shots(base, n):
    return {"shots": [dict(base[i % len(base)], shot_id=f"s{i+1:03d}",
                           script_segment_id=f"seg{i+1:03d}") for i in range(n)]}


V22_STAGES = (          # 不可变：多个测试模块共享同一份预设，避免被 pop 串号
    json.dumps(V22_CONCEPT, ensure_ascii=False),
    json.dumps(V22_PLAN, ensure_ascii=False),
    json.dumps(_scaled_script(V22_SCRIPT["script"], 30), ensure_ascii=False),
    json.dumps(_scaled_shots(V22_SHOTS["shots"], 30), ensure_ascii=False),
    json.dumps({"prompts": [{"shot_id": f"s{i+1:03d}",
                             "prompt": f"dim funeral hall scene {i+1}, candlelight flicker"}
                            for i in range(30)]}, ensure_ascii=False),
    json.dumps(V22_QUALITY, ensure_ascii=False),
)


class SequencedTransport:
    """按顺序返回预设响应（每个阶段一次调用；多余调用抛错）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": headers, "payload": payload,
                           "timeout": timeout})
        if not self.responses:
            raise AssertionError("意外的额外调用")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            return _response(*item)
        return _response(item)


def _response(content: str, finish="stop") -> dict:
    return {"choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": content}}]}


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": headers, "payload": payload,
                           "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


def _engine(transport, api_key="sk-test-1234567890abcdef"):
    return StoryEngine(config={"api_key": api_key, "base_url": "https://api.deepseek.com",
                               "model": "deepseek-flash"}, transport=transport, timeout=5)


# ----------------------------------------------------------------------
class ParseTest(unittest.TestCase):
    def test_plain_json(self):
        story = parse_story(json.dumps(GOOD_STORY, ensure_ascii=False))
        self.assertEqual(story["title"], "雨夜纸人")
        self.assertEqual(len(story["shots"]), 3)
        self.assertEqual(story["shots"][1]["duration"], 4.0)
        self.assertAlmostEqual(story["total_duration"], 10.1)

    def test_markdown_fence(self):
        text = "```json\n" + json.dumps(GOOD_STORY, ensure_ascii=False) + "\n```"
        self.assertEqual(len(parse_story(text)["shots"]), 3)

    def test_leading_chatter(self):
        text = "好的，下面是脚本：\n" + json.dumps(GOOD_STORY, ensure_ascii=False) + "\n希望满意"
        self.assertEqual(parse_story(text)["title"], "雨夜纸人")

    def test_brace_inside_string(self):
        story = dict(GOOD_STORY)
        story["logline"] = "他说：“{别回头}”，然后消失了。"
        text = "前言 { 不完整 " + json.dumps(story, ensure_ascii=False)
        self.assertIn("别回头", parse_story(text)["logline"])

    def test_chinese_keys(self):
        data = {"标题": "午夜纸人", "分镜": [
            {"画面描述": "废弃医院走廊", "旁白": "灯灭了。", "时长": 3}]}
        story = parse_story(json.dumps(data, ensure_ascii=False))
        self.assertEqual(story["title"], "午夜纸人")
        self.assertEqual(story["shots"][0]["scene"], "废弃医院走廊")
        self.assertEqual(story["shots"][0]["duration"], 3.0)

    def test_missing_duration_estimated(self):
        data = {"title": "x", "shots": [{"scene": "a", "narration": "这是一句比较长的旁白文本内容"}]}
        shot = parse_story(json.dumps(data, ensure_ascii=False))["shots"][0]
        self.assertGreater(shot["duration"], se.DEFAULT_DURATION)
        self.assertLessEqual(shot["duration"], se.MAX_DURATION)

    def test_index_renumbered(self):
        data = {"title": "x", "shots": [
            {"index": 9, "scene": "a", "narration": "1"},
            {"index": 3, "scene": "b", "narration": "2"}]}
        shots = parse_story(json.dumps(data, ensure_ascii=False))["shots"]
        self.assertEqual([s["index"] for s in shots], [1, 2])

    def test_empty_shots_raises(self):
        with self.assertRaises(StoryError):
            parse_story('{"title":"x","shots":[]}')

    def test_garbage_raises(self):
        with self.assertRaises(StoryError):
            parse_story("对不起，我无法完成这个请求。")

    def test_truncated_json_raises(self):
        # 分镜列表断开：救不回来必须报错，不能把里面的半截对象当成整个结果
        with self.assertRaises(StoryError):
            parse_story('{"title":"x","shots":[{"scene":"a"')
        # 只有一个完整镜头、接着半截镜头的截断：救回完整的那一个
        salvaged = parse_story('{"title":"x","shots":[{"scene":"a"},{"scene":"b')
        self.assertEqual(len(salvaged["shots"]), 1)

    def test_scene_falls_back_to_narration(self):
        data = {"title": "x", "shots": [{"narration": "只有旁白"}]}
        shot = parse_story(json.dumps(data, ensure_ascii=False))["shots"][0]
        self.assertEqual(shot["scene"], "只有旁白")


# ----------------------------------------------------------------------
class EngineTest(unittest.TestCase):
    def test_request_shape(self):
        """V2.2：一步式 generate 走五阶段流水线，每次调用的请求形状都要正确。"""
        transport = SequencedTransport(V22_STAGES)
        # 30 镜是 standard 档的最小镜数：样本预设正好按 30 段剧本 / 分镜设计
        story = _engine(transport).generate("废弃医院、纸人", 30, "中式民俗恐怖", "结尾要反转")
        first = transport.calls[0]
        self.assertEqual(first["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(first["headers"]["Authorization"], "Bearer sk-test-1234567890abcdef")
        payload = first["payload"]
        self.assertEqual(payload["model"], "deepseek-v4-pro")     # concept 槽位
        prompt = payload["messages"][1]["content"]
        self.assertIn("json", prompt)                             # json_object 模式硬性要求
        self.assertIn("废弃医院、纸人", prompt)
        self.assertIn("结尾要反转", prompt)
        # 六次调用：创意(concept) → 策划(planner) → 剧本(writer) → 分镜(planner)
        #           → 出图提示词(fast) → 质量审核(planner)，全部 json 模式
        self.assertEqual([c["payload"]["model"] for c in transport.calls],
                         ["deepseek-v4-pro"] * 2 + ["deepseek-v4-pro"] +
                         ["deepseek-v4-pro"] + ["deepseek-flash"] + ["deepseek-v4-pro"])
        self.assertEqual(len(transport.calls), 6)
        for call in transport.calls:
            self.assertEqual(call["payload"]["response_format"], {"type": "json_object"})
            self.assertGreaterEqual(call["payload"]["max_tokens"], 2048)
            self.assertIn("json", call["payload"]["messages"][1]["content"])
        self.assertEqual(story["model"], "deepseek-v4-pro")

    def test_missing_key(self):
        transport = FakeTransport(_response("{}"))
        with self.assertRaises(StoryError):
            _engine(transport, api_key="").generate("医院")

    def test_empty_keywords(self):
        transport = FakeTransport(_response("{}"))
        with self.assertRaises(StoryError):
            _engine(transport).generate("   ")

    def test_empty_content_with_length(self):
        transport = FakeTransport(_response("", finish="length"))
        with self.assertRaises(StoryError) as ctx:
            _engine(transport).generate("医院")
        self.assertIn("截断", str(ctx.exception))

    def test_empty_content(self):
        transport = FakeTransport(_response("   "))
        with self.assertRaises(StoryError):
            _engine(transport).generate("医院")

    def test_bad_response_shape(self):
        transport = FakeTransport({"error": "oops"})
        with self.assertRaises(StoryError):
            _engine(transport).generate("医院")

    def test_transport_error_passthrough(self):
        transport = FakeTransport(error=StoryError("API Key 无效"))
        with self.assertRaises(StoryError) as ctx:
            _engine(transport).generate("医院")
        self.assertIn("Key", str(ctx.exception))

    def test_key_never_in_request_log_helpers(self):
        # 错误信息脱敏：真实 HTTP 错误里不应带出完整 key
        from modules import ai_config
        self.assertEqual(ai_config.mask_key("sk-1234567890abcdef"), "sk-123…cdef")
        self.assertNotIn("abcdef", ai_config.scrub("key=sk-1234567890abcdef",
                                                   "sk-1234567890abcdef"))


# ----------------------------------------------------------------------
class _TempLogMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmp.name) / "calls.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def engine(self, stages):
        transport = SequencedTransport(stages)
        engine = StoryEngine(config={"api_key": "sk-test-1234567890abcdef",
                                     "base_url": "https://api.deepseek.com"},
                             transport=transport, timeout=5, retries=2,
                             log_path=self.log_path)
        return engine, transport


class PipelineTest(_TempLogMixin, unittest.TestCase):
    """V2.2 五阶段流水线：阶段产物、重试、JSON 修复、调用日志。"""

    def test_pipeline_builds_complete_story(self):
        engine, transport = self.engine(V22_STAGES)
        concepts = engine.generate_concepts("废弃医院、纸人", "中式民俗恐怖", "结尾要反转")
        story = engine.pipeline(concepts[0], "废弃医院、纸人", "中式民俗恐怖",
                                "结尾要反转", shot_count=30)
        self.assertEqual(len(story["shots"]), 30)
        self.assertEqual(story["schema_version"], ss.SCHEMA_VERSION)
        self.assertGreaterEqual(len(transport.calls), 5)     # 策划→剧本→分镜→提示词→审核
        self.assertEqual(story["quality"]["vetoes"], [])
        self.assertTrue(story["quality"]["passed"])
        # 时长：误差 ≤ 1 秒，每镜在 1.5~6 秒
        self.assertLessEqual(abs(story["total_duration"]
                                 - story["pacing"]["target_seconds"]), 1.0)
        for shot in story["shots"]:
            self.assertGreaterEqual(shot["duration"], ss.MIN_SHOT_DURATION)
            self.assertLessEqual(shot["duration"], ss.MAX_SHOT_DURATION)
        # 每镜都有英文提示词、content_hash，段 id 连续
        for shot in story["shots"]:
            self.assertTrue(shot["image_prompt_en"])
            self.assertTrue(shot["content_hash"])
        self.assertEqual([s["shot_id"] for s in story["shots"]][:3],
                         ["s001", "s002", "s003"])

    def test_storyboard_corrects_unknown_references(self):
        bad = json.loads(V22_STAGES[3])
        bad["shots"][0]["character_ids"] = ["ch_不存在"]
        bad["shots"][0]["scene_id"] = "sc_不存在"
        engine, _ = self.engine((V22_STAGES[0], V22_STAGES[1], V22_STAGES[2],
                                 json.dumps(bad, ensure_ascii=False),
                                 V22_STAGES[4], V22_STAGES[5]))
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        script = engine.write_script(bundle)
        shots = engine.storyboard(bundle, script)
        # 按剧本段纠正：s001 对应 seg001，场景回到灵堂，人物回到阿芸
        self.assertEqual(shots[0]["scene_id"], "sc_灵堂")
        self.assertIn("ch_阿芸", shots[0]["character_ids"])
        char_ids = {c["character_id"] for c in bundle["characters"]}
        for shot in shots:
            self.assertIn(shot["scene_id"], {s["scene_id"] for s in bundle["scenes"]})
            self.assertTrue(set(shot["character_ids"]) <= char_ids)

    def test_segments_scaled_when_too_few(self):
        few = _scaled_script(V22_SCRIPT["script"], 10)
        more = _scaled_script(V22_SCRIPT["script"], 30)
        engine, transport = self.engine((V22_STAGES[0], V22_STAGES[1],
                                         json.dumps(few, ensure_ascii=False),
                                         json.dumps(more, ensure_ascii=False),
                                         V22_STAGES[3], V22_STAGES[4], V22_STAGES[5]))
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        script = engine.write_script(bundle)
        self.assertEqual(len(script), 40)                     # 10 段 + 续写 30 段
        self.assertEqual([s["segment_id"] for s in script][:2], ["seg001", "seg002"])
        self.assertEqual(script[0]["scene_id"], "sc_灵堂")

    def test_script_accepts_chinese_scene_names(self):
        txt = _scaled_script(V22_SCRIPT["script"], 30)
        for seg in txt["script"]:
            seg["scene_id"] = "灵堂"                          # 模型写成中文名
            seg["character_ids"] = ["阿芸"]
        engine, _ = self.engine((V22_STAGES[0], V22_STAGES[1],
                                 json.dumps(txt, ensure_ascii=False),
                                 V22_STAGES[3], V22_STAGES[4], V22_STAGES[5]))
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        script = engine.write_script(bundle)
        self.assertEqual(len(script), 30)
        self.assertEqual(script[0]["scene_id"], "sc_灵堂")
        self.assertEqual(script[0]["character_ids"], ["ch_阿芸"])

    def test_truncated_output_is_retried(self):
        engine, transport = self.engine((("", "length"), V22_STAGES[0]))
        concepts = engine.generate_concepts("废弃医院、纸人")
        self.assertEqual(len(concepts), 1)
        self.assertEqual(len(transport.calls), 2)
        rows = [json.loads(line) for line in self.log_path.read_text("utf-8").splitlines()]
        self.assertFalse(rows[0]["ok"])
        self.assertIn("截断", rows[0]["error"])
        self.assertTrue(rows[1]["ok"])

    def test_truncated_twice_gives_stage_error(self):
        engine, _ = self.engine((("", "length"), ("", "length"), ("", "length")))
        with self.assertRaises(StageError) as ctx:
            engine.generate_concepts("废弃医院、纸人")
        self.assertEqual(ctx.exception.stage, "创意候选")

    def test_json_repair_uses_fast_slot(self):
        engine, transport = self.engine(("{这不是 json", V22_STAGES[0]))
        concepts = engine.generate_concepts("废弃医院、纸人")
        self.assertEqual(len(concepts), 1)
        models = [c["payload"]["model"] for c in transport.calls]
        self.assertEqual(models, ["deepseek-v4-pro", "deepseek-flash"])
        self.assertIn("json修复", json.dumps(
            [r.get("stage") for r in call_log.read_recent(10, self.log_path)],
            ensure_ascii=False))

    def test_call_log_never_contains_key_or_prompt(self):
        engine, transport = self.engine(V22_STAGES)
        concepts = engine.generate_concepts("废弃医院、纸人")
        engine.pipeline(concepts[0], "废弃医院、纸人", shot_count=30)
        text = self.log_path.read_text("utf-8")
        self.assertNotIn("sk-test-1234567890abcdef", text)
        self.assertNotIn("废弃医院", text)                    # 只记字数，不记提示词正文
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(len(rows), len(transport.calls))     # 每次调用恰好一条日志
        for row in rows:
            self.assertIn("prompt_chars", row)
            self.assertGreater(row["prompt_chars"], 0)
            self.assertIn("model", row)
            self.assertNotIn("sk-", json.dumps(row, ensure_ascii=False))

    def test_concepts_dedupe_reversal_types(self):
        base = json.loads(V22_STAGES[0])["concepts"][0]
        dup = json.loads(V22_STAGES[0])
        first = dict(base)
        first["title"] = "另一个纸人故事"
        dup["concepts"] = [base, first]
        engine, _ = self.engine((json.dumps(dup, ensure_ascii=False),))
        concepts = engine.generate_concepts("废弃医院、纸人", count=3)
        # 同反转类型排在后面的先放一边；没有别的可选时再补回
        self.assertEqual(len(concepts), 2)
        self.assertEqual(concepts[0]["title"], "纸人替身")

    def test_concepts_prefer_distinct_reversal(self):
        base = json.loads(V22_STAGES[0])["concepts"][0]
        other = dict(base, title="走廊尽头的纸人", reversal_type="time_loop")
        dup = {"concepts": [base, dict(base, title="重复一"), other]}
        engine, _ = self.engine((json.dumps(dup, ensure_ascii=False),))
        concepts = engine.generate_concepts("废弃医院、纸人", count=2)
        self.assertEqual([c["title"] for c in concepts], ["纸人替身", "走廊尽头的纸人"])

    def test_concepts_fill_tier_and_ruleset(self):
        engine, _ = self.engine((V22_STAGES[0],))
        concepts = engine.generate_concepts("废弃医院、纸人", duration_tier="long")
        self.assertEqual(concepts[0]["duration_tier"], "long")
        self.assertEqual(concepts[0]["ruleset"], "folk")

    def test_image_prompt_replacement_keeps_chinese(self):
        engine, _ = self.engine(V22_STAGES)
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        script = engine.write_script(bundle)
        shots = engine.storyboard(bundle, script)
        cn = [s["image_prompt"] for s in shots]
        engine.image_prompts(shots, "中式民俗恐怖")
        self.assertEqual([s["image_prompt_cn"] for s in shots], cn)
        self.assertTrue(shots[0]["image_prompt_en"].startswith("dim funeral hall"))
        self.assertEqual(shots[0]["image_prompt"], shots[0]["image_prompt_en"])

    def test_review_merges_local_and_model(self):
        engine, _ = self.engine(V22_STAGES)
        concepts = engine.generate_concepts("废弃医院、纸人")
        story = engine.pipeline(concepts[0], "废弃医院、纸人", shot_count=30)
        report = ss.QualityReport(**ss.normalize_quality(story["quality"]))
        self.assertEqual(report.score, 81.0)
        self.assertEqual(report.grade, "pass")
        self.assertIn("本地", report.notes)

    def test_pipeline_notifies_each_stage(self):
        events = []
        engine, _ = self.engine(V22_STAGES)
        engine.on_stage = lambda stage, text: events.append(stage)
        concepts = engine.generate_concepts("废弃医院、纸人")
        engine.pipeline(concepts[0], "废弃医院、纸人", shot_count=30)
        for stage in ("故事策划", "完整剧本", "导演分镜", "时长规划", "出图提示词", "质量审核"):
            self.assertIn(stage, events)

    def test_beats_follow_plan_acts(self):
        engine, _ = self.engine(V22_STAGES)
        concepts = engine.generate_concepts("废弃医院、纸人")
        story = engine.pipeline(concepts[0], "废弃医院、纸人", shot_count=30)
        acts = story["plan"]["acts"]
        first_act = acts[0]["act"]
        last_act = acts[-1]["act"]
        self.assertEqual(story["shots"][0]["act"], first_act)
        self.assertEqual(story["shots"][-1]["act"], last_act)
        order = ["hook", "setup", "escalation", "reversal", "aftertaste"]
        idx = [order.index(s["act"]) for s in story["shots"]]
        self.assertEqual(idx, sorted(idx))                    # 单调不减

    def test_fit_acts_covers_every_shot(self):
        for total in (1, 2, 3, 5, 8, 12, 30, 50):
            acts = se._fit_acts([], total)
            self.assertEqual(acts[0]["start"], 1)
            self.assertEqual(acts[-1]["end"], total)
            for prev, nxt in zip(acts, acts[1:]):
                self.assertEqual(nxt["start"], prev["end"] + 1)


# ----------------------------------------------------------------------
class ConvertTest(unittest.TestCase):
    def setUp(self):
        self.story = parse_story(json.dumps(GOOD_STORY, ensure_ascii=False))

    def test_to_project_shots(self):
        shots = se.to_project_shots(self.story)
        self.assertEqual(len(shots), 3)
        self.assertIsNone(shots[0]["image"])
        self.assertEqual(shots[0]["scene"], GOOD_STORY["shots"][0]["scene"])
        self.assertEqual(shots[0]["narration"], GOOD_STORY["shots"][0]["narration"])

    def test_to_srt_timing(self):
        srt = se.to_srt(self.story)
        self.assertIn("00:00:00,000 --> 00:00:03,500", srt)
        self.assertIn("00:00:03,500 --> 00:00:07,500", srt)
        self.assertIn("那晚，纸人一直在看着我。", srt)
        self.assertTrue(srt.strip().startswith("1\n"))

    def test_clamp_shot_count(self):
        self.assertEqual(se.clamp_shot_count(1), se.MIN_SHOTS)
        self.assertEqual(se.clamp_shot_count(999), se.MAX_SHOTS)
        self.assertEqual(se.clamp_shot_count("6"), 6)


# ----------------------------------------------------------------------
class V21FieldsTest(unittest.TestCase):
    """V2.1：角色卡 / 场景卡、运镜、留白镜、时长钳制。"""

    def test_motion_and_voiced_parsed(self):
        data = {"title": "x", "shots": [
            {"scene": "a", "narration": "一", "duration": 2, "motion": "pan-left", "voiced": True},
            {"scene": "b", "narration": "", "duration": 1.5, "motion": "diag-in", "voiced": False},
        ]}
        shots = parse_story(json.dumps(data, ensure_ascii=False))["shots"]
        self.assertEqual(shots[0]["motion"], "pan-left")
        self.assertTrue(shots[0]["voiced"])
        self.assertEqual(shots[1]["motion"], "diag-in")
        self.assertFalse(shots[1]["voiced"])

    def test_unknown_motion_defaults_static(self):
        data = {"title": "x", "shots": [{"scene": "a", "narration": "一", "motion": "推近"}]}
        self.assertEqual(parse_story(json.dumps(data, ensure_ascii=False))["shots"][0]["motion"],
                         "static")

    def test_voiced_false_clears_narration(self):
        """voiced=false 但模型仍写了旁白：以 voiced 为准，清空旁白（留白镜）。"""
        data = {"title": "x", "shots": [
            {"scene": "a", "narration": "不该出现", "voiced": False},
            {"scene": "b", "narration": "二"},
        ]}
        shots = parse_story(json.dumps(data, ensure_ascii=False))["shots"]
        self.assertEqual(shots[0]["narration"], "")
        self.assertFalse(shots[0]["voiced"])
        # 没写 voiced 时按有无旁白推断
        self.assertTrue(shots[1]["voiced"])

    def test_duration_clamped_to_picture_range(self):
        data = {"title": "x", "shots": [
            {"scene": "a", "narration": "一", "duration": 9},
            {"scene": "b", "narration": "二", "duration": 0.2},
        ]}
        shots = parse_story(json.dumps(data, ensure_ascii=False))["shots"]
        self.assertEqual(shots[0]["duration"], se.MAX_DURATION)
        self.assertEqual(shots[1]["duration"], se.MIN_DURATION)

    def test_characters_and_scenes_cards(self):
        data = {
            "title": "x",
            "characters": {"阿芸": "23 岁女性，齐肩黑发", "老陈": "60 岁，驼背，穿灰棉袄"},
            "scenes": [{"name": "灵堂", "look": "白蜡烛，青砖地"}],
            "shots": [{"scene": "a", "narration": "一"}],
        }
        story = parse_story(json.dumps(data, ensure_ascii=False))
        names = [c["name"] for c in story["characters"]]
        self.assertEqual(names, ["阿芸", "老陈"])
        self.assertEqual(story["scenes"][0]["look"], "白蜡烛，青砖地")

    def test_scenes_cards_not_mistaken_for_shots(self):
        """顶层 scenes（场景卡）不能当分镜列表用。"""
        data = {"title": "x", "scenes": [{"name": "灵堂", "look": "蜡烛"}],
                "shots": [{"scene": "a"}, {"scene": "b"}]}
        story = parse_story(json.dumps(data, ensure_ascii=False))
        self.assertEqual(len(story["shots"]), 2)
        self.assertEqual(len(story["scenes"]), 1)

    def test_consistency_hint_mentions_character(self):
        story = {
            "characters": [{"name": "阿芸", "look": "齐肩黑发"},
                           {"name": "老陈", "look": "灰棉袄"}],
            "scenes": [{"name": "灵堂", "look": "白蜡烛"}],
        }
        hint = se.build_consistency_hint(story, "老陈 站在灵堂门口")
        self.assertIn("阿芸", hint)
        self.assertIn("白蜡烛", hint)
        # 画面里点名的角色排在前面
        self.assertLess(hint.index("老陈"), hint.index("阿芸"))
        self.assertEqual(se.build_consistency_hint(None), "")

    def test_to_project_shots_passes_motion_and_voiced(self):
        story = parse_story(json.dumps({"title": "x", "shots": [
            {"scene": "a", "narration": "", "motion": "pull-out", "voiced": False},
        ]}, ensure_ascii=False))
        shot = se.to_project_shots(story)[0]
        self.assertEqual(shot["motion"], "pull-out")
        self.assertFalse(shot["voiced"])
        self.assertEqual(shot["zoom"], "out")   # 旧字段兼容
        self.assertIsNone(shot["transition"])   # 交给 replace_all_shots 推导

    def test_prompt_has_structure_requirements(self):
        system, user = se.build_prompt("废纸人、灵堂", 8)
        self.assertIn("钩子", system)
        self.assertIn("characters", user)
        self.assertIn("motion", user)
        self.assertIn("voiced", user)
        self.assertIn(f"{se.MAX_NARRATION_CHARS}", user)

    def test_infer_style(self):
        self.assertEqual(se.infer_style("纸人、灵堂", ""), "folk")
        self.assertEqual(se.infer_style("", "都市怪谈"), "urban")
        self.assertEqual(se.infer_style("地铁站", ""), "urban")
        self.assertEqual(se.infer_style("完全不同", ""), "default")


# ----------------------------------------------------------------------
class TruncationTest(_TempLogMixin, unittest.TestCase):
    """实测退步（2026-11-04 真实 API）：推理 token 用尽预算时 finish_reason=length
    但 content 非空，旧逻辑会把半截 JSON 交给修复 / 直接解析。"""

    def test_nonempty_length_output_is_retried(self):
        cut = '{"shots": [{"shot_id": "s001", "image_prompt": "灵堂'
        engine, transport = self.engine(((cut, "length"), V22_STAGES[0]))
        concepts = engine.generate_concepts("废弃医院")
        self.assertEqual(len(concepts), 1)
        self.assertEqual(len(transport.calls), 2)

    def test_length_on_storyboard_is_not_parsed(self):
        cut = json.dumps(V22_STAGES[3], ensure_ascii=False)[:200]
        engine, transport = self.engine((V22_STAGES[0], V22_STAGES[1], V22_STAGES[2],
                                         (cut, "length"), V22_STAGES[3],
                                         V22_STAGES[4], V22_STAGES[5]))
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        script = engine.write_script(bundle)
        shots = engine.storyboard(bundle, script)      # 第 2 次调用完整，应成功
        self.assertEqual(len(shots), 30)

    def test_storyboard_requests_enough_budget(self):
        engine, transport = self.engine(V22_STAGES)
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        script = engine.write_script(bundle)
        engine.storyboard(bundle, script)
        storyboard_call = transport.calls[3]
        self.assertGreaterEqual(storyboard_call["payload"]["max_tokens"], se.SHOT_BUDGET[30])
        self.assertGreaterEqual(storyboard_call["payload"]["max_tokens"], 32768)

    def test_salvage_truncated_storyboard(self):
        full = V22_STAGES[3]                           # 已经是一段 JSON 文本
        idx = full.rfind("s030")
        cut = full[:idx] + 's030", "image_'          # 断在第 30 镜的字段中间
        salvaged = se._salvage_truncated_list(cut)
        self.assertIsNotNone(salvaged)
        self.assertTrue(salvaged.endswith('"}]}'))
        data = json.loads(salvaged)                    # 救回来的 JSON 必须能解析
        self.assertEqual(len(data["shots"]), 29)
        self.assertEqual(data["shots"][-1]["shot_id"], "s029")
        # 端到端：截断输出能直接走通分镜阶段，不用整段重试
        # 截断分镜就地救回 29 镜（不额外调用修复），下一个响应直接给审核
        engine, transport = self.engine((V22_STAGES[0], V22_STAGES[1], V22_STAGES[2],
                                         cut, V22_STAGES[5]))
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        script = engine.write_script(bundle)
        shots = engine.storyboard(bundle, script)
        self.assertEqual(len(shots), 29)
        self.assertEqual(shots[0]["shot_id"], "s001")
        self.assertEqual(len(transport.calls), 4)      # 没有额外重试

    def test_salvage_rejects_complete_list(self):
        self.assertIsNone(se._salvage_truncated_list(V22_STAGES[3]))
        self.assertIsNone(se._salvage_truncated_list("不是 json"))
        self.assertIsNone(se._salvage_truncated_list('{"shots": ['))

    def test_image_prompts_requests_budget_by_shot_count(self):
        # 出图提示词走 fast 槽位也是推理模型：36 镜实测 4096 被吃光，预算必须随镜数抬
        engine, transport = self.engine(V22_STAGES)
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        script = engine.write_script(bundle)
        shots = engine.storyboard(bundle, script)
        engine.image_prompts(shots, "中式民俗恐怖")
        prompt_call = transport.calls[4]
        self.assertEqual(prompt_call["payload"]["max_tokens"],
                         max(se.PROMPT_BUDGET_FLOOR,
                             se.PROMPT_TOKENS_PER_SHOT * len(shots) + 2048))
        self.assertGreater(prompt_call["payload"]["max_tokens"], 4096)
        self.assertGreaterEqual(se.PROMPT_BUDGET_CEIL,
                                se.PROMPT_TOKENS_PER_SHOT * 80 + 2048)  # 长档 80 镜不被封顶


if __name__ == "__main__":
    unittest.main()


class PacingBindingTest(_TempLogMixin, unittest.TestCase):
    """时长分配必须覆盖最终镜头列表的每一个镜头（用户 2026-11-05 报告）。"""

    def _plan(self, engine):
        concepts = engine.generate_concepts("废弃医院、纸人")
        bundle = engine.plan_story(concepts[0], "废弃医院、纸人", shot_count=30)
        return engine.write_script(bundle), bundle

    def test_every_shot_gets_own_duration(self):
        for n in (1, 8, 10, 20):
            with self.subTest(n=n):
                engine, _ = self.engine(V22_STAGES)
                shots = [{"shot_id": f"s{i:03d}", "beat": "setup",
                          "narration": "雨" * (i % 12)} for i in range(1, n + 1)]
                target = n * 3.0
                result = engine.plan_pacing(shots, target)
                self.assertEqual(result["kept_count"], n)
                self.assertEqual(len({s["duration"] for s in shots}),
                                 1 if n == 1 else len({s.get("narration") for s in shots}))
                for shot in shots:
                    self.assertGreaterEqual(shot["duration"], ss.MIN_SHOT_DURATION)
                    self.assertLessEqual(shot["duration"], ss.MAX_SHOT_DURATION)
                self.assertLessEqual(abs(sum(s["duration"] for s in shots) - target), 1.0)

    def test_trimmed_storyboard_keeps_durations_aligned(self):
        # 分镜比目标时长多：plan_pacing 截断后，留下来的镜头各自拿到时长，不多不少
        engine, _ = self.engine(V22_STAGES)
        shots = [{"shot_id": f"s{i:03d}", "beat": "setup", "narration": "雨" * (i % 9)}
                 for i in range(1, 51)]
        result = engine.plan_pacing(shots, 40.0, allow_resize=True)
        self.assertTrue(result["resized"])
        kept = result["kept_count"]
        self.assertLess(kept, 50)
        self.assertTrue(all(shots[i]["duration"] for i in range(kept)))
        for i in range(kept, 50):
            self.assertNotIn("duration", shots[i])
        self.assertEqual(result["trimmed_index"], list(range(kept, 50)))

    def test_mismatch_raises_with_diagnostic_log(self):
        engine, _ = self.engine(V22_STAGES)
        shots = [{"shot_id": "s001", "beat": "setup", "narration": "雨"}]
        original = se.pacing.plan_durations

        def broken(*args, **kwargs):          # 模拟底层返回错位的时长
            return {"durations": [2.0, 3.5], "kept_shot_ids": ["s001", "s002"],
                    "shot_count": 2, "trimmed_index": None, "error": 0.5,
                    "message": "", "weights": {}}

        se.pacing.plan_durations = broken
        try:
            with self.assertRaises(StageError) as ctx:
                engine.plan_pacing(shots, 5.5)
        finally:
            se.pacing.plan_durations = original
        message = str(ctx.exception)
        self.assertIn("时长分配结果与镜头数量不一致", message)
        self.assertIn("2", message)
        records = ([json.loads(line) for line in
                    self.log_path.read_text(encoding="utf-8").splitlines()]
                   if self.log_path.exists() else [])
        diag = [r for r in records if r.get("stage") == "时长规划"]
        self.assertEqual(len(diag), 1)
        for key in ("target_seconds", "shot_count", "duration_count", "durations", "shot_ids"):
            self.assertIn(key, diag[0])
        self.assertEqual(diag[0]["duration_count"], 2)
        self.assertEqual(diag[0]["target_seconds"], 5.5)

    def test_pipeline_durations_cover_all_shots(self):
        engine, _ = self.engine(V22_STAGES)
        concepts = engine.generate_concepts("废弃医院、纸人", "中式民俗恐怖", "结尾要反转")
        story = engine.pipeline(concepts[0], "废弃医院、纸人", "中式民俗恐怖",
                                "结尾要反转", shot_count=30)
        durations = [s.get("duration") for s in story["shots"]]
        self.assertTrue(all(isinstance(d, (int, float)) and d > 0 for d in durations))
        self.assertEqual(len(durations), len(story["shots"]))
        self.assertLessEqual(abs(sum(durations) - story["pacing"]["target_seconds"]), 1.0)
        self.assertEqual(story["pacing"]["kept_count"], len(story["shots"]))
