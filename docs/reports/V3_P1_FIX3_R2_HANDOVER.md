# AI Story Studio V3 — P1-Fix-3-R2 交接报告

- 日期：2026-11-10
- 仓库：AIHorrorStudio（本地工作目录 `D:\AImv\AI_Horror_Studio_V2`）
- 任务：P1-Fix-3-R2（R2-01 升级快照分支的目录副作用；R2-02 隔离备份的覆盖风险）
- 本轮性质：代码修复 + 测试补充 + 测试执行与环境排查 + 第三轮审查补充；**不提交、不推送、不启动 P2**。
- 第三轮补充（2026-11-10）：新增 R2-01 成功路径测试（4.5 / 6 / 7）、按 `git diff --numstat` 修正第 3 节数字、修正第 5.3 / 10 节跨卷表述。
- 最终收尾（2026-11-10，见第 15 节）：闸门次数断言收紧为 `== 5`、`_quarantine_corrupt` 过时 docstring 更新、测试类 docstring 修正；仅测试与 docstring，生产逻辑零改动。

> 事实分级：
> **[代码事实]** = 阅读当前代码可确认；
> **[实测]** = 本轮实际运行并通过命令输出确认；
> **[静态分析]** = 未运行、由代码路径推演得出的结论；
> **[推断/未验证]** = 既未运行也不足以从代码完全确认。

---

## 1. 任务基线

| 项 | 值 | 验证方式 |
| --- | --- | --- |
| 当前目录 | `D:\AImv\AI_Horror_Studio_V2` | `pwd` |
| 分支 | `main` | `git rev-parse --abbrev-ref HEAD` [实测] |
| HEAD（本轮开始与结束） | `a910c9a8bfc9de9db9b3d313119b5452b4e5bc09` | `git rev-parse HEAD` [实测] |
| Python | 3.12.10 | `python --version` [实测] |
| 本轮是否产生提交 | 否 | `git status --short` 仅有工作区修改 [实测] |

HEAD 与 R2 指令中的预期值一致，本轮未提交、未改动历史。

## 2. Git 工作区状态

```
 M docs/reports/V3_P1_FIX3_R1_HANDOVER.md      ← 上一轮遗留的 SHA 补写，原样保留
 M modules/project_manager.py                  ← 本轮 R2-01
 M modules/v3_storage.py                       ← 本轮 R2-02
 M tests/test_v3_storage.py                    ← 本轮新增测试
?? （15 个既有 untracked 文件 + 1 个本报告 = 当前共 16 个 untracked，见第 14 节）
```

未执行 `git add -A`、`reset`、`clean`、`rebase`、`checkout`、`commit`、`push`。未删除、移动、覆盖任何既有 untracked 文件。

## 3. 修改文件清单

以下数字全部来自 `git diff --numstat`（新增 / 删除），与 `git diff --stat`
（8/3 → `11 +-`、37/15 → `52`、307/4 → `311`）逐行一致。当前总计
`4 files changed, 354 insertions(+), 24 deletions(-)`。

| 文件 | 变更量（numstat 新增/删除） | 说明 |
| --- | --- | --- |
| `modules/project_manager.py` | +8 / −3 | R2-01：删除升级快照分支里提前的 `mkdir versions/`（含注释），改为先试运行写盘闸门 |
| `modules/v3_storage.py` | +37 / −15 | R2-02：备份落成由 `staging.replace(target)` 改为 `os.link` 独占创建 + 换名重试；最终收尾更新过时 docstring（实现未改） |
| `tests/test_v3_storage.py` | +307 / −4 | 新增 2 个测试类共 7 项（R2 6 项 + 第三轮补充 1 项成功路径）；2 个 R1 测试的故障注入点随机制迁移；最终收尾收紧闸门次数断言 + 修正类 docstring |
| `docs/reports/V3_P1_FIX3_R2_HANDOVER.md` | 新增（untracked） | 本报告 |
| `docs/reports/test_logs/P1_FIX3_R2{,_CLOSEOUT}/*.log` | 新增（被 `.gitignore` 忽略） | 历史 8 份 + 收尾 4 份真实测试日志 |

（快照参考：第三轮补充前 `tests/` 为 +195 / −4；补充成功路径测试后 +294 / −4；最终收尾后 +307 / −4。）

## 4. R2-01 的解决方式（升级快照不提前建目录）

### 4.1 问题

`_open_project()` 的升级快照分支在进入 `save_version()` **之前**执行
`(project / VERSIONS_DIR).mkdir(...)`。而真正的写盘闸门在 `save_version()` 内部，
失败（隔离失败 / 无恢复源）会让 `save_version` 抛错回滚，但目录已经留在磁盘上——
失败路径产生了不应有的空 `versions/`。

### 4.2 改法 [代码事实]

