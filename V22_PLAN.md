# AI Horror Studio V2.2 实施计划（已确认，待实施）

> 状态：**方案已由用户确认（2026-11-04），代码尚未开始修改。**
> 新对话从这里继续：按「实施顺序」逐步执行，每步跑测试。

## 已确认的决策

| 议题 | 结论 |
|---|---|
| Pydantic | 不引入依赖。新增 `modules/story_schema.py`（dataclass + validate + 宽容 from_dict），对外等价 |
| 时长 | 放宽到 1.5–6.0 秒，由动态时长规划器按目标总时长（3–5 分钟）、节奏、朗读时长分配 |
| 镜数 | 30–50，策划阶段由目标时长与平均镜长推出 |
| 真实验证 | 已授权：完整五阶段 + 出图 3 张，预算不到一毛钱 |
| 执行方式 | 用户要求「所有 AI 生成任务支持失败重试」「重要数据修改前保留版本」 |

## 本机实测事实（不要凭记忆改）

- DeepSeek 账号只有 `deepseek-flash`、`deepseek-v4-pro`，**两者都是推理模型**，先输出 reasoning tokens。flash ≈1.7s / v4-pro ≈6.7s。
- 模型分配：flash 接出图提示词与辅助小任务，v4-pro 接策划/剧本/分镜/审核。模型名全部走配置，不写死。
- `response_format=json_object` 要求提示词中出现 `json` 字样，否则 HTTP 400。
- 推理 token 计入 `max_tokens`；预算不足 → 空内容 + `finish_reason=length`，应视为可重试错误。

## 七项补充要求（用户原文要点）

1. **创意候选**：输入关键词先出 3 个不同核心冲突/反转方式的创意，用户选择后进入完整创作。
2. **动态时长规划器**：按目标时长、剧情节奏、旁白朗读时长、镜头数量分配，不平均；最终时间轴符合目标。
3. **关联字段**：`script_segment_id`、`scene_id`、`shot_id`、`character_ids`；一个剧本段落可对应多个镜头。
4. **恐怖题材规则库**：中式民俗 / 心理恐怖 / 都市怪谈 / 密室恐怖 / 反转悬疑 / 无限循环，各用不同规则。
5. **质量硬性否决**：人物动机缺失、剧情无结局、场景引用错误、时间严重不符、反转缺伏笔 → 高分也不通过。
6. **阶段版本管理 + 依赖失效**：重生成上游把下游标为过期；保留原始图片、配音、分镜版本，支持恢复。
7. **漫画画风**：默认彩色 2D 暗黑恐怖漫画；保留中式 / 日式 / 黑白 / 美式预设；不再默认写实电影剧照。

## 五阶段流水线

| 阶段 | 输入 → 输出 | 模型 |
|---|---|---|
| 0 创意候选 | 题材 + ruleset → `[StoryConcept × 3]`（反转类型互不重复） | v4-pro |
| 1 故事策划 | 选定创意 → `StoryPlan` + `CharacterProfile[]` + `SceneProfile[]` | v4-pro |
| 2 剧本撰写 | 策划 → `ScriptSegment[]`（含对白、情绪、scene_id、character_ids） | v4-pro |
| 3 导演拆镜 | 剧本 → `StoryboardShot[]`（shot_id / script_segment_id / scene_id / character_ids / image_prompt / motion / duration） | v4-pro |
| 4 出图提示词 | 分镜 → 精简 prompt（配合画风预设） | flash |
| 5 质量审核 | 全量 → `QualityReport`（本地确定性检查 + 模型 rubric 打分 + 硬性否决 + 问题带镜号定位） | 本地 + v4-pro |

评分 100 分：剧情完整性 20 / 逻辑合理性 20 / 悬念设计 15 / 恐怖氛围 15 / 人物塑造 10 / 剧情反转 10 / 旁白与对白 5 / 分镜表现力 5。
等级：≥85 优秀、75–84 合格、60–74 需优化、<60 重新生成策划。硬性否决与等级独立，触发即不通过。

## 动态时长规划（`modules/pacing.py`）

```
每镜权重 = 节奏档（钩子1.2 / 建置1.0 / 升级0.9 / 反转0.7 / 余味1.4）
         × 朗读时长（约 4.2 字/秒 + 停顿）
         × 留白镜系数（voiced=false 1.1）
每镜时长 = clamp(归一化权重 × 目标总时长, 1.5, 6.0)
误差修正：剩余秒数补给最长的几镜，总时长误差 ≤ 1 秒
```

