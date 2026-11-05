"""定位 FFmpeg 可执行文件。

查找顺序：
1. 环境变量 FFMPEG_BIN（可直接指向 ffmpeg.exe 或 bin 目录）
2. 系统 PATH
3. Winget 安装目录
4. 常见安装目录
5. 软件目录下的 bin/ffmpeg.exe
找不到时返回 None，由界面提示用户，不抛异常。
"""
import os
import shutil
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

_EXE = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def find_ffprobe(ffmpeg: str | None) -> str | None:
    """由 ffmpeg 路径找到同目录的 ffprobe（注意 Windows 上可能是大写 .EXE）。"""
    if not ffmpeg:
        return None
    path = Path(ffmpeg)
    name = path.name.replace("ffmpeg", "ffprobe", 1)
    for candidate in (name, name.replace(".EXE", ".exe"), name.replace(".exe", ".EXE")):
        probe = path.with_name(candidate)
        if probe.is_file():
            return str(probe)
    return None


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_bin = os.environ.get("FFMPEG_BIN")
    if env_bin:
        p = Path(env_bin)
        dirs.append(p if p.suffix.lower() == ".exe" else p)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
        dirs.append(packages)
    dirs.extend([
        Path("C:/ffmpeg/bin"),
        Path("C:/Program Files/ffmpeg/bin"),
        Path("C:/Program Files (x86)/ffmpeg/bin"),
        APP_DIR / "bin",
        APP_DIR / "ffmpeg" / "bin",
    ])
    return dirs


def find_ffmpeg() -> str | None:
    env_bin = os.environ.get("FFMPEG_BIN")
    if env_bin:
        p = Path(env_bin)
        if p.is_file() and p.name.lower().startswith("ffmpeg"):
            return str(p)
        candidate = p / _EXE
        if candidate.is_file():
            return str(candidate)

    found = shutil.which("ffmpeg")
    if found:
        return found

    for d in _candidate_dirs():
        if not d.exists():
            continue
        direct = d / _EXE
        if direct.is_file():
            return str(direct)
        for hit in d.rglob(_EXE):
            return str(hit)
    return None


def find_ffmpeg_silent() -> str | None:
    """供 import 期间调用，异常时返回 None。"""
    try:
        return find_ffmpeg()
    except Exception:
        return None