```python
if due and data.get("story") and not self._snapshot_written:
    # P1-Fix-3-R2（R2-01）：这里不再提前 mkdir versions/。
    # 先跑一遍写盘闸门（试运行），把「隔离失败 / 无恢复源」这类 ProjectError
    # 在创建任何目录之前拦下；通过后由 save_version 正式隔离并写快照。
    try:
        self._guard_pending_quarantine(project, data)
    except ProjectError:
        return project          # 既有容错语义：升级快照失败不阻止打开
    self._snapshot_written = True
    try:
        data = self._migrate_with_v3(project, data)
        self.save_version(project, data, note="V2.2 结构升级", official=False)
        return project
    except ProjectError:
        pass
```

要点：

- 没有在任何别处补一个替代的提前 `mkdir`；目录完全由 `save_version()` 在闸门成功之后自行创建。
- 预跑闸门失败 → `return project`，与既有「升级快照失败不阻止打开」的容错语义一致。
- 版本记录语义（`save_version(..., official=False)`）、异常容错（外层 `except ProjectError: pass`）均未改动。

### 4.3 预跑闸门与 `save_version` 内闸门的关系 [实测]

预跑闸门是**幂等**的：它在成功时消费 pending marker；在失败时抛出且不消费。
在失败路径上，后面的 `save_version()` 根本不会被调用（见 4.4 的探针输出），
因此不存在「预跑隔离一次 + 正式隔离一次」的重复隔离。

结构补充（第三轮核实）：`due=True` 时，分支前的第一次 `_migrate_with_v3` 内部**必然**调用
`save()`（`if changed or due`），而 `_save` 的闸门在 `finally` 里**无论成败都会释放 marker**。
因此 pending marker **不可能「活着」抵达** :402 的预检闸门——预检属于防御性检查。真实流程中
marker 的消费发生在第一次 migrate 内部的写盘闸门；预检通过时它看到的一定是 `marker=None`。
成功路径见 4.5。

### 4.4 实际调用顺序 [实测]

对「升级项目 + 分支内才出现损坏 + 隔离被模拟为失败」的场景插桩（探针脚本，仓库外）：

```
gate#1: marker=False -> ok
gate#2: marker=False -> ok
gate#3: marker=True -> ProjectError
open returned: （正常返回项目路径）
versions exists: False
snapshot_written: True
migrate calls: 2 | save_version calls: 0
story.json bytes: b'{"broken": '
.corrupt exists: False
tree identical to branch-entry: True
```

解读：

| 观察 | 含义 |
| --- | --- |
| gate#1 / #2 通过且 marker=False | 预跑闸门（:402）与分支内第一次读盘时，标记尚未产生 |
| gate#3 marker=True → ProjectError | 分支内第二次 `_migrate_with_v3` 的 `save()` 撞上闸门 |
| `save_version calls: 0` | 闸门在任何目录创建之前就中止了，`versions/` 不可能被建 |
| `snapshot_written: True` | 确实进入过升级快照分支（该标志仅在此分支内置 True）[代码事实：唯一赋值点 :406] |
| `versions exists: False` | 本次修复的核心断言成立 |
| `tree identical to branch-entry: True` | 失败后整棵目录树（文件字节 + 目录集合）与分支入口完全一致 |
| `.corrupt exists: False` | 无残留 |

### 4.5 成功路径：真实隔离一次 → 恢复 → 升级快照写入 [实测]

第三轮新增测试 `test_upgrade_snapshot_success_path_quarantines_once_then_writes`
（`P1Fix3R2UpgradeBranchTest`），**不 mock 闸门本身、不 mock 隔离结果**，只用 spy 记录：

场景：`_legacy_upgrade_project` 造出「磁盘属 V3、project.json 里 story 仍为旧结构 1」的项目，
在**打开之前**把 `stories/<id>/story.json` 写成 `b'{"broken": '`。

插桩记录到的实际调用顺序与 marker 状态：

```
#1 写盘闸门（分支前第一次 _migrate_with_v3 → save → _save）
   marker=story.json, 文件存在=True, _v3_adopt=可用 → ok
   → 真实 _quarantine_corrupt 成功（1 次），marker 被消费（marker_after=None）
#2 预检闸门（_open_project :402）              marker=None → ok
#3 分支内第二次 _migrate_with_v3 → save 闸门   marker=None → ok
#4 save_version 内部闸门                       marker=None → ok
（#5 为 save_version 收尾的 save() 再走一次闸门，marker=None → ok）
真实隔离次数：1（story.json）；save_version note：'V2.2 结构升级'
```

对应测试断言（7 组）：

