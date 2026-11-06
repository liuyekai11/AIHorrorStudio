# V3 STAGE 0（含 Stage 0.5 / Stage 0.6 修订）— 目标架构（AI Story Studio V3）

日期：2026-11-05
版本：**Stage 0.6 修订版**（取代 Stage 0.5 版同名文件）
性质：**设计文档，不含代码改动**。每条设计均标注「继承自 V2 的哪个模块」或「新建」，禁止无理由推翻已有模块。
配套文件：[现有架构审计](V3_STAGE0_CURRENT_ARCHITECTURE_AUDIT.md)、[迁移方案](V3_STAGE0_MIGRATION_PLAN.md)、[执行摘要](V3_STAGE0_EXECUTIVE_SUMMARY.md)、[架构决策](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md)、[MVP 范围](V3_STAGE0_5_MVP_SCOPE.md)、[开发路线](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md)、[修订报告](V3_STAGE0_5_REVIEW_REPORT.md)、[Stage 0.6 冻结基线](V3_STAGE0_6_FINAL_BASELINE.md)。

> 本文件在 Stage 0 初版基础上按 ChatGPT 架构审查意见修订，修订点逐条记录在 [修订报告](V3_STAGE0_5_REVIEW_REPORT.md)。**文件名保留 Stage 0 原名，内容为 Stage 0.6 结论。**
> **本文件 §4.1 的实体清单是 V3.0 实体统计的唯一权威来源**，其它文档一律引用，不另设清单。

---

## 0. 本文件修订摘要

### 0.1 Stage 0.5 修订（保留）

| # | 修订点 | 对应审查意见 |
| --- | --- | --- |
| 1 | 新增 §1.0 产品定位：通用故事创作与短剧生产系统，恐怖为首发验证题材 | 修订任务 1.1 |
| 2 | 新增 §1.2「V2 能力保留清单」，明确渐进式升级 | 修订任务 1.2 |
| 3 | 存储层从「目录化 JSON + index.json」细化为 Repository 接口族，并明确**禁止业务代码直接读写 JSON** | 修订任务 1.3 |
| 4 | 数据模型扩展，补齐 Project : Story = 1 : N | 修订任务 1.4 |
| 5 | Scene/Shot 实体化增加依赖影响分析（下游过期传播），禁止静默覆盖已审内容 | 修订任务 1.5 |
| 6 | ContextEngine 取消「单一优先级表」，改为**三层信息结构**（客观事实 / 角色认知 / 创作指令）+ 能力清单 + 8 个以上冲突场景 | 修订任务 2 |
| 7 | 工作流改为「AI 辅助生成 + AI 独立审核 + 人工最终审核」，**删除原 §3.3 中的 `gate="human_or_ai"`**，AI 通过不得自动放行 | 修订任务 3 |
| 8 | 审核状态从 7 个决策值改为 7 个状态机状态 + 独立的 `decision` 字段 | 修订任务 3.2 |
| 9 | Provider 槽位扩展，并增加文本/媒体能力区分、并发、成本护栏、PromptStore 版本字段 | 修订任务 4 |
| 10 | 删除「借鉴 AI Dev Hub 的 ProviderManager/AIService 思路」的表述，改为自研接口定义 | 项目隔离要求 |

### 0.2 Stage 0.6 修订（审查问题 2 / 3 / 4 / 8 / 6）

