# V3 STAGE 0.6 — V3.0 开发基线冻结（FINAL BASELINE）

日期：2026-11-05
状态：**Stage 0.6 终审修订版 + 终审补充核验 R4**（ChatGPT 最终审查结论 CONDITIONAL PASS；已按终审意见 1~6 完成定点修订，并按终审补充核验 R4 完成事务日志与暂存副本物理隔离的定点补充；待 ChatGPT 确认后生效为 V3.0 开发基线）
性质：冻结声明 + 索引。本文件**不另行定义**架构细节，细节以各专题文档为准；本文件负责判定「哪些内容已冻结、哪些仍未实现、哪些问题仍待决定」。

关联文档：

| 文件 | 职责 |
| --- | --- |
| [现有架构审计](V3_STAGE0_CURRENT_ARCHITECTURE_AUDIT.md) | V2 现状与缺陷证据 |
| [目标架构](V3_STAGE0_TARGET_ARCHITECTURE.md) | **数据模型、实体清单、工作流阶段表、Provider 槽位、ContextEngine 的唯一权威来源** |
| [迁移方案](V3_STAGE0_MIGRATION_PLAN.md) | 迁移安全、事务日志、`assert_p0_fixed()` 的唯一权威来源 |
| [执行摘要](V3_STAGE0_EXECUTIVE_SUMMARY.md) | 面向决策者的浓缩版 |
| [架构决策](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md) | AD-01 ~ AD-30 的决策与理由 |
| [MVP 范围](V3_STAGE0_5_MVP_SCOPE.md) | V3.0 交付项与暂缓项 |
| [开发路线](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md) | P0~P9 依赖与验收、真实端到端测试 E1~E10 |
| [修订报告](V3_STAGE0_5_REVIEW_REPORT.md) | Stage 0.5 / 0.6 / 0.6 终审 逐条修订记录与自检结果 |
| [ChatGPT 审查包](V3_STAGE0_6_CHATGPT_REVIEW_PACKET.md) | 供 ChatGPT 审查的完整架构报告（终审修订版 v2 + 终审补充核验 R4） |

---

## 1. Stage 0.5 审查意见处理结果（审查问题 1~9）

