# AI Story Studio V3 — P1-Fix-2 补充修复交接报告

- 日期：2026-11-09
- 仓库：`AIHorrorStudio`（本地工作目录 `D:\AImv\AI_Horror_Studio_V2`）
- 分支状态下文的「提交前」指本报告对应代码的提交前状态；「提交后」见第 3 节（如有）
- 运行环境：`C:/Users/yekai.liu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -I`
- 本轮性质：**代码修复 + 测试补充**（不是只读审查）。不调用真实 AI API。

> 事实分级约定（全文适用）：
> **[代码事实]** = 直接阅读代码可确认；**[实验事实]** = 通过实际运行脚本/测试确认；
> **[推断]** = 仅根据调用链推断、未直接运行验证。

---

## 1. 背景与目标

P1-Fix 首次提交 `d4db886` 之后，第二轮只读核验（`docs/reports/V3_P1_FIX_FINAL_AUDIT.md`）确认了四个问题：

| 编号 | 问题 |
| --- | --- |
| R-A2 | `stories/<id>/story.json` 若是「合法 JSON 但结构不可用」（如 `shots` 为字符串），`sync_story` 会把它当作可用故事并静默覆盖；`shots: []` 这类**合法空故事**又可能被误判为损坏 |
| R-C1 | 从 `versions/` 快照恢复后，`versions` / `active_version` 元信息丢失，无法从磁盘重建 |
| R-T1 | `TaskStore.start/finish` 被纳入未来版本只读边界（GPT 已决定：不纳入） |
| R-A3 | V3 恢复失败被 `_v3_load` 静默吞掉，上层拿到的是「正常空 Story」 |

本轮目标：按 GPT 给定规则实现 R-A2、R-C1、R-T1、R-A3 的最小修复，并补充能断言磁盘字节的测试。

---

## 2. 提交前 git 状态

**[实验事实]** 本轮开始时：

```
$ git rev-parse HEAD
d4db886ed6d71ec36f33a122d7b9f7d47fe3c59a
$ git log --oneline -3
d4db886 fix(v3): P1-Fix 数据基础遗留问题 — 版本裁剪计数、数据层只读守卫、Story 损坏安全恢复
741d58d feat(v3): V3 P1 数据基础 — Project 与 Story 固定 1:1，Story 独立持久化
8f007ea docs: finalize AI Story Studio V3 Stage 0.6 architecture baseline
```

工作区未提交修改（均来自上一轮核验与本轮任务，**全部保留**，未丢弃）：

```
 M docs/reports/V3_P1_FIX_HANDOVER.md       ← 上一轮核验修正 + 本轮 R-T1 文字更新
?? docs/reports/V3_P1_FIX_FINAL_AUDIT.md    ← 上一轮核验报告（未跟踪）
?? docs/architecture/Human_in_the_Loop_Workflow_*.md  ← 用户既有文档（未跟踪）
?? docs/code_review/                        ← 用户既有目录（未跟踪）
?? docs/project_knowledge/                  ← 用户既有目录（未跟踪）
?? docs/reports/V3_P1_DATA_CONSISTENCY_AUDIT.md       ← 上一轮既有报告（未跟踪）
```

任务开始时 `modules/` 与 `tests/` **没有**未提交修改；本轮对它们的全部改动都是本任务产生的。未执行 push / reset / clean / rebase / 强制覆盖 / 删除任何未跟踪文件。

---

## 3. 提交后 git 状态

见本报告第 2 节之后执行的唯一一次本地提交（`git log -1` / `git show --stat` 输出与第 17 节一致）。约束遵守情况：

- 未 push；
- 未 reset / clean / rebase / 强制覆盖 / 改写历史；
- 未 amend `d4db886`；
- 未删除任何未跟踪文件；
- 提交只包含本轮相关的 4 个已跟踪文件（见第 4 节），未 `git add -A`。

### HEAD / parent / SHA

| 项目 | 值 |
| --- | --- |
| 修复前 HEAD（parent） | `d4db886ed6d71ec36f33a122d7b9f7d47fe3c59a` |
| 新提交 SHA | 见 `git log -1 --format=%H`（本报告作为文件进入该提交，故不自引用 SHA） |
| 新提交 parent | `d4db886ed6d71ec36f33a122d7b9f7d47fe3c59a` |

