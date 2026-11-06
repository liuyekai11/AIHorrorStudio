# Stage 0.6 最终架构审查报告（供 ChatGPT 审查）

> 使用说明：本文件是**单一可复制文本**，把 9 份架构文档的核心定义完整摘录并按主题重组，供 ChatGPT 在不访问仓库的情况下审阅。
> 摘录原则：定义类内容逐字/近逐字保留；**所有「建议值」与 `OPEN` 问题原样保留，不被描述为已决定**；所有内容均为**设计**，除标注「V2 现状」的部分外，代码中均未实现。
> 生成日期：2026-11-05　项目：AI_Horror_Studio_V2　基线 HEAD：`ac8e333741e9caedeada234a585be153e5a44a0d`（分支 `main`）
> **版本：终审修订版 v4（v2 + 终审补充核验 R4 / R5 + 哈希边界最终修订）。** 初版送审后 ChatGPT 结论为 CONDITIONAL PASS，提出 6 条定点修订意见（v2 已全部落入文档，见 A14.1）；v2 送审后 ChatGPT 补充核验提出 R4（事务日志与暂存副本物理隔离）与 R5（AD 编号范围同步），本版已全部落入 A1 / A9 / A13 / A14 / A16 与附，处理索引见 A14.2 / A16.1c。

---

## 报告目录

| 段 | 内容 |
| --- | --- |
| A1 | 冻结基线与文档权威关系 |
| A2 | 产品定位与设计原则 |
| A3 | 数据架构（存储 / 目录 / 9 个 Repository / 一致性） |
| A4 | 12 个领域实体与关系 |
| A5 | Project / Story 数据隔离与共享资源机制 |
| A6 | ContextEngine |
| A7 | 13 个生产阶段、9 个审核门禁、依赖与状态机 |
| A8 | Provider、5 个能力类型、9 个槽位、PromptTemplate |
| A9 | 迁移与安全机制（事务日志、恢复、冲突、异常 Story） |
| A10 | `assert_p0_fixed()` 规则 |
| A11 | P0~P9 开发路线 |
| A12 | 真实端到端验收 E1~E10 |
| A13 | V3.0 MVP 范围（21 项 / 暂缓 9 项） |
| A14 | 9 条审查意见 + 终审 6 条定点修订 + 补充核验 R4 / R5 的最终处理情况 |
| A15 | OQ-01~OQ-09 状态 |
| A16 | 文档间冲突检查结果（含本轮修正） |
| A17 | 明确未实现的功能 |
| B | P0 启动条件检查表 |

---

# A1. 冻结基线与文档权威关系

| 文档 | 职责 | 权威范围 |
| --- | --- | --- |
| `V3_STAGE0_CURRENT_ARCHITECTURE_AUDIT.md` | V2 现状与缺陷证据 | V2 事实（K-01/K-02/A-05/A-03） |
| `V3_STAGE0_TARGET_ARCHITECTURE.md` | 目标架构 | **数据模型、实体清单、阶段定义表、Provider 槽位、ContextEngine 的唯一权威** |
| `V3_STAGE0_MIGRATION_PLAN.md` | 迁移方案 | **迁移安全、事务日志、`assert_p0_fixed()` 的唯一权威** |
| `V3_STAGE0_EXECUTIVE_SUMMARY.md` | 决策者浓缩版 | 无独占定义 |
| `V3_STAGE0_5_ARCHITECTURE_DECISIONS.md` | AD-01 ~ AD-30 | 决策与理由 |
| `V3_STAGE0_5_MVP_SCOPE.md` | V3.0 交付 / 暂缓 | **MVP 范围权威** |
| `V3_STAGE0_5_DEVELOPMENT_ROADMAP.md` | P0~P9 | **依赖、阶段验收、E1~E10 权威** |
| `V3_STAGE0_5_REVIEW_REPORT.md` | 修订记录与自检 | 修订证据 |
| `V3_STAGE0_6_FINAL_BASELINE.md` | 冻结声明 + 索引 | **哪些已冻结 / 未实现 / 仍待决定**；**OQ 唯一登记处（§11）** |

**冻结声明（基线 §13）**：冻结的是**设计**而非实现；修改冻结内容需「新增 AD + 改权威文档 + 更新基线 + 经 ChatGPT 审查」。冻结不包含仍为 `OPEN` 的 OQ。

**冻结清单（10 项）**：① 产品定位与用户边界；② 存储形态与 9 个 Repository 职责；③ 12 实体清单与来源分类、PromptTemplate 归类；④ Project/Story 边界 8 条规则；⑤ ContextEngine 三层 + T1~T11；⑥ 5 能力类型 + 9 槽位；⑦ 13 阶段 ID 与 9 门禁映射；⑧ 7 状态机与「AI 通过 ≠ 人工通过」；⑨ K-01 硬阻塞、版本判定矩阵、逐步骤事务日志、23 类验收；⑩ P0~P9 依赖（尤其 P9 依赖 P3/P4/P6/P8）。

---

# A2. 产品定位与设计原则

| 项 | 内容 |
| --- | --- |
| 产品 | AI Story Studio V3 — 通用 AI 故事创作与短剧生产系统 |
| 首发题材 | 恐怖（HorrorPack）；架构不绑定题材，GenrePack 可注册 |
| 用户 | 个人创作者 |
| 核心价值 | 提高故事质量与短剧制作效率 |
| 非目标 | 不做商业化 SaaS：无多租户、无权限、无在线协作、无计费 |
| V2 关系 | 渐进升级：V2 项目可原样打开；只做加法与受控拆分 |

**V2 能力保留清单（不得无理由重写，10 项）**：五阶段流水线、JSON 稳健解析链与截断恢复、Pacing、本地质量检查与硬否决、FFmpeg 渲染、媒体调用解耦、批量失败隔离、Key 安全设计、原子写、309 个测试。

**依赖方向**（架构测试须静态扫描）：

```
表现层 → 应用层 → 编排层 → AI 抽象层 → Provider 实现
                     → 领域层 → 数据层（仅通过 Repository 接口）
媒体层只被编排层调用，不得反向依赖 story_engine（修复 A-06）
```

---

# A3. 数据架构

| 项 | 冻结内容 |
| --- | --- |
| 选型 | **目录化 JSON（每实体一个文件）+ Repository 接口 + 原子写入（`tmp.replace`）**；**本轮不引入 SQLite**（保留接口边界） |
| 数据入口 | 业务代码**禁止直接 `open()` 实体 JSON**，只能经 Repository |
| 一致性 | 单实体原子写；多实体写入走「暂存 → 提交」；`index.json` 是**派生、可重建**索引，不是真源 |
| 关联 | 全部稳定 ID；`story_index` / 数组位置不得作为关联依据 |
| 引用完整性 | Repository 写入前后校验；提供只读 `check_integrity()` 供测试与启动自检 |
| Project : Story | **1 : N**，模型层不得限制为 1:1 |

**目标目录布局**：

```
<项目目录>/
├─ project.json                        项目元数据 + settings + schema_version
├─ shared/                             ★ Project 级共享资源
│  ├─ index.json                       共享资源索引（派生、可重建）
│  ├─ characters/<character_id>.json   共享人物基础档案
│  ├─ world/<setting_id>.json          共享世界观基础设定（scope=project）
│  └─ places/<place_id>.json           共享地点（WorldSetting kind=place, scope=project）
├─ stories/<story_id>/
│  ├─ story.json                       元数据 / 创意 / 大纲 / 脚本 / 阶段状态 / active_version
│  ├─ characters/<character_id>.json
│  ├─ relationships/<rel_id>.json
│  ├─ world/<setting_id>.json          scope=story 补充设定
│  ├─ events/<event_id>.json
│  ├─ knowledge/<character_id>/<state_id>.json
│  ├─ scenes/<scene_id>.json
│  ├─ shots/<shot_id>.json
│  ├─ shots/<shot_id>/versions/<rev>.json
│  └─ assets/<asset_id>.json
├─ story/index.json                    story_id 列表（派生、可重建；命名待 OQ-09）
├─ reviews/<review_id>.json            审核记录（只追加）
├─ versions/<version_id>.json          story 级快照（沿用 V2）
├─ images/ audio/ subtitles/ output/ temp/
└─ migration_report.json               迁移后生成
```

**9 个 Repository（实体数量 12 与 Repository 数量 9 是两个口径，不得混用）**：

| 接口 | 职责 | 责任边界 |
| --- | --- | --- |
| `ProjectStore` | `project.json` 读写、schema_version、原子写 | Project 级 |
| `SharedResourceStore` | 共享人物档案 / 共享世界观 / 共享地点 / **引用索引**（`referrers`） | Project 级 |
| `StoryRepository` | Story 元数据、大纲、脚本、阶段状态 | Story 级 |
| `CharacterRepository` | 某 Story 的人物视图（`resolve_shared`）与关系 | Story 级 |
| `SceneRepository` | 场景实体 | Story 级 |
| `ShotRepository` | 镜头实体与镜头版本 | Story 级 |
| `VersionStore` | story / 场景 / 镜头级快照与恢复 | Story 级 |
| `ReviewRepository` | 审核记录（只追加） | Story 级 |
| `AssetRegistry` | 素材索引（图 / 音 / 视频候选） | Story 级 |

约束：① 禁止直接读写实体 JSON；② 写操作统一原子写；③ Repository 不承载业务规则（门禁、审核判定在应用/领域层）；④ 接口形态可映射未来数据库，但不提前实现。

---

# A4. 12 个领域实体与关系

**唯一权威：目标架构 §4.1。** 分类：A = V2 已存在且可迁移（4）；B = V2 嵌套结构需实体化（2）；C = V3 全新（6）。PromptTemplate 为**创作基础设施对象**，不计入。

| # | 实体 | 来源 | 主键 | 所属 | 关键点 |
| --- | --- | --- | --- | --- | --- |
| 1 | `Project` | A | 目录 | 根 | `project.json`：`name / created_at / settings / schema_version`；无版本化 |
| 2 | `Story` | A | `story_id` | Project（1:N） | `title / logline / genre_id / concept_id / outline / script / pacing / stage_states / active_version`；软删除 |
| 3 | `StoryVersion` | A | `version_id` | Story | `source(human/batch/import/restore) / scope / payload_ref`；追加、保留 10 版，被引用版本不裁剪 |
| 4 | `Character` | A | `character_id` | **两段式**：`scope=project`（Project）/ `scope=story`（Story，可 `shared_ref`） | `look / motivation / secret / voice / scope / shared_ref` |
| 5 | `CharacterRelationship` | C | `rel_id` | Story | `from/to_character_id`、`kind`、`strength`、`asymmetric`；关系**故事限定** |
| 6 | `WorldSetting` | C | `setting_id` | 两段式（project / story） | `kind(rule/place/org/taboo)`、`hard=true` 不得被 AI 违反 |
| 7 | `PlotEvent` | C | `event_id` | Story | `timeline_order / when / summary / scene_id / participants / causes / effects` |
| 8 | `CharacterKnowledgeState` | C | `state_id` | **Story + Character** | `knows / does_not_know / misbelieves / conceals / learned_at`；**追加式** |
| 9 | `Scene` | B | `scene_id`（沿用 V2） | Story | 独立文件、独立 Repository、独立版本与审核（V3 新增能力） |
| 10 | `Shot` | B | `shot_id`（沿用 V2） | Scene | 合并 story 内嵌分镜与时间轴；多版本、单镜重生成、镜头级审核；`legacy_timeline_id` |
| 11 | `VisualAsset` | C | `asset_id` | Shot / Character | `kind`、`candidate_of`、`prompt_id`、`provider_id`、`model`、`approved` |
| 12 | `ReviewRecord` | C | `review_id` | 多态 | 见 A7 |
| — | `PromptTemplate` | C | `prompt_id + version` | **用户配置目录（不随项目走）** | 见 A8 |

