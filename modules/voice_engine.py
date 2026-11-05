"""AI 配音引擎（V1.3）：把每个分镜的旁白变成语音。

接口：/v1/audio/speech（硅基流动），模型 FunAudioLLM/CosyVoice2-0.5B，
返回原始音频字节（默认 mp3），直接写文件。

单镜头合成 + 拼接在 media_tools.concat_audio 里完成：
配音本身就比镜头长时会被截断到镜头时长，保证音画同步。
"""
from pathlib import Path

from modules import sf_config
from modules.sf_http import SFClient, SFError

DEFAULT_TIMEOUT = 120
DEFAULT_SPEED = 1.0
MAX_CHARS = 300

# CosyVoice2 在 input 里 <|endofprompt|> 之前可以写“说话风格”，之后才是正文
STYLE_HINT = sf_config.STYLE_HINT


def build_input(text: str, style: str = STYLE_HINT) -> str:
    """拼出 CosyVoice2 的 input：风格指令 + 分隔符 + 正文。"""
    text = (text or "").strip()
    if not text:
        raise SFError("该分镜没有旁白文本，无法配音。")
    if len(text) > MAX_CHARS:
        raise SFError(f"旁白过长（{len(text)} 字），配音接口单次上限约 {MAX_CHARS} 字。")
    style = (style or "").strip()
    if not style:
        return text
    return f"{style}<|endofprompt|>{text}"


def voice_id(model: str, voice: str) -> str:
    """音色参数格式：model:voicename。已经带前缀时原样返回。"""
    voice = (voice or sf_config.DEFAULT_VOICE).strip()
    if ":" in voice:
        return voice
    return f"{model}:{voice}"


def audio_suffix(fmt: str) -> str:
    fmt = (fmt or "mp3").lower()
    return "." + (fmt if fmt in ("mp3", "wav", "opus", "pcm") else "mp3")


class VoiceEngine(SFClient):
    def __init__(self, config: dict | None = None, bytes_transport=None,
                 timeout: int = DEFAULT_TIMEOUT):
        super().__init__(config=config, bytes_transport=bytes_transport)
        self.timeout = timeout

    @property
    def model(self) -> str:
        return sf_config.TTS_MODEL

    @property
    def voice(self) -> str:
        return self.config.get("voice") or sf_config.DEFAULT_VOICE

    @property
    def style(self) -> str:
        """配音风格指令。config["voice_style"] 是题材预设名或 "auto"（调用方已解析好）。"""
        key = self.config.get("voice_style") or "default"
        return sf_config.style_for(key)

    @property
    def default_speed(self) -> float:
        try:
            return sf_config._clamp_speed(self.config.get("voice_speed",
                                                          sf_config.DEFAULT_VOICE_SPEED))
        except (TypeError, ValueError):
            return sf_config.DEFAULT_VOICE_SPEED

    # ------------------------------------------------------------------
    def synthesize(self, text: str, speed: float | None = None,
                   fmt: str = "mp3", style: str | None = None) -> bytes:
        if speed is None:
            speed = self.default_speed
        if style is None:
            style = self.style
        payload = {
            "model": self.model,
            "input": build_input(text, style),
            "voice": voice_id(self.model, self.voice),
            "response_format": fmt,
            "speed": max(0.25, min(4.0, float(speed))),
        }
        data = self._call_bytes("/audio/speech", payload, self.timeout)
        if not data:
            raise SFError("配音服务返回了空音频，请稍后重试。")
        return data

    def synthesize_to_file(self, text: str, target, speed: float | None = None,
                           fmt: str = "wav") -> Path:
        """合成一段旁白并写到 target（默认 wav，便于后续精确拼接）。"""
        target = Path(target)
        data = self.synthesize(text, speed=speed, fmt=fmt)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if target.stat().st_size == 0:
            raise SFError("配音文件为空，请重试。")
        return target

    def test_connection(self) -> str:
        """用一句极短的话验证 Key 与音色是否可用（会产生一次很短的计费）。"""
        data = self.synthesize("测试", speed=1.0, fmt="mp3")
        return (f"配音连接成功（{self.model.split('/')[-1]} · {self.voice} · "
                f"{self.default_speed:g}x），返回音频 {len(data)} 字节")
