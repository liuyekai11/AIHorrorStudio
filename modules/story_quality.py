"""本地确定性质量审核（V2.2）：不联网，毫秒级，覆盖六条硬性否决。

规则全部来自用户 2026-11-04 批准的《质量审核细则》：

* `weak_hook`：不要求第 1 镜是高潮画面。前 3 秒（首镜及累计 ≥3 秒前的镜）
  的旁白 + 画面描述里没有悬念词 / 异常词 / 危险词 / 强视觉词，
  且首镜 voiced 且旁白 < 6 字 → 否决。
* `abrupt_end`：允许完整 / 开放 / 系列悬念三种结局，不强制最后 3 镜解决问题；
  但最后一镜必须出现叙事收束信号（收束词 / 反转词 / 回扣钩子），
  或至少有旁白收尾。两者都没有 → 意外中断，否决。
* `unknown_reference`：镜头引用的 character_ids / scene_id 必须存在于人物 / 场景表。
* `missing_motivation`：策划里没有主角动机。
* `duration_mismatch`：总时长与目标差 > 容差（pacing 已保证可行，这里兜底）。
* `unforeshadowed_reversal`：策划写了反转但没有任何伏笔。

输出 QualityReport（story_schema），模型 rubric 分数由 story_engine 叠加。
"""
from datetime import datetime

from modules import horror_rules
from modules import pacing as pacing_mod
from modules import story_schema as ss