| # | 断言 |
| --- | --- |
| 1 | `_snapshot_written is True`（确实进入升级快照分支），`open_project` 正常返回项目 |
| 2 | `_quarantine_corrupt` 全程**只调用 1 次**，且隔离的就是损坏的 `stories/<id>/story.json`；备份字节 == 原损坏字节 |
| 3 | 第一次闸门 `marker=True` 且文件存在，执行结果为 ok，`marker_after is None`；其后所有闸门 `marker=False`；结束后 `_pending_quarantine is None` |
| 4 | `save_version` 以 `note="V2.2 结构升级"` 调用，内部闸门见 marker=None（#4），**没有第二次隔离** |
| 5 | `versions/` 恰好 1 份快照：note 正确、3 个镜头、快照内不含 `versions` 字段 |
| 6 | `stories/<id>/story.json` 已恢复重写为当前结构（schema 2、3 个镜头），与原始损坏字节不同；`project.json` 仍带 `story` 字段 |
| 7 | `.corrupt/` 只有本次那一份 `.bak`，无 staging 残留 |

**与审查意见的差异，如实说明**：审查要求覆盖「预检前存在 pending marker；预检闸门成功消费
marker」。经代码核实这是**不可能出现的真实状态**——`due=True` 时第一次 `_migrate_with_v3`
必然写盘（见 4.3），而 `_save` 的 `finally` 无条件释放 marker。本测试因此覆盖真实成功链路中
marker 的**真实消费点**（第一次 migrate 的写盘闸门），并断言其后所有闸门（含 `save_version`
内部的闸门）都看到 `None`、不重复隔离。没有为了让测试通过而 mock 掉任何一次闸门调用。

**闸门调用次数 [实测]**：本场景实际恰好 **5 次**，顺序为

| # | 触发点 | 调用时 marker | 结果 |
| --- | --- | --- | --- |
| 1 | 分支前第一次 `_migrate_with_v3` 内部写盘（`save` → `_save`） | 有（`story.json`，文件存在） | ok，**消费 marker**，真实隔离 1 次 |
| 2 | `_open_project` 的预检闸门（:402） | None | ok（防御性检查） |
| 3 | 分支内第二次 `_migrate_with_v3` 内部写盘 | None | ok |
| 4 | `save_version` 自身写盘闸门 | None | ok |
| 5 | `save_version` 收尾 `save()` 的写盘闸门 | None | ok |

最终收尾已把断言从 `assertGreaterEqual(len(gates), 3)` 收紧为
`assertEqual(len(gates), 5)`，并保留全部原有 marker 断言（第 1 次看到 marker、成功消费、
其后均为 None、结束 `_pending_quarantine is None`）。详见第 15 节。

## 5. R2-02 的解决方式（备份文件不覆盖）

### 5.1 问题

原实现：

```python
target = root / f"{path.name}.{stamp}.bak"
staging.replace(target)      # ← 目标已存在时静默覆盖
```

`Path.replace()` 会覆盖已存在的同名文件。如果时间戳（含微秒）与某份历史备份撞名，
历史备份就被这次隔离的字节覆盖掉；随后若失败清理把 `target` 删掉，历史备份就
彻底丢失。

### 5.2 改法 [代码事实]

```python
staging = root / f".{path.name}.{uuid.uuid4().hex[:8]}{_TMP_SUFFIX}"
shutil.copy2(path, staging)
stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
for attempt in range(64):
    candidate = (root / f"{path.name}.{stamp}.bak" if attempt == 0 else
                 root / f"{path.name}.{stamp}-{uuid.uuid4().hex[:6]}.bak")
    try:
        os.link(staging, candidate)      # 目标存在 → FileExistsError（原子）
        target = candidate
        break
    except FileExistsError:
        continue                          # 绝不覆盖，换名重试
if target is None:
    raise OSError("... .corrupt/ 已尝试 64 次")
staging.unlink()
path.unlink()
return target
```

逐条对应指令要求：

| 要求 | 实现 |
| --- | --- |
| 绝不覆盖已存在目标 | `os.link` 在目标存在时抛 `FileExistsError`，不写入 |
| 不依赖时间戳唯一 | 冲突后追加 `-<6位随机hex>`，最多 64 次 |
| 冲突换名或安全中止 | 换名重试；64 次耗尽 → `OSError` → 由外层 `except OSError` 返回 `None` |
| 独占创建语义（非 check-then-replace） | `os.link` 本身是原子操作，无 TOCTOU 窗口 |
| 清理只删本次创建的文件 | `target` 变量仅在 link **成功后**赋值；清理循环只遍历 `(staging, target)` |
| 原文件最后才 unlink | `staging.unlink()`、`path.unlink()` 都在 link 成功之后 |
| 返回值 / 调用方语义不变 | 成功返回 `Path`，失败返回 `None`，签名未变 |

### 5.3 Windows 上的 `os.link` [实测]

本轮 6 项 R2 测试全部在 Windows 11 + NTFS 上真实执行并通过，包括：