| # | 审查指出的问题 | 修订点 |
| --- | --- | --- |
| 11 | Provider 槽位缺少 `audio`，`voice` 与 `audio` 混为一谈 | §8.3 明确 **9 个槽位**，新增 `audio`（音效 / BGM）；明确 `AUDIO` 是能力类型而不是槽位；全文「8 个槽位」统一改为 9 个 |
| 12 | 实体数量统计不统一（8 / 13 / 12 混用） | §4.1 明确 **12 个领域实体 + PromptTemplate 单独归类为创作基础设施对象**；新增**三类来源**统计（V2 可迁移 / V2 嵌套实体化 / V3 全新引入）；作为唯一权威清单 |
| 13 | 13 个阶段与 9 个审核门禁的对应关系不清 | §6.1 重建**唯一阶段定义表**（每阶段 9 个字段）；明确 9 个门禁阶段、其余 4 个阶段免独立门禁的理由、AI 通过≠人工通过、退回产生新版本、审核记录不可删、修改已审内容需重新检查依赖 |
| 14 | Project 级共享资源与 Story 级数据边界不明 | 新增 §4.4「Project / Story 数据边界」；Project 持有共享人物基础档案、共享世界观、共享地点、项目级资源索引；Story 持有创意、大纲、剧情事件，以及该故事中的人物、场景、镜头、审核与视觉资产；列出 8 条边界规则与**需要调整的实体关系** |
| 15 | 实体与阶段改动导致上下文规则需要覆盖跨 Story 共享 | §7.3 增加「共享人物的客观档案 vs 单篇故事中的人物认知」规则；§7.7 增加 T11 场景 |
| 16 | OPEN QUESTION 编号不一致 | §13 改为引用[冻结基线 §11 统一 OPEN QUESTION 注册表](V3_STAGE0_6_FINAL_BASELINE.md#11-open-question-总表)，不再本地编号 |

---

## 1. 设计原则

### 1.0 产品定位

AI Story Studio V3 是**通用 AI 故事创作与短剧生产系统**。

- 首发以**恐怖故事**作为主要验证题材，但架构不得绑定恐怖题材：题材规则、评估维度、Prompt 变体全部走可注册的题材包（GenrePack）。
- 目标用户是**个人创作者**，核心价值是提高故事质量与短剧制作效率。
- **不以构建商业化 SaaS 平台为目标**：不做多租户、不做权限体系、不做在线协作、不做计费。

### 1.1 原则表

| # | 原则 | 说明 |
| --- | --- | --- |
| P1 | **渐进式升级** | V2 项目必须能原样打开；V3 只做加法与受控拆分，不做推倒重来（保留清单见 §1.2） |
| P2 | **数据先于界面** | 先把实体、审核、版本做对，再接入面板 |
| P3 | **模型可替换** | 业务逻辑只依赖 `Slot` + `provider_id`，不依赖任何模型名 |
| P4 | **阶段门禁** | 每个创作阶段产出必须经过审核；**AI 审核通过 ≠ 人工通过**，重要阶段必须人工确认 |
| P5 | **可回滚** | 任何自动化改动（迁移、批量、AI 重写）都必须能回到上一状态 |
| P6 | **题材可插拔** | 恐怖只是第一种题材包 |
| P7 | **UI 薄、逻辑厚** | 新逻辑全部放在可单测的 Python 模块；面板只做展示与回调（沿用 V2 做法） |
| P8 | **接口先于实现** | 业务代码只通过 Repository 访问数据；存储实现（目录 JSON / 未来数据库）可替换 |

### 1.2 V2 能力保留清单（不得无理由重写）

| 能力 | V2 位置 | V3 处理 |
| --- | --- | --- |
| 五阶段故事生成流水线 | `story_engine.pipeline` 及分阶段函数 | 保留，外面包 Provider 接口 |
| JSON 解析链与截断恢复 | `extract_content` / `_strip_fences` / `parse_json_object` / `_repair_json` / `_salvage_truncated_list` | 保留，改为消费 `ChatResult.text` |
| Pacing 时长规划与不变量 | `pacing.py` | 原样保留 |
| 本地质量检查（6 条硬否决） | `story_quality.local_review` | 保留，升级为审核管线第一步 |
| FFmpeg 渲染 | `render_engine.py` | 原样保留 |
| 媒体调用（出图/配音/HTTP） | `image_engine` / `voice_engine` / `sf_http` | 保留，仅解耦反向依赖 |
| 批量失败隔离 | `batch.py` | 保留 |
| API Key 安全设计 | `ai_config` / `sf_config` | 保留（用户目录、打码、不入项目文件） |
| 原子写入 | `ProjectManager.save` 的 `tmp.replace` | 保留并下沉到 `ProjectStore` |
| 版本快照与恢复 | `versions/` + `restore_version` | 保留并扩展覆盖范围 |

---

## 2. 目标分层

在 V2 的六层基础上增加 **AI 抽象层** 与 **工作流层**，其余层保持：

```
表现层    tkinter 面板（沿用 story_panel/timeline/preview/inspector 等，按新实体适配）
应用层    工作流引擎 WorkflowEngine（阶段门禁、审核状态机、审核记录）        [新建]
         └─ 调度 main_window（统一线程/消息通道）                         [重构 A-01]
AI 抽象层 ProviderRegistry / Provider（DeepSeek / OpenAI / SiliconFlow 等）  [新建]
         PromptStore（版本化 Prompt）                                      [新建]
         ContextEngine（三层信息结构 + token 预算）                        [新建]
         UsageLedger / CostGuard（token/成本统计与预算护栏）               [扩展 call_log]
编排层    StoryEngine 五阶段（保留）+ Batch（保留）+ QualityCompare（产品化）
         + ShotRegenerator（单镜重生成）                                  [新建]
领域层    story_schema（扩展）+ pacing + story_quality
         + GenrePack（horror_rules → HorrorPack）                         [扩展]
         + 依赖影响分析 DependencyAnalyzer                                [新建]
数据层    ProjectStore / StoryRepository / CharacterRepository /
         SceneRepository / ShotRepository / VersionStore /
         ReviewRepository / AssetRegistry                                 [新建]
媒体层    image_engine / voice_engine / sf_http / render_engine / media_tools [保留]
```

依赖方向约束（§10 有完整规则）：

```
表现层 → 应用层 → 编排层 → AI 抽象层 → Provider 实现
                       → 领域层 → 数据层（仅通过 Repository 接口）
媒体层只被编排层调用，不得反向依赖 story_engine（修复 A-06）
```

---

## 3. 存储架构

### 3.1 选型结论

采用：**目录化 JSON + Repository 接口 + 原子写入**。**本轮不引入 SQLite。**

| 选项 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| A. 全部塞进 `project.json` | 实现最省事，兼容 V2 | 多实体后单文件非常大，读写整份，并发写风险高 | 仅保留项目元数据与设置 |
| B. 每实体一个 JSON 文件 | 零依赖、易备份、人可读、git 友好、与 V2 哲学一致 | 跨实体查询需自建索引；事务性需自管 | **采用** |
| C. 引入 SQLite | 事务/查询强 | 与 V2 单文件哲学断裂，迁移成本与风险大 | **本轮不采用**；为未来保留接口边界 |

### 3.2 目录布局（目标形态）

```
<项目目录>/
├─ project.json                      项目元数据 + settings + schema_version
├─ shared/                           ★ Project 级共享资源（可被多篇 Story 引用）
│  ├─ index.json                     共享资源索引（派生、可重建）
│  ├─ characters/<character_id>.json 共享人物基础档案
│  ├─ world/<setting_id>.json        共享世界观基础设定（scope=project）
│  └─ places/<place_id>.json         共享地点与基础资料（WorldSetting kind=place, scope=project）
├─ stories/
│  └─ <story_id>/
│     ├─ story.json                  故事元数据 / 创意 / 大纲 / 脚本 / 阶段状态 / active_version
│     ├─ characters/<character_id>.json   故事级人物（引用或扩展共享档案）
│     ├─ relationships/<rel_id>.json
│     ├─ world/<setting_id>.json     故事级补充设定（scope=story）
│     ├─ events/<event_id>.json
│     ├─ knowledge/<character_id>/<state_id>.json
│     ├─ scenes/<scene_id>.json
│     ├─ shots/<shot_id>.json
│     ├─ shots/<shot_id>/versions/<rev>.json
│     └─ assets/<asset_id>.json
├─ story/index.json                  story_id 列表（派生、可重建；Pointer 字段待 OQ-09 确认）
├─ reviews/<review_id>.json          审核记录（只追加）
├─ versions/<version_id>.json        story 级快照（沿用 V2）
├─ images/ audio/ subtitles/ output/ temp/
└─ migration_report.json             迁移后生成（如有）
```

> 目录名与实体名的对应关系在 P1 落地时可再收敛，但**稳定 ID 作为文件名**这一条不变。
>
> 说明：`story/index.json` 与 `stories/` 目录在命名上不够一致（历史原因保留 `story/` 顶层目录名以最大化与 V2 相似，便于人工检查）。该点作为 [OQ-09](V3_STAGE0_6_FINAL_BASELINE.md#11-open-question-总表) 记录，P1 落地前确认最终布局。

### 3.3 Repository 接口族（业务代码唯一数据入口）

| 接口 | 职责 | 主要方法（示意） | 责任边界 |
| --- | --- | --- | --- |
| `ProjectStore` | `project.json` 读写、schema_version、原子写 | `load(project)` / `save(project, data)` / `schema_version(project)` | Project 级 |
| `SharedResourceStore` | Project 级共享人物档案、共享世界观、共享地点、**引用索引** | `get_shared` / `list_shared` / `upsert_shared` / `referrers(entity_id)` | Project 级 |
| `StoryRepository` | Story 元数据、大纲、脚本、阶段状态 | `get` / `list` / `create` / `update_meta` / `set_stage_state` | Story 级 |
| `CharacterRepository` | 某 Story 中的人物视图（引用共享档案或故事级角色）与关系 | `get` / `list_by_story` / `upsert` / `delete(soft)` / `resolve_shared` | Story 级 |
| `SceneRepository` | 场景实体 | `get` / `list_by_story` / `upsert` | Story 级 |
| `ShotRepository` | 镜头实体与镜头版本 | `get` / `list_by_scene` / `upsert` / `add_version` / `set_active_version` | Story 级 |
| `VersionStore` | story/场景/镜头级快照与恢复 | `snapshot` / `restore` / `prune` / `referenced_by` | Story 级 |
| `ReviewRepository` | 审核记录（只追加） | `append` / `list_by_target` / `latest` | Story 级 |
| `AssetRegistry` | 素材索引（图片/音频/视频候选） | `register` / `list_by_shot` / `attach` / `detach` | Story 级 |

> Stage 0.6 变化：原 8 个接口扩展为 **9 个**——新增 `SharedResourceStore` 承担 Project 级共享资源（见 §4.4），分担了原 `CharacterRepository` 中属于 Project 级的职责。**实体数量（12）与 Repository 数量（9）是两个不同口径**，不得混用。

约束：

1. **禁止**业务代码（编排层、应用层、领域层）直接 `open()` 任何实体 JSON。
2. 所有写操作必须经 Repository，并由 Repository 统一使用原子写（`tmp.replace`，沿用 V2）。
3. Repository 只做数据访问，**不承载业务规则**（门禁、审核判定在应用层/领域层）。
4. 接口形态要能映射到未来数据库实现（主键、外键、索引概念在接口上可表达），但**不提前实现 SQLite**。

### 3.4 一致性模型

- 单实体写入：原子（`tmp.replace`）。
- 多实体写入（如导入故事、批量替换镜头）：使用「**暂存目录写入 → 目录级切换**」，见 [迁移方案 §3.4](V3_STAGE0_MIGRATION_PLAN.md#34-迁移事务模型stage-06-修订逐步骤可恢复提交日志)。
- 迁移暂存目录内部结构（Stage 0.6 终审补充 R4）：`.migration_staging/<tx_id>/transaction.json`（事务日志）与 `.migration_staging/<tx_id>/payload/`（被复制的项目内容）**物理隔离**；payload 树哈希范围 = `payload/` 内完整项目树（`transaction.json` 在其父目录、结构上不在范围内；`payload/` 内出现 `transaction.json` 判结构非法，不得按文件名排除），`.migration_tmp/` 只按相对路径排除，哈希前先做结构合法性检查；不完整时只删 `payload/`、保留日志。目录与哈希边界以[迁移方案 §3.4.1 / 「哈希计算范围」](V3_STAGE0_MIGRATION_PLAN.md#341-目录布局项目外暂存与备份)为唯一权威。
- `index.json` 为**派生的可重建索引**，任何时刻都可以由目录扫描重建；不允许把它当作唯一真源。
- 引用完整性（`scene_id` / `shot_id` / `character_id`）由 Repository 在写入前后校验，并有一个只读的 `check_integrity()` 供测试与启动自检使用。

---

## 4. 核心实体与数据模型

### 4.1 实体清单（**12 个领域实体** + 1 个创作基础设施对象）

> **本表是 V3.0 实体统计的唯一权威来源。** 任何文档中的实体数量必须与本节一致；其它统计口径（如 Repository 数量、迁移表数量）必须显式说明是不同的口径。

#### 4.1.1 领域实体（12 个）

| # | 实体 | 来源分类 | 说明 |
| --- | --- | --- | --- |
| 1 | `Project` | **A. V2 已存在且可迁移** | 项目根；`project.json` 顶层 `name/settings/schema_version` |
| 2 | `Story` | **A. V2 已存在且可迁移** | 聚合根；新增 `genre_id`、`stage_states`。**Project 1 : N Story** |
| 3 | `StoryVersion` | **A. V2 已存在且可迁移** | `versions/` 快照机制保留，扩展覆盖范围（含 scenes/shots 的已审状态） |
| 4 | `Character` | **A. V2 已存在且可迁移**（新增共享档案 + 故事级扩展两处存储，见 §4.4） | `CharacterProfile` 扩展 |
| 5 | `CharacterRelationship` | **C. V3 全新引入** | 两角色之间的有向关系（V2 只是在人物描述文本中隐含关系，无结构化数据） |
| 6 | `WorldSetting` | **C. V3 全新引入** | 世界规则 / 地点 / 组织 / 禁忌（V2 无字段） |
| 7 | `PlotEvent` | **C. V3 全新引入** | 时间线事件，可关联角色/场景/镜头（V2 只有 `plan` 文本） |
| 8 | `CharacterKnowledgeState` | **C. V3 全新引入** | 某角色在某时间点/场景的已知/未知/误解/隐瞒信息 |
| 9 | `Scene` | **B. V2 原有嵌套结构，需实体化** | 从 `story.scenes[]`（`SceneProfile`）升格为独立文件；**独立 Repository / 稳定主键 / 依赖分析 / 审核属于 V3 新增能力** |
| 10 | `Shot` | **B. V2 原有嵌套结构，需实体化** | 合并 story 内嵌分镜（`story.shots[]`）与时间轴镜头（`project.shots[]`）；**镜头级版本、单镜重生成、镜头级审核属于 V3 新增能力** |
| 11 | `VisualAsset` | **C. V3 全新引入** | 角色定妆照 / 风格参考 / 镜头候选图（多候选）（V2 素材只是 Shot 上的字段） |
| 12 | `ReviewRecord` | **C. V3 全新引入** | 见 §6.3（V2 不存审核记录） |

#### 4.1.2 创作基础设施对象（不计入领域实体）

| 对象 | 来源分类 | 说明 |
| --- | --- | --- |
| `PromptTemplate` | **C. V3 全新引入** | PromptStore 的持久化对象（7 字段见 §8.6）；**存储在用户配置目录，不随项目走**，因此不属于项目数据，也不计入领域实体 |

#### 4.1.3 分类统计

| 来源分类 | 数量 | 实体 |
| --- | --- | --- |
| A. V2 已存在且可迁移 | **4** | Project / Story / StoryVersion / Character |
| B. V2 原有嵌套结构，需要实体化 | **2** | Scene / Shot |
| C. V3 全新引入 | **6** | CharacterRelationship / WorldSetting / PlotEvent / CharacterKnowledgeState / VisualAsset / ReviewRecord |
| **合计（领域实体）** | **12** | — |
| 另：创作基础设施对象 | 1 | PromptTemplate（不计入 12） |

> **口径说明（避免旧统计混用）**：
> - Stage 0 初版曾写「8 个数据模型 / 5 个全新」，只统计了当时的模型，未含 Project 拆分与 Scene/Shot 的 Repository 化；
> - Stage 0.5 曾写「13 个数据模型」，把 PromptTemplate 计入领域实体；
> - **Stage 0.6 起统一为：12 个领域实体 + 1 个创作基础设施对象**。上述旧数字全部作废。

### 4.2 实体定义模板

每个实体必须明确以下 9 项。下表列出全部实体的最终定义：

#### Project

| 项 | 内容 |
| --- | --- |
| 主键 | 目录路径（项目目录本身） |
| 所属 | 无（根） |
| 核心字段 | `name` / `created_at` / `settings` / `schema_version` |
| 引用 | 无（Story 反向引用它） |
| 生命周期 | 用户创建 / 删除；删除走 `create_project` 反方向（需显式确认） |
| 版本策略 | 无版本化（设置变更直接覆盖） |
| 删除策略 | 仅整目录删除，需用户确认 |
| 审核要求 | 无 |
| 存储 | `project.json` |

#### Story

| 项 | 内容 |
| --- | --- |
| 主键 | `story_id`（V2 单 story 迁移时由 project 名映射生成，见迁移方案） |
| 所属 | Project（1 : N，**不得在模型层限制为 1 : 1**） |
| 核心字段 | `title` / `logline` / `genre_id` / `concept_id`（选中的创意）/ `outline` / `script` / `pacing` / `stage_states` / `active_version` |
| 引用 | `characters[]` / `world[]` / `events[]` / `scenes[]`（均由 ID 引用） |
| 生命周期 | 创建后长期存在；可「归档」不可静默删除 |
| 版本策略 | `StoryVersion` 快照（沿用 10 版上限，区分 human/batch/import 来源） |
| 删除策略 | 软删除（`archived=true`）；硬删除需用户确认且保留最后一版备份 |
| 审核要求 | Stage 状态必须经人工确认才能推进（§6） |

#### StoryVersion

| 项 | 内容 |
| --- | --- |
| 主键 | `version_id` |
| 所属 | Story |
| 核心字段 | `story_id` / `created_at` / `source`（human/batch/import/restore）/ `scope`（覆盖哪些实体）/ `payload_ref` / `note` |
| 引用 | 被 `Story.active_version` 引用；被 `ReviewRecord.target_version` 引用 |
| 生命周期 | 追加，不修改 |
| 版本策略 | 保留最近 10 版（沿用 V2），被引用的版本不裁剪 |
| 删除策略 | 只能由 `prune` 删除未被引用的旧版本 |
| 审核要求 | 无（审核针对 Story 当前内容） |
| 存储 | `versions/<version_id>.json`（项目级目录，按 `story_id` 区分） |

#### Character（共享基础档案 + 故事级角色，见 §4.4）

| 项 | 内容 |
| --- | --- |
| 主键 | `character_id`（沿用 V2 `CharacterProfile.character_id`） |
| 所属 | **两段式**：① 共享基础档案属于 Project（`scope=project`）；② 故事级角色属于 Story（`scope=story`，可 `shared_ref=character_id` 引用共享档案并在其中覆盖/补充字段） |
| 核心字段 | `name` / `role` / `look` / `motivation` / `secret` / `voice` / `scope` / `shared_ref` |
| 引用 | `scene_ids[]` → Scene；被 `CharacterRelationship` / `PlotEvent` / `CharacterKnowledgeState` / `Shot.character_ids` 引用 |
| 生命周期 | 共享档案随 Project；故事级角色随 Story；被引用时不可删 |
| 版本策略 | 无独立版本（变更经 Story 快照覆盖；共享档案变更记入所有引用它的 Story 的依赖记录） |
| 删除策略 | 软删除；有引用时阻塞并提示（共享档案被任一 Story 引用时不可删） |
| 审核要求 | 人工审核（`character_world` 阶段） |
| 存储 | 共享：`shared/characters/<character_id>.json`；故事级：`stories/<story_id>/characters/<character_id>.json` |

#### CharacterRelationship

| 项 | 内容 |
| --- | --- |
| 主键 | `rel_id` |
| 所属 | Story |
| 核心字段 | `from_character_id` / `to_character_id` / `kind`（亲属/敌对/上下级…）/ `strength` / `note` / `asymmetric`（有向性说明） |
| 引用 | 两端 Character |
| 生命周期 | 随 Story；两端角色存在时不自动删 |
| 版本策略 | 无独立版本 |
| 删除策略 | 软删除 |
| 审核要求 | 人工审核（CharacterDesign 阶段，与人物一并审） |
| 存储 | `stories/<story_id>/relationships/<rel_id>.json` |

#### WorldSetting

| 项 | 内容 |
| --- | --- |
| 主键 | `setting_id` |
| 所属 | **两段式**：`scope=project` 的共享设定属于 Project；`scope=story` 的补充设定属于 Story |
| 核心字段 | `kind`（rule/place/org/taboo）/ `title` / `content` / `hard`（硬规则：不得被 AI 违反）/ `scope` |
| 引用 | 可被 PlotEvent / Shot 引用（`world_refs[]`） |
| 生命周期 | 共享设定随 Project；Story 级设定随 Story |
| 版本策略 | 无独立版本；`hard=true` 的规则变更必须重新审核下游 |
| 删除策略 | 软删除；被引用时提示影响面（共享设定被任一 Story 引用时不可删） |
| 审核要求 | 人工审核（`character_world` 阶段） |
| 存储 | 共享：`shared/world/<setting_id>.json`、`shared/places/<place_id>.json`；Story 级：`stories/<story_id>/world/<setting_id>.json` |

#### PlotEvent

| 项 | 内容 |
| --- | --- |
| 主键 | `event_id` |
| 所属 | Story |
| 核心字段 | `timeline_order`（数值，排序用）/ `when`（故事内时间）/ `summary` / `scene_id` / `participants[]`（character_id）/ `causes[]` / `effects[]` |
| 引用 | Character / Scene |
| 生命周期 | 随 Story（不跨 Story 共享） |
| 版本策略 | 无独立版本 |
| 删除策略 | 软删除；下游引用检查 |
| 审核要求 | 人工审核（`outline` 阶段） |
| 存储 | `stories/<story_id>/events/<event_id>.json` |

#### CharacterKnowledgeState

| 项 | 内容 |
| --- | --- |
| 主键 | `state_id` |
| 所属 | Story + Character |
| 核心字段 | `character_id` / `at_event_id` 或 `at_scene_id`（二选一，可为空=初始状态）/ `knows[]` / `does_not_know[]` / `misbelieves[]` / `conceals[]` / `learned_at` |
| 引用 | Character / PlotEvent / Scene |
| 生命周期 | 随 Story；按时间点追加 |
| 版本策略 | **追加式**：状态随剧情推进新增记录，不修改历史记录 |
| 删除策略 | 软删除 |
| 审核要求 | 人工审核（随 `full_story` / `scene_breakdown` 阶段审） |
| 存储 | `stories/<story_id>/knowledge/<character_id>/<state_id>.json` |

#### Scene

| 项 | 内容 |
| --- | --- |
| 主键 | `scene_id`（沿用 V2 `SceneProfile.scene_id`） |
| 所属 | Story |
| 核心字段 | `name` / `look` / `lighting` / `props` / `order`（仅排序）/ `character_ids[]` / `event_ids[]` |
| 引用 | Character / PlotEvent；被 Shot、StoryVersion 引用 |
| 生命周期 | 随 Story（不跨 Story 共享） |
| 版本策略 | 场景拆分调整时快照 |
| 删除策略 | 有 Shot 引用时阻塞；允许「归档」 |
| 审核要求 | 人工审核（`scene_breakdown` 阶段） |
| 存储 | `stories/<story_id>/scenes/<scene_id>.json` |

#### Shot

| 项 | 内容 |
| --- | --- |
| 主键 | `shot_id`（迁移时**沿用 V2 shot_id**） |
| 所属 | Scene |
| 核心字段 | `scene_id` / `order`（仅排序）/ `beat` / `image_prompt` / `narration` / `motion` / `duration` / `character_ids[]` / `world_refs[]` / `version` / `active_version` / `assets[]` / `status` / `depends_on[]` / `legacy_timeline_id` |
| 引用 | Scene / Character / WorldSetting / VisualAsset |
| 生命周期 | 随 Scene；orphan 不自动删 |
| 版本策略 | **多版本**（`versions/<rev>.json`），单镜重生成产生新版本，旧版本保留 |
| 删除策略 | 软删除；`orphan_timeline_shot` 保留为「未关联」分组 |
| 审核要求 | 人工审核（`shot_design` / `image_gen` 阶段） |
| 存储 | `stories/<story_id>/shots/<shot_id>.json` |

#### VisualAsset

| 项 | 内容 |
| --- | --- |
| 主键 | `asset_id` |
| 所属 | Shot 或 Character（定妆照） |
| 核心字段 | `kind`（image/video/audio/reference）/ `path` / `candidate_of`（同组候选）/ `prompt_id` / `provider_id` / `model` / `created_at` / `approved` |
| 引用 | Shot / Character；被 ReviewRecord 引用 |
| 生命周期 | 随宿主实体；删除素材只解除引用，不删文件（除非用户确认） |
| 版本策略 | 每次生成追加；`approved` 标记决定使用哪个 |
| 删除策略 | 解引用，文件保留在 `images/` 等目录 |
| 审核要求 | 人工审核（`image_gen` / `video_gen` 阶段） |
| 存储 | `stories/<story_id>/assets/<asset_id>.json` |

#### ReviewRecord

见 §6.3。

### 4.3 实体关系

```
Project 1─* Story                                  （不限制为 1:1）
Project 1─* Character[scope=project]              （共享基础档案，见 §4.4）
Project 1─* WorldSetting[scope=project]           （含 kind=place 的共享地点）
Story   1─* Character[scope=story] ── shared_ref? ──▶ Character[scope=project]
Story   1─* Character[scope=story] *──* CharacterRelationship（关系仅在本 Story 内有效）
Story   1─* WorldSetting[scope=story]              （故事级补充设定）
Story   1─* PlotEvent ──* Character[scope=story]（参与者）
Character[scope=story] 1─* CharacterKnowledgeState ──1 PlotEvent / Scene（时间点）
Story   1─* Scene 1─* Shot 1─* (versions)
Character[scope=story] 1─* VisualAsset（定妆照 / 故事专属素材）   Shot 1─* VisualAsset（镜头候选）
Story   1─* StoryVersion
*       1─* ReviewRecord（多态：target_kind / target_id / target_version）
```

**需要调整的关系（相对 Stage 0.5，审查问题 8）**：

| 原关系（Stage 0.5） | 调整为（Stage 0.6） | 原因 |
| --- | --- | --- |
| `Story 1─* Character` | `Project 1─* Character[scope=project]` + `Story 1─* Character[scope=story]`，后者可 `shared_ref` 前者 | 同一人物在不同故事中需要共享外观/身份/口吻等基础档案，但故事细节可以不同 |
| `Story 1─* WorldSetting` | `Project 1─* WorldSetting[scope=project]` + `Story 1─* WorldSetting[scope=story]` | 同一世界观下的系列故事必须共享硬规则 |
| `Character 1─* CharacterKnowledgeState` | **`Character[scope=story]`** 1─* CharacterKnowledgeState | 认知（谁知道什么）只对某一篇故事有意义，绝不能跨 Story 共享 |
| `Story 1─* CharacterRelationship` | 不变，但必须在文档中明确：关系是**故事限定**的，即使共享同一人物档案 | 同一对人物在不同故事中的关系可以不同 |
| `* 1─* ReviewRecord` | 不变，但 `target_kind` 增加 `shared_character` / `shared_world` | 共享资源的审核记录必须可追溯，并影响所有引用它的 Story；归属规则见 §6.3.2 |

---

### 4.4 Project 级共享资源与 Story 级数据边界（Stage 0.6 新增）

采用 **Project 级共享资源 + Story 级剧情数据**。

#### 4.4.1 Project 级资源

| 资源 | 存储 | 说明 |
| --- | --- | --- |
| 项目基础信息 | `project.json` | 名称 / 设置 / `schema_version` |
| 共享人物基础档案 | `shared/characters/<character_id>.json` | 外观、真实身份、口吻、基础动机等「跨故事一致」的字段 |
| 共享世界观基础设定 | `shared/world/<setting_id>.json` | 世界规则、组织、禁忌等 `hard` 规则 |
| 共享地点与基础资料 | `shared/places/<place_id>.json` | `WorldSetting(kind=place, scope=project)` |
| 项目级资源索引 | `shared/index.json` | 记录每个共享资源被哪些 Story 引用（派生、可重建） |

#### 4.4.2 Story 级数据

| 数据 | 存储 | 说明 |
| --- | --- | --- |
| 故事创意 | `stories/<story_id>/story.json` → `ideas[]` | 候选创意与选中创意（`concept_id`） |
| 故事大纲 | `stories/<story_id>/story.json` → `outline` | 本故事的结构 |
| 故事级人物 | `stories/<story_id>/characters/` | 只在本故事出现的角色，或对共享档案的本故事扩展 |
| 故事级世界观补充 | `stories/<story_id>/world/` | 本故事特有的设定 |
| 人物关系 | `stories/<story_id>/relationships/` | 仅在本故事内有效 |
| 剧情事件 | `stories/<story_id>/events/` | 本故事时间线 |
| 角色认知状态 | `stories/<story_id>/knowledge/` | 本故事中「谁在何时知道什么」 |
| StoryVersion | `versions/<version_id>.json` | 本故事的快照 |
| Scene / Shot | `stories/<story_id>/scenes/`、`shots/` | 本故事的场景与镜头 |
| 故事审核记录 | `reviews/<review_id>.json`（`target_kind` 指向 Story 级对象） | 审核属于某一故事 |
| 故事专属视觉资产 | `stories/<story_id>/assets/` | 本故事的镜头候选图、定妆照变体 |

#### 4.4.3 八条边界规则

1. **Character 可以被多篇 Story 引用。** 通过 `Character[scope=story].shared_ref` 指向 `Character[scope=project]`。
2. **CharacterKnowledgeState 必须属于具体 Story。** 认知状态没有「项目级」概念，不允许出现在 `shared/`。
3. **共享人物的客观档案与单篇故事中的人物认知不能混淆。** 共享档案是「作者视角的真相」，认知状态是「某篇故事里某角色在某时刻知道的」；ContextEngine 分别从 §7.2 与 §7.3 读取（见 §7.3 规则 5）。
4. **WorldSetting 可以包含项目级共享设定和 Story 级补充设定。** `scope` 字段区分；同一 `setting_id` 的共享版本与故事版本是两条记录，不互相覆盖。
5. **修改共享人物或世界观时，必须检查引用它的 Story。** `SharedResourceStore.referrers(entity_id)` 列出所有引用；修改前必须展示影响清单。
6. **已有 Story 不得被静默修改。** 共享资源变更对某个 Story 的影响表现为「该 Story 的相关对象标记 `stale` + 待审核」，而不是直接改写该 Story 的已审内容。
7. **共享资源修改产生依赖影响记录。** 每次共享资源变更写一条 `DependencyImpact` 记录（`entity_id` / 变更摘要 / 受影响 `story_id` 列表 / 时间 / 是否已处理），作为审计依据。
8. **V3.0 可以先实现基础共享能力，不要求一次性完成复杂的跨故事依赖管理。** V3.0 至少实现：共享档案 CRUD + `referrers()` 查询 + 修改前影响提示 + 标记 `stale`；跨 Story 的自动重新审核编排可以留到后续版本（见 [MVP §3](V3_STAGE0_5_MVP_SCOPE.md#3-v30-暂缓的功能架构预留不在-v30-交付)）。
9. **共享资源的审核记录属于 Project 级**（`target_kind ∈ {shared_character, shared_world}`），不携带单一 `story_id`；Story 级审核不得改写共享资源，只能产生变更提案。完整归属规则见 [§6.3.2](#632-共享资源审核记录归属p2--p6-实现约束)。

#### 4.4.4 迁移与共享资源的关系

- V2 项目是单 story：迁移时，原 `story.characters[]` **优先迁入 Story 级**（`stories/<story_id>/characters/`），**不自动提升为共享档案**（无法判断哪些字段是「跨故事一致」的），避免替用户做决定。
- 用户后续可显式执行「提取为共享人物」，产生 `shared/characters/` 记录并建立 `shared_ref`；该操作有依赖影响记录（规则 7）。
- 当前代码中**不存在**共享资源能力，属 P2 新增。

---

## 5. Scene / Shot 实体化设计

### 5.1 目标

解决双轨制（审计 §6、风险 R2 / R7）：

| V3 需求 | 目标状态 |
| --- | --- |
| Scene 独立数据实体 | 独立文件 `scenes/<scene_id>.json` |
| Shot 独立数据实体 | 独立文件 `shots/<shot_id>.json` |
| 数据关联 | 全部使用稳定 ID，**禁止以 `story_index` / 位置作为关联依据** |
| 单镜重生成 | `ShotRegenerator.regenerate(shot_id)` 产出新版本 |
| 镜头审核 | 按 `shot_id` 单独审核 |
| 旧时间轴素材 | 保留在 `assets[]`，原始文件不移动 |
| Orphan Shot | 不自动删除，归入「未关联」分组 |
| 回滚 | 保留 `legacy_timeline_id`，可映射回 V2 时间轴 |

### 5.2 Shot 字段

| 字段 | 说明 |
| --- | --- |
| `shot_id` | 稳定主键（导入 V2 时沿用原 shot_id） |
| `scene_id` | 所属场景（强引用，删除场景时校验） |
| `order` | 场景内序号（**仅排序**，不承担关联职责） |
| `character_ids` | 出场角色 |
| `world_refs` | 引用的世界设定 |
| `version` / `active_version` | 镜头级版本，支持单镜重生成 |
| `status` | 见 §6.2 |
| `assets[]` | `asset_id` 列表（图像/视频/配音候选），替代 V2 的 `image`/`ai_image` 散落字段 |
| `depends_on` | 上游依赖（如需要连续性的前序镜头） |
| `review_id` | 最近一次审核记录 |

### 5.3 单镜重生成

`ShotRegenerator.regenerate(shot_id, ...)`：

1. 通过 `ShotRepository` 读取当前版本；
2. 通过 `ContextEngine` 组装该镜头上下文（§4 三层信息）；
3. 通过 `ProviderRegistry` 解析 `writer` 槽位生成新内容；
4. 写入新版本（`versions/<rev>.json`），`active_version` 指向新版本，**旧版本保留**；
5. 仅影响该镜头，不改动 story 其他部分；
6. 若该镜头此前已 `human_approved`，新版本状态回到 `pending`，**不覆盖旧审核记录**。

### 5.4 依赖影响分析（新增，修订任务 1.5 要求）

引入 `DependencyAnalyzer`（领域层，纯逻辑、可单测），在任何实体被修改时计算下游影响：

| 上游变更 | 检查的下游 | 处理 |
| --- | --- | --- |
| Character 的外观 / 身份 / 秘密变化 | 该角色出场的 Shot、引用其的 VisualAsset、含该角色的 Scene、依赖该角色的 PlotEvent、相关 CharacterKnowledgeState | 下游 Shot 标记 `stale=true`，相关素材标记「可能过期」 |
| Scene 的 look / lighting / props 变化 | 该 Scene 下全部 Shot、镜头候选图 | 同上 |
| WorldSetting（`hard=true`）变化 | 引用它的 Shot、Event | 同上，并强制重新审核 |
| Shot 内容变化 | 该 Shot 的既有素材候选 | 旧素材保留但标记过期，`active_version` 不变直到批准 |
| StoryVersion 恢复 | 全部下游实体 | 走迁移式一致性检查，不做静默覆盖 |

硬规则：

1. **不得静默覆盖已审核通过的镜头和素材**：任何影响已批准内容的变更必须产生「待审核」状态。
2. `stale` 标记本身是派生状态，可通过 `DependencyAnalyzer` 全量重算验证一致性。
3. 依赖关系以 ID 表达，不依赖顺序。

---

## 6. 工作流与人工审核

### 6.1 阶段流程（Stage 0.6 修订：唯一阶段定义表）

采用：**AI 辅助生成 + AI 独立审核 + 人工最终审核**。重要阶段必须人工明确确认后才能进入下一阶段。

**禁止采用 AI 审核通过后自动放行的模式。**

共 **13 个工作流阶段**（§6.1.1），其中 **9 个审核门禁**（§6.1.2）。

```
story_idea ──人工门禁──▶ outline ──人工门禁──▶ character_world ──人工门禁──▶ full_story
                                                                              │
                                                              AI 独立审核 + 人工门禁
                                                                              ▼
scene_breakdown ──人工门禁──▶ shot_design ──人工门禁──▶ visual_assets ──人工门禁──▶ image_gen
                                                                                       │
                                                                        video_gen ◀────┘
                                                                        （人工门禁）
                                                                                       │
                                                                        audio_prod ◀───┘
                                                                        （人工门禁）
                                                                                       │
                                                                        post_prod ─────┘
                                                                        （人工门禁）
                                                                                       │
                                                                        final_review ──┘
                                                                        （人工门禁）
                                                                                       │
                                                                   export（门禁 = final_review 已 human_approved）
```

> 图片 / 视频 / 音频三者内部的生产顺序可按实际工序调整（`video_gen` 与 `audio_prod` 之间在架构上无强依赖），但**人工确认环节不得取消**。

#### 6.1.1 唯一阶段定义表（全文以此表为准）

| stage_id | stage_name | ai_generation | ai_review | human_review | gate_required | pass_condition | reject_target | dependencies |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `story_idea` | 故事创意 | 是（`concept`） | 否 | **是** | 是 | 本 Story 选定 1 个创意（`concept_id`）且状态 `human_approved` | 自身 | 无 |
| `outline` | 故事大纲 | 是（`planner`） | 否 | **是** | 是 | 大纲已生成且 `human_approved` | `story_idea` | `story_idea` |
| `character_world` | 人物设计 + 世界观 | 是（`planner`） | 否 | **是** | 是 | 本 Story 至少 1 个角色与 1 条世界观设定，且 `human_approved` | `outline` | `outline` |
| `full_story` | 完整故事 | 是（`writer`） | **是（`reviewer`）** | **是** | 是 | AI 审核完成（记录存在）+ 人工 `human_approved` | `outline` | `character_world` |
| `scene_breakdown` | 场景拆分 | 是（`planner`） | 否 | **是** | 是 | Scene 实体已生成且 `human_approved` | `full_story` | `full_story` |
| `shot_design` | 镜头设计 | 是（`writer`） | 否 | **是** | 是 | 全部 Shot 已生成且整阶段 `human_approved` | `scene_breakdown` | `scene_breakdown` |
| `visual_assets` | 视觉设定 | 是（`image` 参考图 / `fast` 提示词） | 否 | **是** | 是 | 角色定妆与风格参考已批准 | `character_world` | `shot_design` |
| `image_gen` | 图片生成 | 是（`image`） | 否 | **是** | 是 | 每个需出图的 Shot 至少 1 个已批准候选（`approved=true`） | `shot_design` | `visual_assets` |
| `video_gen` | 视频生成 | 是（`video`） | 否 | **是** | 是 | 需视频的 Shot 均有已批准视频候选 | `shot_design` | `image_gen` |
| `audio_prod` | 音频制作 | 是（`voice` / `audio`） | 否 | **是** | 是 | 配音、音效、BGM 均已生成并 `human_approved` | **按问题性质分级**（见 §6.1.5）：音频技术 → 本阶段；剧本内容 → 经 `DependencyAnalyzer` 判定 `full_story`；镜头表达 → `shot_design` | `image_gen` |
| `post_prod` | 后期合成 | 否（本地渲染） | 否 | **是** | 是 | 成片（或分段成片）产出且 `human_approved` | `video_gen` / `audio_prod` | `video_gen`, `audio_prod` |
| `final_review` | 最终审核 | 否 | **是（`reviewer`，整片质量审核）** | **是** | 是 | 人工最终确认 `human_approved` | `post_prod` | `post_prod` |
| `export` | 导出 | 否 | 否 | **否**（不独立审核） | **是**（前置条件型） | `final_review` 为 `human_approved`，字段完整性校验通过 | `final_review` | `final_review` |

#### 6.1.2 9 个审核门禁对应哪 9 个阶段

**门禁 = 存在人工放行决策、且该决策是从本阶段进入下游的必要条件。** 9 个门禁阶段：

| # | 门禁阶段 | 放行条件 |
| --- | --- | --- |
| 1 | `story_idea` | 人工选定创意 |
| 2 | `outline` | 人工通过大纲 |
| 3 | `character_world` | 人工通过人物与世界观 |
| 4 | `full_story` | 人工通过完整故事（AI 审核记录必须已存在） |
| 5 | `scene_breakdown` | 人工通过场景拆分 |
| 6 | `shot_design` | 人工通过镜头设计 |
| 7 | `visual_assets` + `image_gen` | 人工通过视觉设定**且**逐个通过候选图（合为「视觉生产」门禁，见下方说明） |
| 8 | `audio_prod` + `video_gen` | 人工通过音频与视频（合为「音视频生产」门禁） |
| 9 | `post_prod` + `final_review` | 人工通过成片（合为「成片」门禁） |

**为什么合并而不是每个阶段单独计一个门禁**：门禁是**人工作业的批次**，不是阶段 ID 的镜像。同一批次中用户一次审完（例如一次审完全部候选图、一次审完成片），强行拆成独立门禁会让 UI 反复弹确认。合并只影响门禁计数与 UI 分组，**不降低任何阶段的审核要求**——上表中每个阶段仍有独立的 `human_approved` 状态与 ReviewRecord。

> 审查意见提示「如果 9 个门禁划分不合理，可以提出修订方案，但必须说明理由」。Stage 0.6 保留 9 个门禁，但给出上述明确的阶段对应关系；此对应关系由 [AD-12（Stage 0.6 修订）](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md#ad-12-九个审核门禁与-13-个阶段的唯一映射stage-06-修订) 记录。

#### 6.1.3 其余阶段为什么不需要（或不需要独立）审核门禁

| 阶段 | 是否人工审核 | 原因 |
| --- | --- | --- |
| `export` | 否 | 导出本身不改变创作内容，只做格式转换与打包；其安全性完全由前置条件（`final_review=human_approved`）保证。若允许导出「未过最终审核」的内容，会有绕过门禁的风险，所以 export 仍有**前置条件型**门禁。 |

除 `export` 外，其余 12 个阶段都有人工审核，只是门禁按 §6.1.2 合并为 9 个批次。

#### 6.1.4 门禁的六条硬规则

1. **AI 通过不能替代人工通过。** `ai_passed` 只是信号，不能自动转换为 `human_approved`（§6.2 硬规则 2）。
2. **只有满足人工放行条件，才可以进入下游阶段。** 工作流层在每个阶段开始时校验上游阶段状态；未满足即拒绝执行 AI 生成（避免用户花冤枉钱。
3. **退回后重新生成的内容必须形成新版本。** `revision_requested` → 重新生成 → 新 `StoryVersion` 或新 Shot 版本；旧版本保留，`active_version` 指向新版本。
4. **原有审核记录不能删除。** 只追加（§6.3）；新审核记录通过 `supersedes` 串成链。
5. **修改已审核内容必须重新检查依赖和审核状态。** `DependencyAnalyzer` 计算下游影响（§5.4），受影响对象标记 `stale` 并回到 `pending`。
6. **不许为了凑门禁数量而遗漏审核。** 门禁合并（§6.1.2）只改变 UI 批次，不改变任何阶段的审核状态要求。

#### 6.1.5 `reject_target` 的通用判定规则与 `audio_prod` 的分级退回（Stage 0.6 终审修订）

**通用规则（适用于全部 13 个阶段）**：`reject_target` 是**默认退回目标**，不是唯一允许的退回点。审核意见必须先分类**问题性质**，再决定退回层级：

| 问题性质 | 判定 | 退回目标 |
| --- | --- | --- |
| **执行层问题**（生成参数、素材质量、技术错误） | 该阶段产物未达要求，上游输入正确 | 本阶段（重新生成本阶段产物） |
| **上游内容问题**（剧本/设定/镜头设计内容错误） | 根源在上游已审内容 | 经 `DependencyAnalyzer` 计算受影响对象后，退回对应上游阶段（与该阶段 `reject_target` 一致） |

退回操作必须产生新的目标阶段版本（`revision_requested` → 新版本 → `pending`），并经 `DependencyAnalyzer` 将受影响下游对象标记 `stale`（§6.1.4 规则 5）。**不允许**把执行层问题直接退回完整故事——那会让用户重审未受影响的内容。

**`audio_prod` 的分级退回表（以此为准，取代单一 `reject_target = full_story`）**：

| 问题性质 | 实例 | 退回目标 | 说明 |
| --- | --- | --- | --- |
| **音频技术问题**（发音、噪音、时长、格式、配音与台词不匹配的技术性错误） | 生成参数或素材质量问题 | **`audio_prod` 本阶段** | 默认在本阶段局部修复（重新生成该条配音 / 音效 / BGM），不动上游 |
| **剧本内容问题**（台词本身要改：措辞、语气提示、台词与 `full_story` 矛盾） | 根源在完整故事文本 | **`full_story`**（必须经 `DependencyAnalyzer`） | 修改 `full_story` → 新版本 → 其下游（`scene_breakdown` 起至本阶段）受影响对象标 `stale` 并逐级重审 |
| **镜头表达问题**（该镜头的口型 / 台词切分 / 镜头文案需调整） | 根源在镜头设计 | **`shot_design`** | 修改目标 Shot → 新 Shot 版本 → 该镜头下游素材标 `stale` |

**不允许所有音频问题默认退回 `full_story`**：退回必须以问题性质为依据；「退回哪个阶段」的选择由人工审核者在审核意见中标注（`ReviewRecord.issues[].code` 携带问题分类），工作流层按标注路由，不自动猜。

### 6.2 审核状态机

阶段 / 审核对象的状态取值（7 个）：

| 状态 | 含义 | 可转入 |
| --- | --- | --- |
| `pending` | 已生成，等待审核 | `ai_reviewing` / `human_approved` / `human_rejected` |
| `ai_reviewing` | AI 审核进行中 | `ai_passed` / `ai_rejected` |
| `ai_passed` | AI 审核通过，**仍不可进入下游** | `human_approved` / `human_rejected` / `revision_requested` |
| `ai_rejected` | AI 审核未通过 | `revision_requested` |
| `human_approved` | 人工通过（唯一可放行状态） | 下游可执行；上游变更时 → `revision_requested` |
| `human_rejected` | 人工否决 | `revision_requested` |
| `revision_requested` | 退回修改 | 生成新版本后 → `pending` |

硬规则：

1. 只有 `human_approved` 允许解锁下一阶段。
2. `ai_passed` **不得**自动转换为 `human_approved`，必须由人工操作。
3. 状态转换必须由状态机校验，非法转换抛错（有单测）。
4. 每次转换写一条事件（追加式），记录触发者（human / ai / system）。

### 6.3 ReviewRecord

#### 6.3.1 共享资源审核记录的 Project/Story 归属（Stage 0.6 终审新增，P2 / P6 实现约束）

| 字段 | 说明 |
| --- | --- |
| `review_id` | 主键 |
| `target_kind` | `story` / `scene` / `shot` / `asset` / `render` / `stage` / `shared_character` / `shared_world`（后两者为 Project 级共享资源；归属与存储规则见 §6.3.2） |
| `target_id` | 被审对象 ID |
| `target_version` | 被审版本 ID（**必填**，确保关联到具体版本） |
| `reviewer_kind` | `human` / `ai` / `local_rule` |
| `reviewer_ref` | 人工：用户名；AI：`provider_id + model`；本地规则：规则集版本 |
| `decision` | `pass` / `reject` / `revise` |
| `rubric_scores` | 维度分（题材包定义维度，默认沿用 V2 的 8 项 rubric） |
| `issues[]` | 结构化问题（`code` / `severity` / `message` / `location`） |
| `comment` | 自由文本 |
| `created_at` | 时间 |
| `supersedes` | 上一次审核记录 ID（形成审核链） |
| `prompt_id` | 该次生成实际使用的 Prompt 版本（AI 审核时必填） |

约束：

- **审核记录只允许追加，不允许覆盖。**
- AI 审核与人工审核**分别记录**（同一次审核操作产生不同的 `reviewer_kind` 记录）。
- 一条 `ReviewRecord` 的 `decision` 只代表该审核者的判断，**不直接改变**阶段状态；状态变更由工作流层根据记录 + 门禁规则推进。

#### 6.3.2 共享资源审核记录归属（P2 / P6 实现约束）

共享人物 / 共享世界观 / 共享地点（`scope=project`）被多篇 Story 引用，其审核记录既是 **Project 级事实**、又必须能被每篇引用它的 Story 追溯。归属规则如下（**冻结**）：

| # | 规则 | 实现约束 |
| --- | --- | --- |
| 1 | **归属判定看 `target_kind`，不看存储路径**：`shared_character` / `shared_world` → **Project 级审核**；`story` / `scene` / `shot` / `asset` / `render` / `stage` → **Story 级审核** | 两类记录可同存于 `reviews/` 目录（§3.2），但由不同 Repository 管理（见规则 5），**不得混用查询接口** |
| 2 | **Project 级记录不携带单一 `story_id` 作为归属**；它通过 `DependencyImpact` / `referrers()`（§4.4.3 规则 5、7）关联到全部引用 Story | `ReviewRepository` 提供 `list_by_target(kind, target_id)`；`SharedResourceStore.reviewing_stories(entity_id)` 给出受影响的 Story 列表 |
| 3 | **Story 级审核不得改写共享资源**：某篇 Story 对共享人物的意见只能产生「变更提案」（§7.4 创作指令层规则 2），由用户在 Project 级决定是否修改共享档案 | P6 必须拒绝「Story 审核直接写入 `shared/`」的调用路径（有测试） |
| 4 | **共享资源修改后的重审是 Story 级的**：变更 → 受影响 Story 的相关对象标 `stale` + `pending`（§4.4.3 规则 6）；每篇 Story 分别重审、分别产生 `revision_requested` / 新版本 | V3.0 只要求「标记 + 提示」，不要求跨 Story 自动编排（MVP 暂缓第 9 项） |
| 5 | **谁负责存储**：Project 级共享审核记录由 `SharedResourceStore` 负责写入与查询；Story 级审核记录由 `ReviewRepository` 负责；两者共用 §6.3 字段定义与只追加约束（AD-15） | P2（`SharedResourceStore` 落地）建立 Project 级审核路径；P6（工作流）接入门禁与冻结规则；P2 与 P6 的验收均需包含「同一共享人物被两篇 Story 引用」的审核用例 |
| 6 | **审核链不跨归属**：`supersedes` 只能在同类 `target_kind` 内串联；Project 级记录的 `supersedes` 不得指向 Story 级记录 | `ReviewRepository.append()` 校验 `supersedes` 的 `target_kind` 与 `target_id` 一致 |

> 对应 ContextEngine 测试场景 T11（§7.7）：共享档案变更后，两篇 Story 的相关对象均 `stale`，且各自产生独立的 Story 级审核记录；Project 级记录只有一条（针对共享档案版本）。

### 6.4 版本冻结

已经人工审核通过的内容必须冻结：

1. **AI 不得自动修改**已 `human_approved` 的内容。
2. 用户主动修改时：
   - 生成新版本（`StoryVersion` 或镜头级版本）；
   - 原审核记录保留不动；
   - 新版本状态变为 `pending`；
   - 运行 `DependencyAnalyzer` 检查下游依赖；
   - 受影响的下游内容标记过期，必要时重新审核。
3. 已批准素材 (`VisualAsset.approved=true`) 只能被显式替换，不随内容重生成而覆盖。

---

## 7. ContextEngine（三层信息结构）

### 7.1 设计修正

Stage 0 初版使用「单一优先级表」，把客观事实、人物认知、用户指令混为一套优先级。Stage 0.5 修订为**三个独立的信息层次**。

### 7.2 客观事实层

包括：

- 已审核通过的**故事事实**；
- **世界观规则**（`WorldSetting`，特别是 `hard=true`）；
- 人物真实身份（`Character` 的 `secret` 等「作者视角真相」）；
- 已确定的剧情事件（`PlotEvent`）；
- 已审核通过的场景与镜头设定。

定位：**故事事实基准**。任何生成结果不得与之矛盾（除非用户显式开启「新版本」流程）。

### 7.3 角色认知层

包括：

- 角色知道的信息（`CharacterKnowledgeState.knows`）；
- 角色不知道的信息（`does_not_know`）；
- 角色误解的信息（`misbelieves`）；
- 角色隐瞒的信息（`conceals`）；
- 角色获得信息的时间（`learned_at`）；
- 角色对事件的主观判断。

规则：

1. **角色认知不得自动修改客观事实**。这是单向关系：事实 → 角色认知。
2. 同一事件，不同角色在不同时间点可以拥有不同认知，ContextEngine 必须支持。
3. 生成对话 / 人物视角内容时，只能注入该角色在**该时间点**已知的信息；`does_not_know` 的内容不得出现在该角色的视角内。
4. AI 不得「因为角色不知道」而改变客观事实（例如：角色不知道有鬼，不代表故事设定里没有鬼）。
5. 角色认知层按 **Story + Character** 定位：`CharacterKnowledgeState` 只属于某篇 Story（§4.4 规则 2），不能跨 Story 复用。
6. **共享人物的客观档案（Project 级）与单篇故事中的人物认知（Story 级）不能混淆**：上下文组装时，共享档案只进入「客观事实层」中该角色的外观/身份/口吻等基础事实；本 Story 的 `CharacterKnowledgeState` 只进入「角色认知层」。即使同一角色在两篇 Story 中认知完全不同，共享档案也必须一致（不一致应由依赖影响分析提示，而不是由模型自行调整）。

### 7.4 创作指令层

包括：

- 用户临时要求；
- 用户修改意见；
- AI 修改建议；
- 剧情反转提议；
- 世界观变更提议。

规则：

1. 用户**可以修改**已审核内容，但必须：
   1. 创建新版本；
   2. 保留旧版本；
   3. 显示修改影响（`DependencyAnalyzer` 结果）；
   4. 检查下游依赖；
   5. 重新审核受影响内容。
2. 创作指令与客观事实冲突时，指令**不是直接覆盖**，而是形成一个「变更提案」，走上述流程。
3. AI 生成的「修改建议」默认只是建议，不改变任何已批准内容。

### 7.5 层次间的组合规则

| 场景 | 组合方式 |
| --- | --- |
| 生成大纲 / 剧本（作者视角） | 客观事实为基准；角色认知用于推导人物行为动机；创作指令作为约束 |
| 生成角色对话 / 视角内容 | 客观事实作为作者真相；只注入该角色此刻已知信息；创作指令用于调整表达 |
| 生成分镜 / 出图提示词 | 客观事实 + 该镜头出场角色当时的认知（用于表情/神态）+ 创作指令 |
| AI 审核 | 只使用客观事实作为评价基准；**不注入创作指令**（否则审核会被指令误导） |

### 7.6 ContextEngine 必须具备的能力

| 能力 | 说明 |
| --- | --- |
| 按生成目标组装上下文 | `ContextRequest(purpose, story_id, scene_id, shot_id, extra_refs)` |
| 按 Scene/Shot 引用加载人物与世界观 | 以 ID 引用驱动加载，不整本注入 |
| 按剧情时间过滤 PlotEvent | 仅包含 ≤ 当前时间点的事件 |
| 按角色认知状态过滤可用信息 | 见 §7.3 |
| 控制 Token 预算 | `fixed(设定卡) → reserved(output) → elastic(历史摘要)`，超限先压缩弹性段 |
| 压缩非关键历史摘要 | 保留最近 N 个片段 + 摘要 |
| 标记缺失信息 | 显式输出 `MISSING:` 而非让模型编造 |
| 记录实际使用的上下文来源 | `ContextBundle.manifest`：每个段的来源实体 ID 与版本 |
| 防止 AI 擅自改变已审核事实 | 生成结果与客观事实的矛盾由 AI 审核 / 本地规则检出，不得自动写回 |

### 7.7 必须覆盖的测试场景（11 个）

| # | 场景 | 预期 |
| --- | --- | --- |
| T1 | 角色 A 不知道 X（事实层有 X） | 生成 A 的视角时上下文不含 X；事实层仍有 X |
| T2 | 角色 A 在某事件后知道 X | 该事件之前的上下文不含 X；之后含 X |
| T3 | 角色 A 误解 Y | 上下文标注「A 认为 Y'」，事实层保留真相 Y |
| T4 | 角色 A 隐瞒 Z | 生成 A 的对白时不被强制说出 Z，但审核可标记不一致 |
| T5 | 用户要求改变已审核的世界规则 | 产生变更提案；不直接改写；下游标记过期 |
| T6 | 已审版本 vs 草稿 | 已审版本进入事实层；草稿作为「提议」附注 |
| T7 | 上下文超预算 | 弹性段先压缩；被裁掉的段记录在 manifest 中 |
| T8 | 缺失关键信息（如角色未定义） | 输出 `MISSING:` 标记；AI 审核 / 本地规则拦截 |
| T9 | 同一场景两个角色认知冲突 | 各自视角上下文正确分离 |
| T10 | AI 审核时存在创作指令 | 审核上下文**不含**创作指令 |
| T11 | 同一共享人物出现在两篇 Story（Stage 0.6） | 两篇 Story 各自注入的是**共享基础档案** + **本 Story 的角色认知**；Story A 的认知状态不得出现在 Story B 的上下文；共享档案变更后两篇 Story 的相关对象均标记 `stale` |

---

## 8. AI Provider 与 Prompt 架构

### 8.1 能力区分

| 能力 | 说明 | 首期 Provider |
| --- | --- | --- |
| `TEXT` | 文本生成（故事、审核、Prompt 生成） | DeepSeek、OpenAI GPT |
| `IMAGE` | 图像生成 | SiliconFlow |
| `VIDEO` | 视频生成 | 预留 |
| `AUDIO` | 语音合成（`voice`）与音效 / BGM（`audio`） | SiliconFlow |
| `VISION` | 图像理解（预留） | 预留 |

### 8.2 Provider 接口

```python
# ai/provider.py
class Provider(Protocol):
    provider_id: str
    def capabilities(self) -> set[Capability]
    def chat(self, request: ChatRequest) -> ChatResult
    def test_connection(self) -> ConnectionResult

# ai/provider_registry.py
class ProviderRegistry:
    def register(self, reg: ProviderRegistration) -> None
    def get(self, provider_id: str) -> Provider
    def state(self, provider_id: str) -> ProviderState
```

约定：

- 业务代码只出现 `Slot` 与 `provider_id`，**不出现任何具体模型名**。
- 文本 Provider 与媒体 Provider 的接口分开定义（媒体 Provider 有 `generate_image` / `generate_audio` 等方法），不允许把媒体方法塞进文本接口。
- 统一 `ChatRequest / ChatResult` 之后，`story_engine` 的解析链改为消费 `ChatResult.text`。

### 8.3 槽位（Stage 0.6 修订：9 个）

**能力类型（Capability）与业务槽位（Slot）是两个不同概念：**

- **能力类型**描述 Provider「能做什么」：`TEXT / IMAGE / VIDEO / AUDIO / VISION`（§8.1）。
- **业务槽位**描述系统「在哪个环节调用 AI」：9 个，每个槽位声明它需要的 1 个能力类型。
- 同一能力类型可以对应多个槽位（`voice` 与 `audio` 都是 AUDIO；`planner` / `writer` / `concept` / `fast` / `reviewer` 都是 TEXT）。
- **不要把能力类型当成槽位**（例如不存在名为 `TEXT` 的槽位，也不存在名为 `AUDIO` 的业务用途——AUDIO 下具体是语音还是音效由槽位区分）。

| # | 槽位 | 主要职责 | 能力类型 | 媒体接口 |
| --- | --- | --- | --- | --- |
| 1 | `planner` | 故事规划与结构设计（大纲、场景拆分） | TEXT | 文本接口 |
| 2 | `writer` | 故事内容生成（剧本、分镜） | TEXT | 文本接口 |
| 3 | `concept` | 创意生成 | TEXT | 文本接口 |
| 4 | `fast` | 快速辅助任务（出图提示词、短任务） | TEXT | 文本接口 |
| 5 | `reviewer` | 独立 AI 审核 | TEXT | 文本接口 |
| 6 | `image` | 图片生成 | IMAGE | `<ImageProvider>` |
| 7 | `video` | 视频生成 | VIDEO | `<VideoProvider>` |
| 8 | `voice` | 角色配音、语音合成 | AUDIO | `<SpeechProvider>` |
| 9 | `audio` | 音效、BGM、音频生成与处理 | AUDIO | `<AudioProvider>` |

`voice` 与 `audio` 的区别：

| 维度 | `voice` | `audio` |
| --- | --- | --- |
| 业务含义 | 把文字变成人声（角色台词、旁白） | 生成/选择/处理非人声音频（音效、环境声、BGM） |
| 典型输入 | 台词文本 + 角色音色 | 场景描述 / 情绪 / 时长 / 风格 |
| 产物 | 每句台词的语音文件 | 音效、环境底噪、配乐 |
| 审核侧重 | 音色一致性、情感、口型不冲突 | 氛围、版权、与画面同步 |
| 可合并实现 | 可由同一个 Provider 提供（如 SiliconFlow），但**槽位配置分开**，便于各自替换 | 同左 |

规则：

- `reviewer` 必须指向**与 `writer` 不同**的 Provider 或模型（独立性要求，配置校验时检查）。
- 槽位到 `(provider_id, model)` 的映射由用户配置决定，不写死在代码中。
- **媒体 Provider 与文本 Provider 使用不同接口**（§8.2）；槽位声明的能力类型决定它走哪个接口。
- **V3.0 可以暂不交付完整的 `image` / `video` / `voice` / `audio` 制作能力，但槽位与接口必须保留**（见 [MVP §3](V3_STAGE0_5_MVP_SCOPE.md#3-v30-暂缓的功能架构预留不在-v30-交付)），不得因为「V3.0 不做」而从配置模型中删除。

### 8.4 多模型并行

| 项 | 规则 |
| --- | --- |
| 单模型生成 | 默认 |
| 多模型并行生成 | 同槽位映射多个候选 `ModelRef` |
| 同 Prompt 对比 | 并行调用必须使用**同一 Prompt 版本与同一上下文基准** |
| 独立模型审核 | `reviewer` 槽位 |
| 默认并发数 | **2** |
| 并发上限 | 用户可配置 |

### 8.5 成本护栏

| 护栏 | 说明 |
| --- | --- |
| 单次任务预算 | 超过即中止并提示 |
| 单项目预算 | 按项目累计 |
| 每日预算 | 按自然日累计 |
| 最大并发数 | 默认 2 |
| 失败重试上限 | 每任务可配置 |
| 重复任务防护 | 同任务指纹在短时间内不重复提交 |
| 超预算确认 | 超出时弹窗确认，不静默继续 |
| Token 统计 | `UsageLedger` 记录 prompt/completion tokens |
| 成本估算 | 依据 `providers.json` 的价格配置 |
| Provider 价格配置 | **不得在代码中写死模型价格** |

### 8.6 PromptStore

| 字段 | 说明 |
| --- | --- |
| `prompt_id` | 主键（内容哈希 + 语义名） |
| `version` | 显式版本号 |
| `genre` | 所属题材包（或 `*` 通用） |
| `stage` | 对应阶段（`outline` / `full_story` / `shot_design` …） |
| `content` | 模板正文 |
| `created_at` | 时间 |
| `description` | 用途说明 |

规则：

1. 每次生成必须记录实际使用的 `prompt_id` 与 `version`（写入 `UsageLedger` 与相关 `ReviewRecord`）。
2. 同一轮模型对比必须使用相同 Prompt 版本与相同上下文基准。
3. V2 内联 Prompt 在 P5 阶段抽成 `version=1` 文件，行为保持不变（用快照测试比对生成结构）。

---

## 9. GenrePack（题材包）

```python
class GenrePack(Protocol):
    genre_id: str
    def rules(self) -> list[Rule]
    def rubric(self) -> list[RubricItem]
    def prompt_variants(self) -> dict[str, str]
    def validate(self, story) -> list[Issue]
```

- 首发实现 `HorrorPack`：把 V2 `horror_rules.py` 的六类规则**原样搬入，不改行为**（21 个测试作为等价性证据）。
- V3.0 **只交付 HorrorPack**。MysteryPack 作为后续验证抽象的第二题材，不在 V3.0 交付范围（见 [MVP 范围](V3_STAGE0_5_MVP_SCOPE.md)）。
- 架构上必须保证新增题材不需要修改业务代码：只需新增一个 `GenrePack` 实现 + Prompt 变体。

---

## 10. 模块依赖方向与架构约束

```
表现层 → 应用层 → 编排层 → AI 抽象层 → Provider 实现
                       → 领域层 → 数据层（仅通过 Repository 接口）
媒体层只被编排层调用，不得反向依赖 story_engine（修复 A-06）
```

约束落地方式：

- 新增 `tests/test_architecture.py`：静态扫描 import 图，验证依赖方向，禁止反向依赖。
- 面板通过回调与 `main_window` 交互，不直接 import 数据层或 AI 层。
- `batch.py` 保持无 tkinter 依赖。
- 业务代码不得直接 `open()` 实体 JSON（架构测试同时扫描 `stories/` / `shared/` 路径字符串）。

---

## 11. UI 演进

不做一次性重写，按阶段逐步接入：

| 阶段 | 面板变化 |
| --- | --- |
| P1 数据层完成 | 现有 story_panel / timeline 改用 Repository，界面不变（回归测试只比对行为） |
| P5 审核上线 | 新增「审核中心」页签：阶段列表 + 审核记录 + 通过/退回 |
| P2 新实体上线 | 新增「设定」页签（人物卡、关系、世界观、事件线、角色认知） |
| P3 镜头实体化完成 | timeline 升级为「镜头详情 + 版本 + 重生成 + 资产候选」 |
| P7 质量体系上线 | 新增「模型对比」页签（`UsageLedger` + 审核分数） |
| P8 | 工作台整合、全部面板适配 |

> 界面阶段编号以 [开发路线](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md) 的 P0~P9 为准。

---

## 12. 待确认事项（统一编号）

本文件不再维护独立的 `OPEN QUESTION` 清单。所有未决问题统一登记在 **[Stage 0.6 冻结基线 §11 OPEN QUESTION 总表](V3_STAGE0_6_FINAL_BASELINE.md#11-open-question-总表)**，按 `OQ-01 ~ OQ-09` 编号。

本文件原 Stage 0.5 的 `OQ-1 ~ OQ-4` 对应关系：

| 原编号 | 统一编号 | 问题 |
| --- | --- | --- |
| OQ-1 | `OQ-01` | 单 Provider 时 `reviewer` 是否允许同 Provider 不同模型 |
| OQ-2 | `OQ-02` | 单任务 / 单项目 / 每日预算的默认数值 |
| OQ-3 | `OQ-03` | 多 Story 的 UI 呈现形态 |
| OQ-4 | `OQ-04` | V3.0 是否必须接入视频生成 Provider |

Stage 0 初版 §10 中提出的 6 个设计问题，已在 Stage 0.5 给出决策（见 [架构决策](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md) AD-01 ~ AD-06），不再列为 OPEN QUESTION。
