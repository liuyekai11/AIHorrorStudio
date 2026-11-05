"""恐怖题材规则库（V2.2）：六类题材各自的写作规则、审核关键词与配音语气。

题材规则不只是提示词装饰，质量审核会用到：
* 钩子检查用 `HOOK_WORDS` / `DANGER_WORDS` / `ANOMALY_WORDS`
* 结局收束检查用 `CLOSURE_WORDS` / `REVERSAL_WORDS`（series 题材另加 `SERIES_HOOK_WORDS`）
* 动机检查用 `MOTIVATION_WORDS`
* 节奏检查建议从 `PACING` 的 beat 权重出发

纯数据 + 纯函数，不联网、不依赖其它模块。规则内容集中在 RULESETS 里，
改规则只改这一个文件，单测 `tests/test_horror_rules.py` 会校验结构完整性。
"""
import re

RULE_KEYS = ("folk", "psych", "urban", "sealed", "mystery", "loop")

RULESETS = {
    "folk": {
        "label": "中式民俗恐怖",
        "keywords": ("民俗", "纸人", "灵堂", "丧", "祠堂", "红白", "冥婚", "扎纸",
                     "符", "门神", "烧纸", "头七", "医院", "老宅", "戏台", "纸扎"),
        "tone": "压抑、潮湿、仪式感，不依赖血浆，恐怖来自「规矩」被打破",
        "structure": (
            "以一条本地禁忌 / 规矩开篇（例如「头七夜不能关灯」），主角因现实原因不得不破例；"
            "中段每一步都在加深「破戒的代价」，并用纸人、镜子、供桌等物件暗示有东西在代替活人；"
            "反转揭示「规矩」本身是谁定的、要的是什么；结局收束于代价已经兑现或即将兑现。"
        ),
        "must": ("至少一条成文的禁忌 / 习俗，且在前三镜出现",
                 "超自然规则前后一致（约定什么时候响、什么时候靠近）",
                 "用物件（纸人、香灰、红绳）承载恐怖，而不是只有音效"),
        "must_not": ("直接写鬼脸吓人", "靠血腥堆恐怖", "把民俗当纯装饰、之后不再提及"),
        "horror_devices": ("纸人替身", "香灰脚印", "红白撞色", "供桌下的影子", "守夜人的死亡时间"),
        "narration": "旁白像老人在讲一件不愿讲的事：短句、方言感、留白；不解释谜底。",
        "dialogue": "对白克制，多用反问和未说完的话；角色很少直呼鬼怪的名。",
        "ending": "代价兑现，但只给一半：观众知道发生了什么，却不知道明天还会不会发生。",
        "voice_style": "folk",
    },
    "psych": {
        "label": "心理恐怖",
        "keywords": ("心理", "记忆", "幻觉", "分裂", "失眠", "梦", "咨询", "创伤",
                     "镜子", "另一个自己", "失忆", "药"),
        "tone": "安静、琐碎、失控，恐怖来自「叙述者自己不可靠」",
        "structure": (
            "以一个具体的日常细节异常开篇（药瓶位置变了、照片多了一个人）；"
            "中段让主角不断「验证」却每次得到更深的自我怀疑；"
            "反转是主角与内心 / 过去的自己的关系；结局不解释全部，留下一个可以回看的细节。"
        ),
        "must": ("叙事视角清晰（谁在看、谁在讲）",
                 "每次恐怖升级都对应主角心理防线的一次后退",
                 "至少一个可回看的细节（二刷才发现不对劲）"),
        "must_not": ("用「一切都是梦」当唯一解释", "突然引入与心理无关的超自然力量",
                     "让角色凭空知道结局"),
        "horror_devices": ("镜中延迟", "多出来的一张照片", "重复的梦境细节", "第二把牙刷", "录音里的第三个人"),
        "narration": "旁白是主角的内心独白：片段化、可重复、语气平静但内容可怕。",
        "dialogue": "对白看似日常，句句都在试探对方是不是「那个版本」的人。",
        "ending": "主角做出选择，但观众无法确认这是解脱还是新一轮循环的开始。",
        "voice_style": "psych",
    },
    "urban": {
        "label": "都市怪谈",
        "keywords": ("都市", "地铁", "电梯", "公寓", "楼道", "电话", "小区", "保安",
                     "监控", "快递", "外卖", "加班", "凌晨", "出租屋"),
        "tone": "冷静、现代、无从逃避，恐怖来自城市里熟悉的设施突然「不对劲」",
        "structure": (
            "开篇就让规则出现（电梯多出一层、监控时间跳帧、楼上传来楼下才有的声音）；"
            "主角用现代常识去解释，每解释一次就更陷一层；"
            "反转揭示这条「怪谈规则」的来历与它挑选人的方式；结局让主角成为规则的一部分或侥幸逃出但被标记。"
        ),
        "must": ("一条可复述的怪谈规则（观众能发给朋友）",
                 "现代设施 / 日常流程中的具体细节（按几楼、几点、几号线）",
                 "规则被违反时的即时后果"),
        "must_not": ("只靠突然出现的怪物", "规则前后矛盾", "主角没有做错事却无缘无故被害（动机要成立）"),
        "horror_devices": ("多出来的一层", "延迟的电话", "被删除的监控片段", "重复的门牌号", "外卖备注"),
        "narration": "旁白像事后复述：时间地点精确，语气越平常越可怕。",
        "dialogue": "对白短、实用，像加班后同事之间的随口闲聊。",
        "ending": "主角暂时安全，但镜头停在「规则还在」的证据上；或主角意识到自己已经成为下一条规则。",
        "voice_style": "urban",
    },
    "sealed": {
        "label": "密室恐怖",
        "keywords": ("密室", "房间", "地下室", "门", "锁", "电梯", "仓库", "手术室",
                     "病房", "被困", "停电"),
        "tone": "压迫、幽闭、物理性的恐惧，空间本身就是反派",
        "structure": (
            "开篇给出「被困」的事实与一个有限资源（剩几小时、一个手电、一扇上锁的门）；"
            "中段每找到一个出口，都发现它通向更深的空间或揭示更多真相；"
            "反转是密室的来历 / 谁造的它；结局必须明确交代是否出去以及代价。"
        ),
        "must": ("空间结构清晰（哪扇门通向哪里）",
                 "资源在不断减少",
                 "至少一次「以为出去了其实没有」的升级"),
        "must_not": ("空间前后矛盾", "出口凭空出现", "完全放弃物理逻辑转而纯说教"),
        "horror_devices": ("会移动的墙", "同一扇门打开通往不同房间", "墙里的声音", "倒计时", "上锁的床位"),
        "narration": "旁白短促，多写身体感受（冷、缺氧、心跳、耳朵里的声音）。",
        "dialogue": "对白紧张、互相指责又互相依赖，能体现人物关系。",
        "ending": "给出明确的离场结果（活着出去 / 没有出去），并让代价可见。",
        "voice_style": "default",
    },
    "mystery": {
        "label": "反转悬疑",
        "keywords": ("悬疑", "反转", "推理", "真相", "失踪", "凶手", "证据", "案子"),
        "tone": "步步紧逼、信息差驱动，恐怖来自「你一直相信的那个人」",
        "structure": (
            "开篇抛出一个看似普通的异常证据；中段按「误判 — 打脸 — 再误判」推进；"
            "反转必须是观众能回看的伏笔（人物外观、物件、某句对白的双重含义）；"
            "结局收束于真相揭晓后的余波，而不是单纯惊吓。"
        ),
        "must": ("反转有伏笔（至少 2 处可回看）",
                 "每个嫌疑人都有明确动机",
                 "主角追查有主动行动，不只是被动承受"),
        "must_not": ("反转靠新增设定 / 新人物", "主角动机缺失", "把凶手留到最后一秒才第一次出现"),
        "horror_devices": ("不该出现的旧照片", "口供里的时间差", "录音里的第二种声音", "被换掉的身份"),
        "narration": "旁白提供线索但不给结论：用疑问句和细节描写制造怀疑。",
        "dialogue": "对白里的每一句话都可以有两种读法。",
        "ending": "真相揭晓后留一个短余味（物证 / 眼神），让观众自己拼最后一块。",
        "voice_style": "urban",
    },
    "loop": {
        "label": "无限循环",
        "keywords": ("循环", "重复", "醒来", "同一天", "时间", "重置", "回到", "每次"),
        "tone": "宿命感、细节差、逐渐绝望",
        "structure": (
            "开篇就用一个「刚刚发生过」的细节建立循环（同一滴水、同一句话）；"
            "中段每次循环都比上一次多知道一点、多失去一点；"
            "反转是循环的发起者 / 代价；结局要么打破循环（付出代价），要么揭示这是永远。"
        ),
        "must": ("循环规则清晰（什么条件下重置、记忆保留还是丢失）",
                 "每次循环之间有可见差异",
                 "主角在循环中做出改变（主动尝试）"),
        "must_not": ("循环没有规则", "重复同样镜头消耗时长", "主角永远被动"),
        "horror_devices": ("同一段对话的不同结尾", "提前出现的伤口", "重复次数刻在墙上", "重复的死法"),
        "narration": "旁白带次数感（第几次、又一次）与疲惫感，越往后越短。",
        "dialogue": "重复的对白在每次循环里有细微变化，观众能听出差别。",
        "ending": "打破循环或证实循环无法打破，两者都必须明确，不能只是画面淡出。",
        "voice_style": "psych",
    },
}

