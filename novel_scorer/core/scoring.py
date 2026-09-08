# -*- coding: utf-8 -*-
"""
scoring.py — 四维评分与校准工具（合并自原 calibrate.py + scoring_d1~d4.py）

评分原则：每个原始指标先映射到 0~1 的"质量分"，再用分项权重加权。
映射采用分段线性插值，锚点来自长网文样本实测标定。

四维：
    D1 语言丰富度（40）— 重文笔：词/字 TTR、句长熵、短语丰富度
    D2 表达复读度（25）— 复读/注水：句加权复读、窗峰、词集中度
    D3 语篇结构度（20）— 段落、对话、章节均衡
    D4 可读性   （15）— 句长、集中度异常

TTR 锚点按实际窗口汉字数分档（短文兼容）：
    short(<1.5万) / 2w(1.5万~3万) / 5w(3万~10万) / full(≥10万)
锚点基于 3 篇长网文实测标定（词级 TTR：1万字 0.47~0.62；2万 0.37~0.54；
5万 0.27~0.40；整本50万 0.10~0.16）。
"""

import statistics

# ===========================================================================
# 一、校准工具（原 calibrate.py）
# ===========================================================================

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def piecewise(x, anchors):
    """
    分段线性映射。

    Args:
        x: 原始值
        anchors: [(x0, y0), (x1, y1), ...] 升序，x 超出范围取端点 y

    Returns:
        y (0~1)
    """
    if not anchors:
        return 0.0
    pts = sorted(anchors, key=lambda p: p[0])
    if x <= pts[0][0]:
        return clamp(pts[0][1])
    if x >= pts[-1][0]:
        return clamp(pts[-1][1])
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return clamp(y1)
            t = (x - x0) / (x1 - x0)
            return clamp(y0 + t * (y1 - y0))
    return clamp(pts[-1][1])


