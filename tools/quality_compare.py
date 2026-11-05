"""对比两次质量基线（quality_baseline.json），模型 / Prompt 更新后用来判断退步。

用法：
    python tools/quality_compare.py                       # 与自带基线对比新跑结果
    python tools/quality_compare.py --baseline a.json --current b.json

退出码：0 = 没有退步；1 = 有题材分数下降 / 出现新的硬性否决 / 失败。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = ROOT / "tests" / "fixtures" / "quality_baseline.json"


def load(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"读取失败 {path}: {exc}")
    return {r.get("topic_id") or r.get("id"): r for r in data.get("results") or []}


def compare(old: dict, new: dict) -> list[str]:
    lines = []
    regressions = []
    for topic_id in sorted(set(old) | set(new)):
        a, b = old.get(topic_id), new.get(topic_id)
        if a is None:
            lines.append(f"＋ {topic_id}: 新题材（无基线）  {_line(b)}")
            continue
        if b is None:
            lines.append(f"－ {topic_id}: 本次未跑  {_line(a)}")
            continue
        old_score = float(a.get("score") or 0)
        new_score = float(b.get("score") or 0)
        delta = new_score - old_score
        flag = "  " if delta >= -3 else "⚠ "
        lines.append(f"{flag}{topic_id}: {old_score:.0f} → {new_score:.0f} "
                     f"({delta:+.0f})  {_line(b)}")
        if delta < -3:
            regressions.append(f"{topic_id} 分数下降 {delta:.0f}")
        old_veto = set(a.get("vetoes") or [])
        new_veto = set(b.get("vetoes") or []) - old_veto
        if new_veto:
            regressions.append(f"{topic_id} 出现新否决：{'、'.join(sorted(new_veto))}")
        if not b.get("ok"):
            # 基线里失败的题材也视为退步：不能因为「上次就失败」而把失败当成常态
            regressions.append(f"{topic_id} 本次失败：{b.get('error')}")
        if (a.get("actual_shots") or 0) and (b.get("actual_shots") or 0):
            if abs((b["actual_shots"] or 0) - (a["actual_shots"] or 0)) > 6:
                lines.append(f"     镜数变化 {a['actual_shots']} → {b['actual_shots']}")
    return lines, regressions


def _line(r: dict | None) -> str:
    if not r:
        return ""
    if not r.get("ok"):
        return f"失败：{r.get('error')}"
    return (f"{r.get('grade')}  {r.get('actual_shots')} 镜 / "
            f"{r.get('total_seconds')}s  否决 {r.get('vetoes') or '无'}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--current", default="")
    parser.add_argument("--current-report", action="store_true",
                        help="不跑 API，只对比 current 文件（配合 quality_baseline.py 的输出）")
    args = parser.parse_args()
    if not args.current:
        print("提示：用 --current 指定本次 quality_baseline.py 的输出文件。")
        return 2
    old = load(Path(args.baseline))
    new = load(Path(args.current))
    if not old:
        raise SystemExit(f"基线为空：{args.baseline}")
    lines, regressions = compare(old, new)
    print("\n".join(lines))
    if regressions:
        print("\n退步：")
        for r in regressions:
            print(f"  • {r}")
        return 1
    print("\n没有检测到退步。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
