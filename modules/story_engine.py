"""故事引擎（V2.2）：五阶段流水线，调用 DeepSeek 生成完整的恐怖短剧。

阶段
----
0 创意候选  `generate_concepts`   题材 + 规则库 → 3 个反转类型互不重复的创意
1 故事策划  `plan_story`          选定创意 → StoryPlan + 人物卡 + 场景卡
2 剧本撰写  `write_script`        策划 → ScriptSegment[]（旁白 / 对白 / 情绪）
3 导演拆镜  `storyboard`          剧本 → StoryboardShot[]（画面 / 运镜 / 时长）
4 出图提示词 `image_prompts`     分镜 → 精简英文画面提示词
5 质量审核  `review`             本地确定性检查 + 模型 rubric 打分 → QualityReport

`pipeline()` 串起 1~5 阶段，`generate()` 保留 V2.1 的一步式入口（内部走同一条流水线）。

设计约束
--------
* 只用标准库；网络层可注入 `transport`，单测用假 transport，不消耗额度。
* 模型槽位 / max_tokens / temperature 全部走 `model_config`，不写死。
* 两个 DeepSeek 模型都是推理模型，推理 token 计入 max_tokens；
  预算不足会返回「空内容 + finish_reason=length」，按可重试错误处理。
* `response_format=json_object` 要求提示词里出现 "json"，解析失败时用
  「JSON 修复」槽位（fast）兜底，再失败才抛出。
* 每次调用写 `call_log`（stage / 模型 / 耗时 / token），不写 Key 与 prompt 正文。
"""
import json
import re
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime

from modules import ai_config
from modules import call_log
from modules import horror_rules
from modules import model_config
from modules import pacing
from modules import story_quality
from modules import story_schema as ss

# ----------------------------------------------------------------------
# 兼容 V2.1 的常量（story_panel 等界面仍会 import）
# ----------------------------------------------------------------------
DEFAULT_TIMEOUT = 120
MIN_SHOTS = 6
MAX_SHOTS = 60
MIN_DURATION = ss.MIN_SHOT_DURATION       # 1.5
MAX_DURATION = ss.MAX_SHOT_DURATION       # 6.0
DEFAULT_DURATION = 2.5
MAX_NARRATION_CHARS = 15
MOTION_MODES = ss.MOTION_MODES
MAX_REPAIRS = 1
DEFAULT_DURATION_TIER = "standard"
DURATION_TIERS = {
    "short": (60.0, 180.0, "1~3 分钟"),
    "standard": (180.0, 300.0, "3~5 分钟"),
    "long": (300.0, 600.0, "5~10 分钟"),
}
# 目标时长档 → [最少镜数, 最多镜数]（由 1.5~6 秒单镜时长推出，再留一点余量）
SHOT_RANGE_BY_TIER = {"short": (14, 32), "standard": (30, 50), "long": (40, 80)}
# 导演分镜的预算（按该档最少镜头数取）：实测推理 token 占掉一半以上，
# 30 镜左右要 ~16k 才能完整输出（2026-11-04 实测 16384 在 36 镜档被截断）
SHOT_BUDGET = {14: 24576, 30: 32768, 40: 49152}
# 出图提示词走 fast 槽位（deepseek-flash 也是推理模型）：实测 36 镜时 4096 被推理
# token 吃光（finish_reason=length，产出 6098 字 JSON），按「输出量 ≈ 130 token/镜
# + 推理 2048」估预算，并设下限与上限。
PROMPT_TOKENS_PER_SHOT = 130
PROMPT_BUDGET_FLOOR = 8192
PROMPT_BUDGET_CEIL = 32768
# 固定质量测试题材（tests/fixtures/quality_topics.json 同步维护）
GOLDEN_TOPICS = ("废弃医院、纸人、雨夜", "凌晨三点的电梯", "镜子里的另一个自己")


class StoryError(Exception):
    """故事生成失败。message 可直接展示给用户。"""


class StageError(StoryError):
    """某个阶段失败（带阶段名，便于界面显示与重试）。"""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class ContentTruncated(StoryError):
    """max_tokens 不足导致空内容 + finish_reason=length（可重试）。"""


class ContentEmpty(StoryError):
    """模型返回空白内容（安全策略拦截等）。"""


class JSONParseError(StoryError):
    """内容不是合法 JSON（可交给 fast 槽位修复）。"""


# ----------------------------------------------------------------------
# 提示词
# ----------------------------------------------------------------------
SYSTEM_PROMPT = (
    "你是一位资深的恐怖短剧编剧兼导演，擅长用极少的文字制造压迫感与不祥的预感，"
    "并把故事拆成能在竖屏短视频里『快切』的镜头带。"
    "你熟悉中式民俗、心理恐怖、都市怪谈、密室、反转悬疑、无限循环六类恐怖题材的写法，"
    "知道每类题材该用什么样的规矩、物件与反转。"
    "角色与场景要写成可复用的『卡片』，保证不同镜头里的同一个人长得一样。"
    "故事一定按『钩子 → 建置 → 升级 → 反转 → 余味』五段组织。"
    "只输出 json，不要输出任何解释、前言或 markdown 代码块。"
)

_CONCEPT_EXAMPLE = """{
  "concepts": [
    {
      "title": "纸人替身（12 字以内）",
      "logline": "一句话概括：谁，在什么处境下，遭遇什么",
      "core_conflict": "主角想要什么 vs 什么在阻止他（必须具体到人物与规则）",
      "reversal_type": "identity / time / space / motivation / perception / none 选一个",
      "horror_device": "贯穿全片的核心恐怖装置（纸人 / 镜子 / 电梯 / 遗留物 …）",
      "hook": "前 3 秒出现的悬念 / 异常 / 危险 / 强视觉画面，一句话",
      "ending_type": "closed（完整结局）/ open（开放式）/ series（系列悬念）选一个",
      "duration_tier": "short / standard / long",
      "score_hint": "一句话说明这个创意的亮点"
    }
  ]
}"""

_PLAN_EXAMPLE = """{
  "title": "标题（12 字以内）",
  "logline": "一句话概括",
  "plan": {
    "theme": "题材",
    "background": "背景：时间、地点、社会处境",
    "core_conflict": "核心冲突",
    "motivation": "主角动机：他为什么非做这件事不可（硬性要求）",
    "stakes": "失败会失去什么",
    "conflicts": [{"description": "冲突描述", "parties": ["谁", "谁"], "escalates_at": 3}],
    "foreshadows": [{"setup": "第几镜埋伏笔、埋什么", "payoff": "第几镜怎么回收",
                     "setup_shot": "2", "payoff_shot": "9"}],
    "reversal": "反转内容",
    "reversal_type": "identity / time / space / motivation / perception / none",
    "hook": "前 3 秒的悬念画面",
    "ending": "结局怎么收",
    "ending_type": "closed / open / series",
    "acts": [{"act": "hook", "start": 1, "end": 3, "summary": "钩子段做什么"},
             {"act": "setup", "start": 4, "end": 12, "summary": "…"},
             {"act": "escalation", "start": 13, "end": 28, "summary": "…"},
             {"act": "reversal", "start": 29, "end": 36, "summary": "…"},
             {"act": "aftertaste", "start": 37, "end": 40, "summary": "…"}],
    "tone": "基调"
  },
  "characters": [
    {"character_id": "ch_阿芸", "name": "阿芸", "role": "主角",
     "look": "23 岁女性，齐肩黑直发，苍白皮肤，褪色蓝布衫，左手腕旧疤（出图固定卡）",
     "motivation": "她想要什么、为什么", "secret": "她不知道 / 不敢说的秘密",
     "voice": "说话方式", "scene_ids": ["sc_灵堂"]}
  ],
  "scenes": [
    {"scene_id": "sc_灵堂", "name": "灵堂", "look": "老宅堂屋，白蜡烛，青砖地，潮湿墙面（出图固定卡）",
     "lighting": "冷青顶光", "props": ["棺材", "纸人", "香炉"]}
  ]
}"""

_SCRIPT_EXAMPLE = """{
  "script": [
    {
      "segment_id": "seg001",
      "scene_id": "sc_灵堂",
      "character_ids": ["ch_阿芸"],
      "visual": "阿芸跪在棺前点香，纸人立在左侧阴影里",
      "narration": "旁白（不超过 15 字，可为空）",
      "dialogue": [{"character_id": "ch_阿芸", "text": "台词", "emotion": "颤抖"}],
      "emotion": "压抑",
      "duration_hint": 3.0,
      "act": "hook / setup / escalation / reversal / aftertaste"
    }
  ]
}"""

_STORYBOARD_EXAMPLE = """{
  "shots": [
    {
      "shot_id": "s001",
      "script_segment_id": "seg001",
      "scene_id": "sc_灵堂",
      "character_ids": ["ch_阿芸"],
      "image_prompt": "画面描述：主体、构图、光线方向、色调、材质、恐怖元素（给文生图用）",
      "motion": "static / push-in / pull-out / pan-left / pan-right / diag-in",
      "duration": 2.5,
      "voiced": true,
      "narration": "旁白（voiced=false 时必须为空字符串）",
      "transition": "cut / fade / dissolve / flash",
      "act": "hook",
      "beat": "hook / setup / escalation / reversal / aftertaste",
      "weight": 1.2
    }
  ]
}"""

