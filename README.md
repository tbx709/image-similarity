# 图片相似度比较工具 (image-similarity)

一个简单好用的图片相似度比较工具，提供三种用法：**单张比较（命令行）**、**批量查找相似/重复图片**、**图形界面**。

**跨平台**：支持 **Ubuntu / Windows**（Python 3.8+，依赖只有 Pillow 和 numpy，GUI 用系统自带 tkinter）。

## 功能一览

| 功能 | 入口 | 说明 |
|------|------|------|
| 单张比较 | `compare.py` | 比较两张图，输出 0~1 相似度和中文判定 |
| 批量扫描 | `batch_compare.py` | 扫一个文件夹（或两个文件夹交叉对比），找出相似/重复图片 |
| 去重归档 | `dedup.py` | 把重复图片**移动**进以基准图命名的子文件夹（默认只预演，可一键撤销） |
| 图形界面 | `gui.py` | 两个页签：单张比较 + 批量扫描，支持进度条、预览、导出 CSV |

## 环境要求

| | Ubuntu | Windows |
|---|---|---|
| Python | 3.8+（`sudo apt install python3`） | 3.8+（[python.org 官方安装包](https://www.python.org/downloads/)，**不要用微软商店版**） |
| 图形界面 | `sudo apt install python3-tk` | 官方安装包自带 tkinter，无需额外安装 |
| 依赖库 | 以下三方统一 `pip install -r requirements.txt` | 同左 |
| 拖拽支持(可选) | `pip install tkinterdnd2` | 同左 |

## 快速开始（Ubuntu）

```bash
# 1. 图形界面需要 tkinter(只需一次)
sudo apt install python3-tk

# 2. 一键启动(首次自动建虚拟环境+装依赖)
./run_gui.sh

# 或者手动操作:
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. 命令行用法
.venv/bin/python compare.py 图片A.png 图片B.jpg                 # 单张比较
.venv/bin/python batch_compare.py 图片文件夹 --csv 报告.csv     # 批量找相似
.venv/bin/python dedup.py 图片文件夹                            # 去重: 先看计划(不动文件)
.venv/bin/python dedup.py 图片文件夹 --apply                    # 确认后再执行移动
```

## 快速开始（Windows）

```powershell
# 1. 一键启动: 双击 run_gui.bat(首次自动建虚拟环境+装依赖)
#    或在命令行:
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python gui.py

# 2. 命令行用法
.venv\Scripts\python compare.py 图片A.png 图片B.jpg            # 单张比较
.venv\Scripts\python batch_compare.py 图片文件夹 --csv 报告.csv # 批量找相似
.venv\Scripts\python dedup.py 图片文件夹                       # 去重: 先看计划(不动文件)
.venv\Scripts\python dedup.py 图片文件夹 --apply               # 确认后再执行移动
```

> 提示：想让 Windows 上直接双击启动 GUI，把项目文件夹里的 `run_gui.bat` 发送到桌面快捷方式即可。

## 用 法 详 解

### 1. 单张比较

```bash
python compare.py 图片A.png 图片B.jpg                 # 综合判断(默认, 6 种算法)
python compare.py 图片A.png 图片B.jpg --method phash  # 只看感知哈希
python compare.py 图片A.png 图片B.jpg --threshold 0.9 # 调高"相似"判定阈值
```

### 2. 批量查找相似 / 重复图片

```bash
python batch_compare.py 图片文件夹                    # 一个文件夹内找相似
python batch_compare.py 图片文件夹 --threshold 0.88   # 自定义阈值
python batch_compare.py 文件夹A --folder-b 文件夹B    # 两个文件夹交叉对比(找重复)
python batch_compare.py 图片文件夹 --csv 报告.csv     # 导出 CSV(Excel 可直接打开)
```

原理：每张图先算一个 64 位**感知哈希**，汉明距离相近的图片用并查集分成一组（默认阈值 0.90，相似度等于 1.00 的会标注"完全相同"）。几千张图也能在几十秒内扫完，结果示例：

```
发现 1 组相似图片:

  组 #1 (3 张):
    基准: /home/user/photos/IMG_001.png
    /home/user/photos/IMG_002.jpg  (相似度 1.00, 完全相同)
    /home/user/photos/sub/IMG_003.png  (相似度 1.00, 完全相同)
```

### 3. 图形界面

```bash
python gui.py        # 或 ./run_gui.sh / run_gui.bat
```

- **单张比较页**：点"浏览"选图，或直接**把两张图片拖进窗口**，立即显示各算法分数和综合判定；右侧有预览图。
- **批量扫描页**：选文件夹 → 设阈值 → 开始扫描（有进度条）；结果按"组"列出，**双击某行弹出图片预览**，可一键导出 CSV。

### 4. 图片去重归档（把重复图归拢进子文件夹）

```bash
python dedup.py 图片文件夹                                   # 预演：只打印计划，不动任何文件
python dedup.py 图片文件夹 --apply                           # 确认无误后真正移动
python dedup.py 图片文件夹 --mode similar -t 0.95 --apply    # 连"压缩/缩放过的同一张图"一起归并
python dedup.py 图片文件夹 --keep largest --apply            # 保留体积最大的那张当基准
python dedup.py --undo 图片文件夹/.dedup-log-2025xxxx.json   # 撤销：按日志原样移回
```

效果：文件夹里有 `a.png`、`b.png`、`c.png`，其中 b、c 与 a 内容一样，执行后变成：

```
图片文件夹/
├── a.png          ← 基准图留在原位，归档文件夹就用它的名字命名
└── a/
    ├── b.png
    └── c.png
```

- **默认 `--mode exact`**：逐字节比对（SHA-256），只有**完全相同**的文件才归并，零误判。
- **`--mode similar`**：感知哈希找"看起来是同一张图"的版本（压缩过、缩放过的也算），阈值默认 0.95（`-t` 可调），`-m` 可选 `phash`/`dhash`/`ahash`。
- **`-k/--keep`** 决定哪张当基准图：`first`=文件名最前（默认）、`largest`=体积最大、`oldest`/`newest`=最早/最新。
- 子文件夹会一起扫描；只想处理顶层加 `--no-recursive`。

**它为什么不会把你的图弄乱：**

| 保护 | 说明 |
|------|------|
| 默认预演 | 必须显式 `--apply` 才移动文件，先看清清单再动手 |
| 一键撤销 | 每次移动都写 JSON 日志，`--undo 日志文件` 按记录移回并清理空文件夹 |
| 绝不覆盖 | 归档文件夹名撞车会退让成 `a_1`/`a_2`；文件夹内重名自动加 `_1` 后缀 |
| 可重复运行 | 归档文件夹里放了一个 `.dedup-group.json` 标记，下次扫描自动跳过，不会越套越深 |
| 只移动不删除 | 全程只有 `move`，任何情况下都不会删掉你的图片 |

> 归档文件夹里的 `.dedup-group.json` 请别删：它是"这个文件夹已经归档过"的标记，删掉后下次运行会把它当成普通文件夹重新归档（会多出一层 `a_1`，图片不会丢，但会乱）。

## 支持的方法（--method 选择）

| 方法  | 含义                         | 适用场景 |
|-------|------------------------------|----------|
| phash | 感知哈希（DCT 频率特征）     | **最常用**：同一张图的压缩/缩放/微调版本 |
| dhash | 差异哈希                     | 对亮度、缩放变化更鲁棒 |
| ahash | 平均哈希                     | 粗略的轮廓一致性 |
| ssim  | 结构相似度                   | 压缩、模糊、缩略图等近同图 |
| hist  | 颜色直方图（Bhattacharyya）  | 色彩分布接近度（不看结构） |
| mse   | 像素均方误差                 | 几乎完全相同的图 |

- 相似度取值均为 **0~1**，越大越相似；图片尺寸不同没关系，程序内部会自动缩放对齐。
- 单张比较判定阈值（默认）：哈希类 / ssim 为 0.85，直方图 0.90，mse 0.95。分数 ≥ 阈值判为"相似"，低于阈值 0.2 以内判为"相近"，再低判为"不相似"。
- 批量扫描默认阈值 0.90：**相册去重建议 0.95**（只报基本确定重复的），0.85 会更激进。

## 目录结构

```
image-similarity/
├── compare.py            # 单张比较主程序
├── batch_compare.py      # 批量扫描
├── dedup.py              # 去重归档(把重复图移动进子文件夹)
├── gui.py                # 图形界面
├── run_gui.sh            # Ubuntu/Linux 一键启动(GUI)
├── run_gui.bat           # Windows 一键启动(GUI)
├── samples/
│   ├── make_samples.py   # 生成测试用示例图片
│   ├── base.png          # 原图
│   ├── same.jpg          # 压缩后的同一张图
│   ├── edited.png        # 缩放+提亮后的版本
│   └── different.png     # 完全不同的图
├── tests/
│   └── test_dedup.py     # dedup.py 自动化测试(在临时目录里跑, 不碰真实图片)
├── requirements.txt
└── README.md
```

运行 `python samples/make_samples.py` 可重新生成示例图片。

## 常见问题

- **双击 `run_gui.sh` 一闪而过？** 先执行 `sudo apt install python3-tk python3-venv`，再双击。
  如果还闪退，在终端运行 `bash run_gui.sh` 看具体报错（脚本现在会在缺组件时弹窗提示并等你按回车）。
- **GUI 打不开/提示缺 tkinter**：Ubuntu 执行 `sudo apt install python3-tk`；Windows 请用 python.org 官方安装包（不要用微软商店版）。
- **拖拽没反应**：`pip install tkinterdnd2` 后重开 GUI；没有它也能用"浏览"按钮选图。
- **Windows 命令行中文乱码**：已默认输出 UTF-8；如 PowerShell 仍乱码可执行 `chcp 65001`。
- **批量扫描几百张图很慢？** 感知哈希每张图只需几十毫秒，瓶颈在图片解码；如需要可自行改成多进程并行。
- **两张不同照片被判相似？** 阈值调高一点（如 0.95），或用 `--method dhash` 再复核；同场景不同帧本来就会相似。
- **`dedup.py` 归并错了想搬回去？** 用执行时打印的那条命令：`python dedup.py --undo 日志文件.json`，会按记录把每个文件移回原位置并删掉空的归档文件夹。
- **`dedup.py` 会不会误删图？** 不会，全程只用移动（move），没有删除动作；而且默认只预演，不加 `--apply` 不会动任何文件。
- **为什么 `dedup.py` 说"已跳过 N 个归档文件夹"？** 那是之前运行留下的归档文件夹（带 `.dedup-group.json` 标记），跳过它们才能保证重复运行不会越套越深。
