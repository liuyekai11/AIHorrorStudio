# V3 STAGE 0（含 Stage 0.5 / Stage 0.6 修订）— 迁移方案（V2 → V3）

日期：2026-11-05
版本：**Stage 0.6 修订版**（取代 Stage 0.5 版同名文件）
性质：设计方案，**本阶段不执行任何迁移**。
配套：[现有架构审计](V3_STAGE0_CURRENT_ARCHITECTURE_AUDIT.md)、[目标架构](V3_STAGE0_TARGET_ARCHITECTURE.md)、[执行摘要](V3_STAGE0_EXECUTIVE_SUMMARY.md)、[架构决策](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md)、[MVP 范围](V3_STAGE0_5_MVP_SCOPE.md)、[开发路线](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md)、[修订报告](V3_STAGE0_5_REVIEW_REPORT.md)、[Stage 0.6 冻结基线](V3_STAGE0_6_FINAL_BASELINE.md)。

---

## 0. 本文件修订摘要

### 0.1 Stage 0.5 修订（保留）

| # | Stage 0 初版问题 | Stage 0.5 修正 |
| --- | --- | --- |
| 1 | 未明确 K-01 对迁移的阻塞关系 | §1 明确：**K-01 未修复并通过回归前，禁止执行任何 V2→V3 迁移** |
| 2 | K-02 只是「并入 P1」 | §1 要求 K-02 改为事务式暂存提交，纳入 P0 |
| 3 | schema_version 语义含糊（「schema_version==2 且有 story/ 即为 V3」） | §3.1 重写版本判定矩阵，禁止「2 被识别为完整 V3」 |
| 4 | 暂存目录放在 `<project>/migration_staging/` | §3.4 改为**项目外**暂存与备份目录，并做路径边界校验 |
| 5 | 「先 replace project.json，再 rename story 目录」被描述为原子提交 | §3.4 承认目录级 rename 不是整体事务；新增提交日志 + 状态标记 + 启动恢复 |
| 6 | story 缺失时「生成空 Story 并标记」 | §3.2 改为：**保留原始字节、不创建空 Story、优先从历史版本恢复** |
| 7 | 迁移验收用例不足 | §5.1 扩充为 12 类，含「迁移中断」「未来 schema_version」 |
| 8 | 未覆盖 Windows 文件占用 / 进程中断 / 切换失败 | §3.6 新增 Windows 异常处理与恢复流程 |

### 0.2 Stage 0.6 修订（审查问题 1 / 5 / 6）