**关系图**：

```
Project 1─* Story                                  （不限制 1:1）
Project 1─* Character[scope=project]              （共享基础档案）
Project 1─* WorldSetting[scope=project]           （含 kind=place）
Story   1─* Character[scope=story] ── shared_ref? ──▶ Character[scope=project]
Story   1─* CharacterRelationship                 （仅本 Story 有效）
Story   1─* WorldSetting[scope=story]
Story   1─* PlotEvent ──* Character[scope=story]
Character[scope=story] 1─* CharacterKnowledgeState ──1 PlotEvent / Scene
Story   1─* Scene 1─* Shot 1─* (versions)
Character[scope=story] 1─* VisualAsset   Shot 1─* VisualAsset
Story   1─* StoryVersion
*       1─* ReviewRecord（target_kind / target_id / target_version）
```

**相对 Stage 0.5 调整的 5 条关系**：`Story 1─* Character` → Project 共享 + Story 扩展（`shared_ref`）；`Story 1─* WorldSetting` → 同理；`Character 1─* KnowledgeState` → **仅 `Character[scope=story]`**；关系保持故事限定；`ReviewRecord.target_kind` 增加 `shared_character` / `shared_world`。

**旧口径作废**：Stage 0「8 个数据模型 / 5 个全新」、Stage 0.5「13 个数据模型」全部作废；Stage 0.6 起统一为 **12 + 1**。

---

# A5. Project / Story 数据隔离与共享资源机制

## A5.1 层级划分

**Project 级（5 类）**：项目基础信息（`project.json`）、共享人物基础档案（`shared/characters/`）、共享世界观基础设定（`shared/world/`，`hard` 规则）、共享地点（`shared/places/`，`WorldSetting(kind=place, scope=project)`）、共享资源索引（`shared/index.json`，派生）。

**Story 级（11 类）**：故事创意（`ideas[]` / `concept_id`）、故事大纲、故事级人物（或共享档案的本故事扩展）、故事级世界观补充、人物关系、剧情事件、角色认知状态、StoryVersion、Scene / Shot、故事审核记录、故事专属视觉资产。

## A5.2 八条边界规则

1. Character 可被多篇 Story 引用：`Character[scope=story].shared_ref` → `Character[scope=project]`。
2. **CharacterKnowledgeState 必须属于具体 Story**，不允许出现在 `shared/`。
3. 共享人物的客观档案（作者视角真相，入事实层）与单篇故事中的人物认知（入认知层）**不得混淆**。
4. WorldSetting 可含项目级共享设定与 Story 级补充；同一 `setting_id` 的两条记录互不覆盖。
5. **修改共享人物或世界观时必须检查引用它的 Story**：`SharedResourceStore.referrers(entity_id)` 列出影响；修改前必须展示影响清单。
6. 已有 Story 不得被静默修改：共享资源变更 → 该 Story 相关对象标记 `stale` + 待审核，**不直接改写已审内容**。
7. 每次共享资源变更写一条 `DependencyImpact`（`entity_id` / 变更摘要 / 受影响 `story_id` 列表 / 时间 / 是否已处理），作为审计依据。
8. **V3.0 只要求基础共享能力**：共享档案 CRUD + `referrers()` + 修改前影响提示 + 标记 `stale`；跨 Story 自动重新审核编排留待后续。

## A5.3 迁移与共享的关系

- V2 是单 Story；迁移时 `story.characters[]` **优先迁入 Story 级**，**不自动提升为共享档案**（无法判断哪些字段「跨故事一致」，不替用户决定）。
- 用户可显式「提取为共享人物」，产生 `shared/` 记录并建立 `shared_ref`，同时写 `DependencyImpact`。
- 当前代码**不存在**共享资源能力，属 P2 新增。

## A5.4 决策记录

- **AD-27** Project 级共享资源 + Story 级剧情数据（理由：系列故事需共享外观/身份/口吻与硬规则；认知只对单篇有意义）。
- **AD-28** 共享资源使用独立 `SharedResourceStore`（理由：避免 `CharacterRepository` 同时依赖 Project 与 Story 上下文；「修改共享必须检查引用」有明确落点）。影响：Repository 8 → 9；增加「Story 级 `shared_ref` 必须指向存在的共享档案」校验。

---

# A6. ContextEngine

**设计修正**：取消 Stage 0 的单一优先级表（当时把事实、认知、指令混为一套），改为**三个独立信息层**。

| 层 | 内容 | 规则要点 |
| --- | --- | --- |
| 客观事实层 | 已审故事事实、`WorldSetting`（尤其 `hard`）、人物真实身份/`secret`、`PlotEvent`、已审场景与镜头 | 生成结果不得与之矛盾（除非走新版本流程） |
| 角色认知层 | `knows / does_not_know / misbelieves / conceals / learned_at`、主观判断 | ① **单向**：事实 → 认知，认知不得修改事实；② 不同角色不同时间认知不同；③ 角色视角只注入该角色**该时间点**已知信息，`does_not_know` 不得出现；④ AI 不得因「角色不知道」改变事实；⑤ 按 **Story + Character** 定位，跨 Story 不复用；⑥ 共享档案只入事实层，本 Story 认知只入认知层 |
| 创作指令层 | 用户临时要求、修改意见、AI 修改建议、反转提议、世界观变更提议 | ① 修改已审内容必须：新版本 → 保留旧版本 → 显示影响 → 检查下游 → 重新审核；② 与事实冲突时形成「变更提案」，**不直接覆盖**；③ AI 建议默认只作建议 |

**组合规则**：作者视角（事实为基准，认知推动机，指令作约束）；角色对话（事实为真相，只注入此刻已知，指令调表达）；分镜/出图（事实 + 出场角色当时认知 + 指令）；**AI 审核（只用事实，不注入创作指令）**。

**9 项必备能力**：按目标组装（`ContextRequest(purpose, story_id, scene_id, shot_id, extra_refs)`）、按 ID 按需加载、按剧情时间过滤事件、按认知过滤、Token 预算 `fixed → reserved → elastic`（超限先压弹性段）、压缩历史摘要、输出 `MISSING:`、`ContextBundle.manifest` 记录来源与版本、防止 AI 擅自改事实。

**11 个测试场景 T1~T11**：T1 角色不知 X；T2 事件前后变化；T3 误解；T4 隐瞒；T5 改已审规则；T6 已审 vs 草稿；T7 超预算；T8 缺失信息；T9 同场景认知冲突；T10 **AI 审核不注入指令**；T11 **同一共享人物出现在两篇 Story**（各自注入共享档案 + 本 Story 认知；A 的认知不得出现在 B；共享档案变更后两篇相关对象均 `stale`）。

---

# A7. 13 个生产阶段、9 个审核门禁、依赖与状态机

## A7.1 唯一阶段定义表（13 阶段 × 9 字段，全文以此为准）

| stage_id | stage_name | ai_generation | ai_review | human_review | gate_required | pass_condition | reject_target | dependencies |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `story_idea` | 故事创意 | 是（`concept`） | 否 | 是 | 是 | 选定 1 个创意且 `human_approved` | 自身 | 无 |
| `outline` | 故事大纲 | 是（`planner`） | 否 | 是 | 是 | 大纲生成且 `human_approved` | `story_idea` | `story_idea` |
| `character_world` | 人物 + 世界观 | 是（`planner`） | 否 | 是 | 是 | ≥1 角色且 ≥1 世界观，均 `human_approved` | `outline` | `outline` |
| `full_story` | 完整故事 | 是（`writer`） | **是（`reviewer`）** | 是 | 是 | AI 审核记录存在 + 人工 `human_approved` | `outline` | `character_world` |
| `scene_breakdown` | 场景拆分 | 是（`planner`） | 否 | 是 | 是 | Scene 生成且 `human_approved` | `full_story` | `full_story` |
| `shot_design` | 镜头设计 | 是（`writer`） | 否 | 是 | 是 | 全部 Shot 生成、整阶段 `human_approved` | `scene_breakdown` | `scene_breakdown` |
| `visual_assets` | 视觉设定 | 是（`image` 参考图 / `fast` 提示词） | 否 | 是 | 是 | 定妆与风格参考已批准 | `character_world` | `shot_design` |
| `image_gen` | 图片生成 | 是（`image`） | 否 | 是 | 是 | 每个需出图的 Shot ≥1 个 `approved` 候选 | `shot_design` | `visual_assets` |
| `video_gen` | 视频生成 | 是（`video`） | 否 | 是 | 是 | 需视频的 Shot 均有已批准候选 | `shot_design` | `image_gen` |
| `audio_prod` | 音频制作 | 是（`voice` / `audio`） | 否 | 是 | 是 | 配音、音效、BGM 均生成且 `human_approved` | **按问题性质分级**（A7.7）：音频技术 → 本阶段；剧本内容 → 经 `DependencyAnalyzer` 判定 `full_story`；镜头表达 → `shot_design` | `image_gen` |
| `post_prod` | 后期合成 | 否（本地渲染） | 否 | 是 | 是 | 成片产出且 `human_approved` | `video_gen` / `audio_prod` | `video_gen`, `audio_prod` |
| `final_review` | 最终审核 | 否 | **是（`reviewer`，整片）** | 是 | 是 | 人工最终 `human_approved` | `post_prod` | `post_prod` |
| `export` | 导出 | 否 | 否 | **否** | **是（前置条件型）** | `final_review=human_approved` + 字段校验 | `final_review` | `final_review` |

> `video_gen` 与 `audio_prod` 在架构上无强依赖，生产顺序可按实际工序调整，但**人工确认不得取消**。

## A7.2 9 个审核门禁 = 9 个人工作业批次

| # | 门禁 | 放行条件 |
| --- | --- | --- |
| 1 | `story_idea` | 人工选定创意 |
| 2 | `outline` | 人工通过大纲 |
| 3 | `character_world` | 人工通过人物与世界观 |
| 4 | `full_story` | 人工通过（AI 审核记录必须已存在） |
| 5 | `scene_breakdown` | 人工通过场景拆分 |
| 6 | `shot_design` | 人工通过镜头设计 |
| 7 | `visual_assets` + `image_gen` | 视觉设定 + 逐个候选图（「视觉生产」门禁） |
| 8 | `audio_prod` + `video_gen` | 音视频（「音视频生产」门禁） |
| 9 | `post_prod` + `final_review` | 成片（「成片」门禁） |

