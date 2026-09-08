# -*- coding: utf-8 -*-
"""
scoring_d2.py — D2 表达复读度（25分）— 复读/注水检测

核心：区分"固定信息模板行"与"正文真实复读"。
机制（在 segment.RepetitionGuard 已实现）：
- 整行模板池（数据驱动发现"章节更新时间"等重复行）
- 独立短行降权
- 重复计数封顶

本模块聚合：
- 句级加权复读率
- 窗口级复读峰值（局部灌水）
- 词级高频集中度
- 段级大段复制（近似）
"""

from .calibrate import piecewise, zscore_outlier_guard, mean


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
