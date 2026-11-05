"""缩略图 + 预览帧合成（纯标准库，Tk PhotoImage 实现）。

Tk 8.6 内置 PhotoImage 支持 PNG/BMP/GIF 解码，以及 copy -zoom/-subsample/
-crop 变换，足够做时间轴缩略图和预览合帧，不需要 Pillow。
如果环境里装了 Pillow，会自动使用它获得更好的缩放质量（可选）。

对外接口：
- ImageLoader(master).load(path) -> ImageRef | None
- make_thumbnail(path, target_h, master) -> Tk 图片名 | PhotoImage | None
- compose_frame(loader, path, w, h, fit) -> Tk 图片名 | None
    fit = "contain" 补黑边 | "cover" 裁切铺满
"""
from pathlib import Path

try:
    from PIL import Image, ImageTk  # type: ignore
    _HAS_PIL = True
except Exception:  # pragma: no cover - Pillow 为可选项
    Image = None
    ImageTk = None
    _HAS_PIL = False

MAX_DECODE_PIXELS = 3000
_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1) if _HAS_PIL else None


class ImageRef:
    """统一图片对象：PIL 图片或 Tk 图片名二选一。"""

    def __init__(self, tk=None, tk_name=None, pil_image=None):
        self.tk = tk
        self.tk_name = tk_name
        self.pil = pil_image
        self._w = self._h = None

    @property
    def width(self):
        self._measure()
        return self._w

    @property
    def height(self):
        self._measure()
        return self._h

    def _measure(self):
        if self._w is not None:
            return
        if self.pil is not None:
            self._w, self._h = self.pil.size
        elif self.tk and self.tk_name:
            try:
                self._w = int(self.tk.call("image", "width", self.tk_name))
                self._h = int(self.tk.call("image", "height", self.tk_name))
            except Exception:
                self._w = self._h = 0
        else:
            self._w = self._h = 0

    def to_tk(self, master):
        """返回可在 canvas.create_image 使用的对象；PIL 图转换后返回 PhotoImage。"""
        if self.pil is not None:
            return ImageTk.PhotoImage(self.pil, master=master)
        return self.tk_name

    def delete(self):
        if self.tk and self.tk_name:
            try:
                self.tk.call("image", "delete", self.tk_name)
            except Exception:
                pass
        self.tk_name = None


class ImageLoader:
    def __init__(self, master):
        self.master = master
        self.tk = master.tk
        self._cache: dict[str, ImageRef | None] = {}

    def load(self, path) -> ImageRef | None:
        key = str(Path(path).resolve())
        if key in self._cache:
            return self._cache[key]
        ref = self._load_uncached(key)
        self._cache[key] = ref
        return ref

    def _load_uncached(self, path: str) -> ImageRef | None:
        if _HAS_PIL:
            try:
                im = Image.open(path)
                im.load()
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                return ImageRef(pil_image=im)
            except Exception:
                pass
        try:
            name = self.tk.call("image", "create", "photo", "-file", path)
            ref = ImageRef(tk=self.tk, tk_name=name)
            if ref.width <= 0 or ref.height <= 0:
                ref.delete()
                return None
            biggest = max(ref.width, ref.height)
            if biggest > MAX_DECODE_PIXELS:
                factor = (biggest + MAX_DECODE_PIXELS - 1) // MAX_DECODE_PIXELS
                ref.delete()
                name = self.tk.call("image", "create", "photo", "-file", path,
                                    "-subsample", factor, factor)
                ref = ImageRef(tk=self.tk, tk_name=name)
            return ref
        except Exception:
            return None

    def release(self, path):
        key = str(Path(path).resolve())
        ref = self._cache.pop(key, None)
        if ref is not None:
            ref.delete()

    def clear(self):
        for ref in self._cache.values():
            if ref is not None:
                ref.delete()
        self._cache.clear()


def make_thumbnail(path, target_h: int, master):
    """时间轴缩略图。返回 PhotoImage（Pillow 路径）或 Tk 图片名（纯 Tk 路径）。"""
    path = Path(path)
    if not path.exists():
        return None
    if _HAS_PIL:
        try:
            with Image.open(path) as im:
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                ratio = target_h / im.height
                size = (max(1, int(im.width * ratio)), target_h)
                return ImageTk.PhotoImage(im.resize(size, _LANCZOS), master=master)
        except Exception:
            pass
    try:
        name = master.tk.call("image", "create", "photo", "-file", str(path))
        h = int(master.tk.call("image", "height", name))
        if h <= 0:
            master.tk.call("image", "delete", name)
            return None
        sub = max(1, round(h / target_h))
        if sub > 1:
            master.tk.call("image", "delete", name)
            name = master.tk.call("image", "create", "photo", "-file", str(path),
                                  "-subsample", sub, sub)
        return name
    except Exception:
        return None