---

## 4. 修改文件清单与关键函数

**[实验事实]** `git diff --numstat`（提交前）：

```
7	6	docs/reports/V3_P1_FIX_HANDOVER.md
34	6	modules/project_manager.py
231	48	modules/v3_storage.py
414	5	tests/test_v3_storage.py
```

### `modules/v3_storage.py`

| 函数 / 成员 | 变更 |
| --- | --- |
| `is_structural_story(story)` | **新增**。结构可用性判定：`dict` 且 `shots` 是 `list`。`shots: []` 结构合法。 |
| `V3ProjectManager._usable_project_story` | 改为要求 `is_valid_story` **且** `is_structural_story` |
| `V3ProjectManager.usable_story_file(path)` | **新增**。JSON 坏 → `CorruptDataError`；JSON 合法但结构不可用 → `CorruptDataError`；空骨架合法返回；文件不存在返回 `None` |
| `V3ProjectManager.load` | `story_path` 提前计算；`CorruptDataError` → `_recover_corrupt_story`；**文件缺失分支**改为：project.json 有可用 Story → 返回（写盘时补回）；否则 `_recover_corrupt_story` |
| `_recover_corrupt_story` | 重写分支顺序：① project.json 可用 → 隔离后采纳；② 有可用快照 → 隔离后从快照恢复（无论 project.json 是否坏）；③ project.json 有内容但结构坏且无快照 → 隔离后 **抛 `CorruptDataError`**（人工恢复）；④ 其余（`None` / `shots: []`）→ 隔离后进入 **部分恢复** 并留痕 |
| `_not_recovered(data, reason)` | **新增**。`_not_recovered=True` 标记 + `recovery_status={"state": "partial", ...}`，`sync_story` 据此不写 stories/ |
| `_set_recovery_status(data, state, reason)` | **新增**。恢复状态只挂在内存 data 上，写盘前由 `ProjectManager._save` 弹出 |
| `_version_entry(snapshot, version_id)` | **新增**。由快照文件内容重建版本条目（与 `VersionStore.snapshot` 记录格式一致） |
| `rebuild_version_entries(current_id)` | **新增**。扫描 `versions/*.json`；不可读 / 结构不可用 / 无镜头 → 记入 `unverified`、跳过（不伪造）；可验证的按 `created_at` 升序；悬空 `base_version` 剥离；`active_version` 仅指向可验证版本 |
| `_restore_from_snapshot(data, snapshot)` | **新增**。剥离内部标记/快照自有键后作为 Story；调用 `rebuild_version_entries` 重建元信息；状态 `recovered` / `partial` |
| `_recoverable_version` | 增加 `_recovery_candidate` 内部标记（恢复后据此重建元信息） |
| `sync_story` | 开头处理 `_not_recovered` → 直接返回 `False`（不写 stories/） |
| `TaskStore.start` / `finish` | **移除** `assert_writable`（R-T1 最终决定） |
| `TaskStore.mark_abandoned` | **保留** `assert_writable` |
| `TaskStore` 类 docstring | 改写为最终边界 |

### `modules/project_manager.py`

| 函数 | 变更 |
| --- | --- |
| `__init__` / `open_project` | 新增 `self.recovery_status`（每次打开重置） |
| `_load_file` | 弹出 `recovery_status` / `_not_recovered`（恢复状态只进内存） |
| `migrate` | 把 `data["recovery_status"]` 移交给实例属性 |
| `_save` | `sync_story` 后弹出 `recovery_status` 写入实例属性（不落盘） |
| `_v3_load` | 统一损坏判定（`usable_story_file`）；隔离失败 → `ProjectError` 中止；**`CorruptDataError` 不再吞掉**，转为 `ProjectError` 抛给调用方（R-A3） |
| `_normalize_story` | **`shots` 不是列表时不再 `pop("story")`**——保留结构损坏的原始内容供 V3/人工恢复判定（否则会被误判为「没有故事」） |

### `docs/reports/V3_P1_FIX_HANDOVER.md`

修正与 R-T1 最终决定矛盾的 TaskStore 描述（第 10 节表格、TaskStore 边界段落、R-06、第 16 节第 3 条）。

