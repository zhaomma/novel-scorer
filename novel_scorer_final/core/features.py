# -*- coding: utf-8 -*-
"""
features.py — 多尺度特征提取

对采样窗口提取评分所需的全部原始特征：
- 字级：字符数、不同字数、TTR
- 词级：jieba 分词后的 TTR / 高频词集中度（若 jieba 不可用降级 n-gram）
- 短语级：2/3/4-gram 覆盖率
- 句级：句长分布、复读（配合 RepetitionGuard）
- 窗口级：滑窗复读峰值
- 语篇级：段落长分布、对话占比

输出为纯字典（原始值），评分模块负责打分。
"""

import re
import math
from collections import Counter

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

_HANZI_RE = re.compile(r"[\u4e00-\u9fff]")
_COMMON_PUNCT = "，。！？；：、""''（）《》【】—…·"


def hanzi_count(text: str) -> int:
    return len(_HANZI_RE.findall(text))


# ---------------------------------------------------------------------------
# 字级 / 词级
# ---------------------------------------------------------------------------
def char_stats(text: str) -> dict:
    """字级统计"""
    chars = _HANZI_RE.findall(text)
    n = len(chars)
    c = Counter(chars)
    v = len(c)
    return {
        "n_chars": n,
        "v_chars": v,
        "ttr": v / n if n else 0.0,
        "simpson": sum(x * x for x in c.values()) / (n * n) if n else 0.0,
        "top1_ratio": (c.most_common(1)[0][1] / n) if n else 0.0,
        "top1_char": c.most_common(1)[0][0] if c else "",
    }


def _check_jieba():
    """jieba 动态可用性重检：启动时缺失但随后被自动安装成功时可切回完整模式"""
    global _HAS_JIEBA
    if not _HAS_JIEBA:
        try:
            import jieba  # noqa: F401
            _HAS_JIEBA = True
        except Exception:
            pass


def _tokenize(text: str) -> list:
    """分词：jieba 可用则用，否则 n-gram 近似"""
    _check_jieba()
    if _HAS_JIEBA:
        words = [w for w in jieba.lcut(text) if len(w) >= 2]
        return words
    # 降级：2-gram
    chars = _HANZI_RE.findall(text)
    return ["".join(chars[i:i + 2]) for i in range(len(chars) - 1)]


def word_stats(text: str) -> dict:
    """词级统计（去停用高频虚词）"""
    words = _tokenize(text)
    if not words:
        return {"n_words": 0, "v_words": 0, "ttr": 0.0,
                "top10_ratio": 0.0, "top20_ratio": 0.0}
    c = Counter(words)
    n = len(words)
    v = len(c)
    top10 = sum(v for _, v in c.most_common(10))
    top20 = sum(v for _, v in c.most_common(20))
    return {
        "n_words": n,
        "v_words": v,
        "ttr": v / n if n else 0.0,
        "top10_ratio": top10 / n if n else 0.0,
        "top20_ratio": top20 / n if n else 0.0,
        "max_word_ratio": c.most_common(1)[0][1] / n if n else 0.0,
        "top_words": [w for w, _ in c.most_common(10)],
    }


# ---------------------------------------------------------------------------
# 短语级 n-gram
# ---------------------------------------------------------------------------
def ngram_coverage(text: str, n: int = 3, top_k: int = 10) -> dict:
    """n-gram 覆盖率"""
    chars = _HANZI_RE.findall(text)
    if len(chars) < n:
        return {"coverage_top10": 0.0, "distinct": 0}
    grams = ["".join(chars[i:i + n]) for i in range(len(chars) - n + 1)]
    c = Counter(grams)
    total = len(grams)
    topk = sum(v for _, v in c.most_common(top_k))
    return {
        "coverage_top10": topk / total if total else 0.0,
        "distinct": len(c),
    }


