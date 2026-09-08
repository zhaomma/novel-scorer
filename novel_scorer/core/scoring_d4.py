# -*- coding: utf-8 -*-
"""
scoring_d4.py — D4 可读性（15分）

衡量"读起来顺不顺"：
- 句长健康：平均句长适中、超长句少、过碎句少
- 高频字异常：Simpson 集中度（过度堆砌某字预警）
- 生僻字/特殊符号适度
"""

from .calibrate import piecewise, zscore_outlier_guard, mean


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