### `tests/test_v3_storage.py`

新增 26 个测试（3 个类），并修正 1 个断言旧行为的测试（见第 12 节）。

---

## 5. R-A2：JSON 合法性 / 结构可用性 / 业务有效性分离

### 根因

**[代码事实]** 原 `is_valid_story(story)` 只判断 `bool(story.get("shots"))`：

- `{"shots": "not-a-list"}` → 被当成**有效** → `_usable_project_story` 采纳 → `sync_story` 写回 stories/，**唯一原始损坏内容被静默覆盖**（第二轮核验已实验确认）；
- `{"shots": []}` → 被判为无效 → 走「缺主 Story」恢复路径，但空 Story 在既有契约中是合法的。

**[代码事实] 额外发现的第二处同类问题**：`ProjectManager._normalize_story` 在 `shots` 不是列表时执行 `data.pop("story")`，把结构损坏的 project.json 内容直接从内存中删掉。即使 V3 层能判定损坏，也看不到「project.json 有内容但结构坏」这一事实，结果被误判为空项目（详见第 13 节测试证据）。

### 修复

三级判定：

| 级别 | 判定 | 含义 |
| --- | --- | --- |
| JSON 合法 | `read_json` 不抛 `CorruptDataError` | 可解析 |
| 结构可用 | `is_structural_story`：`dict` 且 `shots` 是 `list` | 可作为 Story 容器；`shots: []` **合法** |
| 业务有效 | `is_valid_story`：结构可用且 `shots` 非空 | 有实际内容 |

`usable_story_file` 把「JSON 坏」和「结构不可用」统一成 `CorruptDataError`，保证两种损坏都走「先隔离、后恢复」，绝不会被 `sync_story` 覆盖。

`_recover_corrupt_story` 的恢复顺序（**[代码事实]**）：

1. `project.json.story` 可用（有效且结构可读）→ 隔离损坏文件 → 采纳，状态 `recovered`；
2. `versions/` 有可验证快照 → 隔离损坏文件 → 从快照恢复 + 重建元信息；若 project.json 结构坏，在 `reason` 中记录「未采用（原字节保留）」；
3. project.json 有内容但结构坏且无快照 → 隔离后抛 `CorruptDataError`（人工恢复），**绝不**用空骨架覆盖；
4. 其余（project.json 为 `None` / 空故事）→ 隔离 → 部分恢复状态留痕，`sync_story` 不写 stories/。

### 测试证据（`P1Fix2CorruptJudgeTest`，10 个）

| 测试 | 验证点 |
| --- | --- |
| `test_valid_json_shots_string_is_quarantined_and_recovered` | 合法 JSON + `shots` 字符串 → `.corrupt/` 备份字节 == 原始坏字节；从 project.json 恢复；无内部标记落盘 |
| `test_valid_json_root_not_object_is_corrupt` | `[1,2,3]` → 隔离 + 恢复，备份字节精确比对 |
| `test_shots_missing_is_corrupt` | 缺 `shots` 字段 → 隔离 + 恢复 |
| `test_empty_shots_is_legal_not_corrupt` | `shots: []`：`is_valid_story` False 但 `is_structural_story` True；打开后 **story.json 字节完全不变**、不产生 `.corrupt/` |
| `test_structural_bad_both_sides_but_project_json_recoverable` | 两侧有效 + 文件结构坏 → 从 project.json 恢复（1 镜、scene == "a"） |
| `test_structural_bad_both_sides_recovers_from_history` | 清空两侧 + 历史快照 → 恢复 3 镜、`active_version` 指向真实文件、用户存的版本仍在、`recovered`、内部标记不落盘 |
| `test_structural_bad_no_history_raises_and_keeps_bytes` | 双侧结构坏 + 无快照 → 抛出明确错误；坏文件进 `.corrupt/`（字节精确比对）；其它文件（含 project.json 的坏 story）**字节完全不变** |
| `test_quarantine_failure_aborts_without_any_write` | `copy2` 失败 → `RepositoryError`；全项目文件字节对完全相等（**零写入**） |
| `test_open_get_story_save_reopen_preserves_original_bytes` | open → get_story → save → reopen：V2 视图可用；`.corrupt/` 里原始坏字节仍在；不重复隔离 |
| `test_partial_recovery_is_marked_and_not_written_back` | 新建项目 + 文件损坏 → `recovery_status.state == "partial"`；打开与显式保存后 story.json **仍不存在**（不被重建）；`recovery_status` / `_not_recovered` 不写进 project.json |

