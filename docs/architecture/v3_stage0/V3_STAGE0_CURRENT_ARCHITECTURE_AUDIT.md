# V3 STAGE 0 — 现有架构审计（V2.3 → V3 升级评估）

日期：2026-11-05
版本：**Stage 0.6 复核版**（Stage 0 初版结论保留，仅补充 §0 复核记录与实体口径同步；未推翻任何结论）
审查对象：AI Horror Studio V2.2/V2.3（`D:/AImv/AI_Horror_Studio_V2`，分支 `main`，HEAD `ac8e333`）
方法：只读代码审查 + 实跑测试（Python 3.12.10，`python -X utf8 -m unittest discover -s tests`）。所有结论注明文件位置。
本阶段未修改任何代码。

---

## 0. Stage 0.5 / 0.6 复核记录

Stage 0.5 与 Stage 0.6 开工时对 Stage 0 的关键结论做了定点复核（只读），复核结果：

### 0.1 Stage 0.5 复核（保留）

| 复核项 | 复核命令 / 位置 | 结果 |
| --- | --- | --- |
| K-01 仍存在 | [project_manager.py:455/459/465](../../../modules/project_manager.py#L455-L465) `data.pop("story", None)` | **确认存在**，三处丢弃路径 + 第 523 行 `clear_story`（后者是显式清空，非缺陷） |
| `open_project` 仍立即写盘 | [project_manager.py:225-226](../../../modules/project_manager.py#L225-L226) | **确认存在** |
| A-05 index 对齐 | [project_manager.py:704](../../../modules/project_manager.py#L704) `by_index.get(...)` | **确认存在** |
| A-06 反向依赖 | [image_engine.py:19](../../../modules/image_engine.py#L19) `from modules import ... story_engine` | **确认存在** |
| 无 SQLite / OpenAI | `grep -rIn "sqlite\|openai" modules` | 仅 `test_ai_media.py` 一个测试名提及 openai 风格响应，无实现 |
| 测试基线 | `python -X utf8 -m unittest discover -s tests` | **309 通过 / 0 失败（30.5s）**，与 Stage 0 记录一致 |
| 模块规模 | `wc -l modules/*.py` | 27 个模块，与 §10 模块判定表一致 |

结论：**Stage 0 审计结论全部仍然有效**，无需修订 §1~§12 正文。

### 0.2 Stage 0.6 复核记录

| 复核项 | 命令 / 位置 | 结果 |
| --- | --- | --- |
| 仓库身份 | `git branch --show-current` | `main` |
| 基线 HEAD | `git rev-parse HEAD` | `ac8e333741e9caedeada234a585be153e5a44a0d`（与已知基线一致） |
| 工作区状态 | `git status --short` | 仅 `?? docs/`（架构文档目录，未跟踪）；**无任何 `.py` / 测试 / 配置 / 数据文件被修改** |
| 暂存区 | `git stash list` | 空 |
| 代码改动 | 本阶段操作 | **无**（Stage 0.6 只修改 Markdown 文档） |
| 测试基线 | `python -X utf8 -m unittest discover -s tests` | 本阶段**未重跑**（未改动任何代码，基线以 Stage 0.5 实测 309 / 0 为准） |

**结论**：Stage 0.6 开工条件满足；项目身份、分支、提交状态均可确认；无未确认代码修改。

### 0.3 Stage 0.6 对 §12 第 5 条的实体口径同步

Stage 0 初版 §12 第 5 条使用「8 个数据模型 / 5 个全新」的统计。Stage 0.6 按审查问题 3 统一为「12 个领域实体 + 1 个创作基础设施对象，按三类来源统计」，§12 第 5 条已同步更新。实体口径的唯一权威来源为 [目标架构 §4.1](V3_STAGE0_TARGET_ARCHITECTURE.md#41-实体清单12-个领域实体--1-个创作基础设施对象)。

---

## 1. 项目现状

| 项 | 值 | 依据 |
| --- | --- | --- |
| 语言/框架 | Python 3.11+ / tkinter；运行时零第三方依赖（Pillow 可选） | 各模块 import 实测 |
| 代码规模 | 42 个 Python 文件（含 11 个测试文件与 `gui_smoke.py`），约 16,774 行（Stage 0 实测；Stage 0.6 复核时文件计数修正为 42，行数未变化） | `wc -l` / 文件计数实测 |
| 对外版本 | V2.2（README 标题仍写 V2.1） | [README.md](../../../README.md) |
| schema | `project.json` schema_version=2；story schema=2 | [project_manager.py:58-59](../../../modules/project_manager.py#L58-L59)、[story_schema.py:32](../../../modules/story_schema.py#L32) |
| 存储 | **无数据库**：单文件 `project.json`（原子写）+ `versions/` 快照 + 素材目录 | 见 §3 |
| 入口 | `main.py` → `MainWindow` | [main.py](../../../main.py) |
| AI | DeepSeek（文本）+ 硅基流动（出图/配音）+ FFmpeg（渲染） | `model_config.py`、`image_engine.py`、`voice_engine.py` |
| 测试 | **309 通过 / 0 失败**（实跑 32.8s）；`gui_smoke.py` 为手工冒烟，不在 discover 范围 | 本轮实跑 |
| Git | 分支 `main`，HEAD `ac8e333`，工作区除 `docs/` 外干净 | `git status` |

**测试覆盖范围（不只看数量）**：309 个用例集中在 9 个领域测试文件：

| 测试文件 | 用例 | 覆盖对象 |
| --- | --- | --- |
| test_story_engine.py | 58 | 解析链、截断恢复、五阶段函数 |
| test_ai_media.py | 46 | image_engine / voice_engine / sf_http |
| test_project_manager.py | 46 | 项目 CRUD、迁移、版本、素材绑定 |
| test_story_schema.py | 39 | 数据类归一/校验/升级 |
| test_pacing.py | 32 | 时长规划与不变量 |
| test_pipeline.py | 25 | 渲染命令构造 |
| test_horror_rules.py | 21 | 题材规则库 |
| test_render_engine.py | 16 | FFmpeg 命令 |
| test_batch.py | 14 | 批量流水线 |
| test_story_panel_logic.py | 12 | 面板纯逻辑（评分文案/重排） |

**覆盖缺口（V3 大改前必须知道）**：`main_window`（1825 行）、`story_panel`（837 行）、`batch_panel`（572 行）、`timeline`（506 行）、`ai_studio`（378 行）、`ai_settings`（291 行）、`thumbnails`（262 行）、`preview`（203 行）、`inspector`（184 行）**没有自动化测试**。核心逻辑层覆盖较好，GUI 层完全依赖手工冒烟。

---

## 2. 系统分层与模块依赖（实测）

分层：

```
表现层   tkinter 面板：story_panel / ai_studio / batch_panel / timeline /
         preview / inspector / ai_settings / theme
调度层   main_window：页签、项目生命周期、后台线程 + msg_queue 单一回传通道
编排层   story_engine（五阶段）、batch（批量流水线）
领域层   story_schema（结构）、pacing（时长）、story_quality（质检）、horror_rules（题材）
数据层   project_manager（project.json / 版本 / 素材绑定）
媒体层   image_engine / voice_engine / sf_http / media_tools /
         render_engine / ffmpeg_locator
```

实测 import 依赖（grep 全部模块）：

```
main_window ─→ 全部面板 + project_manager + story_engine + batch +
               render_engine + image_engine + voice_engine + media_tools
story_engine ─→ story_schema + pacing + story_quality + horror_rules
project_manager ─→ story_schema（函数内懒 import）
batch ─→ project_manager + story_engine(to_project_shots)     （不依赖 tkinter）
image_engine ─→ story_engine + sf_http                        ← 反向依赖 A-06
preview ─→ project_manager + thumbnails
sf_http ─→ ai_config + sf_config
ai_settings / ai_studio ─→ ai_config + sf_config + story_engine(类型) + voice_engine
```

关键事实：面板不 import `main_window`，通过构造参数接收回调（`StoryPanel` 9 个回调），界面/业务分离良好；`batch.py` 可无 GUI 测试。

---

## 3. 数据存储架构

目录布局（[DATABASE_SCHEMA.md](../../project_knowledge/DATABASE_SCHEMA.md) 与代码一致）：

```
<项目目录>/
├─ project.json           唯一状态源（schema_version=2），原子写 tmp.replace
├─ versions/<id>.json     story 版本快照
├─ images/ audio/ subtitles/ output/ temp/
```

用户级配置（不在项目内）：`~/.ai_horror_studio/ai.json`（DeepSeek Key）、`siliconflow.json`、`models.json`、`logs/calls-YYYYMMDD.jsonl`。

`project.json` 顶层：[project_manager.py:57-110](../../../modules/project_manager.py#L57-L110)

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 2 |
| `name` / `created_at` | 项目元信息 |
| `settings` | 画幅/帧率/grain/vignette/grade/loudnorm/bed_drone/pacing |
| `shots[]` | **时间轴镜头**：id（主键）/image/ai_image/scene/narration/duration/start/motion/transition/voiced/voice/voice_ms/**shot_id**/scene_id/character_ids/**shot_revision**/**content_hash**/story_index/**stale** |
| `story` | 故事文档（见 §4） |
| `narration` / `music` / `subtitle` | 素材路径 |
| `total_duration` | 计算字段 |

**两套镜头标识**：`shots[].id`（时间轴主键）与 `shots[].shot_id`（故事分镜 id）并存，后者弱关联 story。

---

## 4. 故事数据结构（schema 2）

[story_schema.py](../../../modules/story_schema.py) 手写 dataclass：宽容 `from_dict` + 严格 `validate`。

```
Story
├─ concepts[]      StoryConcept：concept_id/title/logline/core_conflict/hook/
│                  reversal_type/ending_type/horror_device/duration_tier
├─ plan            StoryPlan：theme/background/core_conflict/motivation/stakes/
│                  conflicts[]/foreshadows[]/reversal/reversal_type/hook/ending/
│                  ending_type/acts[5段]/tone/ruleset
├─ characters[]    CharacterProfile：character_id/name/role/look/motivation/
│                  secret/voice/scene_ids
├─ scenes[]        SceneProfile：scene_id/name/look/lighting/props
├─ script[]        ScriptSegment：segment_id/scene_id/character_ids/dialogue[]/text
├─ shots[]         StoryboardShot：shot_id/scene_id/script_segment_id/beat/
│                  image_prompt/narration/motion/duration/voiced/revision
├─ pacing / quality / versions[] / active_version / version_strategy / stale
```

行号依据：[story_schema.py:215-360](../../../modules/story_schema.py#L215-L360)（概念/人物/场景/策划）、[418](../../../modules/story_schema.py#L418)（StoryboardShot）。

---

## 5. 故事创作模块审计

### 5.1 五阶段流水线（可保留，V3 直接基础）

[story_engine.py:1011](../../../modules/story_engine.py#L1011) `pipeline()`：

```
创意候选(3) → 策划(plan + 人物 + 场景) → 剧本 → 分镜 → 时长 → 出图提示词 → 质量审核
```

每阶段独立可调：`generate_concepts` / `plan_story` / `write_script` / `storyboard` / `plan_pacing` / `image_prompts` / `review`。

**槽位模型**（[model_config.py](../../../modules/model_config.py)）：planner / writer / concept / fast 四槽位，模型名从槽位解析（`model_for(slot)`），`~/.ai_horror_studio/models.json` 可覆盖。**模型名没有硬编码进业务流程**——这一点满足 V3「不得将具体模型绑定在业务逻辑中」的基础要求，扩展多 Provider 时只需扩槽位与 Provider 解析。

### 5.2 Prompt 管理

内联在 `story_engine.py`：`build_prompt`（[story_engine.py:252](../../../modules/story_engine.py#L252)）+ 各阶段 system/user 模板 + `_QUALITY_EXAMPLE`。**无版本管理、无外置、无多 Provider 差异化**。

### 5.3 AI 调用与解析（可保留）

- 纯标准库 HTTP：`_http_transport`（[story_engine.py:291](../../../modules/story_engine.py#L291)），传输函数可注入 → 测试不联网。
- JSON 稳健解析链（[story_engine.py:1118](../../../modules/story_engine.py#L1118) 起）：`extract_content → _strip_fences → parse_json_object → _find_json_object`，失败走 `_repair_json` 让模型修一次。
- 截断恢复：`finish_reason=length` → `ContentTruncated`；分镜用 `_salvage_truncated_list` 截到最后完整镜头。
- 推理 token 预算：`model_config.DEFAULT_PARAMS` + `SHOT_BUDGET` + 出图提示词按镜数抬底封顶 32768。
- 调用日志：`call_log.py` 写 `calls-YYYYMMDD.jsonl`（含 usage/耗时，不含 Key）。

### 5.4 审核能力（V3 的「AI 独立审核」需求）

[story_engine.py:953](../../../modules/story_engine.py#L953) `review()`：本地确定性规则（`story_quality.local_review`，6 条硬否决：weak_hook / abrupt_end / missing_motivation / unknown_reference / duration_mismatch / unforeshadowed_reversal）+ 模型 rubric 评分（8 项满分 100）合并。

**缺失**：审核结果不持久化为审核记录；无审核人/时间/通过/退回字段；审核不阻塞下一阶段（无门禁）。V3 的 ReviewRecord 实体、审核状态机、人工审核、多模型交叉审核全部为新建。

### 5.5 版本管理

- 正式版本上限 10（[project_manager.py:61](../../../modules/project_manager.py#L61)），裁剪前检查 `active_version`/`base_version`/`stale.versions` 引用（`_version_referenced`）。
- 快照 = story deepcopy 去掉 `versions`/`active_version`，写 `versions/<id>.json` 原子写（[project_manager.py:541](../../../modules/project_manager.py#L541)）。
- 恢复（[project_manager.py:652](../../../modules/project_manager.py#L652)）：先自动备份当前 → 恢复 → 再存「恢复自」版本 → `_sync_timeline_to_story` 对齐时间轴。
- **快照只含 story，不含时间轴 shots / 素材路径映射。**

---

## 6. Scene / Shot 实体化评估（V3 核心差距）

现状是**双轨制**：

| 侧 | 位置 | 主键 | 生命周期 |
| --- | --- | --- | --- |
| story 分镜 | `story.shots[]` | `shot_id` | 随 story 版本快照 |
| 时间轴镜头 | `project.shots[]` | `id` | 独立编辑，不被版本快照覆盖 |

关联：`shots[].shot_id` + `shots[].story_index`（序号）+ `scene_id`/`character_ids` 引用；导入时 `to_project_shots`（[story_engine.py:1623](../../../modules/story_engine.py#L1623)）转换。

| V3 场景/分镜需求 | 现状 |
| --- | --- |
| Scene 独立数据实体 | 否——`scenes[]` 内嵌 story |
| Shot 独立数据实体 | 否——双轨内嵌 |
| 人物与镜头关联 | 有（`character_ids`），但仅是引用字符串 |
| 单镜头重新生成 | **无**（只能整条重跑流水线或手工换图） |
| 镜头版本管理 | 时间轴侧有（`shot_revision`/`content_hash`/`stale`） |
| 审核状态 | **无** |
| 上下游依赖关系 | 弱（`story_index` 序号对齐） |

判定：Scene/Shot **不是独立实体**。V3 要求的实体化、单镜重生成、镜头级审核与版本，需要在数据模型层重构。

---

## 7. Story Context Engine 评估（V3 §四）

现状**无独立 Context Engine**，各阶段直接内联相关片段：

- `storyboard`：内联 plan / characters / scenes / script（[story_engine.py:789](../../../modules/story_engine.py#L789)）
- `_model_review`：内联 plan / characters / scenes + slim shots（[story_engine.py:966](../../../modules/story_engine.py#L966)）
- 出图一致性：`build_consistency_hint` 只带本镜引用的角色/场景卡（[image_engine.py:95](../../../modules/image_engine.py#L95)）

| V3 Context Engine 要求 | 现状 | 可复用点 |
| --- | --- | --- |
| 上下文组装 | 内联拼接 | `build_consistency_hint` 的「按引用取卡」雏形 |
| Token 控制 | 有预算机制 | `DEFAULT_PARAMS` / `SHOT_BUDGET` / 提示词预算封顶可直接泛化 |
| 信息冲突处理 | **无**（单次生成、无多来源） | 需新设计（已审版本 > 草稿 > 退回的优先级） |
| 已审版本注入 | **无** | 依赖 V3 审核记录 |

---

## 8. 多模型管理评估（V3 §五）

| V3 需求 | 现状 | 判定 |
| --- | --- | --- |
| DeepSeek Provider | 生产可用 | 保留 |
| GPT Provider | **不存在**（全仓库无 openai/gpt 引用） | 新建 |
| 模型切换 | 槽位制 `model_for(slot)` | 保留并扩展 Provider 维度 |
| 多模型并行生成 | 无（串行单槽位） | 新建 |
| 独立模型审核 | 无独立 reviewer 槽位 | 新建（可扩槽位） |
| Prompt 版本管理 | 无（内联字符串） | 新建 |
| Token/成本统计 | `call_log.py` 有 usage 流水，无成本换算/聚合 | 扩展 |
| 模型质量对比实验 | `tools/quality_baseline.py`、`quality_compare.py`（手工 CLI） | 工具保留，产品化新建 |

**参考**：V3 的 Provider 抽象为**自研接口定义**（见 [目标架构 §8](V3_STAGE0_TARGET_ARCHITECTURE.md#8-ai-provider-与-prompt-架构)），不读取、不引用、不复制任何外部项目的实现代码。V2 是函数式内联 AI 调用，与任何第三方项目的耦合方式都不同，无法直接照搬。

---

## 9. 数据安全审计（重点检查项）

### 9.1 K-01 — story 校验失败被静默丢弃（**重大数据安全风险，单列**）

[project_manager.py:444-466](../../../modules/project_manager.py#L444-L466)：

```python
story = data.get("story")
if story is None:
    return False
if not isinstance(story, dict):
    data.pop("story", None)          # 丢弃
    return True
...
try:
    upgraded, changed = ss.upgrade_story(story)
except (ss.SchemaError, TypeError, ValueError):
    data.pop("story", None)          # 丢弃
    return True
```

而 [project_manager.py:225-226](../../../modules/project_manager.py#L225-L226) `open_project()` 在 `changed` 时**立即写盘**：

```python
if changed or due:
    self.save(project, migrated)
```

**后果**：用户打开一个旧版项目，若 `upgrade_story` 因任何原因抛异常，整个 story 从磁盘永久消失——无备份、无提示、无日志。这是 V3 升级前必须修复的 P0。

现有 309 个测试没有覆盖「升级失败后打开项目」「story 结构异常」的路径。

### 9.2 K-02 — 导入故事四步写盘非原子（中）

[main_window.py:1151](../../../modules/main_window.py#L1151) `import_story`：`set_story → replace_all_shots → 写 SRT → load+save`，四次独立写盘。中途失败留下混合状态（新 story + 旧字幕、新 shots + 旧素材映射）。

### 9.3 A-05 — index 对齐导致素材错位（中）

[project_manager.py:689](../../../modules/project_manager.py#L689) `_sync_timeline_to_story` 按 `story_index`/位置对齐。story 侧删镜后恢复版本，素材错配到不同镜头。

### 9.4 A-03 — 版本额度被导入/批量稀释（中）

[project_manager.py:488](../../../modules/project_manager.py#L488) `set_story` 每次都存正式版本；导入与批量每项目都会调用 → 10 版正式额度快速耗尽。

### 9.5 良好的数据安全设计（应保留）

- 版本恢复前自动备份当前状态（可回滚）。
- `create_project` 拒绝非空目录；`save` 用 `tmp.replace` 原子写。
- Key 只存用户目录，日志与错误信息打码。
- `_sync_shot_versions` 的内容指纹 + `keep_ids` 机制（有素材的镜头内容变化保留 revision）。
- `migrate` 纯函数无副作用（快照通过 `_version_snapshot_due` 标记，由 `open_project` 执行）。

---

## 10. 模块判定总表

| 模块 | 行数 | 判定 | 理由 |
| --- | --- | --- | --- |
| `story_schema.py` | 1048 | **保留 + 扩展** | 结构良好、无损升级；新增 Relationship/WorldSetting/PlotEvent/KnowledgeState/ReviewRecord |
| `story_engine.py` — 解析链/截断恢复/预算 | ~350 | 保留 | 与 Provider 无关的通用能力 |
| `story_engine.py` — 五阶段流程 | ~600 | 保留 | 与 V3 创作流程兼容 |
| `story_engine.py` — Prompt 内联 | — | **重构** | 抽为可版本化对象 + Context Engine |
| `pacing.py` | 487 | 保留 | Shot 时长仍需要 |
| `story_quality.py` | 185 | 保留 + 泛化 | 恐怖题材硬否决 → 可配置质量规则 |
| `horror_rules.py` | 236 | **保留为题材插件之一** | 六类恐怖规则成为 V3 第一种题材包 |
| `project_manager.py` | 1254 | **重构拆分** | 写入路径原子化；shots 实体化；版本机制保留 |
| `main_window.py` | 1825 | **重构** | 两套线程模型统一（A-01） |
| `batch.py` | 328 | 保留 | 失败隔离好、无 tkinter 依赖 |
| `image_engine.py` / `voice_engine.py` / `sf_http.py` | ~510 | 保留 + 解耦 | 解掉 `image_engine → story_engine` 反向依赖 |
| `render_engine.py` | 374 | 保留 | FFmpeg 命令构造 V3 仍需 |
| `model_config.py` | 118 | **保留 + 扩展为多 Provider 槽位** | 槽位制是正确的解耦方向 |
| `call_log.py` | 4（调用）/ 56（实现） | 保留 + 聚合 | 加成本换算与聚合 |
| `ai_config.py` / `sf_config.py` | ~200 | 保留 | Key 安全设计好 |
| GUI 面板（story_panel/ai_studio/batch_panel/timeline/preview/inspector/ai_settings/thumbnails） | ~4200 | 保留，适配 | 只做展示与回调，业务改造不侵入 |
| `tools/quality_baseline.py` / `quality_compare.py` | ~300 | 保留为 CLI | V3 质量对比实验雏形 |
| `theme.py` / `ffmpeg_locator.py` / `media_tools.py` | ~480 | 保留 | 基础设施 |

---

## 11. 已知技术风险

| # | 风险 | 级别 | 依据 |
| --- | --- | --- | --- |
| R1 | **K-01 story 静默丢弃**：升级失败即永久丢数据（开项目即写盘） | **高** | §9.1 |
| R2 | **Shot 双轨制**：story 内嵌 + 时间轴独立，弱关联 | 高 | §6 |
| R3 | **无审核实体与门禁**：V3 工作流全部新建 | 高 | §5.4 |
| R4 | **无多 Provider 抽象**：GPT 不存在，Prompt 内联 | 高 | §8 |
| R5 | A-01 两套线程模型并存（`root.update()` 泵 vs 队列轮询） | 中 | [main_window.py:1048](../../../modules/main_window.py#L1048) |
| R6 | K-02 导入非原子写盘 | 中 | §9.2 |
| R7 | A-05 index 对齐素材错位 | 中 | §9.3 |
| R8 | A-03 版本额度被导入稀释 | 中 | §9.4 |
| R9 | **GUI 层零自动化测试**：V3 大改面板无回归防线 | 中 | §1 |
| R10 | 单文件 `project.json` 在 V3 实体量级下的性能与并发写风险 | 中 | §3 |
| R11 | Prompt 内联无版本化 → 多 Provider 后行为漂移 | 中 | §5.2 |
| R12 | `image_engine → story_engine` 反向依赖（A-06） | 低 | §2 |

---

## 12. Stage 0 审计结论

1. **可保留的主体**：五阶段引擎、schema 体系、pacing、质量审核、批量流水线、媒体渲染、槽位模型——逻辑层约 60% 可直接继承。
2. **三大改造点**：(a) Scene/Shot 实体化；(b) 多 Provider 抽象；(c) 审核工作流（门禁 + 记录）。
3. **三条红线（V3 开工前必修）**：K-01（升级失败丢 story）、K-02（非原子导入）、A-05（index 对齐，实体化后可自然消解）。
4. **测试建议**：V3 开发前补齐「升级失败项目打开」用例与 GUI 冒烟自动化。
5. **新实体缺口**：V3 的 12 个领域实体中，6 个为 V3 全新引入（CharacterRelationship / WorldSetting / PlotEvent / CharacterKnowledgeState / VisualAsset / ReviewRecord），4 个可由 V2 迁移（Project / Story / StoryVersion / Character），2 个由 V2 嵌套结构实体化（Scene / Shot）；Scene/Shot 由内嵌改为独立实体是最大结构改造。PromptTemplate 为创作基础设施对象，不计入 12 个领域实体。**实体清单与来源统计以 [目标架构 §4.1](V3_STAGE0_TARGET_ARCHITECTURE.md#41-实体清单12-个领域实体--1-个创作基础设施对象) 为唯一权威来源**（本审计文件的第 5 条为审计时点的观察，随 Stage 0.6 统一口径已同步更新）。
6. **不建议推翻任何现有模块**：horror 规则、pacing、渲染、媒体调用、批量、Key 安全设计均经过真实 API 与 309 测试验证，应保留并按需扩展。