def zscore_outlier_guard(values, k=3.0):
    """
    稳健聚合：剔除异常窗口（中位数±k*MAD），返回中位数。
    防止个别污染窗口（如某窗口含大量固定信息）主导整篇结果。
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values]) or 1e-9
    good = [v for v in values if abs(v - med) <= k * 1.4826 * mad]
    return statistics.median(good) if good else med


def mean(values):
    return sum(values) / len(values) if values else 0.0


def median(values):
    return statistics.median(values) if values else 0.0


# ===========================================================================
# 二、D1 语言丰富度（40分）
# ===========================================================================

# 各窗口长度的词级 TTR 锚点（实测标定）
_WORD_TTR_ANCHORS = {
    "short": [(0.42, 0.0), (0.52, 0.45), (0.64, 0.85), (0.74, 1.0)],
    "2w":    [(0.20, 0.0), (0.32, 0.35), (0.48, 0.8), (0.60, 1.0)],
    "5w":    [(0.15, 0.0), (0.24, 0.35), (0.36, 0.8), (0.46, 1.0)],
    "full":  [(0.06, 0.0), (0.10, 0.4),  (0.14, 0.8), (0.18, 1.0)],
}

# 字级 TTR 锚点（实测：1万字 0.112~0.147；2万 0.075~0.092；5万 0.037~0.046；整本≈0.0055）
_CHAR_TTR_ANCHORS = {
    "short": [(0.085, 0.0), (0.115, 0.45), (0.145, 0.85), (0.18, 1.0)],
    "2w":    [(0.04, 0.0), (0.065, 0.4), (0.085, 0.8), (0.10, 1.0)],
    "5w":    [(0.025, 0.0), (0.036, 0.4), (0.045, 0.8), (0.055, 1.0)],
    "full":  [(0.0035, 0.0), (0.0050, 0.5), (0.0060, 0.9), (0.0070, 1.0)],
}

# n-gram 覆盖率锚点（覆盖率越低越丰富）
_NGRAM3_ANCHORS = {
    "short": [(0.010, 1.0), (0.020, 0.7), (0.035, 0.3), (0.05, 0.0)],
    "2w":    [(0.010, 1.0), (0.020, 0.7), (0.035, 0.3), (0.05, 0.0)],
    "5w":    [(0.010, 1.0), (0.020, 0.7), (0.035, 0.3), (0.05, 0.0)],
    "full":  [(0.010, 1.0), (0.020, 0.7), (0.035, 0.3), (0.05, 0.0)],
}


def _anchor_group(n_chars):
    """按实际窗口汉字数选锚点组（短文兼容）"""
    if n_chars is None or n_chars <= 0:
        return "2w"
    if n_chars >= 100000:
        return "full"
    if n_chars >= 30000:
        return "5w"
    if n_chars >= 15000:
        return "2w"
    return "short"


def score_d1(features_list, window_size=None) -> dict:
    """
    features_list: 各采样窗口的 features 字典列表。

    锚点长度**直接读特征数据**，无需外部告知：
    - 正常评分：读窗口自身 char.n_chars（实际汉字数），字数本来就是特征的一部分
    - 合并评分：读合并特征携带的 "_anchor_n_chars"（比较基准=每段窗口长度），
      使合并分与分段分用同一锚点基准，"合并分<分段分"才纯粹反映跨段复用
    window_size: 仅特征缺失时的兜底参考
    """
    if features_list:
        n_chars = (features_list[0].get("_anchor_n_chars")
                   or features_list[0]["char"].get("n_chars", 0))
    else:
        n_chars = window_size or 0
    group = _anchor_group(n_chars)
    w_anchors = _WORD_TTR_ANCHORS[group]
    c_anchors = _CHAR_TTR_ANCHORS[group]
    n3_anchors = _NGRAM3_ANCHORS[group]

    # --- 子项1：词级 TTR（20分）---
    word_ttrs = [f["word"]["ttr"] for f in features_list if f["word"]["n_words"] > 0]
    w_ttr_agg = zscore_outlier_guard(word_ttrs) if word_ttrs else 0.0
    s_word = piecewise(w_ttr_agg, w_anchors) * 20

    # --- 子项2：字级 TTR（10分）---
    char_ttrs = [f["char"]["ttr"] for f in features_list]
    c_ttr = zscore_outlier_guard(char_ttrs)
    s_char = piecewise(c_ttr, c_anchors) * 10

    # --- 子项3：句长分布熵（6分）---
    ents = [f["sentence"]["entropy"] for f in features_list]
    ent = mean(ents)
    s_ent = piecewise(ent, [(1.2, 0.0), (1.7, 0.5), (2.2, 0.9), (2.7, 1.0)]) * 6

    # --- 子项4：短语丰富度（4分）---
    n3s = [f["ngram3"]["coverage_top10"] for f in features_list]
    n3 = zscore_outlier_guard(n3s)
    s_ng = piecewise(n3, n3_anchors) * 4

    total = round(s_word + s_char + s_ent + s_ng, 2)
    return {
        "score": total,
        "max": 40,
        "group": group,
        "subs": {
            "word_ttr": round(s_word, 2),
            "char_ttr": round(s_char, 2),
            "sent_entropy": round(s_ent, 2),
            "ngram_rich": round(s_ng, 2),
        },
        "metrics": {
            "word_ttr": round(w_ttr_agg, 4),
            "char_ttr": round(c_ttr, 4),
            "sentence_entropy": round(ent, 3),
            "ngram3_top10": round(n3, 4),
        },
    }


# ===========================================================================
# 三、D2 表达复读度（25分）
# ===========================================================================

def score_d2(features_list) -> dict:
    # --- 子项1：句级加权复读率（12分）---
    # 使用 guard 加权后的复读率（已钝化固定信息）
    rrs = [f["repeat_guarded"]["repeat_ratio"] for f in features_list]
    rr = zscore_outlier_guard(rrs)
    # 加权复读率越低越好；锚点 0.001=优秀, 0.02=较差
    s_sent = piecewise(rr, [(0.0, 1.0), (0.003, 0.85), (0.010, 0.5), (0.025, 0.0)]) * 12

    # --- 子项2：窗口复读峰值（7分）---
    peaks = [f["window"]["peak"] for f in features_list]
    peak = zscore_outlier_guard(peaks)
    # 峰值越小越好；4-gram 峰值 >20 提示局部灌水
    s_peak = piecewise(peak, [(0, 1.0), (10, 0.9), (20, 0.6), (40, 0.2), (80, 0.0)]) * 7

    # --- 子项3：词级高频集中度（6分）---
    tops = [f["word"]["top10_ratio"] for f in features_list]
    top = zscore_outlier_guard(tops)
    # top10词覆盖率越低越不重复
    s_top = piecewise(top, [(0.05, 1.0), (0.12, 0.85), (0.25, 0.5), (0.40, 0.0)]) * 6

    total = round(s_sent + s_peak + s_top, 2)
    return {
        "score": total,
        "max": 25,
        "subs": {
            "sent_repeat": round(s_sent, 2),
            "window_peak": round(s_peak, 2),
            "word_conc": round(s_top, 2),
        },
        "metrics": {
            "guarded_repeat_ratio": round(rr, 4),
            "window_peak": round(peak, 1),
            "word_top10": round(top, 4),
        },
        "examples": _collect_examples(features_list),
    }


def _collect_examples(features_list) -> list:
    """收集复读样例（供 UI 展示）"""
    seen = []
    for f in features_list:
        for s, c in f["repeat_guarded"]["repeat_examples"][:5]:
            seen.append({"text": s[:40], "count": c})
    # 去重
    out, keys = [], set()
    for item in seen:
        if item["text"] not in keys:
            keys.add(item["text"])
            out.append(item)
    return out[:10]


# ===========================================================================
# 四、D3 语篇结构度（20分）
# ===========================================================================

def score_d3(features_list, chapter_meta=None) -> dict:
    # --- 子项1：段落健康度（8分）---
    # 段落中位数适中、超长段不过多
    meds = [f["paragraph"]["median"] for f in features_list]
    med = zscore_outlier_guard(meds)
    overlongs = [f["paragraph"]["overlong_ratio"] for f in features_list]
    overlong = zscore_outlier_guard(overlongs)
    # 段落中位数 10~40 字为健康
    s_para = piecewise(med, [(5, 0.4), (12, 0.9), (30, 1.0), (60, 0.5), (100, 0.0)])
    # 超长段(>200字)占比越低越好
    s_over = piecewise(overlong, [(0.0, 1.0), (0.03, 0.8), (0.10, 0.4), (0.2, 0.0)])
    s_para_score = (s_para * 0.6 + s_over * 0.4) * 8

    # --- 子项2：对话密度（6分）---
    dlgs = [f["dialogue"]["dialogue_line_ratio"] for f in features_list]
    dlg = zscore_outlier_guard(dlgs)
    # 网文对话行占比 25%~50% 为常态，偏离过远预警
    if dlg <= 0.15:
        s_dlg = piecewise(dlg, [(0.0, 0.3), (0.10, 0.7), (0.15, 1.0)])
    elif dlg <= 0.55:
        s_dlg = 1.0
    else:
        s_dlg = piecewise(dlg, [(0.55, 1.0), (0.70, 0.5), (0.9, 0.0)])
    s_dlg_score = s_dlg * 6

    # --- 子项3：章节均衡度（6分，仅当有章节信息）---
    s_chap_score = 6.0
    chap_detail = None
    if chapter_meta and chapter_meta.get("n_chapters", 0) >= 2:
        lens = [c for _, c in chapter_meta.get("sampled", [])]
        if lens:
            med_ch = statistics.median(lens)
            # 章节汉字量适中（1000~5000）为健康
            s_chap = piecewise(med_ch, [(200, 0.2), (800, 0.7), (1500, 0.95),
                                        (4000, 1.0), (8000, 0.6), (15000, 0.0)])
            s_chap_score = s_chap * 6
            chap_detail = {
                "n_chapters": chapter_meta["n_chapters"],
                "sampled_chapter_lens": lens,
            }
    else:
        # 无章节信息：给出中性分（不因无法判断而重罚）
        s_chap_score = 4.0

    total = round(s_para_score + s_dlg_score + s_chap_score, 2)
    return {
        "score": total,
        "max": 20,
        "subs": {
            "paragraph": round(s_para_score, 2),
            "dialogue": round(s_dlg_score, 2),
            "chapter": round(s_chap_score, 2),
        },
        "metrics": {
            "para_median": round(med, 1),
            "overlong_ratio": round(overlong, 4),
            "dialogue_ratio": round(dlg, 4),
        },
        "chapter_detail": chap_detail,
    }


# ===========================================================================
# 五、D4 可读性（15分）
# ===========================================================================

def score_d4(features_list) -> dict:
    # --- 子项1：句长健康度（8分）---
    means = [f["sentence"]["mean_len"] for f in features_list]
    m = zscore_outlier_guard(means)
    longs = [f["sentence"]["long_ratio"] for f in features_list]
    long_r = zscore_outlier_guard(longs)
    shorts = [f["sentence"]["short_ratio"] for f in features_list]
    short_r = zscore_outlier_guard(shorts)
    # 平均句长 8~25 字为健康；过长/过碎均扣
    s_mean = piecewise(m, [(5, 0.4), (10, 0.85), (18, 1.0), (30, 0.6), (45, 0.0)])
    # 超长句(>60字)占比越低越好
    s_long = piecewise(long_r, [(0.0, 1.0), (0.03, 0.85), (0.08, 0.5), (0.15, 0.0)])
    # 过碎句(<6字)占比适中（网文对话多，允许一定比例）
    s_short = piecewise(short_r, [(0.0, 0.7), (0.08, 1.0), (0.2, 0.8), (0.35, 0.3), (0.5, 0.0)])
    s_len = (s_mean * 0.5 + s_long * 0.3 + s_short * 0.2) * 8

    # --- 子项2：集中度异常（4分）---
    simpsons = [f["char"]["simpson"] for f in features_list]
    sim = zscore_outlier_guard(simpsons)
    # Simpson 过大 => 单字过度集中
    s_sim = piecewise(sim, [(0.0, 1.0), (0.005, 0.9), (0.01, 0.6), (0.02, 0.2), (0.04, 0.0)]) * 4

    # --- 子项3：特殊符号/噪声（3分）---
    # 用 ngram distinct 比例近似文本噪音（窗口内符号越多 distinct 越异常不在此体现）
    # 简化：以窗口峰值合理性兜底，给基础分
    s_noise = 3.0

    total = round(s_len + s_sim + s_noise, 2)
    return {
        "score": total,
        "max": 15,
        "subs": {
            "sentence_len": round(s_len, 2),
            "concentration": round(s_sim, 2),
            "noise": round(s_noise, 2),
        },
        "metrics": {
            "mean_sent_len": round(m, 2),
            "long_ratio": round(long_r, 4),
            "short_ratio": round(short_r, 4),
            "simpson": round(sim, 5),
        },
    }