**合并理由**：门禁是**人工作业批次**，不是阶段 ID 的镜像；合并只影响 UI 分组与计数，**不降低任何阶段审核要求**——合并覆盖的每个阶段仍有独立 `human_approved` 与 ReviewRecord。**唯一无独立人工审核的阶段是 `export`**（不改变创作内容，安全性由 `final_review=human_approved` 前置条件保证），但它仍为前置条件型门禁。

## A7.3 门禁六条硬规则

1. AI 通过不能替代人工通过（`ai_passed` → 人工操作才能 `human_approved`）。
2. 每个阶段开始前校验上游；未满足即拒绝 AI 生成（避免浪费费用）。
3. 退回后重新生成必须形成新版本；旧版本保留，`active_version` 指向新版本。
4. 审核记录只追加，不删除；新记录用 `supersedes` 串链。
5. 修改已审内容必须经 `DependencyAnalyzer` 计算下游，受影响对象置 `stale` 并回 `pending`。
6. 不得为凑门禁数量而遗漏审核。

## A7.4 审核状态机（7 状态）

| 状态 | 含义 | 可转入 |
| --- | --- | --- |
| `pending` | 已生成待审 | `ai_reviewing` / `human_approved` / `human_rejected` |
| `ai_reviewing` | AI 审核中 | `ai_passed` / `ai_rejected` |
| `ai_passed` | AI 通过，**不可放行** | `human_approved` / `human_rejected` / `revision_requested` |
| `ai_rejected` | AI 未通过 | `revision_requested` |
| `human_approved` | **唯一放行状态** | 下游可执行；上游变更 → `revision_requested` |
| `human_rejected` | 人工否决 | `revision_requested` |
| `revision_requested` | 退回修改 | 新版本生成后 → `pending` |

硬规则：只有 `human_approved` 解锁下游；`ai_passed` 不得自动升级；非法转换抛错（有单测）；每次转换写追加式事件（human / ai / system）。

## A7.5 ReviewRecord（13 字段）

`review_id` / `target_kind`（`story / scene / shot / asset / render / stage / shared_character / shared_world`）/ `target_id` / `target_version`（必填）/ `reviewer_kind`（human / ai / local_rule）/ `reviewer_ref` / `decision`（pass / reject / revise）/ `rubric_scores` / `issues[]` / `comment` / `created_at` / `supersedes` / `prompt_id`（AI 审核必填）。

约束：只追加；AI 与人工分别记录；`decision` 只代表该审核者判断，状态推进由工作流层按「记录 + 门禁」决定。

## A7.6 版本冻结

1. AI 不得自动修改 `human_approved` 内容。
2. 用户修改：新版本 → 原审核保留 → 新状态 `pending` → `DependencyAnalyzer` → 受影响下游标过期并重审。
3. `VisualAsset.approved=true` 只能显式替换，不随内容重生成而覆盖。

## A7.7 `reject_target` 通用判定规则与 `audio_prod` 分级退回（终审修订）

**通用规则（适用全部 13 个阶段）**：`reject_target` 是**默认退回目标**，不是唯一允许的退回点；审核意见先分类问题性质，再决定退回层级：

| 问题性质 | 判定 | 退回目标 |
| --- | --- | --- |
| 执行层问题（生成参数、素材质量、技术错误） | 本阶段产物未达要求，上游输入正确 | **本阶段** |
| 上游内容问题（剧本 / 设定 / 镜头设计内容错误） | 根源在上游已审内容 | 经 `DependencyAnalyzer` 计算受影响对象后，退回对应上游阶段 |

退回必须产生目标阶段的新版本并经 `DependencyAnalyzer` 把受影响下游标 `stale`；**不允许**把执行层问题直接退回完整故事。

**`audio_prod` 分级退回表（取代单一 `reject_target = full_story`）**：

| 问题性质 | 退回目标 | 说明 |
| --- | --- | --- |
| 音频技术问题（发音 / 噪音 / 时长 / 格式 / 配音与台词不匹配的技术性错误） | **`audio_prod` 本阶段** | 默认本阶段局部修复（重生成该条配音 / 音效 / BGM），不动上游 |
| 剧本内容问题（台词措辞、语气提示、与 `full_story` 矛盾） | **`full_story`**（必须经 `DependencyAnalyzer`） | 修改 `full_story` → 新版本 → 下游受影响对象 `stale` 并逐级重审 |
| 镜头表达问题（该镜头的口型 / 台词切分 / 镜头文案） | **`shot_design`** | 修改目标 Shot → 新 Shot 版本 → 该镜头下游素材 `stale` |

退回层级由人工审核者在 `ReviewRecord.issues[].code` 中标注问题分类，工作流层按标注路由，**不自动猜**。

## A7.8 共享资源审核记录归属（终审新增，P2 / P6 实现约束）

`target_kind` 为 `shared_character` / `shared_world` 的审核记录是 **Project 级**，其余为 **Story 级**。6 条规则：

| # | 规则 | 实现约束 |
| --- | --- | --- |
| 1 | 归属判定看 `target_kind`，**不看存储路径** | 两类记录可同存 `reviews/`，但由不同 Repository 管理，不得混用查询接口 |
| 2 | Project 级记录不携带单一 `story_id` 作为归属；经 `DependencyImpact` / `referrers()` 关联全部引用 Story | `SharedResourceStore.reviewing_stories(entity_id)` 给出受影响 Story |
| 3 | Story 级审核不得改写共享资源，只能产生「变更提案」 | P6 必须拒绝「Story 审核直接写 `shared/`」的调用路径（有测试） |
| 4 | 共享资源修改后的重审是 **Story 级**的：受影响 Story 对象 `stale` + `pending`，各自重审 | V3.0 只要求「标记 + 提示」，不要求跨 Story 自动编排 |
| 5 | Project 级记录由 `SharedResourceStore` 写入与查询；Story 级由 `ReviewRepository` 负责；共用 §A7.5 字段与只追加约束 | P2 建立 Project 级审核路径；P6 接入门禁；**P2 与 P6 验收均需「同一共享人物被两篇 Story 引用」用例** |
| 6 | `supersedes` 只能在同类 `target_kind` 内串联，不跨归属 | `ReviewRepository.append()` 校验 `target_kind` / `target_id` 一致 |

> 对应 ContextEngine 测试场景 T11。

---

# A8. Provider、能力类型、槽位、PromptTemplate

## A8.1 5 个能力类型（Provider「能做什么」）

| 能力 | 说明 | 当前/预期 Provider |
| --- | --- | --- |
| `TEXT` | 文本生成 | DeepSeek、OpenAI GPT |
| `IMAGE` | 图片生成 | SiliconFlow |
| `VIDEO` | 视频生成 | 预留 |
| `AUDIO` | 音频合成（`voice` 配音 / `audio` 音效 BGM） | SiliconFlow |
| `VISION` | 图像理解（预留） | 预留 |

## A8.2 9 个业务槽位（系统「在哪个环节调用 AI」）

| # | 槽位 | 主要职责 | 能力 | 媒体接口 |
| --- | --- | --- | --- | --- |
| 1 | `planner` | 规划与结构（大纲、场景拆分） | TEXT | 文本接口 |
| 2 | `writer` | 正文生成（剧本、分镜文案） | TEXT | 文本接口 |
| 3 | `concept` | 创意生成 | TEXT | 文本接口 |
| 4 | `fast` | 快速辅助（出图提示词） | TEXT | 文本接口 |
| 5 | `reviewer` | 独立 AI 审核 | TEXT | 文本接口 |
| 6 | `image` | 图片生成 | IMAGE | `<ImageProvider>` |
| 7 | `video` | 视频生成 | VIDEO | `<VideoProvider>` |
| 8 | `voice` | 角色配音 / 语音合成 | AUDIO | `<SpeechProvider>` |
| 9 | `audio` | 音效 / BGM / 音频处理 | AUDIO | `<AudioProvider>` |

**`voice` ≠ `audio`**：业务上分别是「角色台词的声音」与「环境音/音效/BGM」；输入、输出、审核维度不同；**可同一 Provider 提供，但槽位配置必须分开**，便于独立替换。不存在「AUDIO 槽位」——`AUDIO` 是能力类型。

## A8.3 Provider 接口与约束

```python
class Provider(Protocol):
    provider_id: str
    def capabilities(self) -> set[Capability]
    def chat(self, request: ChatRequest) -> ChatResult
    def test_connection(self) -> ConnectionResult

class ProviderRegistry:
    def register(self, reg: ProviderRegistration) -> None
    def get(self, provider_id: str) -> Provider
    def state(self, provider_id: str) -> ProviderState
```

- 业务代码只出现 `Slot` 与 `provider_id`，**不出现具体模型名**（静态扫描断言）。
- 文本与媒体 Provider **接口分离**（不同方法签名），媒体方法不污染文本抽象。
- 统一 `ChatRequest / ChatResult`，`story_engine` 只消费 `ChatResult.text`。
- `reviewer` 必须指向**与 `writer 不同**的 Provider 或模型（OQ-01 仍待定：单 Provider 时是否允许同 Provider 不同模型）。
- 槽位→`(provider_id, model)` 映射由用户配置；**价格不写死**，来自 `providers.json`。
- 默认并发 **2**，可配置。
- 成本护栏 **10 项**：单次预算、单项目预算、每日预算、最大并发、失败重试上限、重复任务防护、超预算确认、Token 统计（UsageLedger）、成本估算、Provider 价格外置。

## A8.4 PromptTemplate（PromptStore，7 字段）

`prompt_id`（内容哈希 + 序号）/ `version` / `genre`（`*` 通用）/ `stage`（`outline` / `full_story` / `shot_design` …）/ `content` / `created_at` / `description`。

规则：① 每次生成记录实际 `prompt_id + version`（写 UsageLedger 与 ReviewRecord）；② 多模型对比必须同 Prompt 版本 + 同上下文基准；③ V2 内联 Prompt 在 P5 抽成 `version=1` 文件，行为不变（可由快照对比）。

**归类**：PromptTemplate 存于**用户配置目录、不随项目走**，属**创作基础设施对象**，不进入 Repository 族、不计入 12 个领域实体。

---

# A9. 迁移与安全机制

> 性质：设计方案，**本阶段不执行任何迁移**。权威文件：迁移方案。

## A9.1 总原则与前置红线

总原则：用户数据零丢失；先备份后迁移（只写新副本）；可回退；按 ID 关联不按 index；**自动迁移最小化**（能读时兼容就不写时转换，写盘必须用户显式确认）；不静默继续（不猜测、不补空、不忽略）；测试先行。

| 编号 | 缺陷（V2 现状，已核实存在） | 迁移要求 |
| --- | --- | --- |
| **K-01** | `_normalize_story` 捕获异常后 `data.pop("story")`（`project_manager.py:455/459/465`），`open_project` 随即写盘（`225-226`） | **打开即永久丢 story** → 必须 V2.3 修复并回归通过后才能迁移 |
| K-02 | `import_story` 四次独立写盘（`main_window.py:1151`） | P0 改事务式暂存提交 |
| A-05 | `_sync_timeline_to_story` 按 index 对齐（`project_manager.py:704`） | P0 增加只读检测告警；V3 按 `shot_id` 关联 |
| A-03 | `set_story` 每次存正式版本 | P0 增加 `source` 标记 |

## A9.2 版本判定矩阵（`schema_version` 唯一权威）

| 状态 | 判定 | 行为 |
| --- | --- | --- |
| 文件不存在 | 无效项目 | 报错；不创建空项目 |
| 缺失 / 非数字 | 兼容检查 | 走 V2 升级路径，**不猜测为 V3** |
| `== 1` | 先 V2 upgrade 后重判 | 必须读到 `2` |
| `== 2` 且无 `story/` | 需 P3 迁移 | 用户确认后执行 |
| `== 2` 且有 `story/` | **仍按 V2 处理** | 冲突告警，不自动升级 |
| `== 3` 完整 | V3 | 正常打开 |
| `== 3` 不完整 | 损坏 | 只读 + 报错，不修复写入 |
| `> 3` | 未来版本 | **只读，禁止写回**，UI 提示 |

硬规则：禁止「2 被识别为完整 V3」；未来版本所有保存被拦截。

## A9.3 迁移过程（6 个阶段 + 阶段 0.5、7 类步骤；终审修订：事务日志先于暂存副本；R4：日志与暂存副本物理隔离）

**暂存目录结构（R4 固定）**：`.migration_staging/<tx_id>/transaction.json`（事务元数据，日志本体，**不属于被复制的项目内容**）+ `.migration_staging/<tx_id>/payload/`（`STAGE_COPY` 复制与校验的唯一目标，含异常 Story 原文 `raw/` 与 V3 转换副本）。两者**物理隔离**；旧口径 `.migration_staging/<name>-<ts>/` 作废。

```
阶段 0   预检（只读，不是事务步骤）：身份、schema 判定、assert_p0_fixed()、路径边界、目标冲突 —— 任一失败不写文件
阶段 0.5 初始化事务日志（终审新增；R4：日志先于暂存副本）：预检通过后创建 .migration_staging/<tx_id>/ 并在其内原子写 transaction.json
          （state=OPEN，steps 含 STAGE_COPY 的全量预生成清单）—— 日志原子写失败 → 中止本次迁移，**禁止开始 STAGE_COPY**
