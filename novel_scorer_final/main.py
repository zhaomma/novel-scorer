# -*- coding: utf-8 -*-
"""
main.py — 批量评分流水线（CLI）

用法：
    python main.py <文件或目录...> [--mode 默认|三段|十段|全本]
                  [--merge] [--out output/] [--json] [--csv] [--html]

文件名直接用文件名（含扩展名显示），不做书籍信息剥离提取。
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 抑制 jieba 初始化日志（避免污染 stderr / 让 CLI 干净退出）
try:
    import jieba
    jieba.setLogLevel(60)
except Exception:
    pass

from core.textio import read_text_file, sample_text, split_chapters, MODE_LABELS
from core.segment import RepetitionGuard, split_sentences
from core.features import extract_features
from core.scoring import score_d1, score_d2, score_d3, score_d4

GRADE_LEVELS = [
    (90, "S", "顶尖"),
    (80, "A", "优秀"),
    (70, "B", "良好"),
    (60, "C", "中等"),
    (45, "D", "偏弱"),
    (0, "E", "不足"),
]


def grade_for(total):
    for threshold, level, desc in GRADE_LEVELS:
        if total >= threshold:
            return {"level": level, "description": desc}
    return {"level": "E", "description": "不足"}


def _chapter_meta(text: str) -> dict:
    """分析章节结构，供 D3 使用"""
    import re
    chapters = split_chapters(text)
    meta = {"n_chapters": len(chapters)}
    if chapters and len(chapters) <= 500:
        meta["sampled"] = [
            (t, len(re.findall(r"[\u4e00-\u9fff]", b))) for t, b in chapters
        ]
    return meta


def _score_features(features_list, window_size, text=None):
    """对一组窗口特征做四维评分"""
    chapter_meta = _chapter_meta(text) if text else None
    d1 = score_d1(features_list, window_size=window_size)
    d2 = score_d2(features_list)
    d3 = score_d3(features_list, chapter_meta)
    d4 = score_d4(features_list)
    total = round(d1["score"] + d2["score"] + d3["score"] + d4["score"], 2)
    return {
        "dimensions": {"D1_richness": d1, "D2_repetition": d2,
                       "D3_structure": d3, "D4_readability": d4},
        "total_score": total,
        "grade": grade_for(total),
        "top_words": features_list[0]["word"]["top_words"],
        "repeat_examples": d2["examples"],
    }


def score_one_file(path: str, mode: str = "default", merge: bool = False,
                   window: int = None, nodes: int = None,
                   on_progress: callable = None) -> dict:
    """
    对单个文件评分。

    Args:
        on_progress: 可选进度回调，签名为 on_progress(dict)，
            dict 含 stage("load"/"extract"/"score"/"merge"/"done")、
            frac(该文件内 0~1)、file(文件名)。供 GUI 细粒度进度显示。

    Returns: 结果字典（含书名、各维度、总分、等级、指标、样例）
    """
    name = os.path.splitext(os.path.basename(path))[0]

    def _prog(stage, frac, extra=""):
        if on_progress:
            try:
                on_progress({"stage": stage, "frac": frac,
                             "file": os.path.basename(path), "extra": extra})
            except Exception:
                pass

    _prog("load", 0.0)
    text, enc = read_text_file(path, "auto")

    # 固定信息机制层（整行模板池 + 短行降权）
    guard = RepetitionGuard()
    guard.build(text)
    _prog("extract", 0.05)

    # 采样
    wins, meta = sample_text(text, mode=mode, window=window, nodes=nodes)
    if not wins:
        return {"title": name, "error": "no_hanzi", "total_score": 0.0,
                "grade": {"level": "E", "description": "无有效内容"}}

    win_size = meta.get("window_size") or (
        len(wins[0]) if wins else None)

    # 分段评分（每窗口独立特征 → 聚合）
    features_list = []
    n_wins = max(len(wins), 1)
    for i, w in enumerate(wins):
        sents = split_sentences(w)
        features_list.append(extract_features(w, sents=sents, guard=guard))
        _prog("extract", 0.05 + 0.55 * (i + 1) / n_wins)
    _prog("score", 0.85)
    result = _score_features(features_list, win_size, text)

    # 合并评分（所有窗口拼成整体 → 单组特征）——诊断跨段复用
    merged = None
    if merge and len(wins) > 1:
        _prog("merge", 0.9)
        merged_text = "\n".join(wins)
        merged_sents = split_sentences(merged_text)
        merged_feat = extract_features(merged_text, sents=merged_sents, guard=guard)
        # 比较基准写入合并特征数据（每段窗口长度）：D1 从特征自动读取，
        # 使合并分与分段分同锚点基准，差值才纯粹反映跨段复用
        per_win = features_list[0]["char"].get("n_chars", win_size or 0) if features_list else None
        if per_win:
            merged_feat["_anchor_n_chars"] = per_win
        merged = _score_features([merged_feat], win_size, text)
        merged["total_hanzi_merged"] = len(merged_text)
    _prog("done", 1.0)

    # 短文本透明提示：实际窗口 <1 万字时标注"仅供参考"
    flags = []
    wins_hanzi = meta.get("window_hanzi") or []
    min_win = min(wins_hanzi) if wins_hanzi else 0
    if min_win and min_win < 10000:
        flags.append("短文本样本（实际窗口 %d 字），分数仅供参考" % min_win)

    result.update({
        "title": name,
        "filename": os.path.basename(path),
        "encoding": enc,
        "total_hanzi": meta["total_hanzi"],
        "windows": meta["windows"],
        "sampling": meta,
        "merged_score": merged,
        "flags": flags,
    })
    return result


def score_paths(paths, mode="default", merge=False, window=None, nodes=None):
    """对多个路径评分，返回结果列表"""
    files = []
    for p in paths:
        if os.path.isdir(p):
            files.extend(sorted(glob.glob(os.path.join(p, "*.txt"))))
        elif os.path.isfile(p):
            files.append(p)
    results = []
    for f in files:
        try:
            r = score_one_file(f, mode, merge, window, nodes)
            r["file"] = f
            results.append(r)
            print(f"[OK] {r['filename']}  {r['total_score']:.1f} {r['grade']['level']}")
        except Exception as e:
            print(f"[ERR] {f}: {e}")
            results.append({"title": os.path.splitext(os.path.basename(f))[0],
                            "filename": os.path.basename(f), "file": f,
                            "error": str(e), "total_score": 0.0,
                            "grade": {"level": "E", "description": "读取失败"}})
    return results


def to_csv(results, out_path):
    """导出 CSV 汇总"""
    import csv
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        header = ["文件名", "总分", "等级", "D1文笔(40)", "D2复读(25)",
                  "D3结构(20)", "D4可读(15)", "采样模式"]
        if any(r.get("merged_score") for r in results):
            header += ["合并总分"]
        w.writerow(header)
        for r in results:
            d = r.get("dimensions", {})
            row = [
                r.get("filename", ""), r.get("total_score", ""),
                r.get("grade", {}).get("level", ""),
                d.get("D1_richness", {}).get("score", ""),
                d.get("D2_repetition", {}).get("score", ""),
                d.get("D3_structure", {}).get("score", ""),
                d.get("D4_readability", {}).get("score", ""),
                r.get("sampling", {}).get("mode_label", ""),
            ]
            if any(x.get("merged_score") for x in [r]):
                ms = r.get("merged_score")
                row += [ms.get("total_score", "") if ms else ""]
            w.writerow(row)


def to_json(results, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="网文批量评分工具")
    ap.add_argument("paths", nargs="*", help="文件或目录路径")
    ap.add_argument("--gui", action="store_true", help="启动一体操作界面（tkinter）")
    ap.add_argument("--mode", default="default",
                    choices=["default", "three", "ten", "full"],
                    help="采样模式（default默认取头5万/three三段/ten十段/full全本）")
    ap.add_argument("--merge", action="store_true",
                    help="同时计算合并评分（所有窗口拼整体，诊断跨段复用）")
    ap.add_argument("--window", type=int, default=None, help="覆盖窗口字数")
    ap.add_argument("--nodes", type=int, default=None, help="覆盖节点数")
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("--json", action="store_true", help="导出 JSON")
    ap.add_argument("--csv", action="store_true", help="导出 CSV")
    ap.add_argument("--html", action="store_true", help="生成 HTML 报告")
    args = ap.parse_args()

    if args.gui:
        from ui.app import main as gui_main
        return gui_main()

    if not args.paths:
        ap.print_help()
        return 1

    # 启动检查：确保 jieba（缺失则尝试自动安装，失败降级继续）
    from core.health import ensure_jieba, human_report
    print("[环境检查]")
    print(human_report())
    dep = ensure_jieba(auto_install=True)
    if dep["mode"] == "full":
        if "自动安装" in dep["detail"]:
            print("jieba: " + dep["detail"] + " ✓")
    else:
        print("jieba: 缺失且自动安装失败 → 已降级 n-gram 运行")
        print("  原因: " + dep["detail"].replace("\n", "\n  "))
        print("  手动安装: python -m pip install jieba")
    print()

    results = score_paths(args.paths, args.mode, args.merge,
                          args.window, args.nodes)
    if not results:
        return 1

    results.sort(key=lambda r: r.get("total_score", 0), reverse=True)

    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)

    if args.json or args.csv or args.html:
        if args.json:
            to_json(results, os.path.join(out_dir, "results.json"))
        if args.csv:
            to_csv(results, os.path.join(out_dir, "results.csv"))
        if args.html:
            from ui.report import generate_html_report
            html_path = generate_html_report(results, os.path.join(out_dir, "report.html"))
            print(f"HTML 报告: {html_path}")

    print("\n===== 评分汇总（按总分降序）=====")
    for r in results:
        d = r.get("dimensions", {})
        ms = r.get("merged_score")
        extra = f"  合并={ms['total_score']:.1f}" if ms else ""
        print(f"  {r.get('filename','')[:20]:<22} "
              f"{r.get('total_score',0):>6.1f} {r.get('grade',{}).get('level','?')} "
              f"D1={d.get('D1_richness',{}).get('score',0):.1f} "
              f"D2={d.get('D2_repetition',{}).get('score',0):.1f} "
              f"D3={d.get('D3_structure',{}).get('score',0):.1f} "
              f"D4={d.get('D4_readability',{}).get('score',0):.1f}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