| # | 审查问题 | 处理结果 | 落地位置 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | 迁移事务恢复机制不够完整 | 改为**逐步骤事务日志**：每步 10 字段、6 状态；先 INTENT 后执行、验证后 COMPLETED、不得仅凭日志推断；恢复入口 2 个、按实际文件状态判定、恢复幂等；目标路径冲突规则；异常 Story 审计；验收 12 → 19 → 21 → 23 类（终审新增暂存副本 2 类；R4 新增日志/暂存隔离与哈希边界 2 类） | [迁移 §1.3 / §3.2 / §3.4 / §5.1](V3_STAGE0_MIGRATION_PLAN.md) | **已解决** |
| 2 | Provider 槽位缺少 `audio` | 明确 **9 个槽位**（新增 `audio`），`voice` 与 `audio` 分开；明确 `AUDIO` 是能力类型而非槽位；全文 8 → 9 统一 | [目标架构 §8.3](V3_STAGE0_TARGET_ARCHITECTURE.md#83-槽位stage-06-修订9-个)、[AD-16](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md#ad-16-九个槽位能力类型与业务槽位分离stage-06-修订) | **已解决** |
| 3 | 领域实体数量统计不统一 | 统一为 **12 个领域实体 + PromptTemplate 为创作基础设施对象**；按 **A/B/C 三类来源**统计；目标架构 §4.1 为唯一权威清单 | [目标架构 §4.1](V3_STAGE0_TARGET_ARCHITECTURE.md#41-实体清单12-个领域实体--1-个创作基础设施对象)、[AD-09](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md#ad-09-12-个领域实体--1-个创作基础设施对象stage-06-修订) | **已解决** |
| 4 | 13 个阶段与 9 个审核门禁不一致 | 重建**唯一阶段定义表**（13 阶段 × 9 字段）；明确 9 个门禁对应哪 9 个阶段；说明 `export` 为前置条件型门禁；6 条门禁硬规则 | [目标架构 §6.1.1~§6.1.4](V3_STAGE0_TARGET_ARCHITECTURE.md#611-唯一阶段定义表全文以此表为准)、[AD-12](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md#ad-12-九个审核门禁与-13-个阶段的唯一映射stage-06-修订) | **已解决** |
| 5 | `assert_p0_fixed()` 机制不明确 | 明确 **6 项运行时检查**（能力版本 / K-01 行为探测 / 回归证据与代码指纹 / 迁移器完整性 / 备份可用 / 事务日志可用）；区分 P0 验收与运行时检查 | [迁移 §1.3.1~§1.3.2](V3_STAGE0_MIGRATION_PLAN.md#131-assert_p0_fixed-的检查清单)、[AD-21](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md#ad-21-k-01-硬阻塞迁移) | **已解决** |
| 6 | OPEN QUESTION 编号与统计不统一 | 建立**统一注册表** `OQ-01 ~ OQ-09`；旧编号全部映射 | 本文件 §11 | **已解决**（问题本身仍 OPEN） |
| 7 | P9 与 P7/P8 并行关系不明确 | P9 依赖 **P3/P4/P6/P8**，**不与 P7/P8 并行**；「P9 预备工作」单独定义且不计入 P9 出口 | [路线 §2.1~§2.3](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md#23-p9-的真实位置与p9-预备工作) | **已解决** |
| 8 | Project 级共享资源与 Story 级数据边界不明确 | 新增 **§4.4 Project/Story 数据边界**（Project 级 5 类资源、Story 级 11 类数据、8 条边界规则、需调整的 5 条实体关系）；新增 AD-27 / AD-28 | [目标架构 §4.4](V3_STAGE0_TARGET_ARCHITECTURE.md#44-project-级共享资源与-story-级数据边界stage-06-新增) | **已解决** |
| 9 | 真实端到端测试要求不完整 | 新增 **E1~E10** 十条端到端验收 + 7 条执行规则 + 分阶段最小验收 | [路线 §3.4](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md#34-真实端到端验收stage-06-新增) | **已解决** |

> 说明：「已解决」指文档层面已给出明确、自洽的规定；**不代表代码已实现**（见 §12）。
> **Stage 0.6 终审补充**：ChatGPT 最终审查结论 CONDITIONAL PASS，提出 6 条定点修订意见（1 退回分级 / 2 事务日志先于暂存 / 3 MOVE_TREE 受限 / 4 E4 口径 / 5 A16.3 清理 / 6 共享资源审核归属），处理结果见本表下方「终审意见处理」与[修订报告 §4A](V3_STAGE0_5_REVIEW_REPORT.md#4a-stage-06-终审修订记录chatgpt-最终审查意见-1---6)。

---

---

## 1A. Stage 0.6 终审意见处理结果（ChatGPT 最终审查：CONDITIONAL PASS）

| # | 终审意见 | 处理结果 | 落地位置 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | `audio_prod` 的 `reject_target` 一律退回 `full_story` 不合理 | 通用规则：`reject_target` 降为**默认值**，按问题性质分级（执行层 → 本阶段；上游内容 → 经 `DependencyAnalyzer` 上游）；`audio_prod` 专项表：音频技术 → 本阶段 / 剧本内容 → `full_story` / 镜头表达 → `shot_design`；不允许所有音频问题默认退回完整故事 | [目标架构 §6.1.1 / §6.1.5](V3_STAGE0_TARGET_ARCHITECTURE.md#615-reject_target-的通用判定规则与-audio_prod-的分级退回stage-06-终审修订)、AD-29 | 已解决 |
| 2 | 事务日志在暂存副本之后才建立，复制中断无日志可依 | 阶段 0.5 **预检通过即建事务**；`STAGE_COPY` 成为事务内第一步（INTENT → 复制 → 校验 → COMPLETED）；新增暂存复制中断恢复判定（6 行表）；验收新增第 20 类 | [迁移 §0.3 / §3.4.2 / §3.4.3](V3_STAGE0_MIGRATION_PLAN.md#342-提交协议承认非原子逐步骤记录)、AD-23 终审行 | 已解决 |
| 3 | `MOVE_TREE` 与「原始 V2 文件必须保留」冲突 | `MOVE_TREE` 重写：只移动**经哈希验证的暂存内容**；不移动原始 V2 文件；其他移动需独立授权与独立恢复机制，默认不实现；验收新增第 21 类（含不完整暂存副本拒绝） | [迁移 §3.4.2 步骤类型表](V3_STAGE0_MIGRATION_PLAN.md#342-提交协议承认非原子逐步骤记录)、§3.4.6、AD-23 终审行 | 已解决 |
| 4 | E4 是否允许 Mock / 回放不明确 | E4 明确**允许 Mock 与录制响应回放**；同时明确 **E4 不替代 E1 / E2 的真实 API 验证**（执行规则第 8 条） | [路线 §3.4.1 说明 / §3.4.2 规则 8](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md#341-十条端到端验收) | 已解决 |
| 5 | 审查报告 A16.3 混淆「待决事项」与「已登记 OQ」，统计有误 | A16.3 重组：1 项（E4 口径）随本次终审解决并移出；2 项确认已登记为 OQ（OQ-05 / OQ-09）非文档冲突；删去异常残留行 | [审查报告包 A16.3](V3_STAGE0_6_CHATGPT_REVIEW_PACKET.md) | 已解决 |
| 6 | 共享资源审核记录的 Project/Story 归属未设计 | 新增 6 条归属规则（`target_kind` 判归属、Project 级记录不带 story_id、Story 级审核只产生变更提案、重审为 Story 级、`SharedResourceStore` 存 Project 级记录、`supersedes` 不跨归属），作为 P2 / P6 实现约束 | [目标架构 §6.3.2](V3_STAGE0_TARGET_ARCHITECTURE.md#632-共享资源审核记录归属p2--p6-实现约束)、AD-30、P2/P6 验收行 | 已解决 |

> 「已解决」同 §1 说明：文档层面自洽，不代表代码实现。

---
## 2. 最终产品定位

| 项 | 内容 |
| --- | --- |
| 产品 | **AI Story Studio V3** — 通用 AI 故事创作与短剧生产系统 |
| 首发题材 | 恐怖故事（HorrorPack）作为主要验证题材；架构不绑定题材（GenrePack 可注册） |
| 目标用户 | 个人创作者 |
| 核心价值 | 提高故事质量与短剧制作效率 |
| 非目标 | 不做商业化 SaaS：无多租户、无权限体系、无在线协作、无计费 |
| V2 关系 | 渐进式升级：V2 项目可原样打开；V3 只做加法与受控拆分（保留清单见[目标架构 §1.2](V3_STAGE0_TARGET_ARCHITECTURE.md#12-v2-能力保留清单不得无理由重写)） |

---

## 3. 最终数据架构

| 项 | 冻结内容 |
| --- | --- |
| 存储形态 | **目录化 JSON + Repository 接口 + 原子写入（`tmp.replace`）**；本轮不引入 SQLite |
| 数据入口 | 业务代码只通过 Repository 访问数据；**禁止直接 `open()` 实体 JSON** |
| Repository | **9 个**：`ProjectStore` / `SharedResourceStore` / `StoryRepository` / `CharacterRepository` / `SceneRepository` / `ShotRepository` / `VersionStore` / `ReviewRepository` / `AssetRegistry` |
| 一致性 | 单实体原子写；多实体写入走「暂存-提交」；`index.json` 为派生、可重建索引，不是真源 |
| 关联 | 全部使用稳定 ID；**`story_index` / 位置不得作为关联依据** |
| Project : Story | **1 : N**（模型层不得限制为 1:1） |
| Project 级 / Story 级 | 共享资源（人物基础档案、世界观、地点、资源索引）在 Project；创意、大纲、关系、事件、认知、版本、场景、镜头、审核、故事资产在 Story（[§4.4](V3_STAGE0_TARGET_ARCHITECTURE.md#44-project-级共享资源与-story-级数据边界stage-06-新增)） |
| 已审内容 | 冻结；任何修改产生新版本 + `pending`；旧审核记录只追加 |

---

## 4. 最终实体清单（12 个领域实体 + 1 个创作基础设施对象）

**唯一权威来源：[目标架构 §4.1](V3_STAGE0_TARGET_ARCHITECTURE.md#41-实体清单12-个领域实体--1-个创作基础设施对象)。**

| # | 实体 | 来源分类 | 所属 |
| --- | --- | --- | --- |
| 1 | Project | A. V2 可迁移 | 根 |
| 2 | Story | A. V2 可迁移 | Project |
| 3 | StoryVersion | A. V2 可迁移 | Story |
| 4 | Character | A. V2 可迁移（新增 `scope` 两段式） | Project（共享档案）/ Story（故事级） |
| 5 | CharacterRelationship | C. V3 全新 | Story |
| 6 | WorldSetting | C. V3 全新（含 `scope`） | Project（共享设定）/ Story（补充设定） |
| 7 | PlotEvent | C. V3 全新 | Story |
| 8 | CharacterKnowledgeState | C. V3 全新 | Story + Character |
| 9 | Scene | B. V2 嵌套实体化 | Story |
| 10 | Shot | B. V2 嵌套实体化 | Scene |
| 11 | VisualAsset | C. V3 全新 | Shot / Character |
| 12 | ReviewRecord | C. V3 全新 | 多态（含 `shared_character` / `shared_world`） |
| — | PromptTemplate | C. V3 全新，**创作基础设施对象，不计入 12** | 用户配置目录（不随项目走） |

统计：**A = 4 / B = 2 / C = 6 → 12 个领域实体**；另有 1 个创作基础设施对象。

---

## 5. ContextEngine 规则

**权威来源：[目标架构 §7](V3_STAGE0_TARGET_ARCHITECTURE.md#7-contextengine三层信息结构)。**

| 项 | 冻结内容 |
| --- | --- |
| 结构 | 三层：**客观事实层 / 角色认知层 / 创作指令层**（取消单一优先级表） |
| 单向关系 | 事实 → 角色认知；角色认知不得修改客观事实 |
| 视角过滤 | 生成某角色视角内容时，只注入**该角色在该时间点**已知的信息；`does_not_know` 不得出现 |
| 认知归属 | `CharacterKnowledgeState` **只属于具体 Story**，不跨 Story 复用 |
| 共享人物 | 共享档案只进入事实层；本 Story 认知只进入认知层；两者不得混淆 |
| AI 审核 | **不注入创作指令**；只以客观事实为评价基准 |
| 用户指令冲突 | 不直接覆盖；形成「变更提案」→ 新版本 → 依赖分析 → 重新审核 |
| Token 预算 | `fixed → reserved → elastic`；超限先压缩弹性段；被裁段记录在 `ContextBundle.manifest` |
| 缺失信息 | 显式输出 `MISSING:`，不让模型编造 |
| 必备测试 | **T1~T11**（含跨 Story 共享人物场景 T11） |

---

## 6. Provider 与槽位定义

| 项 | 冻结内容 |
| --- | --- |
| 能力类型（5） | `TEXT` / `IMAGE` / `VIDEO` / `AUDIO` / `VISION` —— 描述 Provider「能做什么」 |
| 业务槽位（9） | `planner` / `writer` / `concept` / `fast` / `reviewer`（TEXT）、`image`（IMAGE）、`video`（VIDEO）、`voice` / `audio`（AUDIO）—— 描述系统「在哪个环节调用 AI」 |
| `voice` vs `audio` | `voice` = 角色配音 / 语音合成；`audio` = 音效 / BGM / 音频处理。**不可混为一谈**，配置分开 |
| 接口 | 文本 Provider（`chat`）与媒体 Provider（`<ImageProvider>` / `<VideoProvider>` / `<SpeechProvider>` / `<AudioProvider>`）**接口分离** |
| 模型绑定 | 业务代码只出现 `Slot` + `provider_id`，不出现具体模型名；价格不写死在代码 |
| 独立性 | `reviewer` 必须指向与 `writer` 不同的 Provider 或模型 |
| 并发 | 默认 2，可配置 |
| 成本护栏 | 10 项（单次 / 单项目 / 每日预算、并发上限、重试上限、重复任务防护、超预算确认、Token 统计、成本估算、价格外置） |
| PromptStore | 7 字段（`prompt_id / version / genre / stage / content / created_at / description`）；每次生成记录实际 prompt_id + version；对比须同 Prompt 同上下文 |
| V3.0 交付 | TEXT 槽位全部接入（DeepSeek + GPT）；`image` 视 P9 进度；`video` / `voice` / `audio` 保留槽位与接口，不要求完整能力 |

---

## 7. 工作流与人工审核门禁

| 项 | 冻结内容 |
| --- | --- |
| 工作流阶段 | **13 个**：`story_idea` / `outline` / `character_world` / `full_story` / `scene_breakdown` / `shot_design` / `visual_assets` / `image_gen` / `video_gen` / `audio_prod` / `post_prod` / `final_review` / `export` |
| 阶段定义字段 | 9 个：`stage_id` / `stage_name` / `ai_generation` / `ai_review` / `human_review` / `gate_required` / `pass_condition` / `reject_target` / `dependencies`（[唯一阶段定义表](V3_STAGE0_TARGET_ARCHITECTURE.md#611-唯一阶段定义表全文以此表为准)） |
| 审核门禁 | **9 个**（人工作业批次）：①`story_idea` ②`outline` ③`character_world` ④`full_story` ⑤`scene_breakdown` ⑥`shot_design` ⑦`visual_assets+image_gen` ⑧`audio_prod+video_gen` ⑨`post_prod+final_review`；`export` 为前置条件型门禁 |
| AI 审核 | 仅 `full_story`（`reviewer` 槽位）与 `final_review` 设有 AI 审核；其他阶段不设 AI 审核（仍有人工审核） |
| 状态机 | 7 状态：`pending` / `ai_reviewing` / `ai_passed` / `ai_rejected` / `human_approved` / `human_rejected` / `revision_requested` |
| 放行 | **只有 `human_approved` 解锁下游**；`ai_passed` 不得自动转 `human_approved` |
| 退回 | `revision_requested` → 重新生成 → **新版本**；旧版本与旧审核记录保留 |
| 退回分级 | `reject_target` 是**默认值**：执行层问题退回本阶段；上游内容问题经 `DependencyAnalyzer` 退回对应上游。`audio_prod`：音频技术 → 本阶段；剧本内容 → `full_story`；镜头表达 → `shot_design`（[目标架构 §6.1.5](V3_STAGE0_TARGET_ARCHITECTURE.md#615-reject_target-的通用判定规则与-audio_prod-的分级退回stage-06-终审修订)） |
| 审核记录 | `ReviewRecord` 只追加；`decision ∈ {pass, reject, revise}` 独立于状态 |
| 共享资源审核归属 | `shared_character` / `shared_world` 记录为 **Project 级**，由 `SharedResourceStore` 写入；Story 级审核不得改写共享资源；重审为 Story 级；`supersedes` 不跨归属（[目标架构 §6.3.2](V3_STAGE0_TARGET_ARCHITECTURE.md#632-共享资源审核记录归属p2--p6-实现约束)，P2 / P6 约束） |
| 修改已审内容 | 新版本 + `pending` + `DependencyAnalyzer` 下游影响 + 受影响内容重新审核 |

---

## 8. 迁移安全原则

| 项 | 冻结内容 |
| --- | --- |
| 前置阻塞 | `assert_p0_fixed()` 6 项检查（K-01 行为探测 + 回归证据 + 迁移器完整性 + 备份 + 事务日志）未通过 → **禁止迁移**；不是版本号判断 |
| 版本判定 | `schema_version` 唯一权威：2 = V2，3 = V3，>3 只读，缺失/异常 → 兼容检查；**`2 + story/` 仍按 V2 处理并告警** |
| 目录 | 暂存与备份在**项目外**（`.migration_staging/`、`.backups/`）；路径边界校验；跳过暂存/备份目录避免递归 |
| 暂存目录结构 | `.migration_staging/<tx_id>/transaction.json`（事务日志）+ `.migration_staging/<tx_id>/payload/`（被复制内容）**物理隔离**；payload 树哈希 = `payload/` 内完整项目树，`transaction.json` 在父目录、结构上不在范围内（不以文件名排除实现），`payload/` 内出现 `transaction.json` 判结构非法，`.migration_tmp/` 只按相对路径排除，哈希前先做结构合法性检查；不完整时只删 `payload/`、日志保留至 `CLEANED` / `ROLLED_BACK`；日志原子写失败 → 禁止开始 `STAGE_COPY`；启动扫描按两种存在性识别 4 种形态（[迁移 §3.4.1 / §3.4.3](V3_STAGE0_MIGRATION_PLAN.md#341-目录布局项目外暂存与备份)） |
| 事务建立时机 | **预检通过即建事务**（阶段 0.5），再以 `STAGE_COPY` 步骤「INTENT → 复制 → 校验 → COMPLETED」生成暂存副本；**不完整暂存副本不得作为有效迁移结果** |
| 移动限制 | `MOVE_TREE` 只移动**经哈希验证的暂存内容**，**不移动原始 V2 文件**；原始 V2 文件必须保留；其他移动需独立授权与独立恢复机制 |
| 事务 | **逐步骤日志**：INTENT → 执行 → 验证 → COMPLETED；6 状态；原子写日志；**不得仅凭日志推断文件状态** |
| 恢复 | 启动扫描 + 打开单项项目时检查；按实际文件状态判定；恢复幂等；不确定即 `RECOVERY_REQUIRED` 人工处理 |
| 目标冲突 | 已存在 `story/` 不得直接覆盖、不得删除旧目录；无法证明安全 → 停止 |
| 异常 Story | 不补空、不静默继续；人工恢复流程；原文保留；有损恢复须显式确认；`recovery_audit[]` 只追加 |
| 暂存副本 | 复制的有效性唯一标准是 `STAGE_COPY` 为 `COMPLETED` 且树哈希一致；不完整暂存副本**不得作为有效迁移结果**（[迁移 §3.4.6](V3_STAGE0_MIGRATION_PLAN.md#346-不完整暂存副本的处置stage-06-终审新增)） |
| 验收 | **23 类**（12 项目形态 + 9 步骤级安全 + 2 暂存副本安全），失败场景证明原项目字节级不变 |

---

## 9. P0～P9 开发路线

| 阶段 | 内容 | 依赖 |
| --- | --- | --- |
| **P0** | V2.3 数据安全补丁（K-01 / K-02 / A-05 只读检测 / A-03 来源标记） | —（独立于 V3） |
| P1 | 基础架构（Repository / 原子写 / 任务状态 / 基础测试） | P0 |
| P2 | 故事数据层（Story / 人物 / 共享资源 / 关系 / 世界观 / 事件 / 认知 / 多 Story） | P1 |
| P3 | Scene/Shot 实体化（ShotVersion / AssetRegistry / 单镜重生成 / 迁移器） | P1, P2 |
| P4 | AI Provider（Registry / DeepSeek / OpenAI / UsageLedger / CostGuard） | P1 |
| P5 | PromptStore + ContextEngine | P2, P4 |
| P6 | 审核与工作流（WorkflowEngine / ReviewRecord / 门禁 / 冻结 / 依赖失效） | P1, P2, P3, P5 |
| P7 | 质量体系与题材包（AI 独立审核 / 多模型比较 / HorrorPack） | P4, P5, P6 |
| P8 | UI 适配（**V3.0 发布**） | P1~P7 |
| P9 | 短剧生产（图片 / 视频 / 配音 / 音效 / 后期 / 导出） | **P3, P4, P6, P8**（不与 P7/P8 并行；仅预备工作可提前） |

拓扑顺序：`P0 → P1 → P2 → P4 → P3 → P5 → P6 → P7 → P8 → P9`（P2 与 P4 可交换）。

> **P0 尚未开始**。本阶段（Stage 0.6）只产出文档，未执行 P0。

---

## 10. V3.0 MVP 验收标准

**权威来源：[MVP 范围 §2 / §4](V3_STAGE0_5_MVP_SCOPE.md)。**

V3.0 视为完成需同时满足：

1. 21 项能力全部通过验收（原 20 项 + 共享资源基础能力）；
2. 309 个 V2 原有用例全部保留且通过（或经审查确认的等价替换）；
3. 迁移 23 类场景通过，失败场景证明原项目未被破坏；
4. 一个真实 V2 项目完成端到端迁移并人工核对；
5. 一个完整故事从创意到镜头设计走完全部人工门禁；
6. 端到端验收（E3 / E5 / E6 / E7 / E8 / E9 / E10 + Mock 方式的 E1 / E2 / E4）完成并留下记录；
7. 全部**阻塞开发**的 OPEN QUESTION 已确定。

---

## 11. OPEN QUESTION 总表

**本表是 V3 中所有未决问题的唯一登记处。** 其它文档只引用本表编号，不再自行编号。

```jsonc
// 注册表字段（设计约定）
{ "OQ_ID": "OQ-01", "问题": "...", "影响范围": "...", "是否阻塞开发": "否",
  "需要谁决定": "用户", "最迟决策阶段": "P7", "当前状态": "OPEN" }
```

| OQ_ID | 问题 | 影响范围 | 是否阻塞开发 | 需要谁决定 | 最迟决策阶段 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `OQ-01` | 用户只配置一个 Provider 时，`reviewer` 是否允许同 Provider 不同模型，还是必须阻止 AI 审核 | AI 审核（`full_story` / `final_review`）、配置校验 | 否 | 用户 / 产品 | P7（独立审核上线的阶段） | `OPEN` |
| `OQ-02` | 单任务 / 单项目 / 每日预算的默认数值 | 成本护栏、`CostGuard` 默认配置 | **是（P4）** — 没有默认值无法定义超预算行为 | 用户（费用承受能力） | P4 开始前 | `OPEN` |
| `OQ-03` | 多 Story 的 UI 呈现形态（列表页 vs 树形） | P8 UI | 否 | 用户 | P8 开始前 | `OPEN` |
| `OQ-04` | V3.0 是否必须接入视频生成 Provider | P9 范围、MVP 第 1 项暂缓 | 否 | 用户 | P9 规划前 | `OPEN` |
| `OQ-05` | 备份保留时长与次数（迁移备份 + 版本快照） | 迁移 §4.4、磁盘占用 | 否 | 用户 | P3 开始前 | `OPEN` |
| `OQ-06` | 单 Story 项目的 `story_id` 派生规则（项目名 / 稳定 UUID） | 迁移 §3.3、重命名项目后的行为 | **是（P3）** — 迁移必须能稳定生成 story_id | 用户 / 产品 | P3 开始前 | `OPEN` |
| `OQ-07` | 迁移是否需要用户确认，还是允许「首次打开自动迁移」 | 迁移 §4.1 | **是（P3）** — 决定迁移入口交互 | 用户 | P3 开始前 | `OPEN` |
| `OQ-08` | 迁移后 V2 旧程序需继续可用多久 | 兼容层保留期、回滚承诺 | 否 | 用户 | P3 开始前 | `OPEN` |
| `OQ-09` | 目录布局细节（`story/index.json` 的命名、`versions/` 是否按 story 分子目录） | 存储实现（P1） | 否 | 开发者（可给出建议，由用户确认） | P1 实现前 | `OPEN` |

**旧编号映射**（避免同一问题出现不同编号）：

| 原编号 | 出处 | 统一编号 |
| --- | --- | --- |
| OQ-1 | 目标架构 Stage 0.5 §12 / 决策 Stage 0.5 §8 / 修订报告 Stage 0.5 §5 | `OQ-01` |
| OQ-2 | 同上 | `OQ-02` |
| OQ-3 | 同上 | `OQ-03` |
| OQ-4 | 同上 | `OQ-04` |
| OQ-5 | 决策 Stage 0.5 §8 / 迁移方案 Stage 0.5 §9（OQ-M3） | `OQ-06` |
| OQ-6 | 决策 Stage 0.5 §8 / 迁移方案 Stage 0.5 §9（OQ-M1） | `OQ-05` |
| OQ-M1 | 迁移方案 §9 | `OQ-05` |
| OQ-M2 | 迁移方案 §9 | `OQ-07` |
| OQ-M3 | 迁移方案 §9 | `OQ-06` |
| OQ-M4 | 迁移方案 §9 | `OQ-08` |

**统计**：统一编号 **9 个**；其中 **阻塞开发 3 个**（`OQ-02` / `OQ-06` / `OQ-07`），非阻塞 6 个。

> 开发者**不替用户决定**预算与备份策略等产品参数；本表只记录问题、影响与最迟决策点。

---

## 12. 明确标注尚未实现的功能

**以下内容全部是设计，代码中尚不存在**。V2.3 代码保持原样（本阶段未修改任何 `.py` / 测试 / 配置 / 数据）。

| 功能 | 当前状态 | 计划阶段 |
| --- | --- | --- |
| K-01 / K-02 / A-05 / A-03 修复 | **未修复**（缺陷仍在代码中） | P0 |
| Repository 接口族（9 个） | 不存在 | P1~P3 |
| 目录化实体存储、`index.json` | 不存在（当前为单 `project.json`） | P1~P3 |
| Project 级共享资源（`shared/`、`SharedResourceStore`） | 不存在 | P2 |
| 多 Story 支持 | 模型层允许，UI 与存储未实现 | P1~P2 |
| Scene / Shot 独立实体与镜头版本 | 不存在（内嵌 + 时间轴双轨） | P3 |
| `ShotRegenerator` | 不存在 | P3 |
| 迁移器、逐步骤事务日志、启动恢复 | 不存在 | P3 |
| `assert_p0_fixed()` | 不存在 | P0（探测能力）/ P3（迁移入口） |
| ProviderRegistry、OpenAI GPT 接入 | 不存在（仅 DeepSeek 内联调用） | P4 |
| 9 个业务槽位（尤其 `audio`） | 现有 4 个槽位 | P4 |
| UsageLedger / CostGuard | 不存在（`call_log` 仅有基础记录） | P4 |
| PromptStore（7 字段、版本化） | 不存在（Prompt 内联） | P5 |
| ContextEngine（三层结构） | 不存在 | P5 |
| WorkflowEngine、审核门禁、状态机 | 不存在（有 AI 评分，无门禁） | P6 |
| ReviewRecord 持久化 | 不存在 | P6 |
| DependencyAnalyzer | 不存在 | P6 |
| AI 独立审核、多模型比较 | 不存在 | P7 |
| GenrePack / HorrorPack 包装 | 不存在（`horror_rules` 为直接规则） | P7 |
| 审核中心、人物中心、世界观中心、镜头管理、模型对比面板 | 不存在 | P8 |
| 图片 / 视频 / 配音 / 音效 / 后期 / 导出生产链路 | 图片与配音有部分媒体能力，生产链路未接入 V3 | P9 |
| GUI 自动化冒烟（V2 GUI 约 4,200 行零自动化测试） | 不存在 | P8 起逐步补充 |

> 现有 V2 能力：五阶段流水线、JSON 解析链、Pacing、本地质量检查、FFmpeg 渲染、媒体调用、批量失败隔离、Key 安全、原子写、309 个测试 —— **均真实存在**，见[审计](V3_STAGE0_CURRENT_ARCHITECTURE_AUDIT.md)。

---

## 13. V3.0 架构冻结声明

### 13.1 冻结内容（未经过变更流程不得修改）

1. 产品定位与用户边界（§2）；
2. 存储形态与 9 个 Repository 接口的职责划分（§3）；
3. 12 个领域实体清单与来源分类；PromptTemplate 的归类（§4）；
4. Project / Story 数据边界与 8 条规则（§4.4.3）与共享资源审核归属 6 条规则（§6.3.2）；
5. ContextEngine 三层结构与 T1~T11 测试场景（§5）；
6. 5 个能力类型与 9 个业务槽位（§6）；
7. 13 个阶段 ID 与 9 个人工门禁的映射，以及 `reject_target` 按问题性质分级（§7）；
8. 7 状态审核状态机与「AI 通过 ≠ 人工通过」（§7）；
9. 迁移的 K-01 硬阻塞、`schema_version` 判定矩阵、**事务先于暂存**的逐步骤事务日志、**事务日志与暂存副本物理隔离**（`<tx_id>/transaction.json` + `payload/`）、`MOVE_TREE` 只动暂存内容的限制、23 类验收（§8）；
10. P0~P9 依赖关系（§9），尤其是 P9 依赖 P3/P4/P6/P8。

### 13.2 变更流程

任何对冻结内容的修改必须：

1. 新增一条 `AD-xx` 决策，说明理由与影响面；
2. 修改对应权威文档（目标架构 / 迁移方案 / 路线）；
3. 更新本文件对应章节与修订报告；
4. 经 ChatGPT 审查通过后才生效。

### 13.3 冻结的边界

- 冻结的是**设计**，不是实现；§12 列出全部尚未实现的功能。
- 冻结不阻止在开发中发现设计缺陷后按 §13.2 修订。
- 冻结不包含 §11 中仍然是 `OPEN` 的问题；这些问题在各自「最迟决策阶段」前必须确定。

### 13.4 本阶段完成状态

| 项 | 状态 |
| --- | --- |
| 修改 `.py` / 测试 / `project.json` / 用户数据 | **未修改** |
| 执行迁移 / 修改 API Key / 安装依赖 / 修改配置 / 删除旧代码或测试 | **未执行** |
| Git commit / reset / clean / checkout | **未执行** |
| 操作 AI Dev Hub | **未执行** |
| 开始 P0 | **未开始** |
| 修改范围 | 仅 `docs/architecture/v3_stage0/` 下的 Markdown 文件 |

**Stage 0.6 终审修订到此结束。终审意见 1~6 已全部落入文档（见 §1A）；本基线在 ChatGPT 确认终审修订后生效为 V3.0 开发基线。在此之前不进入 P0。**
