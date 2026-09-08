# -*- coding: utf-8 -*-
"""
core/health.py — 环境自检 + 依赖自动安装（可移动分发的"启动检查"）

移动到其他环境后，启动时调用本模块：
- 检测运行条件（Python / jieba / tkinter）
- jieba 缺失时尝试自动安装（pip install jieba），安装失败则降级继续，不崩溃
- GUI / CLI 启动时据此提示用户
"""


def check_environment() -> dict:
    """检测运行环境，返回状态字典（不抛异常）"""
    import platform
    import sys

    info = {
        "python": platform.python_version(),
        "os": platform.system(),
        "machine": platform.machine(),
        "jieba": False,
        "jieba_error": None,
        "tkinter": False,
        "tkinter_error": None,
    }
    try:
        import jieba  # noqa: F401
        info["jieba"] = True
    except Exception as e:
        info["jieba_error"] = str(e)

    try:
        import tkinter  # noqa: F401
        info["tkinter"] = True
    except Exception as e:
        info["tkinter_error"] = str(e)
    return info


def jieba_status() -> str:
    """jieba 状态的一句话说明（供界面/控制台显示）"""
    if check_environment()["jieba"]:
        return "jieba 完整模式"
    return "jieba 未安装（已自动降级 n-gram，D1 词级精度下降）"


def try_install_jieba(timeout: int = 180) -> dict:
    """
    尝试自动安装 jieba（pip install）。

    Returns:
        {"ok": bool, "detail": str}，任何失败都返回 detail 说明，绝不抛异常。
    """
    import subprocess
    import sys
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "jieba"],
            capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "detail": "未找到 pip（python -m pip 不可用）"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "安装超时（网络慢或 pip 挂起）"}
    except Exception as e:
        return {"ok": False, "detail": "安装异常: %s" % e}
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip()[-400:]
        return {"ok": False, "detail": "pip 返回码 %s\n%s" % (r.returncode, tail)}
    # 安装后验证可导入（防"装了但导入失败"）
    try:
        import jieba  # noqa: F401
        return {"ok": True, "detail": "jieba 已自动安装成功"}
    except Exception as e:
        return {"ok": False, "detail": "pip 报告成功但导入失败: %s" % e}


def ensure_jieba(auto_install: bool = True, timeout: int = 180) -> dict:
    """
    确保 jieba 可用。

    Args:
        auto_install: jieba 缺失时是否尝试自动安装
        timeout: 安装超时秒数

    Returns:
        {"ok": bool, "mode": "full"|"degraded", "detail": str}
        ok=False 表示仍不可用（降级 n-gram），程序可继续运行。
    """
    if check_environment()["jieba"]:
        return {"ok": True, "mode": "full", "detail": "jieba 已可用"}
    if not auto_install:
        return {"ok": False, "mode": "degraded", "detail": "jieba 未安装"}
    res = try_install_jieba(timeout)
    if res["ok"]:
        return {"ok": True, "mode": "full", "detail": res["detail"]}
    return {"ok": False, "mode": "degraded", "detail": res["detail"]}


def human_report() -> str:
    """人类可读的环境报告文本（CLI 打印用）"""
    env = check_environment()
    lines = [
        f"Python {env['python']} · {env['os']} {env['machine']}",
        "jieba: " + ("可用 ✓" if env["jieba"] else "缺失 ✗（已降级 n-gram）"),
        "tkinter: " + ("可用 ✓" if env["tkinter"] else "缺失 ✗（GUI 无法启动）"),
    ]
    return "\n".join(lines)