另有 `IntegrityTest.test_v3_without_any_story_is_reported`（见第 12 节修正）。

---

## 6. R-C1：版本存储格式分析与元信息重建

### 存储格式分析（**[代码事实]**）

| 对象 | 内容 |
| --- | --- |
| `stories/<story_id>/story.json` | 唯一真源；含 `versions`（条目数组，旧→新）与 `active_version` |
| `versions/<version_id>.json` | 快照：Story 内容 + `version_id` / `created_at` / `note` / `official`；**不含** `versions` / `active_version`（`VersionStore.snapshot` 与 V2 `save_version` 都会 pop 掉）；恢复版本带 `base_version` |
| `story/index.json` | 只存摘要（`story_id` / `title` / `created_at` / `updated_at` / `shot_count` / `has_story`），无版本信息 |
| `version_id` 命名 | `vYYYYMMDD-HHMMSS-<4hex>` |

**结论**：版本条目只存在于 `story["versions"]`；`versions/` 目录里的快照文件是**唯一**可用于重建元信息的权威来源。

### 重建规则

`rebuild_version_entries`：

1. 扫描 `versions/*.json`（跳过点文件），按文件名排序保证确定性；
2. 每个文件 `read_json` + `is_structural_story` + `shots` 非空三关；任一不过 → 记入 `unverified` 并跳过（**不伪造**）；
3. 条目字段全部来自快照内容（`_version_entry`）：`version_id` / `created_at` / `note` / `official` / `title` / `shot_count` / `total_duration` / `score` / `file`，`base_version` 仅在快照中存在时带上；
4. 按 `(created_at, version_id)` 升序（与 `versions` 原始追加顺序一致）；
5. 悬空 `base_version` 剥离；
6. `active_version` 仅当恢复候选可验证时设置，否则为空字符串；
7. 不删除、不改写任何快照文件。

恢复状态：全部可验证 → `recovered`；存在 `unverified` → `partial`，并在 `reason` 中列出不可识别文件名。

### 测试证据（`P1Fix2VersionRebuildTest`，12 个）

| 测试 | 验证点 |
| --- | --- |
| `test_versions_list_contains_every_verifiable_snapshot` | 列表与磁盘 `versions/*.json` **集合完全相等**（不漏、不多） |
| `test_listed_entries_are_rebuilt_from_snapshot_content` | `note` / `created_at` / `title` / `shot_count` / `file` 与快照文件内容一致 |
| `test_active_version_points_to_real_readable_version` | `active_version` 非空、存在于磁盘、出现在列表中、`file` 字段一致 |
| `test_unreadable_snapshot_is_not_fabricated` | JSON 坏的快照不进列表、不被设为 active、出现在 `reason` 中、`state == "partial"`、**原文件字节不变** |
| `test_structural_bad_snapshot_is_not_listed` | `shots` 字符串的快照不进列表，文件保留 |
| `test_missing_shots_snapshot_is_not_listed` | 无 `shots` 的快照不进列表 |
| `test_entries_have_required_fields_and_no_dangling_refs` | 必需字段齐全；`base_version` 不悬空；`note == "基线"` |
| `test_restore_after_recovery_keeps_base_reference` | 恢复后 `restore_version` 新条目带 `base_version`，stories/ 中该条目也带；无内部标记落盘 |
| `test_original_snapshot_files_all_kept` | 恢复前后 `versions/*.json` 每个文件**字节相等**，且集合只增不减 |
| `test_reopen_keeps_rebuilt_list` | 两次打开列表顺序一致；不丢、不重复；`_v3_adopt` 不落盘 |
| `test_save_version_after_recovery_keeps_old_and_new` | 恢复后再存版本：新旧版本都在列表，新快照文件存在 |
| `test_file_missing_path_strips_internal_markers` | 仅文件缺失路径同样走元信息重建；`_v3_adopt` / `_recovery_candidate` / `recovery_status` 不落盘 |

---

