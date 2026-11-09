"""项目数据管理：project.json 的创建 / 读取 / 保存 / 迁移 / 镜头操作。

V1.1 数据模型（schema_version = 2）
------------------------------------
{
  "schema_version": 2,
  "name": "午夜纸人",
  "created_at": "...",
  "settings": {"width": 1080, "height": 1920, "fps": 30, "fit": "contain"},
  "shots": [
    {"id": "s0001", "image": "images/01.png", "start": 0.0, "duration": 3.5,
     "zoom": "none", "transition": "cut", "subtitle": null}
  ],
  "narration": "audio/voice.wav" | null,
  "music": "audio/bgm.mp3" | null,
  "subtitle": "subtitles/a.srt" | null,
  "images": [...]      # 仅 V1.0 遗留字段，迁移后保留只读
}

V1.2 新增 story 字段（可选，AI 创作的故事脚本）
-----------------------------------------------
{
  "story": {
    "schema_version": 1,
    "title": "雨夜纸人",
    "logline": "一句话梗概",
    "keywords": "废弃医院、纸人、雨夜",
    "generated_at": "...",
    "model": "deepseek-flash",
    "shots": [
      {"index": 1, "scene": "画面描述", "narration": "旁白", "duration": 3.5}
    ]
  }
}
story.shots 只是“脚本草稿”，导入时间轴后由 shots 承载实际画面；
两者通过 shot.story_index 关联，一次生成可反复导入 / 重新生成。

V1.3 新增镜头字段（均可选，旧的 project.json 不需要迁移）
--------------------------------------------------------
shot.ai_image     "images/ai_s0001.png" | null   AI 生成的画面（出图后写入）
shot.voice        "audio/voice_s0001.wav" | null 该镜头的 AI 配音片段
shot.voice_ms     配音实际时长（毫秒），用于界面提示“配音比镜头长被截断”

时间轴以 shots 为唯一事实来源：
- start 由时间轴顺序自动累加计算（reflow），不信任手工写入的 start；
- duration 是每个镜头的独立时长；
- V1.0 项目打开时自动把 images + 统一时长迁移成 shots，并回写磁盘。
"""
import copy
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_FILE = "project.json"
SCHEMA_VERSION = 2
STORY_SCHEMA_VERSION = 2  # story 字段结构版本（V2.2 五阶段结构，旧版自动升级）
VERSIONS_DIR = "versions"        # 历史版本快照目录（story.versions 记录元信息）
OFFICIAL_VERSION_LIMIT = 10      # 保留的正式版本数（保存 / 恢复产生的正式版本）

DEFAULT_SETTINGS = {
    "width": 1080, "height": 1920, "fps": 30, "fit": "contain",
    # V2.1 成片质感（旧项目缺失时自动补默认）
    "grain": 3,            # 胶片颗粒强度 0~10，0 = 关闭
    "vignette": True,      # 暗角
    "grade": "cold",       # 调色：cold / warm / neutral
    "loudnorm": True,      # 响度归一（-16 LUFS）
    "bed_drone": True,     # 没有 BGM 时自动垫低频 drone
    "pacing": "picture",   # 节奏：picture（画面优先）/ voice（声音优先）
}
DEFAULT_DURATION = 3.0
MIN_DURATION = 0.1
MAX_DURATION = 3600.0
# 画面优先节奏：画面时长范围与「旁白塞不下时自动延长」的上限
PICTURE_MIN_DURATION = 1.5
PICTURE_MAX_DURATION = 6.0     # V2.2：分镜时长上限从 4 秒放宽到 6 秒
PICTURE_EXTEND_MAX = 8.0
# 配音在镜头内的起始留白（毫秒）。画面优先模式下越小越利落
VOICE_OFFSET_MS_DEFAULT = 80
VOICE_TAIL_MS = 350
SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# 旧版运镜（只支持中心推拉），保留兼容；新代码优先读 shot["motion"]
ZOOM_MODES = ("none", "in", "out")
# V2.1 运镜：方向必须和画面内容一致（门在左就往左平移）
MOTION_MODES = ("static", "push-in", "pull-out", "pan-left", "pan-right", "diag-in")
MOTION_LABELS = {
    "static": "静止",
    "push-in": "缓慢推近",
    "pull-out": "缓慢拉远",
    "pan-left": "向左平移",
    "pan-right": "向右平移",
    "diag-in": "对角线推近",
}
ZOOM_TO_MOTION = {"none": "static", "in": "push-in", "out": "pull-out"}
TRANSITION_MODES = ("cut", "fade", "dissolve", "flash")
TRANSITION_LABELS = {
    "cut": "硬切",
    "fade": "黑场淡入淡出",
    "dissolve": "短淡入淡出",
    "flash": "白闪",
}
GRADE_MODES = ("cold", "warm", "neutral")
GRADE_LABELS = {"cold": "冷色（恐怖）", "warm": "暖色（复古）", "neutral": "中性（原色）"}
PACING_MODES = ("picture", "voice")
PACING_LABELS = {"picture": "画面优先", "voice": "旁白优先"}
PROJECT_SUBDIRS = ("images", "audio", "subtitles", "output", "temp", "versions")
# V3 P1：属于 stories/ 自有文件的字段，project.json 的 story 副本 / 快照里都不保留
_V3_OWN_KEYS = ("story_id", "project_id", "origin")


class ProjectError(Exception):
    """项目相关错误，界面层捕获后提示用户。"""


class ProjectReadOnlyError(ProjectError):
    """未来版本（schema_version > SCHEMA_VERSION）的项目只读，禁止写回。"""


def _shot_fingerprint(shot: dict, story_shot: dict | None = None) -> str:
    """时间轴镜头的内容指纹：旁白 + 运镜 + 时长（+ 故事分镜的画面描述）。

    用来判断「镜头内容有没有变」——变了才需要重新出图 / 配音。
    """
    from modules import story_schema as ss
    source = story_shot or {}
    prompt = str(source.get("image_prompt") or shot.get("image_prompt")
                 or shot.get("scene") or "")
    return ss.content_hash(prompt, str(shot.get("narration") or ""),
                           str(shot.get("motion") or ""),
                           f"{float(shot.get('duration') or 0):.2f}")


def material_name(shot_id: str, revision: int, kind: str = "image",
                  content_hash: str = "") -> str:
    """素材文件名：图片 = ai_{shot_id}_r{版本}_{指纹8位}.png，配音 = voice_{shot_id}_r{版本}.wav。

    文件名带版本与指纹：同一镜头重生成不会覆盖旧素材，恢复旧版本时可以原样找回。
    """
    revision = int(revision or 0)
    if kind == "voice":
        return f"voice_{shot_id}_r{revision}.wav"
    digest = f"_{(content_hash or '')[:8]}" if content_hash else ""
    return f"ai_{shot_id}_r{revision}{digest}.png"


def material_name_for(shot: dict, kind: str = "image") -> str:
    """按镜头当前版本生成素材文件名。"""
    return material_name(shot.get("shot_id") or shot.get("id") or "shot",
                         shot.get("shot_revision") or 0, kind,
                         shot.get("content_hash") or "")


def sanitize_name(name: str) -> str:
    safe = "".join(c for c in (name or "").strip() if c not in r'<>:"/\\|?*').strip(" .")
    return safe


def duration_to_frames(seconds: float, fps: int) -> int:
    return max(1, int(round(float(seconds) * fps)))


def frames_to_duration(frames: int, fps: int) -> float:
    return round(max(1, int(frames)) / fps, 3)


def format_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:05.2f}"


