"""V3 P1 数据基础测试（不需要 GUI）。

覆盖交付标准：
- 创建 Project 自动得到主 Story；重新打开后主 Story 仍在；
- 不存在没有主 Story 的有效 Project；
- 修改 Story 不破坏 Project 数据；V2.2 项目兼容；
- 原子写失败时原文件字节不变；异常恢复（残留 tmp、损坏文件、任务状态）；
- 迁移：V2 故事在写盘时并入 stories/；
- 自动化覆盖创建、保存、重新打开、异常回滚、迁移。

运行：python -m unittest discover -s tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import v3_storage as v3  # noqa: E402
from modules.project_manager import (  # noqa: E402
    ProjectManager, ProjectError, ProjectReadOnlyError, SCHEMA_VERSION, STORY_SCHEMA_VERSION,
)


def _story(title="纸人替身", n=3):
    """一个最小但完整的 V2.2 故事。"""
    shots = [{"index": i + 1, "scene": f"镜{i + 1}", "narration": f"旁白{i + 1}",
              "duration": 3.0} for i in range(n)]
    return {"schema_version": 2, "title": title, "logline": "守灵夜的纸人",
            "keywords": "纸人、灵堂", "model": "test-model",
            "characters": [], "scenes": [], "shots": shots}


def _snapshot_tree(project):
    """整个项目目录的「相对路径 → 文件字节」集合（含空目录），用于零写入断言。"""
    project = Path(project)
    files = {str(p.relative_to(project)): p.read_bytes()
             for p in project.rglob("*") if p.is_file()}
    dirs = {str(p.relative_to(project)) for p in project.rglob("*") if p.is_dir()}
    return {"files": files, "dirs": dirs}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ahs_v3_"))
        self.pm = ProjectManager()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _project(self, name="V3项目"):
        return self.pm.create_project(self.tmp, name)

    def _raw(self, project):
        return json.loads((project / "project.json").read_text(encoding="utf-8"))

    def _story_file(self, project, story_id="story"):
        path = project / "stories" / story_id / "story.json"
        return json.loads(path.read_text(encoding="utf-8"))


class AtomicWriteTest(_Base):
    """原子写入与异常恢复。"""

    def test_write_is_atomic_and_leaves_no_tmp(self):
        target = self.tmp / "data" / "a.json"
        v3.write_json_atomic(target, {"x": 1})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"x": 1})
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_failed_write_keeps_original_bytes(self):
        target = self.tmp / "a.json"
        target.write_text('{"old": true}', encoding="utf-8")
        original = target.read_bytes()
        with mock.patch.object(Path, "replace", side_effect=OSError("磁盘满")):
            with self.assertRaises(OSError):
                v3.write_json_atomic(target, {"new": True})
        self.assertEqual(target.read_bytes(), original)      # 原文件字节不变
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])   # 临时文件已清理

    def test_failed_write_does_not_create_target(self):
        target = self.tmp / "missing" / "a.json"
        with mock.patch.object(Path, "replace", side_effect=OSError("失败")):
            with self.assertRaises(OSError):
                v3.write_json_atomic(target, {"x": 1})
        self.assertFalse(target.exists())

    def test_cleanup_stale_temps(self):
        (self.tmp / "a.json").write_text("{}", encoding="utf-8")
        (self.tmp / "a.json.tmp").write_text("半截", encoding="utf-8")
        (self.tmp / "sub").mkdir()
        (self.tmp / "sub" / "b.tmp").write_text("", encoding="utf-8")
        self.assertEqual(v3.cleanup_stale_temps(self.tmp), 2)
        self.assertTrue((self.tmp / "a.json").exists())
        self.assertEqual(list(self.tmp.rglob("*.tmp")), [])

    def test_read_json_handles_missing_empty_and_corrupt(self):
        self.assertIsNone(v3.read_json(self.tmp / "nope.json"))
        empty = self.tmp / "empty.json"
        empty.write_text("  ", encoding="utf-8")
        self.assertEqual(v3.read_json(empty, default={}), {})
        broken = self.tmp / "broken.json"
        broken.write_text("{坏", encoding="utf-8")
        with self.assertRaises(v3.RepositoryError):
            v3.read_json(broken)

    def test_invalid_id_rejected(self):
        with self.assertRaises(v3.RepositoryError):
            v3.new_story(story_id="../evil", project_id="p")
        with self.assertRaises(v3.RepositoryError):
            v3.new_story(story_id="a/b", project_id="p")


class TaskStoreTest(_Base):
    """任务状态持久化的基础能力。"""

    def test_start_finish_and_list(self):
        project = self._project()
        tasks = v3.TaskStore(project)
        task = tasks.start("render", "渲染第 1 段")
        self.assertEqual(task["status"], "running")
        done = tasks.finish(task["task_id"], "succeeded")
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(len(tasks.list()), 1)
        # 重新打开项目后状态仍在（持久化）
        self.assertEqual(v3.TaskStore(project).get(task["task_id"])["status"], "succeeded")

    def test_unknown_status_rejected(self):
        project = self._project()
        tasks = v3.TaskStore(project)
        task = tasks.start("x")
        with self.assertRaises(v3.RepositoryError):
            tasks.finish(task["task_id"], "half-done")

    def test_mark_abandoned_after_crash(self):
        project = self._project()
        tasks = v3.TaskStore(project)
        running = tasks.start("render")
        done = tasks.start("render")
        tasks.finish(done["task_id"], "succeeded")
        self.assertEqual(tasks.mark_abandoned(), 1)
        self.assertEqual(tasks.get(running["task_id"])["status"], "failed")
        self.assertEqual(tasks.get(done["task_id"])["status"], "succeeded")


class CreateAndReopenTest(_Base):
    """创建即得到主 Story；重新打开可恢复；任何 Project 都有主 Story。"""

    def test_create_initializes_primary_story(self):
        project = self._project()
        raw = self._raw(project)
        self.assertEqual(raw["schema_version"], v3.V3_SCHEMA_VERSION)
        self.assertEqual(raw["primary_story_id"], v3.PRIMARY_STORY_ID)
        self.assertEqual(len(raw["stories"]), 1)
        self.assertEqual(raw["stories"][0]["story_id"], v3.PRIMARY_STORY_ID)
        story = self._story_file(project)
        self.assertEqual(story["story_id"], v3.PRIMARY_STORY_ID)
        self.assertEqual(story["project_id"], project.name)
        self.assertEqual(story["shots"], [])
        self.assertTrue((project / "story" / "index.json").exists())

    def test_reopen_restores_story(self):
        project = self._project()
        self.pm.set_story(project, _story())
        # 模拟应用重启：新实例、重新打开、重新读取
        pm2 = ProjectManager()
        pm2.open_project(project)
        data = pm2.load(project)
        self.assertEqual(data["story"]["title"], "纸人替身")
        self.assertEqual(len(data["story"]["shots"]), 3)
        self.assertIsNotNone(pm2.get_story(data))
        self.assertEqual(self._raw(project)["schema_version"], v3.V3_SCHEMA_VERSION)

    def test_primary_story_is_single_source_of_truth(self):
        project = self._project()
        self.pm.set_story(project, _story())
        # 直接改 project.json 的 story（旧代码 / 外部编辑）：重开时以 stories/ 为准
        raw = self._raw(project)
        raw["story"]["title"] = "被外部改坏"
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        data = self.pm.migrate(self.pm.load(project))[0]
        self.assertEqual(data["story"]["title"], "纸人替身")

    def test_story_id_survives_project_rename(self):
        project = self._project()
        self.pm.set_story(project, _story())
        before = self._story_file(project)
        self.pm.open_project(project)
        after = self._story_file(project)
        self.assertEqual(before["story_id"], after["story_id"])
        self.assertEqual(before["created_at"], after["created_at"])

    def test_versions_dir_and_snapshot_files(self):
        project = self._project()
        self.pm.set_story(project, _story())
        versions = self._story_file(project)["versions"]
        self.assertEqual(len(versions), 1)
        snap = json.loads((project / versions[0]["file"]).read_text(encoding="utf-8"))
        self.assertNotIn("story_id", snap)        # V3 自有身份字段不进快照
        self.assertNotIn("project_id", snap)
        self.assertEqual(len(snap["shots"]), 3)

    def test_story_modification_does_not_touch_project_shots(self):
        project = self._project()
        self.pm.add_images(project, [], 3.0)  # 空导入：不产生镜头，但走一遍写盘
        data = self.pm.load(project)
        data["shots"] = [{"id": "abc12345", "image": None, "start": 0.0, "duration": 3.0,
                          "zoom": "none", "transition": "cut", "subtitle": None}]
        self.pm.save(project, data)
        self.pm.set_story(project, _story(title="新故事", n=5))
        shots = self._raw(project)["shots"]
        self.assertEqual(len(shots), 1)
        self.assertEqual(shots[0]["id"], "abc12345")
        self.assertEqual(len(self._raw(project)["story"]["shots"]), 5)


class IntegrityTest(_Base):
    """不存在没有主 Story 的有效 Project；损坏 / 缺失有明确处理。"""

    def test_missing_story_file_with_content_is_repaired(self):
        project = self._project()
        self.pm.set_story(project, _story())
        story_path = project / "stories" / "story" / "story.json"
        story_path.unlink()
        # project.json 里还有完整 story：打开时从 project.json 修复 stories/
        data = self.pm.migrate(self.pm.load(project))[0]
        self.assertEqual(len(data["story"]["shots"]), 3)
        self.pm.save(project, data)
        self.assertTrue(story_path.exists())
        self.assertEqual(len(self._story_file(project)["shots"]), 3)

    def test_v3_without_any_story_is_reported(self):
        # P1-Fix-2（R-A2/R-A3）：空骨架 + 无故事 + 无快照 → 明确的「部分恢复」
        # 状态（而不是静默当成正常空 Story），原始内容不丢、不自动创建空 Story。
        project = self._project()
        raw = self._raw(project)
        raw["story"] = None
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        skeleton = project / "stories" / "story" / "story.json"
        skeleton.unlink()
        data, changed = v3.V3ProjectManager(project).load(dict(raw))
        self.assertTrue(changed)
        self.assertEqual(data["recovery_status"]["state"], "partial")
        self.assertEqual(data.get("story"), None)          # 不自动创建空 Story
        self.assertFalse(skeleton.exists())                # 也不写骨架
        self.assertEqual(self.pm.get_story(self.pm.load(project)), None)

    def test_corrupt_story_file_does_not_lose_project(self):
        project = self._project()
        self.pm.set_story(project, _story())
        (project / "stories" / "story" / "story.json").write_text("{坏了", encoding="utf-8")
        data = self.pm.migrate(self.pm.load(project))[0]
        self.assertEqual(data.get("name"), "V3项目")      # project 数据完好
        self.assertEqual(len(data["story"]["shots"]), 3)   # story 从 project.json 恢复

    def test_index_is_rebuildable(self):
        project = self._project()
        self.pm.set_story(project, _story())
        index = project / "story" / "index.json"
        index.unlink()
        rebuilt = v3.StoryRepository(project).rebuild_index()
        self.assertEqual([e["story_id"] for e in rebuilt["stories"]], [v3.PRIMARY_STORY_ID])
        self.assertTrue(index.exists())

    def test_archive_never_deletes_directly(self):
        project = self._project()
        self.pm.set_story(project, _story())
        repo = v3.StoryRepository(project)
        trashed = repo.archive(v3.PRIMARY_STORY_ID)
        self.assertTrue(trashed.exists())
        self.assertTrue((trashed / "story.json").exists())
        self.assertFalse(repo.exists(v3.PRIMARY_STORY_ID))


class AtomicInitRollbackTest(_Base):
    """主 Story 初始化失败 -> 回滚到初始化前，不留下半成品。"""

    def test_init_failure_rolls_back(self):
        project = self.tmp / "回滚"
        project.mkdir()
        data = {"schema_version": SCHEMA_VERSION, "name": "回滚", "shots": [], "story": None}
        (project / "project.json").write_text(json.dumps(data, ensure_ascii=False),
                                              encoding="utf-8")
        with mock.patch.object(v3, "write_json_atomic", side_effect=OSError("失败")):
            with self.assertRaises((OSError, v3.RepositoryError)):
                v3.V3ProjectManager(project).init_primary_story(data=dict(data))
        # project.json 保持原样；新 story 被归档而不是残留为有效主 Story
        self.assertEqual(self._raw(project)["schema_version"], SCHEMA_VERSION)
        repo = v3.StoryRepository(project)
        self.assertFalse(repo.exists(v3.PRIMARY_STORY_ID))
        self.assertFalse((project / v3.V3_LAYOUT_MARKER).exists())

    def test_create_project_falls_back_to_v2_when_v3_fails(self):
        with mock.patch.object(v3, "write_json_atomic", side_effect=OSError("失败")):
            project = self.pm.create_project(self.tmp, "降级")
        self.assertTrue((project / "project.json").exists())
        self.assertEqual(self._raw(project)["schema_version"], SCHEMA_VERSION)
        self.assertFalse((project / "stories" / "story" / "story.json").exists())

    def test_init_is_idempotent(self):
        project = self._project()
        vm = v3.V3ProjectManager(project)
        before = (project / "stories" / "story" / "story.json").read_bytes()
        result = vm.init_primary_story()
        self.assertEqual(result["primary_story_id"], v3.PRIMARY_STORY_ID)
        self.assertEqual((project / "stories" / "story" / "story.json").read_bytes(), before)


class FutureVersionTest(_Base):
    """未来版本只读：不允许写回，也不能把版本号写小。"""

    def test_save_rejects_future_version(self):
        project = self._project()
        data = self.pm.load(project)
        data["schema_version"] = v3.V3_SCHEMA_VERSION + 1
        before = (project / "project.json").read_bytes()
        with self.assertRaises(ProjectReadOnlyError):
            self.pm.save(project, data)
        self.assertEqual((project / "project.json").read_bytes(), before)

    def test_open_future_version_is_read_only(self):
        project = self._project()
        raw = self._raw(project)
        raw["schema_version"] = v3.V3_SCHEMA_VERSION + 1
        raw["future_field"] = "保留"
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        # open_project 可能因为「结构升级」尝试存快照，只读错误被吞掉（不能保存）；
        # 关键约束：打开后磁盘一字未动，也不会写任何快照
        self.pm.open_project(project)
        self.assertEqual(list((project / "versions").glob("*.json")), [])
        kept = self._raw(project)
        self.assertEqual(kept["schema_version"], v3.V3_SCHEMA_VERSION + 1)
        self.assertEqual(kept["future_field"], "保留")


class V2CompatibilityTest(_Base):
    """V2.2 项目兼容：旧数据格式不变，打开不丢故事。"""

    def _v2_project(self):
        project = self.tmp / "v2旧项目"
        for sub in ("images", "audio", "subtitles", "output", "temp", "versions"):
            (project / sub).mkdir(parents=True)
        data = {
            "schema_version": 2, "name": "v2旧项目",
            "created_at": "2026-01-01T00:00:00", "settings": {}, "shots": [],
            "narration": None, "music": None, "subtitle": None,
            "story": _story(title="V2 故事"),
        }
        (project / "project.json").write_text(json.dumps(data, ensure_ascii=False),
                                              encoding="utf-8")
        return project

    def test_v2_project_opens_and_keeps_story(self):
        project = self._v2_project()
        self.pm.open_project(project)
        data = self.pm.load(project)
        self.assertEqual(data["schema_version"], SCHEMA_VERSION)
        self.assertEqual(data["story"]["title"], "V2 故事")
        self.assertEqual(len(data["story"]["shots"]), 3)
        # 写盘后成为 V3 项目，主 Story 独立落盘
        self.assertEqual(self._raw(project)["schema_version"], v3.V3_SCHEMA_VERSION)
        self.assertEqual(len(self._story_file(project)["shots"]), 3)

    def test_v2_project_without_story_gets_skeleton(self):
        project = self._v2_project()
        raw = self._raw(project)
        raw["story"] = None
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        self.pm.open_project(project)
        story = self._story_file(project)
        self.assertEqual(story["story_id"], v3.PRIMARY_STORY_ID)
        self.assertEqual(story["shots"], [])
        self.assertEqual(story["title"], "v2旧项目")

    def test_legacy_v1_project_is_migrated(self):
        project = self.tmp / "v1项目"
        (project / "versions").mkdir(parents=True)
        (project / "images").mkdir()
        legacy = {"schema_version": 1, "name": "v1项目",
                  "images": ["images/01.png"], "image_duration": 4}
        (project / "project.json").write_text(json.dumps(legacy, ensure_ascii=False),
                                              encoding="utf-8")
        self.pm.open_project(project)
        data = self.pm.load(project)
        self.assertEqual(len(data["shots"]), 1)
        self.assertAlmostEqual(data["shots"][0]["duration"], 4.0)
        self.assertEqual(self._raw(project)["schema_version"], v3.V3_SCHEMA_VERSION)

    def test_v2_story_is_upgraded_on_open(self):
        project = self._v2_project()
        raw = self._raw(project)
        raw["story"] = {"schema_version": 1, "title": "旧结构", "shots": [
            {"index": 1, "scene": "灵堂", "narration": "它看着我。", "duration": 3.5}]}
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        self.pm.open_project(project)
        story = self.pm.load(project)["story"]
        self.assertEqual(story["schema_version"], STORY_SCHEMA_VERSION)
        self.assertEqual(story["shots"][0]["shot_id"], "s001")
        self.assertEqual(story["shots"][0]["image_prompt"], "灵堂")
        # 升级快照落盘，且重复打开不会重复生成
        files = list((project / "versions").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.pm.open_project(project)
        self.assertEqual(len(list((project / "versions").glob("*.json"))), 1)


class P1FixVersionPruneTest(_Base):
    """P1-Fix / P1-01：正式版本裁剪只按正式版本计数。"""

    def _story_with_shot(self):
        s = _story(n=2)
        return s

    def _official(self, project):
        story = json.loads((project / "stories" / "story" / "story.json").read_text("utf-8"))
        return [v for v in story.get("versions") or [] if v.get("official")]

    def test_unofficial_versions_do_not_consume_official_quota(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))           # 1 个正式
        for i in range(9):                                 # + 9 个非正式
            self.pm.save_version(project, self.pm.load(project),
                                 note=f"非正式{i}", official=False)
        self.assertEqual(len(self._official(project)), 1)
        self.pm.save_version(project, self.pm.load(project), note="再存", official=False)
        # 正式版本仍在（修复前会被裁掉）
        self.assertEqual(len(self._official(project)), 1)

    def test_official_versions_pruned_at_limit(self):
        project = self._project()
        for i in range(13):
            self.pm.set_story(project, _story(title=f"第{i}版", n=2))
        official = self._official(project)
        self.assertEqual(len(official), 10)
        story = json.loads((project / "stories/story/story.json").read_text("utf-8"))
        self.assertEqual(story["title"], "第12版")
        for entry in official:                              # 元信息引用的文件都还在
            self.assertTrue((project / entry["file"]).exists())

    def test_active_version_never_pruned(self):
        project = self._project()
        self.pm.set_story(project, _story(title="A", n=2))
        active = self._official(project)[0]["version_id"]
        data = self.pm.load(project)
        data["story"]["active_version"] = active
        self.pm.save(project, data)
        for i in range(12):
            self.pm.save_version(project, self.pm.load(project), note=f"x{i}", official=True)
        story = json.loads((project / "stories/story/story.json").read_text("utf-8"))
        self.assertEqual(story["active_version"], active)      # 引用没有丢失
        ids = {v["version_id"] for v in self._official(project)}
        self.assertIn(active, ids)                              # 也不被裁剪
        self.assertTrue((project / "versions" / f"{active}.json").exists())

    def test_referenced_version_never_pruned(self):
        project = self._project()
        self.pm.set_story(project, _story(title="被引用", n=2))
        keep = self._official(project)[0]["version_id"]
        data = self.pm.load(project)
        data["shots"] = [{"id": "abc12345", "image": None, "start": 0.0, "duration": 3.0,
                          "zoom": "none", "motion": "static", "transition": "cut",
                          "subtitle": None, "voiced": True, "voice_version": keep}]
        self.pm.save(project, data)
        for i in range(14):
            self.pm.set_story(project, _story(title=f"第{i}版", n=2))
        ids = {v["version_id"] for v in self._official(project)}
        self.assertIn(keep, ids)

    def test_prune_keeps_metadata_when_file_delete_fails(self):
        project = self._project()
        for i in range(12):
            self.pm.set_story(project, _story(title=f"第{i}版", n=2))
        before = self._official(project)
        with mock.patch.object(Path, "unlink", side_effect=OSError("被占用")):
            self.pm.set_story(project, _story(title="新的一版", n=2))
        official = self._official(project)
        # 删不掉的文件：元信息保留（不产生悬空引用），版本数量只增不减
        for entry in official:
            self.assertTrue((project / entry["file"]).exists())
        kept = {v["version_id"] for v in before}
        self.assertTrue(kept.issubset({v["version_id"] for v in official}))


class P1FixFutureVersionTest(_Base):
    """P1-Fix / P1-02：所有业务数据写入入口在 schema_version=4 时都拒绝。"""

    def _future_project(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        raw = self._raw(project)
        raw["schema_version"] = v3.V3_SCHEMA_VERSION + 1
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        return project

    def _snapshot(self, project):
        def dump(root):
            out = {}
            for path in sorted(Path(root).rglob("*")):
                if path.is_file():
                    out[str(path.relative_to(project))] = path.read_bytes()
            return out
        return dump(project)

    def _assert_untouched(self, project, before):
        self.assertEqual(self._snapshot(project), before)

    def _entries(self, project):
        data = self.pm.load(project)
        return data, v3.StoryRepository(project), v3.VersionStore(project)

    def test_save_refused(self):
        project = self._future_project()
        before = self._snapshot(project)
        data = self.pm.load(project)
        with self.assertRaises((ProjectReadOnlyError, v3.RepositoryError)):
            self.pm.save(project, data)
        self._assert_untouched(project, before)

    def test_save_version_refused_before_snapshot_file(self):
        project = self._future_project()
        before = self._snapshot(project)
        data = self.pm.load(project)
        with self.assertRaises((ProjectReadOnlyError, v3.RepositoryError)):
            self.pm.save_version(project, data, note="x")
        self._assert_untouched(project, before)      # 不能留下新快照文件

    def test_restore_version_refused(self):
        project = self._future_project()
        vid = json.loads((project / "stories/story/story.json").read_text("utf-8"))[
            "versions"][0]["version_id"]
        before = self._snapshot(project)
        with self.assertRaises((ProjectReadOnlyError, v3.RepositoryError)):
            self.pm.restore_version(project, vid)
        self._assert_untouched(project, before)

    def test_set_and_clear_story_refused(self):
        project = self._future_project()
        before = self._snapshot(project)
        with self.assertRaises((ProjectReadOnlyError, v3.RepositoryError)):
            self.pm.set_story(project, _story(title="不该写入", n=2))
        self._assert_untouched(project, before)
        with self.assertRaises((ProjectReadOnlyError, v3.RepositoryError)):
            self.pm.clear_story(project)
        self._assert_untouched(project, before)

    def test_story_repository_refused(self):
        project = self._future_project()
        before = self._snapshot(project)
        repo = v3.StoryRepository(project)
        story = repo.get("story")
        with self.assertRaises(v3.RepositoryError):
            repo.update("story", dict(story, title="不改"))
        self._assert_untouched(project, before)
        with self.assertRaises(v3.RepositoryError):
            repo.create(dict(story, story_id="second"))
        self._assert_untouched(project, before)
        with self.assertRaises(v3.RepositoryError):
            repo.archive("story")
        self._assert_untouched(project, before)

    def test_version_store_refused(self):
        project = self._future_project()
        before = self._snapshot(project)
        store = v3.VersionStore(project)
        vid = store.list("story")[0]["version_id"]
        with self.assertRaises(v3.RepositoryError):
            store.snapshot("story", note="x")
        with self.assertRaises(v3.RepositoryError):
            store.restore("story", vid)
        self._assert_untouched(project, before)

    def test_init_primary_story_refused(self):
        project = self._future_project()
        before = self._snapshot(project)
        raw = self._raw(project)
        with self.assertRaises(v3.RepositoryError):
            v3.V3ProjectManager(project).init_primary_story(data=raw)
        self._assert_untouched(project, before)

    def test_normal_v3_project_still_writable(self):
        project = self._project()
        self.pm.set_story(project, _story(title="正常", n=2))
        data = self.pm.load(project)
        data["story"]["title"] = "正常改"
        self.pm.save(project, data)
        self.pm.save_version(project, self.pm.load(project), note="正常版本")
        self.assertEqual(self.pm.load(project)["story"]["title"], "正常改")
        self.assertEqual(self._raw(project)["schema_version"], v3.V3_SCHEMA_VERSION)


class P1FixCorruptRecoveryTest(_Base):
    """P1-Fix / P1-03：双侧 Story 损坏时的安全恢复。"""

    def _corrupt_primary(self, project):
        path = project / "stories" / "story" / "story.json"
        path.write_bytes(b'{"broken": ')     # truncate 覆盖，尾部不会残留
        return path

    def test_story_file_broken_project_story_valid(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        path = self._corrupt_primary(project)
        self.pm.open_project(project)                            # GUI 打开流程
        story = json.loads((project / "stories/story/story.json").read_text("utf-8"))
        self.assertEqual(len(story["shots"]), 3)                 # 从 project.json 恢复
        # 打开即可读到故事（V2 视图拿得到 project.json 里的故事）
        self.assertEqual(len(self.pm.get_story(self.pm.load(project))["shots"]), 3)
        backups = list((project / ".corrupt").glob("story.json.*.bak"))
        self.assertEqual(len(backups), 1)                        # 原始损坏字节保留
        self.assertEqual(backups[0].read_bytes(), b'{"broken": ')

    def test_story_file_missing_project_story_valid(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        (project / "stories/story/story.json").unlink()
        data = self.pm.migrate(self.pm.load(project))[0]
        self.pm.save(project, data)
        story = json.loads((project / "stories/story/story.json").read_text("utf-8"))
        self.assertEqual(len(story["shots"]), 3)

    def test_both_sides_broken_is_reported_and_bytes_kept(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        broken = self._corrupt_primary(project)
        for entry in (project / "versions").glob("*.json"):
            entry.unlink()
        raw = self._raw(project)
        raw["story"] = {"schema_version": 2, "title": "坏", "shots": "not-a-list"}
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        vm = v3.V3ProjectManager(project)
        before = _snapshot_tree(project)
        with self.assertRaises(v3.CorruptDataError):
            vm.load(dict(raw))
        # P1-Fix-3：V3 层只读判定——不隔离、不删除、不创建 .corrupt/
        self.assertEqual(_snapshot_tree(project), before)
        self.assertTrue(broken.exists())
        self.assertFalse((project / ".corrupt").exists())
        # V2 界面仍能打开项目（V3 失败不能挡住 V2）
        self.assertEqual(self.pm.get_story(self.pm.load(project))["shots"], "not-a-list")

    def test_both_sides_missing_uses_history_if_any(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        (project / "stories/story/story.json").unlink()      # 写一个有效空骨架
        (project / "stories/story/story.json").write_text(json.dumps(
            dict(v3.new_story(story_id="story", project_id="V3项目"),
                 schema_version=2)), encoding="utf-8")
        raw = self._raw(project)
        raw["story"] = None
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        self.pm.open_project(project)
        story = json.loads((project / "stories/story/story.json").read_text("utf-8"))
        self.assertEqual(len(story["shots"]), 3)                 # 来自 StoryVersion
        self.assertNotIn("_v3_adopt", story)                     # 内部标记不外泄

    def test_both_sides_invalid_without_history_never_writes_empty_story(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        (project / "stories/story/story.json").unlink()
        (project / "stories/story/story.json").write_text(json.dumps(
            dict(v3.new_story(story_id="story", project_id="V3项目"),
                 schema_version=2)), encoding="utf-8")
        for entry in (project / "versions").glob("*.json"):
            entry.unlink()
        raw = self._raw(project)
        raw["story"] = None
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        before = (project / "project.json").read_bytes()
        data = self.pm.migrate(self.pm.load(project))[0]
        data.pop("_version_snapshot_due", None)
        self.pm.save(project, data)
        story = json.loads((project / "stories/story/story.json").read_text("utf-8"))
        self.assertEqual(story["shots"], [])                     # 不被任何旧内容"恢复"
        kept = self._raw(project)["story"]
        self.assertIsNone(kept)                                  # 也不会伪造 story
        self.assertNotEqual((project / "project.json").read_bytes(), before)

    def test_quarantine_failure_does_not_touch_original(self):
        # P1-Fix-3：隔离发生在写盘闸门；隔离失败 → 整个打开流程零业务写入，
        # 原文件字节不变（无恢复源时打开本身就零写入，另有专项测试覆盖）。
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        path = self._corrupt_primary(project)          # project.json 有效：有恢复源
        before = _snapshot_tree(project)
        with mock.patch.object(v3.shutil, "copy2", side_effect=OSError("磁盘满")):
            with self.assertRaises((v3.RepositoryError, OSError, ProjectError)):
                self.pm.open_project(project)
        self.assertEqual(path.read_bytes(), b'{"broken": ')
        self.assertEqual(_snapshot_tree(project), before)   # 零写入


class P1ScopeTest(unittest.TestCase):
    """P1 边界：不调用真实 AI API，不引入网络依赖。"""

    def test_data_layer_does_not_import_ai_or_gui(self):
        source = (Path(__file__).resolve().parent.parent
                  / "modules" / "v3_storage.py").read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "tkinter", "story_engine", "main_window"):
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(f"from {forbidden}", source)


class P1Fix2CorruptJudgeTest(_Base):
    """P1-Fix-2 / R-A2：JSON 合法性、结构可用性、业务有效性分级判定。"""

    def _set_project_story(self, project, value):
        path = project / "project.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["story"] = value
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    def test_valid_json_shots_string_is_quarantined_and_recovered(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        bad = json.dumps({"schema_version": 2, "title": "坏", "shots": "not-a-list"})
        (project / "stories/story/story.json").write_text(bad, encoding="utf-8")
        self.pm.open_project(project)
        backups = list((project / ".corrupt").glob("story.json.*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), bad.encode("utf-8"))   # 原始字节保留
        story = self._story_file(project)
        self.assertEqual(len(story["shots"]), 3)                          # 由 project.json 恢复
        self.assertNotIn("_v3_adopt", story)

    def test_valid_json_root_not_object_is_corrupt(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        path = project / "stories/story/story.json"
        path.write_text('[1, 2, 3]', encoding="utf-8")
        self.pm.open_project(project)
        self.assertEqual(len(self._story_file(project)["shots"]), 3)
        self.assertEqual(list((project / ".corrupt").glob("story.json.*.bak"))[0]
                         .read_bytes(), b'[1, 2, 3]')

    def test_shots_missing_is_corrupt(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        (project / "stories/story/story.json").write_text(
            json.dumps({"schema_version": 2, "title": "无镜头"}), encoding="utf-8")
        self.pm.open_project(project)
        self.assertEqual(len(self._story_file(project)["shots"]), 3)

    def test_empty_shots_is_legal_not_corrupt(self):
        project = self._project()
        self.pm.set_story(project, _story(n=0))
        path = project / "stories/story/story.json"
        before = path.read_bytes()
        self.assertFalse(v3.is_valid_story({"shots": []}))          # 业务上「空」
        self.assertTrue(v3.is_structural_story({"shots": []}))      # 结构上「可用」
        self.pm.open_project(project)
        self.assertEqual(path.read_bytes(), before)                 # 一个字节都没动
        self.assertFalse((project / ".corrupt").exists())
        self.assertEqual(self._story_file(project)["shots"], [])

    def test_structural_bad_both_sides_but_project_json_recoverable(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        valid_story = self.pm.get_story(self.pm.load(project))
        valid_story["shots"] = [{"index": 1, "scene": "a", "narration": "b",
                                 "duration": 1.0}]
        self.pm.set_story(project, valid_story)          # stories/ 与 project.json 同步
        (project / "stories/story/story.json").write_text(
            json.dumps({"shots": "bad"}), encoding="utf-8")
        self.pm.open_project(project)
        self.assertEqual(len(self._story_file(project)["shots"]), 1)
        self.assertEqual(self._story_file(project)["shots"][0]["scene"], "a")
        self.assertEqual(len(list((project / ".corrupt").glob("story.json.*.bak"))), 1)

    def test_structural_bad_both_sides_recovers_from_history(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        saved = self.pm.save_version(project, self.pm.load(project), note="基线")
        self.pm.clear_story(project)                     # 两侧都没有可用 Story
        self.assertIsNone(self._raw(project).get("story"))
        (project / "stories/story/story.json").write_text(
            json.dumps({"shots": {"not": "list"}}), encoding="utf-8")
        self.pm.open_project(project)
        story = self._story_file(project)
        self.assertEqual(len(story["shots"]), 3)         # 从 versions/ 快照恢复
        active = story["active_version"]
        self.assertTrue(active)                          # 合法活动版本
        self.assertTrue((project / "versions" / f"{active}.json").exists())
        listed = [v["version_id"] for v in story["versions"]]
        self.assertIn(saved["version_id"], listed)      # 用户存的版本都还在
        self.assertIn(active, listed)
        self.assertEqual(self.pm.recovery_status["state"], "recovered")
        for marker in ("_v3_adopt", "_recovery_candidate", "recovery_status",
                       "_not_recovered"):
            self.assertNotIn(marker, story)              # 内部标记不落盘
        self.assertNotIn("recovery_status", self._raw(project))

    def test_structural_bad_no_history_raises_and_keeps_bytes(self):
        # 双侧结构损坏（project.json 的 shots 不是列表）且无快照：明确报错，
        # 原始字节全部保留（P1-Fix-3：原位不动，不隔离、不删除），绝不用空骨架覆盖。
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        bad = json.dumps({"shots": None})
        for entry in (project / "versions").glob("*.json"):
            entry.unlink()
        path = project / "stories/story/story.json"
        path.write_text(bad, encoding="utf-8")
        raw = self._raw(project)
        raw["story"] = {"schema_version": 2, "title": "坏", "shots": "not-a-list"}
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        before = _snapshot_tree(project)
        with self.assertRaises((v3.CorruptDataError, ProjectError)) as ctx:
            self.pm.open_project(project)
        # 明确报「无法恢复」的损坏，而不是把失败伪装成「没有故事 / 正常空项目」
        self.assertIn("结构无效", str(ctx.exception))
        self.assertIn("保持原位", str(ctx.exception))
        self.assertEqual(_snapshot_tree(project), before)     # 全项目字节零变化
        self.assertEqual(path.read_bytes(), bad.encode("utf-8"))
        self.assertFalse((project / ".corrupt").exists())
        # project.json 的坏 story 原样保留（未采用、未改写）
        self.assertEqual(json.loads((project / "project.json").read_text("utf-8"))["story"],
                         {"schema_version": 2, "title": "坏", "shots": "not-a-list"})
    def test_quarantine_failure_aborts_without_any_write(self):
        # V3 层只读：隔离失败在这里已不适用；真正的隔离闸门失败见 P1Fix3QuarantineFailTest
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        path = project / "stories/story/story.json"
        path.write_text(json.dumps({"shots": "bad"}), encoding="utf-8")
        before = _snapshot_tree(project)
        with mock.patch.object(v3.shutil, "copy2", side_effect=OSError("磁盘满")):
            data = self._raw(project)
            data = v3.V3ProjectManager(project).load(data)[0]
        self.assertEqual(data["_v3_adopt"]["shots"][0]["index"], 1)   # 仅内存采纳
        after = _snapshot_tree(project)
        self.assertEqual(after, before)              # 只读判定：零写入

    def test_open_get_story_save_reopen_preserves_original_bytes(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        bad = b'{"broken": '
        (project / "stories/story/story.json").write_bytes(bad)
        self.pm.open_project(project)
        data = self.pm.load(project)
        self.assertEqual(len(self.pm.get_story(data)["shots"]), 3)     # V2 视图可用
        self.pm.save(project, data)                                    # 保存不丢数据
        backups = list((project / ".corrupt").glob("story.json.*.bak"))
        self.assertEqual(backups[0].read_bytes(), bad)                 # 原始字节仍在
        self.pm.open_project(project)                                  # 再开一次稳定
        self.assertEqual(len(self._story_file(project)["shots"]), 3)
        self.assertEqual(len(list((project / ".corrupt").glob("story.json.*.bak"))), 1)

    def test_partial_recovery_is_marked_and_not_written_back(self):
        project = self._project()               # 新建项目：合法的空故事
        path = project / "stories/story/story.json"
        path.write_bytes(b'{"broken": ')
        self.pm.open_project(project)
        # P1-Fix-3：无恢复源 → 只读判定，不隔离、不删除、零写入
        self.assertEqual(self.pm.recovery_status["state"], "partial")
        self.assertIn("未从 versions/ 覆盖", self.pm.recovery_status["reason"])
        self.assertEqual(path.read_bytes(), b'{"broken": ')  # 原始字节原位保留
        self.assertFalse((project / ".corrupt").exists())
        data = self.pm.load(project)
        self.assertIsNone(self.pm.get_story(data))   # 损坏文件不当作故事
        # 打开流程已对账并保持零写入：原始文件、project.json 的 story 字段都未被改动
        # （独立于打开流程的 save 不再持有 V3 上下文，故这里只断言「损坏文件不被触碰」）
        data = self.pm.migrate(self.pm.load(project))[0]
        self.pm.save(project, data)
        self.assertEqual(path.read_bytes(), b'{"broken": ')
        self.assertFalse((project / ".corrupt").exists())
        raw = self._raw(project)
        self.assertNotIn("recovery_status", raw)      # 恢复状态只留在内存
        self.assertNotIn("_not_recovered", raw)
        self.assertFalse(raw.get("story"))
        # 用户手工修复后正常保存即可
        path.write_text(json.dumps(dict(v3.new_story(story_id="story",
                                                     project_id="V3项目"),
                                        schema_version=2)), encoding="utf-8")
        data = self.pm.migrate(self.pm.load(project))[0]
        self.pm.save(project, data)
        self.pm.open_project(project)
        self.assertIsNone(self.pm.recovery_status)


class P1Fix2VersionRebuildTest(_Base):
    """P1-Fix-2 / R-C1：从 versions/ 重建版本元信息，不伪造、不删除。"""

    def _seed(self, project, n=3):
        """存一版故事，再用 save_version 记录一版带 note 的（返回 note 版条目）。"""
        self.pm.set_story(project, _story(n=n))
        return self.pm.save_version(project, self.pm.load(project), note="基线")

    def _break_story(self, project):
        # 两侧都没有可用 Story，只剩 versions/ 快照文件
        self.pm.clear_story(project)
        (project / "stories/story/story.json").write_bytes(b'{"broken": ')

    def _versions_root(self, project):
        return project / "versions"

    def _disk_ids(self, project):
        return {p.stem for p in self._versions_root(project).glob("v*.json")}

    def test_versions_list_contains_every_verifiable_snapshot(self):
        project = self._project()
        saved = self._seed(project)
        self._break_story(project)
        disk = self._disk_ids(project)                     # 所有快照都完整可读
        self.assertIn(saved["version_id"], disk)
        data, changed = v3.V3ProjectManager(project).load(self._raw(project))
        self.assertTrue(changed)
        listed = [v["version_id"] for v in data["story"]["versions"]]
        self.assertEqual(sorted(listed), sorted(disk))     # 可验证的全部列出，且不漏
        self.assertEqual(data["recovery_status"]["state"], "recovered")

    def test_listed_entries_are_rebuilt_from_snapshot_content(self):
        project = self._project()
        saved = self._seed(project)
        snapshot = json.loads((self._versions_root(project)
                               / f"{saved['version_id']}.json").read_text("utf-8"))
        self._break_story(project)
        data, _ = v3.V3ProjectManager(project).load(self._raw(project))
        entry = [v for v in data["story"]["versions"]
                 if v["version_id"] == saved["version_id"]][0]
        self.assertEqual(entry["note"], snapshot["note"])
        self.assertEqual(entry["created_at"], snapshot["created_at"])
        self.assertEqual(entry["title"], snapshot["title"])
        self.assertEqual(entry["shot_count"], len(snapshot["shots"]))
        self.assertEqual(entry["file"], f"versions/{saved['version_id']}.json")

    def test_active_version_points_to_real_readable_version(self):
        project = self._project()
        saved = self._seed(project)
        self._break_story(project)
        data, _ = v3.V3ProjectManager(project).load(self._raw(project))
        active = data["story"]["active_version"]
        self.assertTrue(active)                            # 合法、非空
        self.assertIn(active, self._disk_ids(project))     # 指向真实存在的快照文件
        self.assertTrue((self._versions_root(project) / f"{active}.json").exists())
        listed = {v["version_id"]: v for v in data["story"]["versions"]}
        self.assertIn(active, listed)
        self.assertEqual(listed[active]["file"], f"versions/{active}.json")
        self.assertIn(saved["version_id"], listed)         # 用户显式存的版本也在列表里

    def test_unreadable_snapshot_is_not_fabricated(self):
        project = self._project()
        saved = self._seed(project)
        broken_id = "v20990101-000000-ffff"
        broken = self._versions_root(project) / f"{broken_id}.json"
        broken.write_bytes(b'{"broken": ')
        self._break_story(project)
        data, _ = v3.V3ProjectManager(project).load(self._raw(project))
        listed = [v["version_id"] for v in data["story"]["versions"]]
        self.assertNotIn(broken_id, listed)                 # 不伪造读不出的版本
        self.assertIn(saved["version_id"], listed)
        self.assertNotEqual(data["story"]["active_version"], broken_id)
        self.assertEqual(data["recovery_status"]["state"], "partial")
        self.assertIn(broken_id, data["recovery_status"]["reason"])
        self.assertEqual(broken.read_bytes(), b'{"broken": ')  # 原快照文件未动

    def test_structural_bad_snapshot_is_not_listed(self):
        project = self._project()
        saved = self._seed(project)
        bad_id = "v20990101-000000-eeee"
        bad = self._versions_root(project) / f"{bad_id}.json"
        bad.write_text(json.dumps({"version_id": bad_id, "shots": "bad"}), encoding="utf-8")
        self._break_story(project)
        data, _ = v3.V3ProjectManager(project).load(self._raw(project))
        listed = [v["version_id"] for v in data["story"]["versions"]]
        self.assertNotIn(bad_id, listed)                    # 结构坏的快照不算可验证
        self.assertIn(saved["version_id"], listed)
        self.assertTrue(bad.exists())                       # 文件保留

    def test_missing_shots_snapshot_is_not_listed(self):
        project = self._project()
        saved = self._seed(project)
        bad_id = "v20990101-000000-dddd"
        bad = self._versions_root(project) / f"{bad_id}.json"
        bad.write_text(json.dumps({"version_id": bad_id, "title": "无镜头"}), encoding="utf-8")
        self._break_story(project)
        data, _ = v3.V3ProjectManager(project).load(self._raw(project))
        listed = [v["version_id"] for v in data["story"]["versions"]]
        self.assertNotIn(bad_id, listed)                    # 无镜头的快照不作为版本
        self.assertIn(saved["version_id"], listed)

    def test_entries_have_required_fields_and_no_dangling_refs(self):
        project = self._project()
        saved = self._seed(project)
        self._break_story(project)
        data, _ = v3.V3ProjectManager(project).load(self._raw(project))
        entries = {v["version_id"]: v for v in data["story"]["versions"]}
        for entry in entries.values():
            for key in ("created_at", "note", "official", "title", "shot_count", "file"):
                self.assertIn(key, entry)
            if entry.get("base_version"):
                self.assertIn(entry["base_version"], entries)  # 不留悬空引用
        self.assertEqual(entries[saved["version_id"]]["note"], "基线")

    def test_restore_after_recovery_keeps_base_reference(self):
        project = self._project()
        saved = self._seed(project)
        self._break_story(project)
        self.pm.open_project(project)
        data = self.pm.migrate(self.pm.load(project))[0]
        entry = self.pm.restore_version(project, saved["version_id"])
        self.assertEqual(entry.get("base_version"), saved["version_id"])
        listed = [v for v in self._story_file(project)["versions"]
                  if v["version_id"] == entry["version_id"]]
        self.assertTrue(listed)
        self.assertEqual(listed[0].get("base_version"), saved["version_id"])
        self.assertNotIn("_v3_adopt", self._story_file(project))
        del data

    def test_original_snapshot_files_all_kept(self):
        project = self._project()
        self._seed(project)
        before = {p.name: p.read_bytes()
                  for p in self._versions_root(project).glob("*.json")}
        self._break_story(project)
        self.pm.open_project(project)
        after = {p.name: p.read_bytes()
                 for p in self._versions_root(project).glob("*.json")}
        for name, raw in before.items():
            self.assertEqual(after[name], raw)               # 字节不变
        self.assertTrue(set(before) <= set(after))

    def test_reopen_keeps_rebuilt_list(self):
        project = self._project()
        saved = self._seed(project)
        self._break_story(project)
        self.pm.open_project(project)
        first = [v["version_id"] for v in self._story_file(project)["versions"]]
        self.assertIn(saved["version_id"], first)
        self.assertEqual(sorted(first), sorted(self._disk_ids(project)))
        self.pm.open_project(project)
        second = [v["version_id"] for v in self._story_file(project)["versions"]]
        self.assertEqual(first, second)                      # 重开不丢列表、不重复
        self.assertNotIn("_v3_adopt", self._story_file(project))

    def test_save_version_after_recovery_keeps_old_and_new(self):
        project = self._project()
        saved = self._seed(project)
        self._break_story(project)
        self.pm.open_project(project)
        new = self.pm.save_version(project, self.pm.load(project), note="恢复后")["version_id"]
        listed = [v["version_id"] for v in self._story_file(project)["versions"]]
        self.assertIn(new, listed)
        self.assertIn(saved["version_id"], listed)
        self.assertTrue((self._versions_root(project) / f"{new}.json").exists())

    def test_file_missing_path_strips_internal_markers(self):
        project = self._project()
        saved = self._seed(project)
        (project / "stories/story/story.json").unlink()      # 只有文件缺失
        self.pm.open_project(project)
        story = self._story_file(project)
        for marker in ("_v3_adopt", "_recovery_candidate", "recovery_status"):
            self.assertNotIn(marker, story)                  # 内部标记不落盘
        self.assertEqual(len(story["shots"]), 3)
        listed = [v["version_id"] for v in story["versions"]]
        self.assertIn(saved["version_id"], listed)           # 同样走元信息重建
        self.assertEqual(sorted(listed), sorted(self._disk_ids(project)))


class P1Fix2TaskBoundaryTest(_Base):
    """P1-Fix-2 / R-T1：未来版本只读边界不覆盖 .tasks/ 运行过程元数据。"""

    def _future_project(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        self.pm.save_version(project, self.pm.load(project), note="基线")
        raw = self._raw(project)
        raw["schema_version"] = v3.V3_SCHEMA_VERSION + 1
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        return project

    def _business(self, project):
        return {str(p.relative_to(project)): p.read_bytes()
                for p in project.rglob("*")
                if p.is_file() and ".tasks" not in p.parts}

    def test_start_and_finish_allowed_on_future_project(self):
        project = self._future_project()
        before = self._business(project)
        tasks = v3.TaskStore(project)
        task = tasks.start("render", "渲染")
        self.assertEqual(task["status"], "running")
        self.assertTrue(any((project / ".tasks").glob("*.json")))
        done = tasks.finish(task["task_id"], "succeeded")
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(self.pm.load(project)["schema_version"], 4)   # 磁盘仍是未来版本
        self.assertEqual(self._business(project), before)              # 业务数据零改动

    def test_mark_abandoned_refused_on_future_project(self):
        project = self._future_project()
        tasks = v3.TaskStore(project)
        # 直接写一条 running 记录（绕过 start 之外的路径），再验证守卫
        (project / ".tasks").mkdir(exist_ok=True)
        (project / ".tasks" / "t1.json").write_text(json.dumps(
            {"task_id": "t1", "kind": "render", "status": "running"}), encoding="utf-8")
        before = (project / ".tasks" / "t1.json").read_bytes()
        tasks = v3.TaskStore(project)
        with self.assertRaises(v3.RepositoryError):
            tasks.mark_abandoned()
        self.assertEqual((project / ".tasks" / "t1.json").read_bytes(), before)

    def test_future_version_business_write_still_refused(self):
        project = self._future_project()
        before = self._business(project)
        data = self.pm.load(project)
        with self.assertRaises((ProjectReadOnlyError, v3.RepositoryError)):
            self.pm.save(project, data)
        self.assertEqual(self._business(project), before)

    def test_normal_v3_task_behavior_unchanged(self):
        project = self._project()
        tasks = v3.TaskStore(project)
        task = tasks.start("render")
        self.assertEqual(tasks.mark_abandoned(), 1)
        self.assertEqual(tasks.get(task["task_id"])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
class P1Fix3QuarantineGateTest(_Base):
    """P1-Fix-3：隔离推迟到「确认恢复源、即将写盘」的闸门（方案 A）。

    规则 1：双侧损坏且无恢复源 → 报错 + 全项目字节零变化；
    规则 2：有恢复源 → 先隔离，隔离成功后才写盘；
    规则 3：隔离失败 → 中止，不写任何业务文件；
    规则 4：正常 V2 / V3 / 未来版本 / 旧行为不回退。
    """

    def _primary(self, project):
        return project / "stories" / "story" / "story.json"

    def _corrupt_primary(self, project):
        path = self._primary(project)
        path.write_bytes(b'{"broken": ')
        return path

    def _business(self, project):
        """项目内文件字节集合（排除运行期 .tasks/）。"""
        project = Path(project)
        return {str(p.relative_to(project)): p.read_bytes()
                for p in project.rglob("*")
                if p.is_file() and ".tasks" not in p.parts}

    def _both_broken_no_snapshot(self):
        """stories/ 损坏 + project.json story 结构坏 + 无 versions/ 可用快照。"""
        project = self._project()
        self.pm.set_story(project, _story(n=3))       # 先有内容，再制造双侧损坏
        path = self._corrupt_primary(project)
        for entry in (project / "versions").glob("*.json"):
            entry.unlink()
        raw = self._raw(project)
        raw["story"] = {"schema_version": 2, "title": "坏", "shots": "not-a-list"}
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        return project, path

    # 1 ---------------------------------------------------------------
    def test_rule1_both_broken_no_snapshot_raises_and_zero_bytes(self):
        project, path = self._both_broken_no_snapshot()
        before = _snapshot_tree(project)
        with self.assertRaises(ProjectError) as ctx:
            self.pm.open_project(project)
        self.assertIn("无法恢复", str(ctx.exception))
        self.assertIn("保持原位", str(ctx.exception))
        self.assertEqual(_snapshot_tree(project), before)      # 全项目零变化
        self.assertTrue(path.exists())                          # 原始文件原位
        self.assertEqual(path.read_bytes(), b'{"broken": ')
        self.assertFalse((project / ".corrupt").exists())       # 不做备份
        self.assertEqual(self._raw(project)["story"]["shots"], "not-a-list")

    # 2 ---------------------------------------------------------------
    def test_rule1_repeated_open_is_stable(self):
        project, path = self._both_broken_no_snapshot()
        before = _snapshot_tree(project)
        for _ in range(2):
            with self.assertRaises(ProjectError):
                self.pm.open_project(project)
            self.assertEqual(_snapshot_tree(project), before)
        self.assertEqual(path.read_bytes(), b'{"broken": ')
        self.assertFalse((project / ".corrupt").exists())

    # 3 ---------------------------------------------------------------
    def test_rule2_with_snapshot_recovers_and_quarantines(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        self.pm.save_version(project, self.pm.load(project), note="基线")
        self._corrupt_primary(project)
        raw = self._raw(project)
        raw["story"] = {"schema_version": 2, "title": "坏", "shots": "not-a-list"}
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        self.pm.open_project(project)                           # 恢复流程
        story = self._story_file(project)
        self.assertEqual(len(story["shots"]), 3)                # 恢复成功
        backups = list((project / ".corrupt").glob("story.json.*.bak"))
        self.assertEqual(len(backups), 1)                       # 原始字节被隔离
        self.assertEqual(backups[0].read_bytes(), b'{"broken": ')
        self.assertEqual(self.pm.recovery_status["state"], "recovered")

    # 3b --------------------------------------------------------------
    def test_marker_consumed_after_recovery_other_project_untouched(self):
        # 同一实例恢复过一个项目之后，再操作另一个正常项目：绝不误隔离
        broken = self._project(name="损坏项目")
        self.pm.set_story(broken, _story(n=3))
        self._corrupt_primary(broken)
        self.pm.open_project(broken)                      # 有恢复源：恢复 + 隔离
        self.assertEqual(len(list((broken / ".corrupt").glob("*.bak"))), 1)
        other = self._project(name="正常项目")
        self.pm.set_story(other, _story(n=2))
        before = _snapshot_tree(other)
        self.pm.open_project(other)
        self.pm.save(other, self.pm.load(other))
        self.assertFalse((other / ".corrupt").exists())   # 没被误隔离
        self.assertEqual(len(self._story_file(other)["shots"]), 2)
        self.assertIsNone(self.pm._pending_quarantine)    # 标记已消费/清除
        self.assertFalse(self.pm._pending_authoritative)
        self.assertNotEqual(_snapshot_tree(other), before)

    # 4 ---------------------------------------------------------------
    def test_rule2_project_json_preferred_and_content_kept(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3, title="存活的故事"))
        self.pm.save_version(project, self.pm.load(project), note="基线")
        path = self._corrupt_primary(project)                  # project.json 仍有效
        self.pm.open_project(project)
        story = self._story_file(project)
        self.assertEqual(story["title"], "存活的故事")
        self.assertEqual(len(story["shots"]), 3)
        backups = list((project / ".corrupt").glob("story.json.*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'{"broken": ')
        self.assertNotEqual(path.read_bytes(), b'{"broken": ')  # 恢复内容已写回

    # 5 ---------------------------------------------------------------
    def test_rule3_quarantine_failure_writes_no_business_file(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        path = self._corrupt_primary(project)                  # 有恢复源
        before = _snapshot_tree(project)
        with mock.patch.object(v3.shutil, "copy2", side_effect=OSError("磁盘满")):
            with self.assertRaises((v3.RepositoryError, OSError, ProjectError)):
                self.pm.open_project(project)
        self.assertEqual(_snapshot_tree(project), before)      # 业务文件零写入
        self.assertEqual(path.read_bytes(), b'{"broken": ')

    # 6 ---------------------------------------------------------------
    def test_rule4_v2_project_migration_unchanged(self):
        project = self.tmp / "v2普通项目"
        for sub in ("images", "audio", "subtitles", "output", "temp", "versions"):
            (project / sub).mkdir(parents=True)
        (project / "project.json").write_text(json.dumps({
            "schema_version": 2, "name": "v2普通项目", "created_at": "2026-01-01T00:00:00",
            "settings": {}, "shots": [], "narration": None, "music": None,
            "subtitle": None, "story": _story(title="V2 故事")},
            ensure_ascii=False), encoding="utf-8")
        self.pm.open_project(project)
        raw = self._raw(project)
        self.assertEqual(raw["schema_version"], v3.V3_SCHEMA_VERSION)
        self.assertEqual(raw["story"]["title"], "V2 故事")
        self.assertEqual(len(self._story_file(project)["shots"]), 3)
        self.assertFalse((project / ".corrupt").exists())      # 没有误报隔离

    # 7 ---------------------------------------------------------------
    def test_rule4_normal_v3_open_save_reopen(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        self.pm.open_project(project)
        self.assertIsNone(self.pm.recovery_status)
        self.assertFalse((project / ".corrupt").exists())
        data = self.pm.load(project)
        data["story"]["title"] = "改名后"
        self.pm.save(project, data)
        self.pm.open_project(project)
        self.assertEqual(self._story_file(project)["title"], "改名后")
        self.assertIsNone(self.pm.recovery_status)
        self.assertFalse((project / ".corrupt").exists())

    # 8 ---------------------------------------------------------------
    def test_rule4_partial_protection_not_regressed(self):
        project = self._project()                               # 合法空故事
        path = self._corrupt_primary(project)
        before = _snapshot_tree(project)
        self.pm.open_project(project)                           # 无恢复源：零写入
        self.assertEqual(self.pm.recovery_status["state"], "partial")
        self.assertEqual(_snapshot_tree(project), before)
        self.assertEqual(path.read_bytes(), b'{"broken": ')
        self.assertFalse((project / ".corrupt").exists())

    # 9 ---------------------------------------------------------------
    def test_rule4_non_open_paths_unaffected(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        self.assertFalse((project / ".corrupt").exists())
        # save_version / restore_version / add_images / clear_story 均正常
        entry = self.pm.save_version(project, self.pm.load(project), note="v1")
        self.pm.restore_version(project, entry["version_id"])
        self.assertEqual(len(self._story_file(project)["shots"]), 3)
        image = self.tmp / "01.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        added = self.pm.add_images(project, [image])
        self.assertEqual(len(added), 1)
        self.assertEqual(len(self._raw(project)["shots"]), 1)
        self.pm.clear_story(project)
        self.assertEqual(self._story_file(project)["shots"], [])
        self.assertFalse((project / ".corrupt").exists())

    def test_rule4_non_open_paths_keep_project_consistent(self):
        # 与上一条相同的正常路径之外，再确认「正常 V3 项目在 save 后重新打开」稳定
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        self.pm.save(project, self.pm.load(project))
        self.pm.open_project(project)
        self.assertEqual(len(self._story_file(project)["shots"]), 2)
        self.assertFalse((project / ".corrupt").exists())

    # 10 --------------------------------------------------------------
    def test_rule4_future_version_boundary_unchanged(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        raw = self._raw(project)
        raw["schema_version"] = v3.V3_SCHEMA_VERSION + 1
        raw["future_field"] = "保留"
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        before = _snapshot_tree(project)
        self.pm.open_project(project)                           # 只读打开
        self.assertEqual(_snapshot_tree(project), before)
        kept = self._raw(project)
        self.assertEqual(kept["schema_version"], v3.V3_SCHEMA_VERSION + 1)
        self.assertEqual(kept["future_field"], "保留")
        with self.assertRaises(ProjectReadOnlyError):
            self.pm.save(project, self.pm.load(project))

    # 11 --------------------------------------------------------------
    def test_rule1_internal_markers_never_written(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        self.pm.save_version(project, self.pm.load(project), note="基线")
        self._corrupt_primary(project)                          # 有恢复源：写入恢复
        self.pm.open_project(project)
        raw_text = (project / "project.json").read_text(encoding="utf-8")
        story_text = self._primary(project).read_text(encoding="utf-8")
        for marker in ("_pending_quarantine", "_quarantine_source", "_v3_adopt",
                       "recovery_status", "_not_recovered", "_recovery_candidate",
                       "_version_snapshot_due", "_v3_upgraded", "_pending_authoritative"):
            self.assertNotIn(marker, raw_text)
            self.assertNotIn(marker, story_text)

    # 12 --------------------------------------------------------------
    def test_rule2_versions_and_active_version_after_recovery(self):
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        saved = self.pm.save_version(project, self.pm.load(project), note="基线")
        self._corrupt_primary(project)
        raw = self._raw(project)
        raw["story"] = {"schema_version": 2, "title": "坏", "shots": "not-a-list"}
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        self.pm.open_project(project)
        data = self.pm.load(project)
        version_ids = {v["version_id"] for v in data["story"]["versions"]}
        disk_ids = {p.stem for p in (project / "versions").glob("v*.json")}
        self.assertEqual(version_ids, disk_ids)                 # 列表与磁盘一致
        self.assertIn(data["story"]["active_version"], version_ids)   # active 指向真实版本
        self.assertIn(saved["version_id"], version_ids)               # 基线快照未被丢弃
        # 恢复后的 Story 快照与原版本内容一致
        self.assertEqual(len(self._story_file(project)["shots"]), 3)
class P1Fix3R1WriteOrderTest(_Base):
    """P1-Fix-3-R1：打开 / 存版本的写盘副作用顺序，以及隔离失败清理。"""

    def _broken_project_without_versions(self):
        """双侧损坏、无可用快照、项目原本没有 versions/。"""
        project = self._project()
        self.pm.set_story(project, _story(n=3))
        (project / "stories/story/story.json").write_bytes(b'{"broken": ')
        for entry in (project / "versions").glob("*.json"):
            entry.unlink()
        (project / "versions").rmdir()
        raw = self._raw(project)
        raw["story"] = {"schema_version": 2, "title": "坏", "shots": "not-a-list"}
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        self.assertFalse((project / "versions").exists())
        return project

    # 测试 A ------------------------------------------------------------
    def test_open_failure_does_not_create_versions(self):
        project = self._broken_project_without_versions()
        before = _snapshot_tree(project)
        with self.assertRaises(ProjectError):
            self.pm.open_project(project)
        self.assertFalse((project / "versions").exists())
        self.assertEqual(_snapshot_tree(project), before)    # 文件 + 目录集合不变

    def test_normal_open_keeps_versions_directory(self):
        # 正常项目打开后 versions/ 仍存在（原有语义不回退）；只读打开不新增目录
        project = self._project()
        self.pm.open_project(project)
        self.assertTrue((project / "versions").is_dir())
        (project / "versions").rmdir()
        self.pm.open_project(project)                        # 正常、无需写盘
        self.assertFalse((project / "versions").exists())
        # 需要写盘（V2 → V3 对账）时由写盘前创建
        self.pm.set_story(project, _story(n=2))
        self.assertTrue((project / "versions").is_dir())

    # 测试 B ------------------------------------------------------------
    def test_save_version_gate_failure_does_not_create_versions(self):
        # 与打开流程一致：一次 migrate（V3 判定）→ 同一 data 直接 save_version。
        # 独立的 load→migrate 不开 V3 上下文，不会产生待隔离标记（见 P1-Fix-3 设计）。
        project = self._broken_project_without_versions()
        raw = self._raw(project)
        raw["story"] = _story(n=3)               # 有恢复源（project.json 可用）
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        outer = self.pm._v3_context(project)
        try:
            data = self.pm.migrate(self.pm.load(project))[0]
            data = self.pm.migrate(data)[0]      # V2 代码写法：二次 migrate 不会丢标记
            self.assertTrue(self.pm._pending_quarantine is not None)
            before = _snapshot_tree(project)
            with mock.patch.object(v3.shutil, "copy2", side_effect=OSError("磁盘满")):
                with self.assertRaises(ProjectError):
                    self.pm.save_version(project, data, note="闸门失败")
        finally:
            self.pm._v3_restore(outer)
        self.assertFalse((project / "versions").exists())    # 不创建空目录
        self.assertEqual(_snapshot_tree(project), before)    # 业务文件零写入
        self.assertEqual((project / "stories/story/story.json").read_bytes(),
                         b'{"broken": ')

    def test_save_version_normal_still_creates_versions(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        for entry in (project / "versions").glob("*.json"):
            entry.unlink()
        (project / "versions").rmdir()
        self.assertFalse((project / "versions").exists())
        entry = self.pm.save_version(project, self.pm.load(project), note="正常")
        self.assertTrue((project / "versions" / f"{entry['version_id']}.json").exists())

    # 测试 C ------------------------------------------------------------
    def test_staging_replace_failure_leaves_no_files(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        path = project / "stories/story/story.json"
        path.write_bytes(b'{"broken": ')
        before = _snapshot_tree(project)
        vm = v3.V3ProjectManager(project)
        with mock.patch.object(Path, "replace",
                               side_effect=OSError("rename 失败")):
            self.assertIsNone(vm._quarantine_corrupt(path))
        self.assertEqual(path.read_bytes(), b'{"broken": ')  # 原文件完整
        self.assertFalse((project / ".corrupt").exists())    # 无 staging / 正式备份
        self.assertEqual(_snapshot_tree(project), before)

    def test_staging_replace_failure_keeps_history_backups(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        path = project / "stories/story/story.json"
        path.write_bytes(b'{"broken": ')
        root = project / ".corrupt"
        root.mkdir()
        history = root / "story.json.20200101-000000-000000.bak"
        history.write_bytes(b'history')
        vm = v3.V3ProjectManager(project)
        with mock.patch.object(Path, "replace",
                               side_effect=OSError("rename 失败")):
            self.assertIsNone(vm._quarantine_corrupt(path))
        self.assertTrue(root.is_dir())                       # 既有目录保留
        self.assertEqual(sorted(p.name for p in root.iterdir()), [history.name])
        self.assertEqual(history.read_bytes(), b'history')

    # 测试 D ------------------------------------------------------------
    def test_unlink_failure_removes_new_backup_and_keeps_original(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        path = project / "stories/story/story.json"
        path.write_bytes(b'{"broken": ')
        real_unlink = Path.unlink

        def fake_unlink(self, *args, **kwargs):
            if self == path:
                raise OSError("文件被占用")
            return real_unlink(self, *args, **kwargs)

        vm = v3.V3ProjectManager(project)
        with mock.patch.object(Path, "unlink", fake_unlink):
            self.assertIsNone(vm._quarantine_corrupt(path))  # 没有返回成功
        self.assertEqual(path.read_bytes(), b'{"broken": ')  # 原文件完整
        self.assertFalse((project / ".corrupt").exists())    # 新 target / staging 已清

    def test_unlink_failure_keeps_history_backups(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        path = project / "stories/story/story.json"
        path.write_bytes(b'{"broken": ')
        root = project / ".corrupt"
        root.mkdir()
        history = root / "story.json.20200101-000000-000000.bak"
        history.write_bytes(b'history')
        real_unlink = Path.unlink

        def fake_unlink(self, *args, **kwargs):
            if self == path:
                raise OSError("文件被占用")
            return real_unlink(self, *args, **kwargs)

        vm = v3.V3ProjectManager(project)
        with mock.patch.object(Path, "unlink", fake_unlink):
            self.assertIsNone(vm._quarantine_corrupt(path))
        self.assertEqual(sorted(p.name for p in root.iterdir()), [history.name])
        self.assertEqual(history.read_bytes(), b'history')

    # 测试 E ------------------------------------------------------------
    def test_failure_cleanup_preserves_existing_corrupt_dir(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        path = project / "stories/story/story.json"
        path.write_bytes(b'{"broken": ')
        root = project / ".corrupt"
        root.mkdir()
        history = root / "old.bak"
        history.write_bytes(b'old')
        before = _snapshot_tree(project)
        vm = v3.V3ProjectManager(project)
        with mock.patch.object(v3.shutil, "copy2", side_effect=OSError("磁盘满")):
            self.assertIsNone(vm._quarantine_corrupt(path))
        self.assertEqual(_snapshot_tree(project), before)    # 目录与文件完全不变

    def test_success_backs_up_original_bytes(self):
        project = self._project()
        self.pm.set_story(project, _story(n=2))
        path = project / "stories/story/story.json"
        path.write_bytes(b'{"broken": ')
        vm = v3.V3ProjectManager(project)
        backup = vm._quarantine_corrupt(path)
        self.assertIsNotNone(backup)
        self.assertFalse(path.exists())                       # 隔离后移出原位置
        self.assertEqual(backup.read_bytes(), b'{"broken": ')  # 原始字节完整备份
        self.assertEqual(sorted(p.name for p in (project / ".corrupt").iterdir()),
                         [backup.name])                     # 无 staging 残留

    # 回归 --------------------------------------------------------------
    def test_open_failure_repeatedly_never_creates_versions(self):
        project = self._broken_project_without_versions()
        before = _snapshot_tree(project)
        for _ in range(2):
            with self.assertRaises(ProjectError):
                self.pm.open_project(project)
        self.assertEqual(_snapshot_tree(project), before)
        self.assertFalse((project / "versions").exists())
        self.assertFalse((project / ".corrupt").exists())
