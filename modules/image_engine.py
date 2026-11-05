"""AI 出图引擎（V1.3）：把分镜的 scene 描述变成实际画面。

流程
----
1. build_prompt(scene, style)         画面描述 → 出图提示词（补上画风与负面词）
2. ImageEngine.generate(prompt)       调 /v1/images/generations，返回临时 URL 列表
3. ImageEngine.download(url, target)  一小时内下载到项目 images/ 目录
4. generate_to_file(...)              串起来，并统一裁切成竖屏尺寸

设计要点
--------
* 网络层注入（json_transport / downloader），单元测试不联网、不花钱。
* 提交后 429 / 503 自动退避重试；失败信息直接可读，Key 会被打码。
* 返回的是临时 URL，必须立即下载——过期后 1 小时就拿不到了。
"""
import time
from pathlib import Path

from modules import sf_config, story_engine
from modules.sf_http import SFClient, SFError

DEFAULT_TIMEOUT = 180
RETRY_STATUS = ("HTTP 429", "HTTP 503", "HTTP 504", "超时")
MAX_RETRIES = 3

# V2.2 画风预设：统一走漫画风，保证同一故事里每张图像出自同一个画师。
# 画风后缀放在提示词最前面（模型对开头的风格词服从度最高），
# 后面依次接场景卡 / 角色卡 / 画面描述（见 build_prompt）。
STYLE_PRESETS = {
    "comic_dark": (
        "中式恐怖漫画风格，厚涂赛璐璐上色，粗黑描边，冷青与暗绿色调，"
        "高对比阴影，细腻的印刷网点质感，电影式分镜构图，竖屏"
    ),
    "comic_retro": (
        "老式港漫风格，浓墨重线，暖黄与暗红色调，颗粒感网点，"
        "强烈的黑白对比，电影式分镜构图，竖屏"
    ),
    "cinematic": (
        "恐怖电影剧照，电影感打光，自然色彩，真实质感，"
        "胶片颗粒感，细节丰富，高对比阴影，竖屏"
    ),
}
DEFAULT_STYLE = "comic_dark"
STYLE_LABELS = {
    "comic_dark": "暗黑漫画（默认）",
    "comic_retro": "复古港漫",
    "cinematic": "电影写实",
}
# 兼容旧代码（V2.1 及以前直接引用 STYLE_SUFFIX）
STYLE_SUFFIX = "，" + STYLE_PRESETS[DEFAULT_STYLE] + "，画面下方留出字幕空间"
# 画风默认值与负面词：漫画风要明确排除写实照片感，否则模型会跑偏
STYLE_NEGATIVE = "照片写实, 真人摄影, 3D渲染, 卡通低龄, 文字, 水印, 签名, logo, " \
                 "畸形手指, 多余肢体, 模糊, 低分辨率, 过曝, 拼接, 边框, 扭曲的脸"
NEGATIVE_PROMPT = STYLE_NEGATIVE   # V2.2 默认负面词（漫画风），保留旧名兼容

# 出图模型支持的尺寸（不同模型接受的范围不同，这里按模型挑最接近的竖屏尺寸）
SIZES = {
    "portrait": (1080, 1920),
    "square": (1024, 1024),
    "landscape": (1920, 1080),
}


def build_prompt(scene: str, style: str = "", extra: str = "") -> str:
    """把分镜画面描述扩成完整出图提示词。

    V2.2 顺序：画风（预设名或自定义风格串）→ 场景卡 / 角色卡 → 画面描述
    → 统一收尾（竖屏 / 字幕空间）。画风放最前面，一致性卡片放画面描述前面。
    """
    scene = (scene or "").strip().rstrip("。，,.")
    if not scene:
        raise SFError("该分镜没有画面描述，无法生成图片。")
    style = (style or "").strip().rstrip("。，,.")
    preset = STYLE_PRESETS.get(style, "") if style in STYLE_PRESETS else ""
    if preset:
        style_text = preset                       # 预设名 → 展开成完整风格串
    elif style:
        style_text = style                        # 自定义风格原样使用
    else:
        style_text = STYLE_PRESETS[DEFAULT_STYLE]
    parts = [style_text]
    if extra:                                     # 一致性卡片（角色 / 场景）
        parts.append(extra.strip().rstrip("。，,."))
    parts.append(scene)
    parts.append("画面下方留出字幕空间")
    return "，".join(parts)


def resolve_style(style: str = "") -> str:
    """把风格输入（预设名 / 空串 / 自定义串）解析成预设名或原样返回。"""
    style = (style or "").strip()
    return style if style in STYLE_PRESETS else (style or DEFAULT_STYLE)