| # | 审查指出的问题 | Stage 0.6 修正 |
| --- | --- | --- |
| 9 | 事务恢复只到「事务级」状态（PREPARED / COMMITTING …），**步骤级信息不足**，无法判断「文件到底改到哪一步」 | §3.4.2 改为**逐步骤事务日志**：每个步骤记录 10 个字段与 6 个状态（含 `INTENT_RECORDED` / `RECOVERY_REQUIRED`），坚持「先写 INTENT 再执行、验证后才 COMPLETED、不得只凭日志推断文件已完成」 |
| 10 | 恢复动作表过于笼统 | §3.4.3 给出**恢复入口**、**按实际文件状态判定的恢复动作表**、**日志与文件不一致的处理**、**恢复必须幂等** |
| 11 | 目标路径冲突（项目内已有 `story/`）的处理不完整 | §3.4.4 新增冲突判定与处理规则（禁止覆盖、禁止删旧目录、无法证明安全即停止） |
| 12 | 异常 Story 的人工恢复流程不完整（无审计记录要求） | §3.2 / §3.4.5 补充来源记录、恢复结果记录、异常项目状态、有损恢复须用户显式确认、全部动作进入审计 |
| 13 | `assert_p0_fixed()` 只写「读版本号 + 运行自检」，机制不明确 | §1.3 重写为 **6 项明确检查**，并区分「开发测试阶段的 P0 验收」与「正式迁移时的运行时安全检查」 |
| 14 | 迁移安全验收缺步骤级测试 | §5.1 由 12 类扩充为 19 类（终审后为 **23 类**）（新增 7 类步骤级中断 / 重复执行 / 日志文件不一致 / 目标冲突 / Windows 占用 / 恢复失败 / 字节级不变） |
| 15 | 同一次迁移在文档中出现多个 OQ 编号 | §9 统一引用 [Stage 0.6 统一 OPEN QUESTION 注册表](V3_STAGE0_6_FINAL_BASELINE.md#11-open-question-总表)，不再单独编号 |

### 0.3 Stage 0.6 终审修订（ChatGPT 审查结论 CONDITIONAL PASS，意见 2 / 3）

| # | 审查指出的问题 | 终审修正 |
| --- | --- | --- |
| 16 | 事务记录在暂存副本之后才建立，暂存复制阶段位于「事务外」，复制中断后无日志可依 | §3.4.2 调整阶段顺序：**预检通过后立即原子写入 `transaction.json`（`state=OPEN`）**，再以 `STAGE_COPY` 步骤「先持久化 INTENT → 执行复制 → 校验 → COMPLETED」生成暂存副本；§3.4.3 新增**暂存复制中断的恢复判定**；§3.4.6 新增「不完整暂存副本的处置」——不完整暂存副本**不得作为有效迁移结果**；§5.1 由 19 类扩充为 **21 类**（新增「暂存复制中断」与「不完整暂存副本被拒绝」） |
| 17 | `MOVE_TREE` 允许「将 project 目录内的旧目录移动到项目外」，与「原始 V2 文件必须保留」冲突 | §3.4.2 步骤类型表重写 `MOVE_TREE`：**只移动经哈希验证的暂存区内容，不移动原始 V2 文件**；原始 V2 文件必须保留；其他移动行为需独立授权与独立恢复机制，默认不实现 |

### 0.4 终审补充核验 R4 — 事务日志与暂存副本物理隔离

| # | 终审补充意见 | 本次修正 |
| --- | --- | --- |
| 18 | `transaction.json` 与 `STAGE_COPY` 的目录边界不够明确：哈希范围、删除边界、启动扫描形态均未固定 | §3.4.1 固定目录结构 `.migration_staging/<tx_id>/transaction.json` + `.migration_staging/<tx_id>/payload/` 并给出隔离 8 条；§3.4.2 明确 `STAGE_COPY` 只复制与校验 `payload/`，新增「哈希计算范围」小节，`transaction.json` 原子写失败即禁止开始复制；§3.4.3 新增按「日志 / payload」存在性识别的 4 种扫描形态表；§3.4.6 明确不完整副本处置**只删 `payload/`、不删 `transaction.json`**；§5.1 新增第 21 / 22 类用例（验收由 21 类扩充为 **23 类**：12 项目形态 + 9 步骤级安全 + 2 暂存副本安全） |
| 19 | R4 的「哈希计算范围」把 `transaction.json` 写成「一律不纳入」的目标哈希排除项，未区分「不在范围内」与「按文件名排除」；`payload/` 内误含 `transaction.json` 的处理、`.migration_tmp/` 的排除方式、哈希前置检查均未固定 | §3.4.2「哈希计算范围」重写：目标哈希范围 = `payload/` 内**完整项目树**（`transaction.json` 在父目录、**结构上不在范围内**，不以文件名排除实现）；`payload/` 内出现 `transaction.json` → **结构非法**（`RECOVERY_REQUIRED`），不得按文件名排除绕过；`.migration_tmp/` **只按明确相对路径** `payload/.migration_tmp/` 排除，禁止文件名通配；新增「目标哈希计算规则」6 条与「payload 目录结构合法性检查」5 项（哈希前执行）；§5.1 第 **23** 类用例扩为 4 个断言点（父目录修改不影响 / payload 内出现即非法 / 用户同名 `*.tmp` 被计入 / 仅相对路径排除） |

---

## 1. 迁移总原则与红线

### 1.1 总原则

1. **用户数据零丢失**：所有已有项目可原样打开；迁移失败必须保留原文件。
2. **先备份后迁移**：迁移前整项目复制到项目外备份目录，迁移只写新副本。
3. **可回退**：迁移后保留 V2 结构可被旧版本重新读取（至少到 V3 首个稳定版）。
4. **按 ID 关联，不按 index**：迁移时一律使用 `shot_id` / `scene_id`。
5. **自动迁移最小化**：能「读时兼容」就不「写时转换」；写盘必须用户显式确认。
6. **不静默继续**：任何异常都必须显式报告并停下，不得猜测、不得补空、不得忽略。
7. **测试先行**：每种项目形态都有迁移用例。

### 1.2 前置红线

| 编号 | 缺陷 | 影响 | 状态要求 |
| --- | --- | --- | --- |
| **K-01** | `_normalize_story` 捕获异常后 `data.pop("story")`（[project_manager.py:444-466](../../../modules/project_manager.py#L444-L466)），`open_project` 随即写盘（[225-226](../../../modules/project_manager.py#L225-L226)） | **打开即永久丢失 story** | **必须在 V2.3 独立补丁中修复，并通过回归测试后，才允许执行 V2→V3 迁移** |
| K-02 | `import_story` 四次独立写盘（[main_window.py:1151](../../../modules/main_window.py#L1151)） | 导入中断产生混合状态 | P0 修复：事务式暂存提交，失败保留原项目状态 |
| A-05 | `_sync_timeline_to_story` 按 index 对齐（[project_manager.py:689](../../../modules/project_manager.py#L689)） | 素材错位 | P0 增加**只读检测**告警；V3 迁移按 shot_id 关联 |
| A-03 | `set_story` 每次都存正式版本（[project_manager.py:488](../../../modules/project_manager.py#L488)） | 10 版额度被稀释 | P0 版本增加 `source` 标记 |

### 1.3 K-01 如何阻塞迁移（明确规则）

```
[迁移入口]
   ↓
检查 K-01 修复状态：
  - 代码层：_normalize_story 失败路径不再 data.pop("story")
  - 测试层：存在回归用例「story 结构异常时打开项目，story 原样保留」
   ↓ 未满足 → 直接拒绝执行迁移，提示「请先升级到含 K-01 修复的 V2.3」
   ↓ 已满足
继续迁移流程
```

> **原因**：迁移本身会触发故事读取与 schema 升级。若 K-01 仍在，迁移期间遇到损坏 story 会被静默清空，用户以为「迁移成功」，实际数据已丢。

#### 1.3.1 `assert_p0_fixed()` 的检查清单

`assert_p0_fixed()` **不是版本号判断**。它是迁移入口在**任何写操作之前**必须通过的运行时检查，逐项检查下列 6 项，任一项不满足即拒绝迁移：

| # | 检查项 | 检查方式 | 不满足时 |
| --- | --- | --- | --- |
| C1 | 当前应用具备经过验证的迁移能力版本 | 应用构建号 / 能力清单中声明 `migration_capability >= 1`，且该声明与代码中的迁移器版本常量一致 | 拒绝迁移：提示应用版本不支持迁移 |
| C2 | K-01 对应的安全能力**实际实现**，而不只是版本号更高 | 运行时探测：对一份构造的「story 结构异常、整体升级将失败」的内存样本调用 `_normalize_story`（只在内存中，不触碰任何用户文件），断言返回结果中 story 仍存在 | 拒绝迁移：`K01_GUARD_MISSING` |
| C3 | K-01 回归测试证据存在 | 发布构建随包携带 `p0_verification.json`（由 P0 验收时测试套件产出：测试名、时间、结果、被测代码指纹）；运行时只校验其完整性（存在、结果全绿、指纹与当前安装的 `project_manager` 文件哈希一致） | 拒绝迁移：`P0_EVIDENCE_MISSING` |
| C4 | 当前迁移路径不会在升级失败时删除 Story | 静态断言：迁移器自身不调用任何移除 `story` 字段的路径；迁移分派（§3.2）在 story 异常时只做「复制到暂存区 + 标记」，不做写回 | 拒绝迁移：迁移器完整性校验失败 |
| C5 | 迁移前能够完成原始项目备份与校验 | 运行时预检：暂存目录、备份目录可创建且可写；磁盘剩余空间 ≥ 原项目大小 × 2.2；备份完整性校验函数可用 | 中止：不进入任何写操作 |
| C6 | 迁移执行期间具备事务日志与恢复机制 | 事务日志模块可加载；日志写入原子性自检（写一次探针记录并回读）；启动恢复入口已注册 | 拒绝迁移：`TRANSACTION_LOG_UNAVAILABLE` |

#### 1.3.2 两个阶段的区分

| 维度 | 开发测试阶段的 P0 验收 | 正式迁移时的运行时安全检查 |
| --- | --- | --- |
| 执行者 | 开发者 / 测试人员 | 每个用户每次迁移 |
| 内容 | 运行完整测试套件：K-01 回归用例、K-02 暂存提交用例、A-05 只读检测、A-03 来源标记、309 个原有用例 | 只执行 §1.3.1 的 C1~C6 |
| 结果形式 | 测试报告 + 生成 `p0_verification.json`（含被测代码指纹） | 逐项布尔结果；失败项写入迁移报告 |
| 频率 | P0 交付时一次；P0 代码变更时重跑 | 每次迁移入口执行（毫秒级） |

硬规则：

1. **不得在每次用户迁移时运行整个测试套件**（慢、依赖测试环境、可能修改临时文件）。
2. **不得仅通过修改版本号绕过检查**：C2 是行为探测、C3 校验 `p0_verification.json` 中的代码指纹，两者都不依赖版本号文本。
3. C2 的探测样本在内存中构造，**不读取、不写入任何用户项目文件**；探测失败本身就是拒绝迁移的理由。
4. `assert_p0_fixed()` 的检查结果写入 `migration_report.json`，供事后审计。

---

## 2. 迁移分期

| 期 | 名称 | 内容 | 出口标准 |
| --- | --- | --- | --- |
| **P0** | V2.3 数据安全补丁 | K-01 / K-02 / A-05 只读检测 / A-03 来源标记 + 回归测试 | 新增回归用例全绿；309 原有用例不回归；**独立于 V3 发布** |
| P1 | 基础架构 | Repository 接口、原子写入、任务状态、基础测试 | 行为等价（快照测试）；无格式变更 |
| P2 | 故事数据层 | Story / Character / Relationship / WorldSetting / PlotEvent / KnowledgeState / 多 Story | 实体 CRUD + 引用完整性用例 |
| P3 | Scene/Shot 实体化 | SceneRepository / ShotRepository / ShotVersion / AssetRegistry / 迁移器 | 项目可往返读取；orphan 保留；素材零错位 |
| P4 | AI Provider | ProviderRegistry / DeepSeek / OpenAI / 统一请求响应 / UsageLedger / 并发与成本 | 业务层无模型名；Mock Provider 测试 |
| P5 | PromptStore + ContextEngine | Prompt 版本 / ContextBundle / Token 预算 / 三层信息 / 冲突测试 | 五阶段生成结构不变；T1~T11 场景测试通过 |
| P6 | 审核与工作流 | WorkflowEngine / ReviewRecord / 门禁 / 冻结 / 退回 / 依赖失效 | 状态机测试；不可越级；审核只追加 |
| P7 | 质量体系与题材包 | AI 独立审核 / 多模型比较 / HorrorPack / GenrePack 抽象 | 审核独立于 writer；HorrorPack 行为等价 |
| P8 | UI 适配 | 工作台 / 故事编辑 / 人物中心 / 世界观中心 / 审核中心 / 镜头管理 / 模型对比 | 自动冒烟通过；旧项目可直接打开 |
| P9 | 短剧生产 | 图片 / 视频 / 配音 / 音效 / 后期 / 导出 / 最终审核 | 单集可完整产出 |

> 与 Stage 0 初版 P0~P8 的对应关系及依赖图见 [开发路线](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md)。

---

## 3. 数据迁移详细设计（P3）

### 3.1 版本判定矩阵（重写）

打开项目时的**只读**判定：

| `project.json` 状态 | 判定 | 行为 |
| --- | --- | --- |
| 不存在 | 无效项目 | 明确报错；**不创建空项目** |
| `schema_version` 缺失 | 兼容检查 | 进入「兼容检查」流程：尝试 V2 既有 upgrade 路径；结果写入迁移报告，**不自动猜测为 V3** |
| `schema_version` 为非数字 / 类型异常 | 兼容检查 | 同上 |
| `schema_version == 1`（历史版本） | 先走 V2 既有 upgrade，再重新判定 | 升级后必须重新读到 `2` |
| `schema_version == 2` 且无 `story/` | **需要 P3 迁移** | 提示用户确认后执行迁移 |
| `schema_version == 2` 且有 `story/` | **仍按 V2 处理**（不认为是 V3） | 记录警告「存在 V2 意外文件」，不自动升级 |
| `schema_version == 3` 且结构完整 | V3 项目 | 正常打开 |
| `schema_version == 3` 且结构不完整 | **损坏** | 只读打开 + 明确报错，不修复写入 |
| `schema_version > 3` | **未来版本** | **只读打开，禁止写回**；UI 明确提示 |

硬规则：

- **禁止**出现「`schema_version=2` 却被识别为完整 V3 结构」的逻辑。版本号是唯一权威判定依据，`story/` 目录的存在只能作为**冲突告警**，不能提升版本判定。
- 未来版本打开时，所有保存类操作必须被拦截（`ProjectStore.save` 层校验）。

### 3.2 Story 形态分派（重写）

| V2 story 状态 | 迁移行为 |
| --- | --- |
| `story` 缺失 | **保留原始字节，不创建空 Story，不静默继续**。步骤：① 检查 `versions/` 是否存在可用快照 → 有则提示可恢复，迁移暂停等待用户选择；② 无快照 → 将项目标记为 `needs_manual_review`，**不写任何 V3 结构**，迁移报告中列出 |
| `story` 结构异常（`upgrade_story` 抛错） | **保留 story 原文**（复制到项目外暂存区的 `raw/`），标记 `needs_manual_review`，不写回原项目；用户确认「以原文迁移」后才能继续 |
| 正常 | 直接转换为实体 |

> 与 Stage 0 初版的区别：不再自动 `recovered_from_missing` 生成空 Story —— 那等于用空内容替换丢失的现实，违背「不静默继续」。

异常 Story 的人工恢复流程（Stage 0.6 补充，审查问题 1）：

| 项 | 规则 |
| --- | --- |
| 默认路径 | 异常 Story **默认进入人工恢复流程**，迁移器不自动「修复」任何 Story 内容 |
| 原始数据 | 在进入人工流程前，原始 `project.json` 已复制到项目外 `.backups/`（迁移前的整项目备份），并在暂存区 `raw/story.json` 保留一份逐字节原文；两处都必须通过哈希校验 |
| 从历史版本恢复 | 允许尝试从 `versions/` 快照恢复，但必须：① 在报告中记录**来源版本文件**（文件路径 + 哈希 + 版本时间）；② 记录**恢复结果**（成功/部分成功/失败与原因）；③ 恢复结果同样作为待确认内容呈交给用户，不直接视为已审核 |
| 无法恢复 | 项目标记为 `needs_manual_review`（异常状态），UI 明确显示；不以任何形式伪造内容补位 |
| 有损或不完整恢复 | **只有用户明确确认后**才允许执行；确认对话框必须列出将丢失或改变的内容；确认记录写入口头无法再现的审计日志（见下一行） |
| 审计记录 | 所有恢复动作（尝试、选择、结果、用户确认）追加写入 `migration_report.json` 的 `recovery_audit[]`：`{time, actor, action, source, result, note}`；审计记录只追加，不修改 |

```jsonc
// migration_report.json 中异常 Story 的审计片段（示意）
{
  "project": "MyStory",
  "status": "needs_manual_review",
  "story": {
    "state": "STRUCTURE_ERROR",
    "raw_copy": { "staging_raw": ".migration_staging/<tx_id>/payload/raw/story.json",
                  "sha256": "<hash>" },
    "recovery_audit": [
      { "time": "<iso>", "actor": "system", "action": "snapshot_scan",
        "source": "versions/v0003.json", "result": "candidate_found" },
      { "time": "<iso>", "actor": "user", "action": "confirm_recover",
        "source": "versions/v0003.json", "result": "accepted",
        "note": "用户确认以快照恢复，损失快照之后的人工修改" }
    ]
  }
}
```

> 说明：JSON 示例中的字段为设计约定，**当前代码中尚未实现**（见 [冻结基线 §12 未实现功能](V3_STAGE0_6_FINAL_BASELINE.md#12-明确标注尚未实现的功能)）。

### 3.3 实体转换规则

| V2 字段 | V3 实体 | 规则 |
| --- | --- | --- |
| 整个项目（单 story） | `Story` | 由项目名派生 `story_id`（稳定生成规则写入报告） |
| `story.concepts[]` | Story.ideas | 原样保留 |
| `story.plan` | Story.outline | 原样保留 |
| `story.characters[]` | Character | 保留 `character_id`；`scene_ids` → `scene_refs` |
| `story.scenes[]` | Scene | 保留 `scene_id` |
| `story.script[]` | Story.script | P2 阶段先保留在 Story 内，不拆分 |
| `story.shots[]` | Shot | `revision` → `version`；`script_segment_id` 保留 |
| `project.shots[]`（时间轴） | 合并进 Shot | 按 `shot_id` 对齐；`image/ai_image/voice` → `assets[]` |
| `project.shots[].id` | `legacy_timeline_id` | 用于回滚与 UI 兼容 |
| `project.shots[].story_index` | 丢弃 | 迁移报告中记录使用情况（诊断用），不再承担关联职责 |
| `versions/*.json` | StoryVersion | 补 `scope=story`、`source`（无法判定时标 `import` + `source_unknown=true`） |
| `settings` | Project.settings | 原样 |

### 3.4 迁移事务模型（Stage 0.6 修订：逐步骤可恢复提交日志）

#### 3.4.1 目录布局（项目外暂存与备份）

```
<Projects 根目录>/
├─ MyStory/                          ← 被迁移的项目
├─ .migration_staging/
│  └─ <tx_id>/                       ← 一次迁移事务一个目录（tx_id 唯一）
│     ├─ transaction.json            ← 事务元数据（日志本体，不属于被迁移的项目内容）
│     └─ payload/                    ← STAGE_COPY 复制与校验的唯一目标
│        ├─ raw/                     ← 异常 Story 原文（§3.2，如适用）
│        └─ ...                      ← V3 转换后的完整项目副本
└─ .backups/
   └─ MyStory-v2-<ts>/               ← 迁移前备份（V2 原样）
```

**事务日志与暂存副本物理隔离（Stage 0.6 终审补充 R4）**：

| # | 规则 |
| --- | --- |
| 1 | `transaction.json` 是独立事务元数据，**不属于被复制的 V2 项目内容**；任何步骤都不得把它复制进 `payload/`，也不得把它纳入 payload 树哈希 |
| 2 | `STAGE_COPY` 只负责复制与校验 `payload/`（`raw/` 与 V3 转换产物都在 `payload/` 之内） |
| 3 | `STAGE_COPY` 的 `expected_source_hash` = 原项目树的规范化树哈希；`expected_target_hash` = `payload/` 树的规范化树哈希（见「哈希计算范围」） |
| 4 | 删除不完整暂存副本时，**只允许删除 `payload/`**；`transaction.json` 一律保留，直到迁移完成或安全回滚 |
| 5 | 事务日志必须保留到迁移完成（`CLEANED`）或安全回滚（`ROLLED_BACK`）；`transaction.json` 的删除只发生在 `CLEANED` 收尾（见阶段 5） |
| 6 | 启动恢复扫描按「`transaction.json` / `payload/`」两种存在性识别 4 种形态（§3.4.3 扫描形态表） |
| 7 | `transaction.json` 自身原子写入失败 → **禁止开始 `STAGE_COPY`**，迁移中止且不写任何项目文件 |
| 8 | 以上规则**不削弱**「`MOVE_TREE` 不得移动原始 V2 文件」与「原始 V2 文件全程保留」的要求（§3.4.2 硬限制） |

规则：

1. 暂存目录与备份目录**必须位于被迁移项目目录之外**。
2. 迁移器启动时计算 `staging_root.resolve()` 与 `project.resolve()`，校验 **`project` 不是 `staging_root` 的父目录、也不是其子目录**；相反方向同理。任一校验失败立即中止。
3. 复制源扫描时跳过 `.migration_staging/` 与 `.backups/`，避免递归复制。
4. 若 `Projects 根目录`不可写（如项目位于盘符根），暂存目录回退到系统临时目录，并在报告中注明（备份仍优先放在项目外的同级目录）。

#### 3.4.2 提交协议（承认非原子，逐步骤记录）

Stage 0 初版把「replace project.json + rename story/」描述为一个原子提交，这是**错误的**：文件系统层面多个 rename 之间存在可观测的中间态。Stage 0.5 引入「提交日志 + 启动恢复」，但只记录**事务级**状态（PREPARED → BACKED_UP → COMMITTING → COMMITTED），无法判断中断时**具体哪个文件操作已完成**。Stage 0.6 改为**逐步骤事务日志**。

##### 迁移过程（6 个阶段，7 类步骤；Stage 0.6 终审修订：事务日志先于暂存副本建立）

```
阶段 0  预检（只读，不是事务步骤）
  - 身份核验、schema_version 判定、assert_p0_fixed()（§1.3）、路径边界检查、目标路径冲突检查（§3.4.4）
  - 任一项失败 → 中止，不写任何文件

阶段 0.5  初始化事务日志（终审新增：先于暂存副本）
  - 预检通过后创建 .migration_staging/<tx_id>/，并在该目录内原子写入 transaction.json（state=OPEN，steps 含 STAGE_COPY 在内的全量预生成清单）
  - transaction.json 与 payload/ 同级、相互独立；日志原子写失败 → 中止，禁止开始 STAGE_COPY
  - 事务记录建立**早于任何复制动作**；从这一刻起迁移全程有日志可依

阶段 1  生成暂存副本（步骤类型 STAGE_COPY，事务内第一步）
  - 先持久化 STAGE_COPY 的 INTENT（源 = 原项目树哈希，目标 = .migration_staging/<tx_id>/payload/ 树哈希），再执行复制
  - 复制完成后按 payload/ 树哈希校验，校验通过才记 COMPLETED
  - 整项目复制到 <Projects>/.migration_staging/<tx_id>/payload/，在 payload 内转换：生成 story/ 结构、实体 JSON、index.json
  - transaction.json 不参与复制、不属于 payload、不纳入任何 payload 哈希
  - 原项目此时**零写入**

阶段 2  全量校验（只读）
  - 实体数量 / ID 双向核对 / 引用完整性 / 镜头素材映射 / 反序列化
  - 前置条件：STAGE_COPY 必须为 COMPLETED；不完整暂存副本不得进入本阶段（见 §3.4.6）
  - 任一项失败 → 删除 payload/（保留 transaction.json），原项目不动，输出差异清单

阶段 3  备份（BACKUP 步骤）
  - 原项目整体复制到 .backups/<name>-v2-<ts>/
  - 备份完整性校验（文件数、字节数、关键文件哈希）
  - 失败 → 事务 ROLLED_BACK，删除 payload/（transaction.json 保留至收尾），原项目不动

阶段 4  提交（逐步骤执行，每步都写日志）
  - MKDIR / PLACE_FILE / PLACE_TREE / MOVE_TREE / REWRITE_PROJECT_JSON，见下表
  - 每个步骤严格执行「写 INTENT → 执行 → 验证 → COMPLETED」
  - 提交期间**不删除原始 V2 文件**（project.json 是 replace 而非删除后新建）

阶段 5  收尾（FINALIZE 步骤）
  - 写 migration_report.json（在项目目录内）
  - 事务标记 COMMITTED 后清理暂存区（CLEANED）：先删 payload/，最后删 transaction.json；任一步失败则保留日志，下次启动提示再次清理
```

> 阶段编号说明：Stage 0.5/0.6 初版的「阶段 3 初始化事务日志」已前移为阶段 0.5，原阶段 4~6 相应前移为 3~5；覆盖内容与步骤总数不变。

##### 步骤类型

| 操作类型 | 含义 | 幂等实现要点 |
| --- | --- | --- |
| `STAGE_COPY`（终审新增） | 把原项目整树复制到项目外暂存区 `.migration_staging/<tx_id>/payload/`，**事务内第一步**；只复制与校验 `payload/` | 先写 INTENT（含源树哈希）再复制；目标不存在 → 执行；目标存在且 payload 树哈希 = `expected_target_hash` → 已完成（补记 `COMPLETED`）；目标存在但哈希不符（不完整副本）→ **不补记、不合并**，按 §3.4.6 处置 |
| `BACKUP` | 整项目复制到 `.backups/` 并校验 | 目标已存在：校验哈希一致 → 视为已完成；不一致 → 人工处理 |
| `MKDIR` | 在项目目录内创建目标目录 | 已存在且是目录 → 视为已完成；已存在且是文件 → 冲突，人工处理 |
| `PLACE_FILE` | 把暂存区单个文件放到目标位置（`project.json` 除外） | 源**必须是已验证的暂存区内容**；目标已存在：若哈希等于 `expected_target_hash` → 已完成；否则冲突，人工处理 |
| `PLACE_TREE` | 把暂存区某个目录树整体放到目标位置（先写入临时目录 `.migration_tmp/<step_id>/`，再 rename 到位） | 源**必须是已验证的暂存区内容**；同上，按树哈希比较 |
| `MOVE_TREE` | **只允许移动「已通过 `STAGE_COPY` 校验的暂存区目录」到项目外的授权位置**（例如把暂存区中已完成转换的子树就位到另一个暂存子目录）；**不得移动原始 V2 文件** | 源不存在但目标存在 → 已完成；两者都存在 → 比较哈希；源位于原始项目目录内 → **拒绝执行**（`RECOVERY_REQUIRED`，报错「不允许移动原始 V2 文件」） |
| `REWRITE_PROJECT_JSON` | 写 `project.json`（`schema_version=3`）：先写 `.part` 后 `replace`（原文件先备份到 `.backups/`） | 当前已是 V3 且内容哈希等于 `expected_target_hash` → 已完成；仍为 V2 → 重试 |

**`MOVE_TREE` 的硬限制（Stage 0.6 终审）**：

1. 只允许移动**经过验证的暂存内容**（源路径必须在 `.migration_staging/<tx_id>/payload/` 之下且该步 `STAGE_COPY` 已 `COMPLETED`；`transaction.json` 不在可移动范围内）。
2. **不允许移动原始 V2 文件**；原始 V2 文件在整个迁移过程中必须保留（回滚依据、V2 兼容期依据）。
3. 需要在原项目内做任何「移动 / 重命名旧目录」行为时，必须有**独立授权**（用户显式确认）与**独立恢复机制**（可逐步撤销），默认**不实现**。
4. 执行前做源路径归属校验；校验失败的步骤进入 `RECOVERY_REQUIRED`，不执行移动。

> 具体步骤清单由迁移设计在 P3 定稿；本表只固定**操作类型与幂等语义**，不固定步骤数量。

##### 哈希计算范围（Stage 0.6 终审补充 R4；最终核验修订：哈希边界）

| 项 | 计算范围 | 明确不包含 |
| --- | --- | --- |
| `STAGE_COPY.expected_source_hash` | 原项目目录树的规范化树哈希（按相对路径排序、逐文件 SHA-256 汇总） | 仅排除位于项目树内可识别的**根级**派生目录 `.migration_staging/`、`.backups/` 与根文件 `migration_report.json`（尚未生成） |
| `STAGE_COPY.expected_target_hash` | `.migration_staging/<tx_id>/payload/` 内的**完整项目树**的规范化树哈希（按相对路径排序、逐文件 SHA-256 汇总） | **`transaction.json` 不参与计算——因为它在 `payload/` 的父目录，结构上就不在哈希范围内**；另按**明确的相对路径**排除 `payload/.migration_tmp/`；**不做任何按文件名的通配过滤** |
| 其它步骤 | 沿用下方步骤记录字段中的定义 | — |

**目标哈希的计算规则（最终核验修订，6 条）**：

| # | 规则 |
| --- | --- |
| 1 | 哈希范围 = `.migration_staging/<tx_id>/payload/` 内的完整项目树；范围边界由**目录**决定，不由文件名决定 |
| 2 | `transaction.json` 位于 `payload/` 的**父目录**，不属于目标哈希；计算 payload 哈希时**无需也不得**对它做任何排除判断（忽略 `transaction.json` 的文件名不是哈希逻辑的一部分） |
| 3 | `payload/` 内若出现 `transaction.json` → **目录结构非法**：计算哈希前先做结构合法性检查（规则 5），检出即判定 `RECOVERY_REQUIRED`（报错「payload 结构非法：不允许包含 transaction.json」），**不得**按文件名排除后照常计算哈希 |
| 4 | `.migration_tmp/` **只按明确的相对目录路径** `payload/.migration_tmp/` 排除；禁止使用 `*.tmp`、`*.part`、`tmp*` 等文件名通配或宽泛过滤（会误排除用户项目中的同名文件） |
| 5 | **哈希计算前先执行 payload 目录结构合法性检查**，通过后才计算树哈希；检查不通过即停止，不产生 `COMPLETED` |
| 6 | 结构合法性检查须自身也做**绝对路径**校验（对 `payload/` 根做 `resolve()` 后确认），防止符号链接 / 路径穿越让范围越过 `payload/` 边界 |

**payload 目录结构合法性检查（哈希前置，5 项）**：

| # | 检查项 | 不通过时 |
| --- | --- | --- |
| 1 | `payload/` 存在且是目录 | 结构非法 → `RECOVERY_REQUIRED` |
| 2 | `payload/` 下**不得出现** `transaction.json`（任何层级） | 结构非法 → `RECOVERY_REQUIRED`，**不得**用文件名排除绕过 |
| 3 | 除 `payload/.migration_tmp/` 外，不得存在其它事务元数据文件（如 `transaction.json` 的原子写残留 `transaction.json.part` / `transaction.json.tmp`）；**按具体文件名逐个判断，不做通配匹配**，用户项目自身的 `*.tmp` / `*.part` 文件合法且必须计入哈希 | 结构非法 → `RECOVERY_REQUIRED` |
| 4 | `payload/` 下的所有条目（解析符号链接后）都位于 `payload/` 之内 | 结构非法 → `RECOVERY_REQUIRED` |
| 5 | 检查通过 → 按「目标哈希计算规则」计算；检查结果写入步骤记录 `note` 字段，供审计 | — |

规则：`transaction.json` 的任何更新（含恢复记录 `recovery[]`）都**不得**改变 payload 树哈希的判定结果；校验 payload 时只读取 `transaction.json`，不把它当作 payload 的一部分。

##### 步骤记录字段

每个步骤在 `transaction.json` 的 `steps[]` 中占一条记录：

| 字段 | 含义 |
| --- | --- |
| `step_id` | 稳定步骤 ID（如 `S05`），创建事务时预生成，重试时不变化 |
| `operation` | 上表的操作类型之一 |
| `source_path` | 源路径（相对项目根或相对暂存区根，报告中注明基准） |
| `target_path` | 目标路径 |
| `expected_source_hash` | 执行前源对象的哈希（文件 SHA-256；目录为规范化树哈希） |
| `expected_target_hash` | 执行后目标对象应有的哈希 |
| `state` | 见下表 |
| `started_at` / `completed_at` | ISO 8601 时间，未发生为 `null` |
| `error` | 失败原因（错误类型 + 消息 + 相关 WinError），无则 `null` |

可选补充字段（便于恢复）：`attempts`（已尝试次数）、`verified_by`（验证方式：文件哈希 / 树哈希 / 结构化比对）、`note`。

##### 步骤状态与转移

| 状态 | 含义 | 允许的下一状态 |
| --- | --- | --- |
| `PENDING` | 尚未开始 | `INTENT_RECORDED` |
| `INTENT_RECORDED` | 已持久化「即将执行什么、期望结果是什么」，**文件操作尚未开始** | `EXECUTING` / `FAILED` |
| `EXECUTING` | 文件操作进行中（进程若在此状态终止，恢复时必须按实际文件状态判定） | `COMPLETED` / `FAILED` / `RECOVERY_REQUIRED` |
| `COMPLETED` | **已验证**目标结果符合 `expected_target_hash` | —（终态） |
| `FAILED` | 操作失败且已确认未产生不可判定的副作用 | `INTENT_RECORDED`（仅当恢复判定为「可安全重试」） |
| `RECOVERY_REQUIRED` | 自动恢复无法得到确定结论，需要人工介入 | 仅由人工处理写入结论（`COMPLETED` 或 `ROLLED_BACK`） |

事务级状态（`transaction.state`）由步骤状态派生，不独立推进：

| 事务状态 | 派生条件 |
| --- | --- |
| `OPEN` | 已初始化（阶段 0.5），尚无步骤进入 `INTENT_RECORDED`；此时**尚未复制任何内容**，放弃无成本 |
| `RUNNING` | 任一逐步状态处于 `INTENT_RECORDED` / `EXECUTING`（含 `STAGE_COPY` 进行中） |
| `COMMITTED` | 全部步骤为 `COMPLETED` |
| `ROLLED_BACK` | 备份存在且项目目录已恢复为迁移前状态（回滚后运行校验）；若备份尚未建立，则为「放弃未开始的迁移」 |
| `RECOVERY_REQUIRED` | 任一步骤处于 `RECOVERY_REQUIRED`（含暂存副本不完整且无法自动重建） |
| `CLEANED` | `COMMITTED` 之后暂存区已清理 |

##### 六条硬规则（对应审查意见 1.1）

1. **先持久化 INTENT，再执行文件操作。** 任何写入/移动前（**包括第一类复制动作 `STAGE_COPY` 本身**），必须先把该步骤置为 `INTENT_RECORDED` 并原子落盘。
2. **文件操作完成后必须验证目标结果。** 验证方式：按 `operation` 重新计算目标哈希（文件 SHA-256 / 规范化树哈希），与 `expected_target_hash` 比较。
3. **验证成功后才能记录 `COMPLETED`。** 验证失败不得写 `COMPLETED`；写 `FAILED` 或 `RECOVERY_REQUIRED`。
4. **每一次状态更新都采用原子写入。** 写 `transaction.json.part` → `os.replace(part, transaction.json)`；崩溃时最坏只丢失这一次更新，不会产生半截 JSON。
5. **进程异常终止后，必须根据「日志 + 实际文件状态」共同判断下一步**，见 §3.4.3。
6. **不得仅根据日志状态推断文件操作已经完成。** 例如日志停在 `EXECUTING`，文件可能已完成也可能没有；必须实测。

##### 日志与文件始终可能不一致

由于规则 4 只能保证「日志文件本身不损坏」，**不能保证「日志最后一条与文件系统完全同步」**。因此任何恢复路径都以**实际文件状态为主、日志为辅**：日志告诉我们「当时准备做什么」，文件状态告诉我们「实际做到了什么」。

**明确声明**：阶段 4 不是数据库意义上的原子事务。它保证的是：

- 原项目在**任何时刻**都可从 `.backups/` 完全恢复；
- 每个步骤都能从日志得知「意图」，并可从文件状态得知「实际结果」，从而选择「重试 / 补记 / 回滚 / 人工」；
- 最坏情况下项目目录处于「V2 + 部分 V3 文件」的中间态，但**没有数据被删除**。

#### 3.4.3 启动恢复

##### 恢复入口

| 入口 | 扫描范围 | 行为 |
| --- | --- | --- |
| 应用启动 | 配置的 Projects 根目录下的 `.migration_staging/<tx_id>/`（逐目录检查 `transaction.json` 与 `payload/` 的存在性；若应用只配置了当前项目，则只检查当前项目） | 按「扫描形态」表分类，列出全部未完成事务，逐项给出「继续 / 回滚 / 人工处理」选项 |
| 用户直接打开单个项目 | 该项目关联的未完成事务（通过暂存区中的 `project` 绝对路径匹配；同时检查项目内 `.needs_manual_review` 标记） | **不允许按普通项目写入方式打开**；必须先恢复、回滚或进入人工处理状态 |
| 迁移入口再次被调用 | 同一项目 | 检测到已有未完成事务 → 不新建事务，进入恢复流程 |

规则：

1. 发现未完成事务时，项目在恢复完成（或明确放弃）之前**只读**。
2. 「放弃」不等于删除：放弃 = 事务标记 `ROLLED_BACK` 并从备份恢复项目（若已开始提交）。
3. 启动扫描本身**不修改**任何项目文件，只读取与展示。

##### 扫描形态（Stage 0.6 终审补充 R4：`transaction.json` 与 `payload/` 物理隔离）

| # | `transaction.json` | `payload/` | 识别 | 处置 |
| --- | --- | --- | --- | --- |
| 1 | 存在 | 不存在 | 事务已建立、复制未开始（或已删除待重建） | 按 `STAGE_COPY` 步骤状态继续（见下方暂存复制中断恢复表） |
| 2 | 存在 | 存在 | 复制已开始或已完成 | 按 payload 树哈希判定：一致 → 可补记；不一致 → 不完整副本：删除 `payload/` 后重建，**保留 `transaction.json`** |
| 3 | 存在 | 存在 | 日志尚未写入 `COMPLETED` | 与第 2 行同一判定路径：以实际文件为主、日志为辅；一致性成立才补记 `COMPLETED`（`verified_by=recovery_hash_check`） |
| 4 | 不存在 | 存在 | **孤儿暂存目录**（无事务元数据） | **不得被接受为有效迁移结果**；提示用户确认后删除（不自动删） |

> 启动扫描只读，不修改任何文件；任何删除动作都由显式恢复流程执行并写入 `recovery[]`。

##### 按实际状态判定的恢复动作表

对每个未完成的步骤，比较 `expected_source_hash` / `expected_target_hash` 与实际文件：

| 实际状态 | 恢复策略 |
| --- | --- |
| 操作未开始（源存在且哈希 = `expected_source_hash`；目标不存在） | 可以安全重试：保持 `PENDING`，或从 `INTENT_RECORDED` 重新执行（等价于重写一次 INTENT 再执行） |
| 源存在，INTENT 已记录但操作未执行（日志 `INTENT_RECORDED`，目标仍不存在） | 验证源哈希后重试 |
| 操作已完成但日志未更新（目标存在且哈希 = `expected_target_hash`，日志停在 `INTENT_RECORDED` / `EXECUTING`） | **校验文件后补记 `COMPLETED`**（写 `verified_by=recovery_hash_check`），不重复执行 |
| 源和目标同时存在且内容冲突（目标存在但哈希 ≠ `expected_target_hash`） | **停止自动恢复**，进入 `RECOVERY_REQUIRED`，人工处理；不覆盖任何一方 |
| 源和目标均不存在 | 无法判断是否已执行或源已被破坏 → 进入 `RECOVERY_REQUIRED` |
| 校验失败（哈希计算失败、文件不可读、目录结构与预期不符） | **禁止继续提交**；事务进入 `RECOVERY_REQUIRED`；提供「从备份整体回滚」选项 |
| 备份本身缺失或校验失败 | 禁止自动回滚；进入 `RECOVERY_REQUIRED`，提示用户使用外部备份 / 手动处理 |

##### 暂存复制（`STAGE_COPY`）中断的恢复判定（Stage 0.6 终审新增）

事务在阶段 0.5 建立后，第一个步骤就是 `STAGE_COPY`。复制可能在任意时刻被中断（强杀、断电、磁盘满、文件占用）。**复制中断不涉及项目目录写入**，原项目始终不经本步骤被修改，因此恢复判定相对简单，但必须严格：

| 实际状态 | 恢复策略 |
| --- | --- |
| 日志 `PENDING`，`payload/` 不存在 | 尚未开始复制 → 从 `STAGE_COPY` 正常开始 |
| 日志 `INTENT_RECORDED`，`payload/` 不存在或为空 | 重写 INTENT 后重新复制 |
| 日志 `INTENT_RECORDED` / `EXECUTING`，`payload/` 存在且**树哈希 = `expected_target_hash`** | 复制实际已完成 → 补记 `COMPLETED`（`verified_by=recovery_hash_check`） |
| 日志 `INTENT_RECORDED` / `EXECUTING`，`payload/` 存在但树哈希**不符**（部分复制） | **不补记、不合并、不校验**：删除不完整 `payload/`（项目外派生副本，不承载用户独有数据；`transaction.json` 保留）→ 将步骤重置为 `INTENT_RECORDED` → 重新完整复制；若删除失败（占用）→ `RECOVERY_REQUIRED` 提示关闭占用后重试 |
| 原项目树哈希 ≠ 执行前的 `expected_source_hash`（复制期间原项目被外部修改） | **停止**：进入 `RECOVERY_REQUIRED`，提示「迁移期间原项目已被修改，请确认后重新开始迁移」；不得用不一致的副本继续 |
| 同一项目已存在另一个未完成事务 | 不新建事务（恢复入口 3），先处理既有事务 |

硬规则：**不完整暂存副本永远不得被后续校验 / 提交步骤接受**；`STAGE_COPY` 未 `COMPLETED` 时，阶段 2 及以后的所有步骤一律拒绝执行（见 §3.4.6）。

##### 恢复动作的两种终局

| 终局 | 条件 | 动作 |
| --- | --- | --- |
| 继续完成 | 全部未完成步骤都能判定为「可安全重试」或「已完成待补记」 | 按顺序重试剩余步骤；全部 `COMPLETED` 后事务 → `COMMITTED` → 收尾 |
| 回滚到备份 | 任一步骤处于 `RECOVERY_REQUIRED`，或用户选择回滚，且备份校验通过 | 用备份整体覆盖项目目录（同样走步骤化：先 INTENT，后执行，后校验），最后校验项目哈希 = 迁移前快照；事务 → `ROLLED_BACK` |

##### 恢复的幂等性

1. 恢复本身也通过 `transaction.json` 记录（`recovery[]` 数组：每次恢复尝试一条），**重复启动、重复执行恢复不会造成二次破坏**。
2. 每个恢复动作先判定「是否已做过」（检查目标哈希），再做；已做过的动作直接跳过。
3. 回滚时先把当前项目目录移动到项目外 `recovery_trash/`（而非直接删除），再覆盖备份；覆盖完成并校验通过后才清理 `recovery_trash/`。
4. 单元测试必须包含「恢复流程被中断，再次恢复」的场景（§5.1 第 18 类）。
##### 其它发现

| 发现 | 处理 |
| --- | --- |
| `transaction.json` 状态 `OPEN` / `RUNNING`，全部步骤 `PENDING`，且暂存目录不存在 | 项目目录未被修改，也未开始复制；提示「发现未完成的迁移，是否重试/放弃」 |
| `transaction.json` 状态 `OPEN` / `RUNNING`，全部步骤 `PENDING`（旧口径中事务日志晚于暂存建立时的残留形态） | 项目目录未被修改；若暂存目录存在，先按 `STAGE_COPY` 恢复判定处理暂存副本，再提示重试/放弃 |
| 事务 `COMMITTED` 但未 `CLEANED` | 提示「迁移已完成，清理暂存区」；清理前先校验项目哈希符合 `expected_target_hash`；清理顺序 = 先删 `payload/`、再删 `transaction.json` |
| 无 `transaction.json` 但存在暂存目录（含 payload） | 视为孤儿暂存，**不得被当作有效迁移结果**；提示用户确认后删除（不自动删）；不得为「救回」孤儿 payload 而反推创建日志 |
| 备份目录存在但项目目录正常 | 仅记录，不影响打开 |

#### 3.4.4 目标路径冲突（Stage 0.6 新增）

V2 项目目录中**可能已经存在** `story/` 目录（例如用户手工创建，或早期版本残留）。处理规则：

| 情况 | 处理 |
| --- | --- |
| 目标路径 `story/` 不存在 | 正常执行 `PLACE_TREE` |
| 目标已存在**空目录** | 允许合并：先 MKDIR 子目录，再 `PLACE_FILE` 逐个放置；每一步都校验哈希 |
| 目标已存在目录且包含文件 | **不允许直接覆盖**；对该目录做内容清单 + 文件哈希 + schema 检查（若含 JSON，逐文件读取并记录 schema_version 字段） |
| 内容检查通过（files 全部是本次迁移将生成且哈希一致） | 视为「上次未完成迁移留下的」→ 进入恢复流程，不重新迁移 |
| 内容检查不通过（存在任何无法解释的文件） | **停止迁移**，保留原始内容，报告列出冲突文件清单；**不删除、不覆盖、不重命名旧目录** |
| 目标是文件而非目录 | 停止迁移，报告冲突 |

硬规则：

1. **不允许通过删除旧目录来解决冲突。**
2. **无法证明目标目录安全时，停止迁移并保留原始内容**；由用户决定如何处置（迁移器不提供「强制覆盖」按钮）。
3. 冲突检查发生在阶段 0（预检），**早于任何写入**。
4. 检查结果写入迁移报告，作为审计证据。

#### 3.4.5 异常 Story 与事务的关系

异常 Story（§3.2）在事务开始前就被识别：

1. 预检阶段发现 story 缺失 / 结构异常 → **不创建事务**，只生成迁移报告与人工处理提示；
2. 暂存区可保留（含 `raw/story.json`），供人工分析；
3. 用户选择「从历史版本恢复」后，恢复得到的 story 视为**用户确认的输入**，重新从阶段 0 开始（新的 `tx_id`）；
4. 用户选择「有损迁移」时，迁移报告必须记录损失项，事务正常执行，但报告状态标记 `lossy=true`；
5. 全部动作进入 `recovery_audit[]`（§3.2）。

#### 3.4.6 不完整暂存副本的处置（Stage 0.6 终审新增）

**结论：不完整暂存副本不得作为有效迁移结果。** 规则如下：

| # | 规则 | 落地 |
| --- | --- | --- |
| 1 | **有效性判定唯一依据 = `STAGE_COPY` 步骤为 `COMPLETED` 且暂存区树哈希 = `expected_target_hash`**；缺一即视为不完整 | 阶段 2 入口硬校验；校验失败不得进入阶段 2 |
| 2 | 不完整暂存区**不得**用于：全量校验、备份、任何 `PLACE_FILE` / `PLACE_TREE` / `MOVE_TREE`、`REWRITE_PROJECT_JSON`、生成 `migration_report.json` 的「迁移成功」结论 | 各步骤执行前复检 `STAGE_COPY` 状态 |
| 3 | 不完整暂存区**不得**被「补写」成完整：不允许只复制缺失文件、不允许保留旧文件合并 | 只能整树重建 |
| 4 | 不完整暂存区**不得**被当作迁移中断的「部分成功」向用户呈现；迁移报告中明确标 `staging_incomplete=true` | 报告字段 |
| 5 | 处置方式：删除（项目外派生数据，可安全重建）→ 重置 `STAGE_COPY` → 重新完整复制；删除失败（占用）→ `RECOVERY_REQUIRED`。**删除范围只限 `payload/`，`transaction.json` 必须保留**（恢复与审计依据） | 见 §3.4.3 暂存复制中断恢复表、§3.4.1 R4 规则 4 |
| 6 | 若原项目在复制期间被外部修改（源哈希变化）→ 不重建，进入 `RECOVERY_REQUIRED` | 同上 |
| 7 | 孤儿暂存目录（无对应事务）同样不得被接受为有效结果 | §3.4.3「其它发现」 |

### 3.5 时间轴 shot 合并的边界情况

| 情况 | 处理 |
| --- | --- |
| `shot_id` 在 story 中存在 | 正常合并，素材挂 `assets[]` |
| `shot_id` 存在但 story 中已不存在 | 保留为 Shot，`source="orphan"`，`source_shot_kind="orphan_timeline_shot"`，scene 尽量从 `scene_id` 推断；无则归入「未关联」分组 |
| 无 `shot_id` | 保留为手工镜头，`source="manual"`，新生成稳定 id（规则写入报告） |
| 多个时间轴 shots 指向同一 `shot_id` | **全部保留**，标记 `duplicate_group=<shot_id>`，不自动去重，报告中列出 |
| story 有 shot 但时间轴无对应 | 正常：Shot 状态 `draft` |
| `shot_revision` / `content_hash` 与 story `revision` 不一致 | 取时间轴侧为 `version` 基准，差异写入报告 |
| 素材文件缺失（路径指向不存在文件） | 保留引用并标记 `missing_file=true`，不删除引用 |

### 3.6 Windows 异常处理

| 异常 | 检测 | 处理 |
| --- | --- | --- |
| 文件被其他进程占用（`WinError 32`） | rename / replace 抛 `PermissionError` | 中止提交，状态保持 `BACKED_UP`；提示关闭占用程序后重试 |
| 进程中断（断电 / 强杀） | 启动恢复扫描 `transaction.json` | 见 §3.4.3 |
| 暂存复制中断（`STAGE_COPY` 未 `COMPLETED`） | 按 §3.4.3 暂存复制中断判定表 | 删除不完整 `payload/`（保留 `transaction.json`）并重建；源已变化则 `RECOVERY_REQUIRED` |
| 磁盘空间不足 | 写入前检查可用空间 ≥ 原项目大小 × 2.2 | 提前中止，不进入阶段 1 |
| 路径过长（> 260 字符） | 提交前对全部目标路径做长度预检 | 中止并报告具体路径；不尝试自动缩短 |
| 备份写入失败 | 备份后做完整性校验 | 事务 `ROLLED_BACK`，只删 `payload/`（`transaction.json` 保留），原项目不动 |
| 提交中途部分 rename 成功 | `transaction.json` 的逐步记录 | 启动恢复时按 §3.4.3 恢复动作表处理：可安全重试则继续（幂等重做未完成项）、已完成则补记、冲突/不确定则回滚或人工 |

### 3.7 恢复到 V2 的路径

| 场景 | 操作 |
| --- | --- |
| 提交前失败（事务未进入阶段 4 / 无任何 `COMPLETED` 步骤） | 事务 `ROLLED_BACK`；删除 `payload/` 即可（`transaction.json` 保留至收尾），项目目录未被写入（若存在不完整暂存副本，按 §3.4.6 处置） |
| 提交中断后放弃 | 从 `.backups/<name>-v2-<ts>/` **步骤化**覆盖回项目目录（见 §3.4.3「回滚到备份」），覆盖后校验项目哈希 = 迁移前快照 |
| 提交完成后发现问题 | 同上覆盖；V2 旧程序可直接打开备份目录 |
| 批量迁移部分失败 | 逐项目按报告中的备份路径回滚，不影响其他项目 |

回滚也必须走**路径边界校验**，禁止把备份目录复制进自身。

---

## 4. 兼容策略

### 4.1 旧项目打开

- P0~P2 期间：V2 格式原样可打开（`ProjectStore` 读时兼容）。
- P3 之后：检测到 `schema_version=2` 且无 `story/` → 提示升级，用户确认后按 §3.4 执行。
- **不静默迁移**：任何写盘型迁移必须显式确认，失败不落盘。

### 4.2 新项目

新建项目直接使用 V3 结构，`schema_version=3`。

### 4.3 批量迁移

`batch.py` 逐项目调用迁移入口；单项目失败不影响其他项目，汇总报告。批量执行**默认不迁移**，需显式勾选。

### 4.4 备份保留

建议：**最近 3 次迁移备份或 30 天，二者取久**——需产品确认（见 §9 `OPEN QUESTION`）。

---

## 5. 迁移验收

### 5.1 必须通过的项目形态

| # | 形态 | 断言 |
| --- | --- | --- |
| 1 | 空项目（无 story、无 shots） | 不产生空 Story；报告标记；原项目不变 |
| 2 | 完整 V2 项目 | 实体数与 ID 一一对应；素材对齐 |
| 3 | story 缺失 | 不创建空 Story；原始字节保留；标记 `needs_manual_review` |
| 4 | story 结构异常 | 原文备份到项目外；不写回；标记 |
| 5 | orphan 时间轴镜头 | 保留且可打开 |
| 6 | 重复 shot_id | 全部保留并标记 |
| 7 | 素材关联 | 迁移前后每张图仍挂在同一 shot_id |
| 8 | 迁移中断（提交阶段注入异常，事务级） | 启动恢复可识别；可继续或回滚 |
| 9 | 迁移后回滚 | 备份覆盖后 V2 程序可读；项目字节级与迁移前一致 |
| 10 | 未来 schema_version（4） | 只读打开；写操作被拦截 |
| 11 | schema_version=2 但有 story/ | 按 V2 处理并告警，不识别为 V3 |
| 12 | 路径边界（暂存目录在项目内 / 项目在暂存目录内） | 预检失败，不执行任何写操作 |

Stage 0.6 补充的步骤级安全验收（审查意见 1.5）：

| # | 形态 | 断言 |
| --- | --- | --- |
| 13 | **每个步骤的中断测试** | 对每个 `operation` 类型至少各注入一次中断，注入点分别位于：INTENT 写入后 / 文件操作中 / 文件操作后但验证前 / 验证后但 COMPLETED 写入前；每次中断后启动恢复都能给出正确结论（继续 / 补记 / 回滚 / 人工），且原项目无未记录改动 |
| 14 | **每个步骤的重复执行测试** | 对已 `COMPLETED` 的步骤再次执行 → 检测到目标哈希一致 → 直接跳过，不重复写入、不报错、不改变文件 |
| 15 | **日志与文件系统状态不一致测试** | 手工构造 4 种不一致：日志 `INTENT_RECORDED` 但文件已就位 / 日志 `EXECUTING` 但文件未就位 / 日志 `COMPLETED` 但文件哈希不符 / 日志 `COMPLETED` 但文件不存在；恢复必须按实际文件状态修正记录，并输出差异报告 |
| 16 | **目标目录冲突测试** | 项目内已存在 `story/`（空 / 有文件 / 有无法解释文件 / 与预期一致）4 种情况；前三种停止迁移且原始内容不变，第四种进入恢复流程；不允许删除旧目录 |
| 17 | **Windows 文件占用测试** | 持有目标文件句柄（`PermissionError` / `WinError 32`），执行到对应步骤时：状态停在 `FAILED` 或 `RECOVERY_REQUIRED`，原项目未被破坏，关闭占用后可重试成功 |
| 18 | **恢复失败测试** | 备份损坏 / 备份缺失 / 回滚过程再次中断：不得进入「自动判定成功」；必须停在 `RECOVERY_REQUIRED`，并且恢复流程本身可再次执行而不会二次破坏 |
| 19 | **原始项目字节级不变测试** | 对第 1~18 类中所有「迁移失败 / 中止 / 回滚」场景，项目目录递归哈希（排除迁移过程中**合法新增**的目标文件，其清单从日志的 `COMPLETED` 步骤得出）必须与迁移前快照完全一致 |

Stage 0.6 终审补充（意见 2 / 3）：

| # | 形态 | 断言 |
| --- | --- | --- |
| 20 | **暂存复制中断测试** | 在 `STAGE_COPY` 的 4 个注入点（INTENT 后 / 复制中 / 复制后校验前 / 校验后 COMPLETED 前）分别强杀进程；重启后：完整性符合 → 补记 `COMPLETED` 继续；部分复制 → 只删 `payload/` 后重建（`transaction.json` 保留），**不合并、不补写**；原项目哈希始终不变；若原项目在复制期间被外部修改 → `RECOVERY_REQUIRED`，不得用不一致副本继续 |
| 21 | **不完整暂存副本拒绝测试** | 手工构造不完整 `payload/`（删除其中若干文件 / 损坏若干文件 / 无 `transaction.json` 的孤儿暂存）：阶段 2 入口校验必须拒绝，事务停在 `RECOVERY_REQUIRED` 或重置 `STAGE_COPY`；不完整副本**不得**产生任何 `COMPLETED` 提交步骤或「迁移成功」报告；报告标 `staging_incomplete=true` |

Stage 0.6 终审补充核验（R4，日志与暂存物理隔离）：

| # | 形态 | 断言 |
| --- | --- | --- |
| 22 | **事务日志 / 暂存副本隔离与扫描形态测试** | 构造 4 种形态：① `transaction.json` 存在、`payload/` 不存在；② `transaction.json` 存在、`payload/` 不完整；③ `payload/` 完整但日志未写入 `COMPLETED`；④ `transaction.json` 不存在的孤儿目录。每种形态启动扫描都能正确识别（§3.4.3 扫描形态表），且：删除不完整副本后 `transaction.json` 仍在；孤儿 payload 不被接受为有效结果；`transaction.json` 原子写失败时**不开始** `STAGE_COPY`、不写任何项目文件 |
| 23 | **哈希边界测试** | ① `transaction.json` 位于 `payload/` 父目录，在 `payload/` 不变的前提下修改它（如追加 `recovery[]` 记录）后，payload 哈希校验结果不变；② 若 `transaction.json` 被放进 `payload/`（任何层级），**结构合法性检查必须判为非法**（`RECOVERY_REQUIRED`），迁移器**不得**通过按文件名排除后继续校验成功；③ 在 `payload/` 中放入用户项目自身的 `*.tmp` / `*.part` 同名文件，哈希必须**包含**它们（证明未使用文件名通配过滤）；④ `payload/.migration_tmp/` 按相对路径被排除，其它位置同名目录不被排除 |

### 5.2 全部失败场景的统一断言

**所有迁移失败场景必须证明原始项目未被破坏**：

- 迁移前后对项目目录做递归哈希（排除 `migration_report.json` 与新建的 `story/`）；
- 对失败场景，哈希必须完全一致；
- 备份目录内容必须与迁移前快照完全一致。

### 5.3 质量判断标准（不止测试数量）

- **真实项目样本迁移**：使用已知 V2 项目副本（不进仓库）做端到端迁移，人工核对。
- **属性测试**：随机生成 story/shot 组合，验证「迁移 → 反序列化 → 再序列化」幂等。
- **架构测试**：import 方向扫描。

---

## 6. 测试迁移策略

### 6.1 V2 的 309 个测试

| 类别 | 处理 |
| --- | --- |
| `test_story_engine.py`（58） | 保留；AI 调用改为 mock Provider 后断言不变 |
| `test_project_manager.py`（46） | 存储层重构后改用新接口，**行为断言逐条保留** |
| `test_story_schema.py`（39） | 保留并扩展新实体 |
| `test_pacing.py` / `test_pipeline.py` / `test_render_engine.py` | 原样保留 |
| `test_batch.py` | 保留，补迁移失败隔离用例 |
| `test_horror_rules.py` | 保留，同时验证 HorrorPack 包装后规则等价（21 个测试作为证据） |
| `test_ai_media.py` / `test_story_panel_logic.py` | 保留 |

**禁止**为让测试通过而删除原有用例。

### 6.2 必须新增的测试

| 类别 | 用例 |
| --- | --- |
| 迁移 | §5.1 的 23 类（12 类项目形态 + 9 类步骤级安全 + 2 类暂存副本安全） |
| Repository | 每个接口的 CRUD + 引用完整性 + 原子写失败回滚 |
| 状态机 | 全部合法/非法状态转换 |
| ContextEngine | T1~T11（见 [目标架构 §7.7](V3_STAGE0_TARGET_ARCHITECTURE.md#77-必须覆盖的测试场景11-个)） |
| Provider | Mock Provider 全链路；独立性校验（reviewer ≠ writer） |
| 架构 | import 方向；禁止直接 `open()` 实体 JSON |
| GUI 冒烟 | 逐步增加自动化冒烟 |

---

## 7. 风险与对策

| 风险 | 级别 | 对策 |
| --- | --- | --- |
| K-01 未修就迁移，升级失败掩盖丢数据 | **高** | `assert_p0_fixed()` 六项运行时检查硬阻塞（§1.3.1），不依赖版本号文本 |
| 迁移中途崩溃留下半迁移目录 | 高 | 提交日志 + 启动恢复（§3.4.3） |
| 暂存目录位于项目内导致递归复制 | 高 | 路径边界校验（§3.4.1） |
| 用户回退到 V2 后打开 V3 项目 | 中 | 迁移报告给备份路径；README 明示 |
| 快照不含时间轴导致恢复错位 | 中 | P3 后快照覆盖 scenes/shots 的已审状态 |
| 10 版上限被迁移快照耗尽 | 中 | 迁移不生成正式版本，只生成草稿快照 |
| 大项目迁移耗时/卡 UI | 中 | 后台线程 + 进度；可中断且可恢复 |
| 迁移后旧测试失效掩盖回归 | 中 | 行为断言逐条保留，禁止删测试改通过 |
| Windows 文件占用导致提交卡死 | 中 | 明确中止 + 提示 + 可重试（§3.6） |

---

## 8. 迁移完成判定

P3 迁移器视为完成需同时满足：

1. §5.1 全部 23 类形态与安全场景通过；
2. 至少一个真实 V2 项目迁移后所有镜头素材正确显示；
3. 所有失败场景下原项目字节级未被修改；
4. 中断恢复演练成功（继续与回滚两种路径）；
5. `migration_report.json` 对所有异常项给出可读说明；
6. 路径边界校验有独立测试。

---

## 9. 待确认事项（统一编号）

本文件原有的 `OQ-M1 ~ OQ-M4` 已并入**统一 OPEN QUESTION 注册表**，不再使用独立编号（避免同一问题在不同文档出现不同编号）：

| 原编号 | 统一编号 | 问题 |
| --- | --- | --- |
| OQ-M1 | `OQ-05` | 备份保留时长与次数 |
| OQ-M2 | `OQ-07` | 迁移是否需要用户确认，还是允许首次打开自动迁移 |
| OQ-M3 | `OQ-06` | 单 story 项目的 `story_id` 派生规则 |
| OQ-M4 | `OQ-08` | 迁移后 V2 旧程序需继续可用多久 |

完整注册表（含影响范围、是否阻塞开发、需要谁决定、最迟决策阶段、当前状态）见 [Stage 0.6 冻结基线 §11 OPEN QUESTION 总表](V3_STAGE0_6_FINAL_BASELINE.md#11-open-question-总表)。

> 当前建议值（§4.4「最近 3 次或 30 天」等）只是**建议**，未经用户确认前不视为决定。
