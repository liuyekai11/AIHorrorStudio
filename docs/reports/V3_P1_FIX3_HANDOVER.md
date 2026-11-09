# AI Story Studio V3 — P1-Fix-3 交接报告（ISSUE-1：预隔离零写入）

- 日期：2026-11-09
- 仓库：`AIHorrorStudio`（本地工作目录 `D:\AImv\AI_Horror_Studio_V2`）
- 基线提交：`5f94261a79688cade26cd63a9c63aa5c4d2401ab`（P1-Fix-2）
- 本轮性质：**代码修复 + 测试补充**；不调用真实 AI API；不启动 P2。
- 运行环境：Windows 11 + `python -I`（`C:\Users\yekai.liu\AppData\Local\Python\pythoncore-3.12-64`）

> 事实分级约定（全文适用）：
> **[代码事实]** = 直接阅读代码可确认；**[实验事实]** = 通过实际运行脚本/测试确认；
> **[推断]** = 仅根据调用链推断、未直接运行验证。

---

## 1. 根因

P1-Fix-2 的最终审查（`docs/reports/V3_P1_FIX_FINAL_AUDIT.md`）指出 ISSUE-1：

**[代码事实]** `ProjectManager._v3_load` 在写盘路径上发现 `stories/<id>/story.json`
损坏时，**立即**调用 `V3ProjectManager._quarantine_corrupt`：
- 把损坏文件 `copy2` 到 `.corrupt/`，然后 `unlink` 原文件；
- 若备份失败直接抛错。

而 `_v3_load` 在**打开项目时也会执行**（`open_project → _migrate_with_v3 → migrate → _v3_load`）。
因此在「双侧损坏且没有任何恢复源」（`stories/` 坏 + `project.json.story` 结构坏 +
`versions/` 无可用快照）的情况下：

1. 打开操作**先物理隔离**了唯一的原始损坏文件（或者制造了 `.corrupt/` 目录）；
2. `_recover_corrupt_story` 随后才判定「无法恢复」并抛 `CorruptDataError`；
3. 结果：一次**失败的打开**已经改变了项目字节——违反「打开失败必须对项目零影响」，
   也违反「不创建 .corrupt/ 备份、不删除任何文件」。

此外 `_recover_corrupt_story` 的三个分支（project.json 采纳 / 快照恢复 / 部分恢复）
都各自调用 `quarantine()`，隔离发生在**恢复源确认之后但写盘之前**，与
「先确认恢复源可用 → 再隔离 → 隔离成功后才允许恢复写入」（规则 2）的顺序不一致，
且隔离的成功与写盘的成功之间没有任何约束（隔离成功但写盘失败时缺少明确语义）。

---

## 2. 修复方案（方案 A：隔离推迟到写盘闸门）

**[代码事实]** 核心原则：**判定与副作用分离**。`_v3_load` / `_recover_corrupt_story`
只做只读判定并写内存标记；真正的物理隔离只发生在「已确认恢复源、且即将写盘」的
唯一通道 `ProjectManager._guard_pending_quarantine`。

### 2.1 标记的产生 / 传递 / 消费 / 清除

| 阶段 | 位置 | 行为 |
| --- | --- | --- |
| 产生 | `ProjectManager._v3_load` | 发现 `stories/` 文件损坏（JSON 坏 / 结构不可用 / 结构版本不符）→ `self._pending_quarantine = (project, story_path)`，`self._pending_authoritative = True`；**不做任何物理操作**。同项目只记一次。 |
| 传递 | `migrate` | `had_not_recovered = bool(data.pop("_not_recovered", False))` 先剥掉上一次 migrate 留下的陈旧结论；`_v3_load` 之后若本次判定出 `_not_recovered`，保留在 data 中交给写盘闸门。`_v3_load` 不再 `data.pop("_v3_adopt")`（交给闸门判定）。 |
| 消费 | `_save` / `save_version` | 在 `sync_story` / 生成任何版本文件**之前**调用 `_guard_pending_quarantine(project, data)`。 |
| 清除 | `_save`（`finally`）、`save_version`（`finally`）、隔离成功时立即清除、`_v3_restore` 最外层 | 任何路径结束时标记都不残留；隔离成功后立刻清标记（同一实例随后为其他项目写盘绝不会误隔离）。 |

所有标记都只存在于 `ProjectManager` 实例内存中，**绝不进入 data / project.json**（测试 11 断言）。

### 2.2 闸门的判定顺序