def build_consistency_hint(story: dict | None, scene: str = "",
                           shot: dict | None = None) -> str:
    """出图用的一致性卡片：只带这一镜实际用到的角色与场景。

    V2.2：优先按 shot.character_ids / shot.scene_id 过滤（分镜阶段已保证引用
    存在），只把「这一镜里出现的人」的外貌塞进提示词——塞一堆不在场角色
    会让画面里凭空多出人来。没有引用信息时退回 V2.1 的名字匹配。
    """
    if not isinstance(story, dict):
        return ""
    chars = [c for c in (story.get("characters") or []) if isinstance(c, dict)]
    scenes = [s for s in (story.get("scenes") or []) if isinstance(s, dict)]
    if isinstance(shot, dict):
        want_chars = {str(c) for c in (shot.get("character_ids") or []) if c}
        want_scene = str(shot.get("scene_id") or "")
        if want_chars:
            picked = [c for c in chars if str(c.get("character_id") or "") in want_chars]
            if picked:
                chars = picked
        else:
            chars = []          # 这一镜没引用任何人：画面里不该凭空出现人物卡
        if want_scene:
            picked_scene = [s for s in scenes
                            if str(s.get("scene_id") or "") == want_scene]
            if picked_scene:
                scenes = picked_scene
    parts = []
    for card in chars[:3]:
        look = (card.get("look") or "").strip()
        if look:
            parts.append(f"角色（{card.get('name') or '主角'}）：{look}")
    for card in scenes[:2]:
        look = (card.get("look") or "").strip()
        if look:
            parts.append(f"场景：{look}")
    if not (chars or scenes):
        # 完全没有卡片可用：退回 V2.1 的按名字匹配
        return story_engine.build_consistency_hint(story, scene)
    return "；".join(parts)


def pick_size(width: int, height: int, model: str = "") -> str:
    """按项目画幅给出 'WxH' 尺寸字符串（只选模型官方支持的档位）。"""
    width, height = int(width), int(height)
    portrait = height > width * 1.25
    landscape = width > height * 1.25
    if model.startswith("Kwai-Kolors"):
        if portrait:
            return "720x1280"
        if landscape:
            return "1280x720"
        return "1024x1024"
    # Qwen-Image / Z-Image 系列
    if portrait:
        return "928x1664"
    if landscape:
        return "1664x928"
    return "1328x1328"


def parse_images(response: dict) -> list[str]:
    """从 /images/generations 响应里取出图片 URL。"""
    if not isinstance(response, dict):
        raise SFError("出图接口返回格式异常。")
    images = response.get("images") or response.get("data") or []
    urls = []
    for item in images:
        if isinstance(item, dict):
            url = item.get("url") or item.get("image_url")
            if url:
                urls.append(str(url))
        elif isinstance(item, str):
            urls.append(item)
    if not urls:
        raise SFError("出图接口没有返回图片（可能被内容审核拦截，换个画面描述试试）。")
    return urls


class ImageEngine(SFClient):
    def __init__(self, config: dict | None = None, json_transport=None,
                 downloader=None, timeout: int = DEFAULT_TIMEOUT):
        super().__init__(config=config, json_transport=json_transport,
                         downloader=downloader)
        self.timeout = timeout

    @property
    def model(self) -> str:
        return self.config.get("image_model") or sf_config.DEFAULT_IMAGE_MODEL

    # ------------------------------------------------------------------
    def generate(self, prompt: str, size: str | None = None,
                 negative_prompt: str = NEGATIVE_PROMPT, steps: int = 20,
                 seed: int | None = None) -> list[str]:
        """生成图片，返回临时 URL 列表（需立即下载）。"""
        prompt = (prompt or "").strip()
        if not prompt:
            raise SFError("提示词为空，无法出图。")
        payload = {
            "model": self.model,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "image_size": size or pick_size(720, 1280, self.model),
            "num_inference_steps": int(steps),
            "batch_size": 1,
        }
        if seed is not None:
            payload["seed"] = int(seed)

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                raw = self._call_json("/images/generations", payload, self.timeout)
                return parse_images(raw)
            except SFError as exc:
                last_error = exc
                message = str(exc)
                if attempt == MAX_RETRIES - 1 or not any(s in message for s in RETRY_STATUS):
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise last_error or SFError("出图失败。")

    def download(self, url: str, target) -> object:
        return self.downloader(url, target, self.timeout)

    def generate_to_file(self, scene: str, target, size: str | None = None,
                         style: str = "", seed: int | None = None,
                         extra: str = "") -> str:
        """一步到位：描述 → 提示词 → 出图 → 下载到 target。返回实际文件路径。

        style = 画风预设名或自定义风格串；extra = 一致性卡片（角色 / 场景外貌）。
        """
        prompt = build_prompt(scene, style, extra)
        urls = self.generate(prompt, size=size, seed=seed)
        # 返回的 URL 约 1 小时后过期，必须立刻下载；父目录可能还不存在
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        self.download(urls[0], target)
        return str(target)
