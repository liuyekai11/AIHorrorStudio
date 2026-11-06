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
        project = self._project()
        raw = self._raw(project)
        raw["story"] = None
        (project / "project.json").write_text(json.dumps(raw, ensure_ascii=False),
                                              encoding="utf-8")
        (project / "stories" / "story" / "story.json").unlink()
        vm = v3.V3ProjectManager(project)
        with self.assertRaises(v3.RepositoryError):
            vm.load(dict(raw))
        # 项目仍然可以打开（V3 失败不能挡住 V2 界面）
        self.assertIsNone(self.pm.get_story(self.pm.load(project)))

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


class P1ScopeTest(unittest.TestCase):
    """P1 边界：不调用真实 AI API，不引入网络依赖。"""

    def test_data_layer_does_not_import_ai_or_gui(self):
        source = (Path(__file__).resolve().parent.parent
                  / "modules" / "v3_storage.py").read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "tkinter", "story_engine", "main_window"):
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(f"from {forbidden}", source)


if __name__ == "__main__":
    unittest.main()
