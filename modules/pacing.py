"""动态时长规划器（V2.2）。

用户批准的算法：带上下限约束的加权分配。
--------------------------------------------------
1. 可行区间检查：n×MIN ≤ 目标 ≤ n×MAX。不满足时先自动调整镜头数，
   仍不满足则抛 PacingError（调用方提示改目标时长）。
2. 加权初分配：每镜权重 = 节奏档 × 朗读时长 × 留白系数，归一化 × 目标后钳到 [MIN, MAX]。
3. 约束再分配（water-filling）：越界镜头固定到边界，剩余时长在剩余镜头里按权重重新分配，
   迭代到无镜头越界。
4. 误差修正：剩余秒数按权重逐个补给仍有容量的镜头（水填），保证
   总时长与目标误差 ≤ TOTAL_TOLERANCE（1 秒）。
5. 结果按 0.01 秒取整，并做最后一次取整修正，保证取整后仍在容差内。

纯逻辑模块，不联网、不依赖项目其它模块。
"""
import math

MIN_SECONDS = 1.5
MAX_SECONDS = 6.0
TOTAL_TOLERANCE = 1.0
CHARITY_PER_CHAR = 1.0 / 4.2      # 中文朗读约 4.2 字/秒
PAUSE_SECONDS = 0.35              # 句尾停顿
SILENT_FACTOR = 1.1               # 留白镜（无旁白）略长，让环境音说话
DEFAULT_WEIGHTS = {"hook": 1.2, "setup": 1.0, "escalation": 0.9,
                   "reversal": 0.7, "aftertaste": 1.4}
DEFAULT_AVG_SHOT = 3.5            # 自动调整镜头数时按这个平均镜长估
BEAT_LABELS = {"hook": "钩子", "setup": "建置", "escalation": "升级",
               "reversal": "反转", "aftertaste": "余味"}


class PacingError(ValueError):
    """时长分配无法满足约束。message 可直接展示。"""


def reading_seconds(text: str) -> float:
    """旁白朗读时长估算：字数 / 4.2 + 停顿。"""
    chars = len((text or "").strip())
    return chars * CHARITY_PER_CHAR + PAUSE_SECONDS if chars else 0.0


def feasible_range(n: int) -> tuple[float, float]:
    return n * MIN_SECONDS, n * MAX_SECONDS


def adjust_shot_count(target_seconds: float, shot_count: int | None = None,
                      avg_shot: float = DEFAULT_AVG_SHOT,
                      min_shots: int = 1, max_shots: int = 200) -> int:
    """在 [min_shots, max_shots] 内找一个能满足目标时长的镜头数。

    优先保留调用方给的 shot_count（可行就返回它）；不可行时改成
    round(目标 / avg_shot) 再钳到数学上可行的范围。
    """
    target = float(target_seconds)
    if target <= 0:
        raise PacingError("目标时长必须大于 0 秒。")
    n_min = max(1, int(math.ceil(target / MAX_SECONDS)))
    n_max = max(n_min, int(math.floor(target / MIN_SECONDS)))
    n_min = max(n_min, int(min_shots))
    n_max = min(n_max, int(max_shots))
    if n_min > n_max:
        raise PacingError(
            f"目标时长 {target:.1f} 秒无法用 {min_shots}~{max_shots} 个镜头实现"
            f"（单镜 {MIN_SECONDS}~{MAX_SECONDS} 秒）。请调整目标时长或镜头数量。")
    if shot_count is not None:
        try:
            n = int(shot_count)
        except (TypeError, ValueError):
            n = 0
        if n_min <= n <= n_max:
            return n
    avg = max(MIN_SECONDS, min(MAX_SECONDS, float(avg_shot or DEFAULT_AVG_SHOT)))
    n = int(round(target / avg))
    return max(n_min, min(n_max, n))


def beat_weight(beat: str, weights: dict | None = None) -> float:
    table = dict(DEFAULT_WEIGHTS)
    if isinstance(weights, dict):
        table.update({k: float(v) for k, v in weights.items()
                      if k in DEFAULT_WEIGHTS and isinstance(v, (int, float))})
    return max(0.05, float(table.get(beat or "", 1.0)))


def shot_weights(shots: list[dict], weights: dict | None = None) -> list[float]:
    """每镜权重 = 节奏档 × 朗读时长系数 × 留白系数。

    朗读时长系数：1 + 2 × 停顿后的朗读秒数 / 3，即 3 秒旁白约 ×3；
    上限 4，避免超长旁白吞掉所有时长。没有旁白时取 1。
    """
    result = []
    for shot in shots:
        w = beat_weight(shot.get("beat", ""), weights)
        narration = (shot.get("narration") or "").strip()
        if narration:
            read = reading_seconds(narration)
            w *= min(4.0, 1.0 + 2.0 * read / 3.0)
        else:
            w *= SILENT_FACTOR
        result.append(max(0.05, w))
    return result


