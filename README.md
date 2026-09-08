# 网文批量评分工具 — 工作目录说明

本目录包含一套面向**长篇网络小说批量评分**的本地工具 `novel_scorer`。
核心目标：重文笔、抗固定信息干扰、可区分复读，全程本地运行、零外部服务。

---

## 一、目录结构

```
workspace/
├── novel_scorer/            开发版工具（源码，模块化，便于修改调试）
│   ├── main.py              CLI 入口（python main.py ...）
│   ├── core/                核心逻辑
│   │   ├── textio.py        多编码读取 + 4 种采样模式
│   │   ├── segment.py       句/段切分 + 固定信息钝化机制（RepetitionGuard）
│   │   ├── features.py      多尺度特征提取
│   │   ├── scoring.py       四维评分 + 校准工具
│   │   └── health.py        环境自检 + jieba 自动安装
│   ├── ui/                  界面层
│   │   ├── app.py           一体操作界面（tkinter，零服务）
│   │   └── report.py        静态 HTML 报告生成
│   └── README.md            工具详细说明
│
├── novel_scorer_final/      最终成果（精简合并版，可移动分发）
│   ├── main.py              CLI 入口
│   ├── launcher.py          exe 打包入口（双击进 GUI）
│   ├── core/ + ui/          同开发版，已合并精简
│   ├── dist/网文评分器.exe   可执行文件（约 31MB，含 jieba，零依赖）
│   ├── output/              示例报告（report.html / results.csv / results.json）
│   └── README.md            工具详细说明
│
├── novel_scorer_final.zip   完整分发包（含 exe + 源码 + 示例报告，31MB）
└── README.md                本说明
```

## 二、工具简介与评分机制

四维评分（总分 100），**重文笔**（D1 权重最高）：

| 维度 | 权重 | 衡量内容 |
|---|---|---|
| D1 语言丰富度 | 40 | 词级 TTR（jieba 分词）、字级 TTR、句长分布熵、短语丰富度 |
| D2 表达复读度 | 25 | 加权句复读率、滑窗复读峰值、高频词集中度 |
| D3 语篇结构度 | 20 | 段落健康度、对话密度、章节均衡度 |
| D4 可读性 | 15 | 句长健康、单字集中度异常、噪声 |

关键设计：

- **抗固定信息**：不依赖清洗。重复计数封顶、独立短行降权、整行模板池自动识别"章节更新时间/第几章"等固定行并降权。实测注入 3400+ 行"更新时间"总分仅降约 1 分，而注入真实复读句 D2 锐降 21.8 分。
- **多尺度复读**：解决旧工具"单字重复度"在长文饱和无区分度的问题，改用 2-gram / 句子 / 局部窗口多尺度检测。
- **短文兼容**：TTR 锚点按实际窗口汉字数动态分档，短文不再虚高；窗口 <1 万字时标记"仅供参考"。
- **采样模式**：默认（去首尾 1000 字符取头 5 万字）/ 三段 / 十段（各取 2 万字窗口）/ 全本。窗口互不重叠，短文自动减节点。
- **合并评分**（可选开关）：把所有窗口拼整体再评一次，暴露跨段复用程度，作诊断参考。

## 三、使用方式

### 1. 可执行文件版（推荐，零依赖）

双击 `novel_scorer_final\dist\网文评分器.exe` 直接打开一体界面：

- 添加文件/文件夹 → 选采样模式（默认/三段/十段/全本）→ 开始评分
- 表格点击列头排序对比、双击行看四维详情
- 导出 HTML 报告 / CSV（文件对话框自选保存位置，默认名带时间戳）

### 2. 源码版（需 Python 3.8+）

```bash
# 一体界面
python main.py --gui              # 或在 novel_scorer_final 目录运行

# 命令行批量
python main.py 文件1.txt 文件2.txt --mode ten --merge --html --csv --json

# 采样模式：--mode default | three | ten | full
# 合并评分：--merge
```

### 3. 启动检查

每次运行自动检查环境：jieba 缺失时自动 `pip install jieba`，成功切完整模式；
失败则降级 n-gram 近似继续运行并提示手动安装命令（`python -m pip install jieba`）。

## 四、示例报告

`novel_scorer_final\output\` 下有工具实测生成的一份示例：

- `report.html` — 自包含静态报告（双击即开，可排序、看详情、导出 CSV）
- `results.csv` / `results.json` — 同批评分的汇总与明细

该示例基于十段模式 + 合并评分的批量运行结果。正式使用请以你自己的文本重新评分。

## 五、注意事项

- 文件名直接作为书名显示（不做书籍信息剥离）。
- 支持编码：UTF-8 / UTF-8-SIG / UTF-16(LE/BE 含无 BOM) / GB18030 / GBK / Big5，自动探测。
- 除 jieba 外零第三方依赖、零网络、零外部服务。
- exe 版在 Windows 上运行；如需重新打包，见 `novel_scorer_final\README.md` 打包节。