- 正常成功路径（备份字节 == 原文件、原文件移走、无 staging 残留）
- 首候选名与历史 `.bak` 同名（`FileExistsError` → 换名 → 历史字节不变）
- 冲突换名后原文件 unlink 失败（返回 `None`；历史不动；本次 target 被清理）
- 连续多次冲突（第三次 link 才成功；历史不变）
- 64 次冲突耗尽（原始文件、历史备份、整棵目录树均不变）

另用仓库外探针对「非 `FileExistsError` 的 `OSError`」（模拟权限 / 跨卷 / 文件系统不支持）：

```
non-FileExists OSError -> returns None: True | original intact: True |
tree unchanged: True | .corrupt removed: True
```

即这类异常同样走安全失败路径，不会留下半成品。

关于「跨卷」的准确描述（第三轮修正）：

- `os.link(staging, candidate)` 的**两端都在 `.corrupt/` 目录内**。即使 `.corrupt/` 本身是
  指向另一卷的目录联接 / 挂载点，两端也会经由同一条联接解析到**同一个真实目录、同一卷**，
  因此**不会在 link 两端之间产生跨卷**。跨卷在本实现里不是这两个端点之间的风险项。
- 真正可能让 `os.link` 失败的是另外两类情况：
  1. **文件系统不支持硬链接**（如 FAT32 / exFAT，或某些网络文件系统 / 沙箱）；
  2. **权限不足**（如目标目录对当前用户只读或受策略限制）。
- 以上两类失败都以**普通 `OSError`（非 `FileExistsError`）** 形式出现，走
  `_quarantine_corrupt` 的外层 `except OSError` → 返回 `None`。这一安全失败路径已由
  仓库外探针**实测**（见上方探针输出：原文件完整、目录树不变、`.corrupt/` 被撤掉）。
  「文件系统不支持硬链接 / 权限不足」是**按代码路径推断**会抛同一类 `OSError`，
  未在真实 FAT32 卷或权限受限环境实跑。

## 6. 新增测试清单（7 项；其中第三轮补充 1 项）

### `P1Fix3R2UpgradeBranchTest`（R2-01，2 项）

| 测试 | 断言要点 |
| --- | --- |
| `test_upgrade_snapshot_gate_failure_does_not_create_versions` | 真实走 `_open_project()` 的升级分支（用 `_snapshot_written` 确认）；损坏文件在**首次 `_migrate_with_v3` 之后**才写入，确保标记只可能在分支内产生；隔离失败被容错；`versions/` 不存在；整树与分支入口逐字节一致；原损坏文件完整；无 `.corrupt` / 临时残留 |
| `test_upgrade_snapshot_success_path_quarantines_once_then_writes`（第三轮新增） | 损坏在打开前就存在；**真实隔离（不 mock 结果）恰好 1 次**；第一次闸门看到 marker 并消费，其后闸门全部 marker=None、不重复隔离；`save_version` 以「V2.2 结构升级」写入 1 份快照；`stories/` 恢复为当前结构；`.corrupt/` 仅 1 份备份无残留。详见 4.5 |

### `P1Fix3R2QuarantineNoOverwriteTest`（R2-02，5 项）

| 对应 | 测试 | 断言要点 |
| --- | --- | --- |
| 测试 A | `test_target_name_conflict_never_overwrites_history` | 首候选名与历史 `.bak` 同名 → 换名；历史字节不变；新备份内容正确；无 staging |
| 测试 B | `test_conflict_then_failure_leaves_history_and_cleans_own_files` | 冲突换名成功后原文件 unlink 失败 → 返回 `None`；历史不动；只清理本次 target；原文件完整 |
| 测试 C | `test_repeated_conflicts_never_overwrite_and_all_history_intact` | 前两次 `FileExistsError`、第三次成功；历史全程不变；无 staging |
| 测试 C' | `test_64_conflicts_safely_abort` | 64 次冲突 → 安全放弃；整树（文件 + 目录）不变 |
| 测试 D | `test_success_backup_matches_original_and_no_staging_residue` | 备份字节 == 原文件；原文件移走；`.corrupt/` 只有备份一项 |

确定性冲突通过 `mock.patch.object(v3, "datetime", FixedDT)` 固定时间戳实现，不依赖真实时钟竞态。

### 已更新（非新增）的 2 项 R1 测试

`test_staging_replace_failure_leaves_no_files` 与 `test_staging_replace_failure_keeps_history_backups`
原本 mock `Path.replace` 抛错。R2-02 之后正式备份不再经过 `Path.replace`，该注入点失效，
两个测试在改动后失败（`assertIsNone` 拿到的是成功返回的备份路径）。

**如实记录**：这两个测试在 R2-02 实现后确实失败过。处理方式是把故障注入点迁移到当前机制的
等价位置（`v3.os.link` 抛 `OSError`），**断言未做任何删减或弱化**——仍然要求返回 `None`、
原文件字节不变、无 `.corrupt` / 历史备份字节不变。理由是这两个测试针对的正是被 R2-02 替换掉的
那一步机制，不属于「为了让测试通过而改无关模块」。

