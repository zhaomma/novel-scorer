# -*- coding: utf-8 -*-
"""
sampler.py — 多模式采样

采样模式（GUI 选项：默认 / 三段 / 十段 / 全本）：
    "default"  默认：去首尾千字符后，取头 5 万字（单窗口）
    "three"    三段：去首尾千字符后，正文均分 3 节点，每节点取 2 万字窗口
    "ten"      十段：去首尾千字符后，正文均分 10 节点，每节点取 2 万字窗口
    "full"     全本：整本作为单个窗口（不裁剪，适合短文本）

去首尾：除 full 外，固定去掉原文开头/结尾各 EDGE_TRIM_CHARS 个【字符】（含标点/空白）。
条件：若流程改为"先行洗过文本"（如先抽纯汉字），则改用 EDGE_TRIM_HANZI 个汉字（见 _trim_edges 参数）。

窗口统一 2 万字（three/ten），默认 5 万字，full 整本。
短文本保护：节点窗口不重叠、不重复——正文不足 N×2 万时自动减少节点数到 min(N, 正文//2万)（至少 1）。

窗口输出保留标点（raw 原文），供句级/段落级切分；调用方用 extract_hanzi 取纯汉字做字级统计。
"""

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