### 最终算法（2026-11-04 批准版：带上下限约束的加权分配）

1. **可行区间检查**：`n×1.5 ≤ 目标 ≤ n×6.0`。不满足时先**自动调整镜头数**
   `n* = round(目标 / 期望平均镜长)` 并夹到 `ceil(目标/6) ~ floor(目标/1.5)`；
   仍无法满足（目标 ≤0 或极端值）→ 抛 `PacingError`。
2. **加权初分配**：按上面的权重归一化后乘目标，再钳到 `[1.5, 6.0]`。
3. **约束再分配**：把超出上下限的镜头固定到边界，剩余时长按剩余镜头权重
   重新归一分配；迭代直到无镜头越界（标准 water-filling，必然收敛）。
4. **误差修正**：剩余秒数（< 0.01 精度）逐个补给仍有容量的镜头，单步不超过其剩余容量；
   大额误差优先补给权重高的镜头（水填）。
5. 结果按 0.01s 取整；**总时长与目标误差 ≤ 1 秒**，否则 `PacingError`。
   所有镜头时长均在 1.5~6.0 内。

## 版本与失效

```
story.version = 2
story.versions = [{version_id, stage, created_at, label, source_version,
                   data:{concept, plan, characters, scenes, script, shots, pacing, quality}}]
story.active_version = "v3"
story.stale = {"script": true, "storyboard": true, "quality": true}
```
- 重新生成某阶段 → 新建版本快照（保留最近 10 个）；下游标记 `stale`。
- 切换/恢复版本只影响 story 数据；`images/`、`audio/` 文件与 shot_id 不动，恢复后旧画面自动重挂。

## 数据结构（`modules/story_schema.py`）

- `StoryConcept`：concept_id、core_conflict、reversal_type、horror_device、hook、duration_tier
- `StoryPlan`：theme、background、core_conflict、motivation、conflicts[]、foreshadows[]、reversal、hook、acts[{act,start,end}]
- `CharacterProfile`：character_id、name、role、look、motivation、voice
- `SceneProfile`：scene_id、name、look、lighting、props[]
- `ScriptSegment`：segment_id、scene_id、character_ids[]、visual、narration、dialogue[]、emotion、duration_hint
- `StoryboardShot`：shot_id、script_segment_id、scene_id、character_ids[]、image_prompt、motion、duration、voiced、transition
- `AudioSegment`：shot_id、kind(narration/dialogue)、text、voice、estimated_ms
- `QualityReport`：score、scores{8 项}、grade、vetoes[]、issues[{stage, shot_id, severity, message, suggestion}]、passed

兼容：旧 `story`（schema 1）打开时自动升级为 v2，旧字段（characters[].name/look、scenes[].name/look、shots[].index/scene/narration/duration/motion/voiced）全部保留；旧函数 `parse_story`、`to_project_shots`、`to_srt`、`build_consistency_hint`、`infer_style` 签名不变。

## 画风预设（`modules/style_presets.py`）

`comic_dark`（默认，彩色 2D 暗黑恐怖漫画）、`comic_cn`（中式水墨）、`comic_jp`（日式黑白网点）、`comic_bw`（黑白粗描线）、`comic_us`（美式强对比）、`realistic`（旧写实，保留可选）。
提示词顺序改为：**画风后缀 → 场景卡/角色卡 → 画面描述**。负面词按画风维护。

## 字幕修复

`render_engine.subtitle_style`：1080 宽 40pt 起、限制每行约 12 字、`Outline=2`、底条不透明度降一档、`MarginV` 下移；同步更新 `test_subtitle_font_scales_with_height`。

## 文件清单

**新增**：`story_schema.py`、`horror_rules.py`、`pacing.py`、`style_presets.py`、
`tests/test_story_schema.py`、`tests/test_horror_rules.py`、`tests/test_pacing.py`

**修改**：`story_engine.py`（重写五阶段，保留旧接口）、`story_panel.py`（候选→状态条→策划/剧本/分镜/评分→版本）、`project_manager.py`（story v2 归一）、`image_engine.py`（画风 + 按镜卡片筛选）、`sf_config.py`（画风默认）、`ai_config.py` + `ai_settings.py`（模型槽位、画风）、`main_window.py`（流水线接线、阶段回报、按镜出图）、`batch.py`（同入口）、`render_engine.py`（字幕）、`tests/test_story_engine.py`、`tests/test_ai_media.py`、`tests/test_render_engine.py`、`tests/test_project_manager.py`、`tests/gui_smoke.py`、`README.md`

