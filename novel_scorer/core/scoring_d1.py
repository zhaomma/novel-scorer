# -*- coding: utf-8 -*-
"""
scoring_d1.py — D1 语言丰富度（40分）— 重文笔

衡量"文笔储备"：
- 词级 TTR（jieba 分词后的词汇多样性）
- 字级 TTR（基础）
- 句长分布熵（句式多样性）
- 短语丰富度（3-gram 去重率间接）

TTR 对窗口长度敏感（窗口越大 TTR 越低），锚点按**实际窗口汉字数**选组（含短文兼容）：
- short(<1.5万) / 2w(1.5万~3万) / 5w(3万~10万) / full(≥10万)
不考虑跨模式：同模式下窗口长度固定，选对应锚点组即可。

锚点基于 3 篇长网文实测标定（词级 TTR 范围）：
1万字 0.47~0.62；2万字 0.37~0.54；5万字 0.27~0.40；整本50万 0.10~0.16。
"""

from .calibrate import piecewise, zscore_outlier_guard, mean

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
