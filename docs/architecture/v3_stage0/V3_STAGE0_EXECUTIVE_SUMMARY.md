# V3 STAGE 0（含 Stage 0.5 / 0.6 修订）— 执行摘要

日期：2026-11-05
版本：**Stage 0.6 修订版**（取代 Stage 0.5 版同名文件）
范围：AI Horror Studio V2.2/V2.3 升级为通用型 AI Story Studio V3 的技术盘点与开发基线。
状态：**Stage 0.6 完成；未修改任何 Python 代码，未执行迁移，未提交 Git。**

配套：[现有架构审计](V3_STAGE0_CURRENT_ARCHITECTURE_AUDIT.md)、[目标架构](V3_STAGE0_TARGET_ARCHITECTURE.md)、[迁移方案](V3_STAGE0_MIGRATION_PLAN.md)、[架构决策](V3_STAGE0_5_ARCHITECTURE_DECISIONS.md)、[MVP 范围](V3_STAGE0_5_MVP_SCOPE.md)、[开发路线](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md)、[修订报告](V3_STAGE0_5_REVIEW_REPORT.md)、[Stage 0.6 冻结基线](V3_STAGE0_6_FINAL_BASELINE.md)。

---

## 一句话结论

V2 的逻辑层质量足够好，约 60% 可以继承；V3 真正的工作量集中在三件事：**Scene/Shot 实体化、多 Provider 抽象、人机协同审核工作流**。在这之前，有一个**必须最先修复的数据丢失缺陷（K-01）**——K-01 未修复并通过回归测试前，不得执行任何 V2→V3 数据迁移。

---

## 1. 现状关键事实