## 7. 完整测试结果

全部命令在 `D:\AImv\AI_Horror_Studio_V2` 下执行，Python 3.12.10。日志原文见
`docs/reports/test_logs/P1_FIX3_R2/`。

### 7.1 R2 专项测试 [实测]

```
$ python -I -m unittest discover -s tests -p test_v3_storage.py -k P1Fix3R2 -v
Ran 6 tests ... OK
EXIT_CODE=0
```

第三轮补充后同一过滤条件（含新增成功路径测试）：

```
$ python -I -m unittest discover -s tests -p test_v3_storage.py -k P1Fix3R2 -v
Ran 7 tests in 1.320s
OK
EXIT_CODE=0   （进程总耗时 1.740s）
```

日志：`docs/reports/test_logs/P1_FIX3_R2/r2_success_path_test.log`。

| 总数 | 通过 | 失败 | 错误 | 跳过 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 6（补充前） | 6 | 0 | 0 | 0 | 1.370s |
| 7（补充后） | 7 | 0 | 0 | 0 | 1.320s |

### 7.2 `test_v3_storage.py` 全量 [实测]

```
$ python -I -m unittest discover -s tests -p test_v3_storage.py
Ran 106 tests in 24.704s
OK
EXIT_CODE=0
```

第三轮补充后：

```
$ python -I -m unittest discover -s tests -p test_v3_storage.py
Ran 107 tests in 27.217s
OK
EXIT_CODE=0
```

日志：`docs/reports/test_logs/P1_FIX3_R2/r2_storage_tests_r3.log`（进程总耗时 27.370s）。

| 总数 | 通过 | 失败 | 错误 | 跳过 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 106（补充前） | 106 | 0 | 0 | 0 | 24.704s |
| 107（补充后） | 107 | 0 | 0 | 0 | 27.217s |

（R1 结束时 100 项 + R2 6 项 = 106 项；第三轮补充 1 项 = 107 项。）

### 7.3 回归：R-A2 / R-C1 / R-T1 [实测]

```
$ python -I -m unittest discover -s tests -p test_v3_storage.py -k P1Fix2        → Ran 26 tests ... OK
$ ... -k P1Fix2CorruptJudgeTest                                                  → Ran 10 tests ... OK
$ ... -k P1Fix2VersionRebuildTest                                                → Ran 12 tests ... OK
$ ... -k P1Fix2TaskBoundaryTest                                                  → Ran 4 tests ... OK
```

| 类 | 对应 | 总数 | 结果 |
| --- | --- | --- | --- |
| `P1Fix2CorruptJudgeTest` | R-A2 | 10 | OK |
| `P1Fix2VersionRebuildTest` | R-C1 | 12 | OK |
| `P1Fix2TaskBoundaryTest` | R-T1 | 4 | OK |

三类的业务规则未被本轮改动，回归全部通过。

### 7.4 全量 unittest [实测]

```
$ python -I -m unittest discover -s tests
Ran 415 tests in 67.133s
OK
EXIT_CODE=0
```

第三轮补充后：

```
$ python -I -m unittest discover -s tests
Ran 416 tests in 65.671s
OK
EXIT_CODE=0
```

日志：`docs/reports/test_logs/P1_FIX3_R2/r2_full_suite_r3.log`（进程总耗时 66.772s）。

| 总数 | 通过 | 失败 | 错误 | 跳过 | 耗时 | 退出码 |
| --- | --- | --- | --- | --- | --- | --- |
| 415（补充前） | 415 | 0 | 0 | 0 | 67.133s | 0 |
| 416（补充后） | 416 | 0 | 0 | 0 | 65.671s | 0 |

（R1 结束时 409 项 + R2 6 项 = 415 项；第三轮补充 1 项 = 416 项。补充前 415 项的证据与日志原样保留。）

### 7.5 GUI smoke [实测]

```
$ python -I tests/gui_smoke.py
...（渲染 / 故事流程 / 批处理面板全部 ok）
GUI smoke OK
EXIT_CODE=0
```

环境允许，实际执行通过。日志中的中文批次名在 GBK 控制台下显示为乱码，属控制台编码显示问题，
不影响判定（末行与退出码为准）。

### 7.6 失败与返工记录：如实说明

| 事件 | 事实 |
| --- | --- |
| 改动后首次跑 storage 套件 | `Ran 100 tests ... FAILED (failures=2)`，失败的是 2 个依赖 `Path.replace` 的 R1 测试 |
| 原因 | R2-02 替换了它们所注入的那一步机制，mock 不再命中 |
| 处理 | 把注入点迁移到 `v3.os.link`，断言不变（见第 6 节） |
| 结果 | 迁移后 106/106 通过 |

