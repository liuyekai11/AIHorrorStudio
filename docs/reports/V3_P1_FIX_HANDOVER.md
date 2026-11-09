# AI Story Studio V3 — P1-Fix 数据基础遗留问题修复 · 交接报告

- 报告日期：2026-11-09
- 范围：P1 数据一致性审查（`docs/reports/V3_P1_DATA_CONSISTENCY_AUDIT.md`）确认的 P1-01 / P1-02 / P1-03
- 状态：**修复完成，全部测试通过，已创建本地 commit，未 push。等待 GPT 审查验收。P2 未启动。**

---

## 1. 背景与基线

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/liuyekai11/AIHorrorStudio |
| 本地目录 | `D:\AImv\AI_Horror_Studio_V2` |
| 修复前分支 | `main` |
| 修复前 HEAD | `741d58d54883b15eb4e7fca08f32106cad332e8d`（`feat(v3): V3 P1 数据基础 — Project 与 Story 固定 1:1，Story 独立持久化`） |
| 修复前与 origin/main | 0 / 0（本地与远端一致） |
| 修复前工作区 | 无已跟踪文件改动（`git status --porcelain` 只有未跟踪文档目录） |
| Python | `C:/Users/yekai.liu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` |
| 测试命令 | 清 `__pycache__` 后 `python -m unittest discover -s tests` |
| GUI 冒烟 | `python tests/gui_smoke.py` |

预检发现 HEAD 与预期一致、无未提交代码改动 → 按要求继续执行。未跟踪文件全部原样保留（见第 13 节）。

## 2. 原审查结论回顾

`V3_P1_DATA_CONSISTENCY_AUDIT.md`（针对 741d58d）：

- **无 P0**。
- **P1-01（已确认）**：`_prune_versions` 用「全部版本条数」对比 10 条上限，却只删正式版本 → 非正式版本把正式版本挤出保留上限，导致过**早**删除正式版本（已复现）。
- **P1-02（已确认）**：`StoryRepository.create/update/archive`、`VersionStore.snapshot/restore`、`_write_v3_story` 绕过未来版本只读保护；只读检查只存在于 GUI/`ProjectManager.save` 一层。
- **P1-03（风险）**：`stories/story/story.json` 与 `project.json.story` 同时无效时，代码会静默创建空骨架 Story，违反 Stage 0.6「保留原始字节、不创建空 Story」的设计。
- 另有 P2-01..P2-09、P3-01..P3-05（本轮未处理，见第 12 节）。
- 结论：有条件通过，需修 P1。

## 3. 本次修复目标

1. P1-01：正式版本独立计数；非正式版本不占名额、不被裁剪；活动版本、被引用版本永不删除；先删文件后删元信息；保持 V2.2 接口语义不变。
2. P1-02：数据层统一版本检查（不只在 GUI/`ProjectManager.save`）；任何业务数据写入前检查**磁盘真实** `schema_version`；`> 3` 一律拒写；`save_version` 在创建快照文件**之前**检查；`restore_version` 在修改 Story **之前**检查；内存 `schema_version=2` 不能绕过；不静默降级。TaskStore 边界明确且代码/文档一致。
3. P1-03：双侧 Story 损坏安全策略（见第 8 节），损坏文件原始字节必须保留，绝不静默替换为空 Story。
4. 新增回归测试，原测试一条不改语义、不删不弱化。

## 4. 修复后 Git 状态（执行时）

- 分支：`main`（未新建分支，非交互式环境；按要求只做本地 commit）
- 修复前 HEAD：`741d58d`；修复后 HEAD：**本地新增 1 个 commit**（哈希见第 14 节）
- 已修改文件：`modules/project_manager.py`、`modules/v3_storage.py`、`tests/test_v3_storage.py`、新增 `docs/reports/V3_P1_FIX_HANDOVER.md`
- **未 push、未 reset、未 clean、未改写历史**。
- 未跟踪文件：`docs/architecture/Human_in_the_Loop_Workflow_*.md`、`docs/code_review/`、`docs/project_knowledge/`、`docs/reports/`（其中 `V3_P1_FIX_HANDOVER.md` 为本轮新增）——全部未被覆盖或删除。