def allocate(target_seconds: float, weights: list[float]) -> list[float]:
    """带上下限约束的加权分配。返回与 weights 等长的时长列表（未取整）。

    target 必须落在 [n×MIN, n×MAX] 内，否则抛 PacingError。
    """
    n = len(weights)
    if n == 0:
        raise PacingError("没有镜头可以分配时长。")
    target = float(target_seconds)
    lo, hi = feasible_range(n)
    if target < lo - 1e-9 or target > hi + 1e-9:
        raise PacingError(
            f"{n} 个镜头无法分配出 {target:.2f} 秒：可行范围 "
            f"{lo:.1f}~{hi:.1f} 秒。请调整镜头数量或目标时长。")
    ws = [max(0.05, float(w)) for w in weights]
    if target > n * MAX_SECONDS + 1e-9 or target < n * MIN_SECONDS - 1e-9:
        raise PacingError(
            f"{n} 个镜头无法分配出 {target:.2f} 秒：可行范围 "
            f"{n * MIN_SECONDS:.1f}~{n * MAX_SECONDS:.1f} 秒。")
    if target > n * MAX_SECONDS - 0.05 or target < n * MIN_SECONDS + 0.05:
        # 贴着上下限：等分；能凑整到 0.01 秒的正好凑整，凑不整的逐镜差 0.01 秒
        return _even_split(n, target)

    result = [None] * n
    active = list(range(n))
    remaining = target
    # 3) 约束再分配：固定越界者，剩余按权重重新分配，直到收敛
    for _ in range(n + 2):
        if not active:
            break
        total_w = sum(ws[i] for i in active)
        scale = remaining / total_w if total_w > 0 else 0.0
        pinned = [i for i in active if ws[i] * scale > MAX_SECONDS or ws[i] * scale < MIN_SECONDS]
        if not pinned:
            for i in active:
                result[i] = ws[i] * scale
            active = []
            remaining = 0.0
            break
        for i in pinned:
            if ws[i] * scale > MAX_SECONDS:
                result[i] = MAX_SECONDS
                remaining -= MAX_SECONDS
            else:
                result[i] = MIN_SECONDS
                remaining -= MIN_SECONDS
            active.remove(i)
        if remaining < 0:
            # 固定值之和已超出目标（理论上不会发生，因为 target 在可行区间内）
            remaining = 0.0
    if active:  # 防御：不变量被破坏时，剩余镜头直接均分
        share = remaining / len(active)
        for i in active:
            result[i] = min(MAX_SECONDS, max(MIN_SECONDS, share))

    # 4) 误差修正：剩余秒数按权重补给仍有容量的镜头
    diff = target - sum(result)
    if diff > 1e-9:
        result = _fill(result, ws, diff)
    elif diff < -1e-9:
        result = _drain(result, ws, -diff)
    # 5) 最后的硬性钳制 + 把钳制造成的误差挪给邻居，保证上下限与总时长同时成立
    result = _clamp_balance(result, target)
    return result


def _clamp_balance(durations: list[float], target: float) -> list[float]:
    out = [min(MAX_SECONDS, max(MIN_SECONDS, d)) for d in durations]
    n = len(out)
    if target > n * MAX_SECONDS + 1e-9 or target < n * MIN_SECONDS - 1e-9:
        raise PacingError(
            f"{n} 个镜头无法分配出 {target:.2f} 秒：可行范围 "
            f"{n * MIN_SECONDS:.1f}~{n * MAX_SECONDS:.1f} 秒。")
    if target > n * MAX_SECONDS - 0.05 or target < n * MIN_SECONDS + 0.05:
        # 贴着可行边界：等分最稳（避免「误差修正」再次把镜头推出上限）
        return _even_split(n, target)
    for _ in range(len(out) * 4 + 4):
        diff = target - sum(out)
        if abs(diff) <= 1e-6:
            break
        if diff > 0:
            free = [i for i, d in enumerate(out) if d < MAX_SECONDS - 1e-9]
            if not free:
                break
            share = diff / len(free)
            for i in free:
                out[i] = min(MAX_SECONDS, out[i] + share)
        else:
            free = [i for i, d in enumerate(out) if d > MIN_SECONDS + 1e-9]
            if not free:
                break
            share = -diff / len(free)
            for i in free:
                out[i] = max(MIN_SECONDS, out[i] - share)
    return out