## 7. R-T1：TaskStore 边界（最终决定，不再讨论）

| 方法 | `assert_writable` |
| --- | --- |
| `TaskStore.start` | **否** |
| `TaskStore.finish` | **否** |
| `TaskStore.mark_abandoned` | **是** |

**[代码事实]** 已同步修改：`start` / `finish` 移除检查，`mark_abandoned` 保留，类 docstring 改写，`V3_P1_FIX_HANDOVER.md` 的矛盾描述已更正（第 10 节表格、TaskStore 段落、R-06、第 16 节第 3 条）。

### 测试证据（`P1Fix2TaskBoundaryTest`，4 个）

| 测试 | 验证点 |
| --- | --- |
| `test_start_and_finish_allowed_on_future_project` | `schema_version=4` 下 start / finish 成功；`.tasks/` 有记录；**业务文件（project.json / stories/ / versions/ / story/index.json）字节集合完全不变**；磁盘版本仍是 4 |
| `test_mark_abandoned_refused_on_future_project` | 手写 `running` 任务 → `mark_abandoned` 抛 `RepositoryError`，任务文件字节不变 |
| `test_future_version_business_write_still_refused` | 同一未来版本项目 `save` 仍被拒，业务文件字节不变 |
| `test_normal_v3_task_behavior_unchanged` | 普通 V3 项目 start / mark_abandoned / get 行为不变 |

---

## 8. R-A3：恢复失败不得伪装成正常空 Story

### 实现（最小改动，未改 GUI）

1. V3 层在内存 `data["recovery_status"] = {"state": "recovered" | "partial", "reason": ...}`；
2. `ProjectManager._save` 在 `sync_story` 之后 `pop` 到实例属性 `self.recovery_status`；`_load_file` 防御性剔除磁盘上的同名键；
3. 部分恢复时 `sync_story` 直接返回，不重建 stories/；
4. `_v3_load` 对 `CorruptDataError` **不再静默返回 False**，转为 `ProjectError` 抛给调用方；隔离失败也抛 `ProjectError` 中止写入；
5. `_v3_load` 缺失文件分支不再直接走到「抛 RepositoryError → 被吞」，而是进入统一恢复流程，从而产生 `partial` 状态。

### 结果与剩余风险

- **[实验事实]** 测试 `test_partial_recovery_is_marked_and_not_written_back` 断言：`recovery_status.state == "partial"`、打开与保存后 story.json 不被重建、状态不落盘；
- **剩余风险（未解决，属 GUI 层）**：GUI 目前不读取 `ProjectManager.recovery_status`，不会向用户弹窗提示。本轮按要求不重构 GUI；建议后续在 `main_window` 打开项目后读取该属性并展示提示（P2）。
- **剩余风险**：`_v3_load` 现在会把 `CorruptDataError` 转为 `ProjectError`，`open_project` 会失败。这符合「不得伪装为正常空项目」，但 GUI 打开失败时需给出可读提示（同上，P2）。

---

## 9. 新旧测试数量

| 项目 | 修改前 | 修改后 |
| --- | --- | --- |
| `tests/test_v3_storage.py` 测试数 | 49 | **75**（+26） |
| 全量测试总数 | 358 | **384**（+26） |
| 跳过的测试 | 0 | 0 |

新增 3 个测试类：`P1Fix2CorruptJudgeTest`（10）、`P1Fix2VersionRebuildTest`（12）、`P1Fix2TaskBoundaryTest`（4）。

修正的既有测试：`IntegrityTest.test_v3_without_any_story_is_reported`（见第 12 节，**未删除、未跳过**）。

---

## 10. 全量测试结果

**[实验事实]** 清除 `__pycache__` 后：

```
$ python -I -m unittest discover -s tests
................................................................................
Ran 384 tests in 65.095s
OK
```

```
$ python -I -m unittest discover -s tests -p test_v3_storage.py
Ran 75 tests in 17.406s
OK
```

**总计 384，通过 384，失败 0，错误 0，跳过 0。**

---

## 11. GUI smoke 结果

**[实验事实]** `python -I tests/gui_smoke.py`：

