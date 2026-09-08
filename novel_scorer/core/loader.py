# -*- coding: utf-8 -*-
"""
loader.py — 文件读取与编码识别

功能：
1. 多编码自动探测：UTF-8 / UTF-8-SIG / UTF-16(LE/BE 含无BOM) / GBK / GB18030 / Big5
2. 提供 read_text_file() 统一入口

注意：按用户要求，评分流程【不做】书籍信息剥离提取，书名直接使用文件名。
strip_book_header() 保留为可选分析工具，但不参与默认评分流水线。

模块独立性：本文件只依赖标准库，不依赖项目其他模块。
"""
import os
import re

# 常见编码候选（按优先级）
_ENCODINGS = ["utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be",
              "gb18030", "gbk", "big5"]


def _cjk_ratio(text: str) -> float:
    """计算文本中 CJK 汉字占比（0~1）"""
    if not text:
        return 0.0
    hanzi = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return hanzi / len(text)


def _sniff_utf16(raw: bytes):
    """无 BOM 时启发式判断 UTF-16LE/BE"""
    # 统计 0x00 字节位置（UTF-16 的 ASCII/常用字符高字节为 0x00）
    if len(raw) < 4:
        return None
    zero_pos = [i for i, b in enumerate(raw) if b == 0]
    if not zero_pos:
        return None
    even = sum(1 for i in zero_pos if i % 2 == 0)
    odd = sum(1 for i in zero_pos if i % 2 == 1)
    if even == 0 or odd == 0:
        # 全在偶数位 => 低位在奇位（LE：ASCII 低字节在偶，0x00 在奇）
        # 全在奇数位 => LE；全在偶数位 => BE（0x00 在偶，低字节在奇）
        le = (odd > even)
    else:
        # 均匀分布，按解码后 CJK 占比选择
        try:
            r_le = _cjk_ratio(raw.decode("utf-16-le", errors="ignore"))
            r_be = _cjk_ratio(raw.decode("utf-16-be", errors="ignore"))
        except Exception:
            return None
        le = r_le >= r_be
    return "utf-16-le" if le else "utf-16-be"


def detect_encoding(raw: bytes) -> str:
    """
    探测字节流的文本编码。

    Args:
        raw: 文件原始字节

    Returns:
        编码名（Python codec 名）
    """
    if not raw:
        return "utf-8"

    # 1. BOM 检测
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if raw[:2] == b"\xff\xfe":
        return "utf-16"          # LE，带 BOM
    if raw[:2] == b"\xfe\xff":
        return "utf-16-be"       # BE，带 BOM

    # 2. UTF-16 无 BOM 启发式（NUL 字节分布）
    enc16 = _sniff_utf16(raw)
    if enc16:
        return enc16

    # 3. 严格 UTF-8（含汉字占比校验）
    try:
        text = raw.decode("utf-8")
        if _cjk_ratio(text) > 0.05 or len(text) > 0:
            return "utf-8"
    except (UnicodeDecodeError, UnicodeError):
        pass

    # 4. GB18030（GBK 超集，可解码大部分 GB 系）
    try:
        text = raw.decode("gb18030")
        if _cjk_ratio(text) > 0.05:
            return "gb18030"
    except (UnicodeDecodeError, UnicodeError):
        pass

    # 5. Big5
    try:
        text = raw.decode("big5")
        if _cjk_ratio(text) > 0.05:
            return "big5"
    except (UnicodeDecodeError, UnicodeError):
        pass

    # 6. 回退
    return "utf-8"


def read_text_file(path: str, encoding: str = "auto") -> tuple:
    """
    读取文本文件。

    Args:
        path: 文件路径
        encoding: "auto" 自动探测，或指定编码名

    Returns:
        (text, used_encoding)
    """
    with open(path, "rb") as f:
        raw = f.read()

    if encoding == "auto":
        enc = detect_encoding(raw)
    else:
        enc = encoding

    text = raw.decode(enc, errors="replace")
    # utf-8-sig / utf-16 带 BOM 会留下首字符，去掉
    if text and text[0] == "\ufeff":
        text = text[1:]
    return text, enc


# ---------------------------------------------------------------------------
# 书头信息识别（可选分析工具，评分流程默认不调用）
# 按用户要求：不做书籍信息剥离提取，书名直接使用文件名。
# 保留此函数仅为需要时手动分析使用。
# ---------------------------------------------------------------------------
_HEAD_PATTERNS = [
    re.compile(r"^书名[:：]"),
    re.compile(r"^作者[:：]"),
    re.compile(r"^book[_ ]?id[:：]?\s*\d*", re.IGNORECASE),
    re.compile(r"^(连载状态|状态|完结|字数|评分|简介|书籍信息|类型|分类|标签|在读)[:：]?"),
    re.compile(r"^书籍信息$"),
    re.compile(r"^(章节数|章节|书籍 ?[iI][dD]|阅读量|总点击|总推荐|总收藏|总字数)[:：]?\s*\d*"),
    re.compile(r"^(文件大小|更新时间|最近更新|最新章节|上一章|下一章|加入书架|投推荐票)[:：]"),
    re.compile(r"^(作品相关|第一章|第1章).{0,40}$"),  # 若首行即章节，保留但标记
]

_CHAP_PATTERN = re.compile(r"^第[0-9一二三四五六七八九十百千万零两]+[章节回卷部篇集][\s:：、.]?")


def strip_book_header(text: str) -> str:
    """
    剥离文件头部的书头信息行（书名/作者/状态/评分等）。

    策略：只清理文件最开头的连续若干"疑似书头行"，
    遇到正文（长行或章节标题）即停止，避免误删正文。

    Returns:
        剥离书头后的文本
    """
    lines = text.split("\n")
    if not lines:
        return text

    cutoff = None
    for i, ln in enumerate(lines[:40]):   # 最多看前 40 行
        s = ln.strip()
        if not s:
            continue
        # 命中书头关键词行 -> 继续剥离
        if any(p.match(s) for p in _HEAD_PATTERNS):
            cutoff = i + 1
            continue
        # 书头中常见的"第X章"标题（作品相关等开头的标题）也一并剥离，
        # 但普通章节标题视为正文起点，停止剥离
        if _CHAP_PATTERN.match(s):
            break
        # 遇到明显长行（正文）即停止
        if len(s) >= 30:
            break
        # 其他短行且不在书头关键词内，视为正文起点
        break

    if cutoff is None:
        return text
    return "\n".join(lines[cutoff:])