def _even_split(n: int, total: float) -> list[float]:
    """把 total 尽量平均分给 n 个镜头，保证每个值都在 [MIN, MAX] 内。"""
    if n <= 0:
        return []
    total = min(n * MAX_SECONDS, max(n * MIN_SECONDS, float(total)))
    base = math.floor(total / n * 100 + 1e-9) / 100
    out = []
    remaining = round(total - base * n, 2)
    for _ in range(n):
        if remaining >= 0.01 - 1e-9:
            out.append(round(base + 0.01, 2))
            remaining = round(remaining - 0.01, 2)
        else:
            out.append(base)
    return [min(MAX_SECONDS, max(MIN_SECONDS, v)) for v in out]


def _fill(durations: list[float], weights: list[float], amount: float) -> list[float]:
    """把 amount 秒按权重水填进还有余量的镜头。"""
    durations = list(durations)
    for _ in range(len(durations) * 2 + 2):
        if amount <= 1e-9:
            break
        room = [MAX_SECONDS - d for d in durations]
        total_room = sum(room)
        if total_room <= 1e-9:
            break
        step = min(amount, total_room)
        active = [i for i, r in enumerate(room) if r > 1e-9]
        # 当前短于最小值的镜头优先补齐（保证不越下限）
        need = [max(0.0, MIN_SECONDS - durations[i]) for i in range(len(durations))]
        if sum(need) > 0:
            for i, nd in enumerate(need):
                take = min(nd, step)
                if take > 0:
                    durations[i] += take
                    step -= take
                    amount -= take
                if step <= 1e-9:
                    break
            continue
        # 在剩余空间上按权重归一（避免某个剪辑权重过大时其余镜头被挤成 1.5 秒）
        total_w = sum(weights[i] for i in active)
        if total_w <= 0:
            share = step / len(active)
            for i in active:
                durations[i] += share
            amount -= step
            continue
        denom = sum(room[i] * weights[i] for i in active) / total_w
        if denom <= 1e-9:          # 有空间的全是权重≈0 的镜头：等比填充
            denom = sum(room[i] for i in active) / len(active) * total_w / max(1e-9, sum(weights[i] for i in active) or total_w)
        # 按权重分配，但不让任何镜头超过 MAX（超出的部分下一轮再分）
        gained = 0.0
        for i in active:
            add = min(step * weights[i] / (total_w * denom), room[i]) if denom > 0 else 0.0
            durations[i] += add
            gained += add
        diff = step - gained
        amount -= gained
        if diff <= 1e-9:
            break          # 本轮的量全部分完且没人被上限截断
        # 有人被截断：把没分完的量还给 amount 继续下一轮
        amount += diff
    remaining = amount
    if remaining > 1e-9:
        # 仍有剩余：再按容量均摊一次
        room = [MAX_SECONDS - d for d in durations]
        total_room = sum(room)
        if total_room > 0:
            for i, r in enumerate(room):
                durations[i] += min(r, remaining * r / total_room)
    return durations


def _drain(durations: list[float], weights: list[float], amount: float) -> list[float]:
    """从时长超出加权目标的镜头里收走 amount 秒，保证不低于最小值。"""
    durations = list(durations)
    total_w = sum(weights) or 1.0
    targets = [w / total_w * sum(durations) for w in weights]
    while amount > 1e-9:
        excess = [max(0.0, d - MIN_SECONDS) for d in durations]
        if sum(excess) <= 1e-9:
            break
        # 优先从「比加权目标多出来更多」的镜头里收
        over = [max(1e-6, d - t) for d, t in zip(durations, targets)]
        total_over = sum(over)
        taken = 0.0
        for i in range(len(durations)):
            take = min(amount * over[i] / total_over, excess[i])
            durations[i] -= take
            taken += take
        amount -= taken
        if taken <= 1e-9:
            break
    return durations


def round_durations(durations: list[float], target: float) -> list[float]:
    """按 0.01 秒取整，并把取整误差补给余量最大的镜头，保证误差 ≤ 容差。"""
    if not durations:
        return []
    rounded = [round(min(MAX_SECONDS, max(MIN_SECONDS, d)), 2) for d in durations]
    total = round(sum(rounded), 2)
    diff = round(float(target) - total, 2)
    if abs(diff) >= 0.01:
        # 每次调 0.01 秒：补到余量最大的镜头 / 从最长的镜头里收，直到误差 < 0.005
        # 单次最多补 / 收 min(0.5, 需要的量)，轮流分配给不同镜头，避免把一个镜头顶到上限
        chunk = round(min(0.5, abs(diff)), 2)
        guard = int(abs(diff) / chunk) * len(rounded) + len(rounded) * 2
        for _ in range(guard):
            diff = round(float(target) - sum(rounded), 2)
            if abs(diff) < 0.005:
                break
            step = round(min(chunk, abs(diff)), 2)
            if diff > 0:
                i = max(range(len(rounded)), key=lambda k: MAX_SECONDS - rounded[k])
                if MAX_SECONDS - rounded[i] < 0.005:
                    break
                rounded[i] = round(min(MAX_SECONDS - 0.01, rounded[i] + step), 2)
            else:
                i = max(range(len(rounded)), key=lambda k: rounded[k] - MIN_SECONDS)
                if rounded[i] - MIN_SECONDS < 0.005:
                    break
                rounded[i] = round(max(MIN_SECONDS + 0.01, rounded[i] - step), 2)
    return rounded