```
render ok: ...\output\smoke.mp4 (282024 bytes)
story render ok: ...\output\story.mp4 (62729 bytes)
ai images ok: ['images/ai_s001_r1_f6c2b732.png', 'images/ai_s002_r1_d2c28ba1.png']
ai voices ok: audio/voice_track.wav (durations=[1.5, 1.5])
ai speed ok: 587Hz for 0.75x
ai render ok: ...\GUI Smoke_final.mp4 (366372 bytes, streams=['video', 'audio'])
ai clear voices ok
story flow ok: ['v20261109-151603-3db9', 'v20261109-151603-c8b1', 'v20261109-151602-0015', 'v20261109-151553-e294', 'v20261109-151552-757d']
batch panel ok: [('...A', 'ok'), ('...B', 'ok')]
GUI smoke OK
```

（smoke 使用 mock AI，不调用真实 API。）

---

## 12. 安全与约束检查

- 未 push、未 reset / clean / rebase / 强制覆盖、未改写历史、未 amend；
- 未删除任何未跟踪文件；
- 提交只包含 4 个已跟踪文件；
- 未调用真实 AI API；数据层未新增网络/GUI 依赖（`P1ScopeTest` 通过）；
- **修正的旧测试说明**：`IntegrityTest.test_v3_without_any_story_is_reported` 原先断言「空骨架 + 无中心故事 + 无快照 → `RepositoryError`」，这是被 R-A2/R-A3 取代的旧行为。现改为断言新行为：返回 `partial` 状态、`story` 仍为 `None`、不重建骨架文件。该测试**未被删除或跳过**，断言更严格（磁盘状态 + 状态字段）。

---

## 13. 未解决 / 已知残留

| 编号 | 内容 | 级别 |
| --- | --- | --- |
| N-1 | GUI 不读取 `recovery_status`，部分恢复 / 打开失败无用户提示（R-A3 的 GUI 部分，本轮按要求不动 GUI） | P2 |
| N-2 | `.corrupt/` 无自动清理 / 限额（沿用 P1-Fix R-01） | P2 |
| N-3 | `Attribution` 为模块级类变量，非线程安全（沿用 R-04） | P2 |
| N-4 | 版本快照 `official` 缺失时重建为 `True`（与 `VersionStore.snapshot` 默认一致；旧快照通常都带该字段） | 低 |
| N-5 | `_recoverable_version` 无版本记录时按**文件名倒序**挑候选，而重建列表按 `created_at` 排序；两者可能选到不同快照作为「当前内容」 | 低（功能正确：两者都可验证） |
| N-6 | 部分恢复（`partial`）后若用户显式调用 `set_story`，会正常重建 story.json（属于用户显式写入，符合预期，未特殊拦截） | 记录 |

---

## 14. P1 闭环建议

- R-A2、R-C1、R-T1、R-A3（数据层部分）**已按 GPT 规则实现并有磁盘级测试证据**；
- 建议 P1-01 / P1-02 / P1-03 本轮复核后可判定**通过**；
- 建议 N-1（GUI 恢复提示）作为 P2 首个任务，与 GUI 自动化一起设计。

---

## 15. 建议 GPT 重点审查

1. `_recover_corrupt_story` 分支顺序：快照优先于「project.json 结构坏 → 人工恢复」是否符合 R-A2 第 5 条（「如果 project.json.story 有效 → 恢复；两侧不可用 → 历史版本恢复」）。
2. `_normalize_story` 不再 `pop` 结构坏的 story：是否有其它调用方依赖「结构坏即删除」的旧语义。
3. `_v3_load` 将 `CorruptDataError` 转 `ProjectError` 上抛：是否与「V3 失败不得挡住 V2」的既有约束冲突（当前只在双侧均不可恢复时触发）。
4. `rebuild_version_entries` 对 `official` 缺失默认 `True`。
5. 部分恢复状态下 `sync_story` 直接返回：是否需要在后续正常保存时自动退出该状态（当前设计为「用户在 .corrupt/ 手工处理后重开」）。
6. `test_structural_bad_no_history_raises_and_keeps_bytes` 断言错误文案「结构无效」「未被覆盖」——文案变动会破坏测试，是否接受。

---

## 16. 下一步建议

- 等待 GPT 对 `docs/reports/V3_P1_FIX2_HANDOVER.md` 与实际 diff 审查验收；
- 本轮**不启动 P2**。
