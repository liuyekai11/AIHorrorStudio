"""V3 P1 数据基础：原子写入 + Repository 基类 + 任务状态持久化。

V3 设计权威见 docs/architecture/v3_stage0/。本模块只落地 P1 需要的最小部分：

- write_json_atomic / read_json / write_text_atomic：统一原子写（tmp + replace），
  写入失败时原文件保持字节级不变，残留的临时文件在下次读写时清理；
- Repository 基类：业务代码只通过 Repository 访问 JSON，不直接 open() 实体文件；
- TaskStore：后台任务状态的持久化基础（只记录，不改变现有调度方式）；
- StoryRepository / VersionStore：Story 独立持久化与 StoryVersion 快照。

本模块不依赖 project_manager / story_engine 等上层模块（数据层不得反向依赖编排层）。
"""
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from modules import story_schema as ss

V3_SCHEMA_VERSION = ss.SCHEMA_VERSION + 1      # = 3：project.json 的 V3 结构版本

STORIES_DIR = "stories"
STORY_FILE = "story.json"
STORY_INDEX_DIR = "story"          # 派生索引 story/index.json（OQ-09 确认前的暂定布局）
STORY_INDEX_FILE = "index.json"
VERSIONS_DIR = "versions"
TASKS_DIR = ".tasks"

TASK_STATUSES = ("running", "succeeded", "failed", "cancelled")

_TMP_SUFFIX = ".tmp"


class RepositoryError(Exception):
    """数据层错误：调用方捕获后提示用户，不得静默继续。"""


# ----------------------------------------------------------------------
# 原子写入
# ----------------------------------------------------------------------
def _fsync(path: Path):
    try:
        with path.open("rb") as f:
            os.fsync(f.fileno())
    except OSError:
        pass