def plan_durations(shots: list[dict], target_seconds: float | None = None,
                   weights: dict | None = None, allow_resize: bool = False,
                   avg_shot: float = DEFAULT_AVG_SHOT) -> dict:
    """给分镜分配时长。

    shots: [{"beat","narration",...}]（不修改输入）
    target_seconds: None 时按「每个镜头给模型 / 剧本建议的时长并钳到 1.5~6」处理，
                    只做上下限约束，不追求总长。
    allow_resize: True 时在镜头数不可行的情况下自动调整镜头数（截断或提示），
                  返回 need_more_shots 让调用方决定，不擅自增删镜头内容。
    返回：
        {"durations":[...], "total":..., "target":..., "error":...,
         "weights":{beat: w}, "per_shot":[{"beat","weight","duration","read_seconds"}],
         "resized": bool, "shot_count": n, "message": str,
         "kept_shot_ids": [...] 或 None, "kept_count": 分配实际覆盖的镜头数,
         "trimmed_index": 被截断的镜头下标列表（无截断时为 None）}
    注意：镜头数不可行且需要截断时，durations 只覆盖前 feasible_n 个镜头，
    调用方必须用 kept_shot_ids / kept_count 判断哪些镜头拿到了时长，
    不能假设 len(durations) == len(输入 shots)。
    """
    if not isinstance(shots, (list, tuple)) or not shots:
        raise PacingError("没有分镜可以分配时长。")
    shots = [s for s in shots if isinstance(s, dict)]
    if not shots:
        raise PacingError("分镜数据为空或格式不正确，无法分配时长。")
    n = len(shots)
    per_weights = shot_weights(shots, weights)
    wmap = dict(DEFAULT_WEIGHTS)
    if isinstance(weights, dict):
        wmap.update({k: v for k, v in weights.items() if k in DEFAULT_WEIGHTS})

    if target_seconds is None:
        raw = []
        for shot, w in zip(shots, per_weights):
            hint = float(shot.get("duration") or 0)
            if hint <= 0:
                hint = min(MAX_SECONDS, max(MIN_SECONDS, 2.0 + (w - 1.0)))
            raw.append(min(MAX_SECONDS, max(MIN_SECONDS, hint)))
        durations = round_durations(raw, sum(raw))
        total = round(sum(durations), 2)
        return _result(shots, durations, per_weights, wmap, None, total, False, "")

    try:
        target = float(target_seconds)
    except (TypeError, ValueError):
        raise PacingError(f"目标时长不是有效数值：{target_seconds!r}") from None
    if not math.isfinite(target) or target <= 0:
        raise PacingError("目标时长必须是大于 0 的有效秒数。")
    lo, hi = feasible_range(n)
    resized = False
    message = ""
    original_n = n
    if target < lo - 1e-9 or target > hi + 1e-9:
        feasible_n = adjust_shot_count(target, n, avg_shot)
        resized = True
        if not allow_resize:
            if n > feasible_n:
                message = (f"{n} 个分镜放不进 {target:.1f} 秒（单镜 {MIN_SECONDS}~{MAX_SECONDS} 秒），"
                           f"按平均 {avg_shot:g} 秒建议改成 {feasible_n} 个分镜。"
                           f" 已按目标时长截断多余的镜头。")
                per_weights = per_weights[:feasible_n]
                shots = shots[:feasible_n]
                n = feasible_n
            else:
                # 镜头太少：分配镜头数能达到的最长总长（不凭空造镜头）
                need = int(math.ceil(target / MAX_SECONDS))
                message = (f"{n} 个分镜最多 {feasible_range(n)[1]:.1f} 秒，放不进 {target:.1f} 秒"
                           f"（单镜 {MIN_SECONDS}~{MAX_SECONDS} 秒）：至少要 {need} 个分镜，"
                           f"按平均 {avg_shot:g} 秒建议 {feasible_n} 个。已按现有镜头分配最大可行总长。")
                target = feasible_range(n)[1]
        else:
            message = f"已按目标时长把分镜数调整为 {feasible_n} 个（原 {n} 个）。"
            if n > feasible_n:
                per_weights = per_weights[:feasible_n]
                shots = shots[:feasible_n]
                n = feasible_n
            else:
                message = (f"分镜太少，无法撑满 {target:.1f} 秒：请至少增加到 "
                           f"{int(math.ceil(target / MAX_SECONDS))} 个分镜。")
                target = feasible_range(n)[1]
        lo, hi = feasible_range(n)
    target_tol = target              # 本轮实际要凑的目标（镜头数被调整时可能与用户目标不同）
    # 贴着上下限时给一点回退量，保证按 0.01 秒取整后仍不越界
    # 若镜头数已经是可行区间内能取的极值（例如 3 镜撑 150 秒，只能取上限或截断），
    # 就不回退，让总时长正好落在边界上。
    n_min_math = int(math.ceil(target / MAX_SECONDS))
    n_max_math = int(math.floor(target / MIN_SECONDS))
    at_cap = n <= n_min_math                 # 镜头数已是最少：目标是上限
    at_floor = n >= n_max_math               # 镜头数已是最多：目标是下限
    target = min(hi - (0.0 if at_cap else 0.05), max(lo + (0.0 if at_floor else 0.05), target))

    raw = allocate(target, per_weights)
    durations = round_durations(raw, target)
    total = round(sum(durations), 2)
    error = round(total - target_tol, 2)
    if abs(error) > TOTAL_TOLERANCE + 1e-9:
        raise PacingError(
            f"时长分配失败：总时长 {total:.2f} 秒与目标 {target_tol:.2f} 秒相差 "
            f"{abs(error):.2f} 秒，超过 {TOTAL_TOLERANCE:g} 秒容差。")
    check_durations(durations, len(shots), total, target_tol)
    return _result(shots, durations, per_weights, wmap, target_tol, total, resized, message,
                   trimmed_n=original_n - n)


