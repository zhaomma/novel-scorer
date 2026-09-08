# -*- coding: utf-8 -*-
"""
ui/app.py — 一体操作界面（tkinter 本地桌面应用，零服务依赖）

功能（一体完成）：
1. 选择/添加待评分文件（支持多选、目录导入、单独移除选中）
2. 配置评分参数（采样模式【默认/三段/十段/全本】、合并评分开关）
3. 一键批量评分：进度条 + 百分比 + 实时出结果行 + 可取消
4. 表格实时对比排序（点击列头排序，显示文件名）
5. 选择性地导出报告：HTML（带详情）/ CSV 汇总
6. 单书详情查看（指标 + 复读样例）

批量处理优化：
- 单文件失败独立容错，不中断整批
- 每完成一个文件立即在结果表插入该行（实时反馈）
- 评分中可点击"取消"停止后续文件（已完成的保留）
- 进度回调细粒度到"窗口提取特征/评分/合并"阶段

运行：
    python -m ui.app   （或 python main.py --gui）
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 保证从任意工作目录启动都能找到 core/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import score_one_file
from ui.report import generate_html_report


def _ts():
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# 模式中文名 → 内部名
MODE_MAP = {"默认": "default", "三段": "three", "十段": "ten", "全本": "full"}

# 进度回调阶段 → 中文说明
STAGE_LABEL = {"load": "读取文件", "extract": "提取特征", "score": "评分中",
               "merge": "合并评分", "done": "完成"}


class NovelScorerApp:
    def __init__(self, root):
        self.root = root
        root.title("网文批量评分器")
        root.geometry("1040x700")
        root.minsize(780, 560)

        self.files = []          # 待评分文件路径列表
        self.results = []        # 评分结果列表
        self.sort_key = "total"
        self.sort_desc = True
        self._cancel_flag = False
        self._scoring = False

        self._build_layout()

    # ------------------------------------------------------------------
    def _build_layout(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="添加文件…", command=self.add_files).pack(side="left")
        ttk.Button(top, text="添加目录…", command=self.add_dir).pack(side="left", padx=6)
        ttk.Button(top, text="移除选中", command=self.remove_selected).pack(side="left")
        ttk.Button(top, text="清空列表", command=self.clear_files).pack(side="left", padx=6)
        ttk.Label(top, text="采样模式:").pack(side="left", padx=(18, 4))
        self.mode_var = tk.StringVar(value="默认")
        ttk.Combobox(top, textvariable=self.mode_var, width=8, state="readonly",
                     values=list(MODE_MAP.keys())).pack(side="left")
        self.merge_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="合并评分", variable=self.merge_var).pack(side="left", padx=10)
        ttk.Button(top, text="导出 HTML 报告", command=self.export_html).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="导出 CSV", command=self.export_csv).pack(side="right", padx=6)
        self.start_btn = ttk.Button(top, text="开始评分", command=self.start_scoring)
        self.start_btn.pack(side="right", padx=6)
        self.cancel_btn = ttk.Button(top, text="取消", command=self.cancel_scoring,
                                     state="disabled")
        self.cancel_btn.pack(side="right")

        # 文件列表
        mid = ttk.LabelFrame(self.root, text="待评分文件", padding=6)
        mid.pack(fill="x", padx=8)
        self.file_list = tk.Listbox(mid, height=5, selectmode="extended")
        self.file_list.pack(fill="x")
        self.file_list.bind("<Delete>", lambda e: self.remove_selected())

        # 进度区（批量评分时显示）
        prog = ttk.Frame(self.root, padding=(8, 2, 8, 0))
        prog.pack(fill="x")
        self.progress = ttk.Progressbar(prog, mode="determinate", maximum=1000)
        self.progress.pack(fill="x", side="left", expand=True)
        self.prog_label = ttk.Label(prog, text="", width=38, anchor="e")
        self.prog_label.pack(side="right", padx=(8, 0))

        # 结果表
        res = ttk.LabelFrame(self.root, text="评分结果（点击列头排序 · 双击行查看详情）", padding=6)
        res.pack(fill="both", expand=True, padx=8, pady=8)
        cols = ("filename", "total", "grade", "d1", "d2", "d3", "d4", "merged", "n")
        self.tree = ttk.Treeview(res, columns=cols, show="headings", height=10)
        headers = {
            "filename": ("文件名", 200),
            "total": ("总分", 64),
            "grade": ("等级", 80),
            "d1": ("D1文笔", 72),
            "d2": ("D2复读", 72),
            "d3": ("D3结构", 72),
            "d4": ("D4可读", 72),
            "merged": ("合并分", 64),
            "n": ("总字数", 84),
        }
        for c, (t, w) in headers.items():
            self.tree.heading(c, text=t, command=lambda cc=c: self.sort_by(cc))
            self.tree.column(c, width=w, anchor="center", stretch=(c == "filename"))
        self.tree.column("filename", anchor="w")
        vsb = ttk.Scrollbar(res, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.show_detail)

        # 状态栏
        self.status = tk.StringVar(value="就绪")
        self.status_lbl = tk.Label(self.root, textvariable=self.status, anchor="w",
                                   relief="sunken", bg="#F0F0F0", fg="#1A1B1C")
        self.status_lbl.pack(fill="x", side="bottom")

    # ------------------------------------------------------------------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择待评分的小说文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.file_list.insert("end", os.path.basename(p))
        self.status.set(f"已添加 {len(self.files)} 个文件")

    def add_dir(self):
        d = filedialog.askdirectory(title="选择包含小说 txt 的目录")
        if not d:
            return
        added = 0
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(".txt"):
                p = os.path.join(d, fn)
                if p not in self.files:
                    self.files.append(p)
                    self.file_list.insert("end", fn)
                    added += 1
        self.status.set(f"目录已添加 {added} 个文件")

    def clear_files(self):
        self.files = []
        self.results = []
        self.file_list.delete(0, "end")
        self._clear_rows()
        self.status.set("已清空")

    def remove_selected(self):
        sel = self.file_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选中要移除的文件")
            return
        for idx in reversed(sel):
            self.files.pop(idx)
            self.file_list.delete(idx)
        self.status.set(f"剩余 {len(self.files)} 个文件")

    # ------------------------------------------------------------------
    def start_scoring(self):
        if self._scoring:
            return
        if not self.files:
            messagebox.showwarning("提示", "请先添加文件")
            return
        self._scoring = True
        self._cancel_flag = False
        self.results = []
        self._clear_rows()
        self.progress["value"] = 0
        self.cancel_btn.configure(state="normal")
        self.start_btn.configure(state="disabled")
        self.status.set("评分中…")
        t = threading.Thread(target=self._do_scoring, daemon=True)
        t.start()

    def cancel_scoring(self):
        if not self._scoring:
            return
        self._cancel_flag = True
        self.cancel_btn.configure(state="disabled")
        self.status.set("正在取消（等待当前文件完成）…")

    # ------------------------------------------------------------------
    def _do_scoring(self):
        mode = MODE_MAP.get(self.mode_var.get(), "default")
        merge = self.merge_var.get()
        total = len(self.files)
        results = []

        for i, f in enumerate(self.files):
            if self._cancel_flag:
                break
            fn = os.path.basename(f)
            try:
                def on_prog(info, idx=i, fname=fn):
                    self.root.after(0, self._update_progress, idx, total, info)

                r = score_one_file(f, mode=mode, merge=merge, on_progress=on_prog)
                r["file"] = f          # 补全文件路径（修复文件名列显示）
                results.append(r)
                self.root.after(0, self._append_result_row, r)
                self.root.after(0, self.status.set, f"已完成 {fn}")
            except Exception as e:
                # 单文件失败独立容错，不中断整批
                results.append({
                    "title": os.path.splitext(fn)[0], "filename": fn, "file": f,
                    "error": str(e), "total_score": 0.0,
                    "grade": {"level": "E", "description": "读取失败"},
                })
                self.root.after(0, self._append_result_row, results[-1])
                self.root.after(0, self.status.set, f"失败 {fn}: {e}")

        # 排序后统一重绘（实时插入的行也一并进入排序）
        results.sort(key=lambda r: r.get("total_score", 0), reverse=True)
        self.results = results
        self.root.after(0, self._refresh_table)
        if self._cancel_flag:
            self.root.after(0, self.status.set, f"已取消（完成 {len(results)}/{total} 个文件）")
        else:
            self.root.after(0, self.status.set, f"完成：{len(results)} 个文件")
        self.root.after(0, self._reset_progress)
        self.root.after(0, self._set_running, False)

    def _set_running(self, running: bool):
        self._scoring = running
        self.start_btn.configure(state="normal" if not running else "disabled")
        self.cancel_btn.configure(state="disabled")

    # ---------- jieba 自动安装回调 ----------
    def _jieba_installed(self):
        self.status.set("jieba 已自动安装（完整模式）✓")
        self.status_lbl.configure(fg="#2E7D32")

    def _jieba_install_failed(self, detail):
        self.status.set("⚠ jieba 缺失（已自动降级 n-gram，D1 精度下降）")
        self.status_lbl.configure(fg="#B45309")
        messagebox.showwarning(
            "jieba 安装失败",
            "未能自动安装 jieba，D1 词级指标将降级为 n-gram 近似（功能仍可用）。\n\n"
            "原因：\n" + detail + "\n\n"
            "可手动安装后重启：\npython -m pip install jieba")

    # ---------- 进度 ----------
    def _update_progress(self, idx, total, info):
        """由 score_one_file 进度回调驱动（在 tk 主线程执行）"""
        frac = info.get("frac", 0) or 0
        # 整体进度 = (已完成的文件数 + 当前文件内比例) / 总数
        overall = min((idx + min(1.0, frac)) / max(total, 1), 1.0)
        self.progress["value"] = int(overall * 1000)
        pct = int(overall * 100)
        stage = STAGE_LABEL.get(info.get("stage", ""), "")
        self.prog_label.configure(
            text=f"{idx + 1}/{total} · {pct}% · {stage}")
        if info.get("file"):
            self.status.set(f"评分中 {info['file']} · {stage}")

    def _reset_progress(self):
        self.progress["value"] = 0
        self.prog_label.configure(text="")

    # ---------- 结果表 ----------
    def _row_values(self, r):
        d = r.get("dimensions", {})
        ms = r.get("merged_score")
        return (
            os.path.basename(r.get("file", r.get("filename", ""))),
            f"{r.get('total_score', 0):.1f}",
            f"{r.get('grade', {}).get('level', '')} {r.get('grade', {}).get('description', '')}",
            f"{d.get('D1_richness', {}).get('score', 0):.1f}",
            f"{d.get('D2_repetition', {}).get('score', 0):.1f}",
            f"{d.get('D3_structure', {}).get('score', 0):.1f}",
            f"{d.get('D4_readability', {}).get('score', 0):.1f}",
            f"{ms.get('total_score', 0):.1f}" if ms else "—",
            f"{r.get('total_hanzi', 0):,}",
        )

    def _append_result_row(self, r):
        """实时插入一行（不排序，最终统一排序重绘）"""
        self.tree.insert("", "end", values=self._row_values(r))

    def _refresh_table(self):
        self._clear_rows()
        for r in self.results:
            self.tree.insert("", "end", values=self._row_values(r))

    def _clear_rows(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    # ------------------------------------------------------------------
    def sort_by(self, key):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = key
            self.sort_desc = True

        def val(r):
            d = r.get("dimensions", {})
            ms = r.get("merged_score")
            return {
                "filename": os.path.basename(r.get("file", "")),
                "total": r.get("total_score", 0),
                "grade": r.get("total_score", 0),
                "d1": d.get("D1_richness", {}).get("score", 0),
                "d2": d.get("D2_repetition", {}).get("score", 0),
                "d3": d.get("D3_structure", {}).get("score", 0),
                "d4": d.get("D4_readability", {}).get("score", 0),
                "merged": ms.get("total_score", -1) if ms else -1,
                "n": r.get("total_hanzi", 0),
            }[key]

        self.results.sort(key=val, reverse=self.sort_desc)
        self._refresh_table()

    def show_detail(self, _evt):
        sel = self.tree.selection()
        if not sel or not self.results:
            return
        idx = self.tree.index(sel[0])
        r = self.results[idx]
        d = r.get("dimensions", {})
        m1 = d.get("D1_richness", {}).get("metrics", {})
        m2 = d.get("D2_repetition", {}).get("metrics", {})
        m3 = d.get("D3_structure", {}).get("metrics", {})
        m4 = d.get("D4_readability", {}).get("metrics", {})
        ex = r.get("repeat_examples", [])
        ex_txt = "；".join(f"{e['text']}(×{e['count']})" for e in ex[:5]) if ex else "无"
        ms = r.get("merged_score")
        merge_txt = f"\n合并评分: {ms.get('total_score')}（诊断跨段复用）" if ms else ""
        detail = (
            f"文件: {os.path.basename(r.get('file', r.get('filename','')))}\n"
            f"采样: {r.get('sampling', {}).get('mode_label', '')} "
            f"(窗口 {r.get('sampling', {}).get('window_hanzi', [])})\n"
            f"总分: {r.get('total_score')}  {r.get('grade',{}).get('level')} {r.get('grade',{}).get('description','')}"
            f"{merge_txt}\n"
            f"D1 文笔: {d.get('D1_richness',{}).get('score')}/40  词TTR={m1.get('word_ttr')} 字TTR={m1.get('char_ttr')}\n"
            f"D2 复读: {d.get('D2_repetition',{}).get('score')}/25  加权复读={m2.get('guarded_repeat_ratio')} 窗峰={m2.get('window_peak')}\n"
            f"D3 结构: {d.get('D3_structure',{}).get('score')}/20  段中位={m3.get('para_median')} 对话={(m3.get('dialogue_ratio',0)*100):.0f}%\n"
            f"D4 可读: {d.get('D4_readability',{}).get('score')}/15  均句长={m4.get('mean_sent_len')}\n"
            f"高频词: {'、'.join(r.get('top_words', [])[:8])}\n"
            f"复读样例: {ex_txt}"
        )
        messagebox.showinfo("详情", detail)

    # ------------------------------------------------------------------
    def _selected_results(self):
        """仅导出选中行（若未选中则全部）"""
        sel = self.tree.selection()
        if not sel:
            return self.results
        return [self.results[self.tree.index(i)] for i in sel]

    def export_html(self):
        if not self.results:
            messagebox.showwarning("提示", "尚无评分结果")
            return
        path = filedialog.asksaveasfilename(
            title="保存 HTML 报告", defaultextension=".html",
            initialfile=f"文本评分报告{_ts()}.html",
            filetypes=[("HTML", "*.html")])
        if not path:
            return
        generate_html_report(self._selected_results(), path)
        messagebox.showinfo("完成", f"报告已保存：\n{path}")

    def export_csv(self):
        if not self.results:
            messagebox.showwarning("提示", "尚无评分结果")
            return
        path = filedialog.asksaveasfilename(
            title="保存 CSV", defaultextension=".csv",
            initialfile=f"文本评分报告{_ts()}.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        import csv
        rows = self._selected_results()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            header = ["文件名", "总分", "等级", "D1文笔", "D2复读",
                      "D3结构", "D4可读", "采样模式"]
            if any(r.get("merged_score") for r in rows):
                header.append("合并分")
            w.writerow(header)
            for r in rows:
                d = r.get("dimensions", {})
                row = [
                    os.path.basename(r.get("file", r.get("filename", ""))),
                    r.get("total_score", ""),
                    r.get("grade", {}).get("level", ""),
                    d.get("D1_richness", {}).get("score", ""),
                    d.get("D2_repetition", {}).get("score", ""),
                    d.get("D3_structure", {}).get("score", ""),
                    d.get("D4_readability", {}).get("score", ""),
                    r.get("sampling", {}).get("mode_label", ""),
                ]
                ms = r.get("merged_score")
                if any(x.get("merged_score") for x in rows):
                    row.append(ms.get("total_score", "") if ms else "")
                w.writerow(row)
        messagebox.showinfo("完成", f"CSV 已保存：\n{path}")


def main():
    from core.health import check_environment
    env = check_environment()
    root = tk.Tk()
    app = NovelScorerApp(root)
    # 启动检查：jieba 缺失 → 后台尝试自动安装，成功/失败分别提示；失败降级继续
    if not env["jieba"]:
        app.status.set("jieba 缺失，正在尝试自动安装…")
        t = threading.Thread(target=_install_and_notify, args=(app,), daemon=True)
        t.start()
    root.mainloop()


def _install_and_notify(app):
    from core.health import ensure_jieba
    dep = ensure_jieba(auto_install=True)
    if dep["mode"] == "full":
        app.root.after(0, app._jieba_installed)
    else:
        app.root.after(0, app._jieba_install_failed, dep["detail"])


if __name__ == "__main__":
    main()
