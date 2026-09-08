# -*- coding: utf-8 -*-
"""
textio.py — 文本读取与采样（合并自原 loader.py + sampler.py）

职责：
1. 多编码自动探测读取：UTF-8 / UTF-8-SIG / UTF-16(LE/BE 含无BOM) / GBK / GB18030 / Big5
2. 多模式采样（默认 / 三段 / 十段 / 全本），窗口不重叠、短文自动兜底
3. 可选书头剥离工具（评分流程不调用，书名直接使用文件名）

采样模式（GUI 选项：默认 / 三段 / 十段 / 全本）：
    "default"  默认：去首尾千字符后，取头 5 万字（单窗口）
    "three"    三段：去首尾千字符后，正文均分 3 节点，每节点取 2 万字窗口
    "ten"      十段：去首尾千字符后，正文均分 10 节点，每节点取 2 万字窗口
    "full"     全本：整本作为单个窗口（不裁剪，适合短文本）

去首尾：除 full 外，固定去掉原文开头/结尾各 EDGE_TRIM_CHARS 个【字符】（含标点/空白）。
条件：若流程改为"先行洗过文本"（如先抽纯汉字），则改用 EDGE_TRIM_HANZI 个汉字（见 _trim_edges 参数）。

窗口统一 2 万字（three/ten），默认 5 万字，full 整本。
短文本保护：窗口互不重叠、不重复——正文不足 N×2 万时自动减少节点数到 k=min(N, 正文汉字数//窗口)（至少 1）。

窗口输出保留标点（raw 原文），供句级/段落级切分；调用方用 extract_hanzi 取纯汉字做字级统计。
"""

import os
import re

_HANZI_RE = re.compile(r"[\u4e00-\u9fff]")

# 除全本外，首尾各去掉的【字符】数（当前流程未清洗 → 按字符计）
EDGE_TRIM_CHARS = 1000
# 若流程改为"先行洗过文本"（已抽纯汉字/去标点）时使用的汉字数
EDGE_TRIM_HANZI = 200

# 各模式默认窗口字数与节点数
MODE_DEFAULTS = {
    "default": {"window": 50000, "nodes": 1},
    "three":   {"window": 20000, "nodes": 3},
    "ten":     {"window": 20000, "nodes": 10},
    "full":    {"window": None,   "nodes": 1},
}

# GUI/报告中文显示名
MODE_LABELS = {
    "default": "默认",
    "three": "三段",
    "ten": "十段",
    "full": "全本",
}

# ===========================================================================
# 一、读取与编码识别
# ===========================================================================

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


# ===========================================================================
# 二、采样
# ===========================================================================

def extract_hanzi(text: str) -> str:
    """仅保留汉字"""
    return "".join(_HANZI_RE.findall(text))


def _raw_windows_from_positions(text: str, positions, window: int) -> list:
    """按汉字起始位置抽取原始窗口（含标点）"""
    raw_windows = []
    total_hz = len(_HANZI_RE.findall(text))
    hz_pos = []
    for i, ch in enumerate(text):
        if _HANZI_RE.match(ch):
            hz_pos.append(i)
    if not hz_pos:
        return []
    for start_hz_idx in positions:
        if start_hz_idx >= total_hz:
            continue
        s = hz_pos[start_hz_idx]
        end_hz_idx = min(start_hz_idx + window, total_hz)
        e = hz_pos[end_hz_idx - 1] + 1 if end_hz_idx > start_hz_idx else s + 1
        seg = text[s:e]
        if len(_HANZI_RE.findall(seg)) >= window * 0.3:
            raw_windows.append(seg)
    return raw_windows


def _trim_edges(text: str) -> str:
    """
    去掉首尾固定量。
    当前流程未先行清洗 → 按【字符】计 EDGE_TRIM_CHARS=1000。
    若流程改为先行洗过文本，改用汉字数 EDGE_TRIM_HANZI=200：
        trim_n = EDGE_TRIM_HANZI  # 需定位第 n 个汉字
    """
    n = EDGE_TRIM_CHARS  # 按字符切片
    if len(text) <= n * 2 + 1:
        return text
    return text[n:-n]