def check_durations(durations, expected_count: int, total: float,
                    target: float) -> None:
    """输出不变量检查：数量、每镜均为数值且落在上下限内、总时长在容差内。

    任一不满足都抛 PacingError——宁可明确失败，也不能把错位的时长交给下游。
    """
    if len(durations) != expected_count:
        raise PacingError(
            f"时长数量 {len(durations)} 与镜头数量 {expected_count} 不一致。")
    for i, d in enumerate(durations, 1):
        if isinstance(d, bool) or not isinstance(d, (int, float)):
            raise PacingError(f"第 {i} 镜时长不是数值：{d!r}")
        if d < MIN_SECONDS - 1e-9 or d > MAX_SECONDS + 1e-9:
            raise PacingError(f"第 {i} 镜时长 {d} 秒不在 {MIN_SECONDS}~{MAX_SECONDS} 秒内。")
    if abs(float(total) - float(target)) > TOTAL_TOLERANCE + 1e-9:
        raise PacingError(
            f"总时长 {total:.2f} 秒与目标 {target:.2f} 秒相差超过 {TOTAL_TOLERANCE:g} 秒。")


def _result(shots, durations, per_weights, wmap, target, total, resized, message,
            trimmed_n=0):
    per_shot = []
    for shot, w, d in zip(shots, durations, per_weights):
        per_shot.append({
            "beat": shot.get("beat", ""),
            "weight": round(w, 3),
            "duration": d,
            "read_seconds": round(reading_seconds(shot.get("narration", "")), 2),
        })
    # 让调用方知道时长究竟分给了哪些镜头：shot_id 优先，没有 id 时用输入下标
    kept_ids = [shot.get("shot_id") if shot.get("shot_id") is not None else i
                for i, shot in enumerate(shots)]
    trimmed = list(range(len(shots), len(shots) + trimmed_n)) if trimmed_n > 0 else None
    return {
        "durations": durations,
        "total": total,
        "target": None if target is None else round(float(target), 2),
        "error": None if target is None else round(total - float(target), 2),
        "weights": wmap,
        "per_shot": per_shot,
        "resized": resized,
        "shot_count": len(durations),
        "kept_count": len(durations),
        "kept_shot_ids": kept_ids,
        "trimmed_index": trimmed,
        "message": message,
    }


def duration_error(total: float, target: float) -> float:
    return round(abs(float(total) - float(target)), 2)


def within_tolerance(total: float, target: float,
                     tolerance: float = TOTAL_TOLERANCE) -> bool:
    return duration_error(total, target) <= tolerance + 1e-9