def compose_frame(loader: ImageLoader, image_path, canvas_w: int, canvas_h: int,
                  fit: str = "contain") -> object | None:
    """把图片缩放/裁切到 canvas 尺寸，返回可直接 create_image 的对象。

    返回值：PIL 路径返回 PhotoImage；纯 Tk 路径返回图片名字符串。
    """
    src = loader.load(image_path)
    if src is None or src.width <= 0 or src.height <= 0:
        return None
    master = loader.master
    if _HAS_PIL and src.pil is not None:
        return _compose_pil(src.pil, canvas_w, canvas_h, fit, master)
    return _compose_tk(loader.tk, src, canvas_w, canvas_h, fit, master)


def _compose_pil(im, cw: int, ch: int, fit: str, master):
    sw, sh = im.size
    if fit == "cover":
        target_ratio = cw / ch
        if sw / sh > target_ratio:
            crop_w = int(sh * target_ratio)
            box = ((sw - crop_w) // 2, 0, (sw + crop_w) // 2, sh)
        else:
            crop_h = int(sw / target_ratio)
            box = (0, (sh - crop_h) // 2, sw, (sh + crop_h) // 2)
        im = im.crop(box).resize((cw, ch), _LANCZOS)
    else:
        scale = min(cw / sw, ch / sh)
        tw, th = max(1, int(sw * scale)), max(1, int(sh * scale))
        im = im.resize((tw, th), _LANCZOS)
        cw, ch = tw, th
    return ImageTk.PhotoImage(im, master=master)


def _compose_tk(tk, src: ImageRef, cw: int, ch: int, fit: str, master):
    sw, sh = src.width, src.height
    try:
        name = str(tk.call("image", "create", "photo"))
    except Exception:
        return None
    try:
        _place_tk(tk, name, src, cw, ch, fit)
    except Exception:
        try:
            tk.call("image", "delete", name)
        except Exception:
            pass
        return None
    return name


def _place_pil(im, cw, ch, fit, master):
    """返回缩放/裁切后的 PhotoImage。"""
    sw, sh = im.size
    if fit == "cover":
        target_ratio = cw / ch
        if sw / sh > target_ratio:
            crop_w = int(sh * target_ratio)
            box = ((sw - crop_w) // 2, 0, (sw + crop_w) // 2, sh)
        else:
            crop_h = int(sw / target_ratio)
            box = (0, (sh - crop_h) // 2, sw, (sh + crop_h) // 2)
        im = im.crop(box).resize((cw, ch), _LANCZOS)
    else:
        scale = min(cw / sw, ch / sh)
        tw, th = max(1, int(sw * scale)), max(1, int(sh * scale))
        im = im.resize((tw, th), _LANCZOS)
    return ImageTk.PhotoImage(im, master=master)


def _place_tk(tk, canvas, src: ImageRef, cw: int, ch: int, fit: str):
    sw, sh = src.width, src.height
    if fit == "cover":
        # 先按画布比例用 subsample 裁到接近画布尺寸，避免整张大图复制
        factor = max(1, int(min(sw / cw, sh / ch)))
        crop_w, crop_h = min(sw // factor, cw) * factor, min(sh // factor, ch) * factor
        left = ((sw // factor - crop_w // factor) // 2) * factor
        top = ((sh // factor - crop_h // factor) // 2) * factor
        small = tk.call("image", "create", "photo", "-width", max(1, crop_w // factor),
                        "-height", max(1, crop_h // factor))
        tk.call("image", "copy", src.tk_name, "-from", left, top, left + crop_w, top + crop_h,
                "-subsample", factor, factor, "-to", small)
        sw2 = int(tk.call("image", "width", small))
        sh2 = int(tk.call("image", "height", small))
        tk.call("image", "copy", small, "-to", canvas, (cw - sw2) // 2, (ch - sh2) // 2)
        tk.call("image", "delete", small)
        return

    scale = min(cw / sw, ch / sh)
    raw_tw = sw * scale
    if raw_tw <= sw:
        factor = max(1, int(round(sw / raw_tw)))
        small = tk.call("image", "create", "photo", "-width", max(1, sw // factor),
                        "-height", max(1, sh // factor))
        tk.call("image", "copy", src.tk_name, "-subsample", factor, factor, "-to", small)
    else:
        zoom = max(1, int(round(raw_tw / sw)))
        small = tk.call("image", "create", "photo", "-width", sw * zoom, "-height", sh * zoom)
        tk.call("image", "copy", src.tk_name, "-zoom", zoom, zoom, "-to", small)
    sw2 = int(tk.call("image", "width", small))
    sh2 = int(tk.call("image", "height", small))
    tk.call("image", "copy", small, "-to", canvas, (cw - sw2) // 2, (ch - sh2) // 2)
    tk.call("image", "delete", small)
