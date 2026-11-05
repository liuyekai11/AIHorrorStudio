"""媒体工具：用 FFmpeg 完成图片 / 音频的尺寸与时长处理（纯标准库）。

用于 AI 出图与 AI 配音的收尾：
* normalize_image   把任意尺寸的出图裁切 / 缩放成竖屏（1080x1920 等）
* audio_duration    读取音频时长（ffprobe）
* concat_audio      把逐镜头配音拼成一条旁白音轨，按镜头起点对齐
* write_silence     生成与全片等长的静音 WAV（没有旁白时也保证音轨长度）
"""
import re
import subprocess
import wave
from pathlib import Path

from modules.ffmpeg_locator import find_ffmpeg


class MediaError(Exception):
    """媒体处理失败，界面层捕获后提示。"""


def _ffmpeg_bin() -> str:
    path = find_ffmpeg()
    if not path:
        raise MediaError("找不到 FFmpeg，无法处理图片 / 音频。")
    return path


def _ffprobe(ffmpeg: str) -> str:
    probe = Path(ffmpeg).with_name("ffprobe.exe")
    return str(probe) if probe.exists() else "ffprobe"


def _run(cmd: list[str], what: str):
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise MediaError(f"{what}失败：\n" + (result.stderr[-2000:] or "未知错误"))


# ----------------------------------------------------------------------
def normalize_image(source: Path, target: Path, width: int, height: int,
                    fit: str = "cover", allow_upscale: bool = False) -> Path:
    """把图片适配到 width x height（保持比例，不拉伸）。

    fit="cover"   铺满并居中裁切；fit="contain" 完整显示并补黑边。
    allow_upscale=False 时源图小于目标就**不放大**，只补边/裁切——
    出图只有 720×1280 却硬拉到 1080×1920 只会更糊，放大交给渲染端处理。

    source 与 target 可以是同一个文件：FFmpeg 不允许读写同一路径，
    这时先输出到同目录的临时文件，成功后再替换。
    """
    ffmpeg = _ffmpeg_bin()
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    in_place = source.resolve() == target.resolve()
    output = target.with_name(f".{target.stem}_norm{target.suffix}") if in_place else target
    w, h = int(width), int(height)
    # 不放大：先按「不放大」的 constrain 缩到不超过目标，再 cover 裁切 / contain 补边
    if fit == "contain":
        # 完整显示：大的等比缩小，小的补黑边（不放大）
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
    else:
        # 铺满：先缩到「不放大时最大能盖住画幅」的尺寸，再居中裁切。
        # 源图小于画幅时不放大，直接居中放上去并把边缘补满（比拉糊再锐化好看）
        # 注意：先 pad 再 crop。如果先 crop 成宽高不匹配的尺寸，pad 会拒绝
        # （"Padded dimensions cannot be smaller than input dimensions"）。
        cover_w = f"min(iw\\,max({w}\\,{h}*iw/ih))"
        vf = (f"scale=w='{cover_w}':h=-2,"
              f"pad=w=max({w}\\,iw):h=max({h}\\,ih):x=(ow-iw)/2:y=(oh-ih)/2:color=black,"
              f"crop={w}:{h},setsar=1")
    try:
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
              "-vf", vf, "-frames:v", "1", str(output)],
             "图片尺寸调整")
        if not output.exists() or output.stat().st_size == 0:
            raise MediaError("图片尺寸调整后没有生成有效文件。")
        if in_place:
            output.replace(target)
    except Exception:
        if in_place and output.exists():
            output.unlink(missing_ok=True)
        raise
    return target


# ----------------------------------------------------------------------
def audio_duration(path: Path) -> float:
    """读取音频时长（秒）。"""
    ffmpeg = _ffmpeg_bin()
    result = subprocess.run(
        [_ffprobe(ffmpeg), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    match = re.search(r"([\d.]+)", result.stdout or "")
    if not match:
        raise MediaError(f"无法读取音频时长：{Path(path).name}")
    return round(float(match.group(1)), 3)


LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def loudnorm_filter() -> str:
    """成片 / 音轨统一响度（短视频平台常用的 -16 LUFS）。"""
    return LOUDNORM


def trim_silence(source: Path, target: Path | None = None,
                 threshold_db: float = -45.0, keep_ms: int = 60) -> Path:
    """裁掉配音首尾的静音，只保留 keep_ms 的气口（不改动中间句间停顿）。

    TTS 经常在句尾拖出 1 秒以上的静音，如果不裁，配音驱动时会白白多出
    一截死寂。这里只裁首尾：先裁头，再反转、裁头、反转回来。
    target 为 None 时原地替换。
    """
    ffmpeg = _ffmpeg_bin()
    source = Path(source)
    target = Path(target) if target else source
    in_place = source.resolve() == target.resolve()
    output = target.with_name(f".{target.stem}_trim{target.suffix}") if in_place else target
    output.parent.mkdir(parents=True, exist_ok=True)
    one_side = (f"silenceremove=start_periods=1:start_duration=0:"
                f"start_threshold={threshold_db:g}dB:detection=peak")
    vf = f"{one_side},areverse,{one_side},areverse"
    try:
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
              "-af", vf, str(output)], "配音静音裁剪")
        if not output.exists() or output.stat().st_size == 0:
            # 全静音的极端情况：保留原文件，不要产出空音频
            if in_place and output.exists():
                output.unlink(missing_ok=True)
            return source
        if in_place:
            output.replace(target)
    except Exception:
        if in_place and output.exists():
            output.unlink(missing_ok=True)
        raise
    return target