DEFAULT_RULESET = "folk"
RULE_KEYWORDS = ("rule", "规矩", "禁忌", "代价", "循环", "伏笔", "反转", "收束", "钩子")

# ----------------------------------------------------------------------
# 审核用词表（纯词表匹配，宁可宽松：漏判交给模型 rubric）
# ----------------------------------------------------------------------
HOOK_WORDS = ("不对劲", "不对", "异常", "多出", "多了一个", "多出来", "突然", "竟然", "居然",
              "为什么会", "为什么", "谁在", "谁", "什么时候", "看到", "听见", "传来", "出现",
              "不见了", "消失", "重复", "又来", "第几次", "滴答", "响", "敲", "翻动")
ANOMALY_WORDS = ("多出", "多了一个", "多出来", "重复", "同一", "又来", "第二次", "第三次",
                 "不见了", "消失", "不见了", "静止", "动不了", "不属于", "不该", "倒计时")
DANGER_WORDS = ("血", "死", "尸体", "追", "抓住", "锁", "困", "惨叫", "危险", "逃", "断裂",
                "掐", "刀", "撞", "坠落", "烧", "掐住", "逼近", "靠近", "贴着", "伸向")
STRONG_VISUAL_WORDS = ("特写", "一个", "一只", "一只手", "一张脸", "脸", "眼", "影子", "倒影",
                       "门缝", "镜中", "镜头", "对面", "背后", "抬头", "回头")
