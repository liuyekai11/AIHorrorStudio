"""渲染引擎：把 shots 时间轴渲染成 MP4。

V1.1 变化：
- 每个镜头独立时长（不再统一秒数）
- 镜头级 zoom 运镜（in：缓慢推近 / out：缓慢拉远 / none：静止）
- 镜头级 transition（cut / fade：0.5s 黑场过渡）
- 时长按 fps 对齐帧数，保证 concat 精确
- 其余行为与 V1.0 一致：旁白、背景音乐循环、SRT 烧录、输出 mp4
"""
import re
import subprocess
from pathlib import Path

from modules.ffmpeg_locator import find_ffmpeg, find_ffprobe


class RenderError(Exception):
    """渲染失败，界面层捕获后展示 stderr。"""


class RenderEngine:
    ZOOM_RANGE = 0.12          # V2.1：运镜幅度 6% → 12%，静态图才有「在动」的感觉
    FADE_SECONDS = 0.5         # fade 过渡（黑场淡入淡出）总时长
    DISSOLVE_SECONDS = 0.4     # dissolve：每镜 0.2s 淡入 + 0.2s 淡出，比黑场快、更连贯
    FLASH_SECONDS = 0.07       # flash：每镜开头一击白闪
    # 调色预设：与 render 端 eq / colorbalance 一起决定「胶片感」
    GRADES = {
        "cold": {"eq": "eq=contrast=1.06:saturation=0.86:brightness=-0.02",
                 "balance": "colorbalance=bs=0.04:bm=0.02:rh=-0.03"},
        "warm": {"eq": "eq=contrast=1.05:saturation=0.92:brightness=-0.01",
                 "balance": "colorbalance=rs=0.03:rm=0.02:bh=-0.03"},
        "neutral": {"eq": "eq=contrast=1.03:saturation=0.95", "balance": ""},
    }

    def __init__(self, ffmpeg=None):
        self.ffmpeg = ffmpeg or find_ffmpeg()
        if not self.ffmpeg:
            raise RenderError(
                "找不到 FFmpeg。请安装 FFmpeg（可执行 winget install Gyan.FFmpeg）"
                "后重启本软件，或设置环境变量 FFMPEG_BIN 指向 ffmpeg.exe。"
            )

    # ------------------------------------------------------------------
    def _resolve(self, project: Path, relative) -> Path | None:
        if not relative:
            return None
        path = (Path(project) / relative).resolve()
        if not path.exists():
            raise RenderError(f"项目素材不存在：{path}")
        return path

    @staticmethod
    def _ass_escape_commas(style: str) -> str:
        """force_style 用逗号分隔；ASS 颜色里没有逗号，这里只是防御性转义。"""
        return style.replace("'", "")

    @staticmethod
    def _escape_filter_path(path: Path) -> str:
        value = str(path.resolve()).replace("\\", "/")
        value = value.replace(":", "\\:")
        value = value.replace("'", "\\'")
        value = value.replace(",", "\\,")
        value = value.replace("[", "\\[").replace("]", "\\]")
        return value

    # ------------------------------------------------------------------
    ZOOM_TO_MOTION = {"none": "static", "in": "push-in", "out": "pull-out"}

    def shot_motion(self, shot: dict) -> str:
        """镜头运镜：优先读新字段 motion，老项目回落到 zoom。"""
        motion = shot.get("motion")
        if motion in ("static", "push-in", "pull-out", "pan-left", "pan-right", "diag-in"):
            return motion
        return self.ZOOM_TO_MOTION.get(shot.get("zoom"), "static")

    def _zoompan_exprs(self, motion: str, duration: float, fps: int) -> tuple[str, str, str] | None:
        """按运镜返回 zoompan 的 (z, x, y) 表达式；static 返回 None（不加 zoompan）。

        on 是输出帧序号（从 0 开始）。平移 / 对角推的进度用 on/(frames-1)，
        保证最后一帧正好走完整段位移。
        """
        frames = max(1, int(round(duration * fps)))
        last = max(1, frames - 1)
        lo, hi = 1 - self.ZOOM_RANGE, 1 + self.ZOOM_RANGE
        step = self.ZOOM_RANGE / frames
        z_in = (f"'if(lte(on,1),{lo:.4f},"
                f"min(zoom+{step:.6f},{hi:.4f}))'")
        z_out = (f"'if(lte(on,1),{hi:.4f},"
                 f"max(zoom-{step:.6f},{lo:.4f}))'")
        z_fixed = f"{hi:.4f}"
        cx = "(iw-iw/zoom)/2"
        cy = "(ih-ih/zoom)/2"
        progress = f"(on/{last})"
        back = f"({last}-on)/{last}"
        if motion == "push-in":
            return z_in, f"'{cx}'", f"'{cy}'"
        if motion == "pull-out":
            return z_out, f"'{cx}'", f"'{cy}'"
        if motion == "pan-left":
            # 画面从右往左扫：窗口从最右移到最左
            return f"'{z_fixed}'", f"'(iw-iw/zoom)*{back}'", f"'{cy}'"
        if motion == "pan-right":
            return f"'{z_fixed}'", f"'(iw-iw/zoom)*{progress}'", f"'{cy}'"
        if motion == "diag-in":
            # 从左上往右下推近
            return (z_in,
                    f"'(iw-iw/zoom)*{progress}'",
                    f"'(ih-ih/zoom)*{progress}'")
        return None

    def _post_grade(self, settings: dict) -> list[str]:
        """V2.1 成片质感：调色 + 胶片颗粒 + 暗角 + 轻锐化。

        全部在 format=yuv420p 之前；grain=0 / vignette=False 时对应滤镜不出现。
        注意 colorbalance 的参数是 rs/gs/bs/rm/gm/bm/rh/gh/bh（没有 ms/hs）。
        """
        grade = self.GRADES.get(settings.get("grade", "cold"), self.GRADES["cold"])
        parts = [grade["eq"]]
        if grade["balance"]:
            parts.append(grade["balance"])
        try:
            grain = int(settings.get("grain", 3))
        except (TypeError, ValueError):
            grain = 3
        if grain > 0:
            parts.append(f"noise=c0s={min(10, grain)}:c0f=t+u")
        if settings.get("vignette", True):
            parts.append("vignette=PI/4.5")
        parts.append("unsharp=5:5:0.5")
        return parts

    @staticmethod
    def subtitle_style(height: int) -> str:
        """字幕样式：字号按画面高度算（竖屏 1080x1920 → 40），半透明底条 + 细描边。

        V2.2：64 号一行只放 9 个汉字、48 号在手机上仍偏大，统一压到 40 起
        （1080 宽一行约 13 字，常见旁白 2 行以内）；底条改得更透（H60），
        字幕整体下移贴近画面底边，少挡脸。
        WrapStyle=0 = 自动换行、长句按音节断行。
        """
        font_size = max(26, min(40, int(int(height) / 48)))
        margin_v = max(44, int(int(height) * 0.055))
        return (f"FontName=Microsoft YaHei,FontSize={font_size},PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,BorderStyle=3,Outline=2,Shadow=1,"
                f"BackColour=&H60000000,Alignment=2,MarginV={margin_v},WrapStyle=0")

    def _shot_filter(self, index: int, image: Path | None, shot: dict, settings: dict):
        """返回 (输入参数列表, 滤镜字符串)。

        image 为 None 时（V1.2 故事导入、尚未生成画面）输出纯黑场，
        时间轴上仍保留该镜头时长，旁白字幕照常烧录。
        """
        width = int(settings["width"])
        height = int(settings["height"])
        fps = int(settings["fps"])
        fit = settings.get("fit", "contain")
        frames = max(1, int(round(float(shot["duration"]) * fps)))
        if image is None:
            inputs = ["-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}"]
        else:
            inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(image)]

        if image is None:
            base = "format=yuv420p"
        elif fit == "cover":
            # V2.1：不再无条件放大到 2 倍（928×1664 的 AI 图放大到 2160×3840 纯属浪费）。
            # 只放大 1.25 倍，保证 zoompan 平移时窗口有足够像素可裁
            pre_w = int(width * 1.25) // 2 * 2
            pre_h = int(height * 1.25) // 2 * 2
            base = (f"scale={pre_w}:{pre_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                    f"crop={pre_w}:{pre_h}")
        else:
            base = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"setsar=1")

        motion = self.shot_motion(shot) if image is not None else "static"
        exprs = self._zoompan_exprs(motion, float(shot["duration"]), fps)
        chain = ""
        if exprs:
            z, x, y = exprs
            chain = (f"zoompan=z={z}:x={x}:y={y}"
                     f":d={frames}:s={width}x{height}:fps={fps}")

        parts = [base]
        if chain:
            parts.append(chain)
        parts.append("setsar=1")
        if image is not None:
            parts.extend(self._post_grade(settings))

        transition = shot.get("transition", "cut")
        duration = float(shot["duration"])
        if transition in ("fade", "dissolve", "flash"):
            if transition == "flash":
                d = min(self.FLASH_SECONDS, duration / 2)
                parts.append(f"fade=t=in:st=0:d={d:.3f}:color=white")
            else:
                total_fade = self.FADE_SECONDS if transition == "fade" else self.DISSOLVE_SECONDS
                d = min(total_fade / 2, duration / 2)
                end = max(0.0, duration - d)
                parts.append(f"fade=t=in:st=0:d={d:.3f}")
                parts.append(f"fade=t=out:st={end:.3f}:d={d:.3f}")
        parts.append("format=yuv420p")
        parts.append(f"trim=duration={float(shot['duration']):.3f}")
        parts.append("setpts=PTS-STARTPTS")
        filt = f"[{index}:v]" + ",".join(parts) + f"[v{index}]"
        return inputs, filt

    def _voice_track(self, data: dict):
        """逐镜头配音拼接出来的音轨路径（相对项目），没有则返回 None。"""
        track = data.get("voice_track")
        if track:
            return track
        return None

    # ------------------------------------------------------------------
    def build_command(self, data: dict, settings: dict, output: Path):
        project = Path(output).parent.parent
        # V1.2：没有图片的镜头（故事导入、画面待生成）按黑场渲染，不再整体拒绝
        shots = [s for s in data.get("shots", []) if s.get("image") or s.get("narration") or s.get("scene")]
        if not shots:
            raise RenderError("时间轴上没有镜头，请先导入图片或生成故事。")
        for shot in shots:
            duration = float(shot.get("duration", 0))
            if duration <= 0:
                raise RenderError("存在时长为 0 的镜头，请检查时间轴。")

        fps = int(settings["fps"])
        images = [self._resolve(project, s["image"]) if s.get("image") else None
                  for s in shots]

        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        filters = []
        for i, (image, shot) in enumerate(zip(images, shots)):
            inputs, filt = self._shot_filter(i, image, shot, settings)
            cmd += inputs
            filters.append(filt)

        n = len(shots)
        concat_in = "".join(f"[v{i}]" for i in range(n))
        filters.append(f"{concat_in}concat=n={n}:v=1:a=0[vout]")

        narration = self._resolve(project, data.get("narration"))
        # V1.3：没有整条旁白音轨时，用逐镜头 AI 配音片段（已按镜头起点拼接）
        voice_source = narration
        if narration is None:
            voice_source = self._resolve(project, self._voice_track(data))
        music = self._resolve(project, data.get("music"))
        subtitle = self._resolve(project, data.get("subtitle"))

        audio_indexes = {}
        if voice_source:
            audio_indexes["narration"] = n
            cmd += ["-i", str(voice_source)]
        if music:
            audio_indexes["music"] = n + len(audio_indexes)
            cmd += ["-stream_loop", "-1", "-i", str(music)]
        # V2.1：没有 BGM 时自动垫一层低频 drone（手机外放听不到 55Hz 以下，
        # 所以再加一个 110Hz 谐波，否则「恐怖片底噪」根本传不到耳朵里）
        bed_drone = bool(settings.get("bed_drone", True)) and not music
        if bed_drone:
            audio_indexes["drone_low"] = n + len(audio_indexes)
            cmd += ["-f", "lavfi", "-i", "sine=frequency=55"]
            audio_indexes["drone_high"] = n + len(audio_indexes)
            cmd += ["-f", "lavfi", "-i", "sine=frequency=110"]

        total = round(sum(float(s["duration"]) for s in shots), 3)

        video_label = "[vout]"
        if subtitle:
            escaped = self._escape_filter_path(subtitle)
            style = self._ass_escape_commas(self.subtitle_style(settings["height"]))
            filters.append(
                f"[vout]subtitles='{escaped}':force_style='{style}'[vsub]"
            )
            video_label = "[vsub]"

        loudnorm = bool(settings.get("loudnorm", True))
        voice_chain = ""
        if voice_source:
            idx = audio_indexes["narration"]
            voice_chain = f"[{idx}:a]aresample=44100,volume=1.0"
            # 轻混响：给旁白一点空间感，避免干声贴脸
            voice_chain += ",aecho=0.8:0.6:40:0.12"
            if loudnorm:
                voice_chain += ",loudnorm=I=-16:TP=-1.5:LRA=11"
            voice_chain += "[narr]"
            filters.append(voice_chain)

        audio_labels = []
        if voice_source:
            audio_labels.append("[narr]")
        if music:
            idx = audio_indexes["music"]
            filters.append(
                f"[{idx}:a]aresample=44100,volume=0.45,"
                f"atrim=duration={total},asetpts=PTS-STARTPTS[mus]"
            )
            audio_labels.append("[mus]")
        if bed_drone:
            filters.append(
                f"[{audio_indexes['drone_low']}:a]aresample=44100,lowpass=f=160,"
                f"atrim=duration={total},asetpts=PTS-STARTPTS,volume=0.10[dlow]")
            filters.append(
                f"[{audio_indexes['drone_high']}:a]aresample=44100,"
                f"atrim=duration={total},asetpts=PTS-STARTPTS,volume=0.03[dhigh]")
            filters.append("[dlow][dhigh]amix=inputs=2:duration=first:normalize=0[drone]")
            audio_labels.append("[drone]")

        if voice_source and music:
            # V2.1：旁白出现时把 BGM 压下去（侧链压缩），旁白结束后自动回升
            filters.append("[narr]asplit=2[nmix][nsc]")
            filters.append(
                "[mus][nsc]sidechaincompress=threshold=0.04:ratio=6:"
                "attack=20:release=400[duck]")
            filters.append("[nmix][duck]amix=inputs=2:duration=first:normalize=0[aout]")
            audio_map = ["-map", "[aout]"]
        elif len(audio_labels) > 1:
            filters.append(f"{''.join(audio_labels)}"
                           f"amix=inputs={len(audio_labels)}:duration=longest:"
                           f"normalize=0:dropout_transition=0[aout]")
            audio_map = ["-map", "[aout]"]
        elif len(audio_labels) == 1:
            audio_map = ["-map", audio_labels[0]]
        else:
            audio_map = []
        if loudnorm and audio_map and audio_map[1] != "[narr]":
            # 没有旁白时（只有 BGM / drone）也统一响度，避免不同手机听起来忽大忽小
            filters.append(f"{audio_map[1]}loudnorm=I=-16:TP=-1.5:LRA=11,"
                           f"atrim=duration={total},asetpts=PTS-STARTPTS[afin]")
            audio_map = ["-map", "[afin]"]

        cmd += ["-filter_complex", ";".join(filters), "-map", video_label]
        cmd += audio_map
        cmd += ["-t", f"{total:.3f}", "-r", str(fps),
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p"]
        cmd += (["-c:a", "aac", "-b:a", "192k"] if audio_labels else ["-an"])
        cmd += ["-movflags", "+faststart", str(output)]
        return cmd

    def render(self, data: dict, settings: dict, output: Path) -> Path:
        output = Path(output)
        cmd = self.build_command(data, settings, output)
        output.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RenderError("FFmpeg 合成失败：\n" + (result.stderr[-4000:] or "未知错误"))
        if not output.exists() or output.stat().st_size == 0:
            raise RenderError("FFmpeg 未生成有效视频文件。")
        return output

    # ------------------------------------------------------------------
    @staticmethod
    def _ffprobe_path(ffmpeg: str) -> str:
        """由 ffmpeg 路径推出 ffprobe（Windows 下可执行文件后缀可能是大写 .EXE）。"""
        return find_ffprobe(ffmpeg) or str(Path(ffmpeg).with_name("ffprobe.exe"))

    def probe_duration(self, path: Path) -> float:
        """读取媒体时长（秒），用于校验。"""
        cmd = [self._ffprobe_path(self.ffmpeg), "-v", "error",
               "-show_entries", "format=duration", "-of", "default=nw=1",
               str(path)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=30)
            m = re.search(r"duration=([\d.]+)", result.stdout or "")
            if m:
                return round(float(m.group(1)), 3)
        except Exception:
            pass
        raise RenderError(f"无法读取媒体时长：{path}")