_IMAGE_PROMPT_EXAMPLE = """{
  "prompts": [
    {"shot_id": "s001", "prompt": "concise English visual description, subject + composition + lighting + mood, no style words"},
    {"shot_id": "s002", "prompt": "..."}
  ]
}"""

_QUALITY_EXAMPLE = """{
  "scores": {
    "story_completeness": 0, "logic": 0, "suspense": 0, "horror_atmosphere": 0,
    "characterization": 0, "reversal": 0, "dialogue_narration": 0, "shot_design": 0
  },
  "vetoes": [{"code": "weak_hook / abrupt_end / missing_motivation / unknown_reference / duration_mismatch / unforeshadowed_reversal",
              "message": "为什么否决", "shot_id": "s003"}],
  "issues": [{"stage": "plan / script / storyboard", "shot_id": "s003", "severity": "info / warning / error",
              "message": "问题", "suggestion": "怎么改"}],
  "notes": "总评（100 字以内）"
}"""


def _json_line() -> str:
    # response_format=json_object 要求提示词里出现 "json" 字样，否则 HTTP 400
    return "只输出一个合法的 json 对象，不要 markdown 代码块、不要解释。"


def planning_shot_count(shot_count=None) -> int:
    """策划阶段要求的镜头规模：按最终数量往下取最近的一档（策划是预估，分镜阶段再精确）。"""
    try:
        n = int(shot_count or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return SHOT_RANGE_BY_TIER[DEFAULT_DURATION_TIER][0]
    for low, _high in sorted(SHOT_RANGE_BY_TIER.values()):
        if n <= low + 2:
            return low
    return max(low for low, _ in SHOT_RANGE_BY_TIER.values())


def _planning_cap(shot_count=None) -> int:
    """策划允许的上限：下一档的最少镜数（策划是预估，分镜阶段再精确）。"""
    count = planning_shot_count(shot_count)
    for low, _high in sorted(SHOT_RANGE_BY_TIER.values()):
        if low > count:
            return low
    return SHOT_RANGE_BY_TIER["long"][1]


def _shot_plan_text(shot_count: int) -> str:
    count = planning_shot_count(shot_count)
    return (f"先按约 {count} 个镜头规划五段结构（上限约 {_planning_cap(shot_count)} 镜）；"
            "完整分镜数量在拆镜阶段按目标总时长决定。")


def build_prompt(keywords: str, shot_count: int, style: str = "",
                 extra: str = "") -> tuple[str, str]:
    """兼容 V2.1 的两段式提示词（内部走流水线的策划阶段）。"""
    keywords = (keywords or "").strip()
    if not keywords:
        raise StoryError("请先输入题材关键词，例如：废弃医院、纸人、雨夜。")
    shot_count = clamp_shot_count(shot_count)
    rule = horror_rules.get_ruleset(horror_rules.detect_ruleset(keywords, style))
    extra_line = f"额外要求：{extra.strip()}。" if (extra or "").strip() else ""
    user = f"""请根据下面的题材写一份恐怖短剧的策划（包含人物卡、场景卡），不要写分镜。

题材关键词：{keywords}
{horror_rules.ruleset_prompt(rule)}
镜头规划：{_shot_plan_text(shot_count)}
{extra_line}

要求：
1. 先定「钩子 → 建置 → 升级 → 反转 → 余味」五段结构，写进 plan.acts。
2. 主角必须有明确动机（plan.motivation 与角色卡的 motivation 都要写），否则视为不合格。
3. 反转必须有伏笔（plan.foreshadows 至少 2 条，写明在第几镜埋、第几镜回收）。
4. 人物卡 / 场景卡的 look 是出图固定描述：长相、服装、光线、色调、材质，不写情绪与剧情。
5. 人物可以跨多个场景出现，不要把人锁死在一个场景里。
6. 结局可以是完整 / 开放式 / 系列悬念，但必须写清楚怎么收（plan.ending）。
7. 先写 concepts（3 个可选创意），再选一个写成 plan。
8. 镜头节奏：运镜 motion（static / push-in / pull-out / pan-left / pan-right / diag-in）、
   voiced（该镜是否有旁白，留白镜为 false）在拆镜阶段填写，这里只需知道它们的含义。
9. 旁白每镜不超过 {MAX_NARRATION_CHARS} 个字。

{_json_line()}

参考结构（字段名必须一致，数值只是示例）：
{_CONCEPT_EXAMPLE}
{_PLAN_EXAMPLE}"""
    return SYSTEM_PROMPT, user


# ----------------------------------------------------------------------
# 网络
# ----------------------------------------------------------------------
def _http_transport(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = (data.get("error") or {}).get("message") or ""
        except Exception:
            pass
        raise StoryError(_friendly_http_error(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
            raise StoryError(f"请求超时（{timeout} 秒）。故事较长时可以调大超时重试。") from exc
        raise StoryError(f"无法连接 DeepSeek（{reason}）。请检查网络或代理设置。") from exc
    except socket.timeout as exc:
        raise StoryError(f"请求超时（{timeout} 秒）。请重试。") from exc
    except json.JSONDecodeError as exc:
        raise StoryError("服务器返回的不是有效 JSON，请稍后重试。") from exc


def _friendly_http_error(code: int, detail: str) -> str:
    detail = ai_config.scrub(detail or "")
    table = {
        400: "请求参数有误",
        401: "API Key 无效或已失效，请在「设置」中重新填写",
        402: "账户余额不足，请到 platform.deepseek.com 充值",
        422: "请求参数有误",
        429: "请求过于频繁或额度用尽，请稍后再试",
        500: "DeepSeek 服务异常，请稍后重试",
        503: "DeepSeek 服务繁忙，请稍后重试",
    }
    head = table.get(code, f"请求失败（HTTP {code}）")
    return f"{head}。{detail}".strip()


# ----------------------------------------------------------------------
# 引擎
# ----------------------------------------------------------------------
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class StoryEngine:
    def __init__(self, config: dict | None = None, transport=None,
                 timeout=DEFAULT_TIMEOUT, retries: int = 2, log_path=None,
                 on_stage=None):
        self.config = config or ai_config.load_config()
        self.transport = transport or _http_transport
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.log_path = log_path
        self.on_stage = on_stage          # callable(stage, text) 进度回报

    # ---- 配置 ----
    @property
    def api_key(self) -> str:
        return (self.config.get("api_key") or "").strip()

    @property
    def model(self) -> str:
        """V2.1 兼容：默认槽位模型。"""
        return model_config.model_for(model_config.LEGACY_SLOT, self.config)

    @property
    def base_url(self) -> str:
        return (self.config.get("base_url") or ai_config.DEFAULT_BASE_URL).rstrip("/")

    def model_for(self, slot: str) -> str:
        return model_config.model_for(slot, self.config)

    def _notify(self, stage: str, text: str):
        if callable(self.on_stage):
            try:
                self.on_stage(stage, text)
            except Exception:
                pass

    # ---- 单次调用 ----
    def _call(self, slot: str, stage: str, system: str, user: str,
              min_tokens: int = 0) -> str:
        """调用指定槽位，返回文本内容。截断 / 空内容自动重试。

        min_tokens：本阶段至少要的预算（长输出阶段用）。实测推理 token 会吃掉
        max_tokens 的 60%+，所以预算取 max(槽位默认, min_tokens)，避免分镜被截断。
        """
        if not self.api_key:
            raise StoryError("还没有配置 DeepSeek API Key。请点「AI 设置」填写，"
                             "或设置环境变量 DEEPSEEK_API_KEY。")
        params = dict(model_config.params_for(slot, self.config))
        if min_tokens:
            params["max_tokens"] = max(int(min_tokens), int(params.get("max_tokens") or 0))
        model = self.model_for(slot)
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": params.get("temperature", 1.0),
            "max_tokens": int(params.get("max_tokens", 8192)),
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        timeout = int(params.get("timeout", self.timeout) or self.timeout)
        last_error = None
        for attempt in range(1, self.retries + 2):
            started = time.monotonic()
            finish = ""
            usage = {}
            try:
                raw = self.transport(f"{self.base_url}/chat/completions",
                                     headers, payload, timeout)
                try:
                    choice = raw["choices"][0]
                    finish = choice.get("finish_reason") or ""
                except (KeyError, IndexError, TypeError):
                    choice = None
                usage = raw.get("usage") if isinstance(raw, dict) else None
                content = extract_content(raw)
            except ContentTruncated as exc:
                last_error = exc
                self._log(stage, slot, model, params, user, started, finish,
                          usage, False, str(exc), attempt)
                self._notify(stage, f"{stage}：输出被截断，重试（{attempt}/{self.retries + 1}）……")
                continue
            except StoryError as exc:
                self._log(stage, slot, model, params, user, started, finish,
                          usage, False, str(exc), attempt)
                # 401/402/超时之外也能重试一次网络类错误
                if attempt <= self.retries and isinstance(exc, (ContentEmpty,)):
                    last_error = exc
                    continue
                raise
            self._log(stage, slot, model, params, user, started, finish,
                      usage, True, "", attempt)
            return content
        assert last_error is not None
        raise StageError(stage, str(last_error)) from last_error

    def _log(self, stage, slot, model, params, user, started, finish, usage,
             ok, error, attempt):
        call_log.record({
            "stage": stage,
            "slot": slot,
            "model": model,
            "prompt_chars": len(user or ""),
            "max_tokens": params.get("max_tokens"),
            "temperature": params.get("temperature"),
            "elapsed_s": round(time.monotonic() - started, 2),
            "finish_reason": finish,
            "usage": usage if isinstance(usage, dict) else {},
            "ok": ok,
            "error": (error or "")[:300],
            "attempt": attempt,
        }, self.log_path)

    def _call_json(self, slot: str, stage: str, system: str, user: str,
                   hint: str = "", min_tokens: int = 0,
                   repair_head_tail: bool = False) -> dict:
        """调用并解析 JSON；解析失败时交给 fast 槽位修复一次。

        repair_head_tail：长列表输出（分镜）被截断时，把「有头无尾」的 JSON
        截到最后一个完整对象后交给 fast 槽位补一个 ] 收尾——能救回大部分镜头，
        比整阶段重试省时间也省钱。
        """
        content = self._call(slot, stage, system, user, min_tokens=min_tokens)
        try:
            return parse_json_object(content)
        except StoryError as exc:
            if repair_head_tail:
                salvaged = _salvage_truncated_list(content)
                if salvaged is not None:
                    # 截到最后一个完整对象再补 ]}，本身就是合法 JSON：直接解析，
                    # 省掉一次修复调用（只有仍不合法时才交给 fast 槽位）
                    try:
                        fixed = parse_json_object(salvaged)
                    except StoryError:
                        fixed = None
                    if fixed is None:
                        fixed = self._repair_json(salvaged, hint)
                    if fixed is not None:
                        return fixed
            fixed = self._repair_json(content, hint)
            if fixed is not None:
                return fixed
            raise StageError(stage, f"{stage} 返回的 json 无法解析：{exc}") from exc

    def _repair_json(self, content: str, hint: str) -> dict | None:
        if MAX_REPAIRS <= 0:
            return None
        repair_user = (
            "下面是一段本应是 json 的模型输出，请修复成合法、完整的 json 对象，"
            "保持原有字段与内容，不要增删信息。\n\n"
            + (f"期望结构提示：{hint}\n\n" if hint else "")
            + "原始输出：\n" + (content or "")[:12000]
        )
        try:
            fixed = self._call("fast", "json修复", SYSTEM_PROMPT, repair_user)
            return parse_json_object(fixed)
        except StoryError:
            return None

    # ---- 阶段 0：创意候选 ----
    def generate_concepts(self, keywords: str, style: str = "", extra: str = "",
                          duration_tier: str = DEFAULT_DURATION_TIER,
                          count: int = 3) -> list[dict]:
        keywords = (keywords or "").strip()
        if not keywords:
            raise StoryError("请先输入题材关键词，例如：废弃医院、纸人、雨夜。")
        tier = duration_tier if duration_tier in DURATION_TIERS else DEFAULT_DURATION_TIER
        rule = horror_rules.get_ruleset(horror_rules.detect_ruleset(keywords, style))
        extra_line = f"额外要求：{extra.strip()}。" if (extra or "").strip() else ""
        user = f"""请为下面的题材构思 {count} 个互不相同的恐怖短剧创意，每个创意用不同的核心冲突与反转方式。

题材关键词：{keywords}
{extra_line}
{horror_rules.ruleset_prompt(rule)}
目标时长档：{tier}（{DURATION_TIERS[tier][2]}）。

要求：
1. 正好 {count} 个创意；每个创意的 core_conflict 与 reversal_type 必须互不相同。
2. 每个创意都要写 hook：前 3 秒出现的悬念 / 异常 / 危险 / 强视觉画面（不要求是高潮）。
3. ending_type 可选 closed（完整结局）/ open（开放式）/ series（系列悬念），三种都可以。
4. 创意要能撑满目标时长，有足够的事件密度，不要一句话就讲完。
5. 题材规则必须遵守（见上方的必须 / 禁止项）。

{_json_line()}

参考结构（字段名必须一致）：
{_CONCEPT_EXAMPLE}"""
        data = self._call_json("concept", "创意候选", SYSTEM_PROMPT, user, _CONCEPT_EXAMPLE)
        raw = data.get("concepts") if isinstance(data, dict) else None
        if not isinstance(raw, list) or not raw:
            raw = data.get("ideas") or data.get("ideas_list") or []
        concepts = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                concept = ss.StoryConcept.from_dict(item).validate()
            except ss.SchemaError:
                continue
            if not concept.ruleset:
                concept.ruleset = rule["key"]
            if not concept.duration_tier or concept.duration_tier != tier:
                concept.duration_tier = tier
            concepts.append(concept.to_dict())
        concepts = _dedupe_concepts(concepts, count)
        if not concepts:
            raise StageError("创意候选", "模型没有给出合格创意（缺核心冲突或钩子）。请重试。")
        return concepts

    # ---- 阶段 1：故事策划 ----
    def plan_story(self, concept: dict, keywords: str = "", style: str = "",
                   extra: str = "", shot_count: int | None = None,
                   duration_tier: str | None = None) -> dict:
        self._notify("故事策划", "正在写故事策划……")
        concept = concept if isinstance(concept, dict) else {}
        if not concept:
            raise StoryError("请先选择一个创意再写策划。")
        tier = duration_tier or concept.get("duration_tier") or DEFAULT_DURATION_TIER
        if tier not in DURATION_TIERS:
            tier = DEFAULT_DURATION_TIER
        count = int(shot_count or SHOT_RANGE_BY_TIER[tier][0])
        extra_line = f"额外要求：{extra.strip()}。" if (extra or "").strip() else ""
        rule = horror_rules.get_ruleset(concept.get("ruleset")
                                        or horror_rules.detect_ruleset(keywords, style))
        concept_text = json.dumps(concept, ensure_ascii=False, indent=2)
        user = f"""请把下面的创意扩写成完整的故事策划（story plan）与人物卡、场景卡。这一阶段不要写分镜。

题材关键词：{keywords or concept.get("title", "")}
创意（用户已选定）：
{concept_text}

{horror_rules.ruleset_prompt(rule)}
镜头规划：{_shot_plan_text(count)}（最终目标时长档：{tier}，{DURATION_TIERS[tier][2]}）
{extra_line}

要求：
1. plan.acts 必须覆盖「钩子 → 建置 → 升级 → 反转 → 余味」五段，start/end 是镜头序号（1 起）。
2. plan.motivation 与每个主要角色的 motivation 都要写清楚「为了什么」。
3. plan.foreshadows 至少 2 条，写明第几镜埋、第几镜回收；反转必须由伏笔支撑。
4. 人物可以跨多个场景出现（character.scene_ids 只是提示）；不要把人锁死在一个场景里。
5. 人物卡 look / 场景卡 look 是出图固定描述：外貌、服装、光线方向、色调、材质，不写情绪与剧情。
6. ending_type 按选定创意处理，plan.ending 写清楚怎么收（完整 / 开放 / 系列悬念都可以）。
7. 保留创意里的标题与核心冲突，把它写得更具体。

{_json_line()}

参考结构（字段名必须一致，数值只是示例）：
{_PLAN_EXAMPLE}"""
        data = self._call_json("planner", "故事策划", SYSTEM_PROMPT, user, _PLAN_EXAMPLE)
        if not isinstance(data, dict):
            raise StageError("故事策划", "策划返回结构不正确。请重试。")
        return self._assemble_plan(data, concept, keywords, style, tier, count, rule)

    def _assemble_plan(self, data, concept, keywords, style, tier, count, rule) -> dict:
        try:
            concepts = [ss.StoryConcept.from_dict(c).validate().to_dict()
                        for c in (data.get("concepts") or []) if isinstance(c, dict)]
        except ss.SchemaError:
            concepts = []
        chosen = ss.StoryConcept.from_dict(concept).to_dict()
        for item in concepts:
            if item.get("title") == chosen.get("title"):
                chosen = item
                break
        if not concepts:
            concepts = [chosen]

        chars = ss.normalize_characters(data.get("characters")
                                        or data.get("roles") or [])
        scenes = ss.normalize_scenes(data.get("scenes")
                                     or data.get("locations") or [])
        char_ids = [c["character_id"] for c in chars]
        scene_ids = [s["scene_id"] for s in scenes]
        plan = ss.normalize_plan(_pick_plan(data), chars, scenes)
        if not plan.get("core_conflict"):
            plan["core_conflict"] = chosen.get("core_conflict", "")
        if not plan.get("hook"):
            plan["hook"] = chosen.get("hook", "")
        if not plan.get("ending_type"):
            plan["ending_type"] = chosen.get("ending_type", "closed")
        if plan.get("ending_type") not in ss.ENDINGS:
            plan["ending_type"] = chosen.get("ending_type", "closed") \
                if chosen.get("ending_type") in ss.ENDINGS else "closed"
        if not plan.get("title"):
            plan["title"] = chosen.get("title", "")
        if not plan.get("logline"):
            plan["logline"] = chosen.get("logline", "")
        if not plan.get("ruleset"):
            plan["ruleset"] = rule["key"]
        if not plan.get("motivation"):
            plan["motivation"] = next((c.get("motivation") for c in chars
                                       if c.get("motivation")), "")
        if plan.get("reversal_type") in (None, ""):
            plan["reversal_type"] = chosen.get("reversal_type", "none")
        plan["foreshadows"] = [f for f in plan.get("foreshadows") or [] if isinstance(f, dict)]
        plan["conflicts"] = [c for c in plan.get("conflicts") or [] if isinstance(c, dict)]
        plan["acts"] = [a for a in plan.get("acts") or [] if isinstance(a, dict)]
        # 策划给的镜头规模是预估：夹在「本档最少」与「下一档最少」之间，越界就重排 acts
        target_shots = max([int(a.get("end") or 0) for a in plan["acts"]] or [0]) or count
        floor = planning_shot_count(count)
        cap = max(floor, _planning_cap(count))
        target_shots = max(floor, min(cap, target_shots))
        plan["acts"] = _fit_acts(plan["acts"], target_shots)
        title = plan.get("title") or chosen.get("title") or "未命名故事"
        return {
            "title": str(title)[:40],
            "logline": str(plan.get("logline") or chosen.get("logline") or "")[:200],
            "keywords": keywords or "",
            "style": style or "",
            "ruleset": rule["key"],
            "duration_tier": tier,
            "duration_range": list(DURATION_TIERS[tier][:2]),
            "shot_target": target_shots,
            "concepts": concepts,
            "concept_id": chosen.get("concept_id", ""),
            "plan": plan,
            "characters": chars,
            "scenes": scenes,
            "landscape": {"character_ids": char_ids, "scene_ids": scene_ids},
        }

    # ---- 阶段 2：剧本 ----
    def write_script(self, plan_bundle: dict, extra: str = "") -> list[dict]:
        if not isinstance(plan_bundle, dict) or not plan_bundle.get("plan"):
            raise StoryError("请先完成故事策划再写剧本。")
        self._notify("完整剧本", "正在写完整剧本……")
        plan = plan_bundle["plan"]
        chars = plan_bundle.get("characters") or []
        scenes = plan_bundle.get("scenes") or []
        target = plan_bundle.get("shot_target") or \
            SHOT_RANGE_BY_TIER.get(plan_bundle.get("duration_tier")
                                   or DEFAULT_DURATION_TIER, (30, 50))[0]
        primary = [c for c in chars if c.get("role") in ("主角", "反派")] or chars
        extra_line = f"额外要求：{extra.strip()}。" if (extra or "").strip() else ""
        user = f"""请根据下面的策划写完整剧本（ScriptSegment 列表，按时间顺序）。

故事：{plan_bundle.get("title", "")} —— {plan_bundle.get("logline", "")}
策划：
{json.dumps(plan, ensure_ascii=False, indent=2)}

人物卡（character_id / name）：
{json.dumps([{k: c.get(k) for k in ('character_id', 'name', 'role', 'motivation', 'voice')}
            for c in primary], ensure_ascii=False, indent=2)}

场景卡（scene_id / name）：
{json.dumps([{k: s.get(k) for k in ('scene_id', 'name', 'lighting')}
            for s in scenes], ensure_ascii=False, indent=2)}
{extra_line}

要求：
1. 旁白 + 对白推进故事，覆盖完整因果链：动机 → 行动 → 阻碍 → 升级 → 反转 → 收束。
2. 一段剧本对应约 1.5~6 秒画面，按节奏写 {max(6, int(round(target)))} 段左右。
3. segment_id 从 seg001 连续编号；scene_id / character_ids 必须只使用上面卡片里出现过的 id。
4. 旁白每段不超过 15 字；约四分之一段落只写画面（narration 为空字符串），让环境音说话。
5. 伏笔段（plan.foreshadows 的 setup）必须在对应位置出现，不能省略。
6. 结尾必须收束（完整 / 开放 / 系列悬念都行），不能突然停下。
7. 人物可以跨多个场景出现；需要换场时写新的 scene_id。

{_json_line()}

参考结构（字段名必须一致）：
{_SCRIPT_EXAMPLE}"""
        data = self._call_json("writer", "完整剧本", SYSTEM_PROMPT, user, _SCRIPT_EXAMPLE)
        raw = data.get("script") if isinstance(data, dict) else None
        if not isinstance(raw, list) or not raw:
            raw = data.get("segments") if isinstance(data, dict) else None
        prepared = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            if not item.get("scene_id") and scenes:
                item["scene_id"] = _nearest_scene(item.get("visual") or item.get("narration") or "",
                                                  scenes)
            prepared.append(item)
        segments = ss.normalize_script(prepared, _ref_ids(scenes, "scene_id", "name"),
                                       _ref_ids(chars, "character_id", "name"))
        if not segments:
            raise StageError("完整剧本", "模型没有给出合格剧本段。请重试。")
        # 剧本段数直接决定分镜数：按目标时长校验，不够就继续写（最多补 2 轮）
        target_seconds = _target_seconds(plan_bundle.get("duration_tier")
                                         or DEFAULT_DURATION_TIER)
        # 镜头目标由策划给定；剧本段不够时按镜头数补，而不是按档中点硬补
        target_seconds = min(target_seconds,
                             SEGMENT_AVG_SECONDS * int(plan_bundle.get("shot_target")
                                                       or 0))
        for attempt in range(2):
            need = _needed_segments(target_seconds, len(segments))
            if need <= 0:
                break
            self._notify("完整剧本", f"剧本段只有 {len(segments)} 段，撑不满 "
                                     f"{target_seconds:.0f} 秒，正在补写到约 {need} 段……")
            prepared = self._extend_script(segments, need, plan_bundle, extra, attempt)
            if not prepared:
                break
            segments = prepared
        for i, seg in enumerate(segments, 1):
            seg["segment_id"] = f"seg{i:03d}"
        return segments

    def _extend_script(self, segments: list[dict], need: int, plan_bundle: dict,
                       extra: str, attempt: int) -> list[dict]:
        """续写剧本：保留已有段落，只写剩余部分（避免整篇重写导致前后矛盾）。"""
        plan = plan_bundle.get("plan") or {}
        chars = plan_bundle.get("characters") or []
        scenes = plan_bundle.get("scenes") or []
        tail = segments[-3:]
        user_tail = "\n".join(f"{s.get('segment_id')}｜{s.get('scene_id')}｜"
                              f"{s.get('narration') or '（留白）'}｜{s.get('visual')}"
                              for s in tail)
        extra_line = f"额外要求：{extra.strip()}。" if (extra or "").strip() else ""
        user = f"""下面的剧本已写了前面 {len(segments)} 段，但按目标时长 {_target_seconds(
            plan_bundle.get('duration_tier') or DEFAULT_DURATION_TIER):.0f} 秒还需要约
{need - len(segments)} 段。请只写续接的 {max(1, need - len(segments))} 段，不要重复已有内容。

故事：{plan_bundle.get('title', '')} —— {plan_bundle.get('logline', '')}
结局方向：{plan.get('ending', '')}（{plan.get('ending_type', 'closed')}）
已写的最后几段：
{user_tail}
{extra_line}
要求：续写直接接上最后一段，推进到反转与收束；每段 1.5~6 秒，旁白不超过 15 字；
约四分之一段落只写画面（narration 为空字符串）。scene_id / character_ids 只使用：
场景 {[s.get('scene_id') for s in scenes]}；人物 {[c.get('character_id') for c in chars]}。

{_json_line()}

参考结构（字段名必须一致）：
{_SCRIPT_EXAMPLE}"""
        try:
            data = self._call_json("writer", "完整剧本", SYSTEM_PROMPT, user, _SCRIPT_EXAMPLE)
        except StageError:
            return []
        raw = (data.get("script") or data.get("segments")) if isinstance(data, dict) else None
        prepared = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["segment_id"] = f"seg{len(segments) + len(prepared) + 1:03d}"
            prepared.append(item)
        more = ss.normalize_script(prepared, _ref_ids(scenes, "scene_id", "name"),
                                   _ref_ids(chars, "character_id", "name"))
        if not more:
            return []
        return segments + more

    # ---- 阶段 3：分镜 ----
    def storyboard(self, plan_bundle: dict, script: list[dict],
                   ok_api=None) -> list[dict]:
        if not script:
            raise StoryError("请先完成剧本再拆镜。")
        self._notify("导演分镜", "正在拆导演分镜……")
        plan = (plan_bundle or {}).get("plan") or {}
        chars = (plan_bundle or {}).get("characters") or []
        scenes = (plan_bundle or {}).get("scenes") or []
        tier = (plan_bundle or {}).get("duration_tier") or DEFAULT_DURATION_TIER
        target_seconds = _target_seconds(tier)
        lo, hi = SHOT_RANGE_BY_TIER.get(tier, SHOT_RANGE_BY_TIER[DEFAULT_DURATION_TIER])
        user = f"""请把下面的完整剧本拆成竖屏恐怖短剧分镜（StoryboardShot 列表）。

故事：{plan.get('title') or (plan_bundle or {}).get('title', '')}
目标总时长：约 {target_seconds:.0f} 秒，分镜数 {lo}~{hi} 个，每镜 {MIN_DURATION}~{MAX_DURATION} 秒。

剧本：
{json.dumps(script, ensure_ascii=False, indent=2)}

人物卡 id：{[c.get('character_id') for c in chars]}
场景卡 id：{[s.get('scene_id') for s in scenes]}

要求：
1. 每个镜头一个画面（对应一张 AI 图）。一个剧本段可以拆成多个镜头，多个短段也可合并。
2. 每个镜头必须写 script_segment_id（来自剧本）、scene_id、character_ids（只写画面里实际出现的人）。
3. shot_id 从 s001 连续编号。
4. image_prompt 必须可直接交给文生图：主体、动作、构图、光线方向、色调、材质、恐怖元素；
   不要带画风词（画风由出图阶段统一附加）。
5. motion 必须与画面内容方向一致（门在左就 pan-left）。
6. duration 先给节奏建议值（{MIN_DURATION}~{MAX_DURATION} 秒，惊吓 / 反转镜 1.5~2 秒）；
   最终时长由系统按目标总时长统一分配，你给的只是节奏倾向。
7. beat 按节奏档标注：hook / setup / escalation / reversal / aftertaste。
8. voiced=false 的镜头 narration 必须为空字符串；约四分之一镜头留白。
9. 第 1 镜不要求是最强画面，但前 3 秒内（首镜及紧随的镜头）必须出现悬念 / 异常 / 危险 / 强视觉。
10. 结尾按策划的 ending 收束，最后一镜要有明确的收束画面或旁白。

{_json_line()}

参考结构（字段名必须一致）：
{_STORYBOARD_EXAMPLE}"""
        data = self._call_json("planner", "导演分镜", SYSTEM_PROMPT, user, _STORYBOARD_EXAMPLE,
                               min_tokens=SHOT_BUDGET.get(lo, 32768),
                               repair_head_tail=True)
        raw = data.get("shots") if isinstance(data, dict) else None
        if not isinstance(raw, list) or not raw:
            raise StageError("导演分镜", "模型没有给出分镜。请重试。")
        scene_ids = [s.get("scene_id") for s in scenes]
        char_ids = [c.get("character_id") for c in chars]
        seg_ids = [s.get("segment_id") for s in script]
        seg_scene = {s.get("segment_id"): s.get("scene_id") for s in script}
        seg_chars = {s.get("segment_id"): list(s.get("character_ids") or []) for s in script}
        cleaned = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            # 引用了卡片之外的人 / 场景：优先按剧本段纠正，纠正不了就清空（不伪造）
            seg_id = item.get("script_segment_id") or ""
            if not item.get("scene_id") and seg_id in seg_scene:
                item["scene_id"] = seg_scene[seg_id]
            if item.get("scene_id") and item["scene_id"] not in scene_ids:
                item["scene_id"] = seg_scene.get(seg_id, "")
            ids = [c for c in (item.get("character_ids") or []) if c in char_ids]
            if not ids and seg_id in seg_chars:
                ids = [c for c in seg_chars[seg_id] if c in char_ids]
            item["character_ids"] = ids
            if seg_id not in seg_ids:
                item["script_segment_id"] = ""
            cleaned.append(item)
        shots = ss.normalize_shots(cleaned, scene_ids, char_ids, seg_ids)
        if not shots:
            raise StageError("导演分镜", "分镜缺少画面描述。请重试。")
        shots = [s for s in shots[:MAX_SHOTS]]
        _beat_stages(shots, plan)
        return shots

    # ---- 阶段 3.5：时长规划 ----
    def plan_pacing(self, shots: list[dict], target_seconds: float,
                    allow_resize: bool = True) -> dict:
        """按最终镜头列表分配时长，并把结果写回每个镜头。

        镜头数不可行时会截断（allow_resize=True）或提示（False）——此时
        plan_durations 只覆盖前 N 个镜头。这里以返回的 kept_shot_ids 为准
        精确匹配，不能用「长度相等 = 一一对应」的假设，否则截断时会错位或误报。
        """
        n_in = len(shots or [])
        result = pacing.plan_durations(shots, target_seconds, allow_resize=allow_resize)
        durations = result.get("durations") or []
        kept_ids = result.get("kept_shot_ids")
        if kept_ids is not None:
            by_key = {(s.get("shot_id") if s.get("shot_id") is not None else i): s
                      for i, s in enumerate(shots)}
            assigned = 0
            for key, duration in zip(kept_ids, durations):
                shot = by_key.get(key)
                if shot is None:
                    continue
                shot["duration"] = duration
                assigned += 1
        elif len(durations) == n_in:
            for shot, duration in zip(shots, durations):
                shot["duration"] = duration
            assigned = n_in
        else:
            assigned = -1
        total_out = round(sum(float(s.get("duration") or 0) for s in shots), 2)
        if assigned != len(durations) or len(durations) > n_in:
            details = _pacing_mismatch_details(shots, target_seconds, result)
            try:
                _log_pacing(details, self.log_path)
            except Exception:       # 日志失败不能掩盖真正的错误
                pass
            raise StageError(
                "时长规划",
                f"时长分配结果与镜头数量不一致：分配了 {len(durations)} 个时长，"
                f"镜头 {n_in} 个，成功写回 {max(assigned, 0)} 个。"
                + (f"（被截断 {len(result.get('trimmed_index') or [])} 个镜头）。"
                   if result.get("trimmed_index") else ""))
        if result.get("message"):
            self._notify("时长规划", result["message"])
        return result

    # ---- 阶段 4：出图提示词 ----
    def image_prompts(self, shots: list[dict], style: str = "") -> list[dict]:
        if not shots:
            return []
        batch = [{"shot_id": s.get("shot_id"), "image_prompt": s.get("image_prompt"),
                  "scene_id": s.get("scene_id"), "character_ids": s.get("character_ids")}
                 for s in shots]
        user = f"""请把下面每个分镜的画面描述压缩成 1~2 句精炼的英文出图提示词。

要求：
1. 只写画面本身：主体、动作、构图、光线方向、色调、材质、恐怖细节。
2. 不要写画风、不要写 "horror movie still"、不要写负面词（画风与负面词由系统统一附加）。
3. 每个 shot_id 都要有一条 prompt，数量与输入一致。
4. prompt 不超过 90 个英文单词。

分镜：
{json.dumps(batch, ensure_ascii=False, indent=2)}

{_json_line()}

参考结构：
{_IMAGE_PROMPT_EXAMPLE}"""
        budget = PROMPT_TOKENS_PER_SHOT * len(shots) + 2048
        budget = max(PROMPT_BUDGET_FLOOR, min(PROMPT_BUDGET_CEIL, budget))
        data = self._call_json("fast", "出图提示词", SYSTEM_PROMPT, user, _IMAGE_PROMPT_EXAMPLE,
                               min_tokens=budget)
        raw = data.get("prompts") if isinstance(data, dict) else None
        by_id = {}
        for item in raw or []:
            if isinstance(item, dict) and item.get("shot_id"):
                text = str(item.get("prompt") or "").strip()
                if text:
                    by_id[str(item["shot_id"])] = text[:600]
        for shot in shots:
            text = by_id.get(str(shot.get("shot_id")))
            if text:
                shot["image_prompt_en"] = text
                shot["image_prompt_cn"] = shot.get("image_prompt", "")
                shot["image_prompt"] = text
        return shots

    # ---- 阶段 5：质量审核 ----
    def review(self, story: dict, use_model: bool = True) -> ss.QualityReport:
        target = _story_target(story)
        local = story_quality.local_review(story, target)
        model_report = None
        if use_model:
            try:
                model_report = self._model_review(story)
            except (StoryError, ss.SchemaError) as exc:
                local.issues.append(ss.QualityIssue(
                    stage="quality", severity="warning", code="model_review_failed",
                    message=f"模型评分失败，仅保留本地检查：{exc}"))
        return story_quality.merge_review(local, model_report)

    def _model_review(self, story: dict) -> ss.QualityReport:
        shots = story.get("shots") or []
        slim = [{"shot_id": s.get("shot_id"), "scene_id": s.get("scene_id"),
                 "characters": s.get("character_ids"), "narration": s.get("narration"),
                 "duration": s.get("duration")} for s in shots]
        plan = story.get("plan") or {}
        user = f"""请审核下面这个恐怖短剧，按评分表打分并指出问题。

策划：
{json.dumps({k: plan.get(k) for k in ('theme', 'core_conflict', 'motivation', 'reversal',
                                      'reversal_type', 'hook', 'ending', 'ending_type',
                                      'foreshadows')}, ensure_ascii=False, indent=2)}

人物：{json.dumps([{'id': c.get('character_id'), 'name': c.get('name'),
                   'motivation': c.get('motivation')} for c in story.get('characters') or []],
                  ensure_ascii=False)}
场景：{json.dumps([{'id': s.get('scene_id'), 'name': s.get('name')}
                  for s in story.get('scenes') or []], ensure_ascii=False)}

分镜（{len(slim)} 个，总时长 {sum(float(s.get('duration') or 0) for s in shots):.1f} 秒）：
{json.dumps(slim, ensure_ascii=False)}

评分表（满分见括号，各项不得超过满分）：
剧情完整性（20）/ 逻辑合理性（20）/ 悬念设计（15）/ 恐怖氛围（15）/
人物塑造（10）/ 剧情反转（10）/ 旁白与对白（5）/ 分镜表现力（5）

否决条件（触发即不通过，即使分数很高）：
- weak_hook：前 3 秒没有悬念 / 异常 / 危险 / 强视觉（不要求首镜是高潮）
- abrupt_end：结局意外中断（完整 / 开放 / 系列悬念都可以，但必须有明确收束）
- missing_motivation：主角动机缺失
- unknown_reference：镜头引用了不存在的人物或场景
- duration_mismatch：总时长严重不符
- unforeshadowed_reversal：反转没有伏笔

要求：每个问题必须定位到 shot_id（能定位时），并给出修改建议。
人物可以跨多个场景出现，不要因此扣分。

{_json_line()}

参考结构：
{_QUALITY_EXAMPLE}"""
        data = self._call_json("planner", "质量审核", SYSTEM_PROMPT, user, _QUALITY_EXAMPLE)
        return ss.QualityReport.from_model(data, model=self.model_for("planner"))

    # ---- 完整流水线 ----
    def pipeline(self, concept: dict, keywords: str = "", style: str = "",
                 extra: str = "", shot_count: int | None = None,
                 use_model_review: bool = True) -> dict:
        """阶段 1~5：策划 → 剧本 → 分镜 → 时长 → 出图提示词 → 审核。返回完整 story。"""
        self._notify("故事策划", "正在写故事策划……")
        bundle = self.plan_story(concept, keywords, style, extra, shot_count)
        self._notify("完整剧本", "正在写完整剧本……")
        script = self.write_script(bundle, extra)
        self._notify("导演分镜", "正在拆导演分镜……")
        shots = self.storyboard(bundle, script)
        tier = bundle.get("duration_tier") or DEFAULT_DURATION_TIER
        target = _target_seconds(tier)
        if shot_count:
            # 用户直接给了镜头数：总时长按分镜数落在档内的部分来定，而不是固定档中点
            target = _target_for_count(shot_count, target)
        self._notify("时长规划", f"正在按 {target:.0f} 秒规划时长……")
        pacing_result = self.plan_pacing(shots, target, allow_resize=True)
        try:
            self._notify("出图提示词", "正在生成出图提示词……")
            self.image_prompts(shots, style)
        except StoryError:
            for shot in shots:
                shot.setdefault("image_prompt_en", shot.get("image_prompt", ""))
        story = self._assemble_story(bundle, script, shots, keywords, style,
                                     target, pacing_result)
        self._notify("质量审核", "正在做质量审核……")
        report = self.review(story, use_model=use_model_review)
        story["quality"] = ss.normalize_quality(report) or {}
        return story

    def _assemble_story(self, bundle, script, shots, keywords, style, target,
                        pacing_result) -> dict:
        total = round(sum(float(s.get("duration") or 0) for s in shots), 2)
        story = {
            "schema_version": ss.SCHEMA_VERSION,
            "title": bundle.get("title") or "未命名故事",
            "logline": bundle.get("logline") or "",
            "keywords": keywords or "",
            "style": style or "",
            "generated_at": _now(),
            "model": self.model_for("planner"),
            "ruleset": bundle.get("ruleset") or "",
            "duration_tier": bundle.get("duration_tier") or DEFAULT_DURATION_TIER,
            "concept_id": bundle.get("concept_id") or "",
            "concepts": bundle.get("concepts") or [],
            "plan": bundle.get("plan") or {},
            "characters": bundle.get("characters") or [],
            "scenes": bundle.get("scenes") or [],
            "script": script,
            "shots": shots,
            "pacing": {
                "target_seconds": round(float(target), 2),
                "total_seconds": total,
                "error": pacing_result.get("error"),
                "shot_count": len(shots),
                "kept_count": pacing_result.get("kept_count", len(shots)),
                "trimmed_count": len(pacing_result.get("trimmed_index") or []),
                "min_seconds": MIN_DURATION,
                "max_seconds": MAX_DURATION,
                "weights": pacing_result.get("weights") or {},
                "message": pacing_result.get("message") or "",
            },
            "total_duration": total,
        }
        for i, shot in enumerate(shots, 1):
            shot["index"] = i
            shot.setdefault("scene", shot.get("image_prompt", ""))
            if not shot.get("content_hash"):
                shot["content_hash"] = ss.shot_content_hash(shot)
        return story

    # ---- V2.1 兼容入口 ----
    def generate(self, keywords: str, shot_count: int = 8, style: str = "",
                 extra: str = "", temperature: float | None = None) -> dict:
        """一步式生成（保持 V2.1 签名）。温度由 model_config 管理，temperature 参数忽略。"""
        keywords = (keywords or "").strip()
        if not keywords:
            raise StoryError("请先输入题材关键词，例如：废弃医院、纸人、雨夜。")
        tier = _tier_for_shot_count(shot_count)
        concepts = self.generate_concepts(keywords, style, extra, tier, count=1)
        story = self.pipeline(concepts[0], keywords, style, extra,
                              shot_count=clamp_shot_count(shot_count))
        return story

    def test_connection(self) -> str:
        """用一次极小的调用验证 Key 是否可用。返回模型名。"""
        if not self.api_key:
            raise StoryError("还没有填写 API Key。")
        model = self.model_for(model_config.LEGACY_SLOT)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "只回复两个字：就绪"}],
            "max_tokens": 8,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        raw = self.transport(f"{self.base_url}/chat/completions", headers, payload, 30)
        content = extract_content(raw, allow_empty=True)
        return f"连接成功（{model}）：{content or 'OK'}"


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
def extract_content(response: dict, allow_empty=False) -> str:
    """从 chat/completions 响应里取出文本内容。"""
    try:
        choice = response["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise StoryError("DeepSeek 返回数据格式异常，未找到内容。") from exc
    content = content.strip()
    finish = (choice.get("finish_reason") or "") if isinstance(choice, dict) else ""
    if finish == "length":
        # 实测（2026-11-04）：分镜这类长输出会把大部分预算花在推理 token 上，
        # finish_reason=length 时 content 也可能非空但被截断——JSON 一定不完整，
        # 必须当可重试的「预算不足」处理，否则会走到 JSON 修复甚至解析出半截故事。
        raise ContentTruncated(
            "模型输出被截断（max_tokens 被推理 token 用尽）。"
            f"已产出 {len(content)} 字，JSON 不完整。请重试或调大 planner 的 max_tokens。")
    if not content:
        if allow_empty:
            return ""
        # JSON 模式下 DeepSeek 偶尔会把无法解析的内容替换成空白
        raise ContentEmpty("模型没有返回有效内容（可能是内容被安全策略拦截），请换个题材或重试。")
    return content


def _salvage_truncated_list(text: str) -> str | None:
    # 把被截断的 JSON 列表尽量救回来：截到最后一个完整的顶层对象再补 ] 收尾。
    #
    # text 形如 {"shots": [{...}, {...}, {"shot_id": "s037", "image_p"（断在半截）。
    # 返回截断后的文本（仍是非法 JSON 的边缘情况交给 fast 槽位再修），
    # 救不回来返回 None。
    # 注意：文档字符串里不能出现 {"shots": ...} 这种片段—— Python 会把
    # \" 当转义，字符串提前结束，后面整段代码被吞进字符串里。
    text = (text or "").strip()
    if not text.startswith("{"):
        return None
    key_at = text.find('"shots"')
    if key_at < 0:
        return None
    bracket = text.find("[", key_at)
    if bracket < 0:
        return None
    # 从 shots 的 '[' 开始扫描（栈底就是它）：一个分镜对象 = ['[', '{']，
    # 对象闭合回到 1 层 = 一个镜头完整；列表的 ']' 闭合到 0 层 = 列表本身完整。
    stack = []
    in_str = False
    escape = False
    last_complete = -1
    for i in range(bracket, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue          # 字符串内不处理括号（包括充当引号的那个字符）
        if ch == '"':
            in_str = True
        elif ch == "{" or ch == "[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
            if len(stack) == 1:
                last_complete = i
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
            if not stack:
                return None
    if last_complete < 0:
        return None
    return text[:last_complete + 1] + "]}"


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    fence = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        return fence.group(1).strip()
    return text


def _find_json_object(text: str) -> str | None:
    """从可能夹带前后文的文本里提取第一个可解析的完整 JSON 对象。

    模型可能在 JSON 前后夹带说明文字（里面也可能出现 `{`），
    所以逐个 `{` 起点尝试，返回第一个能通过括号配平的完整对象。
    """
    start = 0
    candidates = []
    while True:
        start = text.find("{", start)
        if start < 0:
            break
        candidates.append(start)
        start += 1
    for start in candidates:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def parse_json_object(content: str) -> dict:
    """把模型输出解析成 dict（容忍 markdown 代码块与前后说明）。"""
    text = _strip_fences(content or "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # 输出不是从头就是 JSON：
        # 1) 从首个 `{` 起 raw_decode——只有真正闭合的对象才成功，
        #    截断文本里嵌套对象恰好配平的「半截对象」会失败；
        # 2) 分镜列表被截断时在解析层也兜一次：截到最后一个完整镜头再收尾
        #    （空列表 / 半截镜头不兜，交调用方重试）；
        # 3) 否则找夹在说明文字里的第一个完整对象（只有首个 `{` 之前有说明文字时，
        #    才可能真的夹带 JSON；首字符就是 `{` 的截断输出不会走到这里）。
        first = text.find("{")
        if first >= 0:
            try:
                return _parse_first_json_value(text[first:])
            except StoryError:
                pass
        if first >= 0 and not text[:first].strip() and '"shots"' in text:
            # 分镜列表被截断时在解析层也兜一次：截到最后一个完整镜头再收尾，
            # 比整阶段重试省时间（空列表 / 半截镜头不兜，交调用方重试）。
            salvaged = _salvage_truncated_list(text)
            if salvaged is not None:
                try:
                    value = _parse_first_json_value(salvaged)
                except StoryError:
                    value = None
                if isinstance(value, dict) and value.get("shots"):
                    return value
        candidate = _find_json_object(text)
        if candidate is None:
            raise StoryError("模型输出的内容不是有效 JSON。请重试，或减少生成数量。")
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            raise StoryError(f"模型输出的 JSON 不完整（{exc.msg}）。请重试。") from exc
    if not isinstance(data, dict):
        raise StoryError("模型输出的 JSON 结构不正确（应为对象）。")
    return data


def _parse_first_json_value(text: str) -> dict:
    """解析文本开头的完整 JSON 对象，忽略其后多余内容。"""
    try:
        value, _end = json.JSONDecoder().raw_decode(text.lstrip())
    except (json.JSONDecodeError, ValueError) as exc:
        raise StoryError(f"模型输出的 JSON 不完整（{exc}）") from exc
    if not isinstance(value, dict):
        raise StoryError("模型输出的 JSON 结构不正确（应为对象）")
    return value


def _pick(data: dict, *names, default=None):
    lowered = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        if name in data:
            return data[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return default


def _pick_plan(data: dict) -> dict:
    plan = _pick(data, "plan", "story_plan", "策划", "storyplan", default=None)
    if isinstance(plan, dict):
        return plan
    # 模型有时把策划字段平铺在顶层
    keys = ("theme", "background", "core_conflict", "motivation", "stakes", "reversal",
            "reversal_type", "hook", "ending", "ending_type", "acts", "conflicts",
            "foreshadows", "tone")
    return {k: data[k] for k in keys if k in data}


def parse_story(content: str) -> dict:
    """把模型输出解析成 story dict（兼容 V2.1 的一步式 JSON）。"""
    data = parse_json_object(content)
    title = str(_pick(data, "title", "标题", default="未命名故事") or "未命名故事")[:40]
    logline = str(_pick(data, "logline", "summary", "简介", "梗概", default="") or "").strip()
    # 注意：不能把 "scenes" 当分镜字段——V2.1 起 scenes 是顶层的「场景卡」。
    raw_shots = _pick(data, "shots", "storyboard", "shot_list", "分镜", default=[])
    if isinstance(raw_shots, dict):
        raw_shots = _pick(raw_shots, "shots", "items", "list", default=[])
    if not isinstance(raw_shots, list) or not raw_shots:
        raise StoryError("模型没有返回任何分镜（shots 为空）。请重试。")

    shots = []
    for raw in raw_shots:
        if not isinstance(raw, dict):
            continue
        scene = str(_pick(raw, "image_prompt", "scene", "image", "prompt", "visual",
                          "画面", "画面描述", default="") or "").strip()
        narration = str(_pick(raw, "narration", "voice", "text", "line", "旁白", "字幕",
                              default="") or "").strip()
        if not scene and not narration:
            continue
        duration = _as_duration(_pick(raw, "duration", "seconds", "time", "时长"), narration)
        motion = str(_pick(raw, "motion", "camera", "运镜", default="") or "").strip().lower()
        if motion not in MOTION_MODES:
            motion = "static"
        voiced_raw = _pick(raw, "voiced", "has_narration", "有声", default=None)
        if isinstance(voiced_raw, bool):
            voiced = voiced_raw
        elif voiced_raw is None:
            voiced = bool(narration)
        else:
            voiced = str(voiced_raw).strip().lower() not in ("false", "0", "no", "否", "无")
        if not voiced:
            narration = ""
        shots.append({
            "index": len(shots) + 1,
            "scene": scene or narration,
            "narration": narration,
            "duration": duration,
            "motion": motion,
            "voiced": voiced,
        })
    if not shots:
        raise StoryError("模型返回的分镜都缺少画面描述和旁白。请重试。")
    shots = shots[:MAX_SHOTS]
    for i, shot in enumerate(shots):
        shot["index"] = i + 1

    return {
        "title": title,
        "logline": logline,
        "keywords": "",
        "characters": _parse_cards(_pick(data, "characters", "roles", "角色")),
        "scenes": _parse_cards(_pick(data, "scenes", "locations", "locations_cards", "场景")),
        "shots": shots,
        "total_duration": round(sum(s["duration"] for s in shots), 3),
    }


def _parse_cards(value) -> list[dict]:
    """解析角色卡 / 场景卡：[{"name": ..., "look": ...}]。容忍字符串数组与键名差异。"""
    if isinstance(value, dict):
        value = [{"name": k, "look": v} for k, v in value.items()]
    if not isinstance(value, list):
        return []
    cards = []
    for raw in value[:12]:
        if isinstance(raw, str):
            text = raw.strip()
            if text:
                cards.append({"name": text[:20], "look": text})
            continue
        if not isinstance(raw, dict):
            continue
        name = str(_pick(raw, "name", "名字", "角色", "场景", default="") or "").strip()
        look = str(_pick(raw, "look", "description", "appearance", "外貌", "描述",
                         default="") or "").strip()
        if not look and not name:
            continue
        cards.append({"name": name[:20], "look": (look or name)[:300]})
    return cards


def _as_duration(value, narration: str) -> float:
    try:
        value = float(str(value).replace("s", "").replace("秒", "").strip())
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        value = max(DEFAULT_DURATION, pacing.reading_seconds(narration) + 0.3)
    return round(min(MAX_DURATION, max(MIN_DURATION, value)), 2)


def clamp_shot_count(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 30
    return max(MIN_SHOTS, min(MAX_SHOTS, value))


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------
def _target_seconds(tier: str) -> float:
    low, high, _ = DURATION_TIERS.get(tier, DURATION_TIERS[DEFAULT_DURATION_TIER])
    return (low + high) / 2.0


def _target_for_count(shot_count, default_target: float) -> float:
    """按「用户要求的镜头数 × 平均 4 秒」定总时长，再夹回档内上下限。"""
    try:
        n = clamp_shot_count(shot_count)
    except (TypeError, ValueError):
        return default_target
    raw = n * SEGMENT_AVG_SECONDS
    lo, hi = pacing.feasible_range(n)
    # 贴近上限时留 1% 回退，避免「n 镜 × 6 秒」的目标卡在边界上导致后续都要按上限分配
    return round(min(max(raw, lo), hi * 0.99), 2)


def _tier_for_shot_count(shot_count: int) -> str:
    try:
        n = int(shot_count)
    except (TypeError, ValueError):
        return DEFAULT_DURATION_TIER
    for tier, (low, high) in SHOT_RANGE_BY_TIER.items():
        if low <= n <= high:
            return tier
    return DEFAULT_DURATION_TIER


def _log_pacing(details: dict, log_path=None):
    call_log.record(details, log_path)


def _pacing_mismatch_details(shots, target_seconds, result) -> dict:
    """时长规划对不上时写进调用日志的诊断信息（不写旁白正文，避免隐私）。"""
    durations = result.get("durations") or []
    ids = [s.get("shot_id") for s in shots or []]
    return {
        "stage": "时长规划",
        "slot": "",
        "model": "",
        "target_seconds": target_seconds,
        "shot_count": len(shots or []),
        "duration_count": len(durations),
        "durations": list(durations),
        "shot_ids": ids,
        "duplicate_shot_ids": sorted({i for i in ids if ids.count(i) > 1}),
        "trimmed_index": result.get("trimmed_index"),
        "resized": result.get("resized"),
        "pacing_error": result.get("error"),
        "pacing_message": result.get("message") or "",
        "ok": False,
        "error": "时长分配结果与镜头数量不一致",
    }


def _story_target(story: dict) -> float | None:
    pacing_block = story.get("pacing") or {}
    for key in ("target_seconds", "total_seconds"):
        try:
            value = float(pacing_block.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


_STAGES = ("hook", "setup", "escalation", "reversal", "aftertaste")
# 剧本段 / 分镜每镜的平均时长（1.5~6 秒的中段）。低于它分镜数就要往上抬。
SEGMENT_AVG_SECONDS = 4.0


def _needed_segments(target_seconds: float, have: int) -> int:
    """按目标时长算剧本段至少要几段（最多 MAX_SHOTS）。0 表示现有段数够用。"""
    try:
        target = float(target_seconds or 0)
    except (TypeError, ValueError):
        return 0
    if target <= 0:
        return 0
    # 一次最多写满 MAX_SHOTS 段；再长就交给分镜阶段合并（一段可拆多镜，也可合并）
    target = min(target, SEGMENT_AVG_SECONDS * MAX_SHOTS)
    raw_need = int(round(target / SEGMENT_AVG_SECONDS))
    need = min(MAX_SHOTS, max(MIN_SHOTS, raw_need))
    return need if have < need else 0


def _beat_stages(shots: list[dict], plan: dict | None = None) -> None:
    """修整 act/beat。

    * 有策划的 acts 时按策划区间重新分段（策划才是五段结构的权威）；
    * 否则按镜头顺序保证单调不减、不跳档（模型常把镜头乱标）。
    """
    if not shots:
        return
    plan = plan or {}
    acts = [a for a in (plan.get("acts") or []) if isinstance(a, dict)]
    if len(acts) >= 2 and acts[-1].get("end") == len(shots):
        spans = []
        for a in acts:
            act = a.get("act") if a.get("act") in _STAGES else None
            start, end = int(a.get("start") or 0), int(a.get("end") or 0)
            if act and start >= 1 and end >= start:
                spans.append((start, end, act))
        if spans:
            for i, shot in enumerate(shots, 1):
                act = next((name for start, end, name in spans if start <= i <= end),
                           spans[-1][2])
                shot["act"] = act
                shot["beat"] = act
            return
    last = 0
    for i, shot in enumerate(shots):
        if i == 0:
            last = 0
        elif i == len(shots) - 1:
            last = len(_STAGES) - 1
        else:
            raw = _STAGES.index(shot.get("act")) if shot.get("act") in _STAGES else None
            if raw is None:
                raw = _STAGES.index(shot.get("beat")) if shot.get("beat") in _STAGES else last
            last = max(last, min(raw, len(_STAGES) - 2))
        act = _STAGES[last]
        shot["act"] = act
        shot["beat"] = act


def _ref_ids(cards: list[dict], id_key: str, name_key: str) -> dict:
    """{id: id, 名字: id}：模型把 id 写成中文名字时也能映射回卡片。"""
    table = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        ident = card.get(id_key) or ""
        if ident:
            table[ident] = ident
        name = (card.get(name_key) or "").strip()
        if name and ident:
            table[name] = ident
    return table


def _nearest_scene(text: str, scenes: list[dict]) -> str:
    for scene in scenes:
        name = scene.get("name") or ""
        if name and name in (text or ""):
            return scene.get("scene_id", "")
    return scenes[0].get("scene_id", "") if scenes else ""


def _fit_acts(acts: list[dict], total: int) -> list[dict]:
    """把模型给的 acts 重排成连续、覆盖 1~total 的五段（不足五段就均分补齐）。"""
    order = ("hook", "setup", "escalation", "reversal", "aftertaste")
    if total <= 0:
        return []
    acts = [a for a in acts if isinstance(a, dict)]
    if len(acts) < 2:
        # 模型没给或只给了一段：按比例切五段。末段只有 1 镜时反转并进余味
        # （宁可少一段，也不硬造镜头）。
        ratios = (0.0, 0.15, 0.5, 0.8, 0.9)
        cuts = sorted({min(total + 1, max(1, round(total * r) + 1)) for r in ratios})
        cuts.append(total + 1)
        out = []
        for i in range(len(cuts) - 1):
            key = order[min(i, len(order) - 1)]
            out.append({"act": key, "start": cuts[i], "end": cuts[i + 1] - 1,
                        "summary": ""})
        if out:
            out[-1]["summary"] = acts[0].get("summary", "") if acts else ""
        return out
    first = min(max(1, int(acts[0].get("start") or 1)), total)
    last = min(total, max(int(a.get("end") or 0) for a in acts))
    span = max(1, last - first + 1)
    out = []
    for i, act in enumerate(acts):
        start = first + round(i * span / len(acts))
        end = first + round((i + 1) * span / len(acts)) - 1
        if end < start:
            end = start
        if end > total:
            break
        key = act.get("act") or order[min(i, len(order) - 1)]
        out.append({"act": key if key in order else order[min(i, len(order) - 1)],
                    "start": start, "end": end, "summary": act.get("summary", "")})
    if out:
        out[-1]["end"] = total
    return out


def _dedupe_concepts(concepts: list[dict], count: int) -> list[dict]:
    """保证反转类型尽量互不相同；数量不够时从剩余里按顺序补齐。"""
    kept, used = [], set()
    for concept in concepts:
        kind = concept.get("reversal_type", "none")
        if kind not in used or len(kept) >= count:
            kept.append(concept)
            used.add(kind)
    for concept in concepts:
        if len(kept) >= count:
            break
        if concept not in kept:
            kept.append(concept)
    return kept[:count]


def to_project_shots(story: dict) -> list[dict]:
    """转换成 project.json 的 shots 条目（不含 id/image，交给 ProjectManager 补）。"""
    result = []
    for shot in story.get("shots", []):
        motion = shot.get("motion") or "static"
        result.append({
            "image": None,
            "duration": float(shot.get("duration", DEFAULT_DURATION)),
            # 同时写旧 zoom 字段，让还没升级的预览 / 旧逻辑也能工作
            "zoom": {"push-in": "in", "pull-out": "out", "diag-in": "in"}.get(motion, "none"),
            "motion": motion,
            "voiced": bool(shot.get("voiced", True)),
            "transition": None,  # 交给 replace_all_shots 按运镜推导
            "subtitle": None,
            "scene": shot.get("image_prompt") or shot.get("scene", ""),
            "narration": shot.get("narration", ""),
            "shot_id": shot.get("shot_id", ""),
            "shot_revision": shot.get("revision", 0),
            "content_hash": shot.get("content_hash") or ss.shot_content_hash(shot),
        })
    return result


# ----------------------------------------------------------------------
# 配音风格 & 出图一致性提示（V2.1 接口保留）
# ----------------------------------------------------------------------
STYLE_KEYWORDS = {
    "folk": ("民俗", "纸人", "灵堂", "丧", "祠堂", "红白", "冥婚", "扎纸"),
    "urban": ("都市", "地铁", "电梯", "公寓", "楼道", "电话", "小区", "保安", "监控"),
    "cosmic": ("克苏鲁", "深渊", "古神", "触手", "异形", "星空", "不可名状"),
    "psych": ("心理", "记忆", "幻觉", "心理咨询", "分裂", "失眠", "梦"),
}
STYLE_NAMES = {"folk": "folk", "urban": "urban", "cosmic": "cosmic", "psych": "psych",
               "klang": "cosmic"}
_CANONICAL = {"民俗": "folk", "都市": "urban", "克苏鲁": "cosmic", "心理": "psych",
              "中式民俗": "folk", "日式都市": "urban"}


def infer_style(keywords: str = "", style: str = "") -> str:
    """把题材关键词 / 风格文字映射到配音风格预设名；识别不了时返回 'default'。"""
    text = f"{style} {keywords}"
    for label, key in _CANONICAL.items():
        if label in text:
            return key
    for key, words in STYLE_KEYWORDS.items():
        if any(word in text for word in words):
            return key
    return "default"


def build_consistency_hint(story: dict | None, scene: str = "") -> str:
    """出图时的「一致性提示词」：角色卡 + 场景卡。

    V2.2 起优先使用镜头引用的 character_ids / scene_id（见 image_engine），
    这里保留 V2.1 的按名字匹配作为兜底。
    """
    if not isinstance(story, dict):
        return ""
    parts = []
    chars = story.get("characters") or []
    if scene and chars:
        mentioned = [c for c in chars if c.get("name") and c["name"] in scene]
        others = [c for c in chars if c not in mentioned]
        chars = mentioned + others
    for card in chars[:3]:
        look = (card.get("look") or "").strip()
        if look:
            parts.append(f"角色（{card.get('name') or '主角'}）：{look}")
    for card in (story.get("scenes") or [])[:2]:
        look = (card.get("look") or "").strip()
        if look:
            parts.append(f"场景：{look}")
    return "；".join(parts)


def to_srt(story: dict, offset: float = 0.0) -> str:
    """把旁白转成 SRT 文本，时间按 duration 累加，可加 offset（追加导入时用）。"""
    def ts(seconds: float) -> str:
        ms = int(round(max(0.0, seconds) * 1000))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks = []
    cursor = float(offset)
    n = 0
    for shot in story.get("shots", []):
        dur = float(shot.get("duration", DEFAULT_DURATION))
        text = (shot.get("narration") or "").strip()
        if text:
            n += 1
            blocks.append(f"{n}\n{ts(cursor)} --> {ts(cursor + dur)}\n{text}")
        cursor += dur
    return "\n\n".join(blocks) + ("\n" if blocks else "")