阶段 1   生成暂存副本（STAGE_COPY，事务内第一步）：先持久化 INTENT（源树哈希）→ 复制到 .migration_staging/<tx_id>/payload/
          → payload 树哈希（不含 transaction.json）校验通过才记 COMPLETED；原项目零写入
阶段 2   全量校验（只读）：前置条件 STAGE_COPY = COMPLETED；数量 / ID 双向核对 / 引用 / 素材映射 / 反序列化 —— 失败只删 payload/，transaction.json 保留，原项目不动
阶段 3   备份（BACKUP）：复制到 .backups/<name>-v2-<ts>/ + 完整性校验 —— 失败 → 事务 ROLLED_BACK，只删 payload/（保留 transaction.json），原项目不动
阶段 4   提交（MKDIR / PLACE_FILE / PLACE_TREE / MOVE_TREE / REWRITE_PROJECT_JSON）：每步「写 INTENT → 执行 → 验证 → COMPLETED」；不删除原始 V2 文件
阶段 5   收尾（FINALIZE）：写 migration_report.json；COMMITTED 后清理暂存区（CLEANED：先删 payload/，最后删 transaction.json）
```

**哈希计算范围（R4；最终核验修订：哈希边界）**：`STAGE_COPY.expected_source_hash` = 原项目树规范化哈希（仅排除项目树内可识别的根级 `.migration_staging/`、`.backups/` 与 `migration_report.json`）；`STAGE_COPY.expected_target_hash` = `payload/` 内的**完整项目树**规范化哈希——`transaction.json` **不在范围内是因为它在 `payload/` 的父目录，结构上就不被计算**，而非靠文件名排除；另按**明确的相对路径**排除 `payload/.migration_tmp/`，**禁止**任何按文件名的通配过滤（`*.tmp` / `*.part` 等）。哈希计算前先执行 **payload 目录结构合法性检查**。

**payload 目录结构合法性检查（哈希前置）**：① `payload/` 存在且为目录；② `payload/` 下任何层级出现 `transaction.json` → **结构非法**（`RECOVERY_REQUIRED`「payload 结构非法：不允许包含 transaction.json」），**不得**按文件名排除后继续计算；③ 除 `payload/.migration_tmp/` 外不得存在其它事务元数据残留（`transaction.json.part` / `transaction.json.tmp`，按具体文件名判断，不做通配；用户项目自身的 `*.tmp` / `*.part` 合法并计入哈希）；④ `payload/` 下所有条目解析符号链接后都在 `payload/` 之内；⑤ 通过后才计算树哈希，检查结果写入步骤 `note`。`transaction.json` 的任何更新（含 `recovery[]` 追加）**不得**改变 payload 哈希判定。

步骤幂等语义要点：`STAGE_COPY` 目标 `payload/` 不存在 → 执行，payload 树哈希 = `expected_target_hash` → 补记 COMPLETED，哈希不符（不完整副本）→ **不补记、不合并**，按 A9.10 处置；`BACKUP` 目标已存在且哈希一致 → 已完成；`MKDIR` 已是目录 → 已完成；`PLACE_FILE` / `PLACE_TREE` 源必须是已验证的 `payload/` 内容，目标哈希 = `expected_target_hash` → 已完成，否则冲突人工；`REWRITE_PROJECT_JSON` 原文件先备份到 `.backups/`，已是 V3 且哈希一致 → 已完成，仍为 V2 → 重试。

### A9.3.1 暂存复制（`STAGE_COPY`）中断后的恢复判定（终审新增；R4：判定对象为 `payload/`）

| 日志状态 | `payload/` 实际状态 | 恢复动作 |
| --- | --- | --- |
| `STAGE_COPY` = PENDING，`payload/` 不存在 | — | 从阶段 0.5 的事务继续：写 INTENT → 复制 |
| `STAGE_COPY` = INTENT，`payload/` 不存在 | — | 重写 INTENT 后重新完整复制 |
| `STAGE_COPY` = INTENT / EXECUTING，`payload/` 存在且树哈希一致（不含 `transaction.json`） | 已完整写完但未记 COMPLETED | 补记 COMPLETED（`verified_by = recovery_hash_check`） |
| `STAGE_COPY` = INTENT / EXECUTING，`payload/` 存在但哈希不符 | **部分复制（不完整副本）** | **只删除 `payload/`（`transaction.json` 保留）后重建**；不补记、不合并、不校验 |
| 删除 `payload/` 失败（文件占用） | — | `RECOVERY_REQUIRED`（`transaction.json` 仍在，下次恢复继续） |
| 原项目源树哈希与 INTENT 记录不一致 | 复制期间原项目被外部修改 | 停止，`RECOVERY_REQUIRED`（「迁移期间原项目已被修改」） |
| 已存在另一未完成事务 | — | 不新建事务；先处理已有事务 |

### A9.3.2 `MOVE_TREE` 的限制（终审修订）

1. 只允许移动**经过验证的暂存内容**（源路径必须在 `.migration_staging/<tx_id>/payload/` 之下，且 `STAGE_COPY` 已 COMPLETED；`transaction.json` 不在可移动范围内）。
2. **不允许移动原始 V2 文件**；原始 V2 文件在整个迁移过程中必须保留（回滚依据、V2 兼容期依据）。源位于原始项目目录内 → **拒绝执行**（`RECOVERY_REQUIRED`，报错「不允许移动原始 V2 文件」）。
3. 需要在原项目内做「移动 / 重命名旧目录」时，必须有**独立授权**（用户显式确认）与**独立恢复机制**（可逐步撤销），默认**不实现**。
4. 执行前做源路径归属校验；校验失败的步骤进入 `RECOVERY_REQUIRED`，不执行移动。

## A9.4 步骤记录（10 字段）与 6 状态

`step_id`（稳定，重试不变）/ `operation` / `source_path` / `target_path` / `expected_source_hash` / `expected_target_hash` / `state` / `started_at` / `completed_at` / `error`；可选 `attempts / verified_by / note`。

| 状态 | 含义 | 可转入 |
| --- | --- | --- |
| `PENDING` | 未开始 | `INTENT_RECORDED` |
| `INTENT_RECORDED` | **已持久化意图，文件操作未开始** | `EXECUTING` / `FAILED` |
| `EXECUTING` | 文件操作中（进程在此终止需按实际文件判定） | `COMPLETED` / `FAILED` / `RECOVERY_REQUIRED` |
| `COMPLETED` | **已按哈希验证** | 终态 |
| `FAILED` | 失败且无不可判定副作用 | `INTENT_RECORDED`（仅可安全重试时） |
| `RECOVERY_REQUIRED` | 自动恢复无法定论 | 仅人工写入结论 |

事务状态为**派生**：`OPEN` / `RUNNING` / `COMMITTED`（全部 COMPLETED）/ `ROLLED_BACK`（回滚后校验通过）/ `RECOVERY_REQUIRED` / `CLEANED`。

## A9.5 六条硬规则与「非原子」声明

1. 先持久化 INTENT 再执行。2. 操作完成后按哈希验证目标。3. 验证成功才写 `COMPLETED`。4. 每次状态更新原子写（`.part` → `os.replace`）。5. 进程异常后按「日志 + 实际文件状态」共同判断。6. **不得仅凭日志推断文件已完成**。

**明确声明**：阶段 4（提交）**不是数据库意义上的原子事务**。它保证：原项目任何时刻可从 `.backups/` 完全恢复；每步可从日志得知意图、从文件得知实际结果；最坏情况是「V2 + 部分 V3」中间态，但**没有数据被删除**。日志与文件始终可能不一致：**以实际文件为主、日志为辅**。

## A9.6 恢复机制

**入口**：① 应用启动扫描 `.migration_staging/*/`，逐目录检查 `transaction.json` 与 `payload/` 的存在性；② 用户直接打开单个项目（匹配关联事务 + `.needs_manual_review` 标记，须先恢复/回滚/人工）；③ 迁移入口再次被调用（不新建事务，进入恢复）。恢复完成前项目**只读**；启动扫描**不修改**任何文件。

**按实际状态判定的恢复动作表（7 行）**：

| 实际状态 | 策略 |
| --- | --- |
| 操作未开始（源哈希符合、目标不存在） | 安全重试（重写 INTENT 再执行） |
| 日志 `INTENT_RECORDED` 且目标不存在 | 验证源哈希后重试 |
| 目标已就位且哈希符合，日志停在 INTENT/EXECUTING | **补记 `COMPLETED`**（`verified_by=recovery_hash_check`），不重复执行 |
| 源与目标同时存在且冲突 | 停止自动恢复 → `RECOVERY_REQUIRED`，不覆盖任何一方 |
| 源与目标均不存在 | `RECOVERY_REQUIRED` |
| 校验失败（不可读 / 结构不符） | 禁止继续 → `RECOVERY_REQUIRED`，提供整体回滚 |
| 备份缺失或校验失败 | 禁止自动回滚 → `RECOVERY_REQUIRED` |

**启动扫描形态（R4，按两种存在性识别）**：

| 扫描发现 | 判定 | 动作 |
| --- | --- | --- |
| `transaction.json` 存在、`payload/` 不存在 | 日志先行（阶段 0.5 后、复制前中断），合法形态 | 按 `STAGE_COPY` 状态继续（PENDING / INTENT → 从头复制） |
| `transaction.json` 存在、`payload/` 存在但不完整 | 复制中断或残留 | 以实际文件为主：`payload/` 完整且未记 COMPLETED → 补记；不完整 → 只删 `payload/` 重建（`transaction.json` 保留） |
| `payload/` 完整但日志尚未写入 COMPLETED | 写完未记（A9.5 硬规则 5） | 补记 COMPLETED（`verified_by = recovery_hash_check`），不重复复制 |
| `transaction.json` 不存在、`payload/` 存在 | **孤儿暂存** | 不得为救回孤儿 `payload/` 反推创建日志；按 A9.10 规则 7 处置（拒绝为有效结果） |

**两种终局**：继续完成（全部步骤可重试或可补记 → 重试剩余 → COMMITTED → 收尾）；回滚到备份（任一步骤 RECOVERY_REQUIRED 或用户选择，且备份校验通过 → 同样步骤化覆盖 → 校验项目哈希 = 迁移前快照 → ROLLED_BACK）。

**幂等 4 条**：恢复动作写入 `recovery[]`（写入 `transaction.json`，不改变 `payload/` 树哈希）；每个动作先判「是否已做过」（查目标哈希）；回滚先把当前目录移到项目外 `recovery_trash/` 而非直接删除；单元测试须包含「恢复被中断再恢复」。

## A9.7 目标路径冲突（项目内已有 `story/`）

| 情况 | 处理 |
| --- | --- |
| 目标不存在 | 正常 `PLACE_TREE` |
| 目标为空目录 | 允许合并（逐步 MKDIR + PLACE_FILE，逐步校验） |
| 目标含文件 | **不允许直接覆盖**；做清单 + 哈希 + schema 检查 |
| 检查通过（均为本次应生成且哈希一致） | 视为上次未完成迁移 → 进入恢复流程 |
| 检查不通过 | **停止迁移**，保留原始内容，报告列冲突文件；**不删、不覆盖、不重命名旧目录** |
| 目标是文件 | 停止并报告 |

硬规则：不得删旧目录解决冲突；无法证明安全即停止（迁移器**不提供「强制覆盖」按钮**）；冲突检查在阶段 0，早于任何写入；结果写入报告。

## A9.8 异常 Story

| 情况 | 处理 |
| --- | --- |
| `story` 缺失 | 保留原始字节，不建空 Story；有快照则提示恢复并暂停等待；无快照则标 `needs_manual_review`，**不写任何 V3 结构** |
| 结构异常 | 原文复制到暂存区 `.migration_staging/<tx_id>/payload/raw/`，标 `needs_manual_review`，不写回；用户确认后才继续 |

人工恢复：原始数据在 `.backups/` 与暂存区两处且均哈希校验；从 `versions/` 快照恢复须记录来源（路径 + 哈希 + 时间）与结果，结果作为待确认内容而非已审；无法恢复则保持异常状态、不伪造补位；**有损恢复须用户显式确认**（列出将丢失/改变的内容）；全部动作追加写入 `recovery_audit[]`（`{time, actor, action, source, result, note}`，只追加）。

异常 Story 在事务开始前识别：**不创建事务**；恢复得到的 story 视为用户确认输入，从阶段 0 重新开始（新 `tx_id`）；有损迁移报告标 `lossy=true`。

## A9.9 其他边界

- **Windows**：文件占用（WinError 32）中止并保持可重试；断电容忍由启动恢复处理；磁盘空间需 ≥ 原项目 × 2.2；路径长度预检 > 260 中止；备份失败只删 `payload/`（`transaction.json` 保留）；部分 rename 成功由逐步日志恢复。
- **路径边界**：暂存/备份在项目外；校验互为父子即中止；扫描跳过 `.migration_staging/` 与 `.backups/`。
- **时间轴合并**：orphan 保留（`source=orphan`，「未关联」分组）；无 `shot_id` 保留为手工镜头；重复 `shot_id` 全部保留并标记；素材缺失标 `missing_file=true` 不删引用。
- **备份保留建议值**：「最近 3 次或 30 天，取久」——**仅为建议，未经确认（OQ-05）**。
- **不静默迁移**：任何写盘迁移须显式确认（具体交互见 OQ-07）。

### A9.10 不完整暂存副本的处置（终审新增，9 条规则；R4 新增 8 / 9）

**结论：不完整暂存副本不得作为有效迁移结果。**

| # | 规则 |
| --- | --- |
| 1 | 有效性判定唯一依据 = `STAGE_COPY` 为 COMPLETED 且暂存区树哈希 = `expected_target_hash`；缺一即不完整（阶段 2 入口硬校验） |
| 2 | 不得用于：全量校验、备份、任何 `PLACE_FILE` / `PLACE_TREE` / `MOVE_TREE`、`REWRITE_PROJECT_JSON`、生成「迁移成功」结论 |
| 3 | 不得被「补写」成完整（不允许只复制缺失文件或保留旧文件合并），只能整树重建 |
| 4 | 不得当作「部分成功」呈现；迁移报告标 `staging_incomplete=true` |
| 5 | 处置：删除（项目外派生数据，可安全重建）→ 重置 `STAGE_COPY` → 重新完整复制；删除失败 → `RECOVERY_REQUIRED` |
| 6 | 原项目在复制期间被外部修改（源哈希变化）→ 不重建，进入 `RECOVERY_REQUIRED` |
| 7 | 孤儿暂存目录（无对应事务）同样不得被接受为有效结果 |
| 8 | **删除范围只限 `payload/`，`transaction.json` 必须保留**（恢复与审计依据）；`CLEANED` 收尾时按「先删 `payload/` → 再删 `transaction.json`」顺序执行，任一步失败保留日志待下次清理 |
| 9 | **哈希边界**：`transaction.json` 位于 `payload/` 父目录、不属于 payload 树哈希；`payload/` 内出现 `transaction.json` 一律判**结构非法**（不得按文件名排除绕过）；`.migration_tmp/` 只按相对路径 `payload/.migration_tmp/` 排除，禁止文件名通配；哈希前先执行结构合法性检查；`transaction.json` 自身原子写失败时不写 `COMPLETED`，且该事务禁止开始 `STAGE_COPY` |

---

# A10. `assert_p0_fixed()` 规则

**性质**：不是版本号判断，而是迁移入口在**任何写操作之前**必须通过的运行时检查；6 项任一不满足即拒绝迁移。

| # | 检查项 | 方式 | 不满足 |
| --- | --- | --- | --- |
| C1 | 已具备经过验证的迁移能力版本 | 构建号 / 能力清单声明 `migration_capability >= 1` 且与迁移器版本常量一致 | 拒绝 |
| C2 | K-01 安全能力**实际实现** | 运行时探测：对**内存中**构造的「story 结构异常、升级会失败」样本调用 `_normalize_story`（不触碰用户文件），断言 story 仍存在 | `K01_GUARD_MISSING` |
| C3 | K-01 回归证据存在 | 随包携带 `p0_verification.json`（P0 验收产出：测试名 / 时间 / 结果 / 代码指纹）；运行时校验完整、全绿、指纹与 `project_manager` 文件哈希一致 | `P0_EVIDENCE_MISSING` |
| C4 | 迁移路径不会在升级失败时删 Story | 静态断言：迁移器不调用移除 story 的路径；分派在异常时只「复制到暂存 + 标记」 | 完整性校验失败 |
| C5 | 迁移前能完成备份与校验 | 预检：目录可建可写；磁盘 ≥ 原项目 × 2.2；备份校验函数可用 | 中止（不进入写） |
| C6 | 具备事务日志与恢复机制 | 日志模块可加载；原子写探针回读自检；启动恢复入口已注册 | `TRANSACTION_LOG_UNAVAILABLE` |

**两个阶段必须区分**：

| 维度 | 开发期 P0 验收 | 迁移时运行时检查 |
| --- | --- | --- |
| 执行者 | 开发者 / 测试 | 每个用户每次迁移 |
| 内容 | 完整测试套件（K-01 / K-02 / A-05 / A-03 / 309 原有用例） | 仅 C1~C6 |
| 结果 | 测试报告 + `p0_verification.json` | 逐项布尔，写入迁移报告 |
| 频率 | P0 交付时 + 代码变更时 | 每次迁移入口（毫秒级） |

硬规则：**每次用户迁移不得运行整个测试套件**；**不得仅修改版本号绕过**（C2 行为探测、C3 指纹校验）；C2 样本在内存中；结果写入 `migration_report.json`。

---

# A11. P0~P9 开发路线

| 阶段 | 名称 | 核心产出 | 依赖 |
| --- | --- | --- | --- |
| **P0** | V2.3 数据安全补丁 | K-01 / K-02 / A-05 只读检测 / A-03 来源标记 | —（独立于 V3） |
| P1 | 基础架构 | Repository 契约（9 个中 `ProjectStore` / `VersionStore` 先行）、原子写、任务状态、架构测试 | P0 |
| P2 | 故事数据层 | Story / Character / Relationship / WorldSetting / PlotEvent / KnowledgeState / 多 Story / **共享资源基础能力** | P1 |
| P3 | Scene/Shot 实体化 | ShotVersion / AssetRegistry / 单镜重生成 / 迁移器 | P1, P2 |
| P4 | AI Provider | ProviderRegistry / DeepSeek / OpenAI / UsageLedger / CostGuard | P1 |
| P5 | PromptStore + ContextEngine | 三层上下文、Token 预算、T1~T11 | P2, P4 |
| P6 | 审核与工作流 | WorkflowEngine / ReviewRecord / 门禁 / 冻结 / DependencyAnalyzer | P1, P2, P3, P5 |
| P7 | 质量体系与题材包 | AI 独立审核 / 多模型比较 / HorrorPack | P4, P5, P6 |
| P8 | UI 适配 | 工作台 / 人物中心 / 世界观中心 / 审核中心 / 镜头管理 / 模型对比 | P1~P7（**V3.0 发布**） |
| P9 | 短剧生产 | 图片 / 视频 / 配音 / 音效 / 后期 / 导出 / 最终审核 | **P3, P4, P6, P8** |

- 拓扑顺序：`P0 → P1 → P2 → P4 → P3 → P5 → P6 → P7 → P8 → P9`（P2 与 P4 可交换）；**无循环依赖**。
- **P9 是完整阶段，不与 P7/P8 并行。** 「P9 预备工作」可在 P4（媒体 Provider 适配、媒体任务基础设施）等节点提前，但**不计入 P9 出口**、不改冻结数据模型、不动 P8 UI 主线。旧表述「与 P7 部分并行」**已作废**。
- 每阶段须：独立任务书 → 实现 → 变更报告 → 单测 + 309 回归 → 架构检查 → **ChatGPT 审查后进入下一阶段**。

---

# A12. 真实端到端验收 E1~E10

| # | 测试 | 要点 | 阶段 | 真实 API |
| --- | --- | --- | --- | --- |
| E1 | DeepSeek | 4 个文本槽位真实调用；解析链在真实返回上工作；UsageLedger 记录 token | P4 | 是 |
| E2 | GPT | 同槽位真实调用；同一 `ChatRequest/ChatResult`，业务零改动 | P4 | 是 |
| E3 | 模型对比 | 同 `prompt_id` + 同 version + 同 `ContextBundle`（manifest 哈希一致）并行 ≥2 结果，各自入审核 | P7 | 是 |
| E4 | 完整流程 | 空白项目 → 创意 → 大纲 → 人物世界观 → 完整故事 → 场景 → 镜头；至少一次退回重生成（新版本、旧记录保留）；镜头管理可见全部镜头 | P6 + P8 | **否**（允许 Mock / 录制响应回放） |
| E5 | 人工门禁 | UI 不可越级；后端被拒；export 前置被拒；AI 通过不自动升级 | P6 | 否 |
| E6 | 迁移中断 | **任意一步**强杀进程；重启识别事务 → 继续/回滚；回滚路径字节级不变 | P3 | 否 |
| E7 | 镜头修改 | 已批准镜头重生成：新版本、可切回、下游素材不被覆盖只标过期 | P3 + P6 | 否 |
| E8 | 人物认知 | A 不知 X 不出现；事件前后不同；审核提示不泄露 | P5 | 是 |
| E9 | 多 Story | 两篇互不串扰；共享档案变更两篇均获提示；索引可重建 | P2 + P3 | 否 |
| E10 | GUI | 真实 tkinter 全流程 + 重开数据仍在 | P8 | 否 |

**E4 的验收口径（终审明确）**：E4 验证的是**完整流程是否走得通**（门禁顺序、版本生成、退回重生成、数据贯通、GUI 可见），不验证 Provider 接口本身，因此**允许使用 Mock Provider 或录制响应回放**。但 **E4 不替代 E1 / E2 的真实 API 验证**——DeepSeek / GPT 的真实连通性只能由 E1 / E2 以真实 API 证明；E4 通过不得写入「真实 API 已验证」的结论。

**8 条执行规则**：Mock 与真实分开（真实用 `tests/live/` 或 `--live`）；真实测试不进入默认单测；**报告中不得出现 Key 任何片段**（UsageLedger 只记 provider/model/token/成本）；**真实调用费用须事先向用户说明次数、模型、预估费用并取得同意**；**迁移类测试只允许在副本上执行**；真实 GUI 可人工 + 截图但须留可复现步骤；失败不得用 Mock 替代标「通过」；**E4 不替代 E1 / E2**（E4 允许 Mock / 录制回放，真实 API 结论只来自 E1 / E2）。

**分阶段最小验收**：P2→E9；P3→E6/E7；P4→E1/E2；P5→E8；P6→E4（后端）/E5；P7→E3；P8→E4（GUI）/E10。

---

# A13. V3.0 MVP 范围

**V3.0 定义**：可用的「故事创作 + 镜头设计 + 审核」闭环，交付 P0~P8；不要求一次完成视频与后期。

**必须交付 21 项**（原 20 项 + Stage 0.6 第 21 项）：

| # | 能力 | 阶段 |
| --- | --- | --- |
| 1 | 创建一个项目 | P1 |
| 2 | 一项目管理多篇故事 | P2 |
| 3 | 生成故事创意 | P2/P4 |
| 4 | 生成故事大纲 | P2/P5 |
| 5 | 多角色人物档案 | P2 |
| 6 | 人物关系 | P2 |
| 7 | 世界观（含 `hard`） | P2 |
| 8 | 剧情事件 | P2 |
| 9 | 角色认知状态（追加式） | P2 |
| 10 | 完整多角色故事（按认知过滤） | P5 |
| 11 | DeepSeek 与 GPT 可切换 | P4 |
| 12 | 多模型结果比较 | P4/P7 |
| 13 | 独立 AI 审核（reviewer ≠ writer） | P6/P7 |
| 14 | 重要阶段人工确认 | P6 |
| 15 | 故事版本 | P1/P3 |
| 16 | 审核记录（只追加、可查） | P6 |
| 17 | Scene/Shot 独立实体 | P3 |
| 18 | 镜头单独修改与重生成 | P3 |
| 19 | 已审内容不被静默覆盖 | P6 |
| 20 | 旧项目安全迁移（**23 类验收**：12 类项目形态 + 9 类步骤级安全 + 2 类暂存副本安全〔#20 暂存复制中断、#21 不完整暂存副本拒绝；#22 事务日志/暂存副本隔离与扫描形态、#23 哈希边界〕） | P3 |
| 21 | **项目级共享人物档案与世界观基础设定**（多 Story 复用；修改前展示引用 Story；**不要求**跨 Story 自动重审编排） | P2 |

**暂缓 9 项（架构预留）**：① 视频生成完整链路（`video` 槽位 + 接口）；② 音频制作完整链路 / 智能编排（`audio` 槽位；`voice` 沿用 V2 已实现配音）；③ 后期合成与导出自动化（`post_prod`/`export` 阶段 ID 已固定）；④ MysteryPack（GenrePack 接口已定）；⑤ 全球网络故事搜索与改编（独立项目）；⑥ 商业化（不做）；⑦ GUI 全量自动化测试（渐进）；⑧ SQLite（Repository 可映射）；⑨ 跨 Story 自动重新审核编排（`DependencyImpact` + `referrers()` 已预留）。

**V3.0 完成判定 7 条**：① 21 项通过；② 309 原有用例保留通过（或经审查的等价替换）；③ 迁移 23 类通过、失败场景原项目未破坏；④ 一个真实 V2 项目端到端迁移并人工核对；⑤ 一个完整故事走完全部门禁；⑥ 端到端验收 **E3 / E5 / E6 / E7 / E8 / E9 / E10 + Mock 方式 E1 / E2 / E4** 完成并留记录；⑦ 全部**阻塞开发**的 OQ 已确定。

---

# A14. 9 条审查意见的最终处理情况

| # | 审查意见 | 最终处理 | 落地 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | 迁移事务恢复不完整 | 逐步骤日志（10 字段 / 6 状态）；先 INTENT 后执行、验证后 COMPLETED、不得仅凭日志推断；2 个恢复入口、按实际文件状态 7 行判定、恢复幂等；目标冲突规则；异常 Story 审计；验收 12 → 19 → 21 → **23 类**；**明确声明「非数据库原子事务」** | 迁移 §1.3 / §3.2 / §3.4 / §5.1 | 已解决 |
| 2 | 槽位缺 `audio` | **9 槽位**，`voice`（配音/语音合成）与 `audio`（音效/BGM）分开配置；`AUDIO` 是能力类型 | 目标架构 §8.3、AD-16 | 已解决 |
| 3 | 实体数量统计不一 | **12 领域实体 + PromptTemplate（创作基础设施对象）**；A/B/C 三分；§4.1 唯一权威，旧 8/13 口径作废 | 目标架构 §4.1、AD-09 | 已解决 |
| 4 | 13 阶段 vs 9 门禁 | 唯一阶段定义表（13 × 9 字段）；9 门禁 = 9 人工作业批次（合并 7/8/9 三组）；`export` 前置条件型；6 条硬规则 | 目标架构 §6.1.1~§6.1.4、AD-12 | 已解决 |
| 5 | `assert_p0_fixed()` 不明 | 6 项运行时检查 C1~C6 + 失败码；开发期验收 vs 运行时检查分开；不得跑全量测试、不得改版本号绕过 | 迁移 §1.3.1~§1.3.2 | 已解决 |
| 6 | OQ 编号与统计不一 | 统一 `OQ-01~OQ-09` 注册表 + 旧编号映射；**不替用户决定产品参数** | 基线 §11 | 机制已解决；问题本身仍 OPEN |
| 7 | P9 并行关系不明 | P9 依赖 P3/P4/P6/P8、**不与 P7/P8 并行**；「P9 预备工作」单独定义、不计入出口；旧表述作废 | 路线 §2.1 / §2.3 | 已解决 |
| 8 | Project 共享 vs Story 边界 | 新增 §4.4（Project 5 类 / Story 11 类 / 8 条规则 / 5 条关系调整）；`scope` 两段式 + `shared_ref`；AD-27/AD-28；MVP 第 21 项 | 目标架构 §4.1~§4.4、§7.3 规则 5~6 | 已解决 |
| 9 | 真实 E2E 不完整 | **E1~E10 + 8 条执行规则 + 分阶段最小验收**；Mock/真实分离、无 Key 片段、费用授权、迁移只在副本；规则 8 = **E4 不替代 E1 / E2**（终审补充） | 路线 §3.4 | 已解决 |

> 「已解决」= 文档层面自洽；**不代表代码实现**（见 A17）。

## A14.1 终审意见（ChatGPT 最终审查，CONDITIONAL PASS）的 6 条定点修订

| # | 终审意见 | 处理 | 落地 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | `audio_prod` 一律退回 `full_story` 不合理 | `reject_target` 降为默认值，按问题性质分级；`audio_prod`：音频技术 → 本阶段 / 剧本内容 → `full_story`（经 `DependencyAnalyzer`）/ 镜头表达 → `shot_design`；不允许全部默认退回完整故事 | A7.1 / A7.7、AD-29 | 已解决 |
| 2 | 事务日志晚于暂存副本建立，复制中断无日志可依 | 阶段 0.5 **预检通过即建事务**；`STAGE_COPY` 为事务内第一步（INTENT → 复制 → 校验 → COMPLETED）；新增暂存复制中断恢复判定（6 行）与不完整副本处置（7 条）；验收 +2 类 | A9.3 / A9.3.1 / A9.10、迁移 §3.4.3 / §3.4.6 | 已解决 |
| 3 | `MOVE_TREE` 与「原始 V2 文件必须保留」冲突 | 只移动**经哈希验证的暂存内容**；不移动原始 V2 文件；其他移动需独立授权 + 独立恢复机制，默认不实现 | A9.3.2、迁移 §3.4.2 硬限制 4 条 | 已解决 |
| 4 | E4 是否允许 Mock / 回放不明确 | E4 **允许 Mock 与录制响应回放**；**E4 不替代 E1 / E2** 的真实 API 验证（规则 8） | A12、路线 §3.4.1~§3.4.2 | 已解决 |
| 5 | A16.3 混淆「待决事项」与「已登记 OQ」，统计有误 | A16.3 重组（见新版 A16.3）：已解决项移出、已登记 OQ 单列、删除异常残留行 | A16.3 | 已解决 |
| 6 | 共享资源审核记录的 Project / Story 归属未设计 | 新增 6 条归属规则，`target_kind` 判归属、Project 级记录不带 story_id、Story 级审核只产生变更提案、重审为 Story 级、`SharedResourceStore` 存 Project 级记录、`supersedes` 不跨归属；P2 / P6 实现约束 | A7.8、AD-30、P2/P6 验收行 | 已解决 |

## A14.2 补充核验（v2 送审后 ChatGPT 补充意见）的 2 项定点修订

| # | 补充意见 | 处理 | 落地 | 状态 |
| --- | --- | --- | --- | --- |
| R4 | 迁移事务日志与暂存副本必须物理隔离：目录边界、哈希范围、删除边界、启动扫描形态均未固定 | 固定 `.migration_staging/<tx_id>/transaction.json` + `payload/`；`transaction.json` 不属于被复制内容、不纳入 payload 哈希；`STAGE_COPY` 只复制与校验 `payload/`；删除不完整副本只删 `payload/`、日志保留至 `CLEANED` / `ROLLED_BACK`；启动扫描 4 形态；日志原子写失败禁止开始 `STAGE_COPY`；原始 V2 文件保护不变；验收 +2 类（#22 / #23） | A9.3 / A9.3.1 / A9.3.2 / A9.6 / A9.10、A13、迁移 §0.4 / §3.4.1 / §3.4.2 / §3.4.3 / §3.4.6 / §5.1、AD-23 | 已解决 |
| R5 | AD 编号范围未同步 | A1 文档索引由 AD-01 ~ AD-28 更新为 **AD-01 ~ AD-30**（AD-29 `reject_target` 分级、AD-30 共享资源审核归属）；全文检查无其他文档仍把 AD-28 写成最新决策编号 | A1、决策 §8A | 已解决 |
| R6 | 目标哈希的「排除 `transaction.json`」写法有歧义：未区分「结构上不在范围内」与「按文件名排除」，且 `payload/` 误含 `transaction.json`、`.migration_tmp/` 排除方式、哈希前置检查均未固定 | 目标哈希范围 = `payload/` 内完整项目树（`transaction.json` 在父目录、结构上不在范围内）；`payload/` 内出现 `transaction.json` 判**结构非法**（`RECOVERY_REQUIRED`），不得按文件名排除绕过；`.migration_tmp/` 只按相对路径 `payload/.migration_tmp/` 排除，禁止文件名通配；哈希前先执行 payload 结构合法性检查（5 项）；第 23 类用例扩为 4 个断言点 | A9.3 / A9.10 #9、A13、迁移 §3.4.2 / §5.1、目标架构、AD-23、[冻结基线 §8 暂存目录结构](V3_STAGE0_6_FINAL_BASELINE.md#8-迁移安全原则) | 已解决 |

---

# A15. OQ-01 ~ OQ-09 状态

**唯一登记处：基线 §11。** 全部状态 `OPEN`，均未替用户作答。

| OQ_ID | 问题 | 影响范围 | 阻塞开发 | 需要谁决定 | 最迟决策阶段 |
| --- | --- | --- | --- | --- | --- |
| `OQ-01` | 单 Provider 时 `reviewer` 是否允许同 Provider 不同模型，还是必须阻止 AI 审核 | AI 审核（`full_story` / `final_review`）、配置校验 | 否 | 用户 / 产品 | P7 |
| `OQ-02` | 单任务 / 单项目 / 每日预算的默认数值 | 成本护栏、CostGuard 默认值 | **是（P4）** | 用户（费用承受能力） | **P4 开始前** |
| `OQ-03` | 多 Story 的 UI 呈现（列表 vs 树形） | P8 UI | 否 | 用户 | P8 开始前 |
| `OQ-04` | V3.0 是否必须接入视频生成 Provider | P9 范围、MVP 暂缓第 1 项 | 否 | 用户 | P9 规划前 |
| `OQ-05` | 备份保留时长与次数 | 迁移 §4.4、磁盘占用 | 否 | 用户 | P3 开始前 |
| `OQ-06` | 单 Story 项目 `story_id` 派生规则（项目名 / UUID） | 迁移 §3.3、重命名行为 | **是（P3）** | 用户 / 产品 | **P3 开始前** |
| `OQ-07` | 迁移是否需用户确认，可否首次打开自动迁移 | 迁移 §4.1 | **是（P3）** | 用户 | **P3 开始前** |
| `OQ-08` | 迁移后 V2 旧程序需继续可用多久 | 兼容层保留期、回滚承诺 | 否 | 用户 | P3 开始前 |
| `OQ-09` | `story/index.json` 命名、`versions/` 是否按 story 分子目录 | 存储实现（P1） | 否 | 开发者建议 + 用户确认 | P1 实现前 |

**统计**：9 个；阻塞 3 个（OQ-02 / OQ-06 / OQ-07），非阻塞 6 个。

**旧编号映射**：OQ-1~4 → OQ-01~04；OQ-5 → OQ-06；OQ-6 → OQ-05；OQ-M1 → OQ-05；OQ-M2 → OQ-07；OQ-M3 → OQ-06；OQ-M4 → OQ-08。

---

# A16. 文档间冲突检查结果

## A16.1 本轮（本次生成报告前）实际检查并修正的冲突

| # | 冲突 | 处理 |
| --- | --- | --- |
| 1 | T 场景数量：目标架构 / 基线为 **T1~T11**，但 AD-11、路线 P5、迁移 §2 与 §6.2 仍写 **T1~T10** | 统一为 **T1~T11**（4 处） |
| 2 | 门禁 ⑧ 阶段顺序：目标架构 §6.1.2 为「`audio_prod + video_gen`」，AD-12 与基线 §7 写反 | 统一为 **`audio_prod + video_gen`** |
| 3 | 路线 §5「与 MVP 对应」缺少 MVP 第 21 项 | 补「21 项目级共享人物档案与世界观基础设定 → P2」 |
| 4 | MVP 完成判定与基线 §10 的 E 清单**漏掉 E3（模型对比，P7，真实 API）**，且用「Mock 方式 E4」与路线 E6/E7/E9 标注「否（Mock 即可）」不一致 | 改为 **E3 / E5 / E6 / E7 / E8 / E9 / E10 + Mock 方式 E1 / E2 / E4**；E4 按路线保留「真实或录制回放」 |
| 5 | 路线 P1 验收只写 `ProjectStore`/`VersionStore` 与基线「9 个 Repository」的关系不清 | P1 写明「9 个接口契约中 ProjectStore / VersionStore 先行，其余属 P2/P3」 |
| 6 | 审计与执行摘要「33 个 Python 文件」与实际 **42 个文件（含测试）** 不符 | 改为 42；行数 16,774 未变化 |
| 7 | 执行摘要 K-01 行号「444-466」与迁移方案 / 审计的「455/459/465」不一致 | 统一为 **455-465** |

**终审轮次新增检查并修正的项（A16.1b）**：

| # | 冲突 | 处理 |
| --- | --- | --- |
| 8 | 迁移方案阶段顺序：事务日志原在阶段 3（暂存之后），与终审意见 2 冲突；正文与阶段编号引用（原「阶段 4~6」「阶段 5 不是原子事务」）随之错位 | 事务初始化前移为**阶段 0.5**，`STAGE_COPY` 为阶段 1；原阶段 4~6 前移为 3~5；「阶段 5 不是原子事务」改为「阶段 4」；覆盖内容与步骤总数不变 |
| 9 | `MOVE_TREE` 定义（可移动项目内旧目录）与「原始 V2 文件必须保留」冲突 | 重写为只移动已验证的暂存内容；原始 V2 文件禁止移动；验收新增第 21 类 |
| 10 | `audio_prod.reject_target` 在目标架构、本报告 A7.1 中写法不一（初版本报告仍为 `full_story`） | 统一为「按问题性质分级」，新增 A7.7 专项表 |
| 11 | E4 在路线 / MVP / 本报告 A12 中的口径不一致（「是或录制回放」vs「Mock 方式」） | 统一为「**允许 Mock / 录制响应回放**，规则 8 明确不替代 E1 / E2」；MVP §4 第 6 条同步 |
| 12 | 迁移验收类数 19 → 21 未同步到全部文档（R4 后再次同步为 23 类，见 A16.1c 第 16 项） | 目标架构、迁移方案、决策 AD-23、路线、MVP、执行摘要、冻结基线、本报告统一为 21 类（12 + 7 + 2） |
| 13 | 本报告附「操作边界」写「仅 6 份 Markdown」，与实际修改文件数不符 | 改为按实际文件清单（见附） |

**补充核验 R4 / R5 轮次新增检查并修正的项（A16.1c）**：

| # | 冲突 | 处理 |
| --- | --- | --- |
| 14 | 暂存目录口径 `.migration_staging/<name>-<ts>/` 与「事务日志 / 暂存副本」两类内容的边界未固定，哈希与删除范围含糊 | 迁移方案、AD-23、冻结基线、本报告 A9 统一为 `.migration_staging/<tx_id>/transaction.json` + `payload/`；新增「哈希计算范围」与「启动扫描形态（4 形态）」表 |
| 15 | 删除不完整暂存副本的表述为「删暂存区」，会连事务日志一并删除，恢复与审计依据丢失 | 全部删除路径（阶段 2 / 3 / 5、A9.3.1、A9.10 规则 5）改为**只删 `payload/`、`transaction.json` 保留**；`CLEANED` 收尾按先 `payload/` 后 `transaction.json` |
| 16 | 迁移验收类数 21 未随 R4 同步（新增隔离与哈希边界两类用例） | 迁移方案 §0.4 / §5.1 / §6.2 / §8、MVP §2 / §4、路线 P3、执行摘要、冻结基线 §1 / §8 / §10、本报告 A13 / A14.1 统一为 **23 类（12 + 9 + 2）** |
| 17 | A1 文档索引把决策文档写为 AD-01 ~ AD-28，滞后于实际 AD-01 ~ AD-30 | 更新为 **AD-01 ~ AD-30**；全文检查确认其余 AD-28 提法均为对 AD-28 决策本身的引用（非「最新编号」） |
| 18 | 目标架构、执行摘要未引用暂存目录的物理隔离边界 | 目标架构（一致性与隔离一节）增加隔离指针、执行摘要修订行注明隔离与 23 类验收 |
| 19 | 「目标哈希排除 `transaction.json`」在迁移、AD-23、基线、本报告 A9.3 / A9.10 中写法不一致（排除项 vs 结构上不在范围内） | 统一为「范围 = `payload/` 内完整项目树；`transaction.json` 在父目录、结构上不在范围内；payload 内出现即结构非法；`.migration_tmp/` 仅相对路径排除；哈希前先做结构合法性检查」（迁移 §3.4.2 为唯一权威） |

## A16.2 已确认一致、无冲突的项

实体 12 + 1（5 份文档）；Repository 9 个且与实体数量显式区分口径；13 阶段与 9 门禁映射；7 状态机（仅目标架构 §6.2 定义，其余引用）；9 槽位与 5 能力类型；OQ 编号与计数（基线为唯一登记处，其余为映射表）；P9 依赖与「不并行」表述；迁移失败码（`K01_GUARD_MISSING` / `P0_EVIDENCE_MISSING` / `TRANSACTION_LOG_UNAVAILABLE`）三处一致；关键节 ID（`stage_id`、字段名）一致；P0~P9 编号与依赖表一致；Mermaid 2 个图语法可解析；**终审轮次追加核对**：暂存复制中断恢复表（6 行）在迁移 §3.4.3 与本报告 A9.3.1 一致；不完整暂存副本规则（7 条）在迁移 §3.4.6 与本报告 A9.10 一致；`MOVE_TREE` 硬限制 4 条两处一致；共享资源归属 6 条（目标架构 §6.3.2 / 本报告 A7.8 / AD-30）一致；23 类验收（20 = 暂存复制中断、21 = 不完整暂存副本拒绝、22 = 日志/暂存隔离与扫描形态、23 = 哈希边界）在迁移 §5.1、MVP §2/§4、路线、基线 §8/§10、本报告 A13/A14.1 一致；**补充核验 R4 追加核对**：暂存目录结构（`<tx_id>/transaction.json` + `payload/`）与「只删 `payload/`」口径在迁移 §3.4.1~§3.4.6、AD-23、本报告 A9.3~A9.10 一致；哈希计算范围（目标 = `payload/` 内完整项目树；`transaction.json` 结构上不在范围内而非按文件名排除；payload 内出现即结构非法；`payload/.migration_tmp/` 仅相对路径排除；哈希前先做结构合法性检查）在迁移 §3.4.2「哈希计算范围」、目标架构一致性一节、AD-23、基线 §8、本报告 A9.3 / A9.10 一致；启动扫描 4 形态在迁移 §3.4.3 与本报告 A9.6 一致；AD 编号范围 AD-01 ~ AD-30 在 A1、决策文件头、冻结基线一致。

## A16.3 真正待决事项 vs 已登记 OQ（终审重组）

**统计口径（终审修正）**：本节只列**需审查者判断的待决事项**与**已在冻结基线 §11 登记的 OQ**两类，二者分表，不混计。
本版（终审修订后）**真正待决项 1 项、已登记 OQ 2 项、文档冲突 0 项**；初版误计的 3 行（`audio_prod.reject_target`、E4 版本口径）已随 A7.7 / A12 解决并移出，1 行异常残留（「404 类无」）已删除。

### A16.3.1 真正待决事项（需审查者判断，非冲突）

| 项 | 说明 | 不阻塞的原因 |
| --- | --- | --- |
| `audio_prod` 与 `video_gen` 的 `dependencies` 均为 `image_gen` | 二者架构上无强依赖，未声明 `video_gen` → `audio_prod` 固定顺序；目标架构已说明「生产顺序可按实际工序调整，人工确认不得取消」 | 门禁 ⑧ 已把两者合为一个审核批次，顺序不影响审核要求；具体工序在 P3 迁移设计 / P9 实施时确定 |

### A16.3.2 已登记 OPEN QUESTION（不是文档冲突，答案由用户给出）

| 项 | 对应 OQ | 说明 |
| --- | --- | --- |
| 迁移 §4.4 备份建议值「最近 3 次或 30 天，取久」 | **OQ-05** | 文档中已明确标为**建议值**，未决定；不阻塞开发（最迟 P3 开始前） |
| 目标架构 §3.2 `story/index.json` 命名、`versions/` 是否按 story 分目录 | **OQ-09** | 已登记；不阻塞开发（最迟 P1 实现前） |

### A16.3.3 已解决的初版待定项（移出本节，保留索引）

| 初版待定项 | 结论 | 位置 |
| --- | --- | --- |
| `audio_prod.reject_target = full_story` | 改为按问题性质分级（音频技术 / 剧本内容 / 镜头表达） | A7.1、A7.7、AD-29 |
| E4 是否允许 Mock / 录制回放替代真实 API | 允许；E4 不替代 E1 / E2 | A12、路线 §3.4 |

---

# A17. 明确未实现的功能

**V2.3 代码保持原样**（本阶段未修改任何 `.py` / 测试 / 配置 / 数据）。以下**全部为设计，代码中不存在**：

| 功能 | 现状 | 计划 |
| --- | --- | --- |
| K-01 / K-02 / A-05 / A-03 修复 | **未修复**（缺陷仍在） | P0 |
| Repository 接口族（9 个） | 不存在 | P1~P3 |
| 目录化实体存储、`index.json` | 不存在（单 `project.json`） | P1~P3 |
| Project 级共享资源（`shared/`、`SharedResourceStore`） | 不存在 | P2 |
| 多 Story 支持 | 模型层允许，存储与 UI 未实现 | P1~P2 |
| Scene/Shot 独立实体与镜头版本 | 不存在（内嵌 + 时间轴双轨） | P3 |
| `ShotRegenerator` | 不存在 | P3 |
| 迁移器、逐步骤事务日志、启动恢复 | 不存在 | P3 |
| `assert_p0_fixed()` | 不存在 | P0（探测能力）/ P3（入口） |
| ProviderRegistry、OpenAI GPT | 不存在（仅 DeepSeek 内联调用） | P4 |
| 9 个槽位（尤其 `audio`） | 现有 4 槽位 | P4 |
| UsageLedger / CostGuard | 不存在（`call_log` 基础记录） | P4 |
| PromptStore | 不存在（内联 Prompt） | P5 |
| ContextEngine（三层） | 不存在 | P5 |
| WorkflowEngine、门禁、状态机 | 不存在（AI 评分，无门禁） | P6 |
| ReviewRecord 持久化 / DependencyAnalyzer | 不存在 | P6 |
| AI 独立审核 / 多模型比较 | 不存在 | P7 |
| GenrePack / HorrorPack 包装 | 不存在（`horror_rules` 直接规则） | P7 |
| 审核中心 / 人物中心 / 世界观中心 / 镜头管理 / 模型对比面板 | 不存在 | P8 |
| 图片 / 视频 / 配音 / 音效 / 后期 / 导出生产链路 | 图片与配音有部分媒体能力，未接入 V3 | P9 |
| GUI 自动化冒烟（GUI 约 4,200 行零自动化测试） | 不存在 | P8 起 |

**V2 真实存在的能力**：五阶段流水线、JSON 解析链、Pacing、本地质量检查、FFmpeg 渲染、媒体调用、批量失败隔离、Key 安全、原子写、309 个测试（逻辑层覆盖较好，GUI 无自动化测试）。

---

# B. P0 启动条件检查表

> 结论先行：**当前仍不满足启动 P0 的条件。** Stage 0.6 初版审查结论为 CONDITIONAL PASS，6 条定点修订**已在文档中完成**（A14.1），补充核验 R4 / R5 亦已完成（A14.2），但**尚待 ChatGPT 对终审修订版确认**；P0 任务书（B9）与 Git 提交策略（B14）仍未完成。其余工程条件已就绪。
>
> 本版（终审修订版）对 B1 / B2 / B9 / B14 的状态刷新见下表；B3~B8、B10~B13、B15 未变化。

| # | 条件 | 判定依据 | 当前状态 | 证据 / 说明 |
| --- | --- | --- | --- | --- |
| B1 | **Stage 0.6 交付物经 ChatGPT 审查通过** | 路线 §4「未经 ChatGPT 审查，不得进入下一阶段」 | ⏳ **终审修订 + R4 / R5 补充完成，待确认** | 初版审查结论 CONDITIONAL PASS；6 条意见已全部落入文档（A14.1）；补充核验 R4（日志/暂存物理隔离）与 R5（AD-01 ~ AD-30）已完成（A14.2）；需 ChatGPT 确认后方可视为通过 |
| B2 | 冻结基线生效 | 基线 §13.2 变更流程 | ⏳ 待 B1 确认后生效 | 基线 §13 明示「本基线在 ChatGPT 确认终审修订后生效」 |
| B3 | 仓库身份 / 分支 / 提交可确认 | 任务书 §二 | ✅ | 分支 `main`；HEAD `ac8e333741e9caedeada234a585be153e5a44a0d` |
| B4 | 工作区无未确认代码修改 | 同上 | ✅ | `git status --short` 仅 `?? docs/`；无 `.py` / 测试 / 配置 / 数据改动 |
| B5 | 无悬挂暂存 | — | ✅ | `git stash list` 为空 |
| B6 | 基线测试状态已知 | 审计 §0 | ✅ | Stage 0.5 实测 309 通过 / 0 失败；Stage 0.6 未改代码、未重跑 |
| B7 | K-01 缺陷确认存在且范围明确 | 审计 §9.1 / 迁移 §1.2 | ✅ | `project_manager.py:455/459/465` 三处 pop + `225-226` 写盘 |
| B8 | P0 范围已冻结 | 路线 P0 验收 / MVP | ✅ | K-01 / K-02 / A-05 只读检测 / A-03 来源标记 + 回归用例 |
| B9 | P0 独立任务书已编写并经审查 | 路线 §6 治理第 1、2、12 条 | ❌ **未编写** | 任务书应在 P0 启动前单独产出 |
| B10 | P0 验收方式明确 | 迁移 §1.3.2 | ✅ | 全量测试套件 + 新增回归 + `p0_verification.json`（含代码指纹） |
| B11 | P0 不依赖任何 `OPEN` 的 OQ | 基线 §11 | ✅ | 无 OQ 的最迟决策阶段早于 P4；P0 不受阻 |
| B12 | 真实 API 调用与费用 | 路线 §3.4.2 规则 4 | ✅（P0 无需） | P0 为本地补丁，不调用真实 API |
| B13 | 用户数据保护承诺可执行 | 迁移 §1.1 | ✅ | 修复目标是「失败不写盘、保留原文」；回归用例覆盖 |
| B14 | Git 操作授权 | 治理第 13 条「重要功能 Git 独立提交」 | ⏳ **待用户明确** | 本阶段禁止擅自提交；P0 提交策略需用户确认 |
| B15 | 环境可运行测试 | 审计 | ✅ | Python 3.12.10；`unittest discover` 可用 |

**启动 P0 前必须完成**：B1（ChatGPT 确认终审修订版）→ B9（P0 任务书）→ B14（Git 提交策略确认）。B2 随 B1 生效。

**启动 P0 后第一条**：修复 K-01，使 `_normalize_story` 失败路径不再 `data.pop("story")`，补「story 结构异常时打开项目，story 原样保留」回归用例；**任何 V2→V3 迁移在此之前禁止执行**。

---

## 附：本次操作边界

| 项 | 状态 |
| --- | --- |
| 修改 `.py` / 测试 / `project.json` / 用户数据 | 未修改 |
| 执行迁移 / 修改 API Key / 安装依赖 / 修改配置 | 未执行 |
| Git commit / reset / clean / checkout | 未执行 |
| 操作 AI Dev Hub | 未执行 |
| 启动 P0 | 未启动 |
| 本次修改范围 | （哈希边界最终修订批次：迁移方案、目标架构、AD、基线、本报告 A9/A13/A14/A16）Stage 0.6 初版：`docs/architecture/v3_stage0/` 下 6 份 Markdown 的文档冲突修正（A16.1 的 7 处）及本报告新增；终审修订版：9 份架构 Markdown + 本报告（A16.1b 的 8~13 项与终审意见 1~6）；**补充核验 R4 / R5：仅修改 `docs/architecture/v3_stage0/` 下 Markdown（迁移方案、目标架构、执行摘要、AD、MVP、路线、冻结基线、本报告；A16.1c 的 14~18 项与 A14.2）**。均未触及 `.py` / 测试 / 配置 / 用户数据 |
| API Key | 未读取、未打印、未写入任何文件 |
