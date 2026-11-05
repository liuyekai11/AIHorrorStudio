"""AI 调用日志（V2.2）：每次模型调用记一条 JSONL，方便事后排查与费用估算。

文件：~/.ai_horror_studio/logs/calls-YYYYMMDD.jsonl
字段：ts / stage / slot / model / prompt_chars / max_tokens / temperature /
      elapsed_s / finish_reason / usage / ok / error / attempt

**永远不写 API Key、不写完整的 request headers、不写完整 prompt 正文**
（prompt 只记字数，防止把密钥或隐私内容带进日志）。
日志写失败不影响主流程。
"""
import json
import threading
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".ai_horror_studio" / "logs"
_lock = threading.Lock()


def _today() -> Path:
    return LOG_DIR / f"calls-{datetime.now():%Y%m%d}.jsonl"


def record(entry: dict, path: Path | None = None) -> bool:
    """追加一条日志。返回是否写入成功。"""
    if not isinstance(entry, dict):
        return False
    row = {"ts": datetime.now().isoformat(timespec="seconds"), **entry}
    target = Path(path) if path else _today()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False)
        with _lock:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return True
    except OSError:
        return False


def read_recent(limit: int = 50, path: Path | None = None) -> list[dict]:
    """读最近的调用记录（界面「调用日志」用）。坏行跳过。"""
    target = Path(path) if path else _today()
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out