```
_not_recovered in data            → CorruptDataError（规则 1：零写入）
无待隔离标记 / 其他项目 / 文件已不存在 → return（不重复隔离）
data["_v3_adopt"] 结构可用        → 恢复源 = 内存中已采纳的故事
本次流程 V3 已看过 project.json（_pending_authoritative）且没有 _v3_adopt
                                  → 恢复源 = None（规则 1：零写入）
磁盘 project.json.story 可用      → 恢复源 = project.json
否则                              → CorruptDataError（规则 1：零写入）
隔离失败（_quarantine_corrupt 返回 None） → ProjectError（规则 3：中止、零业务写入）
隔离成功                          → self._quarantine_source 记录来源；清除标记
```

### 2.3 隔离本身零残留（`_quarantine_corrupt`）

**[代码事实]** 重写为：先在 `.corrupt/` 写随机临时名（`copy2`）→ `replace` 成正式
备份名 → 最后 `unlink` 原文件。任一环节抛 `OSError`：删除临时文件；若 `.corrupt/`
是本次创建的则 `rmdir`；返回 `None`。因此隔离失败时项目目录（含空目录）字节零变化。

### 2.4 恢复写入失败时不丢原始数据

规则 2 的顺序（先隔离、成功后写盘）保证：写盘失败时原始损坏字节已完成 `copy2 +
rename` 到 `.corrupt/`，且备份是独立文件、写盘使用 tmp+replace 原子替换，不会连带
损坏备份。**剩余窗口**（见第 9 节）：隔离成功后进程崩溃、写盘尚未完成时，`stories/`
文件暂时缺失——`load` 会走「stories/ 缺失 → project.json 可用 → 从 project.json 恢复」，
`.corrupt/` 备份仍在，可手工回填。该窗口在方案 A 下不可避免（先删原文件才能写恢复结果），
但备份始终先落盘。

### 2.5 非打开路径的兼容

- `save` 吞掉 `CorruptDataError`（显式保存无恢复源时静默零写入，GUI 不崩）；
  `_save` 在抛错前把 `recovery_status` 交给 `self.recovery_status`（R-A3 不回退）。
- `save_version` 同样经过闸门；隔离失败 → `ProjectError`，版本文件零生成。
- `clear_story` / `restore_version` / `add_images` 走的都是 `load → migrate → save`
  或 `save_version`，行为不变（测试 9）。
- 未来版本（`schema_version > 3`）：`_v3_load` 早退、`_save` 早退，行为不变（测试 10）。

---

## 3. 修改文件清单

| 文件 | 变更 |
| --- | --- |
| `modules/project_manager.py` | +154 / −25：新增 `_pending_quarantine` / `_pending_authoritative` / `_quarantine_source` 与 `_guard_pending_quarantine` / `_release_pending_quarantine`；`_v3_load` 改为只读标记；`_save`、`save_version` 接入闸门；`save` 处理 `CorruptDataError`；`migrate` 剥陈旧 `_not_recovered` |
| `modules/v3_storage.py` | +56 / −38：`_recover_corrupt_story` 移除全部 `quarantine()` 调用（纯只读判定）；`_quarantine_corrupt` 零残留重写；相关原因文本 / docstring 同步 |
| `tests/test_v3_storage.py` | +301 / −30：新增 `P1Fix3QuarantineGateTest`（14 项）；调整 P1-Fix-2 的损坏判定测试以匹配「打开阶段零写入」；新增 `_snapshot_tree` 整目录字节集合辅助 |
| `docs/reports/V3_P1_FIX3_HANDOVER.md` | 本报告（新增） |

---

## 4. 关键函数修改说明

### `ProjectManager._v3_load`（modules/project_manager.py）
- 删除物理隔离块；改为「只读判定 + 留标记」。损坏判定逻辑（`usable_story_file` +
  `schema_version` 比对）原样保留（R-A2 不回退）。
- 不再 `data.pop("_v3_adopt")`：`_v3_adopt` 是恢复源证据，交给闸门。

### `ProjectManager._guard_pending_quarantine`（新增）
- 见 2.2；在所有业务写入之前执行；隔离失败抛 `ProjectError`（GUI 友好，测试同时接受
  `RepositoryError`/`OSError`）。

### `ProjectManager._save`
- 闸门在 `sync_story` 之前；`CorruptDataError` 分支交出 `recovery_status` 后重抛；
  `finally` 清除标记。删除上一版遗留的「部分恢复时回写 project.json」死代码
  （闸门会先拒绝，该分支不可达）。

### `ProjectManager.save_version`
- 闸门在版本号生成 / 快照写入之前；`try/finally` 清标记。

