# -*- coding: utf-8 -*-
"""
calibrate.py — 归一化与校准工具

评分原则：每个原始指标先映射到 0~1 的"质量分"，再用分项权重加权。
映射采用分段线性插值，锚点来自样本库校准（calibration.json）。

本文件提供：
- sigmoid 风格软阈值映射
- 分段线性映射（锚点驱动）
- 多个窗口特征的稳健聚合（中位数优先，防异常窗口主导）
"""

import statistics


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
