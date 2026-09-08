# -*- coding: utf-8 -*-
"""
scoring_d3.py — D3 语篇结构度（20分）

衡量"是否成文"：
- 章节完整性与均衡（若提供章节信息）
- 段落长度分布健康度
- 对话密度适中度
"""

from .calibrate import piecewise, zscore_outlier_guard, mean


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
            import statistics
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
