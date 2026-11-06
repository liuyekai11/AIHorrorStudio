# V3 STAGE 0.5 / 0.6 — 架构决策记录

日期：2026-11-05
状态：**Stage 0.6 终审修订版**（在 Stage 0.6 修订版基础上按 ChatGPT 终审意见 1 / 6 补充 AD-29 / AD-30 与修订行）
关联：[目标架构](V3_STAGE0_TARGET_ARCHITECTURE.md)、[迁移方案](V3_STAGE0_MIGRATION_PLAN.md)、[MVP 范围](V3_STAGE0_5_MVP_SCOPE.md)、[开发路线](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md)、[修订报告](V3_STAGE0_5_REVIEW_REPORT.md)、[Stage 0.6 冻结基线](V3_STAGE0_6_FINAL_BASELINE.md)

> Stage 0.6 修改了 AD-09 / AD-12 / AD-16 / AD-21 / AD-23 / AD-24 的内容，并新增 AD-27 / AD-28。Stage 0.6 终审（ChatGPT 结论 CONDITIONAL PASS）以修订行形式修改 AD-12 / AD-23 / AD-27 / AD-28，并新增 AD-29 / AD-30。修改处均标注「Stage 0.6 修订」或「Stage 0.6 终审修订」并说明原因。

---

## 0. 记录格式

每条决策包含：

- **决策**：最终采用什么
- **理由**：为什么这样选（技术 + 产品）
- **影响**：会改变哪些模块 / 文档 / 流程
- **状态**：`已确定` / `待确认`（`OPEN QUESTION` 单独列出）
- **对应审查意见**：来自哪一条 Stage 0 审查意见