| 维度 | 结论 |
| --- | --- |
| 产品定位 | V3 = 通用 AI 故事创作与短剧生产系统；恐怖为首发验证题材，个人创作为主，不做商业化 SaaS |
| 代码规模 | 42 个 Python 文件（含测试），约 16,774 行 |
| 外部依赖 | 运行时零第三方依赖（tkinter + 标准库）；可选 Pillow |
| 存储 | 无数据库，单项目单 `project.json` + `versions/` + 素材目录 |
| 测试 | Stage 0 实测 **309 通过 / 0 失败**（32.8s）；Stage 0.5 复核重跑 **309 通过 / 0 失败**（30.5s） |
| 测试覆盖质量 | 逻辑层覆盖较好；**GUI 约 4,200 行零自动化测试** |
| 模型管理 | 四槽位（planner/writer/concept/fast），仅 DeepSeek；**无 OpenAI GPT**。V3 目标为 9 个业务槽位（`planner / writer / concept / fast / reviewer / image / video / voice / audio`，见[目标架构 §8.3](V3_STAGE0_TARGET_ARCHITECTURE.md#83-槽位stage-06-修订9-个)） |
| 审核 | 有本地规则 + AI 评分，**不存记录、不设门禁** |
| 版本 | story 快照，10 版上限；**快照不含时间轴，恢复按 index 对齐（错位风险）** |

---

## 2. 三个最重要的结论

### 2.1 K-01 是必须单列的数据安全红点

[project_manager.py:455-465](../../../modules/project_manager.py#L455-L465) 在 story 升级失败时 `data.pop("story")`，而 [open_project:225-226](../../../modules/project_manager.py#L225-L226) 在 `changed` 时立即写盘。

**用户打开旧项目 → 升级抛异常 → 整个故事永久消失，无备份、无提示。** 现有 309 个测试未覆盖该路径。

→ **V3 开工第一条任务（P0，独立于 V3 的开发）**：修复为「失败不写盘、保留原文、提示用户」，并补回归测试。**K-01 未修复并回归通过前，禁止迁移。**

### 2.2 可继承的大部分是「与模型无关」的能力

五阶段流水线、JSON 稳健解析链与截断恢复、pacing、本地质量硬否决、FFmpeg 渲染、批量失败隔离、Key 安全设计、原子写——全部与 Provider 无关，可直接复用。槽位制（`model_for(slot)`）本身就是「不把模型绑进业务逻辑」的正确起点。

### 2.3 三大改造点决定 V3 工作量

| 改造点 | 现状 | V3 要求 | 量级 |
| --- | --- | --- | --- |
| Scene/Shot 实体化 | story 内嵌 + 时间轴双轨，弱关联 | 独立实体、单镜重生成、镜头版本与审核、依赖影响分析 | **大** |
| 多 Provider | 仅 DeepSeek，调用内联 | 统一抽象、切换、并行、独立审核、成本护栏 | **大** |
| 审核工作流 | 无实体、无门禁 | 13 个工作流阶段 / 9 个人工门禁 + 审核记录 + 人工最终确认 | **大** |

V3 要求的 **12 个领域实体**按来源分为三类：**4 个 V2 已存在且可迁移**（Project / Story / StoryVersion / Character）、**2 个 V2 原有嵌套结构需实体化**（Scene / Shot，独立 Repository、稳定 ID 与版本属于 V3 新增能力）、**6 个 V3 全新引入**（CharacterRelationship / WorldSetting / PlotEvent / CharacterKnowledgeState / VisualAsset / ReviewRecord）。另外 `PromptTemplate` 是**创作基础设施对象**（存于用户配置目录），**不计入** 12 个领域实体。唯一权威清单见 [目标架构 §4.1](V3_STAGE0_TARGET_ARCHITECTURE.md#41-实体清单12-个领域实体--1-个创作基础设施对象)。

---

## 3. 主要风险（按优先级）

| 级别 | 风险 | 说明 |
| --- | --- | --- |
| **高** | K-01 story 静默丢失 | 迁移前必修；任何迁移路径都会触发 |
| **高** | Shot 双轨制 | 单镜重生成与镜头审核的前提被阻塞 |
| **高** | 无审核实体与门禁 | V3 核心业务流程全部新建 |
| **高** | 无多 Provider 抽象 | GPT 不存在，Prompt 内联且无版本 |
| **高** | 迁移非原子（目录级切换） | 必须用提交日志 + 启动恢复兜底 |
| 中 | 导入四步写盘（K-02） | 中断产生混合状态 |
| 中 | 恢复按 index 对齐（A-05） | 素材错位；实体化后按 ID 对齐可根除 |
| 中 | 版本额度被导入稀释（A-03） | 10 版上限快速耗尽 |
| 中 | GUI 零自动化测试 | 大改面板无回归防线 |
| 中 | 单文件 JSON 在实体量级下的膨胀 | 采用目录化 JSON 存储 |

---

## 4. 推荐开发路径（P0~P9）

**先修数据，再做结构，最后接 UI；AI 抽象与数据层可并行。**

| 阶段 | 名称 | 是否阻塞后续 |
| --- | --- | --- |
| **P0** | V2.3 数据安全补丁（K-01 / K-02 / A-05 只读检测 / A-03 来源标记） | **阻塞全部迁移** |
| P1 | 基础架构（Repository 接口 / 原子写入 / 任务状态 / 基础测试） | 阻塞 P2/P3/P6 |
| P2 | 故事数据层（Story / Character / Relationship / WorldSetting / PlotEvent / KnowledgeState / 多 Story） | 阻塞 P3/P6 |
| P3 | Scene/Shot 实体化（Repository / ShotVersion / AssetRegistry / 迁移器） | 阻塞 P6/P9 |
| P4 | AI Provider（ProviderRegistry / DeepSeek / OpenAI / UsageLedger / 并发与成本） | 可与 P2/P3 并行 |
| P5 | PromptStore + ContextEngine | 依赖 P2/P4 |
| P6 | 审核与工作流（WorkflowEngine / ReviewRecord / 门禁 / 冻结 / 依赖失效） | 依赖 P1/P2/P3/P5 |
| P7 | 质量体系与题材包（AI 独立审核 / 多模型比较 / HorrorPack） | 依赖 P4/P5/P6 |
| P8 | UI 适配 | 依赖 P1~P7 |
| P9 | 短剧生产（图片 / 视频 / 配音 / 音效 / 后期 / 导出 / 最终审核） | 依赖 P3/P4/P6/P8；**不与 P7/P8 并行**，仅预备工作可提前（路线 §2.3） |

依赖图与每阶段验收标准见 [开发路线](V3_STAGE0_5_DEVELOPMENT_ROADMAP.md)。**依赖关系无环**（已校验，见修订报告 §8）。

---

## 5. V3.0 MVP 定义

V3.0 至少能够：

1. 创建一个项目。
2. 一个项目管理多篇故事。
3. 生成故事创意。
4. 生成故事大纲。
5. 建立多角色人物档案。
6. 管理人物关系。
7. 管理世界观。
8. 管理剧情事件。
9. 管理角色认知状态。
10. 生成完整多角色故事。
11. DeepSeek 与 GPT 可切换。
12. 支持多模型结果比较。
13. 支持独立 AI 审核。
14. 所有重要阶段人工确认。
15. 保存故事版本。
16. 保存审核记录。
17. 支持 Scene/Shot 独立实体。
18. 支持镜头单独修改和重新生成。
19. 已审核内容不会被 AI 静默覆盖。
20. 旧 V2 项目可以经过用户确认后安全迁移。
21. 项目级共享人物档案与世界观基础设定，可被多篇故事复用（Stage 0.6 新增）。

**V3.0 不要求一次性完成全部视频生成和后期功能。** 图片、视频、配音、音效和合成可以作为后续生产模块（P9）逐步接入，但架构必须预留接口与槽位（`video` / `voice` / `audio`）。

（本清单原为 20 项；Stage 0.6 增加第 21 项「项目级共享人物档案与世界观基础设定」，见 [MVP 范围 §2](V3_STAGE0_5_MVP_SCOPE.md#2-v30-必须交付的能力21-项)。）

首发功能 / 暂缓功能的完整划分见 [MVP 范围](V3_STAGE0_5_MVP_SCOPE.md)。

---

## 6. 明确不建议做的事

- 不建议推翻任何现有模块：horror 规则、pacing、渲染、媒体调用、批量、Key 安全、原子写均经过真实 API 与 309 测试验证。
- 不建议本轮引入 SQLite：与 V2 单文件哲学断裂，迁移风险大；只保留接口边界。
- 不建议一次性重写 GUI：先改逻辑层，面板只做适配。
- 不建议在 P0 完成前开始任何写盘迁移。
- 不建议为通过测试而删除原有用例。

---

## 7. 交付物

| 文件 | 性质 | 内容 |
| --- | --- | --- |
| `V3_STAGE0_CURRENT_ARCHITECTURE_AUDIT.md` | 修订 | 现有代码盘点（12 节）；补充「审计结论仍有效」的复核说明 |
| `V3_STAGE0_TARGET_ARCHITECTURE.md` | 修订 | 产品定位、渐进升级保留清单、存储与 9 个 Repository、**12 个领域实体 + PromptTemplate**、Project/Story 数据边界、三层 ContextEngine、13 阶段 / 9 门禁、9 个槽位、成本护栏、依赖治理 |
| `V3_STAGE0_MIGRATION_PLAN.md` | 修订 | `assert_p0_fixed()` 六项检查、版本判定矩阵、项目外暂存、**逐步骤事务日志与恢复**、目标路径冲突、异常 Story 审计、Windows 异常、事务日志与暂存副本物理隔离、**23 类验收** |
| `V3_STAGE0_EXECUTIVE_SUMMARY.md` | 修订 | 本文件 |
| `V3_STAGE0_5_ARCHITECTURE_DECISIONS.md` | 新增 | 决策记录（理由 / 影响 / 待确认） |
| `V3_STAGE0_5_MVP_SCOPE.md` | 新增 | V3.0 纳入（21 项）与暂缓功能（9 项） |
| `V3_STAGE0_5_DEVELOPMENT_ROADMAP.md` | 新增 | P0~P9 依赖图与拓扑排序、P9 预备工作、阶段验收标准、真实端到端验收（E1~E10） |
| `V3_STAGE0_5_REVIEW_REPORT.md` | 修订 | Stage 0.5 逐条修订记录 + Stage 0.6 逐条修订记录与一致性自检 |
| `V3_STAGE0_6_FINAL_BASELINE.md` | 新增 | **V3.0 架构冻结基线**：产品定位、数据架构、实体清单、ContextEngine、Provider/槽位、工作流门禁、迁移安全、P0~P9、MVP 验收、OQ 总表、未实现功能、冻结声明 |

**Stage 0.6 到此结束，等待 ChatGPT 审查冻结基线，不进入 P0 开发。**
