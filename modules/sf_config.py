"""硅基流动（SiliconFlow）API 配置：Key、模型、音色、语速。

与 DeepSeek 的 Key 分开存放，避免互相覆盖：
    ~/.ai_horror_studio/siliconflow.json

优先级：环境变量 SILICONFLOW_API_KEY > 配置文件。
出图模型 Kwai-Kolors/Kolors 当前免费；配音模型 FunAudioLLM/CosyVoice2-0.5B。
"""
import json
import os
import re
from pathlib import Path

CONFIG_FILE = Path.home() / ".ai_horror_studio" / "siliconflow.json"

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"

# 出图模型（Kolors 免费；Z-Image-Turbo 付费但质量更好，默认用它）
IMAGE_MODELS = [
    ("Kwai-Kolors/Kolors", "免费 · 快"),
    ("Tongyi-MAI/Z-Image-Turbo", "付费 · 质量更好（推荐）"),
    ("Qwen/Qwen-Image", "付费 · 擅长文字"),
]
# 默认 Z-Image-Turbo：原生竖屏 928×1664，比免费 Kolors 的 720×1280 清晰得多。
# 免费额度 / 试运行可在 AI 设置里切回 Kwai-Kolors/Kolors。
DEFAULT_IMAGE_MODEL = "Tongyi-MAI/Z-Image-Turbo"

# 配音模型 + 预置音色（FunAudioLLM/CosyVoice2-0.5B）
TTS_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
VOICES = [
    ("claire", "女声 · 温柔"),
    ("anna", "女声 · 沉稳"),
    ("bella", "女声 · 激情"),
    ("diana", "女声 · 欢快"),
    ("alex", "男声 · 沉稳"),
    ("benjamin", "男声 · 低沉"),
    ("charles", "男声 · 磁性"),
    ("david", "男声 · 欢快"),
]
DEFAULT_VOICE = "claire"

# 配音语速（CosyVoice2 接口范围 0.25~4.0，旁白常用 0.5~1.5）
VOICE_SPEEDS = [
    (0.5, "慢"),
    (0.75, "稍慢"),
    (0.9, "略慢"),
    (1.0, "标准"),
    (1.1, "略快"),
    (1.25, "稍快"),
    (1.5, "快"),
]
DEFAULT_VOICE_SPEED = 1.0

ENV_KEY = "SILICONFLOW_API_KEY"

# 通用的“恐怖旁白”配音风格提示（CosyVoice2 的 <|endofprompt|> 之前的指令）
STYLE_HINT = "用低沉、克制、略带颤抖的恐怖旁白语气朗读，语速稍慢，句尾留白。"

# 按题材细分的配音风格（story_engine.infer_style 的返回值 → 指令）
VOICE_STYLE_PRESETS = {
    "default": STYLE_HINT,
    "folk": "用略带方言口音、低沉沙哑的恐怖旁白语气朗读，语速稍慢，句与句之间留出停顿。",
    "urban": "用冷静、克制、几乎不带情绪的声音朗读，语速偏快，像在低声讲一件不愿提起的事。",
    "cosmic": "用缓慢、低沉、略带敬畏与颤抖的气声朗读，句尾拖长，像在念某种不该念出的东西。",
    "psych": "用温柔但压抑、时而轻声耳语的语气朗读，语速时快时慢，句尾留白。",
}


def style_for(key: str) -> str:
    """取某个题材的配音风格指令，未知题材回落到默认。"""
    return VOICE_STYLE_PRESETS.get(key or "default", STYLE_HINT)


def _clamp_speed(value) -> float:
    return round(max(0.25, min(4.0, float(value))), 2)


def speed_label(value: float) -> str:
    """1.25 → '稍快 · 1.25x'（界面上显示用）。"""
    value = _clamp_speed(value)
    for v, name in VOICE_SPEEDS:
        if abs(v - value) < 0.01:
            return f"{name} · {v:g}x"
    return f"{value:g}x"


def parse_speed(label: str) -> float:
    """'稍快 · 1.25x' / '1.25x' / '1.25' → 1.25（解析不了回默认）。"""
    match = re.search(r"([\d.]+)\s*x", str(label))
    if match:
        try:
            return _clamp_speed(match.group(1))
        except ValueError:
            pass
    try:
        return _clamp_speed(str(label).strip())
    except (TypeError, ValueError):
        return DEFAULT_VOICE_SPEED


def load_config() -> dict:
    data = {"api_key": "", "image_model": DEFAULT_IMAGE_MODEL, "voice": DEFAULT_VOICE,
            "voice_speed": DEFAULT_VOICE_SPEED, "voice_style": "auto",
            "image_style": "comic_dark"}       # V2.2 默认漫画风
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            data.update({k: v for k, v in saved.items()
                         if k in ("api_key", "image_model", "voice", "voice_style",
                                  "image_style")
                         and isinstance(v, str)})
            speed = saved.get("voice_speed")
            if isinstance(speed, (int, float)) and not isinstance(speed, bool):
                data["voice_speed"] = _clamp_speed(speed)
    except (OSError, json.JSONDecodeError):
        pass
    env_key = os.environ.get(ENV_KEY, "").strip()
    if env_key:
        data["api_key"] = env_key
        data["_from_env"] = True
    return data


def save_config(api_key: str, image_model: str = DEFAULT_IMAGE_MODEL,
                voice: str = DEFAULT_VOICE, voice_speed: float = DEFAULT_VOICE_SPEED,
                voice_style: str = "auto", image_style: str = "comic_dark"):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({
        "api_key": (api_key or "").strip(),
        "image_model": image_model or DEFAULT_IMAGE_MODEL,
        "voice": voice or DEFAULT_VOICE,
        "voice_speed": _clamp_speed(voice_speed),
        "voice_style": voice_style or "auto",
        "image_style": image_style or "comic_dark",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