# ---------------------------------------------------------------------------
# 句级
# ---------------------------------------------------------------------------
def sentence_stats(sents) -> dict:
    """句长分布统计"""
    if not sents:
        return {"mean_len": 0.0, "median_len": 0.0, "p95_len": 0.0,
                "long_ratio": 0.0, "short_ratio": 0.0, "entropy": 0.0}
    lens = [hanzi_count(s) for s in sents]
    lens.sort()
    n = len(lens)
    mean = sum(lens) / n
    median = lens[n // 2]
    p95 = lens[int(n * 0.95) - 1] if n > 1 else lens[-1]
    long_ratio = sum(1 for x in lens if x > 60) / n
    short_ratio = sum(1 for x in lens if x < 6) / n
    # 句长分布熵（量化句式多样性）
    buckets = Counter(min(x // 5, 20) for x in lens)
    total = n
    entropy = -sum((cnt / total) * math.log(cnt / total) for cnt in buckets.values())
    return {
        "mean_len": mean,
        "median_len": median,
        "p95_len": p95,
        "long_ratio": long_ratio,
        "short_ratio": short_ratio,
        "entropy": entropy,
    }


# ---------------------------------------------------------------------------
# 窗口级：滑窗复读峰值
# ---------------------------------------------------------------------------
def sliding_peak(text: str, win: int = 5000, step: int = 2500,
                  ngram_n: int = 4) -> dict:
    """滑窗 n-gram 峰值复读：抓局部灌水"""
    chars = _HANZI_RE.findall(text)
    total = len(chars)
    if total < win:
        win = total
    peak = 0
    peak_pos = 0
    for start in range(0, max(1, total - win + 1), step):
        seg = chars[start:start + win]
        if len(seg) < ngram_n:
            continue
        grams = ["".join(seg[i:i + ngram_n]) for i in range(len(seg) - ngram_n + 1)]
        c = Counter(grams)
        _g, cnt = c.most_common(1)[0]
        if cnt > peak:
            peak = cnt
            peak_pos = start
    return {"peak": peak, "peak_pos": peak_pos, "n_windows": max(1, (total - win) // step + 1)}


# ---------------------------------------------------------------------------
# 语篇级
# ---------------------------------------------------------------------------
def paragraph_stats(text: str) -> dict:
    """段落长度分布（按换行分段的汉字长度）"""
    paras = []
    for line in text.split("\n"):
        n = hanzi_count(line)
        if n > 0:
            paras.append(n)
    if not paras:
        return {"n_paras": 0, "mean": 0.0, "median": 0.0,
                "p95": 0.0, "overlong_ratio": 0.0}
    paras.sort()
    n = len(paras)
    mean = sum(paras) / n
    median = paras[n // 2]
    p95 = paras[int(n * 0.95) - 1]
    overlong = sum(1 for x in paras if x > 200) / n
    return {"n_paras": n, "mean": mean, "median": median,
            "p95": p95, "overlong_ratio": overlong}


def dialogue_ratio(text: str) -> dict:
    """对话占比：引号行占比"""
    lines = text.split("\n")
    total = 0
    dlg = 0
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        total += 1
        if "“" in s or "”" in s or '"' in s:
            dlg += 1
    return {"dialogue_line_ratio": dlg / total if total else 0.0}


# ---------------------------------------------------------------------------
# 顶层聚合
# ---------------------------------------------------------------------------
def extract_features(raw_text: str, sents=None, guard=None) -> dict:
    """
    对一段文本提取全部特征。

    Args:
        raw_text: 原始窗口文本（含标点，供句/段切分）
        sents: 预切分的句子列表（可选，避免重复切分）
        guard: RepetitionGuard 实例（可选，用于加权复读）

    Returns:
        特征字典
    """
    hz = "".join(_HANZI_RE.findall(raw_text))
    features = {}
    features["char"] = char_stats(hz)
    features["word"] = word_stats(hz)
    features["ngram2"] = ngram_coverage(hz, 2, 10)
    features["ngram3"] = ngram_coverage(hz, 3, 10)
    features["ngram4"] = ngram_coverage(hz, 4, 10)
    features["window"] = sliding_peak(hz)

    if sents is None:
        from .segment import split_sentences
        sents = split_sentences(raw_text)
    features["sentence"] = sentence_stats(sents)

    # 复读（加权/不加权），在句子上工作
    from .segment import weighted_sentence_repeat
    features["repeat_plain"] = weighted_sentence_repeat(sents, None)
    features["repeat_guarded"] = weighted_sentence_repeat(sents, guard)

    features["paragraph"] = paragraph_stats(raw_text)
    features["dialogue"] = dialogue_ratio(raw_text)
    return features
