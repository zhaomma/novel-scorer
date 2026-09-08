# -*- coding: utf-8 -*-
"""
segment.py — 文本切分与固定信息机制层

职责：
1. 按句/段切分文本（供复读检测使用）
2. 固定信息机制层（不靠清洗，靠机制钝化）：
   - 重复计数封顶：任意句/短语有效重复次数 ≤ cap
   - 位置加权：独立成行的短句降权（模板行弱化）
   - 数据驱动模板池：行首前缀重复 ≥ threshold 自动降权

设计动机：网文导出文件常含"章节更新时间""第X章 标题"等周期性模板行，
这些行的汉字会进入统计。我们不删除它们，而是通过数学机制让它们
无法主导复读类指标，同时保留正文真实复读的检测能力。
"""

import re
from collections import Counter

# 句子切分：以中文标点/换行切句
_SENT_SPLIT = re.compile(r"[。！？!?…~～]+|\n+|…{2,}|(?<=[”\"'])")
_HANZI_RE = re.compile(r"[\u4e00-\u9fff]")

# 独立成行判定：短行（去除标点后汉字数少）
_TEMPLATE_PREFIX_LEN = 6      # 行首模板判定前缀长度
_TEMPLATE_MIN_HITS = 3        # 前缀出现≥N次视为模板
_LINE_SHORT_HANZI = 15        # 汉字≤15视为短行


def split_sentences(text: str) -> list:
    """将文本切分为句子列表（保留原句，含标点截断）"""
    parts = _SENT_SPLIT.split(text)
    sents = []
    for p in parts:
        s = p.strip()
        if len(_HANZI_RE.findall(s)) >= 4:   # 至少4个汉字才算有效句
            sents.append(s)
    return sents


def split_lines(text: str) -> list:
    """按行切分（保留行文本，用于位置加权/模板池）"""
    return text.split("\n")


class RepetitionGuard:
    """
    复读检测的机制层守卫。

    三层机制：
    1. cap_repeats: 重复计数封顶
    2. line_position_weight: 独立成行短句降权
    3. template_prefix_pool: 数据驱动模板前缀池
    """

    def __init__(self, cap: int = 10, short_hanzi: int = _LINE_SHORT_HANZI,
                 template_min_hits: int = _TEMPLATE_MIN_HITS,
                 prefix_len: int = _TEMPLATE_PREFIX_LEN):
        self.cap = cap
        self.short_hanzi = short_hanzi
        self.template_min_hits = template_min_hits
        self.prefix_len = prefix_len
        self.template_pool = set()
        self.line_info = {}      # 行文本 -> {is_short_line, weight}
        self._built = False

    # ------------------------------------------------------------------
    # 构建阶段：分析文本的行结构，发现模板前缀
    # ------------------------------------------------------------------
    def build(self, text: str):
        """分析文本，建立模板行池与行信息。在评分前调用一次。"""
        lines = split_lines(text)
        # 整行汉字序列完全相同 -> 模板行（如"章节更新时间"出现338次）
        line_hz_counter = Counter()
        line_hz_len = {}
        for ln in lines:
            s = ln.strip()
            hz = "".join(_HANZI_RE.findall(s))
            n = len(hz)
            if n == 0:
                continue
            line_hz_len[s] = n
            line_hz_counter[hz] += 1
        # 模板行集合：整行汉字序列出现 ≥ template_min_hits 的行
        self.template_pool = {
            hz for hz, cnt in line_hz_counter.items()
            if cnt >= self.template_min_hits
        }
        # 行权重：整行模板 or 独立短行 -> 低权重
        self.line_info = {}
        for s, n in line_hz_len.items():
            hz = "".join(_HANZI_RE.findall(s))
            is_template = hz in self.template_pool
            is_short = n <= self.short_hanzi
            if is_template or is_short:
                self.line_info[s] = 0.1
            else:
                self.line_info[s] = 1.0
        self._built = True

    # ------------------------------------------------------------------
    # 应用阶段
    # ------------------------------------------------------------------
    def effective_count(self, count: int) -> int:
        """计数封顶：min(count, cap)"""
        return min(count, self.cap)

    def sentence_weight(self, sent: str) -> float:
        """句子权重：若该句为独立短行/模板行则降权，否则 1.0"""
        if not self._built:
            return 1.0
        s = sent.strip()
        # 在行信息中查（句子通常来自一行；多行句用行首判断）
        if s in self.line_info:
            return self.line_info[s]
        # 近似：短句降权
        if len(_HANZI_RE.findall(s)) <= self.short_hanzi:
            return 0.1
        return 1.0

    def prefix_is_template(self, prefix: str) -> bool:
        return prefix in self.template_pool


# 便捷函数：对句子集合统计复读（应用守卫）
def weighted_sentence_repeat(sents, guard: RepetitionGuard) -> dict:
    """
    计算加权句子复读指标。

    Returns:
        {
          "repeat_ratio": 加权复读率（重复句占比，计封顶与权重）
          "max_repeat":   单句最高有效重复次数
          "repeat_examples": [(句, 原始次数), ...] 复读Top样例
        }
    """
    raw_counter = Counter(sents)
    total_weight = 0.0
    repeat_weight = 0.0
    max_eff = 0
    examples = []
    for sent, raw_cnt in raw_counter.items():
        w = guard.sentence_weight(sent) if guard is not None else 1.0
        eff = guard.effective_count(raw_cnt) if guard is not None else raw_cnt
        total_weight += w
        if raw_cnt >= 2:
            repeat_weight += w * (eff - 1) if eff > 1 else 0
            examples.append((sent, raw_cnt))
        max_eff = max(max_eff, eff)
    examples.sort(key=lambda x: -x[1])
    total_weight = total_weight if total_weight > 0 else 1.0
    return {
        "repeat_ratio": repeat_weight / total_weight,
        "max_repeat": max_eff,
        "repeat_examples": examples[:10],
    }