def local_review(story: dict, target_seconds: float | None = None) -> ss.QualityReport:
    """本地审核。story 为 schema 2 结构（升级过的）。"""
    report = ss.QualityReport(
        checked_at=datetime.now().isoformat(timespec="seconds"),
        notes="本地确定性审核（模型评分由引擎叠加）",
    )
    plan = story.get("plan") or {}
    characters = story.get("characters") or []
    scenes = story.get("scenes") or []
    shots = [s for s in (story.get("shots") or []) if isinstance(s, dict)]

    char_ids = {c.get("character_id") for c in characters if c.get("character_id")}
    scene_ids = {s.get("scene_id") for s in scenes if s.get("scene_id")}

    # ---- 人物动机 ----
    motivation = (plan.get("motivation") or "").strip()
    if not motivation and not any((c.get("motivation") or "").strip() for c in characters):
        report.vetoes.append({
            "code": "missing_motivation",
            "message": "策划与人物卡里都找不到主角动机（为什么非做这件事不可）。",
        })

    # ---- 钩子：前 3 秒 ----
    hook_text = []
    elapsed = 0.0
    for shot in shots:
        hook_text.append(shot.get("image_prompt") or shot.get("scene") or "")
        hook_text.append(shot.get("narration") or "")
        elapsed += float(shot.get("duration") or 0)
        if elapsed >= 3.0:
            break
    first = shots[0] if shots else {}
    first_narration = (first.get("narration") or "").strip()
    if shots and not horror_rules.has_hook(" ".join(hook_text)):
        # 词表没命中也不立即否决：首镜有旁白且 ≥6 字仍算「有钩子尝试」
        if not (first.get("voiced") and len(first_narration) >= 6):
            report.vetoes.append({
                "code": "weak_hook",
                "message": "前 3 秒没有出现明确的悬念 / 异常 / 危险 / 强视觉吸引点。",
                "shot_id": first.get("shot_id", ""),
            })

    # ---- 结局收束 ----
    if shots:
        last = shots[-1]
        ending_type = plan.get("ending_type") or "closed"
        tail_text = " ".join(
            " ".join((s.get("narration") or "") + (s.get("image_prompt")
                                                    or s.get("scene") or "")
                     for s in shots[-3:]).split())
        has_signal = horror_rules.has_closure(tail_text, ending_type)
        has_voice_tail = bool((last.get("narration") or "").strip())
        if not has_signal and not has_voice_tail:
            report.vetoes.append({
                "code": "abrupt_end",
                "message": "最后一镜没有任何叙事收束信号，故事像被意外截断。",
                "shot_id": last.get("shot_id", ""),
            })
        # 结局描述缺失时给提示（不是否决——允许开放式）
        if not (plan.get("ending") or "").strip():
            report.issues.append(ss.QualityIssue(
                stage="plan", severity="warning", code="no_ending_desc",
                message="策划没有写结局描述（完整 / 开放 / 系列悬念都可以，但要有）。",
                suggestion="补一句结局怎么收，避免生成时意外中断。"))

    # ---- 引用检查 ----
    for shot in shots:
        sid = shot.get("scene_id") or ""
        if sid and sid not in scene_ids:
            report.vetoes.append({
                "code": "unknown_reference",
                "message": f"镜头 {shot.get('shot_id', '?')} 引用了不存在的场景 {sid}。",
                "shot_id": shot.get("shot_id", ""),
            })
        for cid in shot.get("character_ids") or []:
            if cid not in char_ids:
                report.vetoes.append({
                    "code": "unknown_reference",
                    "message": (f"镜头 {shot.get('shot_id', '?')} 引用了不存在的人物 {cid}。"),
                    "shot_id": shot.get("shot_id", ""),
                })

    # ---- 时长 ----
    total = round(sum(float(s.get("duration") or 0) for s in shots), 2)
    target = target_seconds if target_seconds is not None else \
        (story.get("pacing") or {}).get("target_seconds")
    if target:
        try:
            target = float(target)
            if abs(total - target) > ss.TOTAL_DURATION_TOLERANCE:
                report.vetoes.append({
                    "code": "duration_mismatch",
                    "message": (f"总时长 {total:.1f} 秒与目标 {target:.1f} 秒相差 "
                                f"{abs(total - target):.1f} 秒，超过容差 "
                                f"{ss.TOTAL_DURATION_TOLERANCE:g} 秒。"),
                })
        except (TypeError, ValueError):
            pass

    # ---- 反转伏笔 ----
    has_reversal = bool((plan.get("reversal") or "").strip()) or \
        (plan.get("reversal_type") or "none") != "none"
    foreshadows = [f for f in (plan.get("foreshadows") or []) if isinstance(f, dict)]
    if has_reversal and not foreshadows:
        report.vetoes.append({
            "code": "unforeshadowed_reversal",
            "message": "策划写了反转，但没有任何伏笔（观众会觉得突兀）。",
        })

    # ---- 提示类问题（不算否决）----
    voiced = [s for s in shots if s.get("voiced") and (s.get("narration") or "").strip()]
    if shots and len(voiced) / len(shots) > 0.85:
        report.issues.append(ss.QualityIssue(
            stage="storyboard", severity="info", code="too_dense",
            message="几乎所有镜头都有旁白，缺少留白镜。",
            suggestion="每 3~4 镜留 1 镜只有画面与环境音。"))
    long_narrations = [s for s in voiced if len((s.get("narration") or "").strip()) > 15]
    for shot in long_narrations[:5]:
        report.issues.append(ss.QualityIssue(
            stage="script", severity="warning", code="long_narration",
            message=f"镜头 {shot.get('shot_id', '?')} 旁白超过 15 字，读起来赶。",
            shot_id=shot.get("shot_id", ""),
            suggestion="精简到 15 字以内或拆成两镜。"))
    if shots and not pacing_mod.within_tolerance(total, target) and target:
        report.issues.append(ss.QualityIssue(
            stage="pacing", severity="info", code="pacing_drift",
            message=f"总时长 {total:.1f} 秒与目标 {float(target):.1f} 秒有偏差。",
            suggestion="重新执行时长分配。"))
    chars_in_shots = {cid for s in shots for cid in (s.get("character_ids") or [])}
    unused = char_ids - chars_in_shots
    if unused:
        report.issues.append(ss.QualityIssue(
            stage="plan", severity="info", code="unused_character",
            message=f"人物 {('、'.join(sorted(unused)))[:60]} 没有出现在任何镜头里。",
            suggestion="删掉多余人物卡或补镜头。"))

    report.compute_score()
    return report


def merge_review(local: ss.QualityReport, model_report: ss.QualityReport | None,
                 ) -> ss.QualityReport:
    """本地审核 + 模型 rubric 合并：分数用模型的，否决与问题取并集。"""
    if model_report is None:
        return local
    merged = ss.QualityReport(
        scores=dict(model_report.scores),
        model=model_report.model,
        notes=(model_report.notes or "") + "；含本地硬性检查",
        checked_at=local.checked_at or model_report.checked_at,
    )
    merged.vetoes = local.vetoes + [v for v in model_report.vetoes
                                    if v not in local.vetoes]
    seen = {(i.stage, i.code, i.shot_id) for i in local.issues}
    for issue in model_report.issues:
        key = (issue.stage, issue.code, issue.shot_id)
        if key not in seen:
            merged.issues.append(issue)
            seen.add(key)
    merged.compute_score()
    return merged