### `ProjectManager.migrate`
- `had_not_recovered`：先剥离上次的 `_not_recovered`，避免陈旧结论跨调用传播；
  本次 `_v3_load` 重新判定后 `changed` 会包含 `had_not_recovered`。

### `V3ProjectManager._recover_corrupt_story`（modules/v3_storage.py）
- 移除 4 处 `quarantine()`；`project_bad` 无快照分支的错误文本改为
  「未对任何文件做修改（原始数据保持原位）」。

### `V3ProjectManager._quarantine_corrupt`
- 零残留重写（见 2.3）。

---

## 5. 四条规则对照

| 规则 | 实现 | 对应测试 |
| --- | --- | --- |
| 1 双侧损坏、无快照 → `ProjectError`；原始文件原位；不建 `.corrupt/`；不删文件；不改 project.json；不建空骨架；全项目字节零变化 | `_recover_corrupt_story` 只读抛错；`_v3_load` 只在内存留标记；最外层 `_v3_restore` 释放标记 | `test_rule1_both_broken_no_snapshot_raises_and_zero_bytes`、`test_rule1_repeated_open_is_stable` |
| 2 先确认恢复源 → 再隔离 → 隔离成功后才写盘 | `_guard_pending_quarantine` 判定源 → `_quarantine_corrupt` → 之后才 `sync_story` / 写版本文件 | `test_rule2_with_snapshot_recovers_and_quarantines`、`test_rule2_project_json_preferred_and_content_kept`、`test_rule2_versions_and_active_version_after_recovery` |
| 3 隔离失败 → 立即中止、零业务写入、原始数据完整 | `_quarantine_corrupt` 零残留；闸门抛 `ProjectError`，调用方在写盘前中止 | `test_rule3_quarantine_failure_writes_no_business_file`、P1-Fix-2 `test_quarantine_failure_does_not_touch_original` |
| 4 正常 V3 / V2 迁移 / 未来版本 / R-A2、R-C1、R-T1、R-A3 不回退 | 仅在有损坏标记时改变行为 | `test_rule4_*`（5 项）、测试 11、12、P1-Fix-2 全部既有测试 |

---

## 6. 新增测试（P1Fix3QuarantineGateTest，共 14 项）

| # | 测试 | 覆盖要求 |
| --- | --- | --- |
| 1 | `test_rule1_both_broken_no_snapshot_raises_and_zero_bytes` | 要求 1 |
| 2 | `test_rule1_repeated_open_is_stable` | 要求 2 |
| 3 | `test_rule2_with_snapshot_recovers_and_quarantines` | 要求 3 |
| 3b | `test_marker_consumed_after_recovery_other_project_untouched` | 要求 4/5（跨项目绝不误隔离） |
| 4 | `test_rule2_project_json_preferred_and_content_kept` | 要求 4（project.json 优先） |
| 5 | `test_rule3_quarantine_failure_writes_no_business_file` | 要求 5 |
| 6 | `test_rule4_v2_project_migration_unchanged` | 要求 6 |
| 7 | `test_rule4_normal_v3_open_save_reopen` | 要求 7 |
| 8 | `test_rule4_partial_protection_not_regressed` | 要求 8 |
| 9 | `test_rule4_non_open_paths_unaffected` | 要求 9 |
| 9b | `test_rule4_non_open_paths_keep_project_consistent` | 要求 9 |
| 10 | `test_rule4_future_version_boundary_unchanged` | 要求 10 |
| 11 | `test_rule1_internal_markers_never_written` | 要求 11 |
| 12 | `test_rule2_versions_and_active_version_after_recovery` | 要求 12 |

所有零写入断言均使用 `_snapshot_tree(project)`：整个项目目录的「相对路径 → 文件字节」
集合 + 目录集合（含空目录）。

---

## 7. 测试结果

**[实验事实]**

```
$ python -I -m unittest discover -s tests -p test_v3_storage.py
Ran 89 tests in 31.397s
OK
```

（P1-Fix-2 基线 75 项 + 新增 14 项 = 89 项；无回退。）

```
$ python -I -m unittest discover -s tests
Ran 398 tests in 99.938s
OK
```

（基线 384 项 + 新增 14 项 = 398 项；无回退。）

