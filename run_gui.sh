#!/usr/bin/env bash
# 图片相似度比较工具 —— Ubuntu/Linux 启动器
# 用法: 双击运行, 或终端执行 ./run_gui.sh
# 双击 "一闪而过" 时: 先 sudo apt install python3-tk python3-venv, 再双击
set -e
cd "$(dirname "$0")"

PY=".venv/bin/python"

# 需要用户按回车才关窗(仅当有终端时)
pause() {
  if [ -t 0 ]; then
    echo "—— 按回车键关闭窗口 ——"
    read -r _
  fi
}

# 用系统弹窗提示错误(文件管理器双击运行时没有终端, 只能靠弹窗)
warn() {
  echo
  echo "错误: $1"
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="图片相似度比较工具" --text="$1" 2>/dev/null
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send "图片相似度比较工具" "$1" 2>/dev/null
  fi
}

if ! command -v python3 >/dev/null 2>&1; then
  warn "未找到 Python3, 请先执行: sudo apt install python3 python3-venv"
  pause
  exit 1
fi

if [ ! -x "$PY" ]; then
  echo "[1/2] 创建虚拟环境..."
  if ! python3 -m venv .venv; then
    warn "创建虚拟环境失败, 请先执行: sudo apt install python3-venv"
    pause
    exit 1
  fi
  echo "[2/2] 安装依赖..."
  if ! "$PY" -m pip install -r requirements.txt; then
    warn "安装依赖失败, 请检查网络后重试(临时可换清华源: pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt)"
    pause
    exit 1
  fi
fi

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  warn $'缺少 tkinter 图形组件, 请先执行:\n  sudo apt install python3-tk\n然后重新运行本脚本。'
  pause
  exit 1
fi

echo "正在启动图形界面 (关闭窗口即退出)..."
if ! "$PY" gui.py; then
  echo
  echo "程序异常退出, 上面的错误信息就是原因。"
  pause
fi