**不动**：`voice_engine.py`、`media_tools.py`、`timeline.py`、`inspector.py`、`preview.py`、渲染滤镜/音频链、`ffmpeg_locator.py`、`thumbnails.py`、`sf_http.py`

## 实施顺序

1. 备份现状 → `D:\AImv\_backup_v2_before_v22`
2. 四个纯模块 + 单测（不联网）
3. `story_engine.py` 五阶段 + 调用日志/重试 + 本地质检 + 版本（假 transport 测试）
4. `project_manager` 迁移 + 单测（旧 JSON 零手工迁移）
5. `image_engine` 画风 + 卡片筛选 + 单测
6. `story_panel` + `main_window` 接线 + `batch`
7. 字幕修复 + 渲染测试
8. 全量单测 + GUI Smoke
9. 真实 API 跑「废弃医院、纸人、雨夜」：3 候选 → 选 1 → 五阶段 → 评分/否决/问题 → 导入时间轴 → 出 3 张图 → 渲染短片
10. 交付说明（改动、费用、产物路径、待目视评估项）

## 质量审核细则（2026-11-04 批准版）

**钩子**：不要求第 1 镜是高潮画面。要求**前 3 秒**（第一镜及其后续镜累计 ≥3 秒之前）
出现明确的悬念 / 异常 / 危险 / 强烈视觉吸引点。硬性否决条件 `weak_hook`：
首镜 + 次镜的旁白与画面都没有悬念词、异常词、危险词，且首镜 voiced 且旁白 < 6 字。

**结局**：允许完整结局、开放式结局、系列悬念（`series` / `open` / `closed` 三种类型），
不强制最后 3 镜解决所有问题。硬性否决 `abrupt_end`：最后一镜没有叙事收束信号
（收束词 / 反转词 / 回扣钩子），且无任何旁白收尾。

**人物与场景**：角色可跨多个场景出现。检查每个镜头引用的 `character_ids`、`scene_id`
是否存在于人物/场景表（硬性否决 `unknown_reference`）；镜头可跨镜出现同一角色。

**版本与素材关联**：`shot_id` + `shot_revision` + `content_hash`（画面描述+旁白+运镜+时长
的 sha1 前 16 位）。图片 `images/ai_{shot_id}_r{revision}_{hash8}.png`，配音
`audio/voice_{shot_id}_r{revision}.wav`。镜头记 `image_revision/image_hash/voice_revision`。
恢复旧版本时，按版本内 shot 的 revision/hash 优先重挂匹配素材；
没有匹配素材的镜头扫 `images/`、`audio/` 里同 shot_id 的文件，取**旧版本实际使用的 revision**；
禁止把不同 revision 的图/音混挂。

**版本持久化**：`story.versions` 真正写进 project.json（快照含 concept/plan/characters/
scenes/script/shots/pacing/quality）。保留最近 10 个**正式版本**（版本列表上限 10）。
清理旧版本前检查引用：`shots[].story_version`（时间轴）、`images/`、`audio/` 文件名；
被引用的版本不删。恢复 = 写正式版本列表 + 重挂素材 + 可重复执行；失败时以写前快照回滚。

**固定质量测试题材**：`tests/fixtures/quality_topics.json`（废弃医院·纸人·雨夜 / 凌晨三点的电梯 /
镜子里的另一个自己）。`tests/fixtures/quality_baseline.json` 保存测试生成结果摘要（标题、
分镜数、时长、评分、否决），模型/Prompt 更新时用 `tools/quality_compare.py` 对比。

## 验收标准（用户文档）

主题「废弃医院、纸人、雨夜」，3–5 分钟，30–50 有效分镜，完整背景/动机/冲突/伏笔/反转/对白，质量审核能发现问题，可导入现有时间轴。

## 环境备忘

- Python：`C:/Users/yekai.liu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`
- 测试：`python -m unittest discover -s tests -v`；GUI：`python tests/gui_smoke.py`
- 非 git 仓库；唯一回滚点是备份目录。
- API Key 位于 `C:/Users/yekai.liu/.ai_horror_studio/`，**任何输出都不得打印 Key 值**。