MOTIVATION_WORDS = ("因为", "为了", "必须", "想要", "希望", "寻找", "救", "找到", "查明",
                    "逃出", "离开", "保护", "揭开", "弄清楚")
CLOSURE_WORDS = ("最后", "终于", "从此", "再也没有", "结束了", "原来", "真相", "代价",
                 "安静下来", "天亮", "消失在", "带走", "留下", "永远", "再也", "明白了",
                 "走了", "关上", "合上", "结束")
REVERSAL_WORDS = ("原来", "其实", "真相", "并不是", "不是他", "竟是", "才发现", "反过来",
                  "反而是", "一直", "从来", "早就", "反转", "假的", "替身", "另一个")
SERIES_HOOK_WORDS = ("下一次", "还会", "接着", "轮到", "新的", "未完", "等着", "再来", "下一个",
                     "还没结束", "继续", "明天")


def detect_ruleset(keywords: str = "", style: str = "") -> str:
    """按关键词匹配最合适的题材规则；匹配不到用默认（中式民俗）。"""
    text = f"{style} {keywords}"
    best, best_score = DEFAULT_RULESET, 0
    for key in RULE_KEYS:
        hits = sum(1 for word in RULESETS[key]["keywords"] if word in text)
        if hits > best_score:
            best, best_score = key, hits
    return best


def get_ruleset(key: str | None) -> dict:
    """取规则集（未知 key 回落到默认），返回值带 key 字段。"""
    rule = dict(RULESETS.get(key or DEFAULT_RULESET, RULESETS[DEFAULT_RULESET]))
    rule["key"] = key if key in RULESETS else DEFAULT_RULESET
    return rule


def all_rulesets() -> list[dict]:
    return [get_ruleset(k) for k in RULE_KEYS]


def ruleset_prompt(rule: dict) -> str:
    """把规则集写成提示词段落。"""
    must = "；".join(rule["must"])
    must_not = "；".join(rule["must_not"])
    devices = "、".join(rule["horror_devices"])
    return (
        f"题材类型：{rule['label']}（{rule['key']}）。\n"
        f"基调：{rule['tone']}。\n"
        f"结构建议：{rule['structure']}\n"
        f"必须做到：{must}。\n"
        f"禁止：{must_not}。\n"
        f"可用恐怖装置：{devices}。\n"
        f"旁白写法：{rule['narration']}\n"
        f"对白写法：{rule['dialogue']}\n"
        f"结局建议：{rule['ending']}"
    )


def count_words(text: str, words) -> list[str]:
    """返回 text 里命中的词（去重、保持词表顺序）。"""
    return [w for w in words if w in (text or "")]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def has_hook(text: str) -> bool:
    """前 3 秒钩子判定：悬念词 / 异常词 / 危险词 / 强视觉词任一命中，
    或者首句以问号结尾。"""
    text = _squash(text)
    if not text:
        return False
    if count_words(text, HOOK_WORDS) or count_words(text, ANOMALY_WORDS) \
            or count_words(text, DANGER_WORDS) or count_words(text, STRONG_VISUAL_WORDS):
        return True
    return "?" in text or "？" in text


def has_motivation(text: str) -> bool:
    return bool(count_words(_squash(text), MOTIVATION_WORDS))


def has_closure(text: str, ending_type: str = "closed") -> bool:
    """结局收束：收束词 / 反转词；系列悬念还接受「下一次」类提示词。"""
    text = _squash(text)
    if count_words(text, CLOSURE_WORDS) or count_words(text, REVERSAL_WORDS):
        return True
    if ending_type == "series":
        return bool(count_words(text, SERIES_HOOK_WORDS))
    return False
