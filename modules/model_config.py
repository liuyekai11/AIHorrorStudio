"""模型槽位 / Token 预算 / 推理参数（V2.2）。

所有模型名、max_tokens、temperature 集中在这里，代码里不写死。
优先级：显式传入的 config（例如 ai_config.load_config() 的用户设置）
        > ~/.ai_horror_studio/models.json 里的覆盖
        > 下面的默认值。

槽位（用户 2026-11-04 确认的分工）
----------------------------------
planner  deepseek-v4-pro   故事策划、导演分镜、质量审核
writer   deepseek-v4-pro   完整剧本
concept  deepseek-v4-pro   创意候选（与 planner 可分开调）
fast     deepseek-flash    创意候选兜底、出图提示词、辅助任务、JSON 修复

本机实测：两个模型都是推理模型，推理 token 计入 max_tokens；
预算不足会出现「空内容 + finish_reason=length」，调用方应把它当可重试错误。
"""
import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".ai_horror_studio" / "models.json"

# 6 个槽位 → 默认模型
DEFAULT_SLOTS = {
    "planner": "deepseek-v4-pro",
    "writer": "deepseek-v4-pro",
    "concept": "deepseek-v4-pro",
    "fast": "deepseek-flash",
}

# 每个槽位的默认调用参数（可在 models.json 里按槽位覆盖任意一项）
# planner 同时负责导演分镜：实测推理 token 吃掉一半以上预算，16384 不够 36 镜的完整
# JSON（2026-11-04 实测 finish_reason=length），默认抬到 32768；分镜阶段还会按镜数
# 再抬到更高（见 story_engine.SHOT_BUDGET）。
DEFAULT_PARAMS = {
    "planner": {"temperature": 1.0, "max_tokens": 32768, "timeout": 420},
    "writer": {"temperature": 1.0, "max_tokens": 24576, "timeout": 420},
    "concept": {"temperature": 1.1, "max_tokens": 8192, "timeout": 300},
    # fast 也负责出图提示词（一镜一条）：36 镜实测 4096 不够，按镜数抬预算
    # （见 story_engine.PROMPT_TOKENS_PER_SHOT）；这里把默认值也抬到 8192。
    "fast": {"temperature": 0.8, "max_tokens": 8192, "timeout": 120},
}

# 旧代码里的 config["model"] 视为「默认槽位」——保持 V2.1 行为不变
LEGACY_SLOT = "fast"
_PARAM_KEYS = ("temperature", "max_tokens", "timeout")


def load_overrides() -> dict:
    """读取 models.json：{"slots": {...}, "params": {"planner": {...}}}。读失败返回空。"""
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    result = {}
    slots = data.get("slots")
    if isinstance(slots, dict):
        result["slots"] = {k: str(v) for k, v in slots.items()
                           if k in DEFAULT_SLOTS and isinstance(v, str) and v.strip()}
    params = data.get("params")
    if isinstance(params, dict):
        clean = {}
        for slot, values in params.items():
            if slot not in DEFAULT_SLOTS or not isinstance(values, dict):
                continue
            clean[slot] = {k: v for k, v in values.items()
                           if k in _PARAM_KEYS and isinstance(v, (int, float))
                           and not isinstance(v, bool)}
        result["params"] = clean
    return result


def available_slots() -> tuple:
    return tuple(DEFAULT_SLOTS)


def model_for(slot: str, config: dict | None = None) -> str:
    """槽位 → 模型名。

    config 里有对应槽位键（如 "planner_model"）时优先；否则读 models.json；
    再否则用默认。旧配置只有 "model" 时，把它当作 LEGACY_SLOT 的模型。
    """
    config = config or {}
    key = f"{slot}_model"
    if isinstance(config.get(key), str) and config[key].strip():
        return config[key].strip()
    if slot == LEGACY_SLOT and isinstance(config.get("model"), str) and config["model"].strip():
        return config["model"].strip()
    overrides = load_overrides().get("slots", {})
    if overrides.get(slot):
        return overrides[slot]
    return DEFAULT_SLOTS.get(slot, DEFAULT_SLOTS[LEGACY_SLOT])


def params_for(slot: str, config: dict | None = None) -> dict:
    """槽位 → {temperature, max_tokens, timeout}。

    config 里可给 "params" 字典（{"planner": {...}, ...}）或直接的 "max_tokens"/
    "temperature" 覆盖；models.json 的 params 次之；最后是默认值。
    """
    config = config or {}
    result = dict(DEFAULT_PARAMS.get(slot, DEFAULT_PARAMS[LEGACY_SLOT]))
    result.update(load_overrides().get("params", {}).get(slot, {}))
    from_config = config.get("params")
    if isinstance(from_config, dict) and isinstance(from_config.get(slot), dict):
        result.update({k: v for k, v in from_config[slot].items()
                       if k in _PARAM_KEYS and isinstance(v, (int, float))})
    return result


def describe() -> dict:
    """给界面 / 日志用的完整槽位说明。"""
    return {
        slot: {"model": model_for(slot), **params_for(slot)}
        for slot in DEFAULT_SLOTS
    }
