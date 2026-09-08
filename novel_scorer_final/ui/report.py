# -*- coding: utf-8 -*-
"""
ui/report.py — 生成自包含可操作静态 HTML 报告

特性：
- 数据内嵌（评分 JSON 直接写入 HTML），双击打开即可用，无需任何服务
- 对比排序表：点击列头按 总分/D1/D2/D3/D4 升降序
- 单书详情：四维分项 + 关键指标 + 复读样例（点击行展开）
- 文件名显示：仅显示文件名（不含完整路径）
- 工具自我介绍：modal 悬浮层（点击展开，不改变页面高度）
- 导出 CSV 汇总

生成方式：
    python -m ui.report <results.json> <output.html>
"""

import json
import os
import sys


def _json_embed(data) -> str:
    """转义 JSON 用于嵌入 <script>（避免 </script> 截断）"""
    s = json.dumps(data, ensure_ascii=False)
    return s.replace("</", "<\\/")


def generate_html_report(results: list, out_path: str) -> str:
    """
    根据评分结果列表生成静态 HTML 报告。

    Args:
        results: score_one_file 返回的结果字典列表
        out_path: 输出 html 路径

    Returns:
        html 文件路径
    """
    data = _json_embed(results)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>网文批量评分报告</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'PingFang SC','Microsoft YaHei',sans-serif; background: #F4F3EE; color: #1A1B1C; padding: 20px; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  .sub {{ color: #6B7280; font-size: 13px; margin-bottom: 16px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 16px; border: 1px solid #E4E3DD; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 8px 10px; text-align: right; border-bottom: 1px solid #EEE; }}
  th {{ background: #F8F7F4; cursor: pointer; user-select: none; white-space: nowrap; }}
  th:hover {{ background: #EFEEE9; }}
  td:first-child, th:first-child {{ text-align: left; }}
  .grade-S {{ color:#C9A7E8; font-weight:600; }} .grade-A {{ color:#52C41A; font-weight:600; }}
  .grade-B {{ color:#2F4DB3; font-weight:600; }} .grade-C {{ color:#8C6D1F; font-weight:600; }}
  .grade-D {{ color:#B45309; font-weight:600; }} .grade-E {{ color:#C0392B; font-weight:600; }}
  .sort-arrow {{ color: #9EACEA; margin-left: 3px; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; background:#F0EFEA; margin:2px; }}
  .detail {{ display:none; padding: 14px; background:#FAF9F6; border-radius: 8px; margin-top: 8px; }}
  .btn {{ padding: 8px 16px; border: none; border-radius: 8px; background: #2F4DB3; color: #fff; font-size: 13px; cursor: pointer; }}
  .btn:hover {{ opacity: 0.9; }}
  .btn.secondary {{ background: #E4E3DD; color: #1A1B1C; }}
  .metric-grid {{ display: flex; flex-wrap: wrap; gap: 10px; }}
  .metric {{ flex: 1 1 140px; background:#fff; border:1px solid #E4E3DD; border-radius:8px; padding:8px 10px; }}
  .metric .k {{ font-size:11px; color:#6B7280; }}
  .metric .v {{ font-size:15px; font-weight:600; margin-top:2px; }}
  .footer {{ color:#9CA3AF; font-size:12px; margin-top:20px; text-align:center; }}

  /* modal 悬浮层（不改变页面高度） */
  .modal-overlay {{ display:none; position:fixed; inset:0; background:rgba(20,20,24,0.45); z-index:1000; }}
  .modal {{ position:fixed; left:50%; top:50%; transform:translate(-50%,-50%);
            width:min(680px, 90vw); max-height:80vh; overflow:auto;
            background:#fff; border-radius:14px; padding:22px 24px;
            box-shadow:0 12px 40px rgba(0,0,0,0.25); z-index:1001; }}
  .modal h2 {{ font-size:17px; margin-bottom:12px; }}
  .modal h3 {{ font-size:14px; margin:14px 0 6px; color:#1A1B1C; }}
  .modal p, .modal li {{ font-size:13px; line-height:1.7; color:#333; }}
  .modal ul {{ padding-left:18px; margin:4px 0; }}
  .modal .close {{ float:right; border:none; background:#E4E3DD; border-radius:8px; padding:6px 14px; cursor:pointer; font-size:13px; }}
  .modal .close:hover {{ background:#D5D4CE; }}
  .weight-table {{ width:100%; border-collapse:collapse; font-size:13px; margin:6px 0; }}
  .weight-table td {{ border:1px solid #E4E3DD; padding:6px 10px; text-align:left; }}
  .weight-table td:first-child {{ width:150px; font-weight:600; }}
</style>
</head>
<body>
<h1>网文批量评分报告</h1>
<div class="sub" id="subtitle"></div>

<div class="card" style="margin-bottom:12px;">
  <div>
    <button class="btn secondary" onclick="openAbout()">工具介绍 · 评分规则设计理念</button>
    <button class="btn" onclick="exportCSV()">导出 CSV 汇总</button>
    <button class="btn secondary" onclick="toggleAllDetail()">展开/收起全部详情</button>
  </div>
  <table id="scoreTable" style="margin-top:12px;">
    <thead>
      <tr>
        <th data-key="title">文件名 <span class="sort-arrow"></span></th>
        <th data-key="total_score">总分 <span class="sort-arrow"></span></th>
        <th>等级</th>
        <th data-key="d1">D1 文笔 <span class="sort-arrow"></span></th>
        <th data-key="d2">D2 复读 <span class="sort-arrow"></span></th>
        <th data-key="d3">D3 结构 <span class="sort-arrow"></span></th>
        <th data-key="d4">D4 可读 <span class="sort-arrow"></span></th>
        <th data-key="merged">合并分 <span class="sort-arrow"></span></th>
        <th data-key="total_hanzi">总字数 <span class="sort-arrow"></span></th>
      </tr>
    </thead>
    <tbody id="tableBody"></tbody>
  </table>
</div>

<!-- 工具介绍 modal（不改变页面高度） -->
<div class="modal-overlay" id="aboutOverlay" onclick="if(event.target===this)closeAbout()">
  <div class="modal">
    <button class="close" onclick="closeAbout()">关闭</button>
    <h2>novel_scorer 网文批量评分工具</h2>
    <p>面向长篇网络小说的批量评分软件：重文笔、抗固定信息干扰、可对比排序、可移动分发。评分全程本地计算，报告为自包含静态 HTML（数据内嵌、双击打开即可交互，无需服务器）。</p>

    <h3>一、四维评分规则（总分 100）</h3>
    <table class="weight-table">
      <tr><td>D1 语言丰富度（40 分）</td><td>重文笔的核心维度：词级 TTR（jieba 分词）、字级 TTR、句长分布熵、短语丰富度。权重最高，体现"文笔储备"。</td></tr>
      <tr><td>D2 表达复读度（25 分）</td><td>加权句复读率、滑窗复读峰值、高频词集中度。检测灌水与句式单调。</td></tr>
      <tr><td>D3 语篇结构度（20 分）</td><td>段落健康度、对话密度、章节均衡度。衡量"是否成文"。</td></tr>
      <tr><td>D4 可读性（15 分）</td><td>句长健康、单字集中度异常、噪声。衡量"读起来顺不顺"。</td></tr>
    </table>
    <p>等级：S(≥90) / A(≥80) / B(≥70) / C(≥60) / D(≥45) / E。</p>

    <h3>二、设计理念</h3>
    <ul>
      <li><strong>为什么重文笔？</strong>长网文的根本竞争力在语言层面：词汇是否多样、句式是否灵活、表达是否有储备。D1 权重 40 分最高，直接体现这一取向。</li>
      <li><strong>为什么用多尺度而非单字？</strong>旧式工具用单字重复度（最高字频/Simpson）评分，在 50 万字规模下必然饱和收敛，区分度趋零。本工具改用词级 TTR、句子复读、滑窗峰值等多尺度指标，在长篇上仍保持明显区分。</li>
      <li><strong>为什么"章节更新时间/第几章"不干扰？</strong>不依赖清洗，纯机制钝化：重复计数封顶（cap=10）、短行降权（≤15 汉字权重 0.1）、数据驱动模板池（整行重复≥3 次自动降权）。实测注入 3400+ 行"更新时间"后总分仅降 1 分。</li>
      <li><strong>采样为什么定长？</strong>只比较"等长的代表性切片"（默认取头 5 万字 / 三段 3×2 万 / 十段 10×2 万 / 全本），不让总字数差异混进评分；固定去首尾千字符避开书头与烂尾。</li>
      <li><strong>合并评分是什么？</strong>把全部采样窗口拼成一个整体再评分，用于诊断"段内看似丰富、但全文跨段词汇复用严重"的整体单调问题。合并分显著低于分段分时，提示跨段重复偏多。</li>
    </ul>

    <h3>三、使用</h3>
    <ul>
      <li>GUI：<code>python main.py --gui</code> 或 <code>python -m ui.app</code>（一体操作界面，零服务）</li>
      <li>命令行：<code>python main.py 文件.txt --mode 默认|三段|十段|全本 --merge --html --csv</code></li>
      <li>编码：自动识别 UTF-8 / UTF-8-SIG / UTF-16 / GBK / GB18030 / Big5</li>
      <li>依赖：仅 jieba（未装自动降级 n-gram 近似）</li>
    </ul>
  </div>
</div>

<div class="footer">自包含静态报告 · 数据内嵌 · 双击打开即可交互</div>

<script>
var DATA = {data};
var currentSort = {{ key: 'total_score', desc: true }};

// ---------- 工具 ----------
function esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {{
    return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
  }});
}}
function baseName(p) {{
  if (!p) return '';
  var s = String(p);
  var parts = s.split(/[\\\\\\/]/);
  return parts[parts.length - 1];
}}
function gradeClass(g) {{ return 'grade-' + g; }}

// ---------- 工具介绍 modal ----------
function openAbout() {{ document.getElementById('aboutOverlay').style.display = 'block'; }}
function closeAbout() {{ document.getElementById('aboutOverlay').style.display = 'none'; }}

// ---------- 初始化 ----------
function init() {{
  document.getElementById('subtitle').textContent =
    '共 ' + DATA.length + ' 本 · 由 novel_scorer 生成';
  renderTable();
}}

// ---------- 排序表格 ----------
function dscore(r, key) {{
  if (key === 'd1') return r.dimensions.D1_richness.score;
  if (key === 'd2') return r.dimensions.D2_repetition.score;
  if (key === 'd3') return r.dimensions.D3_structure.score;
  if (key === 'd4') return r.dimensions.D4_readability.score;
  if (key === 'merged') return r.merged_score ? r.merged_score.total_score : -1;
  if (key === 'total_hanzi') return r.total_hanzi;
  if (key === 'title') return baseName(r.file || '');
  return r.total_score;
}}
function renderTable() {{
  var rows = DATA.slice().sort(function(a, b) {{
    var va = dscore(a, currentSort.key), vb = dscore(b, currentSort.key);
    var cmp = (typeof va === 'string') ? va.localeCompare(vb) : (va - vb);
    return currentSort.desc ? -cmp : cmp;
  }});
  var tbody = document.getElementById('tableBody');
  tbody.innerHTML = rows.map(function(r) {{
    var idx = DATA.indexOf(r);
    var d = r.dimensions;
    var ms = r.merged_score;
    return '<tr data-idx="' + idx + '">' +
      '<td><strong>' + esc(baseName(r.file || r.filename || r.title)) + '</strong></td>' +
      '<td><strong>' + r.total_score.toFixed(1) + '</strong></td>' +
      '<td class="' + gradeClass(r.grade.level) + '">' + r.grade.level + ' ' + r.grade.description + '</td>' +
      '<td>' + d.D1_richness.score.toFixed(1) + '</td>' +
      '<td>' + d.D2_repetition.score.toFixed(1) + '</td>' +
      '<td>' + d.D3_structure.score.toFixed(1) + '</td>' +
      '<td>' + d.D4_readability.score.toFixed(1) + '</td>' +
      '<td>' + (ms ? ms.total_score.toFixed(1) : '—') + '</td>' +
      '<td>' + (r.total_hanzi || 0).toLocaleString() + '</td>' +
      '</tr>' +
      '<tr class="detail" id="detail-' + idx + '">' +
      '<td colspan="9">' + buildDetail(r) + '</td></tr>';
  }}).join('');
  tbody.querySelectorAll('tr[data-idx]').forEach(function(tr) {{
    tr.onclick = function() {{
      var idx = tr.getAttribute('data-idx');
      var d = document.getElementById('detail-' + idx);
      d.style.display = d.style.display === 'table-row' ? 'none' : 'table-row';
    }};
  }});
  updateHeaders();
}}

function updateHeaders() {{
  document.querySelectorAll('#scoreTable th').forEach(function(th) {{
    var k = th.getAttribute('data-key');
    var arrow = th.querySelector('.sort-arrow');
    if (!arrow) return;
    if (k === currentSort.key) arrow.textContent = currentSort.desc ? '▼' : '▲';
    else arrow.textContent = '';
  }});
}}
document.querySelectorAll('#scoreTable th').forEach(function(th) {{
  th.onclick = function() {{
    var k = th.getAttribute('data-key');
    if (!k) return;
    if (currentSort.key === k) currentSort.desc = !currentSort.desc;
    else {{ currentSort.key = k; currentSort.desc = true; }}
    renderTable();
  }};
}});

// ---------- 详情 ----------
function buildDetail(r) {{
  var d = r.dimensions;
  var m1 = d.D1_richness.metrics, m2 = d.D2_repetition.metrics,
      m3 = d.D3_structure.metrics, m4 = d.D4_readability.metrics;
  var html = '<div class="metric-grid">' +
    '<div class="metric"><div class="k">D1 文笔</div><div class="v">' + d.D1_richness.score + '/40</div>' +
      '<div style="font-size:11px;color:#6B7280">词TTR ' + m1.word_ttr + ' · 字TTR ' + m1.char_ttr + ' · 句熵 ' + m1.sentence_entropy + '</div></div>' +
    '<div class="metric"><div class="k">D2 复读</div><div class="v">' + d.D2_repetition.score + '/25</div>' +
      '<div style="font-size:11px;color:#6B7280">加权复读 ' + m2.guarded_repeat_ratio + ' · 窗峰 ' + m2.window_peak + '</div></div>' +
    '<div class="metric"><div class="k">D3 结构</div><div class="v">' + d.D3_structure.score + '/20</div>' +
      '<div style="font-size:11px;color:#6B7280">段中位 ' + m3.para_median + ' · 对话 ' + (m3.dialogue_ratio*100).toFixed(0) + '%</div></div>' +
    '<div class="metric"><div class="k">D4 可读</div><div class="v">' + d.D4_readability.score + '/15</div>' +
      '<div style="font-size:11px;color:#6B7280">均句长 ' + m4.mean_sent_len + ' · Simpson ' + m4.simpson + '</div></div>' +
    '</div>';
  if (r.sampling && r.sampling.mode_label) {{
    html += '<div style="margin-top:8px;font-size:12px;color:#6B7280">采样模式：' + esc(r.sampling.mode_label) +
      ' · 窗口 ' + (r.sampling.window_hanzi || []).join(',') + ' 字</div>';
  }}
  if (r.merged_score) {{
    html += '<div style="margin-top:4px;font-size:12px;color:#6B7280">合并评分：' + r.merged_score.total_score +
      '（低于分段分越多，说明全文跨段词汇复用越重）</div>';
  }}
  html += '<div style="margin-top:10px;font-size:12px;color:#444"><strong>高频词：</strong>' +
    (r.top_words || []).map(esc).join('、') + '</div>';
  if (r.repeat_examples && r.repeat_examples.length) {{
    html += '<div style="margin-top:6px;font-size:12px;color:#444"><strong>复读样例：</strong>' +
      r.repeat_examples.slice(0,5).map(function(e){{
        return '<span class="badge">' + esc(e.text) + ' ×' + e.count + '</span>';
      }}).join(' ') + '</div>';
  }}
  return html;
}}

// ---------- 导出 CSV ----------
function exportCSV() {{
  var hasMerge = DATA.some(function(r) {{ return r.merged_score; }});
  var lines = [['文件名','总分','等级','D1文笔','D2复读','D3结构','D4可读','采样模式'].concat(hasMerge ? ['合并分'] : [])];
  DATA.forEach(function(r) {{
    var d = r.dimensions;
    var row = [baseName(r.file || r.filename || r.title), r.total_score, r.grade.level,
      d.D1_richness.score, d.D2_repetition.score,
      d.D3_structure.score, d.D4_readability.score,
      (r.sampling && r.sampling.mode_label) || ''];
    if (hasMerge) row.push(r.merged_score ? r.merged_score.total_score : '');
    lines.push(row);
  }});
  var csv = lines.map(function(l) {{ return l.map(esc).join(',') }}).join('\\n');
  var blob = new Blob(['\\ufeff' + csv], {{ type: 'text/csv;charset=utf-8' }});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = '网文评分导出.csv';
  a.click();
}}

// ---------- 展开全部 ----------
var allOpen = false;
function toggleAllDetail() {{
  allOpen = !allOpen;
  document.querySelectorAll('.detail').forEach(function(d) {{
    d.style.display = allOpen ? 'table-row' : 'none';
  }});
}}

init();
</script>
</body>
</html>"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def main(argv=None):
    if len(sys.argv) < 3:
        print("用法: python -m ui.report <results.json> <output.html>")
        return 1
    with open(sys.argv[1], encoding="utf-8") as f:
        results = json.load(f)
    out = generate_html_report(results, sys.argv[2])
    print(f"报告已生成: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