没有任何测试被删除，没有断言被弱化，没有伪造通过结果。

## 8. 环境排查：`unittest discover` 的 `ImportError`

### 8.1 现象

用户在 `D:\AImv` 执行 `python -I -m unittest discover -s tests -p test_v3_storage.py`，报：

```
ImportError: Start directory is not importable: 'tests'
```

`tests/__init__.py` 不存在。

### 8.2 结论 [实测]

**这不是缺陷，也不需要创建 `tests/__init__.py`。** 原因有两层：

1. **工作目录不对。** `D:\AImv` 下没有 `tests/`，自然无法发现。项目文档里的所有测试命令
   （`docs/project_knowledge/DEVELOPMENT_STATUS.md`、`docs/reports/V3_P1_FIX2_HANDOVER.md` 等）
   都是以**项目根目录**为 cwd 书写和使用的。
2. **`-t .` 才会要求它是包。** 实测对比：

   | 命令 | 结果 |
   | --- | --- |
   | `python -I -m unittest discover -s tests -p test_v3_storage.py`（不带 `-t`） | **Ran 106 tests … OK** |
   | `python -I -m unittest discover -s tests -t . -p …` | `ImportError: Start directory is not importable` |
   | `python -m unittest discover -s tests -t . -p …` | 同上（与 `-I` 无关） |

   不带 `-t` 时，unittest 把 `-s` 指定的目录本身当作顶层目录，因此不要求它是可导入包；
   显式给出 `-t .` 后，`tests` 必须能从项目根被当作包导入，而它没有 `__init__.py`。

### 8.3 采取的做法

- **没有**创建 `tests/__init__.py`，**没有**修改任何测试配置或生产代码。
- 全部测试按项目既有入口（不带 `-t`）在项目根目录执行。
- `-k` 过滤用于挑选测试子集；`python -m unittest tests.xxx` 这种模块路径方式不可用
  （同样因为 `tests` 不是包），已在日志中记录为无效尝试。

补充：`docs/reports/test_logs/` 下的 `.log` 文件被仓库 `.gitignore` 的 `*.log` 规则忽略
（`git check-ignore` 确认），因此不会出现在 `git status` 的 untracked 列表中。

## 9. 数据保护验证结果

| 要求 | 结论 | 依据 |
| --- | --- | --- |
| 升级快照失败不留空 `versions/` | 通过 | R2-01 测试 + 探针（`versions exists: False`，`save_version calls: 0`） |
| 升级快照成功路径：只隔离一次、快照落盘、状态正确 | 通过 | 第三轮新增测试（真实隔离 1 次；其后闸门全为 marker=None；1 份快照；见 4.5） |
| 失败后项目目录树零变化 | 通过 | `_snapshot_tree` 逐字节 + 目录集合比对 |
| 原损坏文件在任何失败下保持原样 | 通过 | R2-01 / R2-02 各失败用例均断言原始字节 |
| 历史 `.bak` 永不被覆盖 | 通过 | A / B / C / 64 次耗尽四类用例 |
| 清理只删本次创建的文件 | 通过 | `target` 仅 link 成功后赋值；B 用例验证 |
| 无恢复源时写入整次拒绝 | 未改动 | R-A2 / 规则 1 回归通过 |
| 重复隔离 | 未发生 | 探针：open 后 `.corrupt` 1 份，再 save 仍 1 份 |

## 10. 未解决问题与风险

| 项 | 性质 | 说明 |
| --- | --- | --- |
| 文件系统不支持硬链接 / 权限不足导致 `os.link` 失败 | **实测安全失败路径 + 推断适用场景** | link 两端都在 `.corrupt/` 内，即便 `.corrupt/` 是指向另一卷的联接，两端也解析到同一真实目录、同一卷，**不构成端点间跨卷**。真正风险是文件系统不支持硬链接或权限不足 → 普通 `OSError` → 实测返回 `None`（原文件/目录树不变）；真实 FAT32 / 权限受限环境未实跑 |
| 64 次冲突耗尽后的用户可见性 | 设计取舍 | 与既有「隔离失败」语义一致：返回 `None` → 闸门抛 `ProjectError` → 保存中止，`.corrupt/` 不再增加。未新增告警文案 |
| `tests/__init__.py` 缺失 | 既有状况 | 不影响既有测试入口；若将来想用 `-t .` 或 `python -m unittest tests.x` 需要补，但不在本轮范围 |
| 文档中的乱码 | 已知显示问题 | GUI smoke 在 GBK 控制台输出中文批次名乱码，不影响退出码判定 |

## 11. GUI smoke 结果

见 7.5。退出码 0，末行 `GUI smoke OK`，1/1 通过。

## 12. 安全边界确认