def parse_time(text: str) -> float:
    """解析 'mm:ss(.xx)'、'hh:mm:ss(.xx)' 或纯秒数。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("时间不能为空")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"无法解析时间：{text}")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    if total < 0:
        raise ValueError("时间不能为负数")
    return round(total, 3)


def _is_v3_data(project: Path, data: dict) -> bool:
    """写盘时 project.json 的版本号：数据已是 V3、或者磁盘上已经是 V3 项目。"""
    from modules import v3_storage
    raw = data.get("schema_version")
    if raw == v3_storage.V3_SCHEMA_VERSION:
        return True
    if raw != SCHEMA_VERSION:
        return False
    # 未来版本只读：绝不在磁盘上把版本号写小
    if ProjectManager._disk_schema_version(project) > v3_storage.V3_SCHEMA_VERSION:
        return False
    # 内存数据是 V2 格式（V3 对 V2 代码透明）：磁盘上已经是 V3 时不能写回 2，
    # 否则 V2 项目的首次「打开即升级」会被下一次保存打回 V2
    if (Path(project) / v3_storage.V3_LAYOUT_MARKER).exists():
        return True
    return ProjectManager._disk_schema_version(project) >= v3_storage.V3_SCHEMA_VERSION


class ProjectManager:
    def __init__(self):
        # V3 P1：最近一次 load / save 的项目目录。界面里大量「先 load 再 migrate」
        # 的两次调用写法，靠它让 migrate 里的 V3 hook 知道当前项目。
        self._v3_project: Path | None = None
        self._disk_story_version: int = -1      # 最近一次打开项目时磁盘上 story 的结构版本
        self._opening: bool = False             # 正在 open_project（对账写回允许因只读跳过）
        self._snapshot_written: bool = False    # 本次打开已写过升级快照
        # P1-Fix-2（R-A3）：最近一次打开时 Story 的恢复状态（None = 正常）。
        # {"state": "recovered" | "partial", "reason": "..."}；供上层识别，
        # 「恢复失败 / 部分恢复」不再被当成「正常空故事」。
        self.recovery_status: dict | None = None

    def _v3_context(self, project: Path):
        """临时把 V3 上下文指向 project（嵌套调用时恢复原值）。"""
        from modules import v3_storage
        outer = v3_storage.Attribution.project
        self._v3_project = Path(project)
        if outer is None:
            v3_storage.Attribution.set_project(Path(project))
        return outer

    def _v3_restore(self, outer):
        from modules import v3_storage
        self._v3_project = None
        if outer is None:
            v3_storage.Attribution.restore()

    def create_project(self, parent: Path, name: str) -> Path:
        safe_name = sanitize_name(name)
        if not safe_name:
            raise ProjectError("项目名称不能为空或包含无效字符。")
        project = Path(parent) / safe_name
        if project.exists() and any(project.iterdir()):
            raise ProjectError(f"目录已存在且不为空：{project}")
        for folder in PROJECT_SUBDIRS:
            (project / folder).mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": SCHEMA_VERSION,
            "name": safe_name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "settings": dict(DEFAULT_SETTINGS),
            "shots": [],
            "narration": None,
            "music": None,
            "subtitle": None,
            "story": None,
        }
        # V3 P1：主 story 元信息（project.json 的 story 字段仍同步维护，供 V2 兼容）
        data["stories"] = []
        data["primary_story_id"] = ""
        from modules import v3_storage
        outer = self._v3_context(project)
        try:
            vm = v3_storage.V3ProjectManager(project)
            data = vm.init_primary_story(data=data)
            if data["schema_version"] == v3_storage.V3_SCHEMA_VERSION:
                self.save(project, data)
        except (v3_storage.RepositoryError, OSError):
            # V3 基础不可用时回退为 V2 项目：保证「创建项目」本身不因 P1 失败
            data["schema_version"] = SCHEMA_VERSION
            data["stories"] = []
            data["primary_story_id"] = ""
            self.save(project, data)
        finally:
            self._v3_restore(outer)
        return project

    @staticmethod
    def _disk_schema_version(project: Path) -> int:
        try:
            raw = json.loads((Path(project) / PROJECT_FILE).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        value = raw.get("schema_version") if isinstance(raw, dict) else None
        return value if isinstance(value, int) else 0

    def open_project(self, project: Path) -> Path:
        project = Path(project)
        if not (project / PROJECT_FILE).exists():
            raise ProjectError("所选目录中没有 project.json，请选择正确的项目文件夹。")
        (project / VERSIONS_DIR).mkdir(parents=True, exist_ok=True)
        outer = self._v3_context(project)
        self._opening = True
        self._snapshot_written = False
        self.recovery_status = None           # R-A3：每次打开重新判定
        try:
            return self._open_project(project)
        finally:
            self._opening = False
            self._v3_restore(outer)

    def _open_project(self, project: Path) -> Path:
        # 第一步：V3 层的读取时间升级（stories/ 是故事的唯一真源）
        data = self.load(project)
        data = self._migrate_with_v3(project, data)
        due = bool(data.pop("_version_snapshot_due", False))
        if due and data.get("story") and not self._snapshot_written:
            # 升级后的结构存一份快照（save_version 会连同 story 一起写盘）
            self._snapshot_written = True
            try:
                data = self._migrate_with_v3(project, data)
                self.save_version(project, data, note="V2.2 结构升级",
                                  official=False)
                return project
            except ProjectError:
                pass
        return project

    def _migrate_with_v3(self, project: Path, data: dict) -> dict:
        """load -> 补版本号 -> migrate(含 V3 对账) -> 有改动就写盘；返回最新数据。"""
        from modules import v3_storage
        data = dict(data)
        story_version = data.pop("story_schema_version", None)
        if isinstance(story_version, int):
            self._disk_story_version = story_version
        # V3 项目对 V2 代码透明（schema_version 报 2）：磁盘上其实是 V3 时补回 3
        if (project / v3_storage.STORIES_DIR).exists() \
                and self._disk_schema_version(project) == v3_storage.V3_SCHEMA_VERSION:
            data["schema_version"] = v3_storage.V3_SCHEMA_VERSION
        data.pop("_version_snapshot_due", None)
        migrated, changed = self.migrate(data)
        due = bool(migrated.pop("_version_snapshot_due", False))
        # V3：内存里的 story 直接来自 stories/（已是当前结构），磁盘上却是旧结构——
        # 这正是「旧版本打开时自动升级」，需要存一份结构升级快照
        due = due or 0 < self._disk_story_version < STORY_SCHEMA_VERSION
        if due:
            migrated["_version_snapshot_due"] = True
        if changed or due:
            self.save(project, migrated)
        return migrated

    def load(self, project: Path) -> dict:
        outer = self._v3_context(project)
        try:
            return self._load_file(project, merge_v3=True)
        finally:
            self._v3_restore(outer)

    @staticmethod
    def _load_file(project: Path, merge_v3: bool = True) -> dict:
        try:
            with (project / PROJECT_FILE).open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ProjectError(f"project.json 格式损坏：{exc}") from exc
        if isinstance(data, dict):
            data.pop("_version_snapshot_due", None)
            data.pop("_v3_adopt", None)
            data.pop("_v3_upgraded", None)
            data.pop("recovery_status", None)      # R-A3：恢复状态只进内存
            data.pop("_not_recovered", None)
            if "story_schema_version" in data:
                # 只由本次 load 记录；内存数据又节省一次写盘（保存时会直接比较）
                data.pop("story_schema_version", None)
        if merge_v3 and isinstance(data, dict):
            from modules import v3_storage
            disk_version = data.get("schema_version")
            # 先记住磁盘上 story 的结构版本（V3 对账后可能被骨架覆盖）
            story = data.get("story")
            version = story.get("schema_version") if isinstance(story, dict) else None
            disk_story_version = version if isinstance(version, int) else -1
            data["story_schema_version"] = disk_story_version
            if disk_story_version < STORY_SCHEMA_VERSION:
                # project.json / stories/ 里的故事是旧结构：直接升级并写回（由 open_project
                # 存升级快照）。V3 对账在第二步进行，不能先被 stories/ 的内容覆盖。
                if disk_version == v3_storage.V3_SCHEMA_VERSION:
                    data["schema_version"] = SCHEMA_VERSION
                return data
            ProjectManager._merge_v3_story(project, data)
            if disk_version == v3_storage.V3_SCHEMA_VERSION:
                # 磁盘是 V3、内存对 V2 代码透明：其余 V2 代码只认识 schema_version=2
                data["schema_version"] = SCHEMA_VERSION
        return data

    @staticmethod
    def _merge_v3_story(project: Path, data: dict):
        """V3 项目：以 stories/<id>/story.json 为准恢复 project.json 的 story 字段。

        只读操作（不改磁盘）；stories/ 缺失或损坏时保持 project.json 原值，交给 migrate 处理。
        """
        version = data.get("schema_version")
        if not isinstance(version, int) or version < SCHEMA_VERSION:
            return
        story_id = str(data.get("primary_story_id") or "")
        if not story_id:
            return
        from modules import v3_storage, story_schema
        try:
            story = v3_storage.StoryRepository(project).get(story_id)
        except (v3_storage.RepositoryError, OSError):
            return
        if not isinstance(story, dict):
            return
        current = data.get("story")
        if v3_storage.is_valid_story(current) \
                and not v3_storage.is_valid_story(story):
            # stories/ 还是空骨架、project.json 有故事：以 project.json 为准
            # （随后由 V3 层采纳并写回 stories/，见 V3ProjectManager._hydrate）
            return
        if story.get("schema_version") != story_schema.SCHEMA_VERSION:
            # stories/ 还是旧结构（project.json 已是新结构）：以 project.json 为准,
            # 交给 migrate 升级后写回 stories/，不拿旧结构覆盖
            return
        data["story"] = v3_storage.V3ProjectManager.render_story_field(story)

    def save(self, project: Path, data: dict):
        outer = self._v3_context(project)
        try:
            self._save(project, data)
        except ProjectReadOnlyError:
            # 打开项目时的自动对账写回：项目是未来版本时只读打开，不能因此打不开
            if not self._opening:
                raise
        finally:
            self._v3_restore(outer)

    def _save(self, project: Path, data: dict):
        from modules import v3_storage
        raw = data.get("schema_version")
        if isinstance(raw, int) and raw > v3_storage.V3_SCHEMA_VERSION:
            # 未来版本只读：禁止任何写回（包括迁移后的写盘）
            raise ProjectReadOnlyError(
                f"项目数据版本 {raw} 高于当前程序支持的 {SCHEMA_VERSION}，"
                "已按只读方式打开，不能保存。")
        if self._disk_schema_version(project) > v3_storage.V3_SCHEMA_VERSION:
            # 磁盘上是未来版本：打开后的对账写回一律跳过（打开即只读，一字不改）
            return
        # 写盘路径上以内存里的 story 为准：同步进 stories/（不反过来改写 project.json）
        from modules import v3_storage
        if (project / PROJECT_FILE).exists():
            # P1-Fix（P1-02）：保存前统一检查磁盘真实版本（不依赖内存里的 2）
            try:
                v3_storage.assert_writable(project, "保存项目")
            except v3_storage.RepositoryError as exc:
                if self._opening:
                    return           # 打开时的自动对账写回：只读直接跳过
                raise ProjectReadOnlyError(str(exc)) from None
        try:
            v3_storage.sync_story(project, data)
            status = data.pop("recovery_status", None)
            if status is not None:
                # R-A3：供上层识别「恢复/部分恢复」；状态本身不落盘
                self.recovery_status = status
            disk = data
            if _is_v3_data(project, data):
                disk = dict(data)
                disk["schema_version"] = v3_storage.V3_SCHEMA_VERSION
        except v3_storage.RepositoryError as exc:
            if self._opening:
                return
            raise ProjectReadOnlyError(str(exc)) from None
        tmp = project / (PROJECT_FILE + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(disk, f, ensure_ascii=False, indent=2)
        tmp.replace(project / PROJECT_FILE)

    # ------------------------------------------------------------------
    # 迁移
    # ------------------------------------------------------------------
    def migrate(self, data: dict) -> tuple[dict, bool]:
        """把任意旧版本数据升级到 V1.1 模型。返回 (新数据, 是否有改动)。"""
        data = copy.deepcopy(data)
        changed = False
        version_changed = False      # story 结构升级 / 镜头版本号变化：需要存版本快照
        if "recovery_status" in data:
            # P1-Fix-2（R-A3）：V3 层在 load 阶段记录的恢复状态不是业务数据：
            # 移交给实例属性供上层读取，绝不写进 project.json
            self.recovery_status = data.pop("recovery_status")

        # V3 P1：未来版本（磁盘上 schema_version 更高）只读——不做迁移、不改任何版本号，
        # 保证打开之后原样写回也不会把磁盘版本号写小
        project = self._v3_project
        if project is not None:
            from modules import v3_storage
            if self._disk_schema_version(project) > v3_storage.V3_SCHEMA_VERSION:
                data.pop("_version_snapshot_due", None)
                return data, False

        if not isinstance(data.get("settings"), dict):
            data["settings"] = dict(DEFAULT_SETTINGS)
            changed = True
        for key, value in DEFAULT_SETTINGS.items():
            if key not in data["settings"]:
                data["settings"][key] = value
                changed = True

        shots = data.get("shots")
        legacy_images = data.get("images") or []

        if not isinstance(shots, list):
            # V1.0 项目：每张图片按统一时长生成镜头
            duration = float(data.get("image_duration", DEFAULT_DURATION) or DEFAULT_DURATION)
            data["shots"] = [
                self._make_shot(image, duration)
                for image in legacy_images
            ]
            changed = True
        else:
            cleaned = []
            for raw in shots:
                shot = self._normalize_shot(raw, legacy_images)
                if shot is not None:
                    cleaned.append(shot)
                    if shot != raw:
                        changed = True
            if cleaned != shots:
                data["shots"] = cleaned
                changed = True
            if "schema_version" not in data:
                changed = True

        old_story_version = (data.get("story") or {}).get("schema_version") \
            if isinstance(data.get("story"), dict) else None
        if "story_schema_version" not in data:
            # V3 对账需要知道「内存里的 story 是不是本次刚升级的」（load 是只读的）。
            # 注：内存里的 story 可能已被 load（V3）按磁盘对齐成当前结构，
            # 真实版本以 load 从磁盘记下的 story_schema_version 为准。
            data["story_schema_version"] = self._disk_story_version
        story_upgrade = False
        if self._normalize_story(data):
            changed = True
            # 磁盘上原本是旧结构（load 记录的 story_schema_version）才算「结构升级」
            if old_story_version != STORY_SCHEMA_VERSION \
                    and 0 <= self._disk_story_version < STORY_SCHEMA_VERSION:
                version_changed = True
                story_upgrade = True
        if story_upgrade and self._v3_project is not None:
            # V3 项目里升级后的故事要写回 stories/（否则下次 load 会被旧结构覆盖）
            data["_v3_adopt"] = data.get("story")
        data.pop("story_schema_version", None)
        # 注意：migrate() 每次读写都会调用，所以版本快照不能在这里生成
        # （否则每次保存都多一个版本）。升级后由 open_project 存一次快照。
        if version_changed:
            data["_version_snapshot_due"] = True
        if self.reflow(data):
            changed = True
        # V3 P1：project.json 的版本号由基础层决定（新项目 = V3，V2 项目保持不变）。
        if self._v3_load(data):
            changed = True
        if data.pop("_v3_upgraded", False):
            # V3 对账时发现磁盘上是旧结构 story、由 stories/ 覆盖：同样需要升级快照
            data["_version_snapshot_due"] = True
        from modules import v3_storage
        if self._v3_project is not None \
                and (Path(self._v3_project) / v3_storage.STORIES_DIR).exists() \
                and data.get("schema_version") == v3_storage.V3_SCHEMA_VERSION:
            # V3 项目对 V2 代码透明：内存里的数据始终报 schema_version=2
            data["schema_version"] = SCHEMA_VERSION
        return data, changed

    def _v3_load(self, data: dict) -> bool:
        """调用 V3 基础层：决定 schema_version 并保证有新项目就有主 Story。

        - 没有项目目录（纯内存测试数据）：保持 V2 结构，不做任何 V3 动作；
        - V2 项目（还没有 stories/）：写盘时一次性初始化主 Story（原有 story 原样
          带入，没有故事则建空骨架），之后磁盘上就是 V3 项目；
        - V3 项目：stories/ 是 story 的唯一真源，据此对账。

        返回是否有改动。V3 失败不得让项目打不开，所以这里不抛异常。
        """
        from modules import v3_storage
        project = self._v3_project or v3_storage.Attribution.project
        if project is not None:
            project = Path(project)
            disk = self._disk_schema_version(project)
            if disk > v3_storage.V3_SCHEMA_VERSION:
                # 未来版本只读：不改内存版本号、不做任何 V3 初始化 / 对账
                return False
        if project is None:
            if "primary_story_id" not in data and "stories" not in data:
                # 纯内存数据（从未落盘）：保持 V2 结构原样
                data["schema_version"] = SCHEMA_VERSION
                return False
            # 之前从项目加载过（带主 Story 元信息）：不能把 schema_version 打回 2，
            # 否则下一次 save 会丢掉 V3 版本号
            return False
        if (project / PROJECT_FILE).exists():
            # 写盘路径上，project.json 的 story 字段与 stories/ 对齐（stories/ 缺失时保持原值）。
            # _v3_adopt：本次内存里的 story 刚由 migrate 升级 / 由 project.json 采纳，是权威值，
            # 不能被 stories/ 里的旧内容覆盖（写盘时由 sync_story 写进 stories/）。
            # P1-Fix（P1-03）：写盘前把损坏的 stories/ 文件隔离（原始字节进 .corrupt/）。
            # 无论内存里的 story 是否已有权威值（_v3_adopt）都要做：否则随后的
            # sync_story 会用内存数据直接覆盖唯一证据。
            pid = str(data.get("primary_story_id") or "")
            story_path = (Path(project) / v3_storage.STORIES_DIR / pid
                          / v3_storage.STORY_FILE)
            broken = False
            try:
                # P1-Fix-2（R-A2）：统一可用性判定——JSON 坏 或 结构不可用
                # （shots 不是列表 / 根不是对象）都算损坏；空骨架 shots:[] 不算。
                stored = v3_storage.V3ProjectManager(project).usable_story_file(story_path)
                if isinstance(stored, dict) and stored.get("schema_version") != STORY_SCHEMA_VERSION:
                    # 结构版本不符 = 无法确认内容可用，按损坏隔离
                    broken = True
            except v3_storage.CorruptDataError:
                broken = True
            except v3_storage.RepositoryError:
                pass
            if broken:
                vm = v3_storage.V3ProjectManager(project)
                if vm._quarantine_corrupt(story_path) is None:
                    raise ProjectError(
                        f"{story_path} 内容损坏，且备份到 .corrupt/ 失败："
                        "为避免覆盖唯一数据，本次保存已中止（未写入任何文件）。")
                data.pop("_v3_adopt", None)     # 文件已隔离：交给 V3 层按规则恢复
            if not data.get("_v3_adopt"):
                # _v3_adopt：内存里的 story 刚由 migrate 升级 / 由 project.json 采纳，
                # 是权威值，不能被 stories/ 里的旧内容覆盖（写盘时由 sync_story 写回）。
                self._merge_v3_story(project, data)
        try:
            vm = v3_storage.V3ProjectManager(project)
            v3_storage.Attribution.enter("v3")
            try:
                result = (vm.init_primary_story(data=data)
                          if not (project / v3_storage.STORIES_DIR).exists()
                          else vm.load(data)[0])
            finally:
                v3_storage.Attribution.leave()
            if result is data:
                return True
            # V3 层返回的是新 dict：就地覆盖，调用方持有的是原对象
            data.clear()
            data.update(result)
            return True
        except (v3_storage.RepositoryError, OSError) as exc:
            if isinstance(exc, v3_storage.CorruptDataError):
                # P1-Fix-2（R-A2/R-A3）：V3 层已判定数据损坏且无法恢复（原始字节
                # 已隔离到 .corrupt/）。不能把它当成「没有故事」静默打开——否则
                # 上层看到的是正常空项目，恢复失败被伪装成正常空 Story。
                raise ProjectError(str(exc)) from None
            return False

    def _make_shot(self, image: str | None, duration: float = DEFAULT_DURATION) -> dict:
        return {
            "id": uuid.uuid4().hex[:8],
            "image": image,
            "start": 0.0,
            "duration": round(max(MIN_DURATION, float(duration)), 3),
            "zoom": "none",
            "motion": "static",
            "transition": "cut",
            "subtitle": None,
            "voiced": True,
        }

    def _normalize_shot(self, raw: dict, legacy_images: list) -> dict | None:
        if not isinstance(raw, dict):
            return None
        image = raw.get("image")
        # image 可以为空：V1.2 从故事导入的镜头在生成画面（V1.3）之前没有图。
        # 旧版本（V1.0/V1.1）的镜头必须有图，所以只丢弃“既无图又无 id 的垃圾条目”。
        if not image and not raw.get("id"):
            return None
        shot = dict(raw)
        shot.setdefault("id", uuid.uuid4().hex[:8])
        try:
            duration = float(shot.get("duration", DEFAULT_DURATION))
        except (TypeError, ValueError):
            duration = DEFAULT_DURATION
        shot["duration"] = round(min(MAX_DURATION, max(MIN_DURATION, duration)), 3)
        # 先归一旧 zoom 字段：V1.x 写的 "in"/"out" 以下面形态都能认
        zoom = shot.get("zoom")
        if zoom not in ZOOM_MODES:
            zoom = "none"
        shot["zoom"] = zoom
        # V2.1 运镜：字段缺失时由旧 zoom 推导，保证老项目也能吃到新运镜
        if shot.get("motion") not in MOTION_MODES:
            shot["motion"] = ZOOM_TO_MOTION.get(zoom, "static")
        if shot.get("transition") not in TRANSITION_MODES:
            shot["transition"] = "cut"
        if not isinstance(shot.get("voiced"), bool):
            shot["voiced"] = True
        shot.setdefault("start", 0.0)
        shot.setdefault("subtitle", None)
        if "image" not in shot:
            shot["image"] = None
        # V1.3：AI 出图 / 配音字段，缺失时补 null（不强制迁移磁盘）
        shot.setdefault("ai_image", None)
        shot.setdefault("voice", None)
        shot.setdefault("voice_ms", None)
        # V2.2：镜头版本与内容指纹——图片 / 配音绑定到具体版本，内容变了才需要重生成。
        # 这两个字段由 _sync_shot_versions 在 migrate 时按需补齐（需要关联故事分镜），
        # 这里不做默认值，否则同步逻辑无法区分「旧镜头」与「已同步的新镜头」。
        if "shot_revision" in shot and (not isinstance(shot["shot_revision"], int)
                                        or shot["shot_revision"] < 0):
            shot["shot_revision"] = 0
        if "content_hash" in shot and not isinstance(shot["content_hash"], str):
            shot["content_hash"] = ""
        shot.setdefault("shot_id", "")       # 故事分镜 id（s001…），导入时写入
        shot.setdefault("scene_id", "")
        shot.setdefault("character_ids", [])
        return shot

    @staticmethod
    def _record_stale(stale: dict, shot: dict, old_hash: str):
        """内容变了：把旧素材按指纹登记到 story.stale（恢复旧版本时可复用）。"""
        if not old_hash:
            return
        entry = stale.setdefault(old_hash, {"paths": {}, "shot_id": shot.get("shot_id", ""),
                                           "revision": int(shot.get("shot_revision") or 0)})
        paths = entry.setdefault("paths", {})
        for key in ("ai_image", "voice"):
            if shot.get(key):
                paths.setdefault(key, shot[key])

    @staticmethod
    def _sync_shot_versions(shots: list[dict], story_shots: list[dict],
                            story: dict | None = None,
                            keep_ids: set | None = None) -> bool:
        """让时间轴镜头的 shot_id / 版本号 / 指纹与故事分镜一致。

        * 新镜头（或 story 重写后内容变化）：shot_revision += 1，更新 content_hash；
        * 已有素材的镜头（keep_ids）与「保持版本」的版本恢复：版本号不动；
        * 内容变了且旧素材还在：paths 列入 story.stale，恢复版本时优先复用。
        """
        from modules import story_schema as ss
        keep_ids = keep_ids or set()
        story = story if isinstance(story, dict) else {}
        keep_versions = story.get("version_strategy") == "keep"
        stale = story.get("stale") if isinstance(story.get("stale"), dict) else None
        by_id = {}
        for item in story_shots:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("shot_id") or "")
            if sid:
                by_id[sid] = item
        changed = False
        for shot in shots:
            sid = str(shot.get("shot_id") or "")
            new_hash = _shot_fingerprint(shot, by_id.get(sid))
            old_hash = str(shot.get("content_hash") or "")
            if "shot_revision" not in shot or "content_hash" not in shot:
                shot["shot_revision"] = max(0, int(shot.get("shot_revision") or 0))
                shot["content_hash"] = old_hash or new_hash
                changed = True
                continue
            if old_hash and (shot.get("id") in keep_ids or keep_versions):
                # 已有素材的镜头（keep_ids）保留原版本号，只补指纹
                if new_hash != old_hash:
                    shot["content_hash"] = new_hash
                    changed = True
                continue
            if new_hash != old_hash:
                if stale is not None:
                    ProjectManager._record_stale(stale, shot, old_hash)
                shot["shot_revision"] = int(shot.get("shot_revision") or 0) + 1
                shot["content_hash"] = new_hash
                changed = True
        # 分镜 id 同步到新故事（s001…），方便素材按故事镜头命名
        for shot in shots:
            pos = shot.get("story_index") or (shots.index(shot) + 1)
            try:
                item = story_shots[int(pos) - 1] if 1 <= int(pos) <= len(story_shots) else None
            except (TypeError, ValueError):
                item = None
            if not isinstance(item, dict) or not item.get("shot_id"):
                continue
            if shot.get("shot_id") != item["shot_id"]:
                shot["shot_id"] = item["shot_id"]
                changed = True
            if shot.get("scene_id") != (item.get("scene_id") or ""):
                shot["scene_id"] = item.get("scene_id") or ""
                changed = True
            if list(shot.get("character_ids") or []) != list(item.get("character_ids") or []):
                shot["character_ids"] = list(item.get("character_ids") or [])
                changed = True
        return changed

    # ------------------------------------------------------------------
    # 故事脚本（V1.2）
    # ------------------------------------------------------------------
    def _normalize_story(self, data: dict) -> bool:
        """校验 story 字段结构并升级到 V2.2 schema 2，返回是否改动过 data。

        旧版 story（schema 1，只有 index/scene/narration/duration）经
        story_schema.upgrade_story 升级：补 shot_id / scene_id / 人物引用 /
        策划 / 剧本 / 节奏 / 质量等字段，旧字段原样保留。
        """
        story = data.get("story")
        if story is None:
            return False
        if data.get("_v3_adopt") is not None:
            # P1-Fix（P1-03）：V3 层刚从 versions/ 恢复出 candidate（写进 story 字段）。
            # candidate 已由 version snapshot 规范过（shots 是列表），这里再 normalize 会
            # 把它判坏而丢掉恢复结果——交给 V3 层按 _v3_adopt 写回 stories/。
            return False
        if not isinstance(story, dict):
            data.pop("story", None)
            return True
        shots = story.get("shots")
        if not isinstance(shots, list):
            # P1-Fix-2（R-A2）：project.json 里的 story 结构损坏（shots 不是列表）。
            # 不能在这里把它删掉——V3 层/人工恢复需要看到原始内容才能判定「双侧
            # 损坏」；删掉会被误判成「没有故事」，进而走空骨架或部分恢复。
            return False
        from modules import story_schema as ss
        try:
            upgraded, changed = ss.upgrade_story(story)
        except (ss.SchemaError, TypeError, ValueError):
            data.pop("story", None)
            return True
        if changed or upgraded is not story:
            data["story"] = upgraded
        story = data["story"]
        if story.get("schema_version") != STORY_SCHEMA_VERSION:
            story["schema_version"] = STORY_SCHEMA_VERSION
            changed = True
        if not isinstance(story.get("versions"), list):
            story["versions"] = []
            changed = True
        # 时间轴镜头同步版本号 / 指纹：已有素材的镜头保留原版本号。
        # 旧项目迁移时镜头缺版本字段也必定改写（不依赖上面的 changed）。
        if self._sync_shot_versions(data.get("shots") or [], story.get("shots") or [],
                                    data.get("story") or {},
                                    keep_ids=self._material_shot_ids(data)):
            changed = True
        return changed

    def get_story(self, data: dict) -> dict | None:
        story = data.get("story")
        return story if isinstance(story, dict) and story.get("shots") else None

    def set_story(self, project: Path, story: dict):
        """保存故事脚本（覆盖旧 story，不动时间轴），并生成一个版本快照。"""
        from modules import v3_storage
        v3_storage.assert_writable(project, "保存故事")
        data = self.migrate(self.load(project))[0]
        # 先按旧 story 同步一次（旧项目镜头还没版本号），再换新 story
        old_story = data.get("story") or {}
        if old_story.get("shots"):
            self._sync_shot_versions(data.get("shots") or [], old_story.get("shots") or [],
                                     old_story,
                                     keep_ids=self._material_shot_ids(data))
        payload = {
            "schema_version": STORY_SCHEMA_VERSION,
            "title": str(story.get("title") or "未命名故事"),
            "logline": str(story.get("logline") or ""),
            "keywords": str(story.get("keywords") or ""),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "model": str(story.get("model") or ""),
            "characters": copy.deepcopy(story.get("characters") or []),
            "scenes": copy.deepcopy(story.get("scenes") or []),
            "shots": copy.deepcopy(story.get("shots") or []),
        }
        for key in ("style", "concept", "concepts", "plan", "script", "pacing", "quality",
                    "stale", "golden_topic", "tier", "model_by_stage"):
            if key in story:
                payload[key] = copy.deepcopy(story[key])
        old = data.get("story") or {}
        payload["versions"] = copy.deepcopy(old.get("versions") or [])
        payload["active_version"] = str(old.get("active_version") or "")
        data["story"] = payload
        self._normalize_story(data)
        self.save_version(project, data, note=str(story.get("note") or "保存剧本"),
                          official=True)
        # V3：版本快照生成后再同步到独立 Story（此时 versions 已完整）
        self._write_v3_story(project, data)
        return data["story"]

    def _write_v3_story(self, project: Path, data: dict):
        """V3 项目：把 project.json 的 story 同步写进 stories/<id>/story.json。

        V2 项目（project.json 没有主 Story，schema_version=2）不做任何事：
        P1 阶段 V2 数据格式不变。V3 写入失败不破坏 V2 数据，只记录原因。
        """
        from modules import v3_storage
        try:
            v3_storage.assert_writable(project, "同步 Story")   # P1-02：数据层统一拒写
        except v3_storage.RepositoryError:
            return
        story_id = str(data.get("primary_story_id") or "")
        if not story_id or not isinstance(data.get("story"), dict):
            return
        repo = v3_storage.StoryRepository(project)
        existing = repo.get(story_id)
        if not isinstance(existing, dict):
            return
        payload = copy.deepcopy(data["story"])
        for key in ("story_id", "project_id", "origin", "created_at"):
            if key in existing:
                payload[key] = copy.deepcopy(existing[key])
        # 版本引用只属于 stories/ 的真源：project.json 的 compatible 副本不强求
        for key in ("versions", "active_version"):
            if key in existing and key not in payload:
                payload[key] = copy.deepcopy(existing[key])
        payload["story_id"] = story_id
        payload["project_id"] = str(data.get("name") or "")
        try:
            story = repo.update(story_id, payload)
            self._sync_v3_story_meta(project, data, story)
        except (v3_storage.RepositoryError, OSError):
            pass

    def _sync_v3_story_meta(self, project: Path, data: dict, v3_story: dict | None):
        """把 V3 story 的版本列表 / 激活版本写回 project.json 的元信息（只增不删）。"""
        if not v3_story:
            return
        entries = []
        seen = False
        for entry in data.get("stories") or []:
            if isinstance(entry, dict) and entry.get("story_id") == v3_story["story_id"]:
                entry = dict(entry)
                entry["title"] = v3_story.get("title") or entry.get("title", "")
                entry["updated_at"] = v3_story.get("updated_at") or entry.get("updated_at", "")
                entry["shot_count"] = len(v3_story.get("shots") or [])
                seen = True
            entries.append(entry)
        if not seen:
            entries.append({"story_id": v3_story["story_id"],
                            "title": v3_story.get("title", "")})
        data["stories"] = entries
        self.save(project, data)

    def clear_story(self, project: Path):
        from modules import v3_storage
        v3_storage.assert_writable(project, "清空故事")
        data = self.migrate(self.load(project))[0]
        data.pop("story", None)
        story_id = str(data.get("primary_story_id") or "")
        if story_id:
            from modules import v3_storage
            repo = v3_storage.StoryRepository(project)
            story = repo.get(story_id)
            if isinstance(story, dict):
                # 清空内容但保留主 Story 骨架（项目仍然「有主 Story」）
                story["shots"] = []
                story["characters"] = []
                story["scenes"] = []
                story["concepts"] = []
                story["stale"] = {}
                try:
                    repo.update(story_id, story)
                except (v3_storage.RepositoryError, OSError):
                    pass
        self.save(project, data)

    # ------------------------------------------------------------------
    # 版本快照（V2.2）
    # ------------------------------------------------------------------
    @staticmethod
    def _material_shot_ids(data: dict) -> set:
        """已有画面 / 配音的镜头 id：这些镜头的版本号不随文案变化重置。"""
        return {s.get("id") for s in data.get("shots") or []
                if s.get("id") and (s.get("ai_image") or s.get("voice"))}

    def _versions_root(self, project: Path) -> Path:
        return Path(project) / VERSIONS_DIR

    def _version_file(self, project: Path, version_id: str) -> Path:
        return self._versions_root(project) / f"{version_id}.json"

    def save_version(self, project: Path, data: dict, note: str = "",
                     official: bool = True) -> dict:
        """把当前 story 完整快照写入 versions/ 并记录元信息，返回版本条目。

        正式版本（official）最多保留 OFFICIAL_VERSION_LIMIT 个；删除最旧快照前
        先检查是否仍被素材引用（active_version 指向的版本永远不删）。
        """
        story = data.get("story") or {}
        if not story:
            raise ProjectError("当前没有故事可以存版本。")
        from modules import v3_storage
        # P1-Fix（P1-02）：必须在创建任何快照文件之前检查磁盘真实版本
        v3_storage.assert_writable(project, "保存版本")
        versions = story.get("versions")
        if not isinstance(versions, list):
            versions = story["versions"] = []
        version_id = f"v{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        root = self._versions_root(project)
        root.mkdir(parents=True, exist_ok=True)
        snapshot = copy.deepcopy(story)
        for key in _V3_OWN_KEYS:      # V3 自有字段只属于 stories/，不进快照
            snapshot.pop(key, None)
        snapshot.pop("versions", None)
        snapshot.pop("active_version", None)
        snapshot["version_id"] = version_id
        snapshot["created_at"] = datetime.now().isoformat(timespec="seconds")
        snapshot["note"] = note or ""
        target = self._version_file(project, version_id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        entry = {
            "version_id": version_id,
            "created_at": snapshot["created_at"],
            "note": note or "",
            "official": bool(official),
            "title": snapshot.get("title", ""),
            "shot_count": len(snapshot.get("shots") or []),
            "total_duration": round(sum(float(s.get("duration") or 0)
                                        for s in snapshot.get("shots") or []), 2),
            "score": (snapshot.get("quality") or {}).get("score") if isinstance(
                snapshot.get("quality"), dict) else None,
            "file": f"{VERSIONS_DIR}/{version_id}.json",
        }
        versions.append(entry)
        self._prune_versions(project, data, official_only=True)
        self.save(project, data)
        return entry

    def _prune_versions(self, project: Path, data: dict, official_only: bool = True):
        """删掉超出保留数量的旧快照。被引用的快照不删（保护素材关联）。

        P1-Fix（P1-01）：上限只按**正式版本**计数——非正式版本（结构升级快照、
        「恢复前自动备份」「恢复自 X」）不占正式版本名额，也不会被本次裁剪删除。
        删除顺序：先删版本文件，成功后才从元信息里移除；文件删不掉（被占用等）
        就保留该元信息，不让「元数据已删、文件还在（或反之）」静默发生。
        """
        story = data.get("story") or {}
        versions = story.get("versions") or []
        official = [v for v in versions if isinstance(v, dict) and v.get("official")]
        excess = len(official) - OFFICIAL_VERSION_LIMIT
        if excess <= 0:
            return
        doomed = []
        for entry in official:            # versions 按时间顺序追加，从最旧的开始
            if len(doomed) >= excess:
                break
            vid = entry.get("version_id")
            if self._version_referenced(project, data, vid):
                continue                  # 活动版本 / base 链 / 素材引用的版本不删
            doomed.append(entry)
        removed = set()
        for entry in doomed:
            vid = entry.get("version_id", "")
            path = self._version_file(project, vid)
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    # 文件删不掉：保留元信息，下次保存再试，不产生悬空引用
                    continue
            removed.add(vid)
        if not removed:
            return
        story["versions"] = [v for v in versions
                             if not (isinstance(v, dict)
                                     and v.get("version_id") in removed)]

    def _version_referenced(self, project: Path, data: dict, version_id: str) -> bool:
        """版本是否仍被引用：激活版本 / 其它版本的 base 链 / 时间轴素材记录。"""
        if not version_id:
            return False
        story = data.get("story") or {}
        if version_id == story.get("active_version"):
            return True
        for entry in story.get("versions") or []:
            if isinstance(entry, dict) and entry.get("base_version") == version_id:
                return True
        for shot in data.get("shots") or []:
            if shot.get("voice_version") == version_id:
                return True
            stale = shot.get("stale") or {}
            if isinstance(stale, dict) and version_id in (stale.get("versions") or []):
                return True
        return False

    def list_versions(self, data: dict) -> list[dict]:
        story = data.get("story") or {}
        versions = [v for v in (story.get("versions") or []) if isinstance(v, dict)]
        return list(reversed(versions))      # 新的在前

    def load_version(self, project: Path, version_id: str) -> dict:
        path = self._version_file(project, version_id)
        if not path.exists():
            raise ProjectError(f"版本 {version_id} 的快照已不存在。")
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError(f"版本快照损坏：{exc}") from exc
        if not isinstance(snapshot, dict):
            raise ProjectError("版本快照格式不正确。")
        return snapshot

    def restore_version(self, project: Path, version_id: str) -> dict:
        """恢复到指定版本。当前状态先存成快照（可再切回），恢复后可回滚。"""
        from modules import v3_storage
        v3_storage.assert_writable(project, "恢复版本")   # 改 Story 之前先拒
        data = self.migrate(self.load(project))[0]
        snapshot = self.load_version(project, version_id)
        before = self.save_version(project, data, note="恢复前自动备份",
                                   official=False) if data.get("story") else None
        meta = [v for v in (data["story"].get("versions") or [])
                if isinstance(v, dict) and v.get("version_id") == version_id]
        story = copy.deepcopy(snapshot)
        story.pop("version_id", None)
        story["versions"] = copy.deepcopy(data["story"].get("versions") or [])
        story["active_version"] = version_id
        for key in ("title", "schema_version"):
            if key in snapshot:
                story[key] = snapshot[key]
        # 恢复后再存一版「恢复」记录：既方便确认，也保证 restore 可重复
        restored = copy.deepcopy(story)
        restored["versions"] = [v for v in story["versions"]
                                if v.get("version_id") != version_id]
        for key in _V3_OWN_KEYS:
            if key in data["story"]:
                restored[key] = data["story"][key]
        data["story"] = restored
        self._normalize_story(data)
        entry = self.save_version(project, data, note=f"恢复自 {version_id}",
                                  official=False)
        entry["base_version"] = version_id
        story_entry = [v for v in data["story"]["versions"]
                       if v.get("version_id") == entry["version_id"]]
        if story_entry:
            story_entry[0]["base_version"] = version_id
        data["story"]["active_version"] = entry["version_id"]
        # 时间轴镜头同步到恢复后的分镜（仍保留已有素材）
        self._sync_timeline_to_story(data)
        self.save(project, data)
        result = dict(entry)
        result["previous"] = before.get("version_id") if before else ""
        result["source_note"] = meta[0].get("note", "") if meta else ""
        return result

    def _sync_timeline_to_story(self, data: dict):
        """恢复版本时把时间轴镜头的文案 / 时长对齐到新 story（保留 id 与已有素材）。"""
        story_shots = ((data.get("story") or {}).get("shots") or [])
        by_index = {}
        for i, item in enumerate(story_shots, 1):
            if isinstance(item, dict):
                try:
                    by_index[int(item.get("index") or i)] = item
                except (TypeError, ValueError):
                    by_index[i] = item
        if not by_index:
            return
        cursor = 0.0
        kept = []
        for pos, shot in enumerate(data.get("shots") or [], 1):
            item = by_index.get(pos) or by_index.get(shot.get("story_index"))
            if item is None and pos <= len(story_shots):
                item = story_shots[pos - 1]
            if item is None:
                kept.append(shot)
                continue
            for key in ("scene", "narration", "motion", "voiced", "transition"):
                if key in item:
                    shot[key] = item[key]
            try:
                shot["duration"] = round(max(MIN_DURATION, float(
                    item.get("duration", shot.get("duration", DEFAULT_DURATION)))), 3)
            except (TypeError, ValueError):
                pass
            shot["shot_id"] = item.get("shot_id") or shot.get("shot_id") or ""
            shot["scene_id"] = item.get("scene_id") or ""
            shot["character_ids"] = list(item.get("character_ids") or [])
            shot["content_hash"] = _shot_fingerprint(shot, item)
            kept.append(shot)
            cursor += float(shot.get("duration", 0))
        data["shots"] = kept
        self.reflow(data)

    def mark_material_stale(self, data: dict, shot: dict) -> bool:
        """镜头内容变化时把旧素材登记为「过期但可复用」。返回是否有改动。"""
        stale = shot.get("stale")
        if not isinstance(stale, dict):
            stale = shot["stale"] = {}
        changed = False
        versions = stale.setdefault("versions", [])
        current = shot.get("shot_revision")
        for key in ("ai_image", "voice"):
            path = shot.get(key)
            if not path:
                continue
            record = stale.get(key)
            if isinstance(record, dict) and record.get("path") == path:
                continue
            stale[key] = {"path": path, "revision": current or 0,
                          "content_hash": shot.get("content_hash") or ""}
            changed = True
        if stale.get("ai_image") and stale["ai_image"].get("content_hash"):
            h = stale["ai_image"]["content_hash"]
            if h not in versions:
                versions.append(h)
                changed = True
        return changed

    def replace_all_shots(self, project: Path, shots: list[dict]):
        """用给定镜头整体替换时间轴（导入故事时使用），返回新镜头列表。

        与 _normalize_shot 不同：这里信任调用者给的条目，
        无图也无脚本的镜头也保留（作为待配图占位）。
        """
        data = self.migrate(self.load(project))[0]
        new_shots = []
        for raw in shots:
            if not isinstance(raw, dict):
                continue
            shot = self._make_shot(raw.get("image") or None,
                                   raw.get("duration", DEFAULT_DURATION))
            for key in ("zoom", "motion", "voiced", "transition", "subtitle", "scene",
                    "narration", "story_index", "ai_image", "voice", "voice_ms",
                    "shot_id", "scene_id", "character_ids", "shot_revision",
                    "content_hash", "stale"):
                if key in raw and raw[key] is not None:
                    shot[key] = raw[key]
            # V2.1：分镜没给转场时按运镜推导，让成片一开始就有节奏变化
            if not raw.get("transition"):
                shot["transition"] = self.suggest_transition(shot)
            # V1.3 字段补 null，保证所有镜头键集一致（界面与渲染按键取值）
            for key in ("ai_image", "voice", "voice_ms"):
                shot.setdefault(key, None)
            new_shots.append(shot)
        data["shots"] = new_shots
        story = data.get("story") or {}
        # 新导入的镜头按故事分镜补齐章节 / 版本号 / 指纹
        self._sync_shot_versions(new_shots, story.get("shots") or [], story,
                                 keep_ids=self._material_shot_ids(data))
        self.reflow(data)
        self.save(project, data)
        return data["shots"]

    def attach_images(self, project: Path, start_index: int, sources: list[Path],
                      only_empty: bool = False) -> int:
        """把图片按顺序贴到从 start_index 开始的镜头上。返回成功数量。

        only_empty=True 时只填 image 为空的镜头（追加图片不会打乱已有画面）。
        """
        data = self.migrate(self.load(project))[0]
        shots = data["shots"]
        pending = []
        for i, shot in enumerate(shots):
            if i < start_index:
                continue
            if only_empty and shot.get("image"):
                continue
            pending.append(shot)
        count = 0
        for shot, source in zip(pending, sources):
            source = Path(source)
            if source.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
                continue
            copied = self._copy_unique(source, project / "images")
            shot["image"] = str(copied.relative_to(project)).replace("\\", "/")
            count += 1
        self.reflow(data)
        self.save(project, data)
        return count

    def link_image(self, project: Path, shot_id: str, source: Path) -> str:
        """给单个镜头指定图片（复制进项目）。返回相对路径。"""
        source = Path(source)
        if source.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
            raise ProjectError("不支持的图片格式。")
        copied = self._copy_unique(source, project / "images")
        rel = str(copied.relative_to(project)).replace("\\", "/")
        self.update_shot(project, shot_id, {"image": rel})
        return rel

    # ------------------------------------------------------------------
    # AI 出图 / 配音（V1.3）
    # ------------------------------------------------------------------
    def set_ai_image(self, project: Path, shot_id: str, source: Path) -> str:
        """记录 AI 生成画面的路径（文件已经放进 images/），并设为该镜头的画面。"""
        rel = str(Path(source).relative_to(project)).replace("\\", "/")
        data = self.migrate(self.load(project))[0]
        shot = self.find_shot(data, shot_id)
        shot["ai_image"] = rel
        shot["image"] = rel
        self.save(project, data)
        return rel

    def set_voice(self, project: Path, shot_id: str, source: Path,
                  duration_ms: int | None = None) -> str:
        """记录某镜头的配音片段（文件已经放进 audio/）。"""
        rel = str(Path(source).relative_to(project)).replace("\\", "/")
        data = self.migrate(self.load(project))[0]
        shot = self.find_shot(data, shot_id)
        shot["voice"] = rel
        shot["voice_ms"] = int(duration_ms) if duration_ms else None
        self.save(project, data)
        return rel

    def clear_voices(self, project: Path):
        """清除所有镜头配音（重新生成前调用）。"""
        data = self.migrate(self.load(project))[0]
        for shot in data["shots"]:
            shot["voice"] = None
            shot["voice_ms"] = None
        self.save(project, data)

    def set_narration(self, project: Path, source: Path) -> str:
        """设置旁白音轨，并清除逐镜头配音（整条音轨优先）。"""
        data = self.migrate(self.load(project))[0]
        rel = str(Path(source).relative_to(project)).replace("\\", "/")
        data["narration"] = rel
        for shot in data["shots"]:
            shot["voice"] = None
            shot["voice_ms"] = None
        self.save(project, data)
        return rel

    def voice_segments(self, data: dict) -> list[tuple[str, float, float]]:
        """返回 [(配音相对路径, 起点秒, 镜头时长秒)]，用于拼接旁白音轨。"""
        segments = []
        for shot in data.get("shots", []):
            voice = shot.get("voice")
            if voice:
                segments.append((voice, float(shot.get("start", 0)),
                                 float(shot.get("duration", 0))))
        return segments

    def voice_offset_ms(self, data: dict) -> int:
        """配音在镜头内的起始留白（毫秒），与 fit_durations_to_voice 保持一致。"""
        value = data.get("voice_offset_ms")
        return max(0, int(value)) if value is not None else VOICE_OFFSET_MS_DEFAULT

    def set_voice_offset(self, project: Path, offset_ms: int):
        data = self.migrate(self.load(project))[0]
        data["voice_offset_ms"] = max(0, int(offset_ms))
        self.save(project, data)

    def fit_durations_to_voice(self, project: Path,
                               offset_ms: int | None = None) -> tuple[list, list]:
        """按配音确定每镜时长。返回 (changed, extended)。

        V2.1 画面优先（settings.pacing == "picture"，默认）：
            新时长 = clamp(max(画面节奏时长, 留白 + 配音长度), 1.5, 8.0)
        即节奏以剧本给出的画面时长为准，旁白塞不下才延长；被延长的镜头
        放进 extended，界面提示「旁白偏长，可精简」。

        旧模式（pacing == "voice"）：
            新时长 = 留白 + 配音长度（旁白说完就切），extended 恒为空。

        changed / extended 均为 [(镜头 id, 原时长, 新时长), ...]。
        没有配音的镜头保持原时长。
        """
        data = self.migrate(self.load(project))[0]
        offset = self.voice_offset_ms(data) if offset_ms is None else max(0, int(offset_ms))
        pacing = data["settings"].get("pacing", "picture")
        picture_durations = self._picture_durations(data)
        changed, extended = [], []
        for shot in data["shots"]:
            ms = shot.get("voice_ms")
            if not shot.get("voice") or not ms:
                continue
            voice_need = (offset + int(ms)) / 1000.0
            if pacing == "picture":
                picture = picture_durations.get(shot["id"], float(shot.get("duration", DEFAULT_DURATION)))
                picture = min(PICTURE_MAX_DURATION, max(PICTURE_MIN_DURATION, picture))
                new_duration = round(min(PICTURE_EXTEND_MAX, max(picture, voice_need)), 3)
                if voice_need > picture + 0.01:
                    extended.append((shot["id"], picture, new_duration))
            else:
                new_duration = round(voice_need, 3)
            old_duration = float(shot.get("duration", 0))
            if abs(old_duration - new_duration) >= 0.01:
                shot["duration"] = new_duration
                changed.append((shot["id"], old_duration, new_duration))
        if changed:
            self.reflow(data)
            self.save(project, data)
        return changed, extended

    @staticmethod
    def _picture_durations(data: dict) -> dict:
        """从剧本取每个镜头的「画面节奏时长」，按 story_index 对应时间轴镜头。"""
        story_shots = ((data.get("story") or {}).get("shots") or [])
        by_index = {}
        for i, item in enumerate(story_shots, 1):
            try:
                by_index[int(item.get("index", i))] = float(item.get("duration", DEFAULT_DURATION))
            except (TypeError, ValueError):
                by_index[i] = DEFAULT_DURATION
        result = {}
        for shot in data.get("shots", []):
            index = shot.get("story_index")
            if index in by_index:
                result[shot["id"]] = by_index[index]
        return result

    def rebalance_durations(self, project: Path) -> list[tuple[str, float, float]]:
        """按剧本的画面节奏重排所有镜头时长（保留旁白完整性的下限）。

        画面时长被限制在 1.5~4.0 秒；有配音的镜头至少留够「留白 + 配音」，
        不足时最多延长到 PICTURE_EXTEND_MAX。
        """
        data = self.migrate(self.load(project))[0]
        picture_durations = self._picture_durations(data)
        if not picture_durations:
            return []
        offset = self.voice_offset_ms(data)
        changed = []
        for shot in data["shots"]:
            picture = picture_durations.get(shot["id"])
            if picture is None:
                continue
            picture = min(PICTURE_MAX_DURATION, max(PICTURE_MIN_DURATION, picture))
            new_duration = picture
            if shot.get("voice") and shot.get("voice_ms"):
                new_duration = min(PICTURE_EXTEND_MAX,
                                   max(picture, (offset + int(shot["voice_ms"])) / 1000.0))
            new_duration = round(new_duration, 3)
            old_duration = float(shot.get("duration", 0))
            if abs(old_duration - new_duration) >= 0.01:
                shot["duration"] = new_duration
                changed.append((shot["id"], old_duration, new_duration))
        if changed:
            self.reflow(data)
            self.save(project, data)
        return changed

    def pending_ai_shots(self, data: dict) -> list[dict]:
        """还没有 AI 画面、但有待生成描述（scene / narration）的镜头。"""
        return [s for s in data.get("shots", [])
                if not s.get("ai_image") and (s.get("scene") or s.get("narration"))]

    def cleared_ai_images(self, project: Path, shot_ids: list[str]):
        """把镜头的 AI 画面清掉（重新生成前），返回旧的相对路径列表。

        只清除来源是 AI 的图片；用户手动配的图保留不动。
        """
        data = self.migrate(self.load(project))[0]
        ids = set(shot_ids)
        removed = []
        for shot in data["shots"]:
            if shot.get("id") not in ids or not shot.get("ai_image"):
                continue
            old = shot["ai_image"]
            if shot.get("image") == old:
                shot["image"] = None
            shot["ai_image"] = None
            removed.append(old)
        self.save(project, data)
        return removed

    # ------------------------------------------------------------------
    # 时间轴
    # ------------------------------------------------------------------
    def reflow(self, data: dict) -> bool:
        """按顺序累计 start。返回是否有变化。"""
        changed = False
        cursor = 0.0
        for shot in data.get("shots", []):
            if round(shot.get("start", 0.0), 3) != round(cursor, 3):
                shot["start"] = round(cursor, 3)
                changed = True
            cursor += float(shot.get("duration", DEFAULT_DURATION))
        if round(data.get("total_duration", -1), 3) != round(cursor, 3):
            data["total_duration"] = round(cursor, 3)
            changed = True
        return changed

    def total_duration(self, data: dict) -> float:
        return round(sum(float(s.get("duration", 0)) for s in data.get("shots", [])), 3)

    # ------------------------------------------------------------------
    # 素材导入
    # ------------------------------------------------------------------
    def _copy_unique(self, source: Path, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        if target.exists():
            target = target_dir / f"{source.stem}_{datetime.now().strftime('%H%M%S%f')}{source.suffix}"
        shutil.copy2(source, target)
        return target

    @staticmethod
    def suggest_transition(shot: dict) -> str:
        """按运镜给默认转场：推镜配短淡入淡出，静止配硬切，留白镜配黑场。"""
        if not shot.get("voiced", True):
            return "fade"
        if shot.get("motion") in ("push-in", "diag-in", "pan-left", "pan-right"):
            return "dissolve"
        return "cut"

    def add_images(self, project: Path, sources: list[Path], default_duration: float = DEFAULT_DURATION) -> list[dict]:
        """复制图片到项目并追加为镜头。返回新追加的镜头列表。"""
        data = self.migrate(self.load(project))[0]
        added = []
        for source in sources:
            source = Path(source)
            if source.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
                continue
            copied = self._copy_unique(source, project / "images")
            rel = str(copied.relative_to(project)).replace("\\", "/")
            shot = self._make_shot(rel, default_duration)
            data["shots"].append(shot)
            added.append(shot)
        self.reflow(data)
        self.save(project, data)
        return added

    def set_media(self, project: Path, kind: str, source: Path):
        if kind not in {"narration", "music", "subtitle"}:
            raise ProjectError("不支持的素材类型。")
        source = Path(source)
        if not source.exists():
            raise ProjectError(f"素材文件不存在：{source}")
        if kind == "subtitle" and source.suffix.lower() != ".srt":
            raise ProjectError("字幕文件必须是 .srt 格式。")
        target_dir = project / ("subtitles" if kind == "subtitle" else "audio")
        copied = self._copy_unique(source, target_dir)
        data = self.migrate(self.load(project))[0]
        data[kind] = str(copied.relative_to(project)).replace("\\", "/")
        self.save(project, data)

    def clear_media(self, project: Path, kind: str):
        if kind not in {"narration", "music", "subtitle"}:
            raise ProjectError("不支持的素材类型。")
        data = self.migrate(self.load(project))[0]
        data[kind] = None
        self.save(project, data)

    # ------------------------------------------------------------------
    # 镜头编辑
    # ------------------------------------------------------------------
    def _shot_index(self, data: dict, shot_id: str) -> int:
        for i, shot in enumerate(data.get("shots", [])):
            if shot.get("id") == shot_id:
                return i
        raise ProjectError(f"找不到镜头：{shot_id}")

    def find_shot(self, data: dict, shot_id: str) -> dict:
        return data["shots"][self._shot_index(data, shot_id)]

    def move_shot(self, project: Path, shot_id: str, delta: int) -> int:
        """返回移动后的新下标；无法移动时返回原下标。"""
        data = self.migrate(self.load(project))[0]
        index = self._shot_index(data, shot_id)
        target = index + delta
        if 0 <= target < len(data["shots"]):
            data["shots"].insert(target, data["shots"].pop(index))
            index = target
        self.reflow(data)
        self.save(project, data)
        return index

    def delete_shots(self, project: Path, shot_ids: list[str]) -> list[str]:
        """删除镜头并返回被删镜头的图片相对路径（用于询问是否删除文件）。"""
        data = self.migrate(self.load(project))[0]
        ids = set(shot_ids)
        removed = [s for s in data["shots"] if s.get("id") in ids]
        data["shots"] = [s for s in data["shots"] if s.get("id") not in ids]
        self.reflow(data)
        self.save(project, data)
        return [s["image"] for s in removed if s.get("image")]

    def image_usage(self, data: dict, image: str) -> int:
        return sum(1 for s in data.get("shots", []) if s.get("image") == image)

    def duplicate_shot(self, project: Path, shot_id: str) -> list[str]:
        data = self.migrate(self.load(project))[0]
        index = self._shot_index(data, shot_id)
        shot = copy.deepcopy(data["shots"][index])
        shot["id"] = uuid.uuid4().hex[:8]
        data["shots"].insert(index + 1, shot)
        self.reflow(data)
        self.save(project, data)
        return [s.get("id") for s in data["shots"]]

    def split_shot(self, project: Path, shot_id: str, at: float) -> list[str]:
        """在镜头内部 at 秒处切分为两个镜头。返回新的镜头 id 列表。"""
        data = self.migrate(self.load(project))[0]
        index = self._shot_index(data, shot_id)
        shot = data["shots"][index]
        duration = float(shot["duration"])
        offset = float(at) - float(shot.get("start", 0.0))
        if not (MIN_DURATION <= offset <= duration - MIN_DURATION):
            raise ProjectError("切割点必须落在镜头内部。")
        left = copy.deepcopy(shot)
        right = copy.deepcopy(shot)
        left["id"] = uuid.uuid4().hex[:8]
        right["id"] = uuid.uuid4().hex[:8]
        left["duration"] = round(offset, 3)
        right["duration"] = round(duration - offset, 3)
        data["shots"][index:index + 1] = [left, right]
        self.reflow(data)
        self.save(project, data)
        return [s.get("id") for s in data["shots"]]

    def update_shot(self, project: Path, shot_id: str, changes: dict):
        allowed = {"duration", "zoom", "motion", "voiced", "transition", "subtitle", "image"}
        data = self.migrate(self.load(project))[0]
        shot = self.find_shot(data, shot_id)
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "duration":
                value = round(min(MAX_DURATION, max(MIN_DURATION, float(value))), 3)
            if key == "zoom" and value not in ZOOM_MODES:
                continue
            if key == "motion" and value not in MOTION_MODES:
                continue
            if key == "voiced" and not isinstance(value, bool):
                continue
            if key == "transition" and value not in TRANSITION_MODES:
                continue
            shot[key] = value
        self.reflow(data)
        self.save(project, data)

    def update_settings(self, project: Path, settings: dict):
        data = self.migrate(self.load(project))[0]
        for key in ("width", "height", "fps", "fit", "grain", "vignette",
                    "grade", "loudnorm", "bed_drone", "pacing"):
            if key not in settings:
                continue
            if key == "grade" and settings[key] not in GRADE_MODES:
                continue
            if key == "pacing" and settings[key] not in PACING_MODES:
                continue
            if key == "grain":
                try:
                    data["settings"][key] = max(0, min(10, int(settings[key])))
                except (TypeError, ValueError):
                    continue
                continue
            data["settings"][key] = settings[key]
        self.save(project, data)

    def replace_shots(self, project: Path, shots: list[dict]):
        """整体替换镜头列表（供测试 / 批量工具使用）。"""
        data = self.migrate(self.load(project))[0]
        data["shots"] = [s for s in (self._normalize_shot(x, []) for x in shots if x) if s]
        self.reflow(data)
        self.save(project, data)

    # ------------------------------------------------------------------
    # SRT 导出（V1.2：把时间轴旁白导出成 SRT）
    # ------------------------------------------------------------------
    def export_srt(self, project: Path, path: Path) -> Path:
        """把时间轴上的旁白按镜头起点导出 SRT 文件。"""
        data = self.migrate(self.load(project))[0]
        lines = []
        n = 0
        cursor = 0.0
        offset = self.voice_offset_ms(data) / 1000.0
        for shot in data["shots"]:
            dur = float(shot.get("duration", 0))
            text = (shot.get("narration") or "").strip()
            if text:
                n += 1
                # V2.1：有配音时字幕跟随配音（从留白后开始、留 0.3s 尾巴），
                # 没有配音时才铺满整镜
                voice_ms = shot.get("voice_ms")
                if shot.get("voice") and voice_ms:
                    start = cursor + offset
                    end = min(cursor + dur, start + int(voice_ms) / 1000.0 + 0.3)
                else:
                    start, end = cursor, cursor + dur
                lines.append(f"{n}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{text}")
            cursor += dur
        path.write_text("\n\n".join(lines) + ("\n" if lines else ""),
                        encoding="utf-8")
        return path


def _srt_ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


_SRT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def read_srt_cues(path: Path) -> list[tuple[float, float, str]]:
    """读取 SRT，返回 [(start, end, text)]，用于预览时叠加字幕。"""
    cues = []
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return cues
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        match = _SRT_TIME.findall(lines[1]) if "-->" in lines[1] else []
        if len(match) != 2:
            continue
        (h1, m1, s1, f1), (h2, m2, s2, f2) = match
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(f1.ljust(3, "0")) / 1000
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(f2.ljust(3, "0")) / 1000
        cues.append((start, end, "\n".join(lines[2:])))
    cues.sort(key=lambda c: c[0])
    return cues