def _uniform_positions(total_hz: int, nodes: int, window: int) -> list:
    """
    在正文上取 nodes 个窗口起点，保证**窗口互不重叠、不重复**：
    - 正文不足一个窗口（total_hz <= window）：返回 [0]（单窗口=全文起点，窗口自然截短）
    - 否则自动减节点到 k = min(nodes, total_hz // window)（不重叠窗口上限，至少 1）
    - k 个起点在 [0, total_hz-window] 均匀分布；因 k <= total_hz//window，
      相邻间距 = (total_hz-window)/(k-1) >= window，故窗口互不重叠
    """
    if total_hz <= 0 or nodes <= 0:
        return []
    if total_hz <= window or nodes == 1:
        return [0]
    k = min(nodes, total_hz // window)
    if k <= 1:
        return [0]
    span = max(1, total_hz - window)
    step = span / (k - 1)
    return [int(step * i) for i in range(k)]


def _sample_nodes(text: str, nodes: int, window: int) -> list:
    """去首尾 → 均分节点 → 每节点取 window 字窗口"""
    body = _trim_edges(text)
    total_hz = len(extract_hanzi(body))
    positions = _uniform_positions(total_hz, nodes, window)
    wins = _raw_windows_from_positions(body, positions, window)
    if not wins:
        if extract_hanzi(body):
            wins = [body]
    return wins


def sample_default(text: str, window: int = 50000) -> list:
    """默认：去首尾千字符后取头 window 字（单窗口）"""
    body = _trim_edges(text)
    wins = _raw_windows_from_positions(body, [0], window)
    if not wins and extract_hanzi(body):
        wins = [body]
    return wins


def sample_three(text: str, window: int = 20000, nodes: int = 3) -> list:
    """三段：去首尾千字符后，正文均分 nodes 节点，每节点取 window 字"""
    return _sample_nodes(text, nodes, window)


def sample_ten(text: str, window: int = 20000, nodes: int = 10) -> list:
    """十段：去首尾千字符后，正文均分 nodes 节点，每节点取 window 字"""
    return _sample_nodes(text, nodes, window)


def sample_full(text: str) -> list:
    """全本：整本作为单个窗口"""
    return [text] if extract_hanzi(text) else []


def split_chapters(text: str) -> list:
    """按章节标题切分（返回 [(标题, 正文)] 列表）"""
    chap_re = re.compile(r"第[0-9一二三四五六七八九十百千万零两]+[章节回卷部篇集]")
    lines = text.split("\n")
    chapters = []
    cur_title = "(序章)"
    cur_body = []
    for ln in lines:
        s = ln.strip()
        if chap_re.match(s):
            if cur_body:
                chapters.append((cur_title, "\n".join(cur_body)))
            cur_title = s
            cur_body = []
        else:
            cur_body.append(ln)
    if cur_body:
        chapters.append((cur_title, "\n".join(cur_body)))
    return chapters


def sample_text(text: str, mode: str = "default", window: int = None,
                nodes: int = None) -> tuple:
    """
    统一采样入口。

    Args:
        text: 原始全文
        mode: "default" / "three" / "ten" / "full"
        window: 可选覆盖窗口字数（None 用模式默认）
        nodes: 可选覆盖节点数（None 用模式默认）

    Returns:
        (raw_windows, meta)
    """
    if mode not in MODE_DEFAULTS:
        raise ValueError(f"未知采样模式: {mode}（可选 default/three/ten/full）")

    d = MODE_DEFAULTS[mode]
    win = window or d["window"]
    nd = nodes or d["nodes"]

    if mode == "full":
        wins = sample_full(text)
    elif mode == "default":
        wins = sample_default(text, win)
    elif mode == "three":
        wins = sample_three(text, win, nd)
    elif mode == "ten":
        wins = sample_ten(text, win, nd)

    meta = {
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "total_hanzi": len(extract_hanzi(text)),
        "window_size": win,
        "nodes": nd,
        "edge_trim_chars": 0 if mode == "full" else EDGE_TRIM_CHARS,
        "windows": 0,
    }
    meta["windows"] = len(wins)
    meta["window_hanzi"] = [len(extract_hanzi(w)) for w in wins]
    return wins, meta


# ===========================================================================
# 三、书头信息识别（可选分析工具，评分流程默认不调用）
# 按用户要求：不做书籍信息剥离提取，书名直接使用文件名。
# 保留此函数仅为需要时手动分析使用。
# ===========================================================================
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
