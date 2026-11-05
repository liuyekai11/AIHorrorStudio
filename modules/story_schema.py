"""故事数据结构（V2.2）：手写 dataclass 校验层，不引入 pydantic。

设计原则
--------
* **宽容 from_dict**：模型返回的 JSON 字段名大小写不一、数值是字符串、
  id 写成了中文 / 重复 / 缺失——一律尽量落地，不整段丢弃。
* **严格 validate**：只做「结构上不可能接受」的检查（缺必填、数值越界、
  列表为空），供引擎在阶段边界调用；语义质量交给 quality.py。
* **旧数据兼容**：schema 1 的 story（title/logline/characters[name,look]/
  scenes[name,look]/shots[index,scene,narration,duration,motion,voiced]）
  必须能被 upgrade_story() 无损升级到 schema 2，旧字段全部保留。
* 纯标准库，可单独测试。

字段关系
--------
GameConcept / StoryConcept     阶段 0 创意候选
StoryPlan                      阶段 1 故事策划（含人物、场景、剧本大纲）
CharacterProfile / SceneProfile 可复用卡片：角色可跨多个场景出现
ScriptSegment                  阶段 2 剧本段；一段可对应多个镜头
StoryboardShot                 阶段 3 镜头；script_segment_id / scene_id / character_ids
AudioSegment                   配音切分（与镜头版本关联由 project_manager 维护）
QualityReport                  阶段 5 审核结果
"""
from __future__ import annotations

import hashlib
import re
import uuid
import dataclasses
from dataclasses import dataclass, field, fields, asdict

SCHEMA_VERSION = 2

# 与 project_manager.MOTION_MODES / TRANSITION_MODES 保持一致（这里不 import，避免循环依赖）
MOTION_MODES = ("static", "push-in", "pull-out", "pan-left", "pan-right", "diag-in")
TRANSITION_MODES = ("cut", "fade", "dissolve", "flash")
BEAT_TIERS = ("hook", "setup", "escalation", "reversal", "aftertaste")
ENDINGS = ("closed", "open", "series")          # 完整结局 / 开放式 / 系列悬念
REVERSAL_TYPES = ("identity", "time", "space", "motivation", "perception", "none")
DURATION_TIERS = ("short", "standard", "long")  # 1~3 分钟 / 3~5 分钟 / 更长

MIN_SHOT_DURATION = 1.5
MAX_SHOT_DURATION = 6.0
MIN_TOTAL_DURATION = 30.0
MAX_TOTAL_DURATION = 900.0
TOTAL_DURATION_TOLERANCE = 1.0


