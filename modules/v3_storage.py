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
import shutil
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


class CorruptDataError(RepositoryError):
    """文件存在但内容损坏（不是合法 JSON）。

    区别于「暂时读不了」（占用 / 权限）：只有确认损坏才进入 P1-03 的恢复流程，
    避免把暂时被锁的好文件当作损坏覆盖。
    """


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
        raise CorruptDataError(f"{path.name} 格式损坏：{exc}") from exc


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


def is_structural_story(story) -> bool:
    """Story 的**结构**可用：JSON 已解析为 dict，且 `shots` 是镜头列表。

    与 is_valid_story 的分工（P1-Fix-2 / R-A2）：
    - is_valid_story（业务有效）：结构可用且至少有一个镜头 —— 用于「有没有故事」；
    - is_structural_story（结构可用）：只看结构，不看内容 —— 用于「文件是否损坏」。
      `shots: []`（空骨架）结构上是**合法**的（new_story 就这么建），不算损坏；
      `shots: "not-a-list"` / 根对象不是 dict 是结构损坏，必须走隔离 + 恢复。
    """
    return isinstance(story, dict) and isinstance(story.get("shots"), list)


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
# 未来版本只读保护（P1-Fix / P1-02）
# ----------------------------------------------------------------------
#: 写入检查看到的实际磁盘版本（测试与排障用；只记录，不参与判定）
_last_write_check: dict = {}


