"""AI 服务配置：API Key 的保存与读取。

Key 只存在用户目录（不在项目目录里，避免随项目分享泄露）：
    ~/.ai_horror_studio/ai.json

优先级：环境变量 DEEPSEEK_API_KEY > 配置文件。
"""
import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".ai_horror_studio"
CONFIG_FILE = CONFIG_DIR / "ai.json"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
AVAILABLE_MODELS = ["deepseek-flash", "deepseek-v4-pro"]

ENV_KEY = "DEEPSEEK_API_KEY"


def load_config() -> dict:
    data = {"api_key": "", "base_url": DEFAULT_BASE_URL, "model": DEFAULT_MODEL}
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            data.update({k: v for k, v in saved.items()
                         if k in ("api_key", "base_url", "model") and isinstance(v, str)})
    except (OSError, json.JSONDecodeError):
        pass
    env_key = os.environ.get(ENV_KEY, "").strip()
    if env_key:
        data["api_key"] = env_key
        data["_from_env"] = True
    return data


def save_config(api_key: str, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({
        "api_key": (api_key or "").strip(),
        "base_url": base_url or DEFAULT_BASE_URL,
        "model": model or DEFAULT_MODEL,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        # Windows 上尽量把文件限制为当前用户可读写
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def mask_key(key: str) -> str:
    key = key or ""
    if len(key) <= 10:
        return "****" if key else ""
    return f"{key[:6]}…{key[-4:]}"


def scrub(text: str, key: str | None = None) -> str:
    """日志/错误信息里隐藏 API Key。"""
    text = str(text or "")
    if key:
        text = text.replace(key, mask_key(key))
    return text
