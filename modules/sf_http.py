"""硅基流动网络层：出图与配音共用的 HTTP 封装。

与 story_engine 一样只用标准库，且传输函数可以注入，单元测试不联网、不花钱。

两种响应形态：
* 出图  POST /v1/images/generations  → JSON（图片以临时 URL 返回，需在 1 小时内下载）
* 配音  POST /v1/audio/speech        → 二进制音频（mp3 / wav ...），并带 X-Siliconcloud-Trace-Id
"""
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

from modules import ai_config, sf_config


class SFError(Exception):
    """硅基流动调用失败，message 可直接展示给用户。"""


# ----------------------------------------------------------------------
# 错误分类
# ----------------------------------------------------------------------
def friendly_http_error(code: int, detail: str, api_key: str = "") -> str:
    detail = ai_config.scrub(detail or "", api_key)
    table = {
        400: "请求参数有误",
        401: "API Key 无效或已失效，请在「AI 设置」中重新填写",
        402: "账户余额不足，请到 cloud.siliconflow.cn 充值",
        403: "该 Key 没有调用此模型的权限",
        404: "接口不存在，请检查版本或网络",
        429: "请求过于频繁或额度用尽，请稍后再试",
        500: "硅基流动服务异常，请稍后重试",
        503: "模型服务繁忙，请稍后重试",
        504: "模型服务超时，请稍后重试",
    }
    head = table.get(code, f"请求失败（HTTP {code}）")
    return f"{head}。{detail}".strip()


def _error_detail(raw: bytes) -> str:
    """从错误响应体里尽量提取可读信息（可能是 JSON，也可能只是字符串）。"""
    text = (raw or b"").decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:300]
    if isinstance(data, dict):
        for key in ("message", "error", "msg", "data"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
            if isinstance(value, dict):
                inner = value.get("message")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()[:300]
    return text[:300]


def _wrap_network_error(exc: BaseException, timeout: int) -> SFError:
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
            return SFError(f"请求超时（{timeout} 秒），模型繁忙时可适当调大超时。")
        return SFError(f"无法连接硅基流动（{reason}）。请检查网络或代理设置。")
    if isinstance(exc, socket.timeout):
        return SFError(f"请求超时（{timeout} 秒），请重试。")
    return SFError(f"网络请求失败：{exc}")


# ----------------------------------------------------------------------
# 传输函数（可注入）
# ----------------------------------------------------------------------
def post_json(url: str, headers: dict, payload: dict, timeout: int,
              api_key: str = "") -> dict:
    """POST JSON，返回解析后的 JSON。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SFError(friendly_http_error(exc.code, _error_detail(exc.read()), api_key)) from exc
    except (urllib.error.URLError, socket.timeout) as exc:
        raise _wrap_network_error(exc, timeout) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SFError("服务器返回的不是有效 JSON，请稍后重试。") from exc


def post_bytes(url: str, headers: dict, payload: dict, timeout: int,
               api_key: str = "") -> bytes:
    """POST JSON，返回原始二进制（配音用）。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        raise SFError(friendly_http_error(exc.code, _error_detail(exc.read()), api_key)) from exc
    except (urllib.error.URLError, socket.timeout) as exc:
        raise _wrap_network_error(exc, timeout) from exc
    if not data:
        raise SFError("服务器返回了空音频，请重试。")
    return data


def download(url: str, target, timeout: int = 120) -> bytes:
    """下载出图 URL（有效期约 1 小时）并写入 target。"""
    target = Path(target)
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Horror-Studio"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        raise SFError(f"下载生成图片失败（HTTP {exc.code}），链接可能已过期。") from exc
    except (urllib.error.URLError, socket.timeout) as exc:
        raise SFError(f"下载生成图片失败：{getattr(exc, 'reason', exc)}") from exc
    if not data:
        raise SFError("下载到的图片为空。")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


# ----------------------------------------------------------------------
# 公共基类
# ----------------------------------------------------------------------
class SFClient:
    def __init__(self, config: dict | None = None, json_transport=None,
                 bytes_transport=None, downloader=None):
        self.config = config if config is not None else sf_config.load_config()
        self.json_transport = json_transport or post_json
        self.bytes_transport = bytes_transport or post_bytes
        self.downloader = downloader or download

    @property
    def api_key(self) -> str:
        return (self.config.get("api_key") or "").strip()

    @property
    def base_url(self) -> str:
        return sf_config.DEFAULT_BASE_URL.rstrip("/")

    def _headers(self) -> dict:
        if not self.api_key:
            raise SFError("还没有配置硅基流动 API Key。请点「AI 设置」填写，"
                          "或设置环境变量 SILICONFLOW_API_KEY。")
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _call_json(self, path: str, payload: dict, timeout: int) -> dict:
        headers = self._headers()
        return self.json_transport(f"{self.base_url}{path}", headers, payload,
                                   timeout, self.api_key)

    def _call_bytes(self, path: str, payload: dict, timeout: int) -> bytes:
        headers = self._headers()
        return self.bytes_transport(f"{self.base_url}{path}", headers, payload,
                                    timeout, self.api_key)
