# AI Story Studio V3 — P1-Fix-3-R1 交接报告

- 日期：2026-11-09
- 仓库：AIHorrorStudio（本地工作目录 `D:\AImv\AI_Horror_Studio_V2`）
- 任务：P1-Fix-3-R1（修复写盘副作用顺序与隔离失败清理）
- 本轮性质：代码修复 + 测试补充；不推送、不启动 P2。

> 事实分级：[代码事实] = 阅读代码可确认；[实验事实] = 实际运行确认；[推断] = 未直接验证。

---

## 1. 任务基线

| 项 | 值 | 验证方式 |
| --- | --- | --- |
| 分支 | `main` | `git rev-parse --abbrev-ref HEAD` |
| 原始 HEAD | `29422dd7126685129ba834a76180869e35f18b19` | `git rev-parse HEAD` |
| 原始 HEAD 的 parent | `5f94261a79688cade26cd63a9c63aa5c4d2401ab` | `git log --oneline` |
| 最终 HEAD | 见第 10 节 | `git log -1` |

## 2. Git 工作区状态

开始时有一处未提交修改：`docs/reports/V3_P1_FIX3_HANDOVER.md`（上一轮交付后我手动把提交
SHA 补写进第 12 节，仅 1 行，与本任务不冲突，未丢弃，原样保留在本次提交中）。

未跟踪文件（全部原样保留，未删除、未修改）：

```
?? docs/architecture/Human_in_the_Loop_Workflow_{Decisions,Design,Risks}.md
?? docs/code_review/
?? docs/project_knowledge/
?? docs/reports/V3_P1_DATA_CONSISTENCY_AUDIT.md
?? docs/reports/V3_P1_FIX_FINAL_AUDIT.md
```

未执行 reset / clean / rebase / amend；未 push；未使用 `git add -A`。

## 3. 修改文件清单

| 文件 | 变更 | 说明 |
| --- | --- | --- |
| `modules/project_manager.py` | +26 / −5 | R1-01（`open_project` 不再无条件 mkdir `versions/`，仅在确定写升级快照的分支创建）、R1-02（`save_version` 闸门先于 makedirs） |
| `modules/v3_storage.py` | +19 / −6 | R1-03（`_quarantine_corrupt` 失败时回收本次 target） |
| `tests/test_v3_storage.py` | +186 / −0 | 新增 `P1Fix3R1WriteOrderTest`（11 项） |
| `docs/reports/V3_P1_FIX3_R1_HANDOVER.md` | 新增 | 本报告 |
| `docs/reports/V3_P1_FIX3_HANDOVER.md` | ±1 行 | 上一轮遗留的 SHA 补写（非本轮代码改动） |

## 4. 四个修复问题的解决方式

### R1-01：`open_project()` 的目录副作用

[代码事实] 原代码在检查 `project.json` 之后无条件执行
`(project / VERSIONS_DIR).mkdir(parents=True, exist_ok=True)`。因此双侧损坏、无恢复源的
**失败打开**会新增一个空 `versions/` 目录（文件字节不变，但目录结构改变）。

修复：删除该无条件 mkdir。`versions/` 只在 `_open_project` 中「存在 `_version_snapshot_due`
且确有 story、本次打开确定要写升级快照」的分支里创建（无论该分支随后成功与否，这次打开都是
一次**成功**的打开）。其余打开路径不创建任何目录：

- 失败打开（无恢复源）：零写入、零目录变化；
- 正常 V3 打开、无需写盘：不新增 `versions/`（该目录在项目创建时就存在；测试中手工删掉后
  打开不会被重建）；
- V2 → V3 对账写盘：由 `save` → `sync_story` 写 stories/ 与 project.json（不依赖 versions/）；
- V2 结构升级：在升级快照分支创建（原有语义）。

`save_version` 本身在目录不存在时会创建（R1-02 之后位于闸门之后），因此「需要写快照」的
路径不会因为目录缺失而失败。