对 P1-Fix-2 既有测试的调整：
- `test_both_sides_broken_is_reported_and_bytes_kept`：V3 层打开失败时断言整目录零变化、无 `.corrupt/`。
- `test_structural_bad_no_history_raises_and_keeps_bytes`：断言错误文本「结构无效 / 保持原位」与整目录零变化。
- `test_quarantine_failure_does_not_touch_original`：改为走 GUI 打开流程（闸门处隔离失败 → 零写入）。
- `test_quarantine_failure_aborts_without_any_write`：V3 层现在是只读判定，断言仅内存采纳。
- `test_partial_recovery_is_marked_and_not_written_back`：断言打开流程零写入、原始字节原位、无 `.corrupt/`；
  独立于打开流程的 `save` 只断言损坏文件不被触碰。

---

## 8. GUI smoke

**[实验事实]** `python -I tests/gui_smoke.py`：

| 运行 | 结果 |
| --- | --- |
| 第 1 次 | `GUI smoke OK`，exit=0 |
| 第 2 次 | `GUI smoke OK`，exit=0 |
| 第 3 次 | `GUI smoke OK`，exit=0 |
| 第 4 次 | `GUI smoke OK`，exit=0 |
| 第 5 次（连续第 2 次采样的首轮） | exit=1：`story_panel._refresh_result` → `treeview get_children` 的 `TclError: invalid command name ...`（Tk 控件已销毁时轮询队列仍触发） |

即 5 次中 4 次通过、1 次失败。该失败点位于 [story_panel.py:659-662](../../modules/story_panel.py#L659-L662)
的 `set_story → _refresh_result`，与 P1-Fix-3 触及的 `project_manager` / `v3_storage`
数据层无调用关系；其前导日志是已销毁控件上的 `_poll_queue` after 回调。判定为 GUI 冒烟脚本
的既有竞态（Tk 事件队列），**不是本轮引入**，但本轮只观察到 1/5，未做基线对照（见第 9 节）。

---

## 9. 未解决 / 已知残留

1. **GUI smoke 偶发竞态**：见第 8 节。建议后续在 `gui_smoke.py` 中于 `mainloop` 结束前
   取消 after 回调，或给 `story_panel._refresh_result` 加 `winfo_exists()` 守卫。
   本轮不修改（超出 P1-Fix-3 范围）。
2. **规则 2 的崩溃窗口**：隔离成功、写盘未完成时进程崩溃 → `stories/` 暂时缺失；
   数据在 `.corrupt/` 备份中（见 2.4）。方案 A 下不可避免。
3. **独立于打开流程的 `save` 不持有恢复判定**：打开完成后标记已释放；随后
   `load → migrate → save` 若 `story` 为 `None`，`sync_story` 直接空转，不会触碰损坏的
   `stories/` 文件，但 project.json 的非 story 字段可能被 reflow 更新。打开流程本身的
   零写入由测试 1/2/8 覆盖。
4. `_quarantine_source` 目前只作为可观测信息记录，尚无上层消费者。

---

## 10. 与 P1-Fix-2 的兼容性

- R-A2（损坏判定统一）：`usable_story_file` / `_usable_project_story` 未改，判定结论不变。
- R-C1（版本元信息重建）：`_restore_from_snapshot` / `rebuild_version_entries` 未改；
  仅恢复原因文本更新。
- R-T1（TaskStore 边界）：未触及。
- R-A3（恢复状态上报）：`recovery_status` 仍在打开后暴露；`_save` 拒绝时也会回交。
- 磁盘格式：无新字段写入；内部标记全部在落盘前清除（测试 11）。

---

## 11. 建议 GPT 重点审查

1. `_guard_pending_quarantine` 的「`_pending_authoritative` 且无 `_v3_adopt` → 无恢复源」
   判定是否覆盖所有调用路径（尤其 `save_version` 直接调用、未经 migrate 的场景）。
2. 规则 2 的「先隔离后写盘」顺序与 2.4 的崩溃窗口是否可接受。
3. P1-Fix-2 中 5 项测试断言的调整是否合理（特别是 partial 恢复的独立 save）。
4. GUI smoke 竞态是否确认与本轮无关（建议审查者在基线上对照 1–2 次）。

---

## 12. Git

- 唯一一次本地提交，父提交 `5f94261a79688cade26cd63a9c63aa5c4d2401ab`。
- 只提交 `modules/project_manager.py`、`modules/v3_storage.py`、`tests/test_v3_storage.py`
  与本报告；未 push / reset / clean / rebase / amend；未使用 `git add -A`；
  所有既有未跟踪文件原样保留。
- 提交 SHA：`29422dd7126685129ba834a76180869e35f18b19`（parent `5f94261a79688cade26cd63a9c63aa5c4d2401ab`）。