## 5. 根因分析

### P1-01

`excess = len(versions) - OFFICIAL_VERSION_LIMIT` 把非正式版本也算进上限基数，而淘汰列表只从正式版本里挑。1 个正式 + 10 个非正式时 `excess = 1`，最旧的正式版本被删——从没超过 10 个正式版本也被裁剪。

### P1-02

只读判定（`_disk_schema_version > 3`）散落在 `ProjectManager.save` 与 GUI 路径。`v3_storage` 的 `StoryRepository` / `VersionStore` / `TaskStore` 与 `ProjectManager._write_v3_story` 直接写盘，没有检查磁盘版本；调用方（例如直接操作数据层的代码或测试）可以绕过。`save_version` 在写快照文件之后才间接触发 `save`，检查过晚。`restore_version` 先改 Story 后才写盘。

### P1-03（两个叠加根因）

1. 旧 `_hydrate` 在「`stories/` 是空骨架、`project.json` 也没有有效 story」时调用 `init_primary_story` 重建——等于用空数据覆盖唯一副本；`load` 对 `CorruptDataError` 一律当作「读不到」，走 `story = None` 分支。
2. **本轮调试发现并修复的新根因**：
   - `is_valid_story` 只判断 `shots` 非空，`shots: "not-a-list"` 也被判「有效」→ 坏的 project.json story 被采纳并写回 `stories/`。新增 `_usable_project_story`（有效且 `shots` 是列表）作为采纳门槛。
   - `_v3_load` 隔离损坏文件的分支被 `if not data.get("_v3_adopt")` 包住，当内存 story 已是权威值时**不会**隔离，`sync_story` 随后直接覆盖损坏字节。改为：先检测并隔离，隔离成功后清掉 `_v3_adopt` 交由 V3 层按规则恢复。
   - `ProjectManager._normalize_story` 会把 V3 层从 `versions/` 恢复出的 candidate 误判为坏而 `pop("story")`，恢复结果丢失。改为：`_v3_adopt` 存在时跳过 normalize（candidate 来自已规范的版本快照）。

## 6. 修改前后差异

### P1-01 · `modules/project_manager.py::_prune_versions`

```python
# 修改前
candidates = [v for v in versions if isinstance(v, dict)
              and (v.get("official") or not official_only) and v.get("version_id") != active]
excess = len(versions) - OFFICIAL_VERSION_LIMIT
...
for entry in doomed:
    try: path.unlink()
    except OSError: pass          # 文件还在，元信息却已删
story["versions"] = [... not in doomed_ids]

# 修改后
official = [v for v in versions if isinstance(v, dict) and v.get("official")]
excess = len(official) - OFFICIAL_VERSION_LIMIT          # 只按正式版本计数
doomed = [official 中从旧到新、未被 _version_referenced 的前 excess 个]
removed = set()
for entry in doomed:
    if path.exists():
        try: path.unlink()
        except OSError: continue                          # 删不掉：保留元信息
    removed.add(vid)
story["versions"] = [... not in removed]                  # 只移除真正删掉文件的条目
```

- 活动版本由 `_version_referenced`（active_version / base 链 / `shot.voice_version` / `stale.versions`）保护，永不被删。
- `official_only` 参数保留（接口兼容）；非正式版本本轮**不删除**（行为变化：以前会在 `official_only=False` 时参与裁剪）。

### P1-02 · `modules/v3_storage.py`

新增统一守卫（数据层，唯一真源是磁盘）：

```python
def assert_writable(project, what: str = "项目数据"):
    """磁盘上 project.json 的 schema_version > 3 → 未来版本只读，抛 RepositoryError。
    文件不存在 / 读不了 / 损坏：不是「未来版本」，放行（交给各自流程处理）。"""
```