### R1-02：`save_version()` 的写盘顺序

[代码事实] 原顺序：`assert_writable` → `root.mkdir()` → `_guard_pending_quarantine()` →
写快照。闸门失败时已留下空 `versions/`。

修复后的顺序：`assert_writable`（原有）→ `_guard_pending_quarantine`（隔离，失败即抛
`ProjectError` 中止）→ 目录不存在才 `mkdir`（记录 `created_dir`）→ 生成版本号 / 写快照 →
`~.json.tmp` → 原子 `replace`。异常路径：仅当本次创建了目录且快照**未写成功**时才尽力
`rmdir` 空目录；闸门失败时根本不会创建目录。版本元数据、`_prune_versions` 引用保护、
`self.save(project, data)` 的调用位置与内容均未变。

### R1-03：`_quarantine_corrupt()` 的失败清理

[代码事实] 原顺序：copy2 → staging.replace(target) → `path.unlink()`。若最后一步失败，
正式 `.bak` 已生成，原文件仍在——两者同时存在，且函数只清理 staging。更严重的是它随后
会尝试 `root.rmdir()`；如果 `.corrupt/` 里只有本次的 `.bak`，`rmdir` 成功时 **本次备份被删除**
（该副作用仅与 cleanup 自身相关，原文件仍在）。

修复：显式跟踪 `staging` 与 `target`，任何 `OSError` 都逐一回收**本次创建**的文件：

| 失败点 | 回收 | 原文件 | 历史备份 |
| --- | --- | --- | --- |
| copy2 | 删 staging（target 未生成） | 完整 | 不动 |
| staging.replace | 删 staging | 完整 | 不动 |
| path.unlink | 删本次 target + staging | 完整 | 不动 |

- 只有全流程成功才返回 target；任一失败返回 `None`。
- `.corrupt/` 只有在「本次创建」时才尝试 `rmdir`，且发生在本次文件已回收之后；既有
  `.corrupt/`（`created_dir=False`）永不被删除。
- 清理本身失败时不做任何伪装：返回值仍是 `None`（闸门据此中止写入并报错），残留文件在
  `.corrupt/` 中如实可见。文件系统无法回滚的情况不会被报告为成功。

### R1-04：新增测试（见第 5 节）

## 5. 新增测试清单（`P1Fix3R1WriteOrderTest`，11 项）

| 对应 | 测试 | 断言要点 |
| --- | --- | --- |
| 测试 A | `test_open_failure_does_not_create_versions` | 失败打开；`versions/` 不存在；`_snapshot_tree` 文件 + 目录集合完全一致 |
| 测试 A | `test_open_failure_repeatedly_never_creates_versions` | 连续两次失败打开均零变化；无 `.corrupt/` |
| A 回归 | `test_normal_open_keeps_versions_directory` | 正常打开不新增目录；需要写盘时由写盘前创建 |
| 测试 B | `test_save_version_gate_failure_does_not_create_versions` | 闸门失败（copy2 失败）→ `ProjectError`；`versions/` 不存在；整目录零变化；原文件字节不变 |
| B 回归 | `test_save_version_normal_still_creates_versions` | 正常存版本仍会创建 versions/ 并写入快照 |
| 测试 C | `test_staging_replace_failure_leaves_no_files` | replace 失败：原文件完整；无 `.corrupt/`（无 staging）；整目录零变化 |
| 测试 C | `test_staging_replace_failure_keeps_history_backups` | replace 失败时既有 `.corrupt/` 与历史 `.bak` 字节不变 |
| 测试 D | `test_unlink_failure_removes_new_backup_and_keeps_original` | unlink 失败：原文件完整；本次 target / staging 已清理；返回 `None` |
| 测试 D | `test_unlink_failure_keeps_history_backups` | unlink 失败时历史 `.bak` 字节不变 |
| 测试 E | `test_failure_cleanup_preserves_existing_corrupt_dir` | copy2 失败 + 既有 `.corrupt/`：整目录（含目录集合）字节不变 |
| 成功路径 | `test_success_backs_up_original_bytes` | 隔离成功：原文件移出原位；备份字节完整；无 staging 残留 |