| 约束 | 状态 |
| --- | --- |
| 不 commit / 不 push / 不 amend | 遵守 |
| 不 reset / clean / rebase / 切分支 | 遵守 |
| 不 `git add -A` | 遵守 |
| 不删除/覆盖/移动既有 untracked 文件 | 遵守（15 个既有 untracked 文件完整；当前 untracked 共 16 个 = 既有 15 + 本报告） |
| 保留 R1 报告的既有 SHA 补写 | 遵守（4 行 diff 原样） |
| 不扩大 R2-01 / R2-02 修改范围 | 遵守（仅 3 个代码/测试文件） |
| 不启动 P2 | 遵守 |

## 13. 后续建议

1. 等待第三轮只读审查；审查通过后再统一提交，提交信息中注明 R2-01 / R2-02。
2. 如需长期保留测试日志，可在 `.gitignore` 中对 `docs/reports/test_logs/` 加白名单，
   当前它们被 `*.log` 规则忽略（本轮未改 `.gitignore`）。
3. `_quarantine_corrupt` 的重试上限（64）与命名方案如被审查认为需要可配置，可单独提
   后续事项，本轮不做。

## 14. 工作区文件清单（收尾核验）

修改（3 个代码/测试文件 + 1 个既有改动）：

```
 M docs/reports/V3_P1_FIX3_R1_HANDOVER.md
 M modules/project_manager.py
 M modules/v3_storage.py
 M tests/test_v3_storage.py
```

新增（1 份报告 + 12 份日志 = 历史 8 份 + 收尾 4 份；日志被 `.gitignore` 忽略）：

```
docs/reports/V3_P1_FIX3_R2_HANDOVER.md
docs/reports/test_logs/P1_FIX3_R2/r2_targeted_tests.log
docs/reports/test_logs/P1_FIX3_R2/r2_storage_tests.log
docs/reports/test_logs/P1_FIX3_R2/r2_regression_tests.log
docs/reports/test_logs/P1_FIX3_R2/r2_full_suite.log
docs/reports/test_logs/P1_FIX3_R2/r2_gui_smoke.log
docs/reports/test_logs/P1_FIX3_R2/r2_success_path_test.log      ← 第三轮
docs/reports/test_logs/P1_FIX3_R2/r2_storage_tests_r3.log       ← 第三轮
docs/reports/test_logs/P1_FIX3_R2/r2_full_suite_r3.log          ← 第三轮
docs/reports/test_logs/P1_FIX3_R2_CLOSEOUT/closeout_branch.log       ← 最终收尾
docs/reports/test_logs/P1_FIX3_R2_CLOSEOUT/closeout_nooverwrite.log  ← 最终收尾
docs/reports/test_logs/P1_FIX3_R2_CLOSEOUT/closeout_storage.log      ← 最终收尾
docs/reports/test_logs/P1_FIX3_R2_CLOSEOUT/closeout_full_suite.log   ← 最终收尾
```

untracked 既有文件（15 个，全部原样保留；加上本报告后当前 untracked 总数为 16 个）：

```
docs/architecture/Human_in_the_Loop_Workflow_Decisions.md
docs/architecture/Human_in_the_Loop_Workflow_Design.md
docs/architecture/Human_in_the_Loop_Workflow_Risks.md
docs/code_review/R1_review_materials.md
docs/project_knowledge/ARCHITECTURE.md
docs/project_knowledge/DATABASE_SCHEMA.md
docs/project_knowledge/DATA_FLOW.md
docs/project_knowledge/DEVELOPMENT_STATUS.md
docs/project_knowledge/KNOWLEDGE_MAINTENANCE.md
docs/project_knowledge/MODULE_INDEX.md
docs/project_knowledge/PROJECT_MAP.md
docs/project_knowledge/TECHNICAL_DECISIONS.md
docs/reports/V3_P1_DATA_CONSISTENCY_AUDIT.md
docs/reports/V3_P1_FIX3_R1_REVIEW_BUNDLE.md
docs/reports/V3_P1_FIX_FINAL_AUDIT.md
```

最终 HEAD：`a910c9a8bfc9de9db9b3d313119b5452b4e5bc09`（未产生新提交）。

## 15. 最终收尾（三项）

最终收尾（2026-11-10）只做三项，**生产逻辑零改动**：`modules/project_manager.py` 本轮未再修改；
`_quarantine_corrupt()` 仅改 docstring，函数体一字未动。

### 15.1 任务 1：收紧成功路径测试的闸门次数断言 [实测]

- 修改：`tests/test_v3_storage.py::P1Fix3R2UpgradeBranchTest::test_upgrade_snapshot_success_path_quarantines_once_then_writes`
  中 `self.assertGreaterEqual(len(gates), 3)` → `self.assertEqual(len(gates), 5)`，并在注释中
  逐条列出 5 次调用来源。