def assert_writable(project, what: str = "项目数据"):
    """任何业务数据写入前的统一检查：**只看磁盘上 project.json 的真实版本号**。

    - 磁盘版本 > V3_SCHEMA_VERSION（未来版本）：拒绝写入，抛 RepositoryError；
    - 其余情况（2 / 3 / 文件损坏）照常放行，老逻辑负责迁移与容错；
    - 不读内存里的 schema_version：V3 对 V2 代码透明时内存恒为 2，不能作为依据。
    """
    project = Path(project)
    path = project / "project.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 还没落盘 / 读不了 / 损坏：都不是「未来版本」，放行，
        # 由老逻辑负责初始化、迁移与损坏报告（不能因此挡住项目创建）
        return
    version = raw.get("schema_version") if isinstance(raw, dict) else None
    if not isinstance(version, int):
        return
    _last_write_check[project] = version
    if version > V3_SCHEMA_VERSION:
        raise RepositoryError(
            f"{what}：项目数据版本 {version} 高于当前程序支持的 {V3_SCHEMA_VERSION}，"
            "已按只读方式打开，拒绝写入。")


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
        assert_writable(self.project, "重建 Story 索引")
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
        assert_writable(self.project, "更新 Story 索引")
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
        assert_writable(self.project, "新建 Story")
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
        assert_writable(self.project, "保存 Story")
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
        assert_writable(self.project, "归档 Story")
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
        assert_writable(self.project, "创建版本快照")
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
        assert_writable(self.project, "恢复版本")
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

    未来版本只读边界（P1-02 / P1-Fix-2 R-T1 最终决策）：`.tasks/` 是运行任务的
    **过程**元数据，不是项目业务数据（不影响 Project / Story / 版本快照的内容与
    版本号），不纳入未来版本只读保护——start() / finish() 恒可写，只读打开的项目
    仍可记录「某个任务尝试运行过 / 结果如何」。
    唯一例外是 mark_abandoned()：它发生在**启动时**，代表一次项目级写操作
    （把上次残留状态标成 failed），保留 assert_writable 守卫。
    """

    def __init__(self, project: Path):
        self.project = Path(project)

    def mark_abandoned(self, note: str = "上次运行未正常结束") -> int:
        """把所有残留的 running 记录标成 failed（进程崩溃后调用）。返回修改数量。"""
        assert_writable(self.project, "恢复任务状态")
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
        # R-T1：start/finish 记录运行过程元数据，不纳入未来版本只读边界
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
        # R-T1：同 start —— 运行过程元数据不纳入只读边界
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
        story_path = self.stories.story_file(
            str(data.get("primary_story_id") or PRIMARY_STORY_ID))
        try:
            story = self.usable_story_file(story_path)
        except CorruptDataError:
            # P1-03：stories/ 损坏（JSON 坏或结构不可用，R-A2）。project.json 有效 →
            # 备份损坏文件后从 project.json 恢复；两侧都无效 → 抛错进入人工恢复，
            # 绝不用空骨架覆盖
            return self._recover_corrupt_story(data)
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
        if not story_path.exists():
            # P1-Fix-2（R-A2/R-A3）：主 Story 文件缺失。两侧都没有可用 Story 时
            # 交给统一恢复流程（可用快照 → 恢复；结构合法的空故事 → 部分恢复留痕）。
            # 否则上层会把 RepositoryError 当作「没故事」，静默换成空 Story。
            if self._usable_project_story(data) is not None:
                return data, False          # 写盘时由 sync_story 补回文件
            return self._recover_corrupt_story(data)
        raise RepositoryError(
            f"V3 项目的主 Story 文件不可读：{story_path}。原文件未做任何修改，"
            "请检查文件权限后重试。")

    @staticmethod
    def _usable_project_story(data: dict) -> dict | None:
        """project.json 里的 story 是否可直接采纳：有效且结构可读（shots 是列表）。

        is_valid_story 只要求 shots 非空；「shots: 'not-a-list'」这类结构损坏
        也可能被判为有效，采纳后会把坏数据写回 stories/。
        """
        story = data.get("story")
        if not is_valid_story(story) or not is_structural_story(story):
            return None
        return story

    def usable_story_file(self, path: Path) -> dict | None:
        """按统一规则读 stories/ 主 Story 文件（P1-Fix-2 / R-A2）。

        返回可用的 story dict；文件不存在返回 None；以下两种情况都抛 CorruptDataError
        （交给调用方按「先隔离、后恢复」处理，绝不让后续写盘覆盖原文件）：
        - JSON 语法损坏（read_json 抛的 CorruptDataError）；
        - JSON 合法但结构不可用（is_structural_story 为 False）。
        空骨架（shots: []）结构合法，原样返回。
        """
        path = Path(path)
        if not path.exists():
            return None
        stored = read_json(path)          # JSON 坏 → CorruptDataError
        if not is_structural_story(stored):
            raise CorruptDataError(
                f"{path.name} 内容结构不可用（shots 不是列表或根对象不是 JSON 对象）")
        return stored

    def _broken_story_path(self, data: dict) -> Path | None:
        """stories/ 主 Story 文件存在但损坏时返回其路径；不存在 / 结构合法返回 None。"""
        pid = str(data.get("primary_story_id") or "")
        if not pid:
            return None
        path = self.stories.story_file(pid)
        if not path.exists():
            return None
        try:
            self.usable_story_file(path)
        except CorruptDataError:
            return path
        return None

    def _broken_side(self, data: dict) -> str:
        """两侧中哪些损坏：'file' / 'project' / 'both' / ''（供上层识别恢复状态）。"""
        broken_file = self._broken_story_path(data) is not None
        raw_story = data.get("story")
        broken_project = isinstance(raw_story, dict) and bool(raw_story.get("shots")) \
            and not is_structural_story(raw_story)
        if broken_file and broken_project:
            return "both"
        if broken_file:
            return "file"
        if broken_project:
            return "project"
        return ""

    @staticmethod
    def _set_recovery_status(data: dict, state: str, reason: str):
        data["recovery_status"] = {"state": state, "reason": reason}

    def _not_recovered(self, data: dict, reason: str):
        """部分恢复：project.json 没有「可用」故事、也没有可用快照。

        P1-Fix-3：**不隔离任何文件**——损坏的 stories/ 文件保持原位。此时保持内存
        现状、不写 stories/（sync_story 遇到 _not_recovered 直接跳过），并把原因
        写给上层。用户随后手工恢复 / 修复 project.json 后重开即回到正常流程；
        在那之前每次保存都会在写盘闸门再次尝试隔离（存在恢复源时）。
        """
        data["_v3_adopt"] = None
        data["_not_recovered"] = True
        V3ProjectManager._set_recovery_status(data, "partial", reason)
        return data, True

    def _recoverable_version(self, data: dict) -> dict | None:
        """两侧 Story 都无效时，从 versions/ 找一个可用的恢复候选（只读）。

        按 story["versions"] 记录的顺序（新的在前）找第一个可加载且结构有效的快照；
        没有版本记录时扫 versions/ 目录按文件名倒序。只挑候选，不写盘——
        写盘由随后的 _v3_adopt 流程完成，失败不会破坏任何原文件。
        """
        vid = ""
        candidates = []
        story = data.get("story") if isinstance(data.get("story"), dict) else {}
        for entry in story.get("versions") or []:
            if isinstance(entry, dict) and entry.get("version_id"):
                candidates.append(str(entry["version_id"]))
        if not candidates:
            root = self.project / VERSIONS_DIR
            if root.exists():
                candidates = sorted(
                    (p.stem for p in root.glob("*.json")
                     if not p.name.startswith(".")),
                    reverse=True)
        for vid in candidates:
            try:
                snapshot = read_json(self.version_file_path(vid))
            except RepositoryError:
                continue
            if isinstance(snapshot, dict) and snapshot.get("shots"):
                payload = _clone(snapshot)
                for key in _OWN_KEYS:
                    payload.pop(key, None)
                payload.pop("version_id", None)
                payload.pop("note", None)
                payload.pop("official", None)
                payload.pop("created_at", None)
                payload["_recovery_candidate"] = str(vid)   # 内部：恢复后据此重建元信息
                return payload
        return None

    # -- 版本元信息重建（P1-Fix-2 / R-C1）--------------------------------
    # 存储事实：版本条目（version_id / note / official / base_version …）只存在于
    # story["versions"]；快照文件本身只含 Story 内容 + version_id / created_at /
    # note / official，**不**含 versions / active_version（VersionStore.snapshot 与
    # ProjectManager.save_version 都显式剥离）。story/index.json 只存摘要，
    # 不含版本信息。所以恢复时的唯一权威是 versions/ 目录里的快照文件本身。
    def _version_entry(self, snapshot: dict, version_id: str) -> dict:
        """由快照文件内容重建版本条目（与 VersionStore.snapshot 的记录格式一致）。"""
        quality = snapshot.get("quality") if isinstance(snapshot.get("quality"), dict) else {}
        shots = snapshot.get("shots") if isinstance(snapshot.get("shots"), list) else []
        entry = {
            "version_id": version_id,
            "created_at": str(snapshot.get("created_at") or ""),
            "note": str(snapshot.get("note") or ""),
            "official": bool(snapshot.get("official", True)),
            "title": snapshot.get("title", ""),
            "shot_count": len(shots),
            "total_duration": round(sum(float(s.get("duration") or 0)
                                        for s in shots
                                        if isinstance(s, dict)), 2),
            "score": quality.get("score"),
            "file": f"{VERSIONS_DIR}/{version_id}.json",
        }
        base = snapshot.get("base_version")
        if isinstance(base, str) and base:
            entry["base_version"] = base
        return entry

    def rebuild_version_entries(self, current_id: str = "") -> tuple[list[dict], dict]:
        """扫描 versions/ 重建 versions 元信息列表（按 created_at 升序 = 旧→新）。

        - 只采纳「可读、结构可识别、shots 是列表」的快照；不可读/不可识别的
          跳过并记录在报告里（**不伪造**条目）；
        - base_version 只保留指向确实存在且可识别的版本的引用；
        - 返回 (entries, report)；report["unverified"] 列出被跳过的文件。
        """
        root = self.project / VERSIONS_DIR
        verified: dict[str, tuple[str, dict]] = {}
        unverified = []
        if root.exists():
            for path in sorted(root.glob("*.json")):
                vid = path.stem
                if path.name.startswith("."):
                    continue
                try:
                    snapshot = read_json(path)
                except RepositoryError:
                    unverified.append(vid)
                    continue
                if not is_structural_story(snapshot) or not snapshot.get("shots"):
                    unverified.append(vid)
                    continue
                verified[vid] = (str(snapshot.get("created_at") or ""), snapshot)
        ordered = sorted(verified.items(), key=lambda kv: (kv[1][0], kv[0]))
        entries = [self._version_entry(snapshot, vid) for vid, (_stamp, snapshot) in ordered]
        ids = {e["version_id"] for e in entries}
        for entry in entries:
            base = entry.get("base_version")
            if base and base not in ids:
                entry.pop("base_version", None)   # 悬空引用不保留
        active = current_id if current_id in ids else ""
        return entries, {"unverified": unverified, "active_version": active,
                         "verified": len(entries)}

    def _restore_from_snapshot(self, data: dict, snapshot: dict) -> dict:
        """用快照恢复 Story，并按 versions/ 目录重建版本元信息（R-C1 部分恢复支持）。"""
        payload = _clone(snapshot)
        for key in _OWN_KEYS:
            payload.pop(key, None)
        for key in ("version_id", "note", "official", "created_at",
                    "_recovery_candidate", "base_version"):
            payload.pop(key, None)
        candidate_id = str(snapshot.get("_recovery_candidate") or "")
        entries, report = self.rebuild_version_entries(current_id=candidate_id)
        payload["versions"] = entries
        payload["active_version"] = report["active_version"]
        data["story"] = payload
        data["_v3_adopt"] = payload
        state = "recovered" if not report["unverified"] and report["verified"] else "partial"
        reason = (f"stories/ 主 Story 损坏，从版本快照 "
                  f"{candidate_id or '?'} 恢复 Story 内容（写盘前先隔离原文件），并按 "
                  f"versions/ 目录重建 {report['verified']} 条版本元信息")
        if report["unverified"]:
            reason += (f"；另有 {len(report['unverified'])} 个版本文件不可识别，"
                       "未重建其元信息（原文件保留）：" + "、".join(report["unverified"]))
        V3ProjectManager._set_recovery_status(data, state, reason)
        return data

    def version_file_path(self, version_id: str) -> Path:
        """versions/<version_id>.json（P1-Fix：供恢复候选读取）。"""
        return self.project / VERSIONS_DIR / f"{_validate_id(version_id, 'version_id')}.json"

    def _quarantine_corrupt(self, path: Path) -> Path | None:
        """把损坏文件的原始字节搬到 .corrupt/（不删除、不覆盖）。返回备份路径。

        当前实现（P1-Fix-3-R2 / R2-02）的操作顺序：
        1. 需要时创建 .corrupt/（记录是否本次新建，供失败回滚）；
        2. copy2 原文件到随机隐藏名 staging（``.<name>.<8hex>.tmp``）；
        3. 用 ``os.link(staging → target)`` 的**独占创建**语义落成正式备份——
           目标已存在时 link 抛 FileExistsError（原子，无「检查后替换」窗口）；
        4. 候选名首次为 ``<name>.<stamp>.bak``，冲突后换
           ``<name>.<stamp>-<6hex>.bak``，最多尝试 64 次；
        5. 成功后先 unlink staging，最后才 unlink 原文件；只有全部成功才返回 target。

        失败语义（任何一步抛 OSError，包括 64 次冲突耗尽、权限不足、文件系统
        不支持硬链接）：删除本次**实际创建**的文件（staging，以及 link 成功的
        target），本次新建的 .corrupt/ 若因此变空则 rmdir，最后返回 None。
        target 只在 link 成功后进入回收集合，历史备份永远不会被误删或覆盖；
        原文件在备份完整落盘之前保持原位。清理本身也可能失败（文件被占用等）——
        此时同样返回 None，并通过 .corrupt/ 里的残留文件如实暴露
        （不伪造零残留、不声称成功）。操作开始前已存在的 .corrupt/ 文件永远不动。

        先前的实现是「copy2 → 随机 staging → rename 成 target」，rename 会覆盖
        已存在的同名文件，极端时间戳冲突时会吞掉历史备份，已由上述 link 方案取代。
        """
        path = Path(path)
        root = self.project / ".corrupt"
        created_dir = not root.exists()
        staging = None
        target = None          # 仅当本次成功 link 出 target 后才非 None（防误删历史文件）
        try:
            if not path.exists():
                return None
            root.mkdir(parents=True, exist_ok=True)
            staging = root / f".{path.name}.{uuid.uuid4().hex[:8]}{_TMP_SUFFIX}"
            shutil.copy2(path, staging)
            # 独占创建 target：os.link 在目标已存在时抛 FileExistsError，
            # 不存在「检查后替换」的竞争窗口；冲突则换名重试。
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            for attempt in range(64):
                candidate = (root / f"{path.name}.{stamp}.bak"
                             if attempt == 0 else
                             root / f"{path.name}.{stamp}-{uuid.uuid4().hex[:6]}.bak")
                try:
                    os.link(staging, candidate)
                    target = candidate
                    break
                except FileExistsError:
                    continue          # 名称冲突：绝不能覆盖，换下一个候选名
            if target is None:
                raise OSError(
                    f"无法为 {path.name} 生成唯一的备份文件名（.corrupt/ 已尝试 64 次）")
            staging.unlink()
            staging = None
            path.unlink()
            return target
        except OSError:
            for leftover in (staging, target):
                if leftover is None:
                    continue
                try:
                    leftover.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass            # 清理失败：残留如实可见，不声称零残留
            if created_dir:
                try:
                    root.rmdir()          # 本次创建的 .corrupt/ 失败后不留下
                except OSError:
                    pass
            return None

    def _recover_corrupt_story(self, data: dict) -> tuple[dict, bool]:
        """stories/ 损坏（JSON 坏 **或** 结构不可用）时的只读恢复判定。

        判定统一走 usable_story_file / _usable_project_story（R-A2），处理顺序：
        - project.json 的 story 可用（有效且结构可读）→ 采纳（内存）；
        - 两侧都不可用但有可用快照 → 采纳快照（历史版本恢复）；
        - project.json 有内容但结构坏且无可用快照 → 抛 CorruptDataError（人工恢复）；
        - project.json 结构可读但无镜头（None / 空骨架）且无快照 → 部分恢复状态留痕；
        - 全部无效且无快照 → 抛 CorruptDataError。
        「不可用但非空」任何时候都不会被空骨架或自动创建的空 Story 覆盖。

        **P1-Fix-3：本函数不执行任何物理隔离**。只判定是否存在恢复源并写好内存
        story；损坏文件的隔离（.corrupt/ 备份 + 移出原位置）由调用方在确认恢复源、
        即将写盘之前完成（ProjectManager._guard_pending_quarantine）。因此：
        - 无恢复源而抛错时，项目目录字节零变化；
        - 有恢复源时先隔离、隔离成功后才写盘。
        """
        current = self._usable_project_story(data)   # 有效且结构可读才算可用
        pid = str(data.get("primary_story_id") or PRIMARY_STORY_ID)

        # 隔离不在这里做：调用方（ProjectManager 写盘闸门）负责。
        # 本函数返回的 data 中 _v3_adopt 是权威值，写盘时由 sync_story 写回 stories/。

        if current is not None:
            data["_v3_adopt"] = current
            self._set_recovery_status(data, "recovered",
                "stories/ 主 Story 损坏，将从 project.json 恢复（写盘前先隔离原文件）")
            return data, True
        raw_story = data.get("story")
        project_bad = (isinstance(raw_story, dict) and raw_story.get("shots")
                       and not is_structural_story(raw_story))
        candidate = self._recoverable_version(data)
        if candidate is not None:
            # 可用快照优先于「双侧都坏」判定（R-A2：双侧损坏 → 历史版本恢复）；
            # 快照只写进内存，由后续保存落盘
            self._restore_from_snapshot(data, candidate)
            self._assign_primary(data)
            if project_bad:
                reason = data["recovery_status"]["reason"]
                data["recovery_status"]["reason"] = (
                    reason + "；project.json 中的 story 结构无效，未采用（原字节保留）")
            return data, True
        if project_bad:
            # 有内容但结构坏（如 shots 不是列表），也没有可用快照：
            # 已损坏、不可用，也绝不是空项目。走人工恢复，不用空骨架覆盖。
            # P1-Fix-3：不隔离、不删除、不移动——本次打开对项目字节零影响。
            raise CorruptDataError(
                f"stories/{pid}/story.json 损坏/缺失，project.json 中的 story 结构无效、"
                "无法恢复，versions/ 中也没有可用快照。未对任何文件做修改（原始数据"
                "保持原位），请手工检查后恢复。")
        # project.json 中没有故事（None）或结构合法的空故事（shots: []）：
        # 保持现状，不用骨架覆盖用户可见的内容；进入部分恢复状态留痕。
        # R-A2：shots 为空是合法 Story，明确标记为「部分恢复」而不是伪装成正常空 Story。
        return self._not_recovered(data,
            "stories/ 主 Story 损坏，project.json 中没有可用故事，"
            "未从 versions/ 覆盖当前内容（部分恢复，无可用快照）；"
            "未隔离、未删除原文件，保存时若仍无恢复源将整次拒绝写入")

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
        if version == 3 and not is_valid_story(story):
            # P1-03：stories/ 是空骨架 / 已被归档，project.json 也没有有效故事。
            # 放弃旧版「init_primary_story 重建」——那会用刚被清空的 project.json
            # 写一个空 Story，覆盖唯一副本。改为 versions/ 候选 > 保持现状。
            if not is_valid_story(current):
                candidate = self._recoverable_version(data)
                if candidate is not None:
                    self._restore_from_snapshot(data, candidate)   # 含版本元信息重建
                    changed = True
            return data, changed
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
    if data.pop("_not_recovered", False):
        # P1-Fix-2（R-A2/R-A3）：stories/ 文件损坏、project.json 没有可用
        # 故事 —— 本次保存不得把 project.json 的现状写回 stories/（那会悄悄丢掉
        # 版本引用或覆盖用户的空故事），交给下次打开按损坏规则再处理。
        # P1-Fix-3：此处不隔离原文件；保存由调用方写盘闸门决定（无恢复源时整次拒绝）。
        return False
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