class SchemaError(ValueError):
    """数据结构不合法。message 可直接展示。"""


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def _pick(data: dict, *names, default=None):
    """按顺序取字段：先精确匹配，再大小写不敏感。"""
    if not isinstance(data, dict):
        return default
    lowered = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        if name in data:
            return data[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return default


def _text(value, limit: int | None = None, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        value = "；".join(_text(v) for v in value if v not in (None, ""))
    text = str(value).strip()
    if limit is not None:
        text = text[:limit]
    return text or default


def _float(value, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return default
        text = str(value).strip().lower().replace("s", "").replace("秒", "").strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def _int(value, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in ("false", "0", "no", "否", "无", "n")


def _list(value) -> list:
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    if isinstance(value, dict):
        return [value]
    return [value]


def _str_list(value, limit: int = 20, item_limit: int = 120) -> list[str]:
    """容忍 "阿芸、老陈" / ["阿芸", "老陈"] / {"阿芸": "外貌"} 三种写法。"""
    if isinstance(value, dict):
        return [_text(k, item_limit) for k in value if _text(k)]
    if isinstance(value, str):
        parts = re.split(r"[、,，;；/\s]+", value.strip())
        return [_text(p, item_limit) for p in parts if _text(p)][:limit]
    items = []
    for raw in _list(value):
        if isinstance(raw, dict):
            raw = _pick(raw, "id", "name", "character_id", "scene_id", default="")
        text = _text(raw, item_limit)
        if text:
            items.append(text)
    return items[:limit]


def slug(text: str, prefix: str = "x", limit: int = 32) -> str:
    """中文 id 保留可读性：只把空白 / 标点替换掉，截断到 limit。"""
    text = re.sub(r"[\s/\\#?,:;\"'`~!@$%^&*()+=\[\]{}|<>。，、；：？！“”‘’（）]+", "_",
                  str(text or "").strip())
    text = text.strip("_")
    return (text or prefix)[:limit]


def content_hash(*parts) -> str:
    """镜头 / 剧本内容的稳定指纹（sha1 前 16 位），用于素材版本关联。"""
    raw = "\x1f".join(_text(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def shot_content_hash(shot) -> str:
    """镜头内容指纹：画面描述 + 旁白 + 运镜 + 时长（四舍五入到 0.01）。"""
    get = shot.get if isinstance(shot, dict) else lambda k, d=None: getattr(shot, k, d)
    return content_hash(get("image_prompt", "") or get("scene", ""),
                        get("narration", ""), get("motion", ""),
                        f"{_float(get('duration', 0)):.2f}")


# ----------------------------------------------------------------------
# 基类
# ----------------------------------------------------------------------
class _Record:
    """dataclass 子类共用：from_dict 时按字段名（含中文别名）取值。"""

    _ALIASES: dict = {}

    @classmethod
    def from_dict(cls, data) -> "_Record":
        data = data if isinstance(data, dict) else {}
        kwargs = {}
        for f in fields(cls):
            if not f.init:
                continue
            names = cls._ALIASES.get(f.name, ())
            value = _pick(data, f.name, *names, default=None)
            kwargs[f.name] = cls.coerce(f.name, value)
        return cls(**kwargs)

    @classmethod
    def coerce(cls, name: str, value):
        default = _default_of(cls, name)
        if isinstance(default, str):
            limit = getattr(cls, "_TEXT_LIMITS", {}).get(name)
            return _text(value, limit, default)
        if isinstance(default, bool):
            return _bool(value, default)
        if isinstance(default, float):
            return _float(value, default)
        if isinstance(default, int):
            return _int(value, default)
        if isinstance(default, list):
            return _list(value)
        return value if value is not None else default

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self):
        """子类覆盖；默认无约束。"""
        return self


def _default_of(cls, name: str):
    for f in fields(cls):
        if f.name == name:
            if f.default is not dataclasses.MISSING:
                return f.default
            if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                return f.default_factory()
            return None
    raise KeyError(name)


# ----------------------------------------------------------------------
# 阶段 0：创意候选
# ----------------------------------------------------------------------
@dataclass
class StoryConcept(_Record):
    concept_id: str = ""
    title: str = ""
    logline: str = ""
    core_conflict: str = ""
    reversal_type: str = "none"
    horror_device: str = ""
    hook: str = ""                       # 前 3 秒的悬念 / 异常 / 危险画面
    ending_type: str = "closed"
    duration_tier: str = "standard"
    ruleset: str = ""
    score_hint: str = ""                 # 模型自评的一句话（只作参考）
    _TEXT_LIMITS = {"title": 40, "logline": 200}

    def validate(self):
        if not self.core_conflict:
            raise SchemaError(f"创意 {self.title or self.concept_id} 缺少核心冲突。")
        if not self.hook:
            raise SchemaError(f"创意 {self.title or self.concept_id} 缺少开场钩子（hook）。")
        if self.reversal_type not in REVERSAL_TYPES:
            self.reversal_type = "none"
        if self.ending_type not in ENDINGS:
            self.ending_type = "closed"
        if self.duration_tier not in DURATION_TIERS:
            self.duration_tier = "standard"
        if not self.concept_id:
            self.concept_id = "c_" + uuid.uuid4().hex[:6]
        return self


# ----------------------------------------------------------------------
# 阶段 1：策划、人物、场景
# ----------------------------------------------------------------------
@dataclass
class CharacterProfile(_Record):
    character_id: str = ""
    name: str = ""
    role: str = ""                    # 主角 / 反派 / 配角 / 纸人等
    look: str = ""                    # 出图用的固定外貌卡
    motivation: str = ""              # 想要什么、为什么
    secret: str = ""
    voice: str = ""                   # 说话方式
    scene_ids: list = field(default_factory=list)   # 出现过的场景（仅提示，不限制）
    _TEXT_LIMITS = {"name": 20, "look": 300}

    def validate(self):
        if not self.name:
            raise SchemaError("有人物卡缺少 name。")
        if not self.look:
            raise SchemaError(f"人物「{self.name}」缺少外貌描述（look），无法保证出图一致性。")
        if not self.character_id:
            self.character_id = "ch_" + slug(self.name, "ch", 16)
        return self


@dataclass
class SceneProfile(_Record):
    scene_id: str = ""
    name: str = ""
    look: str = ""
    lighting: str = ""
    props: list = field(default_factory=list)
    _TEXT_LIMITS = {"name": 24, "look": 300}

    def validate(self):
        if not self.name:
            raise SchemaError("有场景卡缺少 name。")
        if not self.look:
            raise SchemaError(f"场景「{self.name}」缺少画面描述（look）。")
        if not self.scene_id:
            self.scene_id = "sc_" + slug(self.name, "sc", 16)
        return self


@dataclass
class ActBeat(_Record):
    act: str = ""                     # 钩子 / 建置 / 升级 / 反转 / 余味
    start: int = 0                    # 第几镜开始（1 起）
    end: int = 0
    summary: str = ""

    def validate(self):
        if self.start < 1:
            self.start = 1
        if self.end and self.end < self.start:
            self.end = self.start
        return self


@dataclass
class Conflict(_Record):
    description: str = ""
    parties: list = field(default_factory=list)
    escalates_at: int = 0


@dataclass
class Foreshadow(_Record):
    setup: str = ""                   # 埋伏笔（第几镜 / 哪一段）
    payoff: str = ""                  # 回收（第几镜）
    setup_shot: str = ""
    payoff_shot: str = ""

    def resolved(self) -> bool:
        return bool(self.payoff or self.payoff_shot)


@dataclass
class StoryPlan(_Record):
    theme: str = ""
    background: str = ""
    core_conflict: str = ""
    motivation: str = ""              # 主角动机（硬性否决：缺失）
    stakes: str = ""
    conflicts: list = field(default_factory=list)       # [Conflict]
    foreshadows: list = field(default_factory=list)     # [Foreshadow]
    reversal: str = ""
    reversal_type: str = "none"
    hook: str = ""                    # 前 3 秒
    ending: str = ""                  # 结局描述
    ending_type: str = "closed"
    acts: list = field(default_factory=list)            # [ActBeat]
    tone: str = ""
    ruleset: str = ""
    title: str = ""
    logline: str = ""
    style: str = ""

    def validate(self):
        missing = [k for k in ("core_conflict", "motivation", "hook", "ending")
                   if not getattr(self, k)]
        if missing:
            names = {"core_conflict": "核心冲突", "motivation": "主角动机",
                     "hook": "开场钩子", "ending": "结局"}
            raise SchemaError("策划缺少：" + "、".join(names[k] for k in missing))
        if self.reversal_type not in REVERSAL_TYPES:
            self.reversal_type = "none"
        if self.ending_type not in ENDINGS:
            self.ending_type = "closed"
        return self


# ----------------------------------------------------------------------
# 阶段 2：剧本
# ----------------------------------------------------------------------
@dataclass
class ScriptSegment(_Record):
    segment_id: str = ""
    scene_id: str = ""
    character_ids: list = field(default_factory=list)
    visual: str = ""                  # 画面动作（给分镜参考）
    narration: str = ""               # 旁白
    dialogue: list = field(default_factory=list)   # [{"character_id":..., "text":..., "emotion":...}]
    emotion: str = ""
    duration_hint: float = 0.0
    act: str = ""
    _TEXT_LIMITS = {"narration": 200}

    def validate(self, scene_ids=(), character_ids=()):
        if not self.scene_id:
            raise SchemaError("剧本段缺少 scene_id。")
        if scene_ids and self.scene_id not in set(scene_ids):
            raise SchemaError(f"剧本段 {self.segment_id} 引用了不存在的场景 {self.scene_id}。")
        for cid in self.character_ids:
            if character_ids and cid not in set(character_ids):
                raise SchemaError(f"剧本段 {self.segment_id} 引用了不存在的人物 {cid}。")
        if not self.narration and not self.dialogue and not self.visual:
            raise SchemaError(f"剧本段 {self.segment_id} 既没有旁白也没有对白和画面。")
        if not self.segment_id:
            self.segment_id = "seg_" + uuid.uuid4().hex[:6]
        return self

    @classmethod
    def coerce(cls, name, value):
        if name == "dialogue":
            return normalize_dialogue(value)
        return super().coerce(name, value)


def normalize_dialogue(value) -> list[dict]:
    out = []
    for raw in _list(value):
        if isinstance(raw, str):
            out.append({"character_id": "", "text": raw[:200], "emotion": ""})
            continue
        if not isinstance(raw, dict):
            continue
        text = _text(_pick(raw, "text", "line", "台词", "content", default=""), 200)
        if not text:
            continue
        out.append({
            "character_id": _text(_pick(raw, "character_id", "who", "speaker", "角色",
                                        "name", default=""), 40),
            "text": text,
            "emotion": _text(_pick(raw, "emotion", "tone", "情绪", default=""), 40),
        })
    return out


# ----------------------------------------------------------------------
# 阶段 3：分镜
# ----------------------------------------------------------------------
@dataclass
class StoryboardShot(_Record):
    shot_id: str = ""
    script_segment_id: str = ""
    scene_id: str = ""
    character_ids: list = field(default_factory=list)
    image_prompt: str = ""            # 出图用的画面描述（统一为英文 + 中文氛围词均可）
    motion: str = "static"
    duration: float = 2.5
    voiced: bool = True
    narration: str = ""
    transition: str = "cut"
    act: str = ""
    beat: str = ""                    # hook/setup/escalation/reversal/aftertaste
    weight: float = 0.0               # 节奏权重（0 = 由 beat 推导）
    revision: int = 0                 # 镜头版本号（由 project_manager 维护）
    content_hash: str = ""            # 镜头内容指纹（image_prompt+旁白+运镜+时长）
    _TEXT_LIMITS = {"image_prompt": 600, "narration": 200}

    def validate(self, scene_ids=(), character_ids=(), segment_ids=()):
        if not self.image_prompt:
            raise SchemaError(f"镜头 {self.shot_id or '?'} 缺少画面描述（image_prompt）。")
        if self.scene_id and scene_ids and self.scene_id not in set(scene_ids):
            raise SchemaError(f"镜头 {self.shot_id or '?'} 引用了不存在的场景 {self.scene_id}。")
        # 剧本段缺失不算致命（兼容旧数据），只由质量审核给出提示
        for cid in self.character_ids:
            if character_ids and cid not in set(character_ids):
                raise SchemaError(f"镜头 {self.shot_id or '?'} 引用了不存在的人物 {cid}。")
        if self.motion not in MOTION_MODES:
            self.motion = "static"
        if self.transition not in TRANSITION_MODES:
            self.transition = "cut"
        if self.beat and self.beat not in BEAT_TIERS:
            self.beat = ""
        if not self.voiced:
            self.narration = ""
        self.duration = round(min(MAX_SHOT_DURATION,
                                  max(MIN_SHOT_DURATION, _float(self.duration, 2.5))), 2)
        if not self.shot_id:
            self.shot_id = ""     # 交给 allocate_shot_ids 统一编号
        return self


def allocate_shot_ids(shots: list) -> list:
    """给缺 shot_id 的镜头编号 s001…；已有 id 的保留。

    模型偶尔会把同一组 shot_id 原样拆两次（得到 s001,a,b,s001,c）：重复 id
    必须改成新的唯一编号，否则时长 / 素材 / 配音按 shot_id 回写时会串镜或漏镜。
    """
    taken = set()
    for shot in shots:
        shot_id = getattr(shot, "shot_id", "") or ""
        if shot_id and shot_id not in taken:
            taken.add(shot_id)
        elif shot_id:
            shot.shot_id = ""
    n = 0
    for shot in shots:
        if shot.shot_id:
            continue
        while True:
            n += 1
            candidate = f"s{n:03d}"
            if candidate not in taken:
                shot.shot_id = candidate
                taken.add(candidate)
                break
    return shots


# ----------------------------------------------------------------------
# 配音 / 审核
# ----------------------------------------------------------------------
@dataclass
class AudioSegment(_Record):
    shot_id: str = ""
    kind: str = "narration"           # narration / dialogue
    text: str = ""
    voice: str = ""
    estimated_ms: int = 0
    revision: int = 0
    content_hash: str = ""

    def validate(self):
        if self.kind not in ("narration", "dialogue"):
            self.kind = "narration"
        if not self.shot_id:
            raise SchemaError("配音段缺少 shot_id。")
        return self


# 8 项评分与满分（合计 100）
SCORE_WEIGHTS = {
    "story_completeness": 20,   # 剧情完整性
    "logic": 20,                # 逻辑合理性
    "suspense": 15,             # 悬念设计
    "horror_atmosphere": 15,    # 恐怖氛围
    "characterization": 10,     # 人物塑造
    "reversal": 10,             # 剧情反转
    "dialogue_narration": 5,    # 旁白与对白
    "shot_design": 5,           # 分镜表现力
}
SCORE_LABELS = {
    "story_completeness": "剧情完整性",
    "logic": "逻辑合理性",
    "suspense": "悬念设计",
    "horror_atmosphere": "恐怖氛围",
    "characterization": "人物塑造",
    "reversal": "剧情反转",
    "dialogue_narration": "旁白与对白",
    "shot_design": "分镜表现力",
}
VETO_CODES = {
    "missing_motivation": "人物动机缺失",
    "weak_hook": "前 3 秒没有钩子",
    "abrupt_end": "结局意外中断、没有叙事收束",
    "unknown_reference": "引用了不存在的人物 / 场景",
    "duration_mismatch": "总时长严重不符",
    "unforeshadowed_reversal": "反转没有伏笔",
}


def grade_for(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 75:
        return "pass"
    if score >= 60:
        return "needs_work"
    return "regenerate"


GRADE_LABELS = {"excellent": "优秀", "pass": "合格", "needs_work": "需优化",
                "regenerate": "建议重新生成策划"}


@dataclass
class QualityIssue(_Record):
    stage: str = ""                   # concept/plan/script/storyboard/quality
    shot_id: str = ""
    segment_id: str = ""
    severity: str = "warning"         # info / warning / error / veto
    code: str = ""
    message: str = ""
    suggestion: str = ""

    def validate(self):
        if self.severity not in ("info", "warning", "error", "veto"):
            self.severity = "warning"
        if not self.message:
            raise SchemaError("质量问题缺少说明文字。")
        return self


@dataclass
class QualityReport:
    score: float = 0.0
    scores: dict = field(default_factory=dict)     # 8 项原始分
    grade: str = "regenerate"
    vetoes: list = field(default_factory=list)     # [{"code","message","shot_id"}]
    issues: list = field(default_factory=list)     # [QualityIssue]
    passed: bool = False
    model: str = ""
    notes: str = ""
    checked_at: str = ""

    def compute_score(self) -> float:
        total = 0.0
        for key, weight in SCORE_WEIGHTS.items():
            value = _float(self.scores.get(key, 0))
            total += max(0.0, min(float(weight), value))
        self.score = round(total, 1)
        self.grade = grade_for(self.score)
        self.passed = bool(self.score >= 60 and not self.vetoes)
        return self.score

    def veto_codes(self) -> list[str]:
        return [v.get("code", "") for v in self.vetoes if isinstance(v, dict)]

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "scores": dict(self.scores),
            "grade": self.grade,
            "vetoes": [dict(v) for v in self.vetoes if isinstance(v, dict)],
            "issues": [i.to_dict() if isinstance(i, QualityIssue) else dict(i)
                       for i in self.issues if isinstance(i, (dict, QualityIssue))],
            "passed": self.passed,
            "model": self.model,
            "notes": self.notes,
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_model(cls, data: dict, model: str = "") -> "QualityReport":
        """从模型返回的 JSON 构造；分数缺失的项按 0 计（由调用方决定重试）。"""
        data = data if isinstance(data, dict) else {}
        raw_scores = _pick(data, "scores", "评分", default={}) or {}
        if not isinstance(raw_scores, dict):
            raw_scores = {}
        # 容忍中文键
        scores = {}
        for key in SCORE_WEIGHTS:
            value = raw_scores.get(key)
            if value is None and SCORE_LABELS[key] in raw_scores:
                value = raw_scores[SCORE_LABELS[key]]
            if value is None:
                # 只在上面的精确键都没命中时才做模糊匹配（否则「剧情完整性」
                # 会被「剧情反转」的 contains 判断抢走）
                value = next((v for label, v in raw_scores.items()
                              if isinstance(label, str) and label in SCORE_LABELS[key]), None)
            scores[key] = _float(value, 0.0)
        report = cls(scores=scores, model=model,
                     notes=_text(_pick(data, "notes", "comment", "总结", default=""), 1000))
        veto = _pick(data, "vetoes", "否决", default=[]) or []
        if isinstance(veto, str):
            veto = [veto]
        for item in _list(veto):
            if isinstance(item, dict):
                report.vetoes.append({
                    "code": _text(_pick(item, "code", "type", default=""), 40),
                    "message": _text(_pick(item, "message", "reason", "说明", default=""), 300),
                    "shot_id": _text(_pick(item, "shot_id", "shot", default=""), 40),
                })
            elif _text(item):
                report.vetoes.append({"code": "", "message": _text(item, 300), "shot_id": ""})
        for item in _list(_pick(data, "issues", "问题", default=[])):
            if not isinstance(item, dict):
                continue
            issue = QualityIssue.from_dict(item)
            try:
                issue.validate()
            except SchemaError:
                continue
            report.issues.append(issue)
        report.compute_score()
        return report


# ----------------------------------------------------------------------
# 组装：payload → dict
# ----------------------------------------------------------------------
def _records(items, cls):
    out = []
    for raw in _list(items):
        if isinstance(raw, cls):
            out.append(raw)
        elif isinstance(raw, dict):
            out.append(cls.from_dict(raw))
    return out


def normalize_concepts(value) -> list[dict]:
    return [c.validate().to_dict() for c in _records(value, StoryConcept)]


def normalize_plan(value, characters=(), scenes=(), acts=None) -> dict:
    """payload.plan → StoryPlan dict。兼容只有嵌套结构、缺 plan 的情况。"""
    if not isinstance(value, dict):
        value = {}
    plan = StoryPlan.from_dict(value)
    plan.conflicts = [_simple(Conflict, c)
                      for c in _list(_pick(value, "conflicts", "冲突", default=[]))]
    plan.foreshadows = [_simple(Foreshadow, f)
                        for f in _list(_pick(value, "foreshadows", "伏笔", default=[]))]
    acts_value = _pick(value, "acts", "beats", "结构", default=None)
    plan.acts = [_simple(ActBeat, a) for a in _list(acts_value if acts_value is not None else acts)]
    try:
        plan.validate()
    except SchemaError:
        # 增量生成时策划可能还没填全：先落地，由阶段检查 / 质量审核负责拦截
        pass
    return plan.to_dict()


def _simple(cls, raw) -> dict:
    if isinstance(raw, str):
        if cls is Foreshadow:
            raw = {"setup": raw}
        elif cls is ActBeat:
            raw = {"act": raw}
        else:
            raw = {"description": raw}
    obj = cls.from_dict(raw)
    obj.validate()
    return obj.to_dict()


def normalize_characters(value) -> list[dict]:
    """人物卡。兼容旧格式 {"name","look"} 与 dict 映射 {"阿芸": "外貌"}。"""
    if isinstance(value, dict) and not any(k in value for k in ("name", "look", "character_id")):
        value = [{"name": k, "look": v} for k, v in value.items()]
    out = []
    seen = set()
    for char in _records(value, CharacterProfile):
        char.validate()
        base = char.character_id
        n = 2
        while char.character_id in seen:
            char.character_id = f"{base}_{n}"
            n += 1
        seen.add(char.character_id)
        out.append(char.to_dict())
    return out


def normalize_scenes(value) -> list[dict]:
    if isinstance(value, dict) and not any(k in value for k in ("name", "look", "scene_id")):
        value = [{"name": k, "look": v} for k, v in value.items()]
    out = []
    seen = set()
    for scene in _records(value, SceneProfile):
        scene.validate()
        base = scene.scene_id
        n = 2
        while scene.scene_id in seen:
            scene.scene_id = f"{base}_{n}"
            n += 1
        seen.add(scene.scene_id)
        out.append(scene.to_dict())
    return out


def normalize_script(value, scene_ids=(), character_ids=()) -> list[dict]:
    """剧本段。scene_id / character_ids 写成中文名或裸名时映射到 id（宽容）。

    scene_ids / character_ids 可以是 id 序列（只做校验），也可以是 {名字: id} 映射表
    （先把名字换成 id）。映射不上的 id 不清空——保留给上层（storyboard 会按剧本段纠正）。
    """
    def _name_map(value):
        if not isinstance(value, dict):
            return {v: v for v in value}
        if all(k == v for k, v in value.items()):
            return dict(value)                       # 恒等映射等于「只有这些合法 id」
        return dict(value)

    scene_names = _name_map(scene_ids)
    char_names = _name_map(character_ids)
    out = []
    for seg in _records(value, ScriptSegment):
        seg.scene_id = scene_names.get(seg.scene_id, seg.scene_id)
        seg.character_ids = [char_names.get(c, c) for c in seg.character_ids]
        seg.validate()
        out.append(seg.to_dict())
    return out


def normalize_shots(value, scene_ids=(), character_ids=(), segment_ids=()) -> list[dict]:
    """分镜。兼容旧字段 scene / narration / index。"""
    out = []
    for raw in _list(value):
        if not isinstance(raw, dict):
            continue
        if not _pick(raw, "image_prompt", "scene", "visual", "prompt", default=""):
            if not _pick(raw, "narration", "旁白", default=""):
                continue
        shot = StoryboardShot.from_dict(raw)
        if not shot.image_prompt:
            shot.image_prompt = _text(_pick(raw, "scene", "visual", "narration"), 600)
        if not shot.narration:
            shot.narration = _text(_pick(raw, "narration", "旁白", default=""), 200)
        if not shot.voiced:
            shot.narration = ""
        shot.validate(scene_ids, character_ids, segment_ids)
        out.append(shot)
    allocate_shot_ids(out)
    return [s.to_dict() for s in out]


def normalize_quality(value) -> dict | None:
    if isinstance(value, QualityReport):
        value.compute_score()
        return value.to_dict()
    if not isinstance(value, dict) or not value:
        return None
    report = QualityReport(
        scores={k: _float(v) for k, v in (value.get("scores") or {}).items()
                if k in SCORE_WEIGHTS},
        model=_text(value.get("model"), 60),
        notes=_text(value.get("notes"), 1000),
        checked_at=_text(value.get("checked_at"), 40),
        vetoes=[v for v in _list(value.get("vetoes")) if isinstance(v, dict)],
    )
    for raw in _list(value.get("issues")):
        if isinstance(raw, dict):
            try:
                report.issues.append(QualityIssue.from_dict(raw).validate())
            except SchemaError:
                continue
    report.compute_score()
    return report.to_dict()


# ----------------------------------------------------------------------
# 旧数据升级（schema 1 → 2）
# ----------------------------------------------------------------------
DEFAULT_WEIGHTS = {"hook": 1.2, "setup": 1.0, "escalation": 0.9,
                   "reversal": 0.7, "aftertaste": 1.4}


def _beat_for_index(index: int, total: int) -> str:
    if total <= 1:
        return "hook"
    if index <= 1:
        return "hook"
    if index == total:
        return "aftertaste"
    ratio = (index - 1) / max(1, total - 1)
    if ratio >= 0.8:
        return "reversal"
    if ratio >= 0.3:
        return "escalation"
    return "setup"


def _stage_ranges(total: int) -> list[tuple[str, int, int]]:
    """按比例给 5 个节拍划分镜区间（用于旧数据生成 acts）。"""
    order = ("hook", "setup", "escalation", "reversal", "aftertaste")
    if total <= 0:
        return []
    # 单调不减的切点（1 起），不足 5 段的节拍合并到前一段
    cuts = sorted({1, max(2, round(total * 0.15) + 1), max(3, round(total * 0.4)),
                   max(4, round(total * 0.8)), total + 1})
    cuts = [c for c in cuts if c <= total + 1]
    ranges = []
    for i in range(min(len(order), len(cuts) - 1)):
        start, end = cuts[i], min(cuts[i + 1] - 1, total)
        if start <= end:
            ranges.append((order[i], start, end))
    return ranges


def upgrade_story(story: dict) -> tuple[dict, bool]:
    """把 schema 1（或半结构）的 story 升级到 schema 2。返回 (新 story, 是否有改动)。

    * 顶层：title / logline / keywords / characters / scenes / shots 原样保留
    * 新增 stage 数据：concepts / plan / script / pacing / quality / versions
    * 场景 / 人物：名称作为 id（中文可读），并给每个镜头补 scene_id、character_ids
      （按「画面描述里提到了哪个场景名 / 人物名」推断，推断不出就留空——不瞎猜）
    * 旧 shot 的 index / scene / narration / duration / motion / voiced 全部保留，
      另外补 shot_id（=旧 index 一致的编号）、image_prompt（=scene）。
    """
    if not isinstance(story, dict):
        raise SchemaError("story 不是对象。")
    changed = False
    story = dict(story)

    for key, default in (("title", "未命名故事"), ("logline", ""), ("keywords", ""),
                         ("generated_at", ""), ("model", ""), ("style", "")):
        if key not in story:
            story[key] = default
            changed = True

    chars = normalize_characters(story.get("characters") or [])
    scenes = normalize_scenes(story.get("scenes") or [])
    if chars != (story.get("characters") or []):
        story["characters"] = chars
        changed = True
    if scenes != (story.get("scenes") or []):
        story["scenes"] = scenes
        changed = True
    story.setdefault("characters", chars)
    story.setdefault("scenes", scenes)
    # 兼容旧卡字段：确保 name / look 仍在
    for card in story["characters"]:
        card.setdefault("name", card.get("character_id", ""))
        card.setdefault("look", "")
    for card in story["scenes"]:
        card.setdefault("name", card.get("scene_id", ""))
        card.setdefault("look", "")

    raw_shots = [s for s in _list(story.get("shots")) if isinstance(s, dict)]
    total = len(raw_shots)
    scene_names = {s.get("name"): s.get("scene_id") for s in story["scenes"] if s.get("name")}
    char_names = {c.get("name"): c.get("character_id") for c in story["characters"] if c.get("name")}

    shots = []
    for i, raw in enumerate(raw_shots, 1):
        scene_text = _text(_pick(raw, "image_prompt", "scene", "画面", default=""), 600)
        narration = _text(_pick(raw, "narration", default=""), 200)
        voiced = _bool(_pick(raw, "voiced", default=bool(narration)), bool(narration))
        if not voiced:
            narration = ""
        motion = _text(_pick(raw, "motion", default="static"))
        # 旧数据没有 1.5~6 秒限制：能读出数字就原样保留，读不出才用默认时长
        duration = raw.get("duration")
        try:
            duration = round(float(duration), 3) if str(duration).strip() else 2.5
        except (TypeError, ValueError):
            duration = 2.5
        scene_id = _text(raw.get("scene_id"))
        if not scene_id:
            # 按名字包含关系推断（只在唯一命中时采用）
            hits = [sid for name, sid in scene_names.items() if name and name in scene_text]
            scene_id = hits[0] if len(hits) == 1 else ""
        character_ids = _str_list(raw.get("character_ids"))
        if not character_ids:
            character_ids = [cid for name, cid in char_names.items() if name and name in scene_text]
        beat = _text(raw.get("beat")) or _beat_for_index(i, total)
        shot = StoryboardShot(
            shot_id=_text(raw.get("shot_id")) or f"s{i:03d}",
            script_segment_id=_text(raw.get("script_segment_id")) or f"seg{i:03d}",
            scene_id=scene_id,
            character_ids=character_ids,
            image_prompt=scene_text or narration,
            motion=motion if motion in MOTION_MODES else "static",
            duration=duration,
            voiced=voiced,
            narration=narration,
            transition=_text(raw.get("transition")) or "cut",
            act=_text(raw.get("act")),
            beat=beat,
        )
        upgraded = shot.to_dict()
        for key, value in raw.items():
            upgraded.setdefault(key, value)
        # 旧字段强制保留且以原值为准
        upgraded.update({k: raw[k] for k in ("index", "scene", "narration",
                                             "motion", "voiced", "zoom", "transition")
                         if k in raw})
        # 旧时长原样保留（旧版没有 1.5~6 秒限制，不能因为升级改掉节奏）
        if "duration" in raw and str(raw.get("duration")).strip():
            upgraded["duration"] = duration
        upgraded["index"] = _int(raw.get("index"), i) or i
        shots.append(upgraded)
    if shots != raw_shots:
        story["shots"] = shots
        changed = True
    story.setdefault("shots", shots)

    # ---- 阶段数据 ----
    if not isinstance(story.get("concepts"), list):
        story["concepts"] = []
        changed = True
    plan_raw = story.get("plan")
    if not isinstance(plan_raw, dict) or not plan_raw:
        plan = {
            "theme": story.get("keywords", ""),
            "background": "",
            "core_conflict": "",
            "motivation": "",
            "reversal": "",
            "hook": "",
            "ending": "",
            "ending_type": "closed",
            "acts": [{"act": beat, "start": start, "end": end, "summary": ""}
                     for beat, start, end in _stage_ranges(total)],
        }
        story["plan"] = plan
        changed = True
    else:
        plan = story["plan"]
        acts = plan.get("acts")
        if not isinstance(acts, list) or not acts:
            plan["acts"] = [{"act": beat, "start": start, "end": end, "summary": ""}
                            for beat, start, end in _stage_ranges(total)]
            changed = True

    script = story.get("script")
    if not isinstance(script, list) or not script:
        # 旧数据没有剧本段：每个镜头生成一段（保留 segment_id = seg{i} 的对应关系）
        story["script"] = [{
            "segment_id": f"seg{i:03d}",
            "scene_id": s.get("scene_id", ""),
            "character_ids": list(s.get("character_ids") or []),
            "visual": s.get("image_prompt", ""),
            "narration": s.get("narration", ""),
            "dialogue": [],
            "emotion": "",
            "duration_hint": _float(s.get("duration"), 0.0),
            "act": "",
        } for i, s in enumerate(shots, 1)]
        changed = True
        for s, index in zip(story["shots"], range(1, len(shots) + 1)):
            if not s.get("script_segment_id"):
                s["script_segment_id"] = f"seg{index:03d}"
                changed = True

    pacing = story.get("pacing")
    if not isinstance(pacing, dict) or not pacing:
        story["pacing"] = {
            "target_seconds": round(sum(_float(s.get("duration"), 0.0) for s in shots), 2),
            "shot_count": len(shots),
            "min_seconds": MIN_SHOT_DURATION,
            "max_seconds": MAX_SHOT_DURATION,
            "weights": dict(DEFAULT_WEIGHTS),
        }
        changed = True

    quality = story.get("quality")
    if quality is not None and not isinstance(quality, dict):
        story["quality"] = None
        changed = True

    if not isinstance(story.get("versions"), list):
        story["versions"] = []
        changed = True
    if not isinstance(story.get("active_version"), str):
        story["active_version"] = ""
        changed = True
    if not isinstance(story.get("stale"), dict):
        story["stale"] = {}
        changed = True
    if _int(story.get("schema_version")) != SCHEMA_VERSION:
        story["schema_version"] = SCHEMA_VERSION
        changed = True
    if "generated_at" in story and not story["generated_at"]:
        from datetime import datetime
        story["generated_at"] = datetime.now().isoformat(timespec="seconds")
        changed = True
    golden = story.get("golden_topic")          # 固定质量测试题材标记（保留）
    if golden is not None and not isinstance(golden, str):
        story["golden_topic"] = ""
        changed = True
    return story, changed


def story_shot_ids(story: dict) -> list[str]:
    return [_text(s.get("shot_id")) for s in _list(story.get("shots")) if isinstance(s, dict)]


__all__ = [
    "SCHEMA_VERSION", "SchemaError", "StoryConcept", "CharacterProfile", "SceneProfile",
    "ActBeat", "Conflict", "Foreshadow", "StoryPlan", "ScriptSegment", "StoryboardShot",
    "AudioSegment", "QualityIssue", "QualityReport", "SCORE_WEIGHTS", "SCORE_LABELS",
    "VETO_CODES", "GRADE_LABELS", "BEAT_TIERS", "ENDINGS", "REVERSAL_TYPES",
    "MIN_SHOT_DURATION", "MAX_SHOT_DURATION", "TOTAL_DURATION_TOLERANCE",
    "DEFAULT_WEIGHTS", "grade_for", "content_hash", "shot_content_hash", "slug",
    "normalize_concepts", "normalize_plan", "normalize_characters", "normalize_scenes",
    "normalize_script", "normalize_shots", "normalize_quality", "allocate_shot_ids",
    "upgrade_story", "story_shot_ids",
]