说明：测试 B 按照与应用一致的调用方式构造——`_v3_context` 内一次 V3 判定（`migrate`）产生
待隔离标记，再直接调用 `save_version`。独立的 `load → migrate`（不在 V3 上下文中）不会被
V3 层判定、不会产生标记，这是 P1-Fix-3 的既有设计，本轮未改动。

未修改任何原有测试或弱化数据保护断言。

## 6. 完整测试结果

[实验事实]

```
$ python -I -m unittest discover -s tests -p test_v3_storage.py
Ran 100 tests in 22.671s
OK
```

（上一轮 89 项 + 新增 11 项 = 100 项；P1-Fix-3 的 14 项与 P1-Fix-2 的 R-A2/R-C1/R-T1/R-A3
测试全部保持通过。）

```
$ python -I -m unittest discover -s tests
Ran 409 tests in 63.907s
OK
```

（上一轮 398 项 + 新增 11 项 = 409 项。）跳过：0。

## 7. GUI smoke 结果

[实验事实] `python -I tests/gui_smoke.py`：

| 运行 | 退出码 | 末行 |
| --- | --- | --- |
| 1 | 0 | `GUI smoke OK` |
| 2 | 0 | `GUI smoke OK` |
| 3 | 0 | `GUI smoke OK` |

3/3 通过。上一轮观察到的偶发 Tk 竞态本轮未复现（属于已知既有问题，见第 9 节）。

## 8. 数据保护验证结果

| 要求 | 结果 | 依据 |
| --- | --- | --- |
| 无恢复源打开失败：项目目录零变化 | 通过 | 测试 A（文件字节 + 目录集合） |
| 闸门失败：业务写入零变化 | 通过 | 测试 B、P1-Fix-3 `test_rule3_quarantine_failure_writes_no_business_file` |
| 隔离失败：原文件完整 | 通过 | 测试 C / D / E、`test_quarantine_failure_does_not_touch_original` |
| 隔离成功：原始数据有完整备份 | 通过 | `test_success_backs_up_original_bytes`、`test_rule2_*` |
| 重复打开：不会重复隔离 | 通过 | `test_rule1_repeated_open_is_stable`、`test_marker_consumed_after_recovery_other_project_untouched` |
| R-A2 / R-C1 / R-T1 不回退 | 通过 | 相关既有测试全绿 |

## 9. 未解决问题及风险

1. **清理自身失败时的残留**：文件被外部占用等情况可能导致本次临时文件 / 备份无法删除。
   此时函数返回 `None`（写入中止），残留如实留在 `.corrupt/` 中，报告与测试不把它当作
   零残留。Windows 下「文件被占用」是现实可能。
2. **`versions/` 已存在但不为空**：`save_version` 失败时的 `rmdir` 只在本函数创建目录时
   执行，不会影响既有内容。
3. **GUI smoke 偶发 Tk 竞态**（上一轮观察到 1/5）：本轮未复现，未修改 `gui_smoke.py` 或
   `story_panel.py`（超出本任务范围）。
4. **独立 `save_version` 调用不经过 V3 判定**：无待隔离标记时闸门不生效——既有设计，
   本轮未改动。

## 10. 本地 commit SHA

见提交消息（提交后以 `git log -1 --format=%H` 为准）。

## 11. 是否推送

**没有 push。** 没有 reset / clean / rebase / amend，没有 `git add -A`。

## 12. 后续建议

- 在 `gui_smoke.py` 关闭窗口前取消 `after` 回调，或在面板刷新中加 `winfo_exists()` 守卫，
  消除 Tk 竞态。
- 可考虑让 `_quarantine_corrupt` 在清理失败时向上层返回具体原因（当前仅能通过 `.corrupt/`
  中的残留判断），供 GUI 提示用户手工处理。
