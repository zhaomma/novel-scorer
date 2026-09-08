# novel_scorer — 长篇网文批量评分工具

面向长篇网络小说的批量评分软件。核心设计目标是：
- **重文笔**：四维评分中 D1 语言丰富度权重最高（40/100）
- **抗固定信息**：从评分机制层面钝化"章节更新时间/第几章"等站点固定信息，不做清洗
- **可区分复读**：解决旧工具 M2（单字重复度）在长文上饱和无区分度的问题
- **一体 UI**：自包含静态 HTML 报告，双击打开即可对比排序、看雷达图、导出 CSV

## 四维评分体系（总分 100）

| 维度 | 权重 | 衡量内容 |
|---|---|---|
| D1 语言丰富度 | 40 | 词级 TTR（jieba 分词）、字级 TTR、句长分布熵、短语丰富度 |
| D2 表达复读度 | 25 | 加权句复读率、滑窗复读峰值、高频词集中度 |
| D3 语篇结构度 | 20 | 段落健康度、对话密度、章节均衡度 |
| D4 可读性 | 15 | 句长健康、单字集中度异常、噪声 |

## 固定信息机制层（RepetitionGuard）

不依赖清洗，纯数学钝化：

1. **重复计数封顶**（cap=10）：同一句重复超过 10 次不计入权重
2. **独立短行降权**：≤15 汉字的行权重 0.1（固定信息行通常很短）
3. **数据驱动模板池**：整行汉字序列完全相同≥3 次的行自动进池降权（"章节更新时间"等自动识别，无需站点规则）

实测效果：注入 3400+ 行"章节更新时间"后总分仅降 1.04 分；而注入真实重复句后 D2 锐降 21.8 分——能钝化固定信息，也能抓住真注水。

## 使用

### 一体 UI（推荐，零服务依赖的本地桌面应用）

```bash
python -m ui.app        # 或 python main.py --gui
```

打开后一体完成：添加文件/目录 → 选采样模式 → 开始评分 → 表格点击列头对比排序 → 双击行看详情 → 选择性导出 HTML 报告 / CSV / JSON。全程本地运行，不依赖任何服务。

### 命令行批量

```bash
# 单文件/多文件/目录评分（默认去首尾采样，文件名直接用文件名）
python main.py 文件1.txt 文件2.txt
python main.py --out output --html --csv --json 目录路径/

# 采样模式
python main.py 文件.txt --mode trim      # 去首尾采样（默认）：剔除首尾8%，均匀取3×2万字窗口
python main.py 文件.txt --mode 3point    # 三点采样：开头/中段/末尾
python main.py 文件.txt --mode chapter   # 章节级采样：按章节均匀抽样
python main.py 文件.txt --mode full      # 全本扫描（短文本）

# 参数
--window 20000      # 采样窗口字数
--n-windows 3       # 去首尾窗口数
--trim-ratio 0.08   # 首尾剔除比例
```

## 产物

- `output/report.html` — 自包含静态报告（数据内嵌、双击即开、无需服务器）：对比排序表 + 单书详情 + 导出 CSV（无雷达图）
- `output/results.csv` — 汇总表（文件名、总分、等级、四维分）
- `output/results.json` — 全量明细（含指标、复读样例）

## 编码支持

自动探测：UTF-8 / UTF-8-SIG(BOM) / UTF-16(LE/BE 含无BOM) / GBK / GB18030 / Big5。

## 依赖

- **Python 3.8+**（需自带 tkinter；Windows 官方安装默认带，部分 Linux 发行版需额外 `python3-tk`）
- **jieba**（分词，可选）：安装后 D1 词级指标为完整精度

```bash
python -m pip install jieba
```

若未安装 jieba，自动降级为 n-gram 近似分词，功能可用但 D1 词级指标精度下降。除 jieba 外零第三方依赖、零外部服务、零网络。

## 启动检查与依赖自动安装

GUI 与 CLI 启动时均会自动检测环境（Python / jieba / tkinter），**jieba 缺失时自动尝试安装**：

- **GUI**（`python -m ui.app`）：jieba 缺失 → 后台自动 `pip install jieba`；成功则状态栏绿色提示"jieba 已自动安装（完整模式）"；**失败则弹出原因提示（网络/超时/pip 报错等）并给出手动命令，降级 n-gram 继续运行**（橙色常驻警告），不崩溃。
- **CLI**（`python main.py …`）：评分前先打印环境报告；jieba 缺失时自动安装，成功打印"已自动安装"，失败打印原因 + `python -m pip install jieba` 手动命令后降级继续。

```
[环境检查]
Python 3.14.7 · Windows AMD64
jieba: 可用 ✓
tkinter: 可用 ✓
```

安装失败常见原因与应对：无网络 → 离线机器请提前拷入 jieba 或用下方打包方案；无 pip → 重新安装带 pip 的 Python；超时 → 手动执行安装命令。

## 短文兼容

TTR 锚点按**实际窗口汉字数**动态分档（<1.5万 / 1.5万~3万 / 3万~10万 / ≥10万，实测标定）。短文不再因"窗口未满"虚高：实测截断 1.2 万字文本分数从旧逻辑的 97(S) 回落到 78.5(B)。当实际窗口 <1 万字（样本过小、各维度失真）时，结果会带标记"短文本样本，分数仅供参考"。

## 可移动性

整个 `novel_scorer/` 目录拷贝到任何装有 Python 3.8+ 的机器即可运行。核心逻辑零外部服务、零网络依赖；报告为自包含静态 HTML（数据内嵌、双击即开，无雷达图、无 CDN）。首次在新环境运行时，请以启动检查的输出为准确认 jieba 状态（缺失会自动尝试安装）。

### 打包为可执行文件（含 jieba，零依赖分发）

如需目标机器**完全不用装 Python / jieba**，可用 PyInstaller 打包含 jieba 的独立可执行文件：

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name 网文评分器 ^
  --collect-data jieba --hidden-import jieba ^
  --add-data "core;core" --add-data "ui;ui" main.py
```

- `--collect-data jieba` / `--hidden-import jieba`：把 jieba 词典与模块打进包（否则运行时报找不到词典）
- `--windowed`：GUI 模式不弹控制台
- `--onefile`：单文件 exe（约 20~30MB，含 jieba 词典）；也可去掉 `--onefile` 打单目录（启动更快、杀软误报更少）
- 打包后目标机**零 Python、零 jieba**，双击 exe 即用（启动自检仍会运行，但因 jieba 已内嵌必然通过）
- 打包应在与目标系统一致的机器上进行（Windows 包只能在 Windows 跑）

## 目录结构

```
novel_scorer/
├── main.py              # CLI 入口：批量评分流水线（--gui 启动一体界面）
├── core/
│   ├── loader.py        # 多编码读取
│   ├── sampler.py       # 4 种采样模式
│   ├── segment.py       # 句/段切分 + RepetitionGuard 机制层
│   ├── features.py      # 多尺度特征提取
│   ├── calibrate.py     # 归一化/稳健聚合
│   └── scoring_d1~d4.py # 四维评分
├── ui/
│   ├── app.py           # 一体操作界面（tkinter，零服务）
│   └── report.py        # 静态 HTML 报告生成器
├── data/                # （预留）字表/停用词
└── output/              # 报告产物
```