接入点（全部在**任何修改之前**）：

| 类 / 函数 | 检查位置 |
| --- | --- |
| `StoryRepository.create / update / archive / rebuild_index / _sync_index` | 函数首行 |
| `VersionStore.snapshot / restore` | 函数首行 |
| `TaskStore.start / finish` | **不守卫**（P1-Fix-2 / R-T1 最终决定：运行过程元数据不纳入未来版本只读边界） |
| `TaskStore.mark_abandoned` | 函数首行（启动时的项目级写操作，保留守卫） |
| `ProjectManager.save` | `sync_story` 之前（`RepositoryError` → `ProjectReadOnlyError`；打开时只读则跳过对账写回） |
| `ProjectManager.save_version` | 生成版本 id **之前**、创建快照文件**之前** |
| `ProjectManager.restore_version` | 读取 / 修改 Story 之前 |
| `ProjectManager.set_story / clear_story / _write_v3_story` | 函数首行 |

**TaskStore 边界（P1-Fix-2 / R-T1 最终决定）**：`start` 与 `finish` **不**调用 `assert_writable`，`mark_abandoned` **保留**守卫。理由：未来版本程序的 `project.json` 结构未知，但其 `stories/`、`versions/`、`story/index.json` 与任务运行无关；把运行状态也冻结会让新程序打开过的项目在本程序里彻底不可用，超出 P1「保护业务数据」的既定范围。`mark_abandoned` 是启动时按项目进行的写操作，仍纳入边界。类 docstring 与代码一致。此前版本（P1-Fix 首次提交 d4db886）中 `start/finish/mark_abandoned` 三者均守卫的实现已被 R-T1 推翻并修改，见 `docs/reports/V3_P1_FIX2_HANDOVER.md`。

### P1-02 · `modules/project_manager.py::_write_v3_story`

- 写盘前 `assert_writable`；读取失败只记录原因（V3 写入失败不破坏 V2 数据）。
- 同名 payload 补齐：`versions`、`active_version` 从 existing 拷入——修掉「每次 save 都丢 `active_version`」的真实缺陷（P1-01 活动版本测试暴露）。

### P1-03 · `modules/v3_storage.py`

新增：

```python
class CorruptDataError(RepositoryError)     # 文件存在但内容损坏（区别于「暂时读不了」）
read_json: JSONDecodeError → CorruptDataError

V3ProjectManager.load:
    except CorruptDataError: return self._recover_corrupt_story(data)

_usable_project_story(data)                 # 有效且 shots 是列表才算可用
_recoverable_version(data)                  # versions/ 候选（story["versions"] 顺序，否则扫 versions/ 目录）
version_file_path(version_id)
_quarantine_corrupt(path)                   # copy2 → .corrupt/<name>.<时间戳>.bak，再 unlink；OSError → None
_recover_corrupt_story(data)                # 规则 2/3/4
_hydrate v3 分支                            # 删除「init_primary_story 重建空 Story」，改为 versions/ 候选或保持现状
```

### P1-03 · `modules/project_manager.py`

- `_save` 路径（经 `_v3_load`）：写盘前检测 `stories/` 文件损坏 → 隔离 → 清 `_v3_adopt` → V3 层恢复。
- `_normalize_story`：`_v3_adopt` 存在时不 normalize（保护 versions/ 恢复结果）。

## 7. 文件与函数清单