- 依据：先运行仓库外探针确认实际次数为 5（调用顺序见 4.5 新增表格）；再运行测试，收紧后
  仍为 `Ran 2 tests … OK`。**没有为了让预期成立而修改生产代码。**
- 原有 marker 断言全部保留：第 1 次闸门 `marker=True` 且文件存在、`result="ok"`、
  `marker_after is None`；其后所有闸门 `marker=False`、`marker_after is None`；
  结束 `_pending_quarantine is None`。

### 15.2 任务 2：更新 `_quarantine_corrupt()` 函数说明 [代码事实]

`modules/v3_storage.py:977-1048` 的 docstring 原文仍把主流程写成
「copy2 → 随机 staging → **rename** 成正式备份」，与 R2-02 实际使用的 `os.link()` 独占创建
不一致。现改为描述当前真实顺序：

1. 需要时创建 `.corrupt/`（记录是否本次新建，供失败回滚）；
2. `copy2` 原文件到随机 staging（`.<name>.<8hex>.tmp`）；
3. `os.link(staging → target)` 独占创建（目标存在 → `FileExistsError`，原子无 TOCTOU）；
4. 候选名 `<name>.<stamp>.bak`，冲突换 `<name>.<stamp>-<6hex>.bak`，最多 64 次；
5. 成功后先 unlink staging、最后 unlink 原文件，全部成功才返回 target。

失败语义仍按实际代码写明：任何 `OSError`（含 64 次耗尽、权限不足、文件系统不支持硬链接）
→ 只清理本次实际创建的文件（staging + link 成功的 target）→ 本次新建的 `.corrupt/` 尽力 rmdir
→ 返回 `None`；历史备份永不覆盖或误删；清理自身失败时残留如实可见。
并保留一句历史说明（旧实现是 `replace()`/rename，会覆盖同名文件，已被取代）。

**未改动实现**：`git diff` 对该文件只剩 docstring 行的替换 + 原有的 R2-02 实现改动；
`path = Path(path)` 起的函数体与上一轮审查时逐字相同。

### 15.3 任务 3：更新测试类 docstring [代码事实]

`P1Fix3R2UpgradeBranchTest` 类 docstring 由单行「升级快照分支不得提前创建 versions/」
（隐含 1 项测试）改为明确列出 **2 项测试**：失败路径（分支内损坏 + 隔离失败，不留空
`versions/`、目录树逐字节不变）与成功路径（打开前即损坏，真实隔离一次并写入升级快照）。
测试行为未改。

### 15.4 收尾测试结果 [实测]

全部在 `D:\AImv\AI_Horror_Studio_V2`、Python 3.12.10 下执行，命令均不带 `-t`：

| 运行 | 命令 | 结果 | 耗时 | 退出码 | 日志 |
| --- | --- | --- | --- | --- | --- |
| `P1Fix3R2UpgradeBranchTest` | `python -I -m unittest discover -s tests -p test_v3_storage.py -k P1Fix3R2UpgradeBranchTest -v` | Ran 2, OK | 0.645s（进程 1.283s） | 0 | `P1_FIX3_R2_CLOSEOUT/closeout_branch.log` |
| `P1Fix3R2QuarantineNoOverwriteTest` | `… -k P1Fix3R2QuarantineNoOverwriteTest -v` | Ran 5, OK | 0.903s（进程 1.484s） | 0 | `P1_FIX3_R2_CLOSEOUT/closeout_nooverwrite.log` |
| storage 全量 | `… -p test_v3_storage.py` | Ran 107, OK | 25.889s（进程 26.520s） | 0 | `P1_FIX3_R2_CLOSEOUT/closeout_storage.log` |
| 全量套件 | `python -I -m unittest discover -s tests` | Ran 416, OK | 66.032s（进程 66.872s） | 0 | `P1_FIX3_R2_CLOSEOUT/closeout_full_suite.log` |

失败 / 错误 / 跳过：全部为 0。没有任何测试被删除、跳过或弱化。
GUI smoke 本轮未重跑（未改生产逻辑）——其既有实测结论仍见 7.5 / 11。

### 15.5 收尾后的 Git 状态 [实测]

```
$ git rev-parse --abbrev-ref HEAD   → main
$ git rev-parse HEAD                → a910c9a8bfc9de9db9b3d313119b5452b4e5bc09
$ git diff --numstat
2	2	docs/reports/V3_P1_FIX3_R1_HANDOVER.md
8	3	modules/project_manager.py
37	15	modules/v3_storage.py
307	4	tests/test_v3_storage.py
$ git diff --stat → 4 files changed, 354 insertions(+), 24 deletions(-)
$ git diff --check  → 无输出
$ git status --short → 4 modified + 16 untracked（15 个既有 + 本报告）
```

HEAD 未变；未 commit / push / add / reset / clean / rebase / checkout / stash；
未删除任何文件或目录。
