"""V2.2 固定题材质量基线：跑真实 API，把结果摘要存成可对比的 JSON。

用法：
    python tools/quality_baseline.py --out tests/fixtures/quality_baseline.json
    python tools/quality_baseline.py --only hospital        # 只跑一个题材
    python tools/quality_baseline.py --skip-images          # 只跑故事（不花钱出图）

对 tests/fixtures/quality_topics.json 里的每个题材执行完整 V2.2 流程：
创意候选（3 个）→ 固定选第 1 个 → 五阶段流水线 → 质量审核 → 出 3 张图。

产物：
- tests/fixtures/quality_baseline.json：摘要（标题/镜数/时长/评分/否决/阶段耗时）
- baseline_runs/{topic_id}/story.json：完整 story（人工复核用）
- baseline_runs/{topic_id}/images/*.png：每个题材前 3 镜的图

注意：本脚本会调用真实 API（DeepSeek + 硅基流动），一次全量约几十万 token
（约几毛钱人民币）。Key 从 ~/.ai_horror_studio/ 读，绝不打印。
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import ai_config, sf_config                      # noqa: E402
from modules.story_engine import StoryEngine, StageError      # noqa: E402

TOPICS_FILE = ROOT / "tests" / "fixtures" / "quality_topics.json"
RUNS_DIR = ROOT / "baseline_runs"
IMAGE_COUNT = 3      # 每个题材出几张图（只验证画风/一致性，不出全片）


def run_topic(engine, topic, skip_images: bool) -> dict:
    """跑一个题材，返回摘要 dict（不抛异常，错误也记进摘要）。"""
    started = time.monotonic()
    stages: list[dict] = []
    summary = {
        "topic_id": topic["id"], "keywords": topic["keywords"],
        "style": topic["style"], "shot_count": topic["shot_count"],
        "ok": False, "error": "", "concepts": 0, "chosen_concept": "",
        "stages": stages, "images": [],
    }

    def on_stage(stage, text):
        stages.append({"stage": stage, "text": text, "at": round(time.monotonic() - started, 1)})

    engine.on_stage = on_stage
    try:
        # 阶段 0：创意候选
        concepts = engine.generate_concepts(topic["keywords"], topic["style"],
                                            topic.get("extra") or "")
        summary["concepts"] = len(concepts)
        # 固定选第 1 个（对比基线必须确定，选最好的会随模型漂移）
        concept = concepts[0]
        summary["chosen_concept"] = concept.get("title") or ""

        # 阶段 1~5：完整流水线
        story = engine.pipeline(concept, topic["keywords"], topic["style"],
                                topic.get("extra") or "",
                                shot_count=topic["shot_count"],
                                use_model_review=True)
        quality = story.get("quality") or {}
        shots = story.get("shots") or []
        summary.update({
            "ok": True,
            "title": story.get("title") or "",
            "logline": story.get("logline") or "",
            "schema_version": story.get("schema_version"),
            "actual_shots": len(shots),
            "total_seconds": round(sum(float(s.get("duration") or 0) for s in shots), 2),
            "target_seconds": (story.get("pacing") or {}).get("target_seconds"),
            "pacing_error": (story.get("pacing") or {}).get("error"),
            "duration_min": round(min((float(s.get("duration") or 0) for s in shots), ), 2) if shots else 0,
            "duration_max": round(max((float(s.get("duration") or 0) for s in shots)), 2) if shots else 0,
            "score": quality.get("score"),
            "grade": quality.get("grade"),
            "vetoes": [v.get("code") for v in (quality.get("vetoes") or [])
                       if isinstance(v, dict)],
            "issues": len(quality.get("issues") or []),
            "ruleset": story.get("ruleset") or "",
            "model": story.get("model") or "",
        })
        # 持久化完整 story（人工复核 / 素材重挂验证用）
        out_dir = RUNS_DIR / topic["id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "story.json").write_text(
            json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")

        if not skip_images:
            summary["images"] = generate_sample_images(topic, story, out_dir)
    except StageError as exc:
        summary["error"] = f"[{exc.stage}] {exc}"
    except Exception as exc:  # noqa: BLE001 - 摘要里也要能看到失败
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        engine.on_stage = None
    summary["elapsed_s"] = round(time.monotonic() - started, 1)
    return summary


def generate_sample_images(topic: dict, story: dict, out_dir: Path) -> list[str]:
    """出每个题材前 3 镜的图（验证画风预设 + 一致性卡片是否真的进了提示词）。"""
    from modules.image_engine import ImageEngine, build_consistency_hint, pick_size
    from modules import story_schema as ss

    cfg = sf_config.load_config()
    if not cfg.get("api_key"):
        return [{"error": "硅基流动未配置 Key，跳过出图"}]
    engine = ImageEngine(config=cfg)
    model = getattr(engine, "model", "")
    size = pick_size(1080, 1920, model)
    style_key = sf_config.load_config().get("image_style") or "comic_dark"
    from modules.image_engine import STYLE_PRESETS
    if style_key not in STYLE_PRESETS:
        style_key = "comic_dark"
    shots = (story.get("shots") or [])[:IMAGE_COUNT]
    results = []
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for i, shot in enumerate(shots, 1):
        try:
            hint = build_consistency_hint(story, shot.get("image_prompt") or "", shot)
            target = img_dir / f"shot{i:02d}_{(shot.get('content_hash') or '')[:8]}.png"
            engine.generate_to_file(shot.get("image_prompt") or shot.get("scene") or "",
                                    target, style=style_key, extra=hint, size=size)
            results.append(str(target.relative_to(ROOT)).replace("\\", "/"))
        except Exception as exc:  # noqa: BLE001 - 单图失败不中断基线
            results.append({"error": f"shot{i}: {exc}"})
    # 顺带记录每镜引用是否合法（unknown_reference 的直接证据）
    ss_refs = check_references(story)
    if ss_refs:
        results.append({"reference_errors": ss_refs})
    return results


def check_references(story: dict) -> list[str]:
    problems = []
    char_ids = {str(c.get("character_id") or "") for c in story.get("characters") or []
                if isinstance(c, dict)}
    scene_ids = {str(s.get("scene_id") or "") for s in story.get("scenes") or []
                 if isinstance(s, dict)}
    for i, shot in enumerate(story.get("shots") or [], 1):
        for cid in shot.get("character_ids") or []:
            if cid and cid not in char_ids:
                problems.append(f"shot{i} 引用不存在角色 {cid}")
        sid = shot.get("scene_id")
        if sid and sid not in scene_ids:
            problems.append(f"shot{i} 引用不存在场景 {sid}")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "tests" / "fixtures" / "quality_baseline.json"))
    parser.add_argument("--only", default="", help="只跑指定 topic_id")
    parser.add_argument("--skip-images", action="store_true", help="只跑故事不出图")
    parser.add_argument("--append", action="store_true",
                        help="保留 baseline 里已有的题材，只更新这次跑的")
    args = parser.parse_args()

    cfg = ai_config.load_config()
    if not cfg.get("api_key"):
        print("错误：没有配置 DeepSeek API Key（~/.ai_horror_studio/）。")
        return 2
    topics = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))["topics"]
    if args.only:
        topics = [t for t in topics if t["id"] == args.only]
        if not topics:
            print(f"错误：找不到 topic_id={args.only}")
            return 2

    out_path = Path(args.out)
    baseline = {}
    if args.append and out_path.exists():
        try:
            baseline = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            baseline = {}

    results = []
    for topic in topics:
        print(f"[{topic['id']}] {topic['keywords']}（{topic['shot_count']} 镜）……",
              flush=True)
        engine = StoryEngine(config=cfg)
        summary = run_topic(engine, topic, skip_images=args.skip_images)
        status = "OK" if summary.get("ok") else f"FAILED: {summary.get('error')}"
        print(f"    → {status}  分数 {summary.get('score')}  "
              f"{summary.get('actual_shots', '?')} 镜 / {summary.get('total_seconds', '?')}s"
              f"  用时 {summary.get('elapsed_s')}s", flush=True)
        results.append(summary)

    baseline.update({
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python_args": {"only": args.only or None, "skip_images": args.skip_images},
        "results": results,
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n基线已写入 {out_path}（{ok}/{len(results)} 个题材成功）")
    print(f"完整 story 在 {RUNS_DIR}/ 目录，出图在 {RUNS_DIR}/*/images/")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