> Stage 0.6 起，所有未决问题统一登记在 [冻结基线 §11 OPEN QUESTION 总表](V3_STAGE0_6_FINAL_BASELINE.md#11-open-question-总表)，本文件不再自行编号。

---

## 1. 产品与范围

### AD-01 产品定位：通用故事创作系统，恐怖为首发题材

| 项 | 内容 |
| --- | --- |
| 决策 | V3 定位为「通用 AI 故事创作与短剧生产系统」，首发以恐怖故事验证；目标用户为个人创作者；**不做商业化 SaaS** |
| 理由 | 题材绑定会让数据模型和 Prompt 全部长死在恐怖上，后续扩展需要重构；个人创作工具不需要多租户/权限/计费体系 |
| 影响 | GenrePack 必须抽象（§9）；所有审核维度、Prompt 来源题材包；MVP 只交付 HorrorPack |
| 状态 | 已确定 |
| 对应审查意见 | 1.1 产品定位 |

### AD-02 渐进式升级，保留 V2 全部已验证能力

| 项 | 内容 |
| --- | --- |
| 决策 | 保留五阶段流水线、JSON 解析与截断恢复、Pacing、本地质量检查、FFmpeg 渲染、媒体调用、批量失败隔离、Key 安全、原子写；不得无理由重写 |
| 理由 | 这些能力经过真实 API 验证与 309 个测试覆盖，重写只会引入回归 |
| 影响 | 每个阶段开发前必须先审查现有实现，禁止「顺手重写」 |
| 状态 | 已确定 |
| 对应审查意见 | 1.2 渐进式升级 |

### AD-03 本轮不引入 SQLite

| 项 | 内容 |
| --- | --- |
| 决策 | 存储采用「目录化 JSON + Repository 接口 + 原子写入」；保留未来数据库实现的接口边界，但不提前实现 |
| 理由 | 与 V2 单文件哲学一致，迁移风险最低；个人创作者的项目量级不需要数据库的事务/并发能力 |
| 影响 | 必须有 Repository 接口层；业务代码禁止直连 JSON；并发写与多实体一致性通过「暂存-提交」保证 |
| 状态 | 已确定 |
| 对应审查意见 | 1.3 存储架构 |

### AD-04 审核强度：重要阶段全部人工最终确认

| 项 | 内容 |
| --- | --- |
| 决策 | 采用「AI 辅助生成 + AI 独立审核 + 人工最终审核」；**任何阶段 AI 通过都不能自动放行**；只有 `human_approved` 可解锁下一阶段 |
| 理由 | 故事质量与创作方向是主观判断，AI 审核只能提供信号；AI 自动放行会让错误累积到成片 |
| 影响 | 工作流层需要状态机 + 门禁；UI 必须有审核中心；批量流程不得绕过门禁 |
| 状态 | 已确定 |
| 对应审查意见 | 1.2 / 3.1（原 Stage 0 的 `gate="human_or_ai"` 被删除） |

### AD-05 V3.0 只交付 HorrorPack，MysteryPack 延后

| 项 | 内容 |
| --- | --- |
| 决策 | V3.0 首发题材只有恐怖（HorrorPack）；MysteryPack 作为后续验证抽象的第二题材，不在 V3.0 交付范围 |
| 理由 | 恐怖题材已有 21 个规则测试与真实生成基线，是唯一可验证的题材；再做一个题材会拖慢核心交付 |
| 影响 | GenrePack 接口必须设计正确（能容纳未知题材），但**不做第二个实现**；接口抽象质量由代码评审与用例保证 |
| 状态 | 已确定 |
| 对应审查意见 | 1.4 题材抽象（原 Stage 0 §10 第 5 问） |

---

## 2. 数据模型

### AD-06 Project : Story 为 1 : N

| 项 | 内容 |
| --- | --- |
| 决策 | 数据模型层允许「一个项目多篇故事」；**不得在底层永久限制为 1:1** |
| 理由 | 用户会围绕同一世界观/同一组人物创作系列故事；如果模型层写成 1:1，后续改动波及全部实体 |
| 影响 | `Story` 有独立 `story_id`；`story/index.json` 维护列表；所有下游实体必须挂在 story_id 下；迁移时单 story 项目派生一个 story_id |
| 状态 | 已确定 |
| 对应审查意见 | 1.4 数据模型 |

### AD-07 Scene / Shot 实体化，全部使用稳定 ID 关联

| 项 | 内容 |
| --- | --- |
| 决策 | Scene、Shot 独立存储；关联一律使用 ID；**`story_index` / 位置不再作为关联依据**；Shot 支持多版本与多素材候选 |
| 理由 | 双轨制与 index 对齐是 A-05 素材错位的根因；单镜重生成与镜头级审核都要求镜头是独立实体 |
| 影响 | 迁移器按 shot_id 合并；orphan 不删；保留 `legacy_timeline_id`；快照范围扩大 |
| 状态 | 已确定 |
| 对应审查意见 | 1.5 / 7.3 |

### AD-08 已审内容冻结 + 依赖影响分析

| 项 | 内容 |
| --- | --- |
| 决策 | 人工审核通过的内容冻结；任何上游变更必须经过 `DependencyAnalyzer` 计算下游影响，受影响内容标记过期并重新审核；**禁止静默覆盖已批准内容** |
| 理由 | 用户最不可接受的失败是「我审过的东西被 AI 悄悄改了」 |
| 影响 | 领域层新增 `DependencyAnalyzer`；所有 Repository 写入路径需要触发或校验依赖分析；审核状态机需要 `revision_requested` |
| 状态 | 已确定 |
| 对应审查意见 | 1.5 依赖影响分析 / 3.4 版本冻结 |

### AD-09 12 个领域实体 + 1 个创作基础设施对象（Stage 0.6 修订）

| 项 | 内容 |
| --- | --- |
| 决策 | **12 个领域实体**：Project / Story / StoryVersion / Character / CharacterRelationship / WorldSetting / PlotEvent / CharacterKnowledgeState / Scene / Shot / VisualAsset / ReviewRecord。**PromptTemplate 单独归类为创作基础设施对象**，不计入领域实体（它存储在用户配置目录，不随项目走） |
| 修订原因 | Stage 0.5 写「13 个核心实体」把 PromptTemplate 计入领域实体，导致执行摘要、修订报告、冻结文件之间出现 12 / 13 两套口径 |
| 来源三分法 | 按审查问题 3 要求，每个实体标注来源：**A. V2 已存在且可迁移**（Project / Story / StoryVersion / Character，4 个）；**B. V2 原有嵌套结构需实体化**（Scene / Shot，2 个）；**C. V3 全新引入**（CharacterRelationship / WorldSetting / PlotEvent / CharacterKnowledgeState / VisualAsset / ReviewRecord，6 个）。Scene/Shot 的实体「本身」来自 V2，但其独立 Repository、稳定主键关联、独立版本与审核能力属于 V3 新增 |
| 唯一权威 | 实体清单以 [目标架构 §4.1](V3_STAGE0_TARGET_ARCHITECTURE.md#41-实体清单12-个领域实体--1-个创作基础设施对象) 为唯一来源；其它文档不另设清单 |
| 影响 | 每个实体必须定义主键、所属、核心字段、引用、生命周期、版本策略、删除策略、审核要求（见 [目标架构 §4.2](V3_STAGE0_TARGET_ARCHITECTURE.md#42-实体定义模板)）；Repository 数量 9 个（新增 `SharedResourceStore`，见 AD-28），与实体数量是两个口径 |
| 状态 | 已确定 |
| 对应审查意见 | 1.4 / 4.4（Stage 0.5）；审查问题 3（Stage 0.6） |

---

## 3. ContextEngine

### AD-10 三层信息结构取代单一优先级表

| 项 | 内容 |
| --- | --- |
| 决策 | ContextEngine 使用三个独立层次：**客观事实层 / 角色认知层 / 创作指令层**。取消 Stage 0 初版的单一优先级表 |
| 理由 | 客观事实、人物认知、用户指令是三种不同性质的信息，混成一个优先级序列会导致：① 角色该不知道的秘密被注入；② 用户的临时指令被当成事实；③ AI 审核被创作指令带偏 |
| 影响 | `ContextBundle` 按层组织；AI 审核不注入创作指令；用户指令与事实冲突时形成「变更提案」而非直接覆盖 |
| 状态 | 已确定 |
| 对应审查意见 | 2.1~2.4 |

### AD-11 冲突与角色认知测试场景 ≥ 8 个

| 项 | 内容 |
| --- | --- |
| 决策 | 必须覆盖 T1~T11 共 11 个场景（T11 为 Stage 0.6 新增的跨 Story 共享人物场景）（见 [目标架构 §7.7](V3_STAGE0_TARGET_ARCHITECTURE.md#77-必须覆盖的测试场景11-个)） |
| 理由 | 审查意见要求「至少 8 个」；实际列出 10 个以覆盖误解、隐瞒、审核独立性等边界 |
| 影响 | P5 阶段验收标准包含这些测试 |
| 状态 | 已确定 |
| 对应审查意见 | 2.4 |

---

## 4. 工作流与审核

### AD-12 九个审核门禁与 13 个阶段的唯一映射（Stage 0.6 修订）

| 项 | 内容 |
| --- | --- |
| 决策 | **13 个工作流阶段**（`story_idea` / `outline` / `character_world` / `full_story` / `scene_breakdown` / `shot_design` / `visual_assets` / `image_gen` / `video_gen` / `audio_prod` / `post_prod` / `final_review` / `export`），**9 个审核门禁按人工作业批次合并**：① `story_idea` ② `outline` ③ `character_world` ④ `full_story` ⑤ `scene_breakdown` ⑥ `shot_design` ⑦ `visual_assets + image_gen` ⑧ `audio_prod + video_gen` ⑨ `post_prod + final_review`。`export` 不是独立审核阶段，而是「前置条件型门禁」（必须 `final_review=human_approved`） |
| 修订原因 | Stage 0.5 标题写「九个审核阶段门禁」但正文只有 13 阶段表，未说明 9 个门禁具体对应哪 9 个阶段，也未说明其余阶段的处理 |
| 关键区分 | **门禁是人工作业批次，阶段是状态机节点**。合并门禁只影响 UI 与计数，不降低任何阶段的审核要求——9 个门禁覆盖 13 个阶段中的 12 个，这些阶段各自仍需要 `human_approved` 与 ReviewRecord；唯一不需要独立审核的是 `export`（前置条件型门禁，见目标架构 §6.1.3） |
| 理由 | 阶段 ID 需要稳定、可写进 JSON 与测试；门禁按人工作业批次组织更符合实际使用（用户是一次审完一批候选图，而不是 13 次弹窗） |
| 影响 | `stage_states` 使用阶段 ID 作键；详细字段（9 列）与 pass_condition / reject_target / dependencies 见 [目标架构 §6.1.1](V3_STAGE0_TARGET_ARCHITECTURE.md#611-唯一阶段定义表全文以此表为准)；迁移不涉及阶段状态（V2 无此概念，全部从 `not_started` 起） |
| 未推翻 | 9 个门禁的数量与「重要阶段全部人工确认」的原则保持 Stage 0.5 结论不变 |
| Stage 0.6 终审修订（`reject_target` 分级） | `reject_target` 明确为**默认退回目标**，不是唯一退回点：每个阶段先按问题性质分级——执行层问题退回本阶段；上游内容问题经 `DependencyAnalyzer` 退回对应上游。新增 [目标架构 §6.1.5](V3_STAGE0_TARGET_ARCHITECTURE.md#615-reject_target-的通用判定规则与-audio_prod-的分级退回stage-06-终审修订)。**`audio_prod` 不再使用单一 `reject_target = full_story`**：音频技术问题 → 本阶段；剧本内容问题 → 经 `DependencyAnalyzer` 判定 `full_story`；镜头表达问题 → `shot_design`。不得所有音频问题默认退回完整故事 |
| 对应审查意见 | 3.1（Stage 0.5）；审查问题 4（Stage 0.6）；Stage 0.6 终审意见 1 |

### AD-13 审核状态机 7 状态 + 独立 decision

| 项 | 内容 |
| --- | --- |
| 决策 | 状态：`pending / ai_reviewing / ai_passed / ai_rejected / human_approved / human_rejected / revision_requested`；ReviewRecord 的 `decision` 单独使用 `pass / reject / revise` |
| 理由 | 状态机描述「对象当前处于哪个阶段」，decision 描述「这一次评审的结论」；两者混用会导致「AI 通过 = 人工通过」的误判 |
| 影响 | 状态转换由工作流层统一校验；非法转换抛错 |
| 状态 | 已确定 |
| 对应审查意见 | 3.2 |

### AD-14 AI 审核与人工审核分别记录

| 项 | 内容 |
| --- | --- |
| 决策 | 同一次审核操作中，AI 与人工各产生独立 `ReviewRecord`；`reviewer_kind ∈ {human, ai, local_rule}` |
| 理由 | 审计追溯需要区分「谁说的」；AI 记录的价值在于质量对比与回归 |
| 影响 | `ReviewRepository.list_by_target` 需按 `reviewer_kind` 过滤；UI 分栏显示 |
| 状态 | 已确定 |
| 对应审查意见 | 3.2 / 3.3 |

### AD-15 审核记录只追加，永不覆盖

| 项 | 内容 |
| --- | --- |
| 决策 | `ReviewRepository` 只提供 `append`，不提供 `update` / `delete`；旧记录通过 `supersedes` 形成链 |
| 理由 | 审核历史是质量追溯的唯一依据；允许覆盖等于允许篡改 |
| 影响 | 存储层无修改路径；测试需断言「不存在 update 方法」 |
| 状态 | 已确定 |
| 对应审查意见 | 3.3 |

---

## 5. Provider 与 Prompt

### AD-16 九个槽位，能力类型与业务槽位分离（Stage 0.6 修订）

| 项 | 内容 |
| --- | --- |
| 决策 | **9 个业务槽位**：`planner / writer / concept / fast / reviewer / image / video / voice / audio`；**5 个能力类型**：`TEXT / IMAGE / VIDEO / AUDIO / VISION`。`AUDIO` 是能力类型，`voice`（配音 / 语音合成）与 `audio`（音效 / BGM）是两个不同的业务槽位 |
| 修订原因 | Stage 0.5 只有 8 个槽位，缺 `audio`，把音效与配音混在 `voice` 下；审查问题 2 指出这会阻碍音效/BGM 的独立 Provider 与独立审核 |
| 关键区分 | 能力类型 ≠ 槽位；同名不代表同层（不存在「AUDIO 槽位」） |
| 理由 | 文本与媒体 Provider 的接口形态不同；混在一个接口里会导致媒体方法污染文本抽象。配音与音效的生产流程、审核维度、可替换 Provider 都不同 |
| 影响 | `image_engine` / `voice_engine` 改为通过媒体 Provider 调用；V2 的四个槽位映射到新槽位表；`audio` 槽位在 V3.0 可以只保留配置与接口，不交付完整能力（MVP §3） |
| 状态 | 已确定 |
| 对应审查意见 | 4.1（Stage 0.5）；审查问题 2（Stage 0.6） |

### AD-17 reviewer 与 writer 必须不同

| 项 | 内容 |
| --- | --- |
| 决策 | `reviewer` 槽位必须指向与 `writer` 不同的 Provider 或模型；配置校验时检查 |
| 理由 | 同一模型审核自己的输出，独立性无法保证 |
| 影响 | 配置加载时校验；校验失败给出明确提示 |
| 状态 | 已确定（单 Provider 场景下的降级策略为 `OPEN QUESTION` **OQ-01**） |
| 对应审查意见 | 4.1 独立模型审核 |

### AD-18 默认并发 2，用户可配

| 项 | 内容 |
| --- | --- |
| 决策 | 多模型并行默认并发数为 **2**；用户可配置上限 |
| 理由 | 个人创作者机器上并发过高会导致限流与费用不可控 |
| 影响 | `FanoutRunner` 默认值；成本护栏联动 |
| 状态 | 已确定 |
| 对应审查意见 | 4.2 |

### AD-19 成本护栏全套 + 价格外置

| 项 | 内容 |
| --- | --- |
| 决策 | 单次任务预算 / 单项目预算 / 每日预算 / 最大并发 / 重试上限 / 重复任务防护 / 超预算确认 / Token 统计 / 成本估算 / Provider 价格配置；**价格不得写死在代码** |
| 理由 | 多模型对比会显著提高调用量；价格随厂商调整 |
| 影响 | `UsageLedger` + `CostGuard`；`providers.json` |
| 状态 | 已确定（默认预算数值为 `OPEN QUESTION` **OQ-02**） |
| 对应审查意见 | 4.3 |

### AD-20 PromptStore 七个字段 + 使用记录

| 项 | 内容 |
| --- | --- |
| 决策 | `prompt_id / version / genre / stage / content / created_at / description`；每次生成记录实际使用的 prompt_id 与 version |
| 理由 | 没有 Prompt 版本记录，多模型对比的结论无法复现 |
| 影响 | `UsageLedger` 与 `ReviewRecord` 增加 `prompt_id` |
| 状态 | 已确定 |
| 对应审查意见 | 4.4 |

---

## 6. 迁移

### AD-21 K-01 硬阻塞迁移

| 项 | 内容 |
| --- | --- |
| 决策 | K-01 在 V2.3 独立补丁修复并回归通过之前，**禁止执行任何 V2→V3 迁移**；迁移入口通过 `assert_p0_fixed()` 校验。Stage 0.6 明确该函数为 **6 项检查**（迁移能力版本 / K-01 行为探测 / 回归证据文件与代码指纹 / 迁移器完整性 / 备份可用性 / 事务日志可用性），**不是版本号判断**（见 [迁移方案 §1.3.1](V3_STAGE0_MIGRATION_PLAN.md#131-assert_p0_fixed-的检查清单)） |
| Stage 0.6 补充 | 区分「开发测试阶段的 P0 验收」（跑完整测试套件，产出 `p0_verification.json`）与「正式迁移时的运行时安全检查」（每次迁移执行 6 项毫秒级检查）；不得每次迁移跑全套测试，也不得仅改版本号绕过检查 |
| 理由 | 迁移过程中必然触发 story 读取与升级；K-01 存在时迁移会把损坏 story 静默清空 |
| 影响 | P0 独立于 V3 发布；迁移器增加前置检查与测试 |
| 状态 | 已确定 |
| 对应审查意见 | 7.1 |

### AD-22 schema_version 唯一权威判定

| 项 | 内容 |
| --- | --- |
| 决策 | V2 = 2，V3 = 3；大于当前支持版本 → 只读打开禁止写回；缺失或异常 → 兼容检查，**不得自动猜测为 V3**；禁止「2 被识别为完整 V3」 |
| 理由 | Stage 0 初版「`schema_version==2` 且有 `story/` 即 V3」会造成版本语义错乱 |
| 影响 | `ProjectStore.open` 的判定矩阵（[迁移方案 §3.1](V3_STAGE0_MIGRATION_PLAN.md#31-版本判定矩阵重写)） |
| 状态 | 已确定 |
| 对应审查意见 | 7.4 |

### AD-23 项目外暂存 + 提交日志 + 启动恢复

| 项 | 内容 |
| --- | --- |
| 决策 | 暂存与备份目录位于项目外（`.migration_staging/`、`.backups/`）；采用 `transaction.json` **逐步骤**提交日志；启动时扫描未完成迁移；**不把多次 replace/rename 描述为原子事务** |
| Stage 0.6 修订 | 事务日志从「事务级状态」升级为「步骤级记录」：每步 10 个字段（`step_id / operation / source_path / target_path / expected_source_hash / expected_target_hash / state / started_at / completed_at / error`）与 6 个状态（`PENDING / INTENT_RECORDED / EXECUTING / COMPLETED / FAILED / RECOVERY_REQUIRED`）；先写 INTENT 再执行、验证后才 COMPLETED、每次状态更新原子写、**不得仅凭日志推断文件已完成**；恢复按「日志 + 实际文件状态」共同判定（[迁移方案 §3.4.2–3.4.3](V3_STAGE0_MIGRATION_PLAN.md#342-提交协议承认非原子逐步骤记录)） |
| 理由 | 文件系统无法提供目录级原子切换；必须承认中间态并设计恢复。仅记录事务级状态时，进程在 COMMITTING 中断后无法判断具体哪个文件已完成 |
| 影响 | 迁移器架构、启动流程、测试用例（中断/恢复/回滚，**23 类**验收，见迁移方案 §5.1） |
| Stage 0.6 终审修订（日志先于暂存） | **事务记录先于暂存副本建立**：预检通过后即原子写入 `transaction.json`（`state=OPEN`），并以 `STAGE_COPY` 步骤先持久化 INTENT 再执行复制；暂存副本不再位于「事务外」。新增**暂存复制中断恢复判定**：暂存区未完整（`STAGE_COPY` 未 `COMPLETED`）时，**不完整暂存副本不得作为有效迁移结果**——恢复时删除重建或从备份重新暂存，一律不得进入阶段 2 校验之后的流程（[迁移方案 §3.4.2 / §3.4.3 / §3.4.6](V3_STAGE0_MIGRATION_PLAN.md#342-提交协议承认非原子逐步骤记录)） |
| Stage 0.6 终审修订（MOVE_TREE 受限） | `MOVE_TREE` **只允许移动经哈希验证的暂存区内容**；**不允许移动原始 V2 文件**，原始 V2 文件必须保留（回滚与 V2 兼容的依据）；任何其他移动行为（例如移动项目内旧目录）须**独立授权 + 独立恢复机制**，默认不实现（[迁移方案 §3.4.2 步骤类型表](V3_STAGE0_MIGRATION_PLAN.md#步骤类型)） |
| Stage 0.6 终审补充核验 R4（日志与暂存物理隔离） | 暂存目录固定为 `.migration_staging/<tx_id>/transaction.json` + `.migration_staging/<tx_id>/payload/`：`transaction.json` 是独立事务元数据，**不属于被复制的项目内容、结构上不在 payload 哈希范围内**（不以按文件名排除实现）；`payload/` 内出现 `transaction.json` 判结构非法，`.migration_tmp/` 只按相对路径排除，哈希前先做结构合法性检查；`STAGE_COPY` 只复制与校验 `payload/`；删除不完整副本只删 `payload/`，日志保留至 `CLEANED` / `ROLLED_BACK`；日志原子写失败禁止开始 `STAGE_COPY`；启动扫描按两种存在性识别 4 种形态；原始 V2 文件保护规则不变（[迁移方案 §3.4.1 / §3.4.2 / §3.4.3 / §3.4.6](V3_STAGE0_MIGRATION_PLAN.md#341-目录布局项目外暂存与备份)） |
| 状态 | 已确定 |
| 对应审查意见 | 7.5 / 7.6；Stage 0.6 终审意见 2 / 3；终审补充核验 R4 |

### AD-24 story 缺失/异常不补空、不静默继续

| 项 | 内容 |
| --- | --- |
| 决策 | story 缺失 → 保留原始字节、不创建空 Story、优先提示从历史版本恢复；story 结构异常 → 原文备份到项目外并标记人工处理。Stage 0.6 补充：异常 Story **默认进入人工恢复流程**；从历史版本恢复必须记录来源文件与恢复结果；无法恢复则项目标记异常状态；有损恢复须用户显式确认；全部动作写入 `recovery_audit[]` 只追加审计 |
| 理由 | 用空 Story 代替「丢失的事实」违反「不静默继续」原则，会让用户误以为数据还在 |
| 影响 | 迁移分派表（[迁移方案 §3.2](V3_STAGE0_MIGRATION_PLAN.md#32-story-形态分派重写)） |
| 状态 | 已确定 |
| 对应审查意见 | 7.7 |

---

## 7. 开发治理

### AD-25 每阶段独立任务书 + ChatGPT 审查后进入下一阶段

| 项 | 内容 |
| --- | --- |
| 决策 | 每个开发阶段单独任务书；先审查代码再修改；完成后输出变更报告；经 ChatGPT 审查后才能进入下一阶段 |
| 理由 | 一次性大改不可控；逐阶段审查能及早发现架构偏差 |
| 影响 | 开发流程（[开发路线 §6](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md)） |
| 状态 | 已确定 |
| 对应审查意见 | 任务 8 |

### AD-26 测试治理：不删旧用例、新功能必须有用例

| 项 | 内容 |
| --- | --- |
| 决策 | 禁止为通过测试而删除原有用例；新功能必须有单元测试；迁移/状态机/ContextEngine/Provider 有专项测试要求；GUI 逐步增加自动冒烟 |
| 理由 | 309 个用例是 V2 的质量基线；删除测试等于掩盖回归 |
| 影响 | 每阶段验收标准 |
| 状态 | 已确定 |
| 对应审查意见 | 任务 8 |

---

## 8. 项目级共享与 Story 级数据边界（Stage 0.6 新增篇）

### AD-27 Project 级共享资源 + Story 级剧情数据

| 项 | 内容 |
| --- | --- |
| 决策 | 采用「Project 级共享资源 + Story 级剧情数据」：Project 持有项目信息、共享人物基础档案、共享世界观基础设定、共享地点与项目级资源索引；Story 持有创意、大纲、故事级人物、人物关系、故事级世界观补充、剧情事件、角色认知状态、StoryVersion、Scene、Shot、故事审核记录、故事专属视觉资产 |
| 理由 | 用户会围绕同一世界观与同一组人物写系列故事；若人物档案与世界观完全 Story 私有，则第二篇故事要么重复录入、要么出现两套互相矛盾的人物外观与硬规则 |
| 影响 | 新增 `shared/` 目录（目标架构 §3.2）；新增 `SharedResourceStore` 接口（9 个 Repository）；Character / WorldSetting 改为 `scope` 两段式；`CharacterKnowledgeState` 明确只能属 Story；ReviewRecord 的 `target_kind` 增加共享资源类型 |
| 不扩大 MVP | V3.0 只要求「共享档案 CRUD + 引用查询 + 修改前影响提示 + 标记 stale」，不要求跨 Story 自动重新审核编排（MVP §3） |
| 迁移影响 | 迁移时 V2 `story.characters[]` **优先迁入 Story 级**，不自动提升为共享档案；提升为用户显式操作 |
| Stage 0.6 终审修订 | 共享资源的**审核记录归属**单独规定：`target_kind ∈ {shared_character, shared_world}` 的记录为 **Project 级**（不携带单一 `story_id`、由 `SharedResourceStore` 写入）；Story 级审核不得改写共享资源，只能形成变更提案；共享资源变更后的重审是 **Story 级**的，各 Story 独立产生记录；`supersedes` 不跨归属。见 [目标架构 §6.3.2](V3_STAGE0_TARGET_ARCHITECTURE.md#632-共享资源审核记录归属p2--p6-实现约束)；P2 / P6 验收均须包含「同一共享人物被两篇 Story 引用」的审核用例 |
| 状态 | 已确定 |
| 对应审查意见 | 审查问题 8（Stage 0.6）；Stage 0.6 终审意见 6 |

### AD-28 共享资源使用独立 Repository

| 项 | 内容 |
| --- | --- |
| 决策 | 新增 `SharedResourceStore`，负责 `shared/` 下的共享人物、共享世界观、共享地点与引用索引；`CharacterRepository` 只负责 Story 级人物视图并能解析共享档案 |
| 理由 | 若让 `CharacterRepository` 同时管两级数据，它会同时依赖 Story 与 Project 上下文，职责混乱；独立接口可让「修改共享资源必须检查引用」有明确落点 |
| 影响 | Repository 数量 8 → 9；引用完整性校验增加「Story 级 `shared_ref` 必须指向存在的共享档案」 |
| 状态 | 已确定 |
| 对应审查意见 | 审查问题 8（Stage 0.6） |

---

## 8A. Stage 0.6 终审补充决策（ChatGPT 审查结论 CONDITIONAL PASS 后的定点修订）

### AD-29 退回按问题性质分级（`reject_target` 降级为默认值）

| 项 | 内容 |
| --- | --- |
| 决策 | 所有阶段统一采用「问题性质 → 退回层级」分级：**执行层问题退回本阶段；上游内容问题经 `DependencyAnalyzer` 退回对应上游**。`reject_target` 只作为默认值，退回目标由审核意见携带的问题分类决定。[§6.1.5](V3_STAGE0_TARGET_ARCHITECTURE.md#615-reject_target-的通用判定规则与-audio_prod-的分级退回stage-06-终审修订) 给出通用规则与 `audio_prod` 专项分级表 |
| 理由 | 单一 `reject_target` 迫使用户为执行层问题重审整条上游链；`audio_prod` 默认退回 `full_story` 尤其不合理（音频技术问题不应改剧本） |
| 影响 | `ReviewRecord.issues[].code` 必须携带问题分类；工作流层按分类路由；P6 验收增加「audio 三类问题分别路由」用例 |
| 状态 | 已确定 |
| 对应审查意见 | Stage 0.6 终审意见 1 |

### AD-30 共享资源审核记录归属（P2 / P6 实现约束）

| 项 | 内容 |
| --- | --- |
| 决策 | 共享资源审核记录为 **Project 级**（`target_kind ∈ {shared_character, shared_world}`），不携带单一 `story_id`；由 `SharedResourceStore` 写入与查询。Story 级审核**不得改写共享资源**，只能形成变更提案；共享资源变更后的重审是 Story 级的，各引用 Story 独立产生记录；`supersedes` 不得跨归属；查询接口按 `target_kind` 隔离。完整规则见 [目标架构 §6.3.2](V3_STAGE0_TARGET_ARCHITECTURE.md#632-共享资源审核记录归属p2--p6-实现约束) |
| 理由 | 共享档案被多篇 Story 引用，若记录挂在某一篇 Story 下，其他引用它的 Story 无法追溯「这份共享档案被谁审过、审的哪一版」；若允许 Story 级审核直接写共享资源，则一篇 Story 的审核会静默改变其他 Story 的输入 |
| 影响 | `SharedResourceStore` 增加 Project 级审核写入/查询；`ReviewRepository` 增加 `supersedes` 同归属校验；P2 与 P6 验收均须包含 T11 类用例 |
| 不扩大 MVP | 仍不要求跨 Story 自动重新审核编排（MVP 暂缓第 9 项） |
| 状态 | 已确定 |
| 对应审查意见 | Stage 0.6 终审意见 6 |

---

所有未决问题只在 [冻结基线 §11 OPEN QUESTION 总表](V3_STAGE0_6_FINAL_BASELINE.md#11-open-question-总表) 维护，本文件不再保留副本。

原 Stage 0.5 `OQ-1 ~ OQ-6` 的映射：

| 原编号 | 统一编号 |
| --- | --- |
| OQ-1 | `OQ-01` |
| OQ-2 | `OQ-02` |
| OQ-3 | `OQ-03` |
| OQ-4 | `OQ-04` |
| OQ-5 | `OQ-06` |
| OQ-6 | `OQ-05` |

> 迁移方案原 `OQ-M1 ~ OQ-M4` 的映射见 [迁移方案 §9](V3_STAGE0_MIGRATION_PLAN.md#9-待确认事项统一编号)。以上问题**不做猜测**：预算等产品参数不得由开发者替用户决定。

---

## 10. 决策与文档对照

| 决策 | 主要落地文档 | 章节 |
| --- | --- | --- |
| AD-01 / AD-02 | 目标架构 | §1.0 / §1.2 |
| AD-03 / AD-09 | 目标架构 | §3 / §4.1 |
| AD-04 / AD-12~15 | 目标架构 | §6.1 / §6.1.1 / §6.2 / §6.3 |
| AD-05 / AD-16~20 | 目标架构 | §8 / §9 |
| AD-06~08 | 目标架构 | §4.3 / §5 |
| AD-10 / AD-11 | 目标架构 | §7 |
| AD-21~24 | 迁移方案 | §1.3 / §3.2 / §3.4 |
| AD-25 / AD-26 | 开发路线 | §5 / §6 |
| AD-27 / AD-28 / AD-30 | 目标架构 | §3.2 / §3.3 / §4.2 / §4.4 / §6.3.2 |
| AD-29 | 目标架构 | §6.1.1 / §6.1.5 |
| 全部 OQ | 冻结基线 | §11 |
| 范围划分 | MVP 范围 | 全文 |