| 文件 | 变更 |
| --- | --- |
| `modules/v3_storage.py` | +208/-…：`CorruptDataError`；`read_json`；`assert_writable`；`StoryRepository` / `VersionStore` / `TaskStore` 守卫；`V3ProjectManager.load/_hydrate` 重写损坏路径；新增 `_usable_project_story`、`_recoverable_version`、`version_file_path`、`_quarantine_corrupt`、`_recover_corrupt_story`；`TaskStore` 边界 docstring |
| `modules/project_manager.py` | +108/-…：`_prune_versions` 重写；`_save` 统一检查 + `sync_story` 异常转 `ProjectReadOnlyError`；`_v3_load` 先隔离后恢复；`_normalize_story` 保护 candidate；`save_version` / `restore_version` / `set_story` / `clear_story` / `_write_v3_story` 守卫；`_write_v3_story` 保留 `versions` / `active_version` |
| `tests/test_v3_storage.py` | +289/-…：新增 3 个测试类共 19 条 + 1 条既有完整性测试的**增强断言**（`test_v3_without_any_story_is_reported` 原 `assertIsNone(get_story(...))` 保留，仅新增字节保留断言） |
| `docs/reports/V3_P1_FIX_HANDOVER.md` | 本报告（新增） |

## 8. 恢复策略与架构决策

### P1-03 损坏判定规则（判定顺序即优先级）

| 情形 | 行为 |
| --- | --- |
| ① `stories/story/story.json` 合法 | 以它为准（原逻辑不变） |
| ② `stories/` 缺失/损坏，`project.json.story` **可用**（有效且 `shots` 是列表） | 损坏文件原始字节 copy 到 `.corrupt/` 后移出原位置 → `_v3_adopt` 采纳 project.json → 写盘恢复 `stories/` |
| ③ 两侧都无效，`versions/` 有可加载且 `shots` 非空快照 | 损坏文件先隔离 → 采纳版本快照并写回（`_v3_adopt`） |
| ④ 两侧都无效且无可用历史 | **抛 `CorruptDataError`，不写盘、不覆盖任何字节**；V2 界面仍可打开项目 |
| ⑤ 无历史 | 同 ④，不用空故事覆盖 |
| ⑥ `project.json.story` 有镜头但结构坏（如 `shots` 非列表） | 视为「已损坏但非空」，走 ③/④，**绝不**当作空项目 |
| ⑦ 隔离（备份）失败 | 抛 `RepositoryError`，原文件一字不动 |

### 架构决策

1. **损坏文件的字节保留方式 = 隔离（quarantine）**：`copy2` 进 `.corrupt/` → `unlink` 原文件。理由：项目目录之外无可靠写入点；`.corrupt/` 在项目内且不参与 `stories/` 读取；只有移走损坏文件，正常写盘路径才能恢复。若改为保留原位，每次保存都会触发隔离分支。
2. **「有效」的判定**：`is_valid_story` 保持原语义（兼容既有代码），新增 `_usable_project_story` 作为恢复/采纳门槛，避免把 `shots` 非列表的坏数据当有效。
3. **V2 透明性不变**：内存里 V3 项目始终报 `schema_version=2`，写盘映射回 3；未来版本只读仍由 `ProjectManager.save` 抛 `ProjectReadOnlyError`（对外语义不变），数据层用 `RepositoryError`。
4. **Project ↔ Story 1:1 不变**：恢复只改 `stories/` 内容与 `primary_story_id` 元信息，不新增 Story 记录。

## 9. 新增测试清单（19 条）

### `P1FixVersionPruneTest`（P1-01，5 条）

1. `test_unofficial_versions_do_not_consume_official_quota` — 1 正式 + 9 非正式再存非正式 → 正式版本仍在。
2. `test_official_versions_pruned_at_limit` — 超过 10 个正式版本才裁剪最旧的。
3. `test_active_version_never_pruned` — 活动版本永不被删（同时覆盖 `active_version` 写盘不丢失）。
4. `test_referenced_version_never_pruned` — `shot.voice_version` 引用的版本不删。
5. `test_prune_keeps_metadata_when_file_delete_fails` — `Path.unlink` 抛 `OSError` 时元信息保留，所有被引用文件仍在。

### `P1FixFutureVersionTest`（P1-02，8 条，逐入口）

