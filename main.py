"""AI Horror Studio V2.1 - 入口。

启动：python main.py  （或双击 start.bat）
"""
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))


def _report(exc: BaseException):
    """启动失败时写入日志并弹窗，避免双击后无声闪退。"""
    log = APP_DIR / "error.log"
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        log.write_text(detail, encoding="utf-8")
    except OSError:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "AI Horror Studio 启动失败",
            f"{exc}\n\n详细信息已写入：\n{log}")
        root.destroy()
    except Exception:
        print(detail)


if __name__ == "__main__":
    try:
        from modules.main_window import run
        run(APP_DIR)
    except Exception as exc:  # noqa: BLE001 - 启动阶段需要兜底
        _report(exc)
        sys.exit(1)
