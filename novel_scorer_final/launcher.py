# -*- coding: utf-8 -*-
"""
launcher.py — 可执行文件打包入口（双击 exe 直接启动一体 GUI）

exe 版定位为 GUI 应用；命令行批量评分请用 `python main.py ...`。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.app import main as gui_main

if __name__ == "__main__":
    sys.exit(gui_main())