每个用例：把磁盘 `project.json` 改成 `schema_version=4` → 对全目录逐字节快照 → 调入口 → 断言抛 `(ProjectReadOnlyError, RepositoryError)` 且**快照逐字节不变、没有新文件**：
`test_save_refused`、`test_save_version_refused_before_snapshot_file`、`test_restore_version_refused`、`test_set_and_clear_story_refused`、`test_story_repository_refused`、`test_version_store_refused`、`test_init_primary_story_refused`、`test_normal_v3_project_still_writable`（正常 V3 仍可写，防误伤）。

### `P1FixCorruptRecoveryTest`（P1-03，6 条）

1. `test_story_file_broken_project_story_valid` — 走 `open_project`：从 project.json 恢复 3 个镜头，`.corrupt/` 恰有 1 份备份，字节 `b'{"broken": '` 完整。
2. `test_story_file_missing_project_story_valid` — stories 缺失、project.json 有效 → 恢复。
3. `test_both_sides_broken_is_reported_and_bytes_kept` — 两侧无效、无历史 → `CorruptDataError`；损坏字节进 `.corrupt/` 一字不差；随后 `pm.load` 不抛错，但 `pm.get_story` 返回 `None`（见最终核验报告第 4/5 节）。
4. `test_both_sides_missing_uses_history_if_any` — 两侧无有效 story，`versions/` 有快照 → 走 `open_project` 恢复 3 个镜头；`_v3_adopt` 不落盘。
5. `test_both_sides_invalid_without_history_never_writes_empty_story` — 无历史 → 不写任何旧内容、不伪造 story（project.json 的 `story` 保持 `None`）。
6. `test_quarantine_failure_does_not_touch_original` — 备份失败（mock `shutil.copy2` 抛 `OSError`）→ 抛错且原文件字节不变。

### 既有测试的改动说明（诚实披露）

- `IntegrityTest.test_v3_without_any_story_is_reported`：原断言（`vm.load` 抛 `RepositoryError`、`get_story(...)` 为 `None`）**全部保留**；仅新增「原字节进 `.corrupt/`」断言。无 mock。
- 无任何原测试被删除或弱化。