def _wav_params(path: Path) -> tuple[int, int, int]:
    try:
        with wave.open(str(path), "rb") as f:
            return f.getframerate(), f.getnchannels(), f.getsampwidth()
    except (wave.Error, EOFError) as exc:
        raise MediaError(f"不是有效的 WAV 文件：{Path(path).name}") from exc


def write_silence(path: Path, seconds: float, like=None) -> Path:
    """生成静音 WAV。给了 like 时沿用该 WAV 的采样率 / 声道。"""
    rate, channels, sampwidth = (44100, 1, 2)
    if like:
        rate, channels, sampwidth = _wav_params(Path(like))
    frames = max(1, int(round(seconds * rate)))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(sampwidth)
        f.setframerate(rate)
        f.writeframes(b"\x00" * frames * channels * sampwidth)
    return path


def concat_audio(segments: list[tuple[Path, float, float]], output: Path,
                 total: float, offset_ms: int = 0) -> Path:
    """把逐镜头配音按镜头起点对齐，拼成一条旁白音轨。

    segments: [(wav 路径, 该镜头起点秒, 该镜头时长秒), ...]
    total:    全片总时长（输出音轨长度）
    offset_ms: 每段配音在镜头内额外的起始留白（毫秒）。
               fit_durations_to_voice 会把镜头时长设为 offset+配音长，
               这里同样加 offset，配音正好完整放下且稍晚进入。
    """
    segments = list(segments)
    if not segments:
        raise MediaError("没有可拼接的配音片段。")
    ffmpeg = _ffmpeg_bin()
    reference = segments[0][0]
    rate, channels, _ = _wav_params(Path(reference))
    target_total = round(max(float(total),
                             max(seg[1] + seg[2] for seg in segments)), 3)
    offset_ms = max(0, int(offset_ms))

    # 每个片段按“镜头起点 + 镜头内偏移”延迟后混流，再整体截断到全片长度。
    # 不用 concat：concat 要求每段长度精确，且 apad 会把 padding 计入时长。
    parts, labels = [], []
    for i, (path, start, duration) in enumerate(segments):
        delay_ms = int(round(max(0.0, float(start)) * 1000)) + offset_ms
        parts.append(f"[{i}:a]aresample={rate},"
                     f"atrim=duration={max(0.05, float(duration)):.3f},"
                     f"asetpts=PTS-STARTPTS,"
                     f"adelay=delays={delay_ms}:all=1[p{i}]")
        labels.append(f"[p{i}]")
    if len(labels) == 1:
        mixed = labels[0]
    else:
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:"
                     f"duration=longest:normalize=0[aall]")
        mixed = "[aall]"
    # 整条音轨统一响度，否则不同音色的配音拼在一起忽大忽小
    parts.append(f"{mixed}apad=whole_dur={target_total:.3f},{LOUDNORM}[aout]")

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for path, _start, _dur in segments:
        cmd += ["-i", str(path)]
    cmd += ["-filter_complex", ";".join(parts), "-map", "[aout]",
            "-ac", str(channels), "-ar", str(rate),
            "-c:a", "pcm_s16le", str(output)]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(cmd, "配音拼接")
    if not output.exists() or output.stat().st_size == 0:
        raise MediaError("配音拼接后没有生成有效音频文件。")
    return output


def make_placeholder(image: Path, width: int, height: int, label: str = "待配图") -> Path:
    """用纯色 + 文字生成占位图（出图失败时使用，保证渲染不中断）。"""
    ffmpeg = _ffmpeg_bin()
    image = Path(image)
    image.parent.mkdir(parents=True, exist_ok=True)
    escaped = label.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    font_file = "C\\:/Windows/Fonts/msyh.ttc"
    # 不支持 drawtext 的构建会直接失败，此时退回纯色
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"color=c=0x14161d:s={width}x{height}:d=1",
           "-vf", (f"drawtext=fontfile='{font_file}':text='{escaped}':"
                   f"fontcolor=0xd9a441:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2"),
           "-frames:v", "1", str(image)]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0 or not image.exists():
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
              "-f", "lavfi", "-i", f"color=c=0x14161d:s={width}x{height}:d=1",
              "-frames:v", "1", str(image)], "占位图生成")
    return image