def write_text_atomic(path, text: str):
    """原子写文本：写同目录临时文件 → fsync → replace。

    失败时删除临时文件并抛出 OSError，目标文件保持原样（不存在则仍然不存在）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + _TMP_SUFFIX)
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_json_atomic(path, data):
    """原子写 JSON（UTF-8，不转义中文，2 空格缩进）。"""
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))


_READ_RETRIES = 5


def read_json(path, default=None):
    """读 JSON；文件不存在返回 default。格式损坏抛 RepositoryError（不返回半截数据）。

    Windows 上 replace 刚完成的文件偶发暂时占用，读失败会短暂重试。
    """
    path = Path(path)
    if not path.exists():
        return default
    text = None
    for attempt in range(_READ_RETRIES):
        try:
            text = path.read_text(encoding="utf-8")
            break
        except PermissionError:
            if attempt == _READ_RETRIES - 1:
                raise RepositoryError(f"无法读取 {path.name}：文件被占用") from None
            time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            raise RepositoryError(f"无法读取 {path.name}：{exc}") from exc
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RepositoryError(f"{path.name} 格式损坏：{exc}") from exc


def cleanup_stale_temps(root):
    """清理上次写入中断留下的 *.tmp（只清临时文件，不碰任何实体文件）。返回清理数量。"""
    root = Path(root)
    if not root.exists():
        return 0
    count = 0
    for path in root.rglob("*" + _TMP_SUFFIX):
        try:
            if path.is_file():
                path.unlink()
                count += 1
        except OSError:
            pass
    return count


def _validate_id(value, label: str) -> str:
    """稳定 ID 直接作为文件名：必须是安全的单段名称。"""
    text = str(value or "").strip()
    if not text or text in (".", "..") or any(c in text for c in '\\/:*?"<>|'):
        raise RepositoryError(f"{label} 不合法：{value!r}")
    return text


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


# ----------------------------------------------------------------------
# Story 校验与默认值
# ----------------------------------------------------------------------
def new_story(*, story_id: str, project_id: str, title: str = "未命名故事",
              origin: str = "new", now: str | None = None) -> dict:
    """新建一个空 Story（没有 shot 时 is_valid_story() 为 False，直到有分镜）。"""
    stamp = now or _now()
    return {
        "schema_version": ss.SCHEMA_VERSION,   # story 结构版本（沿用 V2.2 的 story_schema）
        "story_id": _validate_id(story_id, "story_id"),
        "project_id": str(project_id or ""),
        "title": str(title or "未命名故事"),
        "logline": "",
        "keywords": "",
        "created_at": stamp,
        "updated_at": stamp,
        "origin": str(origin or "new"),
        "generated_at": "",
        "model": "",
        "characters": [],
        "scenes": [],
        "shots": [],
        "concepts": [],
        "concept": None,
        "plan": None,
        "script": [],
        "pacing": None,
        "quality": None,
        "stale": {},
        "versions": [],
        "active_version": "",
    }


def is_valid_story(story) -> bool:
    return isinstance(story, dict) and bool(story.get("shots"))


def normalize_story(story: dict, *, story_id: str, project_id: str) -> dict:
    """把任意来源（V3 P1 / V2 / 手工）的 story 规范成可落盘的 V3 story。

    - 缺 story_id 时用参数补齐（不改已有 story_id）；
    - 用 story_schema.upgrade_story 升级到 V2.2 结构（兼容入口，旧字段保留）；
    - 原字段全部保留（只增不删），未知字段原样写回。
    """
    if not isinstance(story, dict):
        raise RepositoryError("story 必须是 JSON 对象")
    data = _clone(story)
    try:
        upgraded, _changed = ss.upgrade_story(data)
    except (ss.SchemaError, TypeError, ValueError):
        upgraded = data          # 结构异常也原样保存，交由人工审核（不静默清空）
    if not isinstance(upgraded, dict):
        upgraded = data
    upgraded = _clone(upgraded)
    upgraded.setdefault("story_id", _validate_id(story_id, "story_id"))
    upgraded["story_id"] = _validate_id(upgraded["story_id"], "story_id")
    upgraded.setdefault("project_id", str(project_id or ""))
    upgraded.setdefault("title", "未命名故事")
    upgraded.setdefault("origin", "import")
    upgraded.setdefault("created_at", _now())
    upgraded["schema_version"] = ss.SCHEMA_VERSION
    for key in ("characters", "scenes", "shots", "concepts", "script"):
        if not isinstance(upgraded.get(key), list):
            upgraded[key] = []
    for key in ("versions",):
        if not isinstance(upgraded.get(key), list):
            upgraded[key] = []
    upgraded.setdefault("active_version", "")
    upgraded.setdefault("stale", {})
    upgraded.setdefault("updated_at", upgraded.get("created_at") or _now())
    return upgraded


# ----------------------------------------------------------------------
# Repository 基类
# ----------------------------------------------------------------------
class Attribution:
    """把「当前正在读写哪个项目」告知 V3 层（只记录，不改变 V2 的接口）。

    ProjectManager.load(project) / save(project, data) 在最外层调用时设置，
    migrate() -> V3 hook 据此判断能否在写盘前初始化主 Story。
    """

    project: Path | None = None
    depth: int = 0          # V3 自己写盘时的嵌套层级（>0 表示不参与对账）
    _stack: list = []

    @classmethod
    def set_project(cls, project):
        cls._stack.append((cls.project, cls.depth))
        cls.project = Path(project) if project is not None else None

    @classmethod
    def restore(cls):
        if cls._stack:
            cls.project, cls.depth = cls._stack.pop()

    @classmethod
    def enter(cls, reason: str = ""):
        cls.depth += 1

    @classmethod
    def leave(cls):
        cls.depth = max(0, cls.depth - 1)


class Repository:
    """目录化 JSON 数据访问基类。

    子类实现 _path(...) 决定文件位置；读写统一走原子写与严格 JSON 读取。
    Repository 只做数据访问，不承载业务规则。
    """

    def save_json(self, path: Path, data):
        write_json_atomic(path, data)

    def load_json(self, path: Path, default=None):
        return read_json(path, default)


# ----------------------------------------------------------------------
# Story 独立持久化
# ----------------------------------------------------------------------
class StoryRepository(Repository):
    """Story 持久化：stories/<story_id>/story.json + 派生索引 story/index.json。

    - Story 是独立文件，不再依赖 project.json 的 "story" 字段；
    - index.json 只做派生索引，文件丢失 / 损坏时可从目录扫描重建；
    - delete() 用归档（move 到项目外 .trash/）而不是直接删除。
    """

    TRASH_DIR = ".trash"

    def __init__(self, project: Path):
        self.project = Path(project)

    # -- 路径 ----------------------------------------------------------
    def stories_root(self) -> Path:
        return self.project / STORIES_DIR

    def story_dir(self, story_id: str) -> Path:
        return self.stories_root() / _validate_id(story_id, "story_id")

    def story_file(self, story_id: str) -> Path:
        return self.story_dir(story_id) / STORY_FILE

    def _index_file(self) -> Path:
        return self.project / STORY_INDEX_DIR / STORY_INDEX_FILE

    # -- 索引 ----------------------------------------------------------
    def _index_entry(self, story: dict) -> dict:
        shots = story.get("shots") or []
        return {
            "story_id": story.get("story_id"),
            "title": story.get("title", ""),
            "created_at": story.get("created_at", ""),
            "updated_at": story.get("updated_at", ""),
            "shot_count": len(shots),
            "has_story": bool(shots),
        }

    def rebuild_index(self) -> dict:
        """从目录扫描重建 index.json（唯一天真源是 stories/*/story.json）。"""
        entries = []
        root = self.stories_root()
        if root.exists():
            for folder in sorted(root.iterdir()):
                path = folder / STORY_FILE
                if not folder.is_dir() or not path.exists():
                    continue
                try:
                    story = read_json(path)
                except RepositoryError:
                    entries.append({"story_id": folder.name, "title": "", "corrupt": True})
                    continue
                if isinstance(story, dict):
                    entries.append(self._index_entry(story))
        index = {"schema_version": V3_SCHEMA_VERSION, "stories": entries}
        write_json_atomic(self._index_file(), index)
        return index

    def _sync_index(self, story: dict):
        index = None
        try:
            index = read_json(self._index_file())
        except RepositoryError:
            index = None
        if not isinstance(index, dict) or not isinstance(index.get("stories"), list):
            index = self.rebuild_index()
        entry = self._index_entry(story)
        stories = [e for e in index.get("stories") or []
                   if isinstance(e, dict) and e.get("story_id") != entry["story_id"]]
        stories.append(entry)
        index["schema_version"] = V3_SCHEMA_VERSION
        index["stories"] = stories
        write_json_atomic(self._index_file(), index)

    # -- 读写 ----------------------------------------------------------
    def exists(self, story_id: str) -> bool:
        return self.story_file(story_id).exists()

    def get(self, story_id: str) -> dict | None:
        return read_json(self.story_file(story_id))

    def list(self) -> list[dict]:
        """列出全部 story（按 created_at 排序，缺失的排在前面）。"""
        result = []
        root = self.stories_root()
        if not root.exists():
            return result
        for folder in root.iterdir():
            path = folder / STORY_FILE
            if not folder.is_dir() or not path.exists():
                continue
            try:
                story = read_json(path)
            except RepositoryError:
                continue
            if isinstance(story, dict):
                result.append(story)
        result.sort(key=lambda s: (str(s.get("created_at") or ""), str(s.get("story_id") or "")))
        return result

    def create(self, story: dict) -> dict:
        story = _clone(story)
        story_id = _validate_id(story.get("story_id"), "story_id")
        if self.exists(story_id):
            raise RepositoryError(f"story 已存在：{story_id}")
        story["updated_at"] = story.get("updated_at") or _now()
        write_json_atomic(self.story_file(story_id), story)
        self._sync_index(story)
        return story

    def update(self, story_id: str, story: dict) -> dict:
        """整体覆盖写入（调用方负责先 read-modify）。story_id 不允许改变。"""
        story_id = _validate_id(story_id, "story_id")
        if not self.exists(story_id):
            raise RepositoryError(f"story 不存在：{story_id}")
        data = _clone(story)
        if str(data.get("story_id") or story_id) != story_id:
            raise RepositoryError("不允许修改 story_id")
        data["story_id"] = story_id
        data["updated_at"] = _now()
        write_json_atomic(self.story_file(story_id), data)
        self._sync_index(data)
        return data

    def archive(self, story_id: str) -> Path:
        """归档（不直接删除）：整个 story 目录移动到项目外 .trash/。"""
        folder = self.story_dir(story_id)
        if not folder.exists():
            raise RepositoryError(f"story 不存在：{story_id}")
        target_root = self.project.parent / self.TRASH_DIR
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / f"{story_id}-{datetime.now():%Y%m%d-%H%M%S}"
        folder.rename(target)
        self.rebuild_index()
        return target


# ----------------------------------------------------------------------
# StoryVersion 快照
# ----------------------------------------------------------------------
class VersionStore(Repository):
    """Story 级快照：versions/<version_id>.json（沿用 V2 目录与 10 版上限语义）。

    与 V2 ProjectManager.save_version 的区别：快照直接来自 stories/<id>/story.json，
    不再需要 project.json 里有 story 才能存；被 active_version / base_version 链
    引用的版本不裁剪。
    """

    def __init__(self, project: Path, stories: StoryRepository | None = None,
                 limit: int = 10):
        self.project = Path(project)
        self.stories = stories or StoryRepository(self.project)
        self.limit = max(1, int(limit))

    def versions_root(self) -> Path:
        return self.project / VERSIONS_DIR

    def version_file(self, version_id: str) -> Path:
        return self.versions_root() / f"{_validate_id(version_id, 'version_id')}.json"

    def list(self, story_id: str) -> list[dict]:
        """story 内 [versions] 记录（新的在前）。"""
        story = self.stories.get(story_id) or {}
        entries = [v for v in story.get("versions") or [] if isinstance(v, dict)]
        return list(reversed(entries))

    def snapshot(self, story_id: str, note: str = "", official: bool = True) -> dict:
        """把当前 story 存成快照，并把版本条目追加到 story["versions"]。"""
        story = self.stories.get(story_id)
        if not isinstance(story, dict):
            raise RepositoryError(f"story 不存在：{story_id}")
        versions = story.get("versions") if isinstance(story.get("versions"), list) else []
        stamp = datetime.now()
        version_id = f"v{stamp:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        payload = _clone(story)
        payload.pop("versions", None)
        payload.pop("active_version", None)
        payload["version_id"] = version_id
        payload["created_at"] = stamp.isoformat(timespec="seconds")
        payload["note"] = note or ""
        payload["official"] = bool(official)
        write_json_atomic(self.version_file(version_id), payload)
        quality = story.get("quality") if isinstance(story.get("quality"), dict) else {}
        entry = {
            "version_id": version_id,
            "created_at": payload["created_at"],
            "note": note or "",
            "official": bool(official),
            "title": story.get("title", ""),
            "shot_count": len(story.get("shots") or []),
            "total_duration": round(sum(float(s.get("duration") or 0)
                                        for s in story.get("shots") or []
                                        if isinstance(s, dict)), 2),
            "score": quality.get("score"),
            "file": f"{VERSIONS_DIR}/{version_id}.json",
        }
        story["versions"] = versions + [entry]
        self._prune(story)
        self.stories.update(story_id, story)
        return entry

    def _prune(self, story: dict):
        """按正式版本数裁剪（与 V2 OFFICIAL_VERSION_LIMIT 语义一致）。"""
        versions = story.get("versions") or []
        official = [v for v in versions if isinstance(v, dict) and v.get("official")]
        excess = len(official) - self.limit
        if excess <= 0:
            return
        active = str(story.get("active_version") or "")
        referenced = {str(v.get("base_version") or "") for v in versions if isinstance(v, dict)}
        doomed = []
        for entry in official:                 # 按时间顺序追加，从最旧的开始
            if len(doomed) >= excess:
                break
            vid = str(entry.get("version_id") or "")
            if vid == active or vid in referenced:
                continue
            doomed.append(entry)
        for entry in doomed:
            try:
                self.version_file(entry.get("version_id", "")).unlink()
            except OSError:
                pass
        doomed_ids = {e.get("version_id") for e in doomed}
        story["versions"] = [v for v in versions
                             if not (isinstance(v, dict) and v.get("version_id") in doomed_ids)]

    def load(self, version_id: str) -> dict:
        snapshot = read_json(self.version_file(version_id))
        if not isinstance(snapshot, dict):
            raise RepositoryError(f"版本 {version_id} 不存在")
        return snapshot

    def restore(self, story_id: str, version_id: str) -> dict:
        """恢复到指定版本；恢复前先备份当前状态（回到旧状态可再切回）。"""
        snapshot = self.load(version_id)
        if str(snapshot.get("story_id") or story_id) != str(story_id):
            raise RepositoryError("版本不属于该 story")
        before = self.snapshot(story_id, note="恢复前自动备份", official=False)
        current = self.stories.get(story_id) or {}
        restored = _clone(snapshot)
        restored.pop("version_id", None)
        # 版本列表以当前 story 为准（快照里没有 versions / active_version）
        restored["versions"] = _clone(current.get("versions") or [])
        restored["story_id"] = story_id
        self.stories.update(story_id, restored)
        entry = self.snapshot(story_id, note=f"恢复自 {version_id}", official=False)
        story = self.stories.get(story_id) or {}
        for item in story.get("versions") or []:
            if isinstance(item, dict) and item.get("version_id") == entry["version_id"]:
                item["base_version"] = version_id
        story["active_version"] = entry["version_id"]
        self.stories.update(story_id, story)
        result = dict(entry)
        result["previous"] = before.get("version_id")
        return result


# ----------------------------------------------------------------------
# 任务状态持久化
# ----------------------------------------------------------------------
class TaskStore(Repository):
    """后台任务状态记录：.tasks/<task_id>.json。

    只是持久化基础（用于崩溃后诊断与 UI 展示），不替代现有的线程调度。
    mark_abandoned() 用于识别上次进程异常退出时残留的 running 记录。
    """

    def __init__(self, project: Path):
        self.project = Path(project)

    def mark_abandoned(self, note: str = "上次运行未正常结束") -> int:
        """把所有残留的 running 记录标成 failed（进程崩溃后调用）。返回修改数量。"""
        count = 0
        for record in self.list():
            if record.get("status") != "running":
                continue
            try:
                self.finish(record.get("task_id", ""), "failed", note)
                count += 1
            except RepositoryError:
                continue
        return count

    def _root(self) -> Path:
        return self.project / TASKS_DIR

    def _file(self, task_id: str) -> Path:
        return self._root() / f"{_validate_id(task_id, 'task_id')}.json"

    def start(self, kind: str, note: str = "", task_id: str | None = None) -> dict:
        stamp = _now()
        record = {
            "task_id": task_id or uuid.uuid4().hex[:12],
            "kind": str(kind or ""),
            "note": note or "",
            "status": "running",
            "created_at": stamp,
            "updated_at": stamp,
            "error": "",
        }
        write_json_atomic(self._file(record["task_id"]), record)
        return record

    def get(self, task_id: str) -> dict | None:
        return read_json(self._file(task_id))

    def finish(self, task_id: str, status: str, error: str = "") -> dict:
        if status not in TASK_STATUSES:
            raise RepositoryError(f"未知任务状态：{status}")
        record = read_json(self._file(task_id))
        if not isinstance(record, dict):
            raise RepositoryError(f"任务不存在：{task_id}")
        record["status"] = status
        record["error"] = str(error or "")
        record["updated_at"] = _now()
        write_json_atomic(self._file(task_id), record)
        return record

    def list(self) -> list[dict]:
        root = self._root()
        if not root.exists():
            return []
        records = []
        for path in root.glob("*.json"):
            try:
                record = read_json(path)
            except RepositoryError:
                continue
            if isinstance(record, dict):
                records.append(record)
        records.sort(key=lambda r: str(r.get("created_at") or ""))
        return records


# ----------------------------------------------------------------------
# V3 项目：主 Story 的原子初始化与驻留
# ----------------------------------------------------------------------
V3_LAYOUT_DIRS = (STORIES_DIR, STORY_INDEX_DIR, VERSIONS_DIR)
PRIMARY_STORY_ID = "story"          # 主 Story 的稳定 ID（OQ-06 确认前固定，不随项目重命名变化）
V3_LAYOUT_MARKER = ".v3_layout"
_V2_CODE_VERSION = 2                # V2 代码理解的 project.json 版本（对 V2 代码透明）

# 属于 stories/<id>/story.json 自有文件的字段：project.json 的 story 副本与快照都不保存
_OWN_KEYS = ("story_id", "project_id", "origin")


class V3ProjectManager(Repository):
    """V3 项目初始化：Project 与主 Story 固定 1:1（模型层仍允许 1:N）。

    初始化顺序（任一步失败 -> 回滚到初始化前状态）：
      1. stories/ story/ versions/ 目录（已存在则不记录，回滚时不删旧目录）
      2. stories/<id>/story.json + story/index.json
      3. project.json 切换到 schema_version=3（写主 Story 元信息）

    兼容：
      - V2 项目（schema_version=2）打开时 load() 只读补齐主 Story，不写盘；
        写盘由 ProjectManager.save() 的 migrate 完成（沿用 V2「打开即升级」语义）；
      - 未来版本（>3）只读，拒绝任何初始化 / 写回。
    """

    def __init__(self, project: Path, stories: StoryRepository | None = None):
        self.project = Path(project)
        self.stories = stories or StoryRepository(self.project)

    # -- 状态 ----------------------------------------------------------
    def schema_version(self) -> int | None:
        data = read_json(self.project / "project.json", {})
        value = data.get("schema_version") if isinstance(data, dict) else None
        return value if isinstance(value, int) else None

    def is_v3(self) -> bool:
        return self.schema_version() == V3_SCHEMA_VERSION

    def primary_story_id(self) -> str:
        data = read_json(self.project / "project.json", {}) or {}
        pid = str(data.get("primary_story_id") or "")
        return pid if pid and self.stories.exists(pid) else ""

    def get_primary_story(self) -> dict | None:
        pid = self.primary_story_id()
        return self.stories.get(pid) if pid else None

    # -- 打开 ----------------------------------------------------------
    def load(self, data: dict) -> tuple[dict, bool]:
        """打开项目时的 V3 处理。返回 (data, changed)；V2 / 未来版本 / 旧版本原样返回。"""
        version = data.get("schema_version")
        if not isinstance(version, int):
            return data, False
        if version > V3_SCHEMA_VERSION:
            return data, False
        v2_transparent = version in (2, V3_SCHEMA_VERSION)
        if v2_transparent:
            # V3 项目（以及满载 V3 布局的 V2 项目）对 V2 代码透明：
            # 内存里的 schema_version 一律报 2，写盘时再映射回 V3
            data["schema_version"] = _V2_CODE_VERSION
        if version < 2:
            # 旧版本交给 ProjectManager.migrate 先升到 V2
            data["schema_version"] = _V2_CODE_VERSION
            return data, False
        if not (self.project / STORIES_DIR).exists():
            # 还没有 stories/ 的 V2 项目：用 V2 故事（没有则空骨架）补主 Story，
            # 写盘时由 init_primary_story 一次性初始化
            self._assign_primary(data)
            return data, False
        try:
            story = self.get_primary_story()
        except RepositoryError:
            story = None
        if version == 2:
            if story is None and is_valid_story(data.get("story")):
                # V2 项目有故事：只在内存里补主 Story，并在 migrate 时写盘
                self._assign_primary(data)
                return data, False
            if story is not None:
                return self._hydrate(data, story, version=2)
            self._assign_primary(data)
            return data, False
        # V3 项目
        if story is not None:
            return self._hydrate(data, story, version=3)
        # 主 Story 缺失：V3 项目不得没有主 Story，进入修复流程
        if is_valid_story(data.get("story")):
            self._assign_primary(data)
            return data, True
        raise RepositoryError(
            "V3 项目缺少主 Story，且 project.json 中也没有可恢复的故事。"
            "项目已按损坏处理，请从 versions/ 手工恢复或联系维护者。")

    def _hydrate(self, data: dict, story: dict, *, version: int) -> tuple[dict, bool]:
        changed = False
        entries = [e for e in data.get("stories") or [] if isinstance(e, dict)]
        if data.get("primary_story_id") != story["story_id"]:
            data["primary_story_id"] = story["story_id"]
            changed = True
        if not any(e.get("story_id") == story["story_id"] for e in entries):
            entries.append(self._meta_entry(story))
            data["stories"] = entries
            changed = True
        if version == 2 and Attribution.depth:
            # V2 -> V3（仅在 V3 自己写盘时，同一份数据重新渲染 story 字段）
            data["story"] = self.render_story_field(story)
            data["schema_version"] = _V2_CODE_VERSION   # V3 项目对 V2 代码透明
            return data, True
        if version == 2:
            # V2 项目（stories/ 是 migrate 写盘时初始化的骨架）对 V2 代码透明：
            # story 字段保持 V2 结构，schema_version 保持 2，不做对账
            current = data.get("story")
            incoming = data.pop("story_schema_version", None)
            upgraded = isinstance(incoming, int) and incoming < ss.SCHEMA_VERSION
            if upgraded and not Attribution.depth:
                # 磁盘上的 story 已是当前结构（migrate 刚升级）：升级快照由
                # ProjectManager 补记
                data["_v3_upgraded"] = True
                changed = True
            if is_valid_story(current) \
                    and (not is_valid_story(story)
                         or story.get("schema_version") != ss.SCHEMA_VERSION):
                # stories/ 还是旧结构 / 空骨架、project.json 有故事：以 project.json 为准
                # （V3 代码的加载路径会把当前结构同步进 stories/）
                data["_v3_adopt"] = current
                changed = True
            elif current is None and is_valid_story(story):
                # 骨架写回 project.json，使「有项目就有主 Story」在数据层也成立
                data["story"] = _clone(story)
                changed = True
            elif is_valid_story(current) and not is_valid_story(story):
                # project.json 有故事、stories/ 还是初始化时的空骨架：写盘时采纳
                data["_v3_adopt"] = current
                changed = True
            return data, changed
        current = data.get("story")
        adopted = bool(data.get("_v3_adopt"))
        if version == 3 and adopted and is_valid_story(current):
            # 本次内存里的 story 是权威值（刚由 project.json 采纳 / 刚升级）：保留，
            # 不拿 stories/ 里可能过时的内容覆盖（写盘时 sync_story 会写回 stories/）
            return data, changed
        if version == 3 and not is_valid_story(story) \
                and not is_valid_story(current) \
                and not self.stories.exists(story["story_id"]):
            # 主 Story 已被归档（骨架还在但文件已移走）：项目不能没有主 Story，先重建
            try:
                self.init_primary_story(project=self.project)
            except (RepositoryError, OSError):
                raise RepositoryError(f"主 Story 文件缺失：{story['story_id']}")
            story = self.stories.get(story["story_id"]) or story
        theirs = (self.render_story_field(story)
                  if is_valid_story(story) else None)
        if current is None or not is_valid_story(current):
            # stories/ 里有故事：补进 project.json（空骨架不必往 project.json 写 None）
            if theirs is not None:
                data["story"] = _clone(theirs)
                changed = True
        elif theirs is None:
            # stories/ 还是初始化时的空骨架、project.json 有故事：采纳 project.json
            # （V2 代码直接写 story / 外部手改 project.json 的情况）
            if not self.stories.exists(story["story_id"]):
                raise RepositoryError(f"主 Story 文件缺失：{story['story_id']}")
            data["_v3_adopt"] = current
            changed = True
        elif self._story_view(current) != self._story_view(story):
            # 双写不一致：stories/ 是唯一真源
            data["story"] = _clone(theirs)
            changed = True
        return data, changed

    @staticmethod
    def render_story_field(story: dict) -> dict:
        """V3 story -> project.json 的 story 字段（去掉 V3 自有的 ID 字段）。"""
        rendered = {k: _clone(v) for k, v in story.items() if k not in _OWN_KEYS}
        rendered["schema_version"] = ss.SCHEMA_VERSION
        return rendered

    @staticmethod
    def _story_view(story) -> dict | None:
        """比较用的 story 视图：去掉 V3 自有字段。"""
        if not isinstance(story, dict):
            return None
        return {k: v for k, v in story.items() if k not in _OWN_KEYS}

    @staticmethod
    def _absorb(skeleton: dict, source: dict) -> dict:
        """把 source 的内容并入已有的 story 骨架（保留 story_id / created_at 等身份字段）。"""
        merged = _clone(source)
        for key in _OWN_KEYS + ("schema_version",):
            merged.pop(key, None)
        result = _clone(skeleton)
        result.update(merged)
        result["schema_version"] = ss.SCHEMA_VERSION
        return result

    # -- 创建 ----------------------------------------------------------
    def init_primary_story(self, project: Path | None = None, data: dict | None = None) -> dict:
        """原子初始化主 Story，成功后 project.json 变为 schema_version=3。"""
        project = Path(project or self.project)
        if data is None:
            data = read_json(project / "project.json", {}) or {}
        version = data.get("schema_version")
        if isinstance(version, int) and version > V3_SCHEMA_VERSION:
            raise RepositoryError(f"项目数据版本 {version} 高于 {V3_SCHEMA_VERSION}，只读。")
        pid = str(data.get("primary_story_id") or "")
        if isinstance(version, int) and version == V3_SCHEMA_VERSION and pid \
                and StoryRepository(project).exists(pid):
            return data                    # 已初始化，幂等

        created_dirs = []
        for name in V3_LAYOUT_DIRS:
            path = project / name
            if path.exists():
                continue
            path.mkdir(parents=True)
            created_dirs.append(path)
        marker = project / V3_LAYOUT_MARKER
        marker_created = not marker.exists()
        story = None
        created = False
        try:
            source = data.get("story")
            if self.stories.exists(PRIMARY_STORY_ID):
                # story 文件已在但不属于本事务：不覆盖、不回滚它
                story = self.stories.get(PRIMARY_STORY_ID)
                if story is None:
                    raise RepositoryError(f"主 Story 文件损坏：{PRIMARY_STORY_ID}")
            elif is_valid_story(source):
                story = normalize_story(source, story_id=PRIMARY_STORY_ID,
                                        project_id=str(data.get("name") or ""))
                story["origin"] = "v2"
                self.stories.create(story)
                created = True
            else:
                story = new_story(story_id=PRIMARY_STORY_ID,
                                  project_id=str(data.get("name") or ""),
                                  title=str(data.get("name") or "未命名故事"))
                self.stories.create(story)
                created = True
            if marker_created:
                write_text_atomic(marker, f"{V3_SCHEMA_VERSION}\n{_now()}\n")

            new_data = _clone(data)
            new_data["schema_version"] = V3_SCHEMA_VERSION
            new_data["primary_story_id"] = PRIMARY_STORY_ID
            new_data["stories"] = [self._meta_entry(story)]
            if playable(story):
                new_data["story"] = self.render_story_field(story)
            write_json_atomic(project / "project.json", new_data)
            return new_data
        except BaseException:
            # 只撤掉本次创建的东西：新 story、新标记、新目录
            if created:
                try:
                    self.stories.archive(PRIMARY_STORY_ID)
                except (RepositoryError, OSError):
                    pass
            if marker_created:
                try:
                    marker.unlink()
                except OSError:
                    pass
            for path in reversed(created_dirs):
                try:
                    if path.exists() and not any(path.iterdir()):
                        path.rmdir()
                except OSError:
                    pass
            raise

    def _assign_primary(self, data: dict):
        data["primary_story_id"] = PRIMARY_STORY_ID
        story = data.get("story")
        data["stories"] = ([{"story_id": PRIMARY_STORY_ID,
                             "title": str(story.get("title") or "")}]
                           if isinstance(story, dict) else [])

    @staticmethod
    def _meta_entry(story: dict) -> dict:
        return {
            "story_id": story.get("story_id"),
            "title": story.get("title", ""),
            "created_at": story.get("created_at", ""),
            "updated_at": story.get("updated_at", ""),
            "shot_count": len(story.get("shots") or []),
            "origin": story.get("origin", ""),
            "versions": _clone(story.get("versions") or []),
            "active_version": str(story.get("active_version") or ""),
        }


def playable(story) -> bool:
    """story 是否同步到 project.json 的 story 字段（V2 界面按 shot 判断有没有故事）。"""
    return is_valid_story(story)


def sync_story(project: Path, data: dict) -> bool:
    """写 project.json 之前：把内存里的 story 同步到 stories/<id>/story.json。

    - 调用方直接改了 data["story"]（V2 旧代码、恢复版本、外部导入）：以内存为准
      并入 stories/ 的骨架，保证两份数据一致；
    - 没改（与 stories/ 相同）：不写，避免每次保存都增加写入；
    - data["_v3_adopt"]：本次内存里的 story 是权威值（刚升级 / 刚采纳），无条件写回；
    - 旧结构（schema_version 落后）且结构没升级成功的 story：不写进 stories/，
      免得给旧内容贴上当前版本号，让之后的对账误以为 stories/ 是新结构。
    stories/ 写失败只影响本次同步：project.json 照常保存，打开时会再次对账。
    """
    adopt = bool(data.pop("_v3_adopt", None))   # 写盘前清理内部标记
    data.pop("_v3_upgraded", None)
    pid = str(data.get("primary_story_id") or "")
    story = data.get("story")
    if not pid or not isinstance(story, dict) or not is_valid_story(story):
        return False
    if not adopt:
        version = story.get("schema_version")
        if isinstance(version, int) and version < ss.SCHEMA_VERSION:
            # 旧结构原样留在 project.json，等打开时由 migrate 升级后再写回 stories/
            return False
    stories = StoryRepository(Path(project))
    try:
        existing = stories.get(pid)
        if not isinstance(existing, dict):
            # 主 Story 还没初始化（V2 项目首次写盘）：此时 project.json 就是真源，
            # 用这份数据建主 Story（资产丢失也能从 project.json 自愈）
            story = normalize_story(story, story_id=pid,
                                    project_id=str(data.get("name") or ""))
            stories.create(story)
            return True
        if not adopt \
                and V3ProjectManager._story_view(story) == V3ProjectManager._story_view(existing):
            return False
        stories.update(pid, V3ProjectManager._absorb(existing, story))
        return True
    except (RepositoryError, OSError):
        return False