## 10. 完整测试结果

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests`（先清 `__pycache__`） | **Ran 358 tests，OK**，0 失败 / 0 错误 / 0 skip；耗时约 55–58 s |
| `python -m unittest discover -s tests -p test_v3_storage.py` | Ran 49，OK（原 30 + 新 19） |
| `python -m unittest discover -s tests -p test_project_manager.py` | Ran 46，OK（原样） |
| 修复前基线 | 339 tests OK |

358 = 339（原）+ 19（新）。无 skip、无 xfail。全程未调用真实 AI API（测试均使用 mock / 本地生成资源）。

## 11. GUI 冒烟

`python tests/gui_smoke.py` → **exit 0，`GUI smoke OK`**。输出包括：横屏渲染、故事渲染、AI 图像（mock）、AI 配音（本地合成）、倍速、带音轨成片渲染、清空配音、故事流程（版本列表 5 个）、批量面板 A/B 两个项目均 ok。GUI 冒烟使用离线/mock 资源，未调用真实 AI API。

## 12. 未解决项与风险

| 编号 | 内容 | 级别 | 说明 |
| --- | --- | --- | --- |
| R-01 | `.corrupt/` 无自动清理 / 限额 | P2 | 每次隔离产生一份 `<name>.<时间戳>.bak`；建议后续加数量上限或迁移到 `.trash/` |
| R-02 | 版本快照本身损坏（非 story.json） | P2 | `_recoverable_version` 跳过坏快照继续找；若全部坏则按规则 ④ 报错 |
| R-03 | `_version_file` 对非法 `version_id` 可能抛错 | P3 | 现有 `_validate_id` 路径保持一致，未改动 |
| R-04 | `Attribution` 为类变量（模块级上下文），非线程安全 | P2（审查已有） | 本轮未改 |
| R-05 | 非正式版本永不自动删除 | 行为变化 | 符合 P1-01 要求；长期可能积累结构升级 / 恢复备份快照，建议后续单独设计清理策略 |
| R-06 | `TaskStore.start/finish` 实际**纳入**了只读边界（与报告文字「不纳入」矛盾） | **已关闭（P1-Fix-2 / R-T1）** | GPT 决定：`start` / `finish` 不守卫，`mark_abandoned` 保留守卫；代码、docstring、本报告已按最终决定更新。见 `docs/reports/V3_P1_FIX2_HANDOVER.md` |
| R-07 | P2-01..P2-09、P3-01..P3-05（原审查） | 未处理 | 不在 P1-Fix 范围 |

## 13. 安全检查（确认）

- [x] 未覆盖 / 未删除任何未跟踪文件：`docs/architecture/Human_in_the_Loop_Workflow_{Decisions,Design,Risks}.md`、`docs/code_review/`、`docs/project_knowledge/`、`docs/reports/V3_P1_DATA_CONSISTENCY_AUDIT.md`
- [x] 未修改 V2.2 故事引擎 / 创建工作流 / GUI 代码
- [x] 未调用真实 AI API，无接口费用
- [x] 未删除或弱化原测试（唯一改动是增强断言，见第 9 节）
- [x] 未 `git reset` / `git clean` / 改写历史 / 强推
- [x] 未 push
- [x] 测试后干净：无 `.tmp` 残留（`write_json_atomic` 测试覆盖）；临时调试脚本已删除

## 14. 本地 commit

- 单个本地 commit，位于 `main`，父提交 `741d58d`。
- 提交信息结尾：`Co-Authored-By: Claude Code <noreply@anthropic.com>`
- 提交范围：`modules/project_manager.py`、`modules/v3_storage.py`、`tests/test_v3_storage.py`、`docs/reports/V3_P1_FIX_HANDOVER.md`
- **未 push。**

## 15. push 状态

**NO** — 按本轮要求不 push，等待 GPT 审查。

## 16. 建议 GPT 重点审查

1. `_prune_versions`：非正式版本「永不删除」的新语义是否符合 V2.2 预期；`official_only` 参数保留但语义收窄。
2. `assert_writable` 在 `project.json` 缺失 / 损坏时放行——是否覆盖全部未来版本场景（已测：save / save_version / restore_version / set+clear / StoryRepository ×3 / VersionStore ×2 / init_primary_story）。
3. TaskStore 边界：`.tasks/` 不纳入、`mark_abandoned` 纳入——**已按 GPT 决定落地（P1-Fix-2 / R-T1）**：`start / finish` 不守卫，`mark_abandoned` 保留守卫；代码与 docstring 一致。详见 `docs/reports/V3_P1_FIX2_HANDOVER.md` 第 8 节。
4. 隔离语义：损坏文件从原位移入 `.corrupt/`（字节 copy2 保留）。是否接受「原位置不存在、备份存在」作为「保留原始字节」的合规实现。
5. 规则 ⑥（`project.json.story` 有镜头但 `shots` 非列表 → 不作空项目处理）。
6. `_normalize_story` 在 `_v3_adopt` 存在时跳过是否可能漏掉其它规范化（candidate 来自 version 快照，已含 `schema_version` / `shots`）。
7. `_write_v3_story` 保留 `versions` / `active_version` 的修复（暴露的既有缺陷）。
8. 测试 3 中「V2 层照见坏 story」的断言：当前 `.corrupt/` 已存在时 V2 下游 `get_story` 会清掉内存 story；该断言只覆盖「load 照见」，是否符合验收预期。

## 17. 下一步

- 等待 GPT 审查本报告与 commit diff。
- GPT 验收通过前**不启动 P2**。
- 若审查有修改意见：按意见修改 → 重跑全量测试 + GUI 冒烟 → 追加本地 commit（仍不 push）。
